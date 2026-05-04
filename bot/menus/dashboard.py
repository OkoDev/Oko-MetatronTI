"""
ARCH-13: Telegram Operations Dashboard.
Inline-keyboard дашборд для управления тогглами, параметрами и просмотра статуса.
"""
import logging
from datetime import datetime

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

# Те же тогглы что и в web dashboard — единый источник правды
_TOGGLES = [
    ("future_pivots.broadcast_tg", "Future Pivot->TG"),
    ("signals.mtf_alert_register", "MTF Alert Reg"),
    ("signals.cascade_div_enabled", "Cascade Div"),
    ("signals.send_chart", "📊 График к сигналу"),
    ("analysis.confluence.enabled", "Confluence"),
    ("analysis.confluence.use_state_machine", "Confluence SM"),
    ("trading.use_tsl", "TSL"),
    ("trading.cascade_tsl", "Cascade TSL"),
    ("trading.use_breakeven", "Breakeven"),
    ("signal_quality.btc_filter_enabled", "BTC Filter"),
    ("risk_management.regime_strategy.enabled", "Regime SL/TP"),
    ("future_pivots.enabled", "Future Pivots"),
]

_PARAMS = [
    ("signal_quality.min_strength_register", "min_str_reg", 40, 10, 100, 5),
    ("signal_quality.min_strength", "min_str_tg", 50, 20, 100, 5),
    ("signal_quality.dedup_minutes", "dedup_min", 30, 5, 120, 5),
    ("signal_quality.sl_cooldown_hours", "sl_cool_h", 1, 1, 48, 1),
    ("analysis.confluence.max_per_cycle", "conf/cycle", 10, 1, 50, 1),
    ("signal_quality.counter_trend_strength_threshold", "ct_thr", 30, 10, 100, 5),
    ("trading.min_rr_ratio", "min R:R", 2.0, 1.0, 5.0, 0.5),
    ("trading.max_trade_duration_hours", "expiry_h", 48, 12, 168, 12),
    ("trading.tsl_activation_r", "tsl_act_r", 1.0, 0.3, 3.0, 0.1),
    ("signal_quality.min_volume_usd", "min_vol_usd", 1000000, 100000, 100000000, 100000),
    ("monitoring.check_intervals.background_every_n_cycles", "bg_cycles", 5, 1, 20, 1),
]

_BTC_MODES = ["shadow", "block", "off"]

# Defaults для тогглов (True = включен по умолчанию)
_TOGGLE_DEFAULTS = {
    "future_pivots.broadcast_tg": False,
    "signals.mtf_alert_register": True,
    "signals.cascade_div_enabled": True,
    "signals.send_chart": True,
    "analysis.confluence.enabled": True,
    "analysis.confluence.use_state_machine": False,
    "trading.use_tsl": True,
    "trading.cascade_tsl": True,
    "trading.use_breakeven": False,
    "signal_quality.btc_filter_enabled": True,
    "risk_management.regime_strategy.enabled": True,
    "future_pivots.enabled": False,
}


def dashboard_status_text(bot) -> str:
    """Формирует текст статуса для TG дашборда."""
    is_mon = getattr(bot, "is_monitoring", False)
    pairs = len(getattr(bot, "monitored_pairs", []))
    sc = getattr(bot, "signal_counters", {})

    # BTC regime
    btc = (getattr(bot, "_btc_regime_cache", None) or {}).get("regime", "N/A")

    # ML
    op = getattr(bot, "outcome_predictor", None)
    ml_ok = op and getattr(op, "is_trained", False)
    ml_str = "trained" if ml_ok else "not trained"

    # Trade stats
    open_count = 0
    wr = 0.0
    avg_r = 0.0
    try:
        from core.trading.performance_engine import PerformanceEngine
        engine = PerformanceEngine(db_path=bot.trade_simulator.db_path)
        stats = engine.full_stats()
        open_count = stats.get("open_count", 0)
        wr = stats.get("win_rate", 0)
        avg_r = stats.get("avg_r", 0)
    except Exception:
        pass

    status_emoji = "🟢" if is_mon else "🔴"
    btc_emoji = "📈" if btc == "TREND_UP" else "📉" if btc == "TREND_DOWN" else "📊"

    lines = [
        f"<b>📟 OPERATIONS DASHBOARD</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"{status_emoji} Мониторинг: <b>{'ACTIVE' if is_mon else 'STOPPED'}</b> | {pairs} пар",
        f"{btc_emoji} BTC: <b>{btc}</b>",
        f"",
        f"📈 Сигналы:",
        f"  conf:{sc.get('confluence', 0)} piv:{sc.get('pivot_reversal', 0)} "
        f"mtf:{sc.get('mtf_alert', 0)} div:{sc.get('divergence', 0)}",
        f"",
        f"💾 Открыто: <b>{open_count}</b> | WR: <b>{wr:.1f}%</b> | R̄: <b>{avg_r:.2f}</b>",
        f"🤖 ML: <b>{ml_str}</b>",
        f"",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M:%S')}",
    ]
    return "\n".join(lines)


