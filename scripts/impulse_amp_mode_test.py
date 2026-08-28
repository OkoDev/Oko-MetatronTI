"""
impulse_amp_mode_test.py — ход по CLOSE против хода по ЭКСТРЕМУМАМ.

Команда Егора (28.08.2026): «детектор на экстремумы менять! это важно!».
Правка боевая: амплитуда задаёт вход по фибо, стоп и цель у ВСЕХ сетапов.
Полная замена детектора однажды уже обрушила выборку (2.82 → 0.75), поэтому
сначала замер обеих версий на ОДНОЙ боевой геометрии, потом смена дефолта.

Механика — боевая `impulse_fib`: три гейта, зона стопа 1.5-3.234%, вход лимитом
0.382, цель −1.618, стоп 2.5·ATR. Отличается ТОЛЬКО способ измерения хода.

    python scripts/impulse_amp_mode_test.py --tf 15m --symbols 30
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

from research_harness import load, universe, stat, line       # noqa: E402

GEOM = {"1h": dict(wait=12, hold=96), "15m": dict(wait=48, hold=384)}
LO, HI, COST, PEN = 1.5, 3.234, 0.35, 0.15


def run(tf: str, n_symbols: int, amp_mode: str,
        min_atr: float | None = None,
        max_retr: float | None = None) -> pd.DataFrame:
    from core.smc.impulse_fib import _atr, find_impulses, impulse_points
    g = GEOM[tf]
    out = []
    for sym in universe(tf, n=n_symbols):
        df = load(sym, tf)
        if len(df) < 12000:
            continue
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values
        rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        kw = {}
        if min_atr is not None: kw['min_atr'] = min_atr
        if max_retr is not None: kw['max_retr'] = max_retr
        for a, b, up in find_impulses(H, L, C, atr, n, amp_mode=amp_mode, **kw):
            if b < 400 or b >= n - g["hold"] - g["wait"] - 2:
                continue
            p_a, p_b, amp = impulse_points(H, L, C, a, b, up, amp_mode)
            if amp <= 0 or not vm[b] or vm[b] <= 0:
                continue
            vr = float(V[a:b + 1].sum() / (b - a + 1) / vm[b])
            r_ = float(rgv[b]) if not np.isnan(rgv[b]) else 1.0
            trend_ok = (C[b] > ema[b]) if up else (C[b] < ema[b])
            if not (1.0 <= vr < 1.5 and trend_ok and r_ >= 1.1):
                continue
            d = 1.0 if up else -1.0
            e = p_b - d * 0.382 * amp          # вход отмеряется от КОНЦА хода
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
                            pnl=r - COST, stop_pct=sp, amp_pct=amp / e * 100,
                            key=f"{sym}|{b}"))
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m", choices=["15m", "1h"])
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--calib", action="store_true",
                    help="extremes с ПЕРЕКАЛИБРОВАННЫМ MIN_ATR (равный поток)")
    a = ap.parse_args()

    print("=" * 104)
    print(f"ХОД ПО CLOSE ПРОТИВ ХОДА ПО ЭКСТРЕМУМАМ · ТФ {a.tf} · {a.symbols} монет")
    print("Геометрия боевая, отличается ТОЛЬКО способ измерения хода.")
    print("=" * 104)
    res = {}
    # 🔴 ЧЕСТНОЕ СРАВНЕНИЕ ТРЕБУЕТ РАВНОЙ СТРОГОСТИ ПОРОГА.
    # `MIN_ATR=3.0` калиброван под амплитуду по CLOSE. Ход по экстремумам
    # больше медианно в 1.18× → тот же порог становится СЛАБЕЕ, и в выборку
    # заходит то, что раньше отсеивалось. Поэтому «extremes хуже» может
    # означать «фильтр ослаб», а не «измерение неверно». Режим --calib
    # поднимает порог на ту же 1.18×, уравнивая строгость.
    # 🔴 УЗКОЕ МЕСТО — НЕ MIN_ATR, А MAX_RETR. Проверено прямым замером:
    # подъём min_atr 3.0→3.54 меняет выборку на 2.6%, а режим — на 87%.
    # Причина: `max_retr` сравнивает контр-откат (по H/L) с ХОДОМ. В режиме
    # extremes ход больше → отношение меньше → фильтр ЧИСТОТЫ хода слабеет,
    # и внутрь заходят рваные движения. Эквивалент боевого 0.35 ≈ 0.32.
    modes = [("close", None, None), ("extremes", None, None)]
    if a.calib:
        modes.append(("extremes", None, 0.32))
    for mode, matr, mretr in modes:
        R = run(a.tf, a.symbols, mode, matr, mretr)
        key = mode if mretr is None else f"{mode}·retr{mretr}"
        res[key] = R
        print(f"\n{key}: сетапов {len(R)} · монет "
              f"{R.sym.nunique() if len(R) else 0}")

    print("\n" + "=" * 104)
    print("ОБЩИЙ РЕЗУЛЬТАТ")
    print("=" * 104)
    for mode, R in res.items():
        if len(R):
            print(line(R, f"  {mode:<9}"))

    print("\nСТОРОНА:")
    for side in ("long", "short"):
        for mode, R in res.items():
            if len(R):
                print(line(R[R.side == side], f"  {side} · {mode}"))

    print("\nГОД:")
    years = sorted(set(res["close"].year.unique()) | set(res["extremes"].year.unique()))
    for y in years:
        for mode, R in res.items():
            if len(R):
                print(line(R[R.year == y], f"  {y} · {mode}"))

    print("\n" + "=" * 104)
    print("ЧТО ИЗМЕНИЛОСЬ В САМОЙ ВЫБОРКЕ")
    print("=" * 104)
    kc, ke = set(res["close"].key), set(res["extremes"].key)
    print(f"  сетапов только у close:     {len(kc - ke)}")
    print(f"  сетапов только у extremes:  {len(ke - kc)}")
    print(f"  общих:                      {len(kc & ke)}")
    if len(res["close"]) and len(res["extremes"]):
        print(f"  медианная амплитуда: close {res['close'].amp_pct.median():.2f}% · "
              f"extremes {res['extremes'].amp_pct.median():.2f}%")
        print(f"  медианный стоп:      close {res['close'].stop_pct.median():.2f}% · "
              f"extremes {res['extremes'].stop_pct.median():.2f}%")
    print("\n🔑 Смена режима меняет НАБОР сетапов, а не только их цены: другой ход →")
    print("   другой вход → другой стоп → часть выпадает из зоны 1.5-3.234%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
