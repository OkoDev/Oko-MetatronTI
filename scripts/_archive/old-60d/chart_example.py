"""
Пример генерации candlestick графика через mplfinance.
Получает OHLCV с Binance (публичный API, без ключей), строит график и сохраняет PNG.

Запуск:
    python scripts/chart_example.py GRT
    python scripts/chart_example.py BTC 1h 100
"""
import asyncio
import io
import sys
from datetime import datetime

import ccxt.async_support as ccxt_async
import mplfinance as mpf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ─── Параметры ────────────────────────────────────────────────────────────────

SYMBOL_ARG  = sys.argv[1] if len(sys.argv) > 1 else "GRT"
TF_ARG      = sys.argv[2] if len(sys.argv) > 2 else "15m"
BARS        = int(sys.argv[3]) if len(sys.argv) > 3 else 300
OUT_FILE    = f"chart_{SYMBOL_ARG}_{TF_ARG}.png"

# Баров для прогрева индикаторов (не показываются на графике)
WARMUP = 80

SYMBOL = f"{SYMBOL_ARG}/USDT"


# ─── Получение данных ─────────────────────────────────────────────────────────

async def fetch_ohlcv(symbol: str, tf: str, limit: int) -> pd.DataFrame:
    exchange = ccxt_async.binance({"enableRateLimit": True})
    try:
        raw = await exchange.fetch_ohlcv(symbol, tf, limit=limit)
    finally:
        await exchange.close()

    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df = df.set_index("time")
    df = df.astype(float)
    return df


# ─── WaveTrend индикатор ──────────────────────────────────────────────────────

def calculate_wt(df: pd.DataFrame, n1: int = 10, n2: int = 21) -> pd.DataFrame:
    """WaveTrend осциллятор — параметры TV: Channel Length=10, Average Length=21."""
    ap  = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=n1, adjust=False).mean()
    d   = (ap - esa).abs().ewm(span=n1, adjust=False).mean()
    ci  = (ap - esa) / (0.015 * d.replace(0, np.nan)).fillna(0)
    tci = ci.ewm(span=n2, adjust=False).mean()
    wt2 = tci.rolling(4).mean()
    df  = df.copy()
    df["wt1"] = tci
    df["wt2"] = wt2
    # Маркеры кроссов
    cross_up   = (df["wt1"].shift(1) < df["wt2"].shift(1)) & (df["wt1"] > df["wt2"])
    cross_down = (df["wt1"].shift(1) > df["wt2"].shift(1)) & (df["wt1"] < df["wt2"])
    df["cross_up"]   = np.where(cross_up,   df["wt2"], np.nan)
    df["cross_down"] = np.where(cross_down, df["wt2"], np.nan)
    return df


# ─── Пивоты (ручной расчёт без кэша) ─────────────────────────────────────────

def _pivot_levels(high: float, low: float, close: float) -> dict:
    pp = (high + low + close) / 3
    hl = high - low
    return {"PP": pp, "R1": 2*pp - low, "R2": pp + hl, "S1": 2*pp - high, "S2": pp - hl}


