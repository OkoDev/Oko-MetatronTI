"""
radar_verdict.py — полный протокол по радару на реальных ценах (02.10.2026).

Повод: починка `vst_real_resolve.py` (30.09, `ca9727e`) перевернула радару знак на реальных ценах
(+0.85% → −0.12%/сделку): прежний «плюс» держался на выпадавших быстрых стопах (вход и стоп в одной свече).
Одного числа для решения мало — здесь полная нарезка по осям протокола + контрольная группа.

Метод:
  • исход каждой заявки радара (`simulated_trades.source_router='radar'`, с 03.07) переигран по ценам:
    до 15.09 — минутки Binance (`C:/oko_data/history/1m`), после — 3m BingX из хранилища Сферы 1.
    🔑 Источники сверены на пересечении 30.08–15.09: 37/37 исходов совпали, средние −2.16% против −2.16%.
  • правило: лимит по entry в окне TTL 30 мин (вход проверяется РАНЬШЕ стопа — цена непрерывна),
    затем стоп/цель по касанию со свечи филла, стоп приоритетнее; выход по времени через 24 ч по close.
    Косты 0.10%. TSL/BE не моделируются — это мера ГЕОМЕТРИИ сигнала (как `vst_real_resolve`).
  • КОНТРОЛЬ (закон проекта): та же монета, случайный момент ±30 дней, ТА ЖЕ геометрия в процентах
    (лимит на том же относительном расстоянии от цены, стоп и цель — от лимита), то же окно. ×5 на заявку.
  • оси нарезки: сторона · месяц · тип сетапа · grade · wave_leg (из `radar_orders`) · размер стопа ·
    охват монет · хрупкость (сумма без верхних 10%).

    python scripts/radar_verdict.py            (Python312: нужен pyarrow)
"""
from __future__ import annotations

import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.infra import market_store as ms            # noqa: E402

TTL_MIN, HOLD_H, COST = 30, 24.0, 0.10
P1M = Path("C:/oko_data/history/1m")
SWITCH = pd.Timestamp("2026-09-15")                   # дальше минуток Binance нет → 3m BingX
CTRL_N, CTRL_DAYS = 5, 30
_c1: dict = {}


PRE_H = 4   # запас истории ДО входа — нужен для волатильности (подбор контроля)


def bars(base: str, t0: pd.Timestamp) -> tuple[pd.DataFrame | None, int]:
    """(свечи с запасом PRE_H до t0, шаг в минутах). До 15.09 — 1m Binance, дальше — 3m BingX.
    🔴 Запас обязателен: без него ATR% перед входом не считается и подбор контроля молча отключается."""
    if t0 < SWITCH:
        if base not in _c1:
            f = P1M / f"{base}USDT.parquet"
            d0 = pd.read_parquet(f) if f.exists() else None
            if d0 is not None and getattr(d0.index, "tz", None) is not None:
                d0 = d0.copy(); d0.index = d0.index.tz_localize(None)   # часть паркетов 1m — tz-aware
            _c1[base] = d0
        d = _c1[base]
        return (None, 1) if d is None else (d[d.index >= t0 - pd.Timedelta(hours=PRE_H)], 1)
    d = ms.read_bars(base, "3m", since_ms=int((t0 - pd.Timedelta(hours=PRE_H)).timestamp() * 1000))
    if not len(d):
        return None, 3
    d = d.copy(); d.index = d.index.tz_localize(None)
    return d, 3


def resolve(w, t0, long_, e, sl, tp, step_min) -> tuple[str, float | None]:
    if w is None or len(w) == 0:
        return "нет данных", None
    w = w[w.index >= t0]
    if len(w) == 0 or w.index[0] > t0 + pd.Timedelta(minutes=2 * step_min):
        return "нет данных", None
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    n_ttl = max(1, int(TTL_MIN / step_min)); fill = None
    for j in range(min(n_ttl, len(w))):
        if (lo[j] <= e) if long_ else (hi[j] >= e):
            fill = j; break
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return "стоп до филла", None
    if fill is None:
        return "нет филла", None
    n_hold = int(HOLD_H * 60 / step_min)
    for j in range(fill, min(fill + 1 + n_hold, len(w))):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return "SL", ((sl - e) / e * 100) * (1 if long_ else -1) - COST
        if (hi[j] >= tp) if long_ else (lo[j] <= tp):
            return "TP", ((tp - e) / e * 100) * (1 if long_ else -1) - COST
    j = min(fill + n_hold, len(w) - 1)
    if w.index[j] > pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(minutes=30):
        return "открыта", None                        # удержание ещё не истекло — не судим
    return "время", ((cl[j] - e) / e * 100) * (1 if long_ else -1) - COST


