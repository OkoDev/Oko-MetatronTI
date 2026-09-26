# -*- coding: utf-8 -*-
"""ELLIOTT-LUX — порт ВЫЧИСЛИТЕЛЬНОГО ядра LuxAlgo «Elliott Wave» (Pine v5) в Python.

Источник: Elliott Wave [LuxAlgo], CC BY-NC-SA 4.0 © LuxAlgo (Егор нашёл 23.06).
Портировано ТОЛЬКО ядро (без line/label/box — это TV-визуал):
  • multi-степень pivots (ta.pivothigh/low, leftbars=length, rightbars=1)
  • ZigZag из пивотов (чередование, extend экстремума)
  • isWave — кардинальные правила Эллиотта 1-2-3-4-5 (bull/bear), 1:1 с Pine
  • фибо-зона 0.5/0.618/0.764/0.854 отката волны-5 = OTE-зона входа
  • broken — пробой 0.854 = инвалидация (= наша валидность/untested)

⚠️ Пакетная версия (проход по всем закрытым барам), НЕ бар-в-бар как Pine —
на ЗАКРЫТЫХ барах эквивалентно. Проверяем на SYN 45m против ручной разметки Егора.

Запуск:  python scripts/elliott_lux.py --sym SYNUSDT --tf 45m
"""
from __future__ import annotations
import asyncio, os, sys, argparse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

# фибо-уровни LuxAlgo (i_500/618/764/854)
FIB = (0.5, 0.618, 0.764, 0.854)
STEPS = {1: 4, 2: 8, 3: 16}   # len1/len2/len3 LuxAlgo


def _pivots(hi, lo, left: int, right: int = 1):
    """ta.pivothigh/low: бар-пивот выше/ниже left слева и right справа. → [(i, price, 'H'/'L')]."""
    n = len(hi)
    piv = []
    for i in range(left, n - right):
        seg_l_h = hi[i - left:i]; seg_r_h = hi[i + 1:i + 1 + right]
        if hi[i] > max(seg_l_h) and hi[i] >= max(seg_r_h):
            piv.append((i, float(hi[i]), "H")); continue
        seg_l_l = lo[i - left:i]; seg_r_l = lo[i + 1:i + 1 + right]
        if lo[i] < min(seg_l_l) and lo[i] <= min(seg_r_l):
            piv.append((i, float(lo[i]), "L"))
    return piv


def _zigzag(piv):
    """Чередование H/L; при подряд одном типе — оставить экстремум (как LuxAlgo extend)."""
    zz = []
    for p in piv:
        if not zz:
            zz.append(p); continue
        if p[2] == zz[-1][2]:
            if (p[2] == "H" and p[1] > zz[-1][1]) or (p[2] == "L" and p[1] < zz[-1][1]):
                zz[-1] = p
        else:
            zz.append(p)
    return zz


def _is_wave(p6) -> bool:
    """isWave LuxAlgo 1:1. p6 = 6 zz-точек (волны 1..5). Тип 6-й точки = направление."""
    (_, _1y, _), (_, _2y, _), (_, _3y, _), (_, _4y, _), (_, _5y, _), (_, _6y, t6) = p6
    if t6 == "H":  # bull-импульс (заканчивается вершиной)
        _W1 = _2y - _1y; _W3 = _4y - _3y; _W5 = _6y - _5y
        mn = min(_W1, _W3, _W5)
        return (_W3 != mn) and (_6y > _4y) and (_3y > _1y) and (_5y > _2y)
    else:          # bear-импульс (заканчивается дном)
        _W1 = _1y - _2y; _W3 = _3y - _4y; _W5 = _5y - _6y
        mn = min(_W1, _W3, _W5)
        return (_W3 != mn) and (_4y > _6y) and (_1y > _3y) and (_2y > _5y)


def _fib_zone(start_y, end_y, bull: bool):
    """Фибо отката волны-5 (LuxAlgo barstate.islast). → {fib: price}, 0.854 = глубочайший."""
    diff = abs(end_y - start_y)
    sgn = -1 if bull else 1
    return {f: end_y + sgn * diff * f for f in FIB}


