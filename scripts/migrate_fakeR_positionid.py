#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_fakeR_positionid.py — пересчёт fake-R на боевой БД (19.06.2026).

КОРЕНЬ (доказано на бирже, [[bug_phantom_exit_resolve]]): _resolve_exit терял orderId-якорь
(None у STG / протух после cancel+replace SL у HMSTR) → fallback symbol+side хватал ЧУЖОЙ
старый close-ордер → exit_price вне диапазона жизни сделки → R=323 при реальном убытке −1.

Эта миграция чинит уже записанные exit_price/R_multiple ДВУМЯ путями:

  Tier 1 (--with-exchange): истинный exit по positionID из allOrders.
      Для сделки берём entry orderId (exchange_order_id) → находим её positionID →
      берём close-side FILLED ордер ТОЙ ЖЕ позиции (вход+SL+TP+перевыставленные = один
      positionID) → его avgPrice = настоящий exit. Точнее всего, НО:
        - allOrders отдаёт лишь ~limit последних ордеров по символу → старые сделки вне окна;
        - жжёт API (конкуренция с живым ботом по IP-бюджету) → ВЫКЛ по умолчанию.

  Tier 2 (по умолчанию, оффлайн): clamp exit в реальный диапазон [min_price, max_price],
      который сделка прошла по тикам. Фантом = exit ВНЕ этого диапазона (это и есть баг) →
      clamp гарантирует R ≤ MFE. Это тот же инвариант, что в trade_simulator.close_trade,
      но применённый к историческим строкам, где он не сработал (level-3 clamp слеп при
      MFE=None ИЛИ был внесён уже после записи строки).

  Tier 3: min_price/max_price = NULL (MFE не затрекан) → пересчитать нельзя, помечаем.

R-математика — РОВНО как в trade_simulator.close_trade (core.trading.r_math):
  one_r = |entry - original_sl| (fallback sl); R = compute_r(dir, entry, exit, one_r);
  clamp_r_smart по sl_dist (раннеры дышат, артефакт sl_dist≈0 клампится). НАМЕРЕННО без
  потолка 50R — легитимные раннеры целы [[milestone_clamp50_runners_proven]].
  Строки с частичным TP1 (tp1_hit_at) пропускаем (бленд-формула) — их мало, логируем.

БЕЗОПАСНОСТЬ:
  * dry-run по умолчанию — только печатает распределение avgR до/после, НИЧЕГО не пишет.
  * --commit делает БЭКАП (subscriptions.db.fakeR-bak-YYYYMMDD-HHMMSS) ПЕРЕД записью.
  * Бот лучше остановить перед --commit (SQLite write-lock; иначе busy_timeout).

Запуск:
  # dry-run (оффлайн, безопасно, ничего не пишет):
  python scripts/migrate_fakeR_positionid.py
  # dry-run с биржевой сверкой по positionID (жжёт API — остановить бота / тихий час):
  python scripts/migrate_fakeR_positionid.py --with-exchange
  # применить (бэкап автоматически):
  python scripts/migrate_fakeR_positionid.py --commit
  python scripts/migrate_fakeR_positionid.py --commit --with-exchange
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB_DEFAULT = r"e:/MTF BOT/CURSOR/crypto_volume_bot/subscriptions.db"

from core.trading.r_math import compute_one_r, compute_r, clamp_r_smart  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _ensure_position_id_column(conn: sqlite3.Connection) -> None:
    """Идемпотентно добавляет колонку position_id (как сделает бот при рестарте)."""
    if not _has_column(conn, "simulated_trades", "position_id"):
        conn.execute("ALTER TABLE simulated_trades ADD COLUMN position_id TEXT")
        conn.commit()
        print("[SCHEMA] добавлена колонка simulated_trades.position_id")


def _ensure_quarantine_column(conn: sqlite3.Connection) -> None:
    """Идемпотентно добавляет колонку fakeR_quarantine (как сделает бот при рестарте)."""
    if not _has_column(conn, "simulated_trades", "fakeR_quarantine"):
        conn.execute("ALTER TABLE simulated_trades ADD COLUMN fakeR_quarantine INTEGER DEFAULT 0")
        conn.commit()
        print("[SCHEMA] добавлена колонка simulated_trades.fakeR_quarantine")


