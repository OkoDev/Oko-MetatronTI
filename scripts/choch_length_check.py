"""
choch_length_check.py — гипотеза: arch104 «захватывает часто» из-за слепого CHoCH.
Сравнивает detect_structure_breaks length=50 (default, swing_bridge) vs length=5 (эталон OKO-SM).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
from core.smc.smc_engine import detect_structure_breaks

SYMBOL = "XLM/USDT:USDT"
TFS = ["5m", "15m", "1h", "4h"]


def load(ex, tf, limit=500):
    o = ex.fetch_ohlcv(SYMBOL, tf, limit=limit)
    return pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])


def main():
    ex = ccxt.bingx({"options": {"defaultType": "swap"}})
    print(f"{'TF':>4} {'len':>4} | {'CHoCH':>5} {'BOS':>4} | посл.CHoCH @bar (лаг от конца) | направление")
    print("-" * 82)
    for tf in TFS:
        df = load(ex, tf)
        n = len(df)
        for length in (50, 5):
            try:
                breaks = detect_structure_breaks(df, length=length)
            except Exception as e:
                print(f"{tf:>4} {length:>4} | ошибка: {e}")
                continue
            choch = [b for b in breaks if getattr(b, "kind", "") == "CHoCH"]
            bos = [b for b in breaks if getattr(b, "kind", "") == "BOS"]
            if choch:
                last = choch[-1]
                idx = getattr(last, "idx", -1)
                age = n - 1 - idx if idx >= 0 else -1
                d = getattr(last, "direction", "?")
                tail = f"@bar {idx} (лаг {age} баров) {d}"
            else:
                tail = "нет CHoCH"
            mark = "  ← слепой default" if length == 50 else "  ← эталон OKO-SM"
            print(f"{tf:>4} {length:>4} | {len(choch):>5} {len(bos):>4} | {tail:<32}{mark}")
        print()


if __name__ == "__main__":
    main()