def detect_elliott(df: pd.DataFrame, length: int) -> list[dict]:
    """Найти все импульсы 1-5 одной степени (length). → list (точки, dir, fib-зона, broken)."""
    d = df.copy(); d.columns = [c.lower() for c in d.columns]
    hi = d["high"].values; lo = d["low"].values; n = len(d)
    zz = _zigzag(_pivots(hi, lo, length))
    if len(zz) < 6:
        return []
    out = []
    for k in range(5, len(zz)):
        p6 = zz[k - 5:k + 1]
        if not _is_wave(p6):
            continue
        bull = p6[-1][2] == "H"
        start_i, start_y = p6[0][0], p6[0][1]   # начало волны-1
        end_i, end_y = p6[-1][0], p6[-1][1]      # конец волны-5
        fib = _fib_zone(start_y, end_y, bull)
        f854 = fib[0.854]
        # broken: после конца волны-5 цена пробила 0.854 (инвалидация зоны)
        broken = False
        for j in range(end_i + 1, n):
            if (bull and lo[j] < f854) or (not bull and hi[j] > f854):
                broken = True; break
        zlo = min(fib[0.5], fib[0.854]); zhi = max(fib[0.5], fib[0.854])
        out.append({
            "length": length, "dir": "bull" if bull else "bear",
            "w1_start_i": start_i, "w1_start": start_y,
            "w5_end_i": end_i, "w5_end": end_y,
            "span_pct": abs(end_y - start_y) / start_y * 100 if start_y else 0,
            "fib": fib, "ote_lo": zlo, "ote_hi": zhi, "broken": broken,
            "f705_like": fib[0.764],   # 0.764 LuxAlgo ≈ наш OTE 0.705
        })
    return out


def detect_all_steps(df: pd.DataFrame) -> dict[int, list[dict]]:
    return {lvl: detect_elliott(df, ln) for lvl, ln in STEPS.items()}


async def _load(rt, sym: str, tf: str, limit: int):
    """OHLCV с datetime-index. 45m не поддержан BingX → ресемпл из 15m×3."""
    df = await rt.get_ohlcv(sym, timeframe=tf, limit=min(limit, 1000))  # BingX cap (1d~700)
    if df is not None and not df.empty:
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], unit="ms"))
        return df
    if tf == "45m":
        base = await rt.get_ohlcv(sym, timeframe="15m", limit=min(1440, limit * 3))
        if base is not None and not base.empty:
            base = base.set_index(pd.to_datetime(base["time"], unit="ms"))
            agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            return base.resample("45min").agg(agg).dropna()
    return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", type=str, default="SYNUSDT")
    ap.add_argument("--tf", type=str, default="45m")
    ap.add_argument("--limit", type=int, default=1500)
    args = ap.parse_args()
    from core.infra.data_collector import RealTimeData

    sym = args.sym.replace("-", "").upper()
    rt = RealTimeData()
    df = await _load(rt, sym, args.tf, args.limit)
    await rt.close()
    if df is None or df.empty:
        print("нет данных"); return
    price = float(df["close"].iloc[-1])
    print(f"ELLIOTT-LUX  {sym} {args.tf}  баров={len(df)}  цена={price:.6f}")

    steps = detect_all_steps(df)
    for lvl, ln in STEPS.items():
        imps = steps[lvl]
        live = [s for s in imps if not s["broken"]]
        print(f"\n=== СТЕПЕНЬ {lvl} (length={ln}): импульсов={len(imps)}, живых(not broken)={len(live)} ===")
        # последние 5 импульсов этой степени
        for s in imps[-5:]:
            in_zone = s["ote_lo"] <= price <= s["ote_hi"]
            mark = " <-- ЦЕНА В OTE" if in_zone else ""
            flag = "BROKEN" if s["broken"] else "valid "
            arrow = "↑" if s["dir"] == "bull" else "↓"
            print(f"  {arrow}{s['dir']:4} [{flag}] волна1→5: {s['w1_start']:.6f}→{s['w5_end']:.6f} "
                  f"({s['span_pct']:.0f}%)  OTE {s['ote_lo']:.6f}–{s['ote_hi']:.6f} "
                  f"(0.764={s['f705_like']:.6f}){mark}")


if __name__ == "__main__":
    asyncio.run(main())
