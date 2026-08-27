# -*- coding: utf-8 -*-
"""ВЕРИФИКАЦИЯ ЛУПА choch_wavec: резолвер против эталона бэктеста.

Три проверки:
  A. статусы _resolve() == эталонный прямой расчёт (1:1 по каждому сетапу);
  B. МНОГОШАГОВЫЙ резолв (как в бою: каждые 15 мин на растущем df) == одношаговый;
  C. агрегат WR/PF совпадает с заявленным по механике (WR 53.1%, PF 1.17).
"""
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from bot.loops.choch_wavec_loop import HOLD_BARS, _TABLE, _resolve   # noqa: E402
from core.smc.choch_wavec import (PULLBACK, TARGET_K, WAIT_BARS,     # noqa: E402
                                  is_junk)
from core.smc.oko_sm_engine import run_structure                     # noqa: E402

N_SYM = int(sys.argv[1]) if len(sys.argv) > 1 else 25
COST = 0.35        # косты лимитом, % за круг


def load(sym):
    c = sqlite3.connect("ohlcv_cache.db")
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                    "WHERE symbol=? AND timeframe='1h' ORDER BY time", c, params=(sym,))
    c.close()
    if len(d) < 500:
        return None
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def setups(df):
    """Все swing-CHoCH вниз с ногой из leg_history — каузально, как find_setup."""
    dd = df.reset_index(drop=True)
    st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
    legs, out = st.leg_history, []
    if not legs or len(legs) != len(dd):
        return out
    for e in st.events:
        if e.kind != "CHoCH" or e.internal or e.bull:
            continue
        i = int(e.i)
        leg = legs[i]
        if not leg or leg.get("trend") == "long":
            continue
        o, x = float(leg["origin"]), float(leg["extreme"])
        A = abs(x - o)
        if A <= 0:
            continue
        entry, sl = x + A * PULLBACK, o * 1.001
        if sl <= entry:
            continue
        out.append({"i": i, "ts": str(df.index[i]), "entry": entry, "sl": sl,
                    "tp": entry - A * TARGET_K})
    return out


def truth(df, s):
    """ЭТАЛОН = логика замера scripts/choch_pullback_real_leg.py (resolve + окно wait).

    Независимая реализация: фил ищется в `range(i+1, i+1+wait)`, позиция держится
    ttl баров от бара фила, «ни стоп ни цель» → выход по close (tail).
    """
    H, L, C = df.high.values, df.low.values, df.close.values
    i, n, e, sl, tp = s["i"], len(df), s["entry"], s["sl"], s["tp"]

    jf = None
    for j in range(i + 1, min(i + 1 + WAIT_BARS, n)):
        if H[j] >= e:
            jf = j
            break
    if jf is None:
        # окно ещё не исчерпано данными → сетап всё ещё ждёт
        return ("EXPIRED", None) if i + WAIT_BARS < n else ("WAITING", None)

    end = min(jf + HOLD_BARS, n - 1)
    fl, fh = L[jf + 1:end + 1], H[jf + 1:end + 1]
    if len(fl) == 0:
        return "FILLED", None
    js = next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9)
    jt = next((k for k in range(len(fl)) if fl[k] <= tp), 10 ** 9)
    if js == 10 ** 9 and jt == 10 ** 9:
        if end - jf >= HOLD_BARS:
            return "EXPIRED", (e - float(C[end])) / e * 100
        return "FILLED", None
    if js <= jt:
        return "SL", (e - sl) / e * 100
    return "TP", (e - tp) / e * 100


def run():
    c = sqlite3.connect("ohlcv_cache.db")
    syms = [r[0] for r in c.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()]
    c.close()
    syms = [s for s in syms if not is_junk(s)][:N_SYM]

    mismatch_A = mismatch_B = 0
    total = 0
    res = []
    for sym in syms:
        df = load(sym)
        if df is None:
            continue
        ss = setups(df)
        if not ss:
            continue

        # ── одношаговый резолв через код лупа ──
        db1 = sqlite3.connect(":memory:")
        db1.execute(_TABLE)
        for s in ss:
            db1.execute("INSERT INTO choch_shadow (symbol,choch_ts,entry,stop_loss,"
                        "take_profit) VALUES (?,?,?,?,?)",
                        (sym, s["ts"], s["entry"], s["sl"], s["tp"]))
        db1.commit()
        _resolve(db1, sym, df)
        got1 = {r[0]: (r[1], r[2]) for r in db1.execute(
            "SELECT choch_ts,status,result_pct FROM choch_shadow")}

        # ── многошаговый: df растёт кусками по 50 баров, как в бою ──
        db2 = sqlite3.connect(":memory:")
        db2.execute(_TABLE)
        seen = set()
        for k in range(400, len(df) + 50, 50):
            part = df.iloc[:min(k, len(df))]
            for s in ss:
                if s["ts"] not in seen and s["i"] < len(part) - 1:
                    db2.execute("INSERT INTO choch_shadow (symbol,choch_ts,entry,"
                                "stop_loss,take_profit) VALUES (?,?,?,?,?)",
                                (sym, s["ts"], s["entry"], s["sl"], s["tp"]))
                    seen.add(s["ts"])
            db2.commit()
            _resolve(db2, sym, part)
            db2.commit()
        got2 = {r[0]: (r[1], r[2]) for r in db2.execute(
            "SELECT choch_ts,status,result_pct FROM choch_shadow")}

        for s in ss:
            total += 1
            exp, exp_pct = truth(df, s)
            g1 = got1.get(s["ts"], ("?", None))
            if g1[0] != exp:
                mismatch_A += 1
                if mismatch_A <= 5:
                    print(f"  ❌A {sym} {s['ts'][:16]}: луп={g1[0]} эталон={exp}")
            if got2.get(s["ts"], ("?", None))[0] != g1[0]:
                mismatch_B += 1
                if mismatch_B <= 5:
                    print(f"  ❌B {sym} {s['ts'][:16]}: многошаг={got2.get(s['ts'])} "
                          f"одношаг={g1[0]}")
            if g1[0] in ("TP", "SL", "EXPIRED") and g1[1] is not None:
                res.append(g1[1] - COST)
        db1.close()
        db2.close()

    print(f"\n{'═' * 70}")
    print(f"монет {len(syms)} · сетапов {total}")
    print(f"A. резолвер лупа == эталон бэктеста : "
          f"{'✅ 0 расхождений' if mismatch_A == 0 else f'❌ {mismatch_A}'}")
    print(f"B. многошаговый == одношаговый      : "
          f"{'✅ 0 расхождений' if mismatch_B == 0 else f'❌ {mismatch_B}'}")
    if res:
        w = [x for x in res if x > 0]
        gp, gl = sum(w), -sum(x for x in res if x <= 0)
        print(f"C. закрытых {len(res)} · WR {len(w) / len(res) * 100:.1f}% · "
              f"PF {gp / gl if gl else 0:.2f} · медиана {pd.Series(res).median():+.3f}% "
              f"(косты {COST}% учтены)")
        print("   заявлено по механике: WR 53.1% · PF 1.17")
    return 0 if mismatch_A == 0 and mismatch_B == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
