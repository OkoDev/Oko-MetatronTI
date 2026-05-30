"""
core/chart_builder.py — генерация candlestick PNG для отправки в Telegram.

Использует Binance публичный API (без ключей).
Вызывается из bot/monitoring.py при отправке сигнала если send_chart: true в config.

Основные функции:
    build_signal_chart(symbol, tf, bars, warmup) → bytes | None
"""
import asyncio
import io
import logging
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend — обязателен в async (иначе TkAgg → RuntimeError в потоках)
    import matplotlib.pyplot as plt
    import mplfinance as mpf
    _MPF_OK = True
except ImportError:
    _MPF_OK = False
    logger.warning("mplfinance не установлен — генерация графиков недоступна")

try:
    import ccxt.async_support as ccxt_async
    _CCXT_OK = True
except ImportError:
    _CCXT_OK = False


# DEV-100: blacklist малоликвидных пар — mplfinance падает на OHLCV с нулями/выбросами
# Читается из config.yaml: signals.chart_blacklist (список строк).
# Хардкодный базовый список; дополняется из конфига при вызове.
_CHART_BLACKLIST_BASE: set[str] = {
    "GAIB/USDT:USDT",
    "GAIB/USDT",
    "BANANA/USDT:USDT",
    "BANANA/USDT",
}


def _is_chart_blacklisted(symbol: str, bot=None) -> bool:
    """True если пара в blacklist (хардкод + config)."""
    if symbol in _CHART_BLACKLIST_BASE:
        return True
    if bot is not None:
        cfg_list = bot.config.get("signals.chart_blacklist", []) if hasattr(bot, "config") else []
        if isinstance(cfg_list, list) and symbol in cfg_list:
            return True
    return False


# ─── Fetch ────────────────────────────────────────────────────────────────────

def _to_binance_symbol(symbol: str) -> str:
    """BingX perpetual FAI/USDT:USDT → Binance spot FAI/USDT."""
    return symbol.split(":")[0]


async def _fetch_ohlcv_from(exch, sym: str, tf: str, limit: int) -> list:
    try:
        return await exch.fetch_ohlcv(sym, tf, limit=limit)
    finally:
        await exch.close()


async def _fetch_ohlcv(symbol: str, tf: str, limit: int) -> pd.DataFrame:
    # BingX — основная биржа бота; Binance как fallback для spot-символов
    try:
        raw = await _fetch_ohlcv_from(
            ccxt_async.bingx({"enableRateLimit": True}),
            symbol, tf, limit,
        )
    except Exception:
        raw = await _fetch_ohlcv_from(
            ccxt_async.binance({"enableRateLimit": True}),
            _to_binance_symbol(symbol), tf, limit,
        )
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("time").astype(float)
    return df


# ─── WaveTrend ────────────────────────────────────────────────────────────────

def _calculate_wt(df: pd.DataFrame, n1: int = 10, n2: int = 21) -> pd.DataFrame:
    # ARCH-117 ph2: wt1/wt2 из канона (indicators.calculate_wt) — убрана 5-я копия
    # формулы. Cross-маркеры для графика остаются здесь (chart-специфичны).
    from core.indicators.indicators import calculate_wt
    df = calculate_wt(df.copy(), n1=n1, n2=n2)
    cross_up   = (df["wt1"].shift(1) < df["wt2"].shift(1)) & (df["wt1"] > df["wt2"])
    cross_down = (df["wt1"].shift(1) > df["wt2"].shift(1)) & (df["wt1"] < df["wt2"])
    df["cross_up"]   = np.where(cross_up,   df["wt2"], np.nan)
    df["cross_down"] = np.where(cross_down, df["wt2"], np.nan)
    return df


# ─── Пивоты ───────────────────────────────────────────────────────────────────

def _pivot_levels(high, low, close) -> dict:
    pp = (high + low + close) / 3
    hl = high - low
    return {"PP": pp, "R1": 2*pp - low, "R2": pp + hl, "S1": 2*pp - high, "S2": pp - hl}


async def _fetch_pivot_1h(symbol: str, limit: int = 530) -> pd.DataFrame:
    """Загружает 1h данные для расчёта пивотов (≥3 полных недели)."""
    try:
        raw = await _fetch_ohlcv_from(
            ccxt_async.bingx({"enableRateLimit": True}),
            symbol, "1h", limit,
        )
    except Exception:
        raw = await _fetch_ohlcv_from(
            ccxt_async.binance({"enableRateLimit": True}),
            _to_binance_symbol(symbol), "1h", limit,
        )
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("time").astype(float)
    return df


def _calc_pivot_levels(df1h: pd.DataFrame, tz_offset_hours: int = 3) -> tuple[dict, dict]:
    """
    Считает дневные и недельные пивоты из 1h данных с учётом timezone.
    tz_offset_hours=3 → UTC+3 (как в TradingView у пользователя).
    Граница дня: 00:00 местного = (24 - tz_offset_hours) % 24 UTC.
    """
    offset = pd.Timedelta(hours=tz_offset_hours)

    daily = (df1h
             .resample("D", offset=offset)
             .agg({"high": "max", "low": "min", "close": "last"})
             .dropna())
    daily_piv = _pivot_levels(*daily.iloc[-2][["high", "low", "close"]]) if len(daily) >= 2 else {}

    weekly = (df1h
              .resample("W-MON", offset=offset)
              .agg({"high": "max", "low": "min", "close": "last"})
              .dropna())
    weekly_piv = _pivot_levels(*weekly.iloc[-2][["high", "low", "close"]]) if len(weekly) >= 2 else {}

    return daily_piv, weekly_piv


