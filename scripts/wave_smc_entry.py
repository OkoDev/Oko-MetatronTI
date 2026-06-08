#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Wave+SMC Entry Analyzer — где входить по связке Волна + SMC + OTE + Пивоты.

Объединяет валидированную связку (memory/wave_smc_backtest_validated.md, edge +0.45..+0.72R):
  • Волна Эллиотта (detect_elliott_impulse) — фаза: импульс/откат, направление
  • SMC (detect_structure_breaks, length=5 эталон OKO-SM) — CHoCH(разворот)/BOS(тренд)
  • OTE Фибо-зоны (0.618/0.705/0.786) последнего движения — конфлюэнция между TF
  • Пивоты (calculate_pivot_points) — daily PP/S/R как уровни поддержки/сопротивления
  → MTF-синтез: контекст (HTF) + зона входа (конфлюэнция) + SL/TP/RR

Использование:
  python scripts/wave_smc_entry.py XLM
  python scripts/wave_smc_entry.py BTC --side LONG
  python scripts/wave_smc_entry.py SOL --tfs 4h,1h,15m,5m
"""
import sys, argparse
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import ccxt
import pandas as pd
from core.smc.smc_engine import (
    zigzag_atr, detect_elliott_impulse, detect_structure_breaks, _zz_typed,
)
from core.indicators.indicators import calculate_pivot_points

FIB = (0.618, 0.705, 0.786)  # OTE-зона


def fetch(ex, sym, tf, lim):
    o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=lim)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def wave_phase(df):
    """Фаза по последнему импульсу. → dict(dir, retr_pct, textbook) или None."""
    li = None
    for dev in (3.0, 5.0):
        for imp in detect_elliott_impulse(zigzag_atr(df, 11, dev)):
            if li is None or imp["waves"][-1][0] > li["waves"][-1][0]:
                li = imp
    if not li:
        return None
    price = df["close"].iloc[-1]
    d = li["direction"]; w5 = li["waves"][-1][1]; w0 = li["waves"][0][1]
    if d == "down":
        retr = (price - w5) / (w0 - w5) * 100 if w0 != w5 else 0
    else:
        retr = (w5 - price) / (w5 - w0) * 100 if w5 != w0 else 0
    return dict(dir=d, retr=retr, textbook=li["textbook"], w0=w0, w5=w5)


def smc_state(df):
    """Последний слом структуры. → dict(kind, direction, level, bars_ago, vol)."""
    brks = detect_structure_breaks(df, length=5)
    if not brks:
        return None
    last = brks[-1]; n = len(df)
    return dict(kind=last.kind, direction=last.direction, level=last.price,
                bars_ago=n - 1 - last.idx, vol=last.has_volume)


def ote_zone(df):
    """OTE-зона последнего восходящего движения (для LONG-отката). → dict или None."""
    zz = zigzag_atr(df, 11, 3.0); typed = _zz_typed(zz)
    sw = [(p, t) for _, p, t in typed]
    move = None  # последняя пара L→H (движение вверх) и H→L (вниз)
    for i in range(len(sw) - 1, 0, -1):
        if sw[i][1] == "H" and sw[i - 1][1] == "L":
            move = ("up", sw[i - 1][0], sw[i][0]); break
        if sw[i][1] == "L" and sw[i - 1][1] == "H":
            move = ("down", sw[i - 1][0], sw[i][0]); break
    if not move:
        return None
    direction, a, b = move
    rng = abs(b - a)
    if direction == "up":  # откат LONG = вниз от high
        zones = {f: b - f * rng for f in FIB}
    else:                  # откат SHORT = вверх от low
        zones = {f: b + f * rng for f in FIB}
    return dict(dir=direction, a=a, b=b, zones=zones)


def daily_pivots(ex, sym):
    """Daily-пивоты по предыдущей завершённой дневной свече."""
    df = fetch(ex, sym, "1d", 5)
    prev = df.iloc[-2]  # предыдущая завершённая
    return calculate_pivot_points(float(prev["high"]), float(prev["low"]), float(prev["close"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tfs", default="1d,4h,1h,15m,5m,3m")
    ap.add_argument("--side", default="auto", choices=["auto", "LONG", "SHORT"])
    a = ap.parse_args()
    sym = a.symbol.upper()
    tfs = a.tfs.split(",")
    ex = ccxt.bingx()
    price = ex.fetch_ticker(f"{sym}/USDT:USDT")["last"]

    print(f"\n{'='*70}")
    print(f"  {sym} — Wave+SMC Entry Analyzer   цена={price:.5f}")
    print(f"{'='*70}\n")

    # ── MTF таблица: волна + SMC ──
    lims = {"1d": 200, "4h": 300, "1h": 400, "15m": 400, "5m": 500, "3m": 500}
    htf_dir = []  # старшие TF направление импульса
    ote_all = {}
    print("  TF    волна                  SMC (length=5)")
    print("  " + "-" * 64)
    for tf in tfs:
        try:
            df = fetch(ex, sym, tf, lims.get(tf, 400))
        except Exception as e:
            print(f"  {tf:<5} err {str(e)[:40]}"); continue
        w = wave_phase(df); s = smc_state(df); oz = ote_zone(df)
        ote_all[tf] = oz
        if w:
            wd = "↓" if w["dir"] == "down" else "↑"
            wstr = f"ИМП{wd}{'✓' if w['textbook'] else ''} откат{w['retr']:.0f}%"
            if tf in ("1d", "4h", "1h"):
                htf_dir.append(w["dir"])
        else:
            wstr = "?"
        sstr = (f"{s['kind']} {s['direction']}{'+V' if s['vol'] else ''} "
                f"@{s['level']:.5f} ({s['bars_ago']}бар)") if s else "—"
        print(f"  {tf:<5} {wstr:<22} {sstr}")

    # ── OTE Фибо-зоны (собираем точки для конфлюэнции) ──
    print(f"\n  ── OTE Фибо-зоны (откат последнего движения) ──")
    pts = []  # (источник, метка, уровень)
    for tf in ("4h", "1h", "15m"):
        oz = ote_all.get(tf)
        if oz:
            z = oz["zones"]
            tag = "LONG-откат" if oz["dir"] == "up" else "SHORT-откат"
            print(f"  {tf:<5} [{tag}] 0.618={z[0.618]:.5f} 0.705={z[0.705]:.5f} 0.786={z[0.786]:.5f}")
            for f in FIB:
                pts.append((f"{tf}", f"OTE{f}", z[f]))

    # ── Пивоты (тоже в конфлюэнцию) ──
    try:
        piv = daily_pivots(ex, sym)
        print(f"\n  ── Daily Pivots (вчерашняя свеча) ──")
        for k in ["R3", "R2", "R1", "PP", "S1", "S2", "S3"]:
            if k in piv:
                v = piv[k]; dist = (v - price) / price * 100
                mark = " ← цена" if abs(dist) < 0.5 else ""
                print(f"      {k:>3} {v:.5f}  ({dist:+.1f}%){mark}")
                pts.append(("PIV", k, v))
    except Exception as e:
        print(f"  пивоты err: {str(e)[:40]}")

    # ── Конфлюэнция (OTE × OTE × Пивоты), уровни ближе 1% ──
    confl = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if pts[i][0] != pts[j][0] and abs(pts[i][2] - pts[j][2]) / price < 0.01:
                confl.append((round((pts[i][2] + pts[j][2]) / 2, 5),
                              f"{pts[i][0]}-{pts[i][1]} × {pts[j][0]}-{pts[j][1]}"))
    if confl:
        print(f"\n  🎯 КОНФЛЮЭНЦИЯ (сильные зоны — Фибо × Пивоты):")
        for lvl, src in sorted(set(confl)):
            dist = (lvl - price) / price * 100
            print(f"      {lvl:.5f}  ({dist:+.1f}%)  [{src}]")

    # ── Синтез ──
    print(f"\n  {'─'*64}")
    print(f"  ВЕРДИКТ:")
    if htf_dir:
        dn = htf_dir.count("down"); up = htf_dir.count("up")
        if dn > up:
            print(f"    HTF контекст: НИСХОДЯЩИЙ ({dn}↓/{up}↑) → LONG=осторожно(против), SHORT по тренду")
        elif up > dn:
            print(f"    HTF контекст: ВОСХОДЯЩИЙ ({up}↑/{dn}↓) → LONG по тренду, SHORT=осторожно")
        else:
            print(f"    HTF контекст: смешанный ({up}↑/{dn}↓) → ждать ясности")
    else:
        print(f"    HTF: импульс не классифицирован (коррекция/боковик) → low-confidence")
    print(f"    Вход: зона конфлюэнции Фибо + LTF (3m/5m) CHoCH в сторону входа = триггер")
    print(f"    SL: за дальнюю границу OTE (0.786) / swing. TP: к противоположному пивоту/high")
    print()


if __name__ == "__main__":
    main()
