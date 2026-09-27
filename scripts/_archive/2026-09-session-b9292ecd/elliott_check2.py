import sys, warnings
from pathlib import Path
import pandas as pd, numpy as np
ROOT = Path(r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
from research_harness import load, stat

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
LAG_H = 1.5

def canon_marks(sym, ts):
    from core.smc.smc_engine import detect_elliott_mtf
    try:
        d = load(sym, "15m")
    except Exception:
        return pd.DataFrame()
    if d is None or len(d) < 5000:
        return pd.DataFrame()
    try:
        imps = detect_elliott_mtf(d)
    except Exception:
        return pd.DataFrame()
    if not imps:
        return pd.DataFrame()
    rows = []
    for im in imps:
        w = im["waves"]
        t_end = pd.Timestamp(w[-1][0])
        if t_end.tzinfo is None:
            t_end = t_end.tz_localize("UTC")
        rows.append(dict(t_end=t_end, direction=im["direction"], scale=float(im["scale"])))
    E = pd.DataFrame(rows).sort_values("t_end")
    E["known_at"] = E["t_end"] + pd.Timedelta(hours=LAG_H)
    left = pd.DataFrame({"_ts": pd.to_datetime(ts.values, utc=True)}).sort_values("_ts")
    E2 = E.copy(); E2["imp_end"] = E2["t_end"]
    j = pd.merge_asof(left, E2.rename(columns={"known_at": "_ts"}), on="_ts",
                       direction="backward", allow_exact_matches=False)
    j["age_h"] = (j["_ts"] - j["imp_end"]).dt.total_seconds() / 3600
    return j.drop(columns=["_ts", "imp_end"])

R = pd.read_parquet(PQ)
R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
R = R[R._ts.notna()].copy()
parts = []
for sym, g in R.groupby("sym"):
    g = g.sort_values("_ts")
    M = canon_marks(sym, g._ts)
    if M.empty: continue
    parts.append(pd.concat([g.reset_index(drop=True), M.reset_index(drop=True)], axis=1))
R = pd.concat(parts, ignore_index=True)

gate = R.mkt_drift_slope > 0
fresh = R.direction.notna() & (R.age_h <= 72)
against = gate & fresh & (((R.direction == "up") & (R.side == "short")) | ((R.direction == "down") & (R.side == "long")))

sub = R[against]
print("против импульса: top5 pnl", sorted(sub.pnl.values)[-5:])
print("сумма всех:", sub.pnl.sum(), "сумма без топ3:", sub.pnl.sort_values(ascending=False).iloc[3:].sum())
per = sub.groupby("sym").pnl.sum().sort_values(ascending=False)
print("монет", len(per), "в плюсе", (per>0).sum())
print("топ3 монеты:", per.head(3).to_dict())

wt_os = R.wt_os_15m == True
sub2 = R[against & wt_os]
print("\nwt_os подвыборка n=", len(sub2))
print(sub2[["sym","year","side","pnl"]].sort_values("pnl", ascending=False).head(10))
print("сумма:", sub2.pnl.sum(), "без топ2:", sub2.pnl.sort_values(ascending=False).iloc[2:].sum())

print("\n=== БЕЗ ФИЛЬТРА СВЕЖЕСТИ (как в оригинальном elliott_canon_remeasure.py, только с лагом 1.5ч) ===")
for dr in ("up","down"):
    for side in ("long","short"):
        m = gate & R.direction.notna() & (R.direction==dr) & (R.side==side)
        tag = "ПО" if ((dr=="up")==(side=="long")) else "ПРОТИВ"
        s = stat(R[m])
        if s:
            print(f"  импульс {dr:<5} + {side:<6} ({tag:<6}) n={s['n']:<5} WR {s['wr']:.1f}% PF {s['pf']:.2f} ср {s['avg']:+.2f}% мед {R[m].pnl.median():+.2f}% безтоп10% {s['bt']:+.0f}")
