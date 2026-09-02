"""ЧЕСТНЫЙ РЕ-ТЕСТ atr_change 4h SHORT + недельная S2 (03.07, методология после look-ahead уроков).

Оригинал (memory atr_change_pivot_short_thin_edge): 4h SHORT при ATRTrend-флипе вниз + close<недельный
PP, выход на недельной S2 → mean +0.248%/тр, 4/5 лет+. Проверяем той же честной рамкой:
  • вход по CLOSE 4h-бара флипа (сигнальный ТФ = торговый → intrabar-проблемы НЕТ)
  • недельные пивоты ПРОШЛОЙ недели (shift 1, каузально)
  • выход: касание S2 (тейк) ИЛИ обратный флип ATRTrend (по close) — вариант B с SL за swing-high
  • % net, costs 0.2 (+вариант 0.1 maker-lean), по годам 2022-2026
Запуск: python scripts/test_atr_s2.py
"""
from __future__ import annotations
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from core.calculators.combinator_core import atr_supertrend

COST_PCT = 0.2
DB = "ohlcv_cache.db"
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI", "SUI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA",
           "GRT", "ALGO", "EGLD", "SAND", "MANA", "CHZ", "ENJ", "KAVA", "ZIL", "IOTA"]
VARIANTS = ["A_s2_or_flip", "B_with_sl"]


