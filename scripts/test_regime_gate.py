"""РЕЖИМ-ГЕЙТ (03.07, =REGIME-V2 через structure_trend): BTC-структура как переключатель SHORT on/off.

Доказано: SHORT-рецепт в медвежьем +0.81%/сделку, в бычьем −0.9% → нужен гейт. Кандидаты режима:
  R1_btc4h   — BTC structure_trend 4h == short → SHORT разрешён
  R2_btc1d   — BTC structure_trend 1d == short
  R3_btc_both— оба (1d И 4h) short
  R4_none    — без гейта (контроль)
Прогон SHORT-рецепта (1h OTE + 4h==short симв + возврат + SL 15m-слом + TP fib−1.0) на ohlcv_cache.db
по ЭПОХАМ: 2022 (медвежий год), 2023H1, 2023Q4-2024Q1 (бык), 2024Q4 (бык), 2025H2, 2026 (текущий).
Вопрос: гейт режет бычьи лоси, сохраняя медвежий профит? Мера % net. Запуск: python scripts/test_regime_gate.py
"""
from __future__ import annotations
import sys, sqlite3
import pandas as pd

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
DB = "ohlcv_cache.db"
EPOCHS = {"2022_BEAR": ("2022-02-01", "2022-11-30"),
          "2023H1": ("2023-01-01", "2023-06-30"),
          "2023Q4_BULL": ("2023-10-01", "2024-03-31"),
          "2024Q4_BULL": ("2024-09-01", "2025-01-31"),
          "2025H2": ("2025-07-01", "2025-12-31"),
          "2026_NOW": ("2026-02-01", "2026-05-31")}
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP"]
GATES = ["R1_btc4h", "R2_btc1d", "R3_btc_both", "R4_none"]


def load(conn, sym, tf, start, end, warm_days=40):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe=? AND time BETWEEN ? AND ? ORDER BY time"""
    t0 = int(pd.Timestamp(start).timestamp() * 1000) - 86400000 * warm_days
    t1 = int(pd.Timestamp(end).timestamp() * 1000)
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT", tf, t0, t1))
    if len(df) < 200:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def btc_regime_series(conn, start, end):
    """BTC 4h/1d(=ресемпл 4h) структура по барам 4h: {ts: (dir4h, dir1d)}. Каузально."""
    d4 = load(conn, "BTC", "4h", start, end, warm_days=120)
    if d4 is None:
        return None
    d1d = d4.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()
    out = {}
    for i in range(120, len(d4)):
        t = d4.index[i]
        s4 = structure_trend(d4.iloc[:i + 1], lookback=250)
        dsub = d1d[d1d.index <= t]
        s1 = structure_trend(dsub, lookback=250) if len(dsub) >= 100 else {"trend": None}
        out[t] = (s4["trend"], s1["trend"])
    return out


def regime_at(reg, t):
    """Последний известный режим ≤ t."""
    keys = [k for k in reg if k <= t]
    return reg[max(keys)] if keys else (None, None)


def run(d4h, d1h, d15, reg, start_ts):
    res = {g: [] for g in GATES}; pos = {g: None for g in GATES}
    l1 = l4 = -1; c1 = c4 = None
    start = pd.Timestamp(start_ts)
    reg_keys = sorted(reg.keys())
    ri = 0; cur_reg = (None, None)
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        # обновляем режим (продвигаем указатель)
        while ri < len(reg_keys) and reg_keys[ri] <= t:
            cur_reg = reg[reg_keys[ri]]; ri += 1
        for g in GATES:
            p = pos[g]
            if not p:
                continue
            ex_px = None
            if hi >= p["sl"]:
                ex_px = p["sl"]
            elif lo <= p["tp"]:
                ex_px = p["tp"]
            if ex_px is not None:
                gross = (p["entry"] - ex_px) / p["entry"] * 100          # short
                res[g].append({"net": gross - COST_PCT, "win": gross - COST_PCT > 0, "ts": p["ts"]})
                pos[g] = None
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != l1:
            c1 = structure_trend(d1, lookback=250); l1 = len(d1)
        d4 = d4h[d4h.index <= t]
        if len(d4) != l4:
            l4 = len(d4)
            c4 = structure_trend(d4, lookback=250) if len(d4) >= 120 else None
        if not c1 or not c4 or t < start:
            continue
        if c1["trend"] != "short" or c1["break_level"] is None or c1["extreme"] is None:
            continue
        if c4["trend"] != "short":
            continue
        ob = build_ote(c1["extreme"], c1["break_level"])
        lo_z, hi_z = ob["ote"]; lv = ob["levels"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        b15 = st15.get("break_level")
        entry = price
        if b15 is None or b15 <= entry:
            continue
        sl = b15 * 1.001
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        tp = lv.get(-1.0)
        if tp is None or tp >= entry:
            continue
        r4h, r1d = cur_reg
        allow = {"R1_btc4h": r4h == "short", "R2_btc1d": r1d == "short",
                 "R3_btc_both": r4h == "short" and r1d == "short", "R4_none": True}
        for g in GATES:
            if pos[g] is None and allow[g]:
                pos[g] = {"entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    grand = {g: [] for g in GATES}
    for ep, (start, end) in EPOCHS.items():
        reg = btc_regime_series(conn, start, end)
        if reg is None:
            print(f"{ep}: нет BTC данных"); continue
        agg = {g: [] for g in GATES}
        done = 0
        for sym in SYMBOLS:
            d4h = load(conn, sym, "4h", start, end)
            d1h = load(conn, sym, "1h", start, end)
            d15 = load(conn, sym, "15m", start, end)
            if any(x is None for x in (d4h, d1h, d15)):
                continue
            res = run(d4h, d1h, d15, reg, start)
            for g in agg:
                agg[g].extend(res[g])
            done += 1
        line = f"{ep:12} ({done}sym): "
        for g in GATES:
            tr = agg[g]
            grand[g].extend(tr)
            if tr:
                nets = [x["net"] for x in tr]
                line += f"{g.split('_')[0]}:n{len(tr)} {s.mean(nets):+.2f}%  "
            else:
                line += f"{g.split('_')[0]}:n0  "
        print(line)
    print("=" * 70)
    print("ИТОГО по всем эпохам:")
    for g in GATES:
        tr = grand[g]
        if not tr:
            continue
        nets = [x["net"] for x in tr]
        wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
        print(f"  {g:12} n={len(tr):4} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
    conn.close()
    print(f"costs={COST_PCT}% · SHORT-рецепт + BTC-режим-гейты · walk-forward по эпохам 2022-2026")


if __name__ == "__main__":
    main()