def _select_closed_trades(conn: sqlite3.Connection, since: str | None):
    """Биржевые закрытые сделки (VST/LIVE). SIM (без биржевой позиции) не трогаем."""
    # колонки может ещё не быть (бот не рестартился) → подставляем NULL для dry-run
    _pid_sel = "position_id" if _has_column(conn, "simulated_trades", "position_id") else "NULL AS position_id"
    q = (
        "SELECT id, symbol, direction, status, entry_price, exit_price, stop_loss, "
        "       original_sl, take_profit, tp1_price, tp1_hit_at, max_price, min_price, "
        f"      R_multiple, max_R_possible, qty, {_pid_sel}, exchange_order_id, account_id "
        "FROM simulated_trades "
        "WHERE status IN ('TP','SL','TSL','EXPIRED') "
        "  AND (execution_mode != 'SIM' OR "
        "       (exchange_order_id IS NOT NULL AND exchange_order_id != '' AND exchange_order_id != 'SIM')) "
        "  AND exit_price IS NOT NULL "
    )
    params: list = []
    if since:
        q += " AND created_at >= ? "
        params.append(since)
    q += " ORDER BY id ASC"
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def _recompute(direction: str, entry: float, exit_price: float,
               original_sl, stop_loss, max_price, min_price):
    """Возвращает (r_multiple, profit_pct, max_R_possible) РОВНО как close_trade (non-TP1 ветка)."""
    dir_up = str(direction).upper()
    one_r, _src = compute_one_r(entry, original_sl, fallback_sl=stop_loss)

    if dir_up == "LONG":
        profit_pct = (exit_price - entry) / entry * 100.0
    else:
        profit_pct = (entry - exit_price) / entry * 100.0

    r_multiple = compute_r(dir_up, entry, exit_price, one_r) if one_r else None
    if r_multiple is not None:
        r_multiple = round(clamp_r_smart(r_multiple, entry, one_r), 3)

    max_R_possible = None
    if one_r and one_r > 0:
        _peak = max_price if dir_up == "LONG" else min_price
        if _peak:
            _mfe = compute_r(dir_up, entry, _peak, one_r)
            max_R_possible = round(clamp_r_smart(_mfe, entry, one_r), 3) if _mfe is not None else None
    return r_multiple, round(profit_pct, 4), max_R_possible


def _clamp_exit(exit_price, max_price, min_price):
    """Инвариант close_trade: exit в [min,max]. Возвращает (new_exit, clamped?)."""
    if exit_price and max_price and min_price and max_price >= min_price:
        if exit_price > max_price or exit_price < min_price:
            return min(max(float(exit_price), float(min_price)), float(max_price)), True
    return exit_price, False


# ─────────────────────────────────────────────────────────────────────────────
async def _build_exchange_exits(rows, limit_orders: int):
    """Tier 1: {trade_id: (real_exit_price, status)} по positionID из allOrders.

    Группируем по символу+аккаунту, тянем allOrders раз на символ, мапим:
      entry orderId (exchange_order_id) → positionID → close-side FILLED той же позиции.
    """
    from dotenv import load_dotenv
    load_dotenv()
    from core.infra.config_loader import config
    from core.exchange.order_manager import OrderManager

    _TYPE_TO_STATUS = {
        "STOP_MARKET": "SL", "STOP": "SL",
        "TAKE_PROFIT_MARKET": "TP", "TAKE_PROFIT": "TP",
        "TRAILING_STOP_MARKET": "TSL",
    }

    om = OrderManager(config)
    if not om.is_live():
        print("[!] --with-exchange требует vst/live режим (config trading.execution_mode) — пропуск Tier 1")
        return {}
    router = om._get_router() if getattr(om, "_multiacct", False) else None

    async def client_for(acc):
        if router is not None and acc is not None:
            cli = router.client_for_account(acc)
            if cli is not None:
                try:
                    await cli.sync_time()
                except Exception:
                    pass
                return cli
        return await om._get_client_synced()

    # уникальные (symbol, account) с кэшем allOrders
    by_symacc: dict[tuple, list] = {}
    for r in rows:
        by_symacc.setdefault((r["symbol"], r["account_id"]), []).append(r)

    out: dict[int, tuple] = {}
    _n_syms = len(by_symacc)
    for _i, ((sym, acc), group) in enumerate(by_symacc.items()):
        await asyncio.sleep(0.3)   # throttle: сотни символов × allOrders → rate-limit BingX
        if _i % 25 == 0:
            print(f"  Tier1 progress: {_i}/{_n_syms} символов…")
        try:
            cli = await client_for(acc)
            filled = await cli.get_filled_orders(sym, limit=limit_orders)
        except Exception as e:
            print(f"  [!] {sym} acc={acc} allOrders err: {e}")
            continue
        by_oid = {str(o.get("orderId")): o for o in filled}

        def _pid_of(o):
            return str(o.get("positionID") or o.get("positionId") or "")

        for r in group:
            entry_oid = str(r["exchange_order_id"] or "")
            # positionID: из колонки (новый захват) ИЛИ из entry-ордера в истории
            pid = str(r["position_id"] or "")
            if not pid and entry_oid in by_oid:
                pid = _pid_of(by_oid[entry_oid])
            if not pid:
                continue  # вне окна allOrders и не захвачен — Tier 2
            close_side = "SELL" if str(r["direction"]).upper() == "LONG" else "BUY"
            cands = [o for o in filled
                     if _pid_of(o) == pid and str(o.get("side", "")).upper() == close_side]
            if not cands:
                continue
            o = max(cands, key=lambda x: int(x.get("updateTime") or x.get("time") or 0))
            avg = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
            if not avg:
                continue
            status = _TYPE_TO_STATUS.get(o.get("type", ""), r["status"])
            out[r["id"]] = (float(avg), status)
    return out