# ─── Render ───────────────────────────────────────────────────────────────────

def _render(df: pd.DataFrame, symbol: str, tf: str,
            daily_pivots: dict | None = None,
            weekly_pivots: dict | None = None) -> bytes:
    if daily_pivots is None:
        daily_pivots = _calc_daily_pivots(df)
    if weekly_pivots is None:
        weekly_pivots = _calc_weekly_pivots(df)

    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350",
        wick={"up": "#26a69a", "down": "#ef5350"},
        volume={"up": "#26a69a44", "down": "#ef535044"},
        edge="inherit",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        facecolor="#131722", figcolor="#131722",
        gridcolor="#1e2130", gridstyle="--", gridaxis="both",
        y_on_right=True,
        rc={
            "axes.labelcolor": "#d1d4dc",
            "xtick.color": "#787b86", "ytick.color": "#787b86",
            "text.color": "#d1d4dc", "xtick.labelsize": 7,
        },
    )

    # Невидимый addplot создаёт panel=2 для WT
    wt_panel = [mpf.make_addplot(df["wt1"], panel=2, color="#131722",
                                  ylabel="WT", linewidths=0.1)]

    last_price = df["close"].iloc[-1]
    pct = (last_price / df["close"].iloc[0] - 1) * 100
    sign = "+" if pct >= 0 else ""
    title = (f"{symbol}  ·  {tf}  ·  ${last_price:.5g}  "
             f"({sign}{pct:.1f}%)  ·  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")

    buf = io.BytesIO()
    fig, axes = mpf.plot(
        df, type="candle", style=style, title=title,
        volume=True, addplot=wt_panel,
        panel_ratios=(4, 1, 2), figsize=(14, 8),
        returnfig=True, tight_layout=True,
    )

    # Даты горизонтально
    for ax in fig.axes:
        ax.tick_params(axis="x", labelsize=7)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(0)
            lbl.set_ha("center")

    # WT на axes[4]
    ax_wt = axes[4]
    xs = np.arange(len(df))
    w1, w2 = df["wt1"].values, df["wt2"].values
    ax_wt.fill_between(xs, w1, w2, alpha=0.15, color="#2196f3")
    ax_wt.plot(xs, w1, color="#e91e63", linewidth=1.2, zorder=3)
    ax_wt.plot(xs, w2, color="#4caf50", linewidth=1.2, zorder=3)
    for col, color in [("cross_up", "#26a69a"), ("cross_down", "#ef5350")]:
        vals = df[col].values
        cx = [i for i, v in enumerate(vals) if not np.isnan(v)]
        if cx:
            ax_wt.scatter(cx, [vals[i] for i in cx], s=60, marker="o", color=color, zorder=5)
    for lvl, color, ls, alp in [
        (80, "#ef5350", "-", 1.0), (60, "#ef5350", "--", 0.6),
        (0, "#555555", "--", 0.8),
        (-60, "#26a69a", "--", 0.6), (-80, "#26a69a", "-", 1.0),
    ]:
        ax_wt.axhline(lvl, color=color, linestyle=ls, linewidth=0.8, alpha=alp)

    # Пивоты на axes[0]
    ax_price = axes[0]
    n, x_end = len(df), len(df) - 1
    price_min, price_max = df["low"].min(), df["high"].max()

    last_t = df.index[-1]
    # Защита от дубликатов/нулевой разницы: берём медиану первых 10 интервалов
    _tf_fallback = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
    if len(df) > 1:
        _diffs = [abs((df.index[i+1] - df.index[i]).total_seconds()) for i in range(min(10, len(df)-1)) if (df.index[i+1] - df.index[i]).total_seconds() > 0]
        bar_sec = int(sorted(_diffs)[len(_diffs)//2]) if _diffs else 900
    else:
        bar_sec = 900
    if bar_sec == 0:
        bar_sec = 900
    next_midnight = last_t.normalize() + pd.Timedelta(days=1)
    bars_to_eod = max(1, int((next_midnight - last_t).total_seconds() / bar_sec))
    days_to_mon = (7 - last_t.weekday()) % 7 or 7
    next_monday = last_t.normalize() + pd.Timedelta(days=days_to_mon)
    bars_to_eow = max(1, int((next_monday - last_t).total_seconds() / bar_sec))

    x_eod = x_end + bars_to_eod
    x_eow = x_end + bars_to_eow
    x_right = max(x_eow, x_eod) + 2 + n * 0.50

    last_date = last_t.date()
    day_start = next((i for i, t in enumerate(df.index) if t.date() == last_date), 0)
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
                ax_price.text(
                    x_to, price, f" {prefix}{name} {price:.5g} ",
                    color="#131722", fontsize=6.5, va="center", ha="left",
                    zorder=5, clip_on=False,
                    bbox=dict(facecolor=color, edgecolor="none",
                              alpha=0.85, boxstyle="round,pad=0.15"),
                )

    _draw_pivots(daily_pivots, day_start, x_eod,
                 {"PP": "#ffeb3b", "R1": "#ef5350", "R2": "#ef535088",
                  "S1": "#26a69a", "S2": "#26a69a88"}, "--", 0.8, "D:")
    _draw_pivots(weekly_pivots, week_start, x_eow,
                 {"PP": "#ffd700", "R1": "#ff1744", "R2": "#ff174466",
                  "S1": "#00e676", "S2": "#00e67666"}, "-", 1.2, "W:")

    for ax in [axes[0], axes[2], axes[4]]:
        ax.set_xlim(-0.5, x_right)

    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─── Public API ───────────────────────────────────────────────────────────────

async def build_signal_chart(symbol: str, tf: str = "1h",
                              bars: int = 300, warmup: int = 80,
                              bot=None, fvg_zones=None) -> bytes | None:
    """Генерирует PNG-график для сигнала. Возвращает bytes или None при ошибке."""
    if not _MPF_OK:
        logger.warning("chart_builder: mplfinance не установлен")
        return None
    # DEV-100: blacklist малоликвидных пар
    if _is_chart_blacklisted(symbol, bot):
        logger.info("chart_builder: %s в blacklist — пропускаем генерацию графика", symbol)
        return None
    try:
        dc = getattr(bot, "data_collector", None) if bot else None

        # Основные данные: из кеша data_collector (уже загружены при сканировании)
        # Fallback: прямой запрос BingX → Binance
        if dc is not None:
            limit = bars + warmup
            df_full = await dc.get_ohlcv(symbol, tf, limit=limit)
            df_pivot1h = await dc.get_ohlcv(symbol, "1h", limit=530)
        else:
            if not _CCXT_OK:
                logger.warning("chart_builder: ccxt недоступен")
                return None
            df_full, df_pivot1h = await asyncio.gather(
                _fetch_ohlcv(symbol, tf, bars + warmup),
                _fetch_pivot_1h(symbol),
            )

        if df_full is None or df_full.empty:
            logger.warning("chart_builder: нет данных для %s %s", symbol, tf)
            return None

        # DEV-100: защита от нестандартных OHLCV (нули, NaN, выбросы → mplfinance краш)
        _close = df_full["close"] if "close" in df_full.columns else None
        if _close is None or (_close <= 0).any() or _close.isna().any():
            logger.warning("chart_builder: %s — невалидные close (нули/NaN), пропускаем", symbol)
            return None

        # Нормализуем индекс: data_collector возвращает RangeIndex + колонка "time" (ms int)
        # _calc_pivot_levels требует DatetimeIndex с tz; pd.to_datetime без unit="ms"
        # интерпретирует int как наносекунды → неверные даты → пустые пивоты
        def _ensure_dt_index(df: pd.DataFrame) -> pd.DataFrame:
            if isinstance(df.index, pd.DatetimeIndex):
                return df
            df = df.copy()
            if "time" in df.columns:
                col = df["time"]
                if pd.api.types.is_numeric_dtype(col):
                    # ms timestamps от data_collector/ccxt
                    df["time"] = pd.to_datetime(col, unit="ms", utc=True)
                else:
                    df["time"] = pd.to_datetime(col, utc=True)
                df = df.set_index("time")
            else:
                df.index = pd.to_datetime(df.index, utc=True)
            return df

        df_full     = _ensure_dt_index(df_full)
        df_pivot1h  = _ensure_dt_index(df_pivot1h) if df_pivot1h is not None else None

        df_full = _calculate_wt(df_full)
        df = df_full.iloc[-bars:].copy()
        daily_pivots, weekly_pivots = _calc_pivot_levels(df_pivot1h, tz_offset_hours=3) if df_pivot1h is not None and not df_pivot1h.empty else ({}, {})
        return _render(df, symbol, tf,
                       daily_pivots=daily_pivots,
                       weekly_pivots=weekly_pivots)
    except Exception:
        logger.exception("chart_builder: ошибка генерации графика для %s", symbol)
        return None


def build_deep_chart(
    df,
    symbol: str,
    tf: str,
    daily_pivots=None,
    weekly_pivots=None,
    fvg_zones=None,
    cross_pivots=None,
    all_fvgs=None,
) -> bytes | None:
    """Синхронная обёртка для deep_analysis_handler (вызывается через run_in_executor).
    fvg_zones / cross_pivots / all_fvgs зарезервированы для будущего рендеринга FVG-зон.
    """
    if not _MPF_OK:
        return None
    try:
        if "wt1" not in df.columns:
            df = _calculate_wt(df)
        return _render(df, symbol, tf,
                       daily_pivots=daily_pivots,
                       weekly_pivots=weekly_pivots)
    except Exception:
        logger.exception("build_deep_chart: ошибка для %s", symbol)
        return None
