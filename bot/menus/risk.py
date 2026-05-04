"""
Меню риск-менеджмента — реальные данные из simulated_trades через PerformanceEngine.
Бот работает в режиме симуляции, реальных позиций нет.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


def _get_pe(bot):
    from core.trading.performance_engine import PerformanceEngine
    db = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
    return PerformanceEngine(db)


async def show_risk_profile(bot, message: Message) -> None:
    """Профиль риска на основе статистики симулированных сделок."""
    pe = _get_pe(bot)
    s = pe.summary()
    rows = pe.by_signal_type()
    lines = ["<b>Профиль риска (симуляция)</b>"]
    if s:
        lines += [
            f"Win rate: {s['win_rate']}%" if s.get("win_rate") is not None else "Win rate: —",
            f"Avg R: {s.get('avg_r', '—')}",
            f"Avg R (win): {s.get('avg_r_win', '—')} | Avg R (loss): {s.get('avg_r_loss', '—')}",
            f"Закрытых сделок: {s.get('closed_count', 0)}",
        ]
    if rows:
        lines.append("\n<b>По типам:</b>")
        for r in rows:
            wr = f"{r['win_rate']}%" if r.get("win_rate") is not None else "—"
            lines.append(f"• {r['signal_type']}: WR={wr} avgR={r.get('avg_r','—')}")
    await message.answer("\n".join(lines))


async def show_active_positions(bot, message: Message) -> None:
    """Открытые симулированные сделки."""
    pe = _get_pe(bot)
    trades = pe.open_trades()
    if not trades:
        await message.answer("Нет открытых сделок")
        return
    lines = [f"<b>Открытые сделки ({len(trades)})</b>"]
    for t in trades[:10]:
        lines.append(
            f"• {t['symbol']} {t['direction']} | entry={t['entry_price']:.4f} "
            f"SL={t['stop_loss']:.4f} TP={t['take_profit']:.4f}"
        )
    await message.answer("\n".join(lines))


async def show_position_sizes(bot, message: Message) -> None:
    """Информация о размерах позиций из конфига."""
    from core.infra.config_loader import config
    risk_pct = config.get("trading.risk_per_trade_pct", 1.0)
    sl_pct = config.get("trading.sl_pct", 2.0)
    tp_pct = config.get("trading.tp_pct", 4.0)
    lines = [
        "<b>Параметры позиций (конфиг)</b>",
        f"Риск на сделку: {risk_pct}%",
        f"Stop Loss: {sl_pct}%",
        f"Take Profit: {tp_pct}%",
        f"R/R ratio: {round(tp_pct / sl_pct, 2) if sl_pct else '—'}",
    ]
    await message.answer("\n".join(lines))


async def show_stop_losses(bot, message: Message) -> None:
    """Информация о стоп-лоссах."""
    await message.answer(
        "Для расчёта SL/TP используйте команду /intelligence SYMBOL — "
        "уровни предлагаются в рекомендациях анализа."
    )


async def show_risk_reward_ratio(bot, message: Message) -> None:
    """R/R статистика по закрытым сделкам."""
    pe = _get_pe(bot)
    rows = pe.by_direction()
    s = pe.summary()
    lines = ["<b>Соотношение риск/прибыль</b>"]
    if s:
        lines.append(f"Общий avg R: {s.get('avg_r', '—')}")
        lines.append(f"Avg R win: {s.get('avg_r_win', '—')} | Avg R loss: {s.get('avg_r_loss', '—')}")
    if rows:
        for r in rows:
            lines.append(f"• {r['direction']}: avgR={r.get('avg_r','—')} WR={r.get('win_rate','—')}%")
    await message.answer("\n".join(lines))


async def show_risk_warnings(bot, message: Message) -> None:
    """Предупреждения на основе статистики."""
    pe = _get_pe(bot)
    s = pe.summary()
    warnings = []
    if s.get("win_rate") is not None and s["win_rate"] < 35:
        warnings.append(f"Win rate {s['win_rate']}% — ниже 35%")
    if s.get("avg_r") is not None and s["avg_r"] < -0.3:
        warnings.append(f"Avg R = {s['avg_r']} — отрицательный")
    if not warnings:
        await message.answer("Нарушений риск-правил не обнаружено")
        return
    lines = ["<b>Предупреждения</b>"]
    for w in warnings:
        lines.append(f"• {w}")
    await message.answer("\n".join(lines))


async def show_risk_statistics(bot, message: Message) -> None:
    """Статистика рисков по режимам рынка."""
    pe = _get_pe(bot)
    by_regime = pe.by_regime()
    s = pe.summary()
    lines = ["<b>Статистика рисков</b>"]
    if s:
        lines += [
            f"Закрытых: {s.get('closed_count', 0)} | Open: {s.get('open_count', 0)}",
            f"Win rate: {s.get('win_rate', '—')}% | Avg R: {s.get('avg_r','—')}",
        ]
    if by_regime:
        lines.append("\n<b>По режиму рынка:</b>")
        for r in by_regime:
            wr = f"{r['win_rate']}%" if r.get("win_rate") is not None else "—"
            lines.append(f"• {r['regime']}: {r['total']} сд. WR={wr} avgR={r.get('avg_r','—')}")
    await message.answer("\n".join(lines))


async def show_risk_settings(bot, message: Message) -> None:
    """Настройки риска из конфига."""
    from core.infra.config_loader import config
    lines = [
        "<b>Настройки риска</b>",
        f"Риск на сделку: {config.get('trading.risk_per_trade_pct', 1.0)}%",
        f"Stop Loss: {config.get('trading.sl_pct', 2.0)}%",
        f"Take Profit: {config.get('trading.tp_pct', 4.0)}%",
        f"TSL: {'включён' if config.get('trading.use_tsl', True) else 'выключен'}",
        f"TSL активация: +{config.get('trading.tsl_activation_r', 1.0)}R",
    ]
    await message.answer("\n".join(lines))