def atr_pct(w, t, step) -> float | None:
    """Волатильность перед входом: средний размах 12 баров в % от цены."""
    pre = w[w.index <= t]
    if len(pre) < 14:
        return None
    return float((pre.high - pre.low).tail(12).mean() / pre.close.values[-1] * 100)


def control(base, t0, long_, px, e, sl, tp, rnd, atr0=None, tol=0.25, tries=60) -> list[float]:
    """Контроль: та же монета/сторона/геометрия в %, случайный момент ±CTRL_DAYS.

    🔴 02.10: добавлен ПОДБОР ПО ВОЛАТИЛЬНОСТИ. Без него контроль попадал в вчетверо более
    спокойный рынок (медиана ATR% 0.17 против 0.76 у радара: он входит после резкого движения) —
    при геометрии, заданной в процентах, это меняет шансы дойти и до стопа, и до цели.
    `atr0=None` → старое поведение (контроль без подбора), чтобы сравнить оба.
    """
    d_e, d_sl, d_tp = (e - px) / px, (sl - e) / e, (tp - e) / e
    out, n = [], 0
    for _ in range(tries):
        if n >= CTRL_N:
            break
        tr = t0 + pd.Timedelta(days=rnd.uniform(-CTRL_DAYS, CTRL_DAYS))
        if tr > pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(hours=HOLD_H + 2):
            continue
        w, step = bars(base, tr)
        if w is None or len(w) == 0:
            continue
        w0 = w[w.index >= tr]
        if len(w0) == 0:
            continue
        if atr0:
            a = atr_pct(w, tr, step)
            if a is None or not (atr0 * (1 - tol) <= a <= atr0 * (1 + tol)):
                continue                                   # не похоже по волатильности — другой момент
        p = float(w0.close.values[0])
        r, pnl = resolve(w, tr, long_, p * (1 + d_e), p * (1 + d_e) * (1 + d_sl), p * (1 + d_e) * (1 + d_tp), step)
        n += 1
        if pnl is not None:
            out.append(pnl)
    return out