def dashboard_main_kb() -> InlineKeyboardMarkup:
    """Главная клавиатура дашборда."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ Тогглы", callback_data="dash:toggles"),
            InlineKeyboardButton(text="⚙️ Параметры", callback_data="dash:params"),
        ],
        [
            InlineKeyboardButton(text="🩺 Диагностика", callback_data="dash:diag"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="dash:refresh"),
        ],
    ])


def dashboard_toggles_text(bot) -> str:
    """Формирует текст экрана тогглов."""
    config = bot.config
    lines = ["<b>⚡ ПЕРЕКЛЮЧАТЕЛИ</b>", "━━━━━━━━━━━━━━━━━━━━", ""]

    for key, label in _TOGGLES:
        val = config.get(key, _TOGGLE_DEFAULTS.get(key, False))
        emoji = "✅" if val else "❌"
        lines.append(f"{emoji} {label}")

    btc_mode = config.get("signal_quality.btc_filter_mode", "shadow")
    lines.append(f"\n🛡 BTC Filter: <b>{btc_mode}</b>")

    return "\n".join(lines)


def dashboard_toggles_kb(bot) -> InlineKeyboardMarkup:
    """Inline клавиатура для тогглов."""
    config = bot.config
    rows = []

    # По 2 тоггла в ряд
    for i in range(0, len(_TOGGLES), 2):
        row = []
        for j in range(2):
            if i + j >= len(_TOGGLES):
                break
            key, label = _TOGGLES[i + j]
            default = key in ("signals.mtf_alert_register", "signals.cascade_div_enabled",
                              "analysis.confluence.enabled", "trading.use_tsl")
            val = config.get(key, default)
            emoji = "✅" if val else "❌"
            row.append(InlineKeyboardButton(
                text=f"{emoji} {label}",
                callback_data=f"dash:t:{key}",
            ))
        rows.append(row)

    # BTC filter mode buttons
    btc_mode = config.get("signal_quality.btc_filter_mode", "shadow")
    btc_row = []
    for mode in _BTC_MODES:
        marker = "◉ " if btc_mode == mode else ""
        btc_row.append(InlineKeyboardButton(
            text=f"{marker}{mode}",
            callback_data=f"dash:btc:{mode}",
        ))
    rows.append(btc_row)

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dash:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dashboard_params_text(bot) -> str:
    """Формирует текст экрана параметров."""
    config = bot.config
    lines = ["<b>⚙️ ПАРАМЕТРЫ</b>", "━━━━━━━━━━━━━━━━━━━━", ""]

    for key, label, default, mn, mx, step in _PARAMS:
        val = config.get(key, default)
        lines.append(f"  {label}: <b>{val}</b>  [{mn}..{mx}]")

    return "\n".join(lines)


def dashboard_params_kb(bot) -> InlineKeyboardMarkup:
    """Inline клавиатура для параметров."""
    config = bot.config
    rows = []

    for key, label, default, mn, mx, step in _PARAMS:
        val = config.get(key, default)
        rows.append([
            InlineKeyboardButton(text=f"−{step}", callback_data=f"dash:p:{key}:-{step}"),
            InlineKeyboardButton(text=f"{label}: {val}", callback_data="dash:noop"),
            InlineKeyboardButton(text=f"+{step}", callback_data=f"dash:p:{key}:+{step}"),
        ])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dash:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
