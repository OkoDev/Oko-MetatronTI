"""
Действия меню управления рисками — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


async def show_risk_profile(bot, message: Message) -> None:
    """Показ профиля риска портфеля."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("🛡️ Менеджер рисков недоступен")
        return
    summary = rm.get_risk_summary()
    recs = rm.get_risk_recommendations()
    lines = [
        "🛡️ <b>Профиль риска портфеля</b>",
        f"Капитал: ${summary['base_capital']:.2f}",
        f"Экспозиция: ${summary['total_exposure']:.2f} ({summary['exposure_percent']:.1f}%)",
        f"Суммарный риск: ${summary['total_risk']:.2f} ({summary['risk_percent']:.2f}%)",
        f"Активных позиций: {summary['active_positions']}",
        f"Профилей риска: {summary['risk_profiles']}",
        "",
        "💡 <b>Рекомендации:</b>",
    ]
    for r in recs:
        lines.append(f"• {r}")
    await message.answer("\n".join(lines))


async def show_active_positions(bot, message: Message) -> None:
    """Показ активных позиций."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm or not rm.active_positions:
        await message.answer("📊 Активных позиций нет")
        return
    lines = ["📊 <b>Активные позиции</b>"]
    for sym, pos in list(rm.active_positions.items())[:10]:
        lines.append(
            f"• {sym}: size={pos.position_size:.4f}, entry={pos.entry_price:.4f}, "
            f"SL={pos.stop_loss:.4f}, TP={pos.take_profit:.4f}"
        )
    await message.answer("\n".join(lines))


async def show_position_sizes(bot, message: Message) -> None:
    """Показ шкалы размеров позиций."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("💰 Менеджер рисков недоступен")
        return
    lines = ["💰 <b>Шкала размеров позиций</b>"]
    for name, pct in rm.position_sizes.items():
        lines.append(f"• {name.value}: {pct*100:.2f}% от капитала")
    await message.answer("\n".join(lines))


async def show_stop_losses(bot, message: Message) -> None:
    """Информация о стоп-лоссах."""
    await message.answer(
        "🎯 Для расчета SL/TP используйте команду /intelligence SYMBOL — "
        "уровни предлагаются в рекомендациях анализа."
    )


async def show_risk_reward_ratio(bot, message: Message) -> None:
    """Показ общей оценки риск/прибыль."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("📈 Менеджер рисков недоступен")
        return
    s = rm.get_risk_summary()
    lines = [
        "📈 <b>Общая оценка риск/прибыль</b>",
        f"Дневных сделок: {s['daily_trades']}",
        f"Дневной PnL: ${s['daily_pnl']:.2f}",
        f"Макс. просадка: ${s['max_drawdown']:.2f}",
    ]
    await message.answer("\n".join(lines))


async def show_risk_warnings(bot, message: Message) -> None:
    """Показ предупреждений о нарушении риск-правил."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("⚠️ Менеджер рисков недоступен")
        return
    warnings = []
    for pos in rm.active_positions.values():
        _, w = rm.check_risk_limits(pos.symbol, pos)
        warnings.extend(w)
    if not warnings:
        await message.answer("✅ Нарушений риск-правил не обнаружено")
        return
    lines = ["⚠️ <b>Предупреждения</b>"]
    for w in warnings[:10]:
        lines.append(f"• {w}")
    await message.answer("\n".join(lines))


async def show_risk_statistics(bot, message: Message) -> None:
    """Показ статистики рисков."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("📊 Менеджер рисков недоступен")
        return
    s = rm.get_risk_summary()
    lines = [
        "📊 <b>Статистика рисков</b>",
        f"Экспозиция: ${s['total_exposure']:.2f} ({s['exposure_percent']:.1f}%)",
        f"Суммарный риск: ${s['total_risk']:.2f} ({s['risk_percent']:.2f}%)",
        f"Дневной PnL: ${s['daily_pnl']:.2f}",
        f"Серий убытков: {s['consecutive_losses']}",
    ]
    await message.answer("\n".join(lines))


async def show_risk_settings(bot, message: Message) -> None:
    """Показ настроек рисков."""
    rm = getattr(bot.trading_intelligence, "risk_manager", None)
    if not rm:
        await message.answer("⚙️ Менеджер рисков недоступен")
        return
    settings = getattr(rm, "settings", {})
    lines = ["⚙️ <b>Настройки рисков</b>"]
    for key, val in settings.items():
        lines.append(f"{key}: {val}")
    await message.answer("\n".join(lines) if lines else "⚙️ Настройки по умолчанию")