def stats(xs: list[float]) -> dict | None:
    n = len(xs)
    if n == 0:
        return None
    s = sorted(xs)
    w = sum(x for x in xs if x > 0); l = -sum(x for x in xs if x < 0)
    k = max(1, n // 10)
    return {"n": n, "wr": sum(x > 0 for x in xs) / n * 100, "ср": sum(xs) / n, "мед": s[n // 2],
            "PF": (w / l) if l else float("inf"), "сумма": sum(xs), "безтоп10": sum(sorted(xs, reverse=True)[k:])}


def line(st: dict | None) -> str:
    if not st:
        return "—"
    return (f"n={st['n']:4d} WR={st['wr']:3.0f}% ср={st['ср']:+6.2f} мед={st['мед']:+6.2f} "
            f"PF={st['PF']:4.2f} Σ={st['сумма']:+8.0f} безтоп10%={st['безтоп10']:+8.0f}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rnd = random.Random(17)
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    rows = db.execute("""SELECT id, symbol, direction, signal_type, entry_price, COALESCE(original_sl, stop_loss),
                         take_profit, created_at, status, execution_mode, features_json
                         FROM simulated_trades WHERE source_router='radar' AND entry_price>0 AND take_profit>0
                         ORDER BY created_at""").fetchall()
    # wave_leg и grade — из журнала радара по (монета, радарное ts)
    rdb = sqlite3.connect(f"file:{ROOT / 'oko_feed' / 'external_data.db'}?mode=ro", uri=True, timeout=20)
    # 🔴 в radar_orders монета БЕЗ суффикса ('SUPER'), в сделках — 'SUPER/USDT:USDT'
    leg = {(s, int(ts)): (wl, g) for ts, s, wl, g in
           rdb.execute("SELECT ts, symbol, wave_leg, grade FROM radar_orders")}

    print(f"ИНВЕНТАРИЗАЦИЯ: заявок радара {len(rows)}; окно "
          f"{rows[0][7][:10]} → {rows[-1][7][:10]}; цены: до 15.09 — 1m Binance, после — 3m BingX "
          f"(источники сверены: 37/37 исходов, медиана разницы 0.00 п.п.)")

    import json
    R = []
    for (tid, sym, side, stype, e, sl, tp, ca, status, mode, fj) in rows:
        t0 = pd.Timestamp(str(ca).replace("T", " ")[:19])
        base, long_ = ms.base_of(sym), (side or "").upper() == "LONG"
        w, step = bars(base, t0)
        r, pnl = resolve(w, t0, long_, float(e), float(sl), float(tp), step)
        try:
            f = json.loads(fj or "{}")
        except Exception:
            f = {}
        rts = int(f.get("radar_ts") or 0)
        wl, grade = leg.get((base, rts), (None, f.get("radar_grade")))
        px = None
        if w is not None and len(w):
            w0 = w[w.index <= t0]
            px = float(w0.close.values[-1]) if len(w0) else None
        a0 = atr_pct(w, t0, step) if (w is not None and len(w)) else None
        R.append(dict(id=tid, atr0=a0, sym=base, side="LONG" if long_ else "SHORT", stype=stype, t0=t0,
                      month=str(ca)[:7], real=r, pnl=pnl, stop_pct=abs(e - sl) / e * 100,
                      wl=wl, grade=grade or f.get("radar_grade"), mode=mode, px=px,
                      e=float(e), sl=float(sl), tp=float(tp), long_=long_))
    judged = [r for r in R if r["pnl"] is not None]
    print(f"\nисходы: " + " · ".join(f"{k} {v}" for k, v in
          sorted(((k, sum(1 for r in R if r["real"] == k)) for k in {x['real'] for x in R}), key=lambda x: -x[1])))
    print(f"судимых (закрытых на рынке): {len(judged)}\n")
    print("■ БАЗА (все заявки радара):      " + line(stats([r["pnl"] for r in judged])))

    # контроль: без подбора (как было) и с подбором по волатильности (честный)
    ctrl, ctrl_m = [], []
    for r in judged:
        if not r["px"]:
            continue
        ctrl += control(r["sym"], r["t0"], r["long_"], r["px"], r["e"], r["sl"], r["tp"], rnd)
        ctrl_m += control(r["sym"], r["t0"], r["long_"], r["px"], r["e"], r["sl"], r["tp"], rnd,
                          atr0=r.get("atr0"))
    print("■ КОНТРОЛЬ случайный момент:     " + line(stats(ctrl)))
    print("■ КОНТРОЛЬ + та же волатильность:" + line(stats(ctrl_m)))
    b = stats([r["pnl"] for r in judged])
    sig = [r["pnl"] for r in judged]
    for nm, cc, arr in (("случайный момент", stats(ctrl), ctrl),
                        ("та же волатильность", stats(ctrl_m), ctrl_m)):
        if not (b and cc):
            continue
        # бутстрап разницы средних (закон о контрольной группе требует интервал, а не точку)
        d = []
        for _ in range(2000):
            a = sum(rnd.choice(sig) for _ in range(len(sig))) / len(sig)
            c2 = sum(rnd.choice(arr) for _ in range(len(arr))) / len(arr)
            d.append(a - c2)
        d.sort()
        lo, hi = d[int(0.025 * len(d))], d[int(0.975 * len(d))]
        print(f"   Δ сигнал − контроль [{nm}]: {b['ср'] - cc['ср']:+.2f} п.п./сделку "
              f"(95% [{lo:+.2f}; {hi:+.2f}]) · по медиане {b['мед'] - cc['мед']:+.2f} · "
              f"PF {b['PF']:.2f} против {cc['PF']:.2f}")

    axes = [("сторона", lambda r: r["side"]), ("месяц", lambda r: r["month"]),
            ("тип сетапа", lambda r: r["stype"]), ("grade", lambda r: str(r["grade"])),
            ("wave_leg", lambda r: "нет" if r["wl"] is None else ("leg≥3" if r["wl"] >= 3 else f"leg={r['wl']}")),
            ("стоп", lambda r: "<1.5%" if r["stop_pct"] < 1.5 else "1.5-3%" if r["stop_pct"] < 3
             else "3-5%" if r["stop_pct"] < 5 else "≥5%"),
            ("режим", lambda r: r["mode"])]
    for nm, f in axes:
        g = defaultdict(list)
        for r in judged:
            g[f(r)].append(r["pnl"])
        print(f"\n— {nm}:")
        for k in sorted(g, key=lambda k: -len(g[k])):
            print(f"    {str(k):12} " + line(stats(g[k])))

    by = defaultdict(list)
    for r in judged:
        by[r["sym"]].append(r["pnl"])
    pos = sum(1 for v in by.values() if sum(v) > 0)
    print(f"\n— охват монет: {len(by)} · в плюсе {pos} ({pos / len(by) * 100:.0f}%)")
    pd.DataFrame([{k: v for k, v in r.items() if k != "t0"} | {"t0": str(r["t0"])} for r in R]).to_csv(
        ROOT / "obsidian" / "Research" / "2026-10-02-radar-verdict-rows.csv", index=False, encoding="utf-8")


if __name__ == "__main__":
    main()
