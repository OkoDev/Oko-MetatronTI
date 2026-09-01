"""
mtf_confluence_zone.py — MTF-КОНФЛЮЭНЦИЯ В ЗОНЕ ВХОДА (30.08.2026).

Третья часть запроса Егора: «конфлюенции MTF в зоне OTE как подтверждение».

Первые две части уже закрыты и обе дали отрицательный результат:
  · завершённость импульса — гипотеза ОПРОВЕРГНУТА: продолжение импульса ЛУЧШЕ
    завершённости (K=24: ×1.29 против ×0.58), причём по сторонам зеркально;
  · вход из зоны OTE — НЕ работает: кривая по глубине монотонно падает
    (0.382 → PF 2.57 · 0.5 → 2.19 · 0.75 → 1.45), «глубже лучше» оказалось
    СЛЕДСТВИЕМ силы движения, а не рычагом.

Конфлюэнция — принципиально другой вопрос: не ГДЕ входить, а ПОДТВЕРЖДАЕТ ли зону
старший ТФ. Здесь она не зависит от того, где стоит лимит.

🔴 ПОЧЕМУ ЭТО НЕ ПОВТОР ПРОШЛЫХ ЗАМЕРОВ. В реестре записано: «290 признаков старших ТФ
мерились ПООДИНОЧКЕ, набором — ни разу» (пункт 1.2 плана перепроверки). Одиночный признак
4h — это не конфлюэнция. Конфлюэнция = СКОЛЬКО независимых свидетельств старшего ТФ
согласны с направлением сделки. Считаем именно счётчик согласия.

🔴 И ЭТО НЕ «ЖЁСТКИЙ ГЕЙТ». Прошлая попытка MTF-матрицы провалилась именно на жёстком
гейте ([[mtf_confluence_matrix_vision]]). Поэтому здесь конфлюэнция меряется как
НЕПРЕРЫВНАЯ шкала (0..N согласных), а вердикт выносится по ФОРМЕ кривой: монотонный
рост = подтверждение работает; U-образная = работает только край
([[zone_confluence_and_gaps]] — там кривая была именно U-образной).

    python scripts/mtf_confluence_zone.py --tf 1h
"""
from __future__ import annotations

import argparse
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

from research_harness import stat, line        # noqa: E402

# Пары «бычье свидетельство / медвежье свидетельство» на старшем ТФ.
# Считаем СОГЛАСИЕ с направлением сделки: для long засчитывается бычье, для short медвежье.
PAIRS = [("bull_fvg_in", "bear_fvg_in"), ("bull_ob_near", "bear_ob_near"),
         ("bull_breaker", "bear_breaker"), ("bull_bos", "bear_bos"),
         ("bull_choch", "bear_choch"), ("wt_state_up", "wt_state_down"),
         ("wt_cross_up", "wt_cross_down"), ("wt_div_bull_regular", "wt_div_bear_regular"),
         ("rsi_cross50_up", "rsi_cross50_down"), ("bull_mom", "bear_mom"),
         ("above_ema200", "below_ema200"), ("ema50_above_ema200", "ema50_below_ema200"),
         ("dc_at_upper", "dc_at_lower"), ("dc_slope_up", "dc_slope_down"),
         ("st5_up", "st5_down"), ("st50_up", "st50_down")]


