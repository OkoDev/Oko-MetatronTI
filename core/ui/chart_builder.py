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
    # ARCH-117 ph2: wt1/wt2 из канона (indicators.calculate_wt) — убрана 5-я копия.
    # FIX 30.05: calculate_wt делает reset_index(drop=True) → теряется DatetimeIndex,
    # нужный mplfinance. Сохраняем и восстанавливаем индекс (длина/порядок те же).
    from core.indicators.indicators import calculate_wt
    _idx = df.index
    df = calculate_wt(df.copy(), n1=n1, n2=n2)
    df.index = _idx
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
            weekly_pivots: dict | None = None,
            wave_overlay: bool = False,
            h4_pivots: dict | None = None,
            htf_fvg: list | None = None,
            okosm: dict | None = None,
            choch_length: int | None = None,
            choch_length_major: int | None = None) -> bytes:
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

    # Ограничиваем проекцию до конца дня/недели: на младших ТФ (5m: до 2016 баров до
    # конца недели) правое поле съедало график, свечи сжимались. Кап = 20% ширины.
    _max_proj = int(n * 0.20)
    x_eod = x_end + min(bars_to_eod, _max_proj)
    x_eow = x_end + min(bars_to_eow, _max_proj)
    x_right = max(x_eow, x_eod) + 2 + n * 0.12   # фикс-поле 0.50→0.12 (было 33% пустое)

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

    # WAVE-CHART overlay: ZigZag-волна (нумерация с 0) + OB-зоны + FVG на ТФ входа
    if wave_overlay:
        try:
            from core.smc.smc_engine import (zigzag_atr, detect_structure_breaks,
                                             detect_order_blocks, detect_fvg,
                                             detect_equal_levels, _zz_typed)
            _d = df.reset_index(drop=True)  # позиционный индекс для smc (совпадает с mpf x)
            _dev, _bd = 3.0, 1e9            # adaptive dev (целевое ~8 swing под TF)
            for _dv in (1.5, 2.0, 2.5, 3.0, 4.0):
                _nn = len(zigzag_atr(_d, 11, _dv))
                if abs(_nn - 8) < _bd:
                    _bd, _dev = abs(_nn - 8), _dv
            _typed = _zz_typed(zigzag_atr(_d, 11, _dev))
            if _typed:
                # zigzag-линия БЕЗ нумерации (zigzag не различает импульс 1-5 / коррекцию ABC)
                ax_price.plot([i for i, _, _ in _typed], [p for _, p, _ in _typed],
                              color="#ffa726", linewidth=1.3, zorder=6, alpha=0.85)
            # 🔴 28.08: длина вынесена в параметр, чтобы можно было показать
            # ЭТАЛОН (5) против БОЕВОГО (50) одним и тем же рендером.
            # Дефолт прежний — поведение боевых графиков не меняется.
            # 🔴 28.08 ДВЕ СТРУКТУРЫ НА ОДНОМ ГРАФИКЕ (метод Егора len5/len50).
            # len5 и len50 — НЕ «зрячий против слепого», а РАЗНЫЙ МАСШТАБ:
            # len50 = значимые сломы (направление и подтверждение),
            # len5  = внутренняя структура (точки входа). Работают ВМЕСТЕ:
            # триггер входа даёт len5, подтверждение и добор — len50
            # ([[method_egor_two_scale_entry]]).
            # Старшая рисуется ТОЛЩЕ и ярче, младшая — тоньше и бледнее.
            if choch_length_major:
                for _bm in detect_structure_breaks(_d, length=choch_length_major)[-6:]:
                    _mc = "#26a69a" if _bm.direction == "bull" else "#ef5350"
                    _mf = _bm.from_idx if _bm.from_idx >= 0 else _bm.idx
                    ax_price.plot([_mf, _bm.idx], [_bm.price, _bm.price], color=_mc,
                                  linestyle="-", linewidth=2.6, alpha=0.95, zorder=6)
                    ax_price.annotate(f"{_bm.kind}·{choch_length_major}",
                                      ((_mf + _bm.idx) / 2, _bm.price), color=_mc,
                                      fontsize=8, fontweight="bold", zorder=7,
                                      va="bottom", ha="center")
            _brks = detect_structure_breaks(_d, length=(choch_length or 5))
            for _b in detect_order_blocks(_d, _brks):
                if _b.mitigated_idx != -1:
                    continue
                _col = "#26a69a" if _b.kind == "bull" else "#ef5350"
                ax_price.add_patch(plt.Rectangle((_b.left_idx, _b.bottom), n - _b.left_idx,
                                   _b.top - _b.bottom, facecolor=_col, alpha=0.10,
                                   edgecolor=_col, linewidth=0.7, zorder=1))
                # подпись OB с ТФ по центру бокса (bull/bear уже различимы цветом)
                ax_price.annotate(f"OB-{tf}", ((_b.left_idx + n) / 2, (_b.top + _b.bottom) / 2),
                                  color=_col, fontsize=6, fontweight="bold", va="center",
                                  ha="center", zorder=6, alpha=0.85)
            # BOS/CHoCH линии слома (CHoCH=сплошная=разворот, BOS=пунктир=продолжение)
            for _br in _brks[-5:]:
                _bc = "#26a69a" if _br.direction == "bull" else "#ef5350"
                _bls = "-" if _br.kind == "CHoCH" else (0, (3, 3))
                _frm = _br.from_idx if _br.from_idx >= 0 else _br.idx
                ax_price.plot([_frm, _br.idx], [_br.price, _br.price], color=_bc,
                              linestyle=_bls, linewidth=1.0, alpha=0.7, zorder=5)
                # подпись по СЕРЕДИНЕ линии слома (не на правом конце)
                ax_price.annotate(_br.kind, ((_frm + _br.idx) / 2, _br.price), color=_bc, fontsize=7,
                                  fontweight="bold", zorder=6, va="bottom", ha="center")
            _pr = df["close"].iloc[-1]
            for _f in detect_fvg(_d)[-15:]:
                if _f[5] is not None:    # пробитый (mitigated) FVG — не рисуем (каша слева)
                    continue
                _top, _bot, _kind = _f[1], _f[2], _f[3]
                if abs((_top + _bot) / 2 - _pr) / _pr > 0.03:
                    continue
                _fc = "#42a5f5" if _kind == "bull" else "#ff7043"
                ax_price.add_patch(plt.Rectangle((_f[0], min(_top, _bot)), n - _f[0],
                                   abs(_top - _bot), facecolor=_fc, alpha=0.13,
                                   edgecolor=_fc, linewidth=0.5, zorder=1, hatch="///"))
            # 4h-пивоты (для младших ТФ) — рисуем ТОЛЬКО в пределах последней 4h-свечи
            # (правый край = текущий 4h-период), а не на весь чарт.
            if h4_pivots:
                _tf_min = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(tf, 60)
                _x4 = max(0, n - max(1, int(240 / _tf_min)))  # старт последнего 4h-периода
                for _k, _c2 in [("R2", "#ef5350"), ("R1", "#ff9800"), ("PP", "#ffeb3b"),
                                ("S1", "#4caf50"), ("S2", "#26a69a")]:
                    if _k in h4_pivots:
                        _v = h4_pivots[_k]
                        ax_price.plot([_x4, n - 1], [_v, _v], color=_c2, linestyle="--",
                                      linewidth=0.8, alpha=0.6, zorder=2)
                        ax_price.annotate(f"4h-{_k}", (n - 1, _v), color=_c2, fontsize=7,
                                          va="center", ha="left", zorder=6)
            # 🟦 HTF-FVG (daily/4h активные) — зоны-магниты СТАРШЕГО ТФ (origin за окном
            # младшего ТФ невидим; рисуем боксом у правого края = «куда тянет цену»).
            if htf_fvg:
                for _hf in htf_fvg:
                    _hl, _ht, _hb, _hk, _hx = _hf  # (label, top, bottom, kind, x_origin)
                    _hc = "#1e88e5" if _hk == "bull" else "#e53935"
                    _hmid = (_ht + _hb) / 2
                    # широкий залитый бокс от origin-свечи (_hx) вправо до текущего бара (OKO-SM стиль)
                    ax_price.add_patch(plt.Rectangle((_hx, min(_ht, _hb)), n - 1 - _hx,
                                       abs(_ht - _hb), facecolor=_hc, alpha=0.15,
                                       edgecolor=_hc, linewidth=1.0, zorder=2))
                    # midline 0.5 (consequent encroachment) + подпись по ЦЕНТРУ бокса
                    ax_price.plot([_hx, n - 1], [_hmid, _hmid], color=_hc,
                                  linewidth=0.7, alpha=0.6, zorder=3)
                    ax_price.annotate(f"FVG-{_hl}", ((_hx + n - 1) / 2, _hmid), color=_hc,
                                      fontsize=6, fontweight="bold", va="center", ha="center", zorder=6, alpha=0.85)
            # 🌀 ФИБО/OTE-ЗОНА последнего движения (ЯДРО входа: откат волны-2 → волна-3)
            _ote_levels = {}
            if len(_typed) >= 2:
                (_ia, _pa, _ta) = _typed[-2]
                (_ib, _pb, _tb) = _typed[-1]
                _rng = _pb - _pa
                if abs(_rng) / _pr > 0.003:
                    # 🔴 28.08 (Егор: «на фибо нужны отметки 0 и 1»): без границ хода
                    # уровни 0.618/0.705/0.786 висят в воздухе — непонятно, от чего
                    # отмеряны. 0 и 1 = концы самой ноги, читаются тонкой линией.
                    for _ff, _fc, _lw in [(0.0, "#ffd700", 0.6), (0.618, "#ffd700", 0.8),
                                          (0.705, "#ffa726", 1.1), (0.786, "#ffd700", 0.8),
                                          (1.0, "#ffd700", 0.6)]:
                        _lvl = _pb - _ff * _rng
                        _ote_levels[_ff] = _lvl
                        ax_price.plot([_ib, n - 1], [_lvl, _lvl], color=_fc, linestyle=":",
                                      linewidth=_lw, alpha=0.75, zorder=3)
                        ax_price.annotate(f"{_ff}", (_ib, _lvl), color=_fc, fontsize=6, zorder=6, ha="right")
                    _z1 = _pb - 0.618 * _rng; _z2 = _pb - 0.786 * _rng
                    ax_price.axhspan(min(_z1, _z2), max(_z1, _z2), xmin=max(0, _ib) / n,
                                     color="#ffd700", alpha=0.07, zorder=1)
            # 💧 EQL/EQH (ликвидность) — только АКТИВНЫЕ (цена НЕ прошла за уровень = не снят)
            for _eq in detect_equal_levels(_d)[-8:]:
                _i1, _ep1, _i2, _ekind = _eq[0], _eq[1], _eq[2], _eq[4]
                _after = _d.iloc[_i2 + 1:]
                _swept = False
                if len(_after):
                    if _ekind == "EQH" and _after["high"].max() > _ep1 * 1.001:
                        _swept = True
                    if _ekind == "EQL" and _after["low"].min() < _ep1 * 0.999:
                        _swept = True
                if _swept:
                    continue  # снятая ликвидность — не рисуем
                ax_price.axhline(_ep1, color="#ab47bc", linestyle=(0, (1, 2)), linewidth=0.7, alpha=0.5, zorder=2)
                ax_price.annotate(_ekind, (_i1, _ep1), color="#ab47bc", fontsize=6, zorder=6)
            # КОНФЛЮЭНЦИЯ (Фибо-OTE × 4h-пивот) — НЕ рисуем на чарте (смешивалось),
            # выводим ТЕКСТОМ в caption (wave_chart_send / WAVE-WATCH).
        except Exception as _e:
            logger.warning("[chart_builder] wave_overlay %s: %s", symbol, _e)

    # OKO-SM ВАХТА overlay (23.07, опционально — okosm=None ничего не меняет):
    # нога (оранж) + золотая OTE-зона + fib-уровни (⭐=схождение) + слом. Времена в мс →
    # позиции баров через DatetimeIndex (кламп к левому краю если нога старше окна).
    if okosm:
        try:
            ax_price = axes[0]
            n = len(df)
            idx_ns = df.index.view("int64") // 1_000_000   # DatetimeIndex → мс

            def _pos(ms):
                import numpy as _np
                return int(max(0, min(n - 1, _np.searchsorted(idx_ns, ms))))
            t0, p0, t1, p1 = okosm["leg"]
            ax_price.plot([_pos(t0), _pos(t1)], [p0, p1],
                          color="#ff9800", lw=2.4, zorder=7, solid_capstyle="round")
            zlo, zhi = sorted(okosm["zone"])
            ax_price.axhspan(zlo, zhi, color="#ffd54f", alpha=0.10, zorder=1)
            for f, price, starred in okosm.get("levels", []):
                ax_price.axhline(price, color="#ffd54f",
                                 lw=1.6 if starred else 0.7,
                                 ls="-" if starred else "--", alpha=0.9, zorder=6)
                ax_price.annotate(f"{f:g}{' *' if starred else ''}",
                                  (n + 1, price), color="#ffd54f", fontsize=7,
                                  zorder=8, annotation_clip=False)
            if okosm.get("break"):
                ax_price.axhline(okosm["break"], color="#e91e63", lw=1.4,
                                 ls=(0, (4, 2)), alpha=0.95, zorder=6)
                ax_price.annotate("слом 1.0", (n + 1, okosm["break"]),
                                  color="#e91e63", fontsize=7, zorder=8,
                                  annotation_clip=False)
        except Exception as _e_ok:
            logger.warning("[chart_builder] okosm overlay %s: %s", symbol, _e_ok)

    for ax in [axes[0], axes[2], axes[4]]:
        ax.set_xlim(-0.5, x_right)

    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─── Public API ───────────────────────────────────────────────────────────────

