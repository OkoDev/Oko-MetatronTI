"""
adaptive_target.py — ЦЕЛЬ ДОЛЖНА СЧИТАТЬСЯ ИЗ РЫНКА, А НЕ БЫТЬ КОНСТАНТОЙ (Егор, 29.08.2026).

Формулировка Егора: «механика должна быть умной и гибкой; рынок определяет ликвидность
и волатильность; нет объёмов = нет движения».

Что сейчас: цель боевого `impulse_fib` = **1.618 × амплитуда импульса**, слепая к тому,
есть ли куда идти. Замер 29.08 показал, чем это кончается в 2026:

    ЦЕЛЬ / ЛОКАЛЬНЫЙ КОРИДОР (30 дней):  2024 → 32% · 2025 → 31% · 2026 → 49%

В коридоре шириной 26% цель 12.7% требует пройти половину пути до стены. Фильтр этого
не чинит — он выбирает сделки, но не двигает стену ([[market_2026_no_separability]]).

Здесь сравниваются ПРАВИЛА ЦЕЛИ на ОДНОМ И ТОМ ЖЕ потоке сетапов — меняется только цель,
вход/стоп/гейты неизменны. Иначе сравнивались бы разные выборки.

  fix_1618     боевое, контроль
  fix_1000     1.0 × амплитуда (по [[target_fib_minus1_beats_1618_on_15m]] уже лучше на 15m)
  edge_080     0.8 расстояния до границы коридора 30д — «целься в стену, а не за неё»
  cap          min(1.618×amp, 0.8×до стены) — не жадничать, когда стена близко
  vol_scaled   цель × объёмный множитель: мало объёма → ближе цель (мысль Егора про объём)

🔴 Проверяется на ВСЕХ годах, а не только на 2026. Правило, которое лучше только в 2026, —
подгонка под текущий рынок ([[law_recorded_pf_needs_remeasure]]).

🔴 И ещё: «адаптивное» уже проигрывало — адаптивные ОКНА оказались хуже фиксированных
([[constants_plateau_not_fibonacci]]). Здесь адаптивна ЦЕЛЬ, а не окно, но предупреждение
в силе: если разницы нет, честно сказать, что нет.

    python scripts/adaptive_target.py --symbols 40
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

from research_harness import load, universe, line, stat        # noqa: E402

WAIT, HOLD = 48, 384
LO, HI, COST, PEN = 1.5, 3.234, 0.35, 0.15
RANGE_BARS = 30 * 96          # 30 дней на 15m


def run(syms: list[str]) -> pd.DataFrame:
    from core.smc.impulse_fib import _atr, find_impulses, impulse_points
    out = []
    for sym in syms:
        try:
            df = load(sym, "15m")
        except Exception:                       # noqa: BLE001
            continue
        if df is None or len(df) < 20000:
            continue
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values
        rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        # коридор: ПРОШЛЫЕ 30 дней, сдвиг на бар — причинно
        rhi = pd.Series(H).rolling(RANGE_BARS).max().shift(1).values
        rlo = pd.Series(L).rolling(RANGE_BARS).min().shift(1).values

        # 🔑 ЗИГЗАГИ ИЗ ВОЛНОВОЙ ТЕОРИИ (напоминание Егора 29.08). Канон коррекций:
        #   зигзаг (5-3-5)      C ≈ A, часто 1.618·A — резкая коррекция;
        #   плоскость (3-3-5)   B ≈ A, C ≈ A — боковая;
        #   треугольник         КАЖДАЯ следующая волна МЕНЬШЕ предыдущей.
        # Отсюда прямое объяснение 2026: в боковике доминируют плоскости и треугольники,
        # где волны СЖИМАЮТСЯ, и фиксированная цель 1.618 недостижима ПО ПОСТРОЕНИЮ.
        # Значит цель надо отмерять от ПРЕДЫДУЩЕЙ ноги того же масштаба, а не множителем
        # текущей, а отношение нога/предыдущая — это и есть тип структуры.
        prev_amp = None
        for a, b, up in find_impulses(H, L, C, atr, n):
            if b < RANGE_BARS + 10 or b >= n - HOLD - WAIT - 2:
                _pa, _pb, _am = impulse_points(H, L, C, a, b, up, "extremes")
                prev_amp = _am if _am > 0 else prev_amp
                continue
            if np.isnan(rhi[b]) or np.isnan(rlo[b]):
                continue
            p_a, p_b, amp = impulse_points(H, L, C, a, b, up, "extremes")
            if amp <= 0 or not vm[b] or vm[b] <= 0:
                continue
            vr = float(V[a:b + 1].sum() / (b - a + 1) / vm[b])
            r_ = float(rgv[b]) if not np.isnan(rgv[b]) else 1.0
            trend_ok = (C[b] > ema[b]) if up else (C[b] < ema[b])
            if not (1.0 <= vr < 1.5 and trend_ok and r_ >= 1.1):
                continue
            d = 1.0 if up else -1.0
            e = p_b - d * 0.382 * amp
            sl = e - d * 2.5 * atr[b]
            if (sl >= e) if up else (sl <= e):
                continue
            sp = abs(e - sl) / e * 100
            if not (LO <= sp <= HI):
                continue
            deep = e * (1 - d * PEN / 100)
            w = range(b + 1, min(b + 1 + WAIT, n))
            jf = next((q for q in w if (L[q] <= e if up else H[q] >= e)), None)
            jd = next((q for q in w if (L[q] <= deep if up else H[q] >= deep)), None)
            if jf is None or jd is None:
                continue

            # ── расстояние до СТЕНЫ коридора в сторону сделки ──
            wall = (rhi[b] - e) if up else (e - rlo[b])
            wall = max(float(wall), 0.0)
            volm = float(V[b] / vm[b]) if vm[b] else 1.0
            # тип структуры по канону: сжимаются волны (треугольник/плоскость) или растут
            ratio = (amp / prev_amp) if prev_amp else np.nan

            # 🔴 АДАПТИВНОСТЬ К СТРУКТУРЕ, А НЕ «В ВОЗДУХ» (уточнение Егора 29.08).
            # Отвергнут вариант `vol_scaled` = произвольный множитель 0.5-1.5 по объёму:
            # это подгоняемый коэффициент без опоры на разметку, ровно тот класс, что уже
            # проиграл в [[constants_plateau_not_fibonacci]] (адаптивные окна хуже фиксированных).
            # Оставлены только цели, отмеренные ФИБО ОТ ВОЛНЫ или от границы коридора.
            targets = {
                "fix_1618": 1.618 * amp,                 # боевое, контроль
                "fix_1000": 1.000 * amp,
                "edge_080": 0.80 * wall,                 # до стены коридора
                "cap": min(1.618 * amp, 0.80 * wall),    # не жадничать у стены
                # ── фибо-проекции от ПРЕДЫДУЩЕЙ волны (канон зигзага: C ≈ A) ──
                "prevA_1000": (1.000 * prev_amp) if prev_amp else np.nan,
                "prevA_1618": (1.618 * prev_amp) if prev_amp else np.nan,
                # ── выбор проекции ПО ТИПУ СТРУКТУРЫ ──
                # волны растут (импульсная последовательность) → расширение 1.618·A;
                # волны сжимаются (треугольник/плоскость) → возврат 0.618·A.
                "by_shape": (np.nan if not prev_amp else
                             (1.618 * prev_amp if ratio >= 1.0 else 0.618 * prev_amp)),
            }
            end = min(jf + HOLD, n - 1)
            fh, fl = H[jf + 1:end + 1], L[jf + 1:end + 1]
            if len(fh) == 0:
                continue
            js = (next((k for k in range(len(fl)) if fl[k] <= sl), 10 ** 9) if up
                  else next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9))
            row = dict(sym=sym, year=int(df.index[jf].year),
                       side="long" if up else "short", stop_pct=sp,
                       amp_pct=amp / e * 100, wall_pct=wall / e * 100, volm=volm,
                       leg_ratio=ratio)
            for name, tdist in targets.items():
                if tdist <= 0:
                    row[name] = np.nan
                    continue
                tp = e + d * tdist
                jt = (next((k for k in range(len(fh)) if fh[k] >= tp), 10 ** 9) if up
                      else next((k for k in range(len(fl)) if fl[k] <= tp), 10 ** 9))
                if js <= jt and js < 10 ** 9:
                    r = d * (sl - e) / e * 100
                elif jt < 10 ** 9:
                    r = d * (tp - e) / e * 100
                else:
                    r = d * (float(C[end]) - e) / e * 100
                row[name] = r - COST
            out.append(row)
            prev_amp = amp          # 🔴 иначе «предыдущая волна» замерзает на пропущенных
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    a = ap.parse_args()
    syms = universe("15m", n=a.symbols)
    R = run(syms)
    names = ["fix_1618", "fix_1000", "edge_080", "cap", "prevA_1000", "prevA_1618", "by_shape"]

    print("=" * 104)
    print(f"ПРАВИЛА ЦЕЛИ НА ОДНОМ ПОТОКЕ СЕТАПОВ · 15m · {R.sym.nunique()} монет · {len(R)} сетапов")
    print("=" * 104)
    print(f"  медианы: амплитуда {R.amp_pct.median():.2f}% · стоп {R.stop_pct.median():.2f}% · "
          f"до стены коридора {R.wall_pct.median():.2f}%")
    print(f"  цель 1.618 против стены: цель БОЛЬШЕ расстояния до стены у "
          f"{(1.618 * R.amp_pct > R.wall_pct).mean() * 100:.0f}% сетапов")

    print("\nВСЁ:")
    for nm in names:
        print(line(R.assign(pnl=R[nm]).dropna(subset=["pnl"]), f"  {nm:<12}"))

    print("\nПО ГОДАМ:")
    for y in sorted(R.year.unique()):
        print(f"  {y}:")
        for nm in names:
            g = R[R.year == y].assign(pnl=R[R.year == y][nm]).dropna(subset=["pnl"])
            if len(g) >= 30:
                print(line(g, f"    {nm:<12}"))

    print("\nСТОРОНА:")
    for side in ("long", "short"):
        print(f"  {side}:")
        for nm in names:
            g = R[R.side == side].assign(pnl=R[R.side == side][nm]).dropna(subset=["pnl"])
            if len(g) >= 30:
                print(line(g, f"    {nm:<12}"))

    print("\n🔑 Правило лучше ТОЛЬКО в 2026 — подгонка под текущий рынок, не находка.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
