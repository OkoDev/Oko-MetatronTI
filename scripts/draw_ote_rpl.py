"""Визуализация OTE сетапа RPL/USDT (4h→1h SHORT 26.06.2026)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timezone, timedelta

SYMBOL  = "RPL/USDT:USDT"
HTF     = "4h"
LTF     = "1h"
LIMIT   = 200          # баров каждого ТФ
OUT_HTF = "scripts/rpl_ote_4h.png"
OUT_LTF = "scripts/rpl_ote_1h.png"

# ── данные из кэша бота ─────────────────────────────────────────────────────
def get_data(tf, limit):
    import ccxt
    from dotenv import load_dotenv; load_dotenv()
    import os
    ex = ccxt.bingx({
        "apiKey": os.getenv("BINGX_API_KEY", ""),
        "secret": os.getenv("BINGX_SECRET", ""),
        "options": {"defaultType": "swap"},
    })
    bars = ex.fetch_ohlcv(SYMBOL, tf, limit=limit)
    df = pd.DataFrame(bars, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").astype(float)
    return df

# ── OTE зоны ────────────────────────────────────────────────────────────────
def ote_levels(swing_lo, swing_hi, direction):
    """Фибо уровни OTE (0.382, 0.5, 0.618, 0.786) + zone 0.618-0.786."""
    rng = swing_hi - swing_lo
    if direction == "short":   # откат вверх внутри нисходящего импульса
        fibs = {k: swing_hi - rng * k for k in [0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}
        zone_lo = swing_hi - rng * 0.786
        zone_hi = swing_hi - rng * 0.382
    else:                      # откат вниз внутри восходящего импульса
        fibs = {k: swing_lo + rng * k for k in [0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}
        zone_lo = swing_lo + rng * 0.382
        zone_hi = swing_lo + rng * 0.786
    return fibs, zone_lo, zone_hi

def draw_chart(df, title, out, *, swing_lo=None, swing_hi=None, direction=None,
               entry=None, sl=None, tp=None, actual_entry=None,
               choch_time=None, zone_lo=None, zone_hi=None, htf_zone=None):

    fibs, z_lo, z_hi = (None, None, None)
    if swing_lo and swing_hi and direction:
        fibs, z_lo, z_hi = ote_levels(swing_lo, swing_hi, direction)
    if zone_lo: z_lo = zone_lo
    if zone_hi: z_hi = zone_hi

    ap = []
    colors = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                                   edge="inherit", wick="inherit", volume="inherit")
    s = mpf.make_mpf_style(marketcolors=colors, gridstyle="--",
                           gridcolor="#2a2a2a", facecolor="#131722",
                           figcolor="#131722", rc={"axes.labelcolor":"#aaa",
                                                   "xtick.color":"#aaa","ytick.color":"#aaa"})

    # OTE зона (полупрозрачный прямоугольник через hlines пару)
    if z_lo and z_hi:
        ap.append(mpf.make_addplot(
            pd.Series(z_hi, index=df.index), color="#f59e0b", alpha=0.25,
            linestyle="--", width=1.2, panel=0))
        ap.append(mpf.make_addplot(
            pd.Series(z_lo, index=df.index), color="#f59e0b", alpha=0.25,
            linestyle="--", width=1.2, panel=0))

    # SL / TP / entry
    if sl:
        ap.append(mpf.make_addplot(
            pd.Series(sl, index=df.index), color="#ef5350", linestyle="-", width=1.2, panel=0))
    if tp:
        ap.append(mpf.make_addplot(
            pd.Series(tp, index=df.index), color="#26a69a", linestyle="-", width=1.2, panel=0))
    if entry:
        ap.append(mpf.make_addplot(
            pd.Series(entry, index=df.index), color="#bb86fc", linestyle=":", width=1.5, panel=0))
    if actual_entry:
        ap.append(mpf.make_addplot(
            pd.Series(actual_entry, index=df.index), color="#ff9800", linestyle="-.", width=1.5, panel=0))

    # HTF зона (если рисуем LTF)
    if htf_zone:
        ap.append(mpf.make_addplot(
            pd.Series(htf_zone[1], index=df.index), color="#64b5f6", alpha=0.3,
            linestyle=":", width=1, panel=0))
        ap.append(mpf.make_addplot(
            pd.Series(htf_zone[0], index=df.index), color="#64b5f6", alpha=0.3,
            linestyle=":", width=1, panel=0))

    fig, axes = mpf.plot(df, type="candle", style=s, addplot=ap,
                         title=title, returnfig=True, figsize=(18, 9),
                         volume=True, tight_layout=True)

    ax = axes[0]

    # Заливка OTE зоны
    if z_lo and z_hi:
        ax.axhspan(z_lo, z_hi, alpha=0.08, color="#f59e0b", label=f"OTE zone {z_lo:.4f}–{z_hi:.4f}")

    # CHoCH вертикальная линия
    if choch_time:
        try:
            ct = pd.Timestamp(choch_time, tz="UTC")
            if ct in df.index:
                xi = df.index.get_loc(ct)
            else:
                xi = df.index.searchsorted(ct)
            ax.axvline(xi, color="#9c27b0", linestyle="--", alpha=0.7, linewidth=1.5, label="CHoCH")
        except Exception:
            pass

    # Аннотации уровней
    xr = len(df) - 1
    for label, val, color in [
        ("SL",    sl,           "#ef5350"),
        ("TP",    tp,           "#26a69a"),
        ("entry_sig", entry,    "#bb86fc"),
        ("actual", actual_entry, "#ff9800"),
        ("zone_hi", z_hi,      "#f59e0b"),
        ("zone_lo", z_lo,      "#f59e0b"),
    ]:
        if val:
            ax.annotate(f" {label} {val:.4f}", xy=(xr, val),
                        xycoords=("data","data"), fontsize=7.5,
                        color=color, va="center")

    # Свинг HIGH/LOW маркеры
    if swing_hi:
        xi_hi = df["high"].idxmax()
        ax.annotate(f"Swing H\n{swing_hi:.4f}",
                    xy=(df.index.get_loc(xi_hi), swing_hi), fontsize=7, color="#64b5f6",
                    ha="center", va="bottom")
    if swing_lo:
        xi_lo = df["low"].idxmin()
        ax.annotate(f"Swing L\n{swing_lo:.4f}",
                    xy=(df.index.get_loc(xi_lo), swing_lo), fontsize=7, color="#64b5f6",
                    ha="center", va="top")

    ax.legend(loc="upper left", fontsize=7, framealpha=0.4, labelcolor="white")
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    print(f"Saved: {out}")

# ── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Загружаю данные RPL 4h и 1h...")
    df4h = get_data(HTF, LIMIT)
    df1h = get_data(LTF, LIMIT)

    print(f"4h: {len(df4h)} баров, {df4h.index[0]} … {df4h.index[-1]}")
    print(f"1h: {len(df1h)} баров, {df1h.index[0]} … {df1h.index[-1]}")

    # Параметры сделки из БД
    ENTRY_SIG    = 1.32806
    ACTUAL_ENTRY = 1.305
    SL           = 1.3255391
    TP           = 1.1930705
    CHOCH_TS     = None    # заполним из oko_ote если найдём

    # Попробуем запустить сам детектор чтобы получить реальные зоны
    try:
        from core.smc.oko_ote import oko_ote
        print("Запускаю oko_ote на реальных данных...")
        sig = oko_ote(
            symbol=SYMBOL,
            df_zone=df4h,
            df_break=df1h,
            zone_tf=HTF,
            break_tf=LTF,
            only_latest=False,      # бэктест — все сетапы
        )
        if sig:
            sigs = sig if isinstance(sig, list) else [sig]
            # Берём ближайший к нашей сделке (05:59 UTC 26.06)
            target_ts = pd.Timestamp("2026-06-26 05:59:00", tz="UTC")
            short_sigs = [s for s in sigs if s.direction == "short"]
            print(f"  Найдено SHORT сетапов: {len(short_sigs)}")
            if short_sigs:
                # ближайший по entry_ts
                def dist(s):
                    try: return abs(pd.Timestamp(s.entry_ts, tz="UTC") - target_ts)
                    except: return timedelta(days=999)
                best = min(short_sigs, key=dist)
                print(f"  Лучший: entry={best.entry:.5f} sl={best.sl:.5f} tp={best.tp:.5f}")
                print(f"  zone_lo={best.zone_lo:.5f} zone_hi={best.zone_hi:.5f}")
                print(f"  choch_ts={best.choch_ts}")
                CHOCH_TS  = best.choch_ts
                ENTRY_SIG = best.entry
                SL        = best.sl
                TP        = best.tp
        else:
            print("  oko_ote вернул None — рисуем из БД")
    except Exception as e:
        print(f"  oko_ote ошибка: {e}")

    # Найдём swing high/low в 4h данных вокруг даты сделки
    cutoff = pd.Timestamp("2026-06-26 06:00:00", tz="UTC")
    df4h_cut = df4h[df4h.index <= cutoff]
    # Для SHORT: ищем свинговый максимум (откуда пошёл импульс вниз)
    # Грубо — топ за последние 60 баров 4h
    window4h = df4h_cut.tail(80)
    swing_h4 = float(window4h["high"].max())
    swing_l4 = float(window4h["low"].min())

    print(f"\nSwing 4h window: HIGH={swing_h4:.4f} LOW={swing_l4:.4f}")

    # 4h chart
    draw_chart(
        df4h_cut.tail(80), f"RPL/USDT 4h — OTE зона | SHORT 26.06.2026", OUT_HTF,
        swing_lo=swing_l4, swing_hi=swing_h4, direction="short",
        entry=ENTRY_SIG, sl=SL, tp=TP, actual_entry=ACTUAL_ENTRY,
        choch_time=None,
    )

    # 1h chart (зона входа)
    df1h_cut = df1h[df1h.index <= cutoff].tail(120)
    window1h = df1h_cut.tail(120)
    swing_h1 = float(window1h["high"].max())
    swing_l1 = float(window1h["low"].min())

    # OTE зона для 1h (та же что детектор выдал)
    _, z_lo, z_hi = ote_levels(swing_l1, swing_h1, "short")

    draw_chart(
        df1h_cut, f"RPL/USDT 1h — CHoCH + вход | SHORT 26.06.2026", OUT_LTF,
        swing_lo=swing_l1, swing_hi=swing_h1, direction="short",
        entry=ENTRY_SIG, sl=SL, tp=TP, actual_entry=ACTUAL_ENTRY,
        choch_time=CHOCH_TS,
        zone_lo=z_lo, zone_hi=z_hi,
        htf_zone=(swing_l4 * 0.382 + swing_h4 * 0.618, swing_h4 - (swing_h4-swing_l4)*0.382),
    )

    print("\nГотово! Открой:")
    print(f"  {OUT_HTF}")
    print(f"  {OUT_LTF}")