async def build_signal_chart(symbol: str, tf: str = "1h",
                              bars: int = 300, warmup: int = 80,
                              bot=None, fvg_zones=None,
                              wave_overlay: bool = False,
                              okosm: dict | None = None) -> bytes | None:
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
        # 4h-пивоты для МЛАДШИХ ТФ (ресемпл 1h→4h) — ближние интрадей-уровни, релевантнее daily
        h4_pivots = None
        if tf in ("1m", "3m", "5m", "15m", "30m") and df_pivot1h is not None and not df_pivot1h.empty:
            try:
                _h4 = (df_pivot1h.resample("4h")
                       .agg({"high": "max", "low": "min", "close": "last"}).dropna())
                if len(_h4) >= 2:
                    h4_pivots = _pivot_levels(*_h4.iloc[-2][["high", "low", "close"]])
            except Exception:
                pass
        # HTF-FVG (1D+4h активные, рядом с ценой) — зоны-магниты старшего ТФ для overlay
        htf_fvg = None
        if wave_overlay:
            try:
                from core.smc.smc_engine import detect_fvg as _dfvg
                _pr = float(df["close"].iloc[-1])
                _htf_src = {"1D": df_pivot1h.resample("1D").agg(
                                {"high": "max", "low": "min", "close": "last", "open": "first"}).dropna()
                            if df_pivot1h is not None else None,
                            "4h": df_pivot1h.resample("4h").agg(
                                {"high": "max", "low": "min", "close": "last", "open": "first"}).dropna()
                            if df_pivot1h is not None else None}
                htf_fvg = []
                for _lbl, _src in _htf_src.items():
                    if _src is None or len(_src) < 5:
                        continue
                    for _fv in _dfvg(_src):
                        if _fv[5] is not None:          # mitigated (перекрыт) — пропуск (инвалидация)
                            continue
                        _t, _b = _fv[1], _fv[2]
                        if abs((_t + _b) / 2 - _pr) / _pr <= 0.28:   # в пределах ±28% (вся стопка как OKO-SM)
                            # привязка к СРЕДНЕЙ свече паттерна (i-1 = импульсная, создавшая gap):
                            # i-2 уезжал влево («была до образования»), i — вправо. Середина = impulse-бар
                            _xl = int(df.index.searchsorted(_fv[0]))  # 1-я свеча (i-2)
                            _xi = int(df.index.searchsorted(_fv[4]))  # 3-я свеча (i, подтверждение)
                            _xo = max(0, min((_xl + _xi) // 2, len(df) - 1))
                            htf_fvg.append((_lbl, _t, _b, _fv[3], _xo))
                htf_fvg = htf_fvg[:6] or None
            except Exception as _e:
                logger.warning("[chart_builder] htf_fvg %s: %s", symbol, _e)
        return _render(df, symbol, tf,
                       daily_pivots=daily_pivots,
                       weekly_pivots=weekly_pivots,
                       wave_overlay=wave_overlay,
                       h4_pivots=h4_pivots,
                       htf_fvg=htf_fvg,
                       okosm=okosm)
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