def build_score(X: pd.DataFrame, stf: str) -> tuple[pd.Series, list[str]]:
    """Счётчик согласия старшего ТФ с направлением сделки."""
    up = (X.side == "long").values
    score = np.zeros(len(X))
    used = []
    for b, s in PAIRS:
        cb, cs = f"{b}_{stf}__from_{stf}", f"{s}_{stf}__from_{stf}"
        if cb not in X.columns or cs not in X.columns:
            continue
        vb = X[cb].fillna(0).astype(float).values
        vs = X[cs].fillna(0).astype(float).values
        score += np.where(up, vb, vs)          # согласие: бычье для long, медвежье для short
        used.append(b)
    return pd.Series(score, index=X.index), used


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--pq", default=None)
    a = ap.parse_args()
    pq = Path(a.pq) if a.pq else ROOT / "cache" / f"matrix_core_{a.tf}.parquet"
    X = pd.read_parquet(pq)
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    senior = {"15m": ["1h", "4h"], "1h": ["4h"]}.get(a.tf, ["4h"])

    print("=" * 104)
    print(f"MTF-КОНФЛЮЭНЦИЯ В ЗОНЕ ВХОДА · {pq.name} · {len(X)} сделок · {X.sym.nunique()} монет")
    print("=" * 104)
    print("конфлюэнция = СКОЛЬКО независимых свидетельств старшего ТФ согласны с направлением")
    print("🔴 меряем НЕПРЕРЫВНОЙ шкалой, не жёстким гейтом: прошлая MTF-матрица провалилась")
    print("   именно на жёстком гейте. Вердикт — по ФОРМЕ кривой, а не по одной клетке.")

    b_all = stat(X)
    for stf in senior:
        score, used = build_score(X, stf)
        if not used:
            print(f"\n── {stf}: подходящих пар признаков НЕТ — измерить нечем")
            continue
        X[f"conf_{stf}"] = score
        print(f"\n── КОНФЛЮЭНЦИЯ С {stf.upper()} · свидетельств в наборе: {len(used)} ──")
        print(f"   {', '.join(used)}")
        print(f"   распределение: медиана {score.median():.0f} · макс {score.max():.0f}")
        print(f"\n   {'согласных':<12} {'n':>6} {'PF':>7} {'подъём':>8} {'WR':>7}"
              f" {'безтоп10%':>11} {'охват':>7}")
        for lo, hi in ((0, 0), (1, 1), (2, 2), (3, 3), (4, 5), (6, 99)):
            m = (score >= lo) & (score <= hi)
            s = stat(X[m])
            if s and s["n"] >= 40:
                lbl = f"{lo}" if lo == hi else f"{lo}-{hi if hi < 99 else '+'}"
                print(f"   {lbl:<12} {s['n']:>6} {s['pf']:>7.2f} ×{s['pf']/b_all['pf']:>7.2f}"
                      f" {s['wr']:>6.1f}% {s['bt']:>+11.0f} {s['cov']:>6.0f}%")

        print("\n   ── по сторонам (правило может быть односторонним) ──")
        for side in ("long", "short"):
            S = X[X.side == side]
            bs = stat(S)
            if not bs:
                continue
            sc = score[S.index]
            print(f"     {side} (база PF {bs['pf']:.2f}):", end="")
            for lo, hi in ((0, 1), (2, 3), (4, 99)):
                m = (sc >= lo) & (sc <= hi)
                s = stat(S[m])
                if s and s["n"] >= 30:
                    print(f"  [{lo}-{hi if hi<99 else '+'}] PF {s['pf']:.2f}"
                          f" ×{s['pf']/bs['pf']:.2f} (n={s['n']})", end="")
            print()

        # форма кривой — главный вердикт
        vals = []
        for lo, hi in ((0, 1), (2, 3), (4, 99)):
            m = (score >= lo) & (score <= hi)
            s = stat(X[m])
            vals.append(s["pf"] / b_all["pf"] if s and s["n"] >= 40 else np.nan)
        v = [x for x in vals if not np.isnan(x)]
        if len(v) >= 3:
            mono_up = v[0] < v[1] < v[2]
            mono_dn = v[0] > v[1] > v[2]
            u_shape = v[1] < v[0] and v[1] < v[2]
            form = ("🟢 МОНОТОННЫЙ РОСТ — подтверждение работает" if mono_up else
                    "🔴 МОНОТОННОЕ ПАДЕНИЕ — согласие старшего ТФ ВРЕДИТ" if mono_dn else
                    "⚠️ U-ОБРАЗНАЯ — работает только край, середина хуже" if u_shape else
                    "⚠️ формы нет — шум")
            print(f"\n   ФОРМА КРИВОЙ: {' → '.join(f'×{x:.2f}' for x in v)}   {form}")

        print("\n   ── по годам (макс конфлюэнция ≥4) ──")
        m = score >= 4
        for y in sorted(X.year.dropna().unique()):
            g = X[X.year == y]
            s, bb = stat(g[m[g.index]]), stat(g)
            if s and bb and bb["pf"] and s["n"] >= 20:
                print(f"     {int(y)}: PF {s['pf']:5.2f} (n={s['n']:>4}) против {bb['pf']:5.2f}"
                      f"  ×{s['pf']/bb['pf']:.2f}  безтоп10% {s['bt']:+7.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
