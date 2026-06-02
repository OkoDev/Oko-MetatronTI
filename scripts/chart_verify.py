# -*- coding: utf-8 -*-
"""Визуальный верификатор наработок — рисует чарт с overlay для сверки с OKO-SM.

Цель: пользователь сверяет ВИЗУАЛЬНО (не только численно) — совпадают ли свинги/
ZigZag/OTE/Fib/SMC-структура с тем, что он видит в индикаторе OKO-SM на TradingView.

Слои (каждый опционален, передаётся как аргумент):
  swings_major/minor : [(idx_or_ts, price, 'H'/'L'), ...] — точки свингов (значимые/мелкие)
  zigzag             : [(ts, price), ...] — ломаная ZigZag
  hlines             : {label: price} — горизонтальные уровни (Fib/OTE/pivots/EQH)
  zones              : [(y_low, y_high, color, label)] — зоны (OTE, premium/discount, FVG)
  boxes              : [(ts_left, y_top, ts_right, y_bottom, color, label)] — OB/FVG боксы

Использование (из любого скрипта-наработки):
  from scripts.chart_verify import render_verify
  render_verify(df, "BTC 4h — swings", swings_major=[...], zigzag=[...], out="e:/tmp/v.png")

CLI smoke: python scripts/chart_verify.py  (рисует BTC 4h без слоёв — проверка рендера)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mplfinance as mpf
except Exception as e:  # pragma: no cover
    print(f"графич. либы недоступны: {e}")
    raise


def render_verify(
    df: pd.DataFrame,
    title: str,
    swings_major: Optional[list] = None,   # [(ts, price, 'H'/'L')]
    swings_minor: Optional[list] = None,
    zigzag: Optional[list] = None,         # [(ts, price)]
    hlines: Optional[dict] = None,         # {label: price}
    zones: Optional[list] = None,          # [(y_low, y_high, color, label)]
    labels: Optional[list] = None,         # [(ts, price, text)] — метки HH/HL/LH/LL
    hsegments: Optional[list] = None,      # [(ts_from, ts_to, price, color, label)] — линии BOS/CHoCH
    boxes: Optional[list] = None,          # [(ts_left, top, bottom, color, label)] — OB/FVG боксы (extend вправо)
    out: str = "tmp_charts/chart_verify.png",
) -> str:
    """Рисует candlestick + overlay-слои → PNG. df: DatetimeIndex + OHLC."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        if "ts" in d.columns:
            d.index = pd.to_datetime(d["ts"], unit="ms", utc=True)
    d = d[["open", "high", "low", "close"] + (["volume"] if "volume" in d.columns else [])]

    addplots = []
    # свинги — scatter поверх (major крупнее)
    for sw, marker, size, col in ((swings_major, "^", 90, "#00d4ff"), (swings_minor, ".", 30, "#888")):
        if not sw:
            continue
        ser = pd.Series(index=d.index, dtype=float)
        for ts, price, _hl in sw:
            key = ts if ts in d.index else (d.index[ts] if isinstance(ts, int) and ts < len(d) else None)
            if key is not None:
                ser.loc[key] = price
        if ser.notna().any():
            addplots.append(mpf.make_addplot(ser, type="scatter", markersize=size, marker=marker, color=col))

    # ZigZag — ломаная через alines (белый Dotted, как OKO-SM Waves)
    alines = None
    if zigzag and len(zigzag) >= 2:
        pts = [(ts, p) for ts, p in zigzag if ts in d.index]
        if len(pts) >= 2:
            alines = dict(alines=pts, colors=["#ffffff"], linewidths=[1.4], linestyle=":", alpha=0.95)

    hl = None
    if hlines:
        hl = dict(hlines=list(hlines.values()), colors=["#bbbbbb"] * len(hlines),
                  linestyle="--", linewidths=0.7)

    style = mpf.make_mpf_style(base_mpf_style="nightclouds", facecolor="#131722", gridcolor="#222")
    kw = dict(type="candle", style=style, title=title, ylabel="", figratio=(16, 9),
              figscale=1.4, returnfig=True, tight_layout=True)
    if addplots:
        kw["addplot"] = addplots
    if alines:
        kw["alines"] = alines
    if hl:
        kw["hlines"] = hl

    fig, axes = mpf.plot(d, **kw)
    # зоны (OTE/premium/discount) — горизонтальные полосы
    if zones:
        ax = axes[0]
        for y_low, y_high, color, label in zones:
            ax.axhspan(y_low, y_high, color=color, alpha=0.15)
            ax.text(0.01, (y_low + y_high) / 2, label, transform=ax.get_yaxis_transform(),
                    color=color, fontsize=8, va="center")
    # OB/FVG боксы (прямоугольник от left до правого края, extend вправо)
    if boxes:
        from matplotlib.patches import Rectangle
        ax = axes[0]
        posb = {ts: k for k, ts in enumerate(d.index)}
        x_right = len(d) - 1
        for bx in boxes:
            ts_left, top, bottom, color, label = bx
            xl = posb.get(ts_left)
            if xl is None:
                continue
            ax.add_patch(Rectangle((xl, bottom), x_right - xl, top - bottom,
                                    facecolor=color, edgecolor=color, alpha=0.22, linewidth=0.6))
            ax.annotate(label, (xl, (top + bottom) / 2), color=color, fontsize=6,
                        ha="right", va="center", xytext=(-2, 0), textcoords="offset points")

    # горизонтальные линии BOS/CHoCH (от свинга до пробоя, пунктир + метка) — как OKO-SM
    if hsegments:
        ax = axes[0]
        posh = {ts: k for k, ts in enumerate(d.index)}
        for seg in hsegments:
            ts_from, ts_to, price, color, label = seg
            x1, x2 = posh.get(ts_from), posh.get(ts_to)
            if x1 is None or x2 is None:
                continue
            ax.plot([x1, x2], [price, price], "--", color=color, linewidth=1.0, alpha=0.9)
            ax.annotate(label, (x2, price), color=color, fontsize=7, fontweight="bold",
                        ha="left", va="center", xytext=(3, 0), textcoords="offset points")

    # текстовые метки HH/HL/LH/LL — по позиции бара (x = iloc)
    if labels:
        ax = axes[0]
        pos = {ts: k for k, ts in enumerate(d.index)}
        for lab in labels:
            ts, price, text = lab[0], lab[1], lab[2]
            col = lab[3] if len(lab) > 3 else ("#f23645" if text in ("LH", "HH") else "#089981")
            x = pos.get(ts)
            if x is None:
                continue
            up = text in ("LL", "HL") or "↑" in str(text)
            ax.annotate(text, (x, price), color=col, fontsize=8, fontweight="bold",
                        ha="center", va=("top" if not up else "bottom"),
                        xytext=(0, 8 if up else -8), textcoords="offset points")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    print(f"сохранено: {out}")
    return out


def _smoke():
    """Проверка рендера: BTC 4h с биржи, без слоёв."""
    import ccxt
    ex = ccxt.bingx({"enableRateLimit": True})
    o = ex.fetch_ohlcv("BTC/USDT:USDT", "4h", limit=120)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    render_verify(df, "BTC 4h — smoke (рендер OK)", out="tmp_charts/chart_verify_smoke.png")


if __name__ == "__main__":
    _smoke()
