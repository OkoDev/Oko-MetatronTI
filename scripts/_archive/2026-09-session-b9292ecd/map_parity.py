"""Parity реплеев с журналами боя ДО фила: сетапы choch_shadow / impulse_shadow (1h) против сетапов реплея на тех же монетах.
python map_parity.py"""
import sys, sqlite3
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
pd.set_option("display.width", 250)


def choch_setups(sym, m, t_from):
    from core.smc.oko_sm_engine import run_structure
    from core.smc.choch_wavec import PULLBACK, SWING_LEN
    st = run_structure(m.reset_index(drop=True), swing_len=SWING_LEN, internal_len=5, record_legs=True); legs = st.leg_history
    tr = pd.concat([m.high - m.low, (m.high - m.close.shift()).abs(), (m.low - m.close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = (tr.ewm(alpha=1 / 43, adjust=False).mean() / m.close * 100).rolling(1000, min_periods=300).median().values
    out = []
    for ev in st.events:
        if ev.kind == "CHoCH" and not ev.internal and not ev.bull and m.index[ev.i] >= t_from:
            leg = legs[ev.i]
            if not leg or leg.get("trend") == "long":
                continue
            o, x = float(leg["origin"]), float(leg["extreme"]); L = abs(x - o); e = x + PULLBACK * L; sl = o * 1.001; sp = (sl - e) / e * 100
            out.append({"sym": sym, "t": m.index[ev.i], "entry": e, "sl": sl, "stop_pct": sp, "atr_pct": atr_pct[ev.i],
                        "ok": bool(8 <= sp <= 15 and atr_pct[ev.i] >= 1.59)})
    return out


def impulse_setups(sym, m, t_from):
    from core.smc.impulse_fib import find_impulses, _atr, ENTRY_FIB, STOP_ATR_K, VOL_LO, VOL_HI, REGIME_MIN
    d = m.reset_index(drop=True); n = len(d); H, L, C, V = d.high.values, d.low.values, d.close.values, d.volume.values
    aa = _atr(d); atr = aa.values; regime = (aa / aa.rolling(100).mean()).values
    ema200 = d.close.ewm(span=200, adjust=False).mean().values; volma = pd.Series(V).rolling(120).mean().values
    i0 = int(np.searchsorted(m.index.values, np.datetime64(t_from)))
    out = []
    for a, b, up in find_impulses(H, L, C, atr, n, start=max(60, i0 - 100)):
        if b < i0:
            continue
        origin, extreme = float(C[a]), float(C[b]); amp = abs(extreme - origin); sign = -1.0 if up else 1.0
        e = extreme + sign * ENTRY_FIB * amp; sl = e - STOP_ATR_K * atr[b] if up else e + STOP_ATR_K * atr[b]
        sp = abs(e - sl) / e * 100
        vr = float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0
        reg = float(regime[b]) if not np.isnan(regime[b]) else 1.0; wt = bool((C[b] > ema200[b]) == up)
        out.append({"sym": sym, "t": m.index[b], "side": "long" if up else "short", "entry": e, "sl": sl, "stop_pct": sp,
                    "ok": bool(1.5 <= sp <= 3.234 and VOL_LO <= vr < VOL_HI and wt and reg >= REGIME_MIN)})
    return out


if __name__ == "__main__":
    c = sqlite3.connect(ROOT / "subscriptions.db"); have = {p.stem for p in PARQ.glob("*.parquet")}
    for tbl, ts, fn in (("choch_shadow", "choch_ts", choch_setups), ("impulse_shadow", "impulse_ts", impulse_setups)):
        J = pd.read_sql(f"SELECT symbol,{ts} AS ts,entry,stop_loss,stop_pct,status,result_pct,created_at FROM {tbl}", c)
        J["sym"] = J.symbol.str.split("/").str[0] + "USDT"; J["t"] = pd.to_datetime(J.ts); J = J.drop_duplicates(["sym", "t"])
        J = J[J.sym.isin(have)]
        t_from = J.t.min() - pd.Timedelta(days=2); t_to = pd.Timestamp("2026-09-15 23:00")   # паркеты до 15.09
        Jw = J[J.t <= t_to]
        R = []
        for sym in sorted(Jw.sym.unique()):
            try:
                m = load_tf(sym, "1h")
            except Exception:
                continue
            R += fn(sym, m, t_from)
        R = pd.DataFrame(R); Rok = R[R.ok]
        print(f"\n=== {tbl}: журнал {len(Jw)} сетапов до 15.09 на {Jw.sym.nunique()} монетах с паркетами · реплей на тех же монетах: {len(Rok)} сетапов (все: {len(R)})")
        hit = 0; miss = []
        for r in Jw.itertuples():
            q = Rok[(Rok.sym == r.sym) & ((Rok.t - r.t).abs() <= pd.Timedelta(hours=1))]
            if len(q):
                hit += 1; q0 = q.iloc[0]
                de = (q0.entry / r.entry - 1) * 100; ds = (q0.sl / r.stop_loss - 1) * 100
                if abs(de) > 0.5 or abs(ds) > 0.5:
                    print(f"  ≈ {r.sym} {r.t:%d.%m %H:%M}: цена входа расходится {de:+.2f}% · стоп {ds:+.2f}%")
            else:
                q2 = R[(R.sym == r.sym) & ((R.t - r.t).abs() <= pd.Timedelta(hours=1))]
                miss.append((r.sym, f"{r.t:%d.%m %H:%M}", r.status, "есть, но отсеян фильтром" if len(q2) else "нет сетапа в реплее"))
        print(f"  журнал → реплей: совпало {hit}/{len(Jw)}")
        for x in miss[:25]:
            print("   ✗", x)
        # обратная сторона: сетапы реплея, которых нет в журнале
        extra = 0
        for r in Rok[(Rok.t >= Jw.t.min()) & (Rok.t <= t_to)].itertuples():
            if not len(Jw[(Jw.sym == r.sym) & ((Jw.t - r.t).abs() <= pd.Timedelta(hours=1))]):
                extra += 1
        print(f"  реплей → журнал: сетапов реплея без пары в журнале {extra} (из {int(((Rok.t >= Jw.t.min()) & (Rok.t <= t_to)).sum())}); бой видит ~250 монет по обороту + кэп 8 позиций")