def calc_daily_pivots(df: pd.DataFrame) -> dict:
    daily = df.resample("D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(daily) < 2:
        return {}
    p = daily.iloc[-2]
    return _pivot_levels(p["high"], p["low"], p["close"])


def calc_weekly_pivots(df: pd.DataFrame) -> dict:
    weekly = df.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(weekly) < 2:
        return {}
    p = weekly.iloc[-2]
    return _pivot_levels(p["high"], p["low"], p["close"])


# ─── Генерация графика ────────────────────────────────────────────────────────

def build_chart(df: pd.DataFrame, symbol: str, tf: str, out_file: str) -> bytes:
    daily_pivots  = calc_daily_pivots(df)
    weekly_pivots = calc_weekly_pivots(df)

    # ── Настройка стиля ───────────────────────────────────────────────────────
    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350",
        wick={"up": "#26a69a", "down": "#ef5350"},
        volume={"up": "#26a69a44", "down": "#ef535044"},
        edge="inherit",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        facecolor="#131722",
        figcolor="#131722",
        gridcolor="#1e2130",
        gridstyle="--",
        gridaxis="both",
        y_on_right=True,
        rc={
            "axes.labelcolor": "#d1d4dc",
            "xtick.color": "#787b86",
            "ytick.color": "#787b86",
            "text.color": "#d1d4dc",
            "xtick.labelsize": 7,
        },
    )

    # Пивоты рисуем вручную после plot() — нет addplot

    # ── WT осциллятор (нижняя панель) ─────────────────────────────────────────
    # Невидимый addplot только для создания panel=2; всё рисуем вручную на ax_wt
    wt_panel = [
        mpf.make_addplot(df["wt1"], panel=2, color="#131722", ylabel="WT",
                         linewidths=0.1),
    ]
    # wt1/wt2/crosses/fill/OB/OS — рисуем на осях после plot()

    all_plots = wt_panel

    # ── Маркер последнего сигнала (OS зона) ───────────────────────────────────
    last_wt1 = df["wt1"].iloc[-1]
    if last_wt1 < -80:
        signal_marker = mpf.make_addplot(
            pd.Series([None] * (len(df) - 1) + [df["low"].iloc[-1] * 0.998],
                      index=df.index),
            panel=0, type="scatter", markersize=120,
            marker="^", color="#26a69a",
        )
        all_plots.append(signal_marker)
    elif last_wt1 > 80:
        signal_marker = mpf.make_addplot(
            pd.Series([None] * (len(df) - 1) + [df["high"].iloc[-1] * 1.002],
                      index=df.index),
            panel=0, type="scatter", markersize=120,
            marker="v", color="#ef5350",
        )
        all_plots.append(signal_marker)

    # ── Рендер ────────────────────────────────────────────────────────────────
    last_price = df["close"].iloc[-1]
    pct_change = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    sign = "+" if pct_change >= 0 else ""
    title = (
        f"{symbol}  ·  {tf}  ·  "
        f"${last_price:.4f}  ({sign}{pct_change:.1f}%)  ·  "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )

    buf = io.BytesIO()
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        title=title,
        volume=True,
        addplot=all_plots,
        panel_ratios=(4, 1, 2),   # свечи : объём : WT
        figsize=(14, 8),
        returnfig=True,
        tight_layout=True,
    )

    # ── X-метки: 45° вместо 90°, меньший шрифт ───────────────────────────────
    for ax in fig.axes:
        ax.tick_params(axis="x", labelsize=7)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(0)
            lbl.set_ha("center")

    # ── WT всё рисуем напрямую на axes[4] (единая ось → маркеры на нужных Y) ──
    ax_wt = axes[4]
    xs = np.arange(len(df))
    w1 = df["wt1"].values
    w2 = df["wt2"].values
    # fill между wt1 и wt2
    ax_wt.fill_between(xs, w1, w2, alpha=0.15, color="#2196f3")
    # wt1 — красный (быстрый), wt2 — зелёный (гладкий)
    ax_wt.plot(xs, w1, color="#e91e63", linewidth=1.2, zorder=3)
    ax_wt.plot(xs, w2, color="#4caf50", linewidth=1.2, zorder=3)
    # Кросс-маркеры — на той же оси, те же координаты
    for col, color in [("cross_up", "#26a69a"), ("cross_down", "#ef5350")]:
        vals = df[col].values
        cx = [i for i, v in enumerate(vals) if not np.isnan(v)]
        cy = [vals[i] for i in cx]
        if cx:
            ax_wt.scatter(cx, cy, s=60, marker="o", color=color, zorder=5)
    # OB/OS уровни — не через addplot, не растягивают ось
    for lvl, color, ls, alp in [
        (80,  "#ef5350", "-",  1.0), (60,  "#ef5350", "--", 0.6),
        (0,   "#555555", "--", 0.8),
        (-60, "#26a69a", "--", 0.6), (-80, "#26a69a", "-",  1.0),
    ]:
        ax_wt.axhline(lvl, color=color, linestyle=ls, linewidth=0.8, alpha=alp)
        if lvl != 0:
            ax_wt.text(len(df) - 0.5, lvl, f" {lvl}", color=color,
                       fontsize=7, va="center")

    # ── Пивоты на price-панели — линии от начала дня/недели вправо ──────────
    ax_price = axes[0]
    price_min = df["low"].min()
    price_max = df["high"].max()
    n = len(df)
    x_end = n - 1

    # ── Расчёт баров до конца дня / конца недели ─────────────────────────────
    from datetime import timedelta, timezone as _tz
    last_t = df.index[-1]
    # размер бара в секундах (из данных)
    bar_sec = int((df.index[1] - df.index[0]).total_seconds()) if len(df) > 1 else 3600

    next_midnight = (last_t.normalize() + pd.Timedelta(days=1)).tz_localize(None) \
        if last_t.tz is None else (last_t.normalize() + pd.Timedelta(days=1))
    bars_to_eod = max(1, int((next_midnight - last_t).total_seconds() / bar_sec))

    # Следующий понедельник 00:00
    days_to_mon = (7 - last_t.weekday()) % 7 or 7
    next_monday = (last_t.normalize() + pd.Timedelta(days=days_to_mon)).tz_localize(None) \
        if last_t.tz is None else (last_t.normalize() + pd.Timedelta(days=days_to_mon))
    bars_to_eow = max(1, int((next_monday - last_t).total_seconds() / bar_sec))

    # x-координаты концов линий (в правом margin)
    x_eod = x_end + bars_to_eod
    x_eow = x_end + bars_to_eow
    x_right = max(x_eow, x_eod) + 2 + n * 0.50  # правый предел оси (50% отступ)

    # Индекс первого бара текущего дня
    last_date = last_t.date()
    day_start = next((i for i, t in enumerate(df.index) if t.date() == last_date), 0)

    # Индекс первого бара текущей недели
    last_iso = last_t.isocalendar()
    week_start = next(
        (i for i, t in enumerate(df.index)
         if t.isocalendar().week == last_iso.week
         and t.isocalendar().year == last_iso.year), 0)

    def _draw_pivots(piv_dict, x_from, x_to, d_colors, ls, lw, prefix):
        for name, price in piv_dict.items():
            if price <= 0:
                continue
            color = d_colors.get(name, "#888888")
            ax_price.plot([x_from, x_to], [price, price],
                          color=color, linestyle=ls, linewidth=lw, zorder=2)
            if price_min * 0.97 < price < price_max * 1.03:
                # Бокс-лейбл прямо у конца линии (как в TV), не на шкале цены
                ax_price.text(
                    x_to, price,
                    f" {prefix}{name} {price:.5g} ",
                    color="#131722", fontsize=6.5, va="center", ha="left",
                    zorder=5, clip_on=False,
                    bbox=dict(facecolor=color, edgecolor="none",
                              alpha=0.85, boxstyle="round,pad=0.15"),
                )

    _draw_pivots(
        daily_pivots, day_start, x_eod,
        {"PP": "#ffeb3b", "R1": "#ef5350", "R2": "#ef535088",
         "S1": "#26a69a", "S2": "#26a69a88"},
        "--", 0.8, "D:"
    )
    _draw_pivots(
        weekly_pivots, week_start, x_eow,
        {"PP": "#ffd700", "R1": "#ff1744", "R2": "#ff174466",
         "S1": "#00e676", "S2": "#00e67666"},
        "-", 1.2, "W:"
    )

    # ── Правый отступ вмещает конец дня и недели ─────────────────────────────
    for ax in [axes[0], axes[2], axes[4]]:
        ax.set_xlim(-0.5, x_right)

    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#131722")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    fetch_bars = BARS + WARMUP
    print(f"Получаю {fetch_bars} баров {SYMBOL} {TF_ARG} с Binance (прогрев {WARMUP} + показ {BARS})...")
    df_full = await fetch_ohlcv(SYMBOL, TF_ARG, fetch_bars)
    print(f"Получено {len(df_full)} свечей | последняя цена: {df_full['close'].iloc[-1]:.6f}")

    # Считаем индикаторы на полном массиве, показываем только BARS последних баров
    df_full = calculate_wt(df_full)
    df = df_full.iloc[-BARS:].copy()

    print("Генерирую график...")
    png_bytes = build_chart(df, SYMBOL, TF_ARG, OUT_FILE)

    with open(OUT_FILE, "wb") as f:
        f.write(png_bytes)
    print(f"Сохранено: {OUT_FILE} ({len(png_bytes) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