def load4h(conn, sym):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe='4h' ORDER BY time"""
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT",))
    if len(df) < 600:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def weekly_pivots(d4h):
    wk = d4h.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (wk["high"] + wk["low"] + wk["close"]) / 3
    s1 = 2 * pp - wk["high"]
    s2 = pp - (wk["high"] - wk["low"])
    return pd.DataFrame({"PP": pp, "S1": s1, "S2": s2}).shift(1)


def run(d4h, sym=""):
    # 🔴 136.E: в запись добавлены `sym` и `stop` — без них НЕВОЗМОЖНЫ обязательные
    # срезы протокола вердикта (охват монет, хрупкость, корзины стопа, кластер).
    # Логика входа/выхода НЕ тронута.
    st = atr_supertrend(d4h)
    piv = weekly_pivots(d4h)
    piv_idx = piv.index
    res = {v: [] for v in VARIANTS}
    pos = {v: None for v in VARIANTS}
    highs = d4h["high"].values; lows = d4h["low"].values; closes = d4h["close"].values
    idx = d4h.index
    for i in range(60, len(d4h)):
        t = idx[i]
        c = float(closes[i]); hi = float(highs[i]); lo = float(lows[i])
        # пивоты активной недели (прошлой недели значения)
        pi = piv_idx.searchsorted(t)
        if pi >= len(piv_idx):
            pi = len(piv_idx) - 1
        row = piv.iloc[pi] if pi < len(piv) else None
        if row is None or pd.isna(row["PP"]):
            continue
        PP, S2 = float(row["PP"]), float(row["S2"])
        for v in VARIANTS:
            p = pos[v]
            if not p:
                continue
            ex = None
            # SHORT: тейк на S2 (intrabar касание), SL (вариант B), обратный флип (по close)
            if lo <= p["s2"]:
                ex = p["s2"]
            elif v == "B_with_sl" and hi >= p["sl"]:
                ex = p["sl"]
            elif st[i] > 0:                       # обратный флип вверх → выход по close
                ex = c
            if ex is not None:
                gross = (p["entry"] - ex) / p["entry"] * 100
                res[v].append({"net": gross - COST_PCT, "gross": gross, "ts": p["ts"],
                               "sym": sym, "stop": (p["sl"] - p["entry"]) / p["entry"] * 100})
                pos[v] = None
        # ВХОД: флип вниз на этом баре + close<PP
        if st[i] < 0 and st[i - 1] > 0 and c < PP:
            entry = c
            s2_lvl = S2
            if s2_lvl >= entry:                    # S2 выше цены — цель невалидна
                continue
            sl = float(highs[max(0, i - 12):i + 1].max()) * 1.0015   # за swing-high 12 баров (структура)
            for v in VARIANTS:
                if pos[v] is None:
                    if v == "B_with_sl" and (sl <= entry or (sl - entry) / entry > 0.10):
                        continue
                    pos[v] = {"entry": entry, "s2": s2_lvl, "sl": sl, "ts": t}
    return res


def main():
    import argparse
    import statistics as s
    # 🔴 136.E (01.09.2026): SYMBOLS выше — 38 ВРУЧНУЮ ВЫБРАННЫХ крупных монет,
    # все выжившие. Это самая узкая вселенная среди боевых источников; на выборке
    # такого рода вердикт переворачивался дважды ([[law_sample_representativeness]]).
    # `--core` заменяет её на балансированную панель (монета есть на ВСЁМ окне).
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="store_true", help="ядро вместо списка SYMBOLS")
    a = ap.parse_args()
    if a.core:
        from scripts.research_harness import core_universe
        symbols = [x.split("/")[0] for x in core_universe("4h", since="2023-01-01")]
        print(f"ВСЕЛЕННАЯ: ЯДРО, {len(symbols)} монет (балансированная панель)")
    else:
        symbols = SYMBOLS
        print(f"ВСЕЛЕННАЯ: список SYMBOLS, {len(symbols)} монет (выжившие, не балансировано)")
    conn = sqlite3.connect(DB)
    agg = {v: [] for v in VARIANTS}
    done = 0
    for sym in symbols:
        d4h = load4h(conn, sym)
        if d4h is None:
            continue
        r = run(d4h, sym)
        for v in agg:
            agg[v].extend(r[v])
        done += 1
    print(f"символов: {done}")
    print(f"{'вариант':14} {'n':>5} {'WR':>4} {'mean%':>8} {'med%':>8} {'sum%':>9}")
    for v in VARIANTS:
        tr = agg[v]
        if not tr:
            print(f"{v:14} n=0"); continue
        nets = [x["net"] for x in tr]
        wr = 100 * sum(1 for x in tr if x["net"] > 0) / len(tr)
        print(f"{v:14} {len(tr):>5} {wr:>3.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+8.1f}")
    print("\nПО ГОДАМ (A_s2_or_flip):")
    tr = agg["A_s2_or_flip"]
    for yr in [2022, 2023, 2024, 2025, 2026]:
        part = [x for x in tr if x["ts"].year == yr]
        if len(part) < 10:
            continue
        nets = [x["net"] for x in part]
        wr = 100 * sum(1 for x in part if x["net"] > 0) / len(part)
        print(f"  {yr}: n={len(part):4} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%")
    # ── 🔴 136.E: ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ ПРОТОКОЛА (боевой вариант B_with_sl) ──────
    import collections
    B = agg["B_with_sl"]
    if B and "sym" in B[0]:
        def _st(rows, cost=COST_PCT):
            if len(rows) < 30:
                return None
            n = np.array([x["gross"] - cost for x in rows])
            w, gl = n[n > 0], -n[n <= 0].sum()
            srt = np.sort(n)[::-1]
            return dict(n=len(n), wr=100 * (n > 0).mean(),
                        pf=(w.sum() / gl if gl else 0.0), avg=n.mean(),
                        bt=srt[int(len(srt) * 0.1):].sum())

        def _line(nm, rows):
            s_ = _st(rows)
            if not s_:
                print(f"  {nm:<26} n={len(rows)} — мало"); return
            print(f"  {nm:<26} n={s_['n']:>6} WR {s_['wr']:>4.1f}% PF {s_['pf']:>5.2f} "
                  f"ср {s_['avg']:>+6.3f}% безтоп10% {s_['bt']:>+8.0f}")

        print(f"\n{'='*94}\nОБЯЗАТЕЛЬНЫЕ СРЕЗЫ · B_with_sl (боевой) · косты {COST_PCT}%\n{'='*94}")
        _line("ВСЁ", B)
        print("\nРАЗМЕР СТОПА:")
        for lo, hi in ((0, 2), (2, 4), (4, 6), (6, 11)):
            _line(f"  стоп {lo}-{hi}%", [x for x in B if lo <= x["stop"] < hi])
        print("\nОХВАТ МОНЕТ:")
        per = collections.defaultdict(float)
        for x in B:
            per[x["sym"]] += x["gross"] - COST_PCT
        vals = sorted(per.values(), reverse=True)
        print(f"  монет {len(per)} · в плюсе {sum(1 for v in vals if v > 0)} "
              f"({100 * sum(1 for v in vals if v > 0) / max(len(vals), 1):.0f}%) · "
              f"сумма {sum(vals):+.0f}% · без топ-3 {sum(vals[3:]):+.0f}% · "
              f"без топ-10% {sum(vals[int(len(vals) * 0.1):]):+.0f}%")
        print("\nКЛАСТЕР (≥2 монеты в один день):")
        by_day = collections.defaultdict(set)
        for x in B:
            by_day[x["ts"].date()].add(x["sym"])
        _line("  одиночка", [x for x in B if len(by_day[x["ts"].date()]) < 2])
        _line("  кластер ≥2", [x for x in B if len(by_day[x["ts"].date()]) >= 2])
        print("\nБОЕВЫЕ КОСТЫ (вход ЛИМИТНЫЙ → 0.35%, а не 0.2%):")
        _line("  при costs 0.35%", B)
        s35 = _st(B, 0.35)
        if s35:
            print(f"     → ср {s35['avg']:+.3f}%/сд · PF {s35['pf']:.2f} · "
                  f"безтоп10% {s35['bt']:+.0f}")

    # costs-чувствительность
    print("\nCosts-свип (A): ", end="")
    for cst in [0.1, 0.2, 0.3, 0.45]:
        nets = [x["gross"] - cst for x in tr]
        print(f"{cst}%→{s.mean(nets):+.3f}  ", end="")
    print()
    conn.close()


if __name__ == "__main__":
    main()
