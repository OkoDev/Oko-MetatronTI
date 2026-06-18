"""DS-326 OOS (обобщённый): устойчивость edge по ADX-порогам + walk-forward + по годам.
Параметризован по связке сигнал-ТФ / вход-ТФ (--sig --entry), порог ADX для B/C (--adx).
Окна нормированы по времени (5ч вход / 75ч симуляция). RR=3, TSL=crude.

Примеры:
  python scripts/ds326_oos.py --sig 1h --entry 15m --adx 25   # база
  python scripts/ds326_oos.py --sig 4h --entry 15m --adx 35
"""
import sys, os, warnings, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from ds326_tf_matrix import load_tf, htf_wt, CONTEXT_OF, TF_MIN, WINDOW_HOURS, SIM_HOURS
from backtest_wt_b_ltf_entry import scan_1h_signals, find_ltf_entry, simulate_trade
from ds326_all_filters import adx_value

RR = 3.0


def collect(sig_tf: str, entry_tf: str) -> pd.DataFrame:
    em = TF_MIN[entry_tf]
    win = max(3, round(WINDOW_HOURS * 60 / em))
    simb = round(SIM_HOURS * 60 / em)
    syms = sorted(set(p.stem for p in Path("data/history/1h").glob("*.parquet")) &
                  set(p.stem for p in Path(f"data/history/{entry_tf}").glob("*.parquet")))[:45] \
        if entry_tf in ("5m", "15m", "1h") else []
    cache = {}
    rows = []
    for s in syms:
        df_sig = load_tf(s, sig_tf, cache)
        df_entry = load_tf(s, entry_tf, cache)
        if df_sig is None or df_entry is None:
            continue
        wt = htf_wt(load_tf(s, CONTEXT_OF[sig_tf], cache))
        for sig in scan_1h_signals(df_sig, wt):
            if sig["kind"] == "cross":
                continue
            adx = adx_value(df_sig, sig["ts"])
            ltf = find_ltf_entry(df_entry, sig["ts"], sig["direction"], sig["os_"], sig["ob"], win)
            if not ltf:
                continue
            R = simulate_trade(df_entry, ltf["ts"], ltf["entry"], ltf["sl"], sig["direction"],
                               RR, use_tsl=True, max_bars=simb)
            rows.append({"ts": pd.Timestamp(sig["ts"]), "dir": sig["direction"], "adx": adx, "R": R})
    return pd.DataFrame(rows)


HDR = f"{'срез':<26s} {'n':>4s} {'avgR':>7s} {'medR':>7s} {'WR':>6s} {'Sh':>6s} {'sumR':>7s}"


def row(label, arr):
    arr = np.asarray(arr, float)
    if len(arr) == 0:
        print(f"{label:<26s}   n=0"); return
    wr = (arr > 0).mean() * 100
    sh = arr.mean() / arr.std() if arr.std() > 0 else 0.0
    print(f"{label:<26s} {len(arr):>4d} {arr.mean():>+7.3f} {np.median(arr):>+7.3f} "
          f"{wr:>5.1f}% {sh:>+6.3f} {arr.sum():>+7.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sig", default="1h")
    ap.add_argument("--entry", default="15m")
    ap.add_argument("--adx", type=float, default=25.0, help="базовый порог ADX для B/C")
    a = ap.parse_args()

    df = collect(a.sig, a.entry).sort_values("ts").reset_index(drop=True)
    print(f"=== {a.sig}→{a.entry} | базовый ADX<{a.adx:.0f} ===")
    print(f"LTF-входов всего (без ADX-фильтра): {len(df)} | даты {str(df['ts'].min())[:10]} … {str(df['ts'].max())[:10]}\n")

    print("A) по ADX-порогу")
    print(HDR)
    for thr in (999, 40, 35, 30, 25, 20):
        row("без фильтра" if thr == 999 else f"ADX<{thr}", df[df["adx"] < thr]["R"])

    print("\nB) WALK-FORWARD (split пополам по времени)")
    print(HDR)
    for thr in (999, a.adx):
        sub = df[df["adx"] < thr].reset_index(drop=True)
        if len(sub) < 8:
            continue
        m = len(sub) // 2
        cut = str(sub.iloc[m]["ts"])[:10]
        lbl = "без фильтра" if thr == 999 else f"ADX<{thr:.0f}"
        row(f"{lbl} IN (<{cut})", sub.iloc[:m]["R"])
        row(f"{lbl} OUT(>={cut})", sub.iloc[m:]["R"])

    print("\nC) по годам")
    print(HDR)
    df["year"] = df["ts"].dt.year
    for thr in (999, a.adx):
        lbl = "без фильтра" if thr == 999 else f"ADX<{thr:.0f}"
        for y in sorted(df["year"].unique()):
            row(f"{lbl} {y}", df[(df["adx"] < thr) & (df["year"] == y)]["R"])
        print()


if __name__ == "__main__":
    main()