# ─────────────────────────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--commit", action="store_true", help="применить (иначе dry-run)")
    ap.add_argument("--with-exchange", action="store_true",
                    help="Tier 1: истинный exit по positionID из allOrders (жжёт API)")
    ap.add_argument("--limit-orders", type=int, default=500)
    ap.add_argument("--since", default=None, help="ISO cutoff created_at (например 2026-06-01)")
    ap.add_argument("--quarantine-r", type=float, default=10.0,
                    help="Tier3 (MFE=None) с R > порога и нерезолвимые → R/profit=NULL + пометка")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[!] БД не найдена: {args.db}")
        return

    conn = sqlite3.connect(args.db, timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    rows = _select_closed_trades(conn, args.since)
    print(f"Биржевых закрытых сделок к проверке: {len(rows)}")

    exch_exits: dict[int, tuple] = {}
    if args.with_exchange:
        print(f"Tier 1: тяну allOrders (limit={args.limit_orders}) по символам…")
        exch_exits = await _build_exchange_exits(rows, args.limit_orders)
        print(f"Tier 1: положение exit'ов по positionID найдено для {len(exch_exits)} сделок")

    updates: list[tuple] = []        # (exit, R, profit_pct, max_R, status, pid, tier, id)
    quarantines: list[tuple] = []    # (id, symbol, old_R) — R/profit→NULL, пометка
    t1 = t2 = t3 = skip_tp1 = unchanged = 0
    old_sum = new_sum = 0.0
    old_n = new_n = 0

    for r in rows:
        tid = r["id"]
        entry = float(r["entry_price"] or 0)
        if entry <= 0:
            continue
        old_R = r["R_multiple"]
        if old_R is not None:
            old_sum += float(old_R); old_n += 1

        if r["tp1_hit_at"] and r["tp1_price"]:
            skip_tp1 += 1
            continue  # бленд-формула TP1 — не трогаем (редко)

        new_exit = float(r["exit_price"])
        new_status = r["status"]
        tier = None

        if tid in exch_exits:                       # Tier 1
            new_exit, new_status = exch_exits[tid]
            tier = 1
        else:                                        # Tier 2: clamp в [min,max]
            clamped_exit, did = _clamp_exit(float(r["exit_price"]), r["max_price"], r["min_price"])
            if did:
                new_exit = clamped_exit
                tier = 2
            elif r["max_price"] is None or r["min_price"] is None:
                tier = 3                              # MFE=None — пересчитать нельзя

        if tier is None:
            unchanged += 1
            if old_R is not None:
                new_sum += float(old_R); new_n += 1
            continue
        if tier == 3:
            t3 += 1
            # КАРАНТИН (решение юзера 19.06): нерезолвимый MFE=None фантом-монстр R>порога →
            # R/profit=NULL + пометка. Нет [min,max] (clamp) и нет ордера в окне allOrders
            # (Tier1) → восстановить exit нельзя; держать R=323 = травить веса/метрики.
            if old_R is not None and abs(float(old_R)) > args.quarantine_r:
                quarantines.append((tid, r["symbol"], float(old_R)))
                # из new_sum ИСКЛЮЧАЕМ (станет NULL) — честное «не знаем», не 0
                print(f"  #{tid} {r['symbol']:14} {r['direction']:5} КАРАНТИН: "
                      f"R={float(old_R):.1f} MFE=None → NULL")
            elif old_R is not None:
                new_sum += float(old_R); new_n += 1   # правдоподобный малый R — оставляем
            continue

        # Tier 1/2 — пересчёт R/profit/MFE по новому exit (+ повторный clamp для Tier 1)
        new_exit, _ = _clamp_exit(new_exit, r["max_price"], r["min_price"])
        new_R, new_profit, new_maxR = _recompute(
            r["direction"], entry, new_exit, r["original_sl"], r["stop_loss"],
            r["max_price"], r["min_price"])
        if new_R is not None:
            new_sum += new_R; new_n += 1
        if tier == 1:
            t1 += 1
        else:
            t2 += 1
        updates.append((new_exit, new_R, new_profit, new_maxR, new_status,
                        str(r["position_id"] or ""), tier, tid))

        if (tier == 1 or abs((new_R or 0) - (float(old_R) if old_R is not None else 0)) > 1.0):
            print(f"  #{tid} {r['symbol']:14} {r['direction']:5} T{tier}: "
                  f"exit {float(r['exit_price']):.6g}→{new_exit:.6g}  "
                  f"R {('%.2f'%old_R) if old_R is not None else 'None':>7}→{('%.2f'%new_R) if new_R is not None else 'None':>7}  "
                  f"MFE={r['max_R_possible']}")

    _q_sum = sum(q[2] for q in quarantines)
    print("\n" + "=" * 78)
    print(f"Tier1 (positionID exit): {t1}   Tier2 (clamp [min,max]): {t2}   Tier3 (MFE=None): {t3}")
    print(f"  из Tier3 → КАРАНТИН (R>{args.quarantine_r:g}, R/profit→NULL): {len(quarantines)} "
          f"(сумма яда {_q_sum:+.1f}R исключена)")
    print(f"TP1-бленд пропущено: {skip_tp1}   без изменений: {unchanged}")
    if old_n:
        print(f"avgR ДО:    {old_sum/old_n:+.4f}  (n={old_n})")
    if new_n:
        print(f"avgR ПОСЛЕ: {new_sum/new_n:+.4f}  (n={new_n}, карантин исключён)")
    print(f"Строк к пересчёту: {len(updates)}   к карантину: {len(quarantines)}")

    if not args.commit:
        print("\n[DRY-RUN] ничего не записано. Для применения: --commit (бэкап будет автоматически).")
        conn.close()
        return

    # ── COMMIT: бэкап → запись ──────────────────────────────────────────────
    conn.close()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{args.db}.fakeR-bak-{ts}"
    shutil.copy2(args.db, backup)
    print(f"\n[BACKUP] {backup}")

    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    _ensure_position_id_column(conn)          # backfill position_id требует колонку
    _ensure_quarantine_column(conn)           # пометка карантина
    cur = conn.cursor()
    written = 0
    for (new_exit, new_R, new_profit, new_maxR, new_status, pid, tier, tid) in updates:
        try:
            cur.execute(
                "UPDATE simulated_trades SET exit_price=?, R_multiple=?, profit_pct=?, "
                "max_R_possible=?, status=? WHERE id=?",
                (new_exit, new_R, new_profit, new_maxR, new_status, tid),
            )
            # backfill position_id если резолвился через биржу (Tier 1) и колонка пуста
            if tier == 1 and pid:
                cur.execute("UPDATE simulated_trades SET position_id=? WHERE id=? AND "
                            "(position_id IS NULL OR position_id='')", (pid, tid))
            written += 1
        except Exception as e:
            print(f"  [!] update #{tid}: {e}")
    quar = 0
    for (tid, _sym, _oldR) in quarantines:
        try:
            cur.execute(
                "UPDATE simulated_trades SET R_multiple=NULL, profit_pct=NULL, "
                "fakeR_quarantine=1 WHERE id=?", (tid,),
            )
            quar += 1
        except Exception as e:
            print(f"  [!] quarantine #{tid}: {e}")
    conn.commit()
    conn.close()
    print(f"[COMMIT] пересчитано {written} строк, карантин {quar} строк. Бэкап: {backup}")
    print("⚠️ Перезапусти бота/дашборд, чтобы метрики/веса пересчитались на честном R.")


if __name__ == "__main__":
    asyncio.run(main())
