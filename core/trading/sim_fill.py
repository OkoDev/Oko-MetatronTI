"""
sim_fill.py — исполнение SIM-лимиток по свечам Сферы 1 (30.09.2026).

🔴 Дефект, который лечим (замер `scripts/limit_fill_measure.py`): филл лимитки засчитывался ТОЛЬКО по позиции
на бирже (`radar_armed_loop._check_pending`), а у SIM позиции нет — заявка всегда доживала до TTL и снималась.
`impulse_fib_15m` на паузе: 0 филлов из 380, тогда как реальный рынок исполнил бы ~30%. SIM-строки
`simulated_trades` у LIMIT-источников не были форвардом; честный форвард жил только в тенях двух механик.

Здесь заявка судится по ЦЕНЕ, как в замере:
    касание entry в окне TTL              → OPEN (actual_entry_price = лимит, комиссии/проскальзывания нет)
    вход и стоп в одной свече             → OPEN (цена непрерывна: сначала вход, стоп отработает симулятор)
    стоп задет раньше входа               → CANCELLED (сделки не было)
    TTL истёк                             → CANCELLED

🔑 При нормальной геометрии «стоп раньше входа» недостижим: цена непрерывна и проходит вход первым
(стоп всегда ЗА входом). Ветка ловит вывернутую заявку — для лонга стоп выше входа. Поэтому в замере
`limit_fill_measure.py` исходы «стоп до филла» оказались артефактом порядка проверок, а не рынка.
Оговорка: при гэпе через вход мы считаем филл по лимиту, хотя биржа дала бы цену открытия (чуть лучше).

🔑 `sim_fill_at` в features — время филла. `TradeSimulator` ведёт открытую сделку по свечам ОТ НЕГО, а не от
`created_at`: иначе в счёт пошли бы бары до входа (для лимита на откате цена там с другой стороны — сделка
могла бы «закрыться» по цели, которой не было).

Источник свечей — хранилище Сферы 1 (`core/infra/market_store`): свои данные, биржу не трогаем.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TF_PRIMARY = "5m"      # точность филла; в хранилище с 29.08.2026
TF_FALLBACK = "15m"    # молодая монета / нет 5m


def _bars(base: str, tf: str, since: datetime) -> pd.DataFrame:
    from core.infra import market_store as ms
    return ms.read_bars(base, tf, since_ms=int(since.timestamp() * 1000))


def _ttl_hours(trade_mode: str, default_h: float = 12.0) -> float:
    try:
        from core.trading.source_registry import ttl_for
        return float(ttl_for(trade_mode, default_sec=default_h * 3600)) / 3600.0
    except Exception:                                   # noqa: BLE001
        return default_h


def _verdict(df: pd.DataFrame, t0: datetime, long_: bool, entry: float, sl: float,
             ttl_h: float, now: datetime) -> tuple[str, Optional[datetime]]:
    """('fill', время) · ('cancel', None) — стоп раньше входа или TTL · ('wait', None)."""
    deadline = t0 + timedelta(hours=ttl_h)
    w = df[(df.index >= t0) & (df.index <= deadline)]
    for ts, b in w.iterrows():
        hit_entry = (b.low <= entry) if long_ else (b.high >= entry)
        if hit_entry:
            return "fill", ts.to_pydatetime()
        hit_sl = (b.low <= sl) if long_ else (b.high >= sl)
        if hit_sl:
            return "cancel", None
    return ("cancel", None) if now >= deadline else ("wait", None)


def resolve_sim_pending(db_path: str, now: Optional[datetime] = None, limit: int = 200) -> dict:
    """Один проход по SIM-заявкам PENDING_ENTRY. Возвращает счётчики {'fill','cancel','wait','skip'}."""
    now = now or datetime.now(timezone.utc)
    out = {"fill": 0, "cancel": 0, "wait": 0, "skip": 0}
    with sqlite3.connect(db_path, timeout=10) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT id, symbol, direction, entry_price, COALESCE(original_sl, stop_loss) AS sl, "
            "created_at, features_json FROM simulated_trades WHERE status='PENDING_ENTRY' "
            "AND (exchange_order_id IS NULL OR exchange_order_id IN ('', 'SIM')) "
            "ORDER BY created_at LIMIT ?", (limit,))]
    if not rows:
        return out

    from core.infra.market_store import base_of
    for t in rows:
        try:
            entry, sl = float(t["entry_price"] or 0), float(t["sl"] or 0)
            if entry <= 0 or sl <= 0:
                out["skip"] += 1
                continue
            t0 = datetime.fromisoformat(str(t["created_at"]).replace("Z", "+00:00").replace("T", " "))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            feats = json.loads(t["features_json"] or "{}")
            long_ = (t["direction"] or "").upper() == "LONG"
            ttl_h = _ttl_hours(str(feats.get("trade_mode") or ""))
            base = base_of(t["symbol"])
            df = _bars(base, TF_PRIMARY, t0)
            if df.empty or df.index[0] > t0 + timedelta(minutes=10):
                df = _bars(base, TF_FALLBACK, t0)
            if df.empty:
                out["skip"] += 1
                continue
            verdict, fill_at = _verdict(df, t0, long_, entry, sl, ttl_h, now)
            if verdict == "wait":
                out["wait"] += 1
                continue
            with sqlite3.connect(db_path, timeout=10) as c:
                if verdict == "fill":
                    feats["sim_fill_at"] = fill_at.isoformat()
                    c.execute("UPDATE simulated_trades SET status='OPEN', actual_entry_price=?, "
                              "features_json=? WHERE id=? AND status='PENDING_ENTRY'",
                              (entry, json.dumps(feats, ensure_ascii=False), int(t["id"])))
                    logger.info("[SIM-FILL] #%s %s %s лимит %.6g исполнен на свече %s",
                                t["id"], t["symbol"], "LONG" if long_ else "SHORT", entry, fill_at)
                else:
                    c.execute("UPDATE simulated_trades SET status='CANCELLED', closed_at=? "
                              "WHERE id=? AND status='PENDING_ENTRY'",
                              (now.isoformat(), int(t["id"])))
                c.commit()
            out[verdict] += 1
        except Exception as e:                          # noqa: BLE001 — одна заявка не роняет проход
            out["skip"] += 1
            logger.debug("[SIM-FILL] #%s: %s", t.get("id"), e)
    return out
