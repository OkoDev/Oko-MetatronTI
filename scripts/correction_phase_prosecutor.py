"""
correction_phase_prosecutor.py — ПРОКУРОР ПО «ФАЗЕ КОРРЕКЦИИ» (29.08.2026).

Единственная находка сессии, пережившая 2026: вход в фазе коррекции (нет свежего
ЗАВЕРШЁННОГО эллиоттовского импульса) даёт подъём к базе своего года ×1.74 / ×1.38 / ×1.47
в 2024-2025-2026 ([[elliott_canon_beats_my_proxy]]). Все прочие оси в 2026 не работали.

Здесь закрываются ВСЕ хвосты, а не выборочные:

  1. ПЛАТО ПОРОГА — 72 ч взяты навскидку. Если результат живёт на одном значении, это пик,
     а не свойство ([[constants_plateau_not_fibonacci]]).
  2. МАСШТАБ — `detect_elliott_mtf` даёт scale 3/5/8. Работает ли на всех или на одном.
  3. ВРЕМЕННОЙ OOS — train до 2025, test 2025-26. Разбиение по монетам этого не проверяет.
  4. ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ на той же схеме.
  5. 2023 ДАЁТ ОБРАТНЫЙ ЗНАК (×0.28) — назвать причину, а не замолчать.
  6. ОХВАТ МОНЕТ и вклад лучших — «плюс на 4 из 10» не эдж.
  7. ХРУПКОСТЬ — безтоп10% печатается везде.
  8. СТОРОНА — обе обязательны.

🔴 Причинность: импульс засчитывается ТОЛЬКО если завершился строго ДО бара входа
(`allow_exact_matches=False`) — детектор расширяет волну 5 вперёд по ряду.

    python scripts/correction_phase_prosecutor.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import load, line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def build() -> pd.DataFrame:
    """Сделки + каноничная разметка: возраст последнего ЗАВЕРШЁННОГО импульса и его масштаб."""
    from core.smc.smc_engine import detect_elliott_mtf
    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna()]
    parts = []
    for sym, g in R.groupby("sym"):
        try:
            d = load(sym, "15m")
        except Exception:                    # noqa: BLE001
            continue
        if d is None or len(d) < 5000:
            continue
        try:
            imps = detect_elliott_mtf(d)
        except Exception:                    # noqa: BLE001
            continue
        if not imps:
            continue
        rows = []
        for im in imps:
            t = pd.Timestamp(im["waves"][-1][0])
            t = t.tz_localize("UTC") if t.tzinfo is None else t
            rows.append(dict(t_end=t, direction=im["direction"], scale=float(im["scale"]),
                             textbook=bool(im["textbook"])))
        E = pd.DataFrame(rows).sort_values("t_end")
        E["imp_end"] = E.t_end
        g = g.sort_values("_ts").reset_index(drop=True)
        j = pd.merge_asof(pd.DataFrame({"_ts": g._ts}),
                          E.rename(columns={"t_end": "_ts"}), on="_ts",
                          direction="backward", allow_exact_matches=False)
        j["age_h"] = (j._ts - j.imp_end).dt.total_seconds() / 3600
        parts.append(pd.concat([g, j.drop(columns=["_ts", "imp_end"])], axis=1))
    return pd.concat(parts, ignore_index=True)


def corr_mask(R: pd.DataFrame, hours: float) -> pd.Series:
    """Фаза коррекции: свежего завершённого импульса НЕТ."""
    return ~(R.direction.notna() & (R.age_h <= hours))


def main() -> int:
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--hours",type=float,default=72.0)
    ARGS=ap.parse_args()
    R = build()
    gate = R.mkt_drift_slope > 0
    print("=" * 104)
    print(f"ПРОКУРОР · ФАЗА КОРРЕКЦИИ · сделок {len(R)} · монет {R.sym.nunique()}")
    print("=" * 104)
    print(line(R, "  БАЗА ВСЁ"))
    print(line(R[gate], "  БАЗА гейт"))

    # ── 1. ПЛАТО ПОРОГА ──────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("1. ПЛАТО ПОРОГА СВЕЖЕСТИ (72 ч взяты навскидку — пик это или плато)")
    print("=" * 104)
    for h in (12, 24, 48, 72, 96, 168, 336):
        m = corr_mask(R, h)
        a, b = stat(R[gate & m]), stat(R[gate & ~m])
        if a is None or b is None:
            print(f"  {h:>4} ч: мало"); continue
        print(f"  {h:>4} ч: коррекция PF {a['pf']:5.2f} (n={a['n']:>4}, доля {m.mean()*100:2.0f}%) "
              f"против импульс {b['pf']:5.2f} (n={b['n']:>4})  ×{a['pf']/b['pf']:.2f}"
              f"  безтоп10% {a['bt']:+7.0f}")

    H = ARGS.hours
    print(f"\n>>> ДАЛЬШЕ ВСЁ НА ПОРОГЕ {H:.0f} ч <<<")
    m = corr_mask(R, H)

    # ── 2. МАСШТАБ ───────────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("2. МАСШТАБ ИМПУЛЬСА (3/5/8) — на всех работает или на одном")
    print("=" * 104)
    for sc in sorted(R.scale.dropna().unique()):
        sub = R[(R.scale == sc) | m]          # импульсы этого масштаба + фаза коррекции
        mm = corr_mask(sub, H)
        a, b = stat(sub[gate[sub.index] & mm]), stat(sub[gate[sub.index] & ~mm])
        if a and b and b["pf"]:
            print(f"  scale {sc}: коррекция {a['pf']:5.2f} (n={a['n']:>4}) против "
                  f"импульс {b['pf']:5.2f} (n={b['n']:>4})  ×{a['pf']/b['pf']:.2f}")

    # ── 3. ВРЕМЕННОЙ OOS ─────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("3. ВРЕМЕННОЙ OOS: train < 2025 → test 2025-2026")
    print("=" * 104)
    tr, te = R._ts < SPLIT, R._ts >= SPLIT
    for nm, sel in (("train", tr), ("test", te)):
        a, b = stat(R[sel & gate & m]), stat(R[sel & gate])
        if a and b:
            print(f"  {nm}: коррекция PF {a['pf']:5.2f} (n={a['n']:>4}) против "
                  f"база гейта {b['pf']:5.2f} (n={b['n']:>4})  ×{a['pf']/b['pf']:.2f}"
                  f"  безтоп10% {a['bt']:+7.0f}  охват {a['cov']:.0f}%")

    # ── 4. ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ ──────────────────────────────────────────
    print("\n🎲 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ (30 перемешиваний pnl, та же схема train→test):")
    rng = np.random.default_rng(23)
    real = stat(R[te & gate & m])["pf"] / stat(R[te & gate])["pf"]
    noise = []
    for _ in range(30):
        Rs = R.assign(pnl=rng.permutation(R.pnl.values))
        a, b = stat(Rs[te & gate & m]), stat(Rs[te & gate])
        noise.append(a["pf"] / b["pf"] if a and b and b["pf"] else np.nan)
    noise = np.array([x for x in noise if np.isfinite(x)])
    p = float((noise >= real).mean())
    print(f"   ШУМ: медиана ×{np.median(noise):.2f} · 95-й перцентиль ×{np.percentile(noise,95):.2f}"
          f" · максимум ×{noise.max():.2f}   наш ×{real:.2f}")
    print(f"   P(шум ≥ нашего) = {p:.3f}   " +
          ("🟢 ОТЛИЧИМО ОТ ШУМА" if p < 0.05 else "🔴 НЕ отличимо" if p > 0.15 else "🟡 граница"))

    # ── 5. ГОД + ПОЧЕМУ 2023 ОБРАТНЫЙ ────────────────────────────────────────
    print("\n" + "=" * 104)
    print("5. ГОД · и разбор обратного знака в 2023")
    print("=" * 104)
    for y in sorted(R.year.unique()):
        g = R[R.year == y]
        a, b = stat(g[gate[g.index] & m[g.index]]), stat(g[gate[g.index]])
        if a and b and b["pf"]:
            print(f"  {y}: коррекция {a['pf']:5.2f} (n={a['n']:>4}) против гейт {b['pf']:5.2f}"
                  f"  ×{a['pf']/b['pf']:.2f}  безтоп10% {a['bt']:+7.0f}  охват {a['cov']:.0f}%")
    print("\n  доля фазы коррекции и состав по годам:")
    for y in sorted(R.year.unique()):
        g = R[R.year == y]
        print(f"    {y}: коррекция {m[g.index].mean()*100:2.0f}% сделок · "
              f"long {(g.side=='long').mean()*100:2.0f}% · "
              f"импульсов вверх {(g.direction=='up').mean()*100:2.0f}%")

    # ── 6-8. СТОРОНА · ОХВАТ · ХРУПКОСТЬ ─────────────────────────────────────
    print("\n" + "=" * 104)
    print("6. СТОРОНА (обе обязательны)")
    print("=" * 104)
    for side in ("long", "short"):
        s = R.side == side
        a, b = stat(R[gate & m & s]), stat(R[gate & s])
        if a and b and b["pf"]:
            print(f"  {side:<6} коррекция {a['pf']:5.2f} (n={a['n']:>4}) против гейт "
                  f"{b['pf']:5.2f}  ×{a['pf']/b['pf']:.2f}  безтоп10% {a['bt']:+7.0f}")

    print("\n" + "=" * 104)
    print("7. ОХВАТ МОНЕТ И ВКЛАД ЛУЧШИХ")
    print("=" * 104)
    sub = R[gate & m]
    per = sub.groupby("sym").pnl.sum().sort_values(ascending=False)
    print(f"  монет {len(per)} · в плюсе {(per>0).sum()} ({(per>0).mean()*100:.0f}%)")
    print(f"  сумма {per.sum():+.0f}% · без лучшей {per.iloc[1:].sum():+.0f}% · "
          f"без лучших трёх {per.iloc[3:].sum():+.0f}%")
    print(f"  лучшая {per.index[0]} {per.iloc[0]:+.0f}% · худшая {per.index[-1]} {per.iloc[-1]:+.0f}%")

    print("\n" + "=" * 104)
    print("8. СВЯЗКА С УЖЕ ИЗВЕСТНЫМ (не дубль ли это)")
    print("=" * 104)
    churn = R.st5_count20_15m >= 2
    ch = R.st50_is_choch_15m == 1.0
    for nm, other in (("churn", churn), ("CHoCH", ch)):
        jac = (m & other).sum() / (m | other).sum()
        print(f"  коррекция ∩ {nm}: Жаккар {jac:.3f} · r = "
              f"{m.astype(float).corr(other.astype(float)):+.3f}")
        a, b = stat(R[gate & m & other]), stat(R[gate & m & ~other])
        if a and b and b["pf"]:
            print(f"     внутри коррекции {nm} даёт {a['pf']:5.2f} (n={a['n']:>4}) против "
                  f"{b['pf']:5.2f} (n={b['n']:>4})  ×{a['pf']/b['pf']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
