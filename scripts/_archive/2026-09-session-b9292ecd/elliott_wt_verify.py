"""
Перепроверка PF3.15 (29.08) с исправлением 1.5ч lag детектора + гипотеза WT-add-on.
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from research_harness import load, line, stat  # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
LAG_H = 1.5   # честная задержка видимости детектора (detector_confirmation_lag.py, медиана 6 баров на 15m)


def canon_marks(sym: str, ts: pd.Series) -> pd.DataFrame:
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
        rows.append(dict(t_end=t_end, direction=im["direction"], scale=float(im["scale"]),
                          textbook=bool(im["textbook"])))
    E = pd.DataFrame(rows).sort_values("t_end")
    # 🔴 честная задержка: событие "известно" только через LAG_H после t_end
    E["known_at"] = E["t_end"] + pd.Timedelta(hours=LAG_H)
    left = pd.DataFrame({"_ts": pd.to_datetime(ts.values, utc=True)}).sort_values("_ts")
    E2 = E.copy(); E2["imp_end"] = E2["t_end"]
    j = pd.merge_asof(left, E2.rename(columns={"known_at": "_ts"}), on="_ts",
                       direction="backward", allow_exact_matches=False)
    j["age_h"] = (j["_ts"] - j["imp_end"]).dt.total_seconds() / 3600
    return j.drop(columns=["_ts", "imp_end"])


def median_line(v: pd.DataFrame, nm: str) -> str:
    st = stat(v)
    if st is None:
        return f"  {nm:<38} n={len(v)} — мало"
    med = v.pnl.median()
    return (f"  {nm:<38} n={st['n']:<5} WR {st['wr']:5.1f}%  PF {st['pf']:5.2f}  "
            f"ср {st['avg']:+6.2f}%  мед {med:+6.2f}%  безтоп10% {st['bt']:+7.0f}  охват {st['cov']:3.0f}%")


def main():
    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna()].copy()

    parts = []
    for sym, g in R.groupby("sym"):
        g = g.sort_values("_ts")
        M = canon_marks(sym, g._ts)
        if M.empty:
            continue
        M = M.reset_index(drop=True)
        g = g.reset_index(drop=True)
        parts.append(pd.concat([g, M], axis=1))
    R = pd.concat(parts, ignore_index=True)
    print(f"сделок с покрытием {len(R)} / {len(pd.read_parquet(PQ))} · монет {R.sym.nunique()}")

    gate = R.mkt_drift_slope > 0
    fresh = R.direction.notna() & (R.age_h <= 72)   # тот же порог свежести 72ч, что в elliott_canon_remeasure

    print("\n" + "=" * 110)
    print(f"ГИПОТЕЗА 1 (с честным лагом {LAG_H} ч) — против/по завершённому импульсу, гейт mkt_drift_slope>0")
    print("=" * 110)
    for dr in ("up", "down"):
        for side in ("long", "short"):
            m = gate & fresh & (R.direction == dr) & (R.side == side)
            tag = "ПО импульсу" if ((dr == "up") == (side == "long")) else "ПРОТИВ импульса"
            print(median_line(R[m], f"импульс {dr:<5} + {side:<6} ({tag})"))

    print("\nАГРЕГАТ ПРОТИВ/ПО (обе стороны/направления слиты):")
    against = gate & fresh & (((R.direction == "up") & (R.side == "short")) | ((R.direction == "down") & (R.side == "long")))
    withimp = gate & fresh & (((R.direction == "up") & (R.side == "long")) | ((R.direction == "down") & (R.side == "short")))
    print(median_line(R[against], "ПРОТИВ импульса (агрегат)"))
    print(median_line(R[withimp], "ПО импульсу (агрегат)"))

    print("\nПО ГОДАМ (агрегат ПРОТИВ):")
    for y in sorted(R.year.unique()):
        print(median_line(R[against & (R.year == y)], f"  {y}"))

    print("\nПО РАЗМЕРУ СТОПА, терцили (агрегат ПРОТИВ):")
    q = R.stop_pct.quantile([1/3, 2/3]).values
    bins = [(0, q[0]), (q[0], q[1]), (q[1], 100)]
    for lo, hi in bins:
        m = against & (R.stop_pct >= lo) & (R.stop_pct < hi)
        print(median_line(R[m], f"  стоп [{lo:.2f},{hi:.2f})%"))

    print("\n" + "=" * 110)
    print("ГИПОТЕЗА 2 — WT добавляет поверх ГИПОТЕЗЫ 1 (агрегат ПРОТИВ импульса)")
    print("=" * 110)
    # направление дивергенции, ожидаемо совпадающее с разворотом (волна 5→A):
    # против up-импульса (шорт) ждём медвежью дивергенцию; против down (лонг) — бычью
    wt_div_against = (((R.direction == "up") & (R.side == "short") & (R.wt_div_bear_regular_15m == True)) |
                       ((R.direction == "down") & (R.side == "long") & (R.wt_div_bull_regular_15m == True)))
    print(f"доля сделок 'против импульса' с ожидаемой WT-дивергенцией: {wt_div_against[against].mean()*100:.1f}%"
          f" (n={wt_div_against[against].sum()})")
    print(median_line(R[against & wt_div_against], "ПРОТИВ импульса + WT div (ожид. направление)"))
    print(median_line(R[against & ~wt_div_against], "ПРОТИВ импульса БЕЗ WT div"))

    # extreme wt_state (перекупленность/перепроданность) на баре входа как маркер волны 3/5
    for col, nm in (("wt_ob_15m", "wt_ob (перекуплен)"), ("wt_os_15m", "wt_os (перепродан)")):
        if col in R.columns:
            mm = R[col] == True
            print(median_line(R[against & mm], f"ПРОТИВ импульса + {nm}"))
            print(median_line(R[against & ~mm], f"ПРОТИВ импульса БЕЗ {nm}"))

    print("\n" + "=" * 110)
    print("КОНТРОЛЬ (permutation): совпадение реального разделения ПРОТИВ vs ПО со случайной перетасовкой pnl")
    print("=" * 110)
    real = stat(R[against])["pf"] / stat(R[withimp])["pf"] if stat(R[withimp]) and stat(R[withimp])["pf"] else np.nan
    rng = np.random.default_rng(23)
    pool = R[against | withimp]
    noise = []
    for _ in range(200):
        perm = pool.assign(pnl=rng.permutation(pool.pnl.values))
        a = stat(perm[against.reindex(perm.index, fill_value=False) if False else perm.index.isin(R[against].index)])
        b = stat(perm[perm.index.isin(R[withimp].index)])
        if a and b and b["pf"]:
            noise.append(a["pf"] / b["pf"])
    noise = np.array(noise)
    p = float((noise >= real).mean()) if len(noise) else np.nan
    print(f"реальное разделение ×{real:.2f} · шум медиана ×{np.median(noise):.2f} · P95 ×{np.percentile(noise,95):.2f} · P(шум>=реал)={p:.3f}")


if __name__ == "__main__":
    sys.exit(main())
