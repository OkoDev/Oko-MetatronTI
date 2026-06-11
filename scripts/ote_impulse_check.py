"""
ote_impulse_check.py — рассогласование OTE-импульса по ВСЕМ ТФ:
  snapshot (detect_structure period=5)  vs  торговля (zigzag из ote_retest_setups).

Гипотеза: snapshot (дашборд) промахивается на всех/многих ТФ, zigzag (торговля) — нет.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd

from core.smc.structure import detect_structure
from core.smc.smc_engine import ote_retest_setups

SYMBOL = "XLM/USDT:USDT"
TFS = ["3m", "5m", "15m", "1h", "4h", "1d"]
OTE_LO_R, OTE_HI_R = 0.618, 0.786   # как в smc_snapshot


def load(ex, tf, limit=500):
    o = ex.fetch_ohlcv(SYMBOL, tf, limit=limit)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    return df


def snapshot_ote(df, current):
    """Повторяет логику smc_snapshot: impulse = last_high/last_low (period=5)."""
    s = detect_structure(df, swing_period=5)
    sa = s.swing_analysis
    if sa.last_high is None or sa.last_low is None:
        return None
    ih, il = sa.last_high.value, sa.last_low.value
    if ih <= il:
        return None
    direction = "LONG" if sa.last_high.index > sa.last_low.index else "SHORT"
    diff = ih - il
    retr = (ih - current) / diff * 100 if direction == "LONG" else (current - il) / diff * 100
    ote_hi = ih - diff * OTE_LO_R
    ote_lo = ih - diff * OTE_HI_R
    lo, hi = min(ote_lo, ote_hi), max(ote_lo, ote_hi)
    return {"dir": direction, "retr": retr, "in_ote": lo <= current <= hi, "ote": (lo, hi), "imp": (il, ih)}


def zigzag_ote(df, current, depth, dev):
    """Реальный торговый путь: ote_retest_setups (zigzag)."""
    setups = ote_retest_setups(df, depth=depth, dev_mult=dev, only_choch=False, provisional=True)
    if not setups:
        return None
    h = setups[-1]
    lo, hi = h["ote"]
    lo, hi = min(lo, hi), max(lo, hi)
    return {"dir": h["direction"], "in_ote": lo <= current <= hi, "ote": (lo, hi), "imp": (h.get("from"), h.get("to"))}


def main():
    ex = ccxt.bingx({"options": {"defaultType": "swap"}})
    # per-ТФ zigzag параметры из генератора (реально что торгует)
    try:
        from core.smc.ote_signal_generator import OTESignalGenerator
        gen = OTESignalGenerator()
        zz_of = lambda tf: gen._zz(tf)
    except Exception:
        zz_of = lambda tf: (11, 3.0)

    print(f"{'TF':>4} | {'snapshot(p5)':>22} | {'zigzag(торговля)':>26} | расхожд.")
    print("-" * 78)
    for tf in TFS:
        try:
            df = load(ex, tf)
            current = float(df["close"].iloc[-1])
            snap = snapshot_ote(df, current)
            depth, dev = zz_of(tf)
            zz = zigzag_ote(df, current, depth, dev)

            snap_s = f"{snap['dir']} retr={snap['retr']:.0f}% in_ote={snap['in_ote']}" if snap else "—"
            zz_s = f"zz{depth}/{dev:g} {zz['dir']} in_ote={zz['in_ote']}" if zz else f"zz{depth}/{dev:g} нет setup"
            # расхождение: snapshot и zigzag не согласны про in_ote или direction
            mism = ""
            if snap and zz:
                if snap["in_ote"] != zz["in_ote"]:
                    mism = "⚠️ IN_OTE расходится"
                elif snap["dir"].lower() != zz["dir"].lower():
                    mism = "⚠️ DIR расходится"
                else:
                    mism = "ok"
            print(f"{tf:>4} | {snap_s:>22} | {zz_s:>26} | {mism}")
        except Exception as e:
            print(f"{tf:>4} | ошибка: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
