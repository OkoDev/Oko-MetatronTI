"""
Действия меню исторического анализа — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


async def show_performance_analysis(bot, message: Message) -> None:
    """Показ общей эффективности."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("📊 Исторический анализатор недоступен")
        return
    m = ha.calculate_performance_metrics()
    lines = [
        "📊 <b>Эффективность за всё время</b>",
        f"Сигналов: {m.total_signals}",
        f"Win rate: {m.win_rate:.1%}",
        f"Success rate: {m.success_rate:.1%}",
        f"Profit Factor: {m.profit_factor:.2f}",
        f"Max DD: {m.max_drawdown:.2f}%",
    ]
    await message.answer("\n".join(lines))


async def show_performance_trend(bot, message: Message) -> None:
    """Показ тренда производительности за 7 дней."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("📈 Исторический анализатор недоступен")
        return
    trend = ha.get_performance_trend(days=7)
    if not trend:
        await message.answer("📈 Недостаточно данных для тренда (7д)")
        return
    lines = ["📈 <b>Тренд (7д)</b>"]
    for d, v in list(trend.items())[-7:]:
        lines.append(f"• {d}: SR={v['success_rate']:.1%} PF={v['profit_factor']:.2f} N={v['total_signals']}")
    await message.answer("\n".join(lines))


async def show_analysis_by_type(bot, message: Message) -> None:
    """Показ эффективности по типам сигналов."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("🎯 Исторический анализатор недоступен")
        return
    by_type = ha.get_performance_by_signal_type()
    if not by_type:
        await message.answer("🎯 Нет данных по типам сигналов")
        return
    lines = ["🎯 <b>По типам сигналов</b>"]
    for t, m in by_type.items():
        lines.append(f"• {t}: SR={m.success_rate:.1%} PF={m.profit_factor:.2f} N={m.total_signals}")
    await message.answer("\n".join(lines))


async def show_signal_history(bot, message: Message) -> None:
    """Показ последних 10 сигналов из истории."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("📚 Исторический анализатор недоступен")
        return
    sigs = ha.get_signals(limit=10)
    if not sigs:
        await message.answer("📚 История пуста")
        return
    lines = ["📚 <b>Последние сигналы</b>"]
    for s in sigs[:10]:
        lines.append(f"• {s.timestamp:%Y-%m-%d %H:%M} {s.symbol} {s.signal_type} → {s.outcome.value}")
    await message.answer("\n".join(lines))


async def show_improvement_recommendations(bot, message: Message) -> None:
    """Показ рекомендаций по улучшению."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("💡 Исторический анализатор недоступен")
        return
    recs = ha.get_recommendations_for_improvement()
    lines = ["💡 <b>Рекомендации</b>"]
    for r in recs:
        lines.append(f"• {r}")
    await message.answer("\n".join(lines))


async def show_detailed_statistics(bot, message: Message) -> None:
    """Показ детальной статистики."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("📊 Исторический анализатор недоступен")
        return
    m = ha.calculate_performance_metrics()
    lines = [
        "📊 <b>Детальная статистика</b>",
        f"Всего сигналов: {m.total_signals}",
        f"Успешные/Неуспешные/Частичные: {m.successful_signals}/{m.failed_signals}/{m.partial_signals}",
        f"Win rate: {m.win_rate:.1%}",
        f"Avg Profit: {m.average_profit:.2f} | Avg Loss: {m.average_loss:.2f}",
        f"Profit Factor: {m.profit_factor:.2f} | Sharpe: {m.sharpe_ratio:.2f}",
    ]
    await message.answer("\n".join(lines))


async def refresh_history_data(bot, message: Message) -> None:
    """Обновление / очистка устаревших данных истории."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("🔄 Исторический анализатор недоступен")
        return
    ok = ha.cleanup_old_data()
    await message.answer("✅ Данные обновлены" if ok else "❌ Не удалось обновить данные")


async def export_history_data(bot, message: Message) -> None:
    """Экспорт метрик производительности в БД."""
    ha = getattr(bot.trading_intelligence, "historical_analyzer", None)
    if not ha:
        await message.answer("📤 Исторический анализатор недоступен")
        return
    m = ha.calculate_performance_metrics()
    ok = ha.save_performance_metrics(m)
    await message.answer("📤 Метрики сохранены в базу" if ok else "❌ Ошибка сохранения метрик")
