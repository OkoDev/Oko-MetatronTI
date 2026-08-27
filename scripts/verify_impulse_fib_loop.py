# -*- coding: utf-8 -*-
"""ВЕРИФИКАЦИЯ ЛУПА impulse_fib: резолвер против эталона замера.

Три проверки, ровно те, что поймали баг в `choch_wavec_loop` (резолвер искал фил по
ВСЕЙ истории вместо окна 12 баров — 1086 из 1807 сетапов):
  A. резолвер лупа == эталон замера (одношаговый прогон по полной истории);
  B. многошаговый == одношаговый (df растёт кусками по 50 баров, как в бою);
  C. сводка по закрытым — сверка с заявленными числами механики.

Запуск: python scripts/verify_impulse_fib_loop.py [N_SYM]
"""
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from bot.loops.impulse_fib_loop import _TABLE, _resolve            # noqa: E402
from core.smc.impulse_fib import (ENTRY_FIB, HOLD_BARS, STOP_ATR_K,  # noqa: E402
                                  TARGET_FIB, WAIT_BARS, _atr, find_impulses, is_junk)

COST = 0.35
N_SYM = int(sys.argv[1]) if len(sys.argv) > 1 else 12


def load(sym):
    c = sqlite3.connect("file:ohlcv_cache.db?mode=ro", uri=True)
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='1h' ORDER BY time LIMIT 6000", c, params=(sym,))
    c.close()
    if len(d) < 1500:
        return None
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def setups(df):
    """Все сетапы механики каузально — та же геометрия, что у боевого find_setup."""
    dd = df.reset_index(drop=True)
    H, L, C = dd.high.values, dd.low.values, dd.close.values
    atr = _atr(dd).values
    n = len(dd)
    out = []
    for a, b, up in find_impulses(H, L, C, atr, n):
        if b < 250 or b >= n - 5:
            continue
        side = "long" if up else "short"
        amp = abs(C[b] - C[a])
        if amp <= 0:
            continue
        sign = -1.0 if up else 1.0
        entry = C[b] + sign * ENTRY_FIB * amp
        tp = C[b] + sign * TARGET_FIB * amp
        sl = entry - STOP_ATR_K * atr[b] if up else entry + STOP_ATR_K * atr[b]
        if (up and sl >= entry) or (not up and sl <= entry):
            continue
        sp = abs(entry - sl) / entry * 100
        if sp <= 0 or sp > 30:
            continue
        out.append({"i": b, "ts": str(df.index[b]), "ots": str(df.index[a]), "side": side,
                    "entry": float(entry), "sl": float(sl), "tp": float(tp)})
    return out


def truth(df, s):
    """ЭТАЛОН = логика замера: окно фила WAIT_BARS, затем горизонт HOLD_BARS."""
    d = df.iloc[:-1]
    w = d[d.index > pd.Timestamp(s["ts"], tz="UTC")]
    if w.empty:
        return "WAITING", None
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    up = s["side"] == "long"
    entry, sl, tp = s["entry"], s["sl"], s["tp"]
    sgn = 1.0 if up else -1.0

    win = min(len(hi), WAIT_BARS)
    if up:
        jf = next((k for k in range(win) if lo[k] <= entry), None)
        js0 = next((k for k in range(win) if lo[k] <= sl), None)
    else:
        jf = next((k for k in range(win) if hi[k] >= entry), None)
        js0 = next((k for k in range(win) if hi[k] >= sl), None)
    if js0 is not None and (jf is None or js0 < jf):
        return "INVALID", None
    if jf is None:
        return ("EXPIRED", None) if len(hi) >= WAIT_BARS else ("WAITING", None)

    hi2, lo2, cl2 = hi[jf + 1:], lo[jf + 1:], cl[jf + 1:]
    if len(hi2) == 0:
        return "FILLED", None
    hold = min(len(hi2), HOLD_BARS)
    if up:
        jt = next((k for k in range(hold) if hi2[k] >= tp), None)
        js = next((k for k in range(hold) if lo2[k] <= sl), None)
    else:
        jt = next((k for k in range(hold) if lo2[k] <= tp), None)
        js = next((k for k in range(hold) if hi2[k] >= sl), None)
    if jt is None and js is None:
        if len(hi2) >= HOLD_BARS:
            return "EXPIRED", sgn * (float(cl2[hold - 1]) - entry) / entry * 100
        return "FILLED", None
    if js is not None and (jt is None or js <= jt):
        return "SL", sgn * (sl - entry) / entry * 100
    return "TP", sgn * (tp - entry) / entry * 100


