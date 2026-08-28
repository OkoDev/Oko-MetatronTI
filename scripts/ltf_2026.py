"""
ltf_2026.py — МЕХАНИКА НА МЛАДШЕМ ТФ В 2026 (Егор, 29.08.2026: «волны работают на любом ТФ»).

Цепочка, которая привела сюда, за один абзац. В 2026 механика `impulse_fib` перестала
работать, и ни один фильтр этого не чинит: 10 проверенных осей дают среднее |x−1| = 0.30,
то есть разделения в данных нет вовсе ([[market_2026_no_separability]]). Геометрия сетапов
при этом ОДИНАКОВА во все четыре года (амплитуда 7.9-8.4%, стоп 2.0-2.2%).

Причина нашлась не в признаках, а в масштабе. Разметка Егора на LINK 1D: рынок 2026 ходит
в коридорах по **17%**, сменяющих друг друга. Замер подтвердил на топ-12:

    ЦЕЛЬ / ЛОКАЛЬНЫЙ КОРИДОР      30 дней   45 дней
      2024                           32%       24%
      2025                           31%       22%
      2026                           49%       44%      ← вдвое больше

Цель −1.618 в 2026 требует пройти ПОЛОВИНУ коридора. В 2024-25 хватало четверти.

Отсюда следствие Егора: механика фрактальна, опустить масштаб — цель уменьшится и
поместится в тот же коридор. Проверяем прямо: та же геометрия на 5m против 15m,
ОДИН период (данные 5m: 2025-01 → 2026-05).

🔴 Главный риск, который надо измерить, а не предположить: косты. На младшем ТФ
амплитуда меньше → стоп меньше → те же 0.35% на сделку съедают бОльшую долю хода.
Механика может «заработать» геометрически и умереть на костах
([[live_root_cause_costs_eat_tight_stops]]).

    python scripts/ltf_2026.py --symbols 40
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

# Окна пересчитаны ПО ВРЕМЕНИ, а не по барам: 12 ч ожидания фила, 96 ч удержания.
# Константа в барах, перенесённая между ТФ без пересчёта, — известная ловушка
# ([[twins_15m_stabilized_by_measure]]).
GEOM = {"15m": dict(wait=48, hold=384), "5m": dict(wait=144, hold=1152),
        "3m": dict(wait=240, hold=1920)}
LO, HI, COST, PEN = 1.5, 3.234, 0.35, 0.15
T0, T1 = "2026-01-01", "2026-05-31"


def run(tf: str, syms: list[str], t0: str, t1: str) -> pd.DataFrame:
    from core.smc.impulse_fib import _atr, find_impulses, impulse_points
    g = GEOM[tf]
    out = []
    for sym in syms:
        try:
            df = load(sym, tf)
        except Exception:                      # noqa: BLE001
            continue
        if df is None:
            continue
        df = df[(df.index >= t0) & (df.index <= t1)]
        if len(df) < 3000:
            continue
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values
        rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        for a, b, up in find_impulses(H, L, C, atr, n):
            if b < 400 or b >= n - g["hold"] - g["wait"] - 2:
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
            tp = p_b + d * 1.618 * amp
            sl = e - d * 2.5 * atr[b]
            if (sl >= e) if up else (sl <= e):
                continue
            sp = abs(e - sl) / e * 100
            if not (LO <= sp <= HI):
                continue
            deep = e * (1 - d * PEN / 100)
            w = range(b + 1, min(b + 1 + g["wait"], n))
            jf = next((q for q in w if (L[q] <= e if up else H[q] >= e)), None)
            jd = next((q for q in w if (L[q] <= deep if up else H[q] >= deep)), None)
            if jf is None or jd is None:
                continue
            end = min(jf + g["hold"], n - 1)
            fh, fl = H[jf + 1:end + 1], L[jf + 1:end + 1]
            if len(fh) == 0:
                continue
            if up:
                jt = next((k for k in range(len(fh)) if fh[k] >= tp), 10 ** 9)
                js = next((k for k in range(len(fl)) if fl[k] <= sl), 10 ** 9)
            else:
                jt = next((k for k in range(len(fl)) if fl[k] <= tp), 10 ** 9)
                js = next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9)
            if js <= jt and js < 10 ** 9:
                r = d * (sl - e) / e * 100
            elif jt < 10 ** 9:
                r = d * (tp - e) / e * 100
            else:
                r = d * (float(C[end]) - e) / e * 100
            out.append(dict(sym=sym, year=int(df.index[jf].year),
                            side="long" if up else "short",
                            pnl_gross=r, pnl=r - COST,
                            stop_pct=sp, amp_pct=amp / e * 100,
                            tgt_pct=1.618 * amp / e * 100))
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    a = ap.parse_args()

    syms = universe("5m", n=a.symbols)          # общая вселенная — иначе сравнение нечестное
    print("=" * 104)
    print(f"МЕХАНИКА НА МЛАДШЕМ ТФ · 2026 · период {T0} → {T1} · {len(syms)} монет")
    print("=" * 104)
    print("Одна вселенная, одна геометрия, окна пересчитаны ПО ВРЕМЕНИ (12ч фил / 96ч held).")

    res = {}
    for tf in ("15m", "5m"):
        R = run(tf, syms, T0, T1)
        res[tf] = R
        print(f"\n{tf}: сетапов {len(R)} · монет {R.sym.nunique() if len(R) else 0}")

    print("\n" + "=" * 104)
    print("РЕЗУЛЬТАТ (net, косты 0.35% на сделку)")
    print("=" * 104)
    for tf, R in res.items():
        if len(R):
            print(line(R, f"  {tf:<6}"))
    print("\nСТОРОНА:")
    for side in ("long", "short"):
        for tf, R in res.items():
            if len(R):
                print(line(R[R.side == side], f"  {tf} · {side}"))

    print("\n" + "=" * 104)
    print("🔴 ГЛАВНОЕ: ГЕОМЕТРИЯ И ЦЕНА КОСТОВ")
    print("=" * 104)
    for tf, R in res.items():
        if not len(R):
            continue
        gross = stat(R.assign(pnl=R.pnl_gross))
        net = stat(R)
        cost_share = COST / R.stop_pct.median() * 100
        print(f"  {tf:<5} амплитуда {R.amp_pct.median():5.2f}% · стоп {R.stop_pct.median():5.2f}% · "
              f"цель {R.tgt_pct.median():5.2f}%")
        print(f"        PF ДО костов {gross['pf']:5.2f} → ПОСЛЕ {net['pf']:5.2f}   "
              f"косты = {cost_share:.0f}% от стопа   ср/сделка {R.pnl.mean():+.3f}%")
    print("\n🔑 Цель на младшем ТФ обязана быть МЕНЬШЕ — тогда она помещается в коридор 2026")
    print("   (замер: цель/коридор 30д = 49% на 15m). Если PF не вырос — дело не в масштабе.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