def _insert(db, sym, s):
    db.execute("INSERT OR IGNORE INTO impulse_shadow (symbol,impulse_ts,origin_ts,side,"
               "entry,stop_loss,take_profit) VALUES (?,?,?,?,?,?,?)",
               (sym, s["ts"], s["ots"], s["side"], s["entry"], s["sl"], s["tp"]))


def run():
    c = sqlite3.connect("file:ohlcv_cache.db?mode=ro", uri=True)
    syms = [r[0] for r in c.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()]
    c.close()
    syms = [s for s in syms if not is_junk(s)][:N_SYM]

    mismatch_A = mismatch_B = total = 0
    res = []
    for sym in syms:
        df = load(sym)
        if df is None:
            continue
        ss = setups(df)
        if not ss:
            continue

        db1 = sqlite3.connect(":memory:")
        db1.execute(_TABLE)
        for s in ss:
            _insert(db1, sym, s)
        db1.commit()
        _resolve(db1, sym, df)
        got1 = {r[0]: (r[1], r[2]) for r in db1.execute(
            "SELECT impulse_ts,status,result_pct FROM impulse_shadow")}

        db2 = sqlite3.connect(":memory:")
        db2.execute(_TABLE)
        seen = set()
        for k in range(400, len(df) + 50, 50):
            part = df.iloc[:min(k, len(df))]
            for s in ss:
                if s["ts"] not in seen and s["i"] < len(part) - 1:
                    _insert(db2, sym, s)
                    seen.add(s["ts"])
            db2.commit()
            _resolve(db2, sym, part)
            db2.commit()
        got2 = {r[0]: (r[1], r[2]) for r in db2.execute(
            "SELECT impulse_ts,status,result_pct FROM impulse_shadow")}

        for s in ss:
            total += 1
            exp, _ = truth(df, s)
            g1 = got1.get(s["ts"], ("?", None))
            if g1[0] != exp:
                mismatch_A += 1
                if mismatch_A <= 5:
                    print(f"  ❌A {sym} {s['ts'][:16]} {s['side']}: луп={g1[0]} эталон={exp}")
            if got2.get(s["ts"], ("?", None))[0] != g1[0]:
                mismatch_B += 1
                if mismatch_B <= 5:
                    print(f"  ❌B {sym} {s['ts'][:16]}: многошаг={got2.get(s['ts'])} "
                          f"одношаг={g1[0]}")
            if g1[0] in ("TP", "SL", "EXPIRED") and g1[1] is not None:
                res.append(g1[1] - COST)
        db1.close()
        db2.close()

    print("\n" + "═" * 70)
    print(f"монет {len(syms)} · сетапов {total}")
    print("A. резолвер лупа == эталон замера   : "
          + ("✅ 0 расхождений" if mismatch_A == 0 else f"❌ {mismatch_A}"))
    print("B. многошаговый == одношаговый      : "
          + ("✅ 0 расхождений" if mismatch_B == 0 else f"❌ {mismatch_B}"))
    if res:
        w = [x for x in res if x > 0]
        gp, gl = sum(w), -sum(x for x in res if x <= 0)
        print(f"C. закрытых {len(res)} · WR {len(w) / len(res) * 100:.1f}% · "
              f"PF {gp / gl if gl else 0:.2f} · медиана {np.median(res):+.3f}% "
              f"(косты {COST}% учтены)")
        print("   🔴 без гейтов и без фильтра глубины фила — сверять с базой замера, "
              "а не с итоговым PF 1.53")
    return 0 if mismatch_A == 0 and mismatch_B == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
