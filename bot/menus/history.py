"""
Меню истории сигналов — данные из simulated_trades через PerformanceEngine.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


def _get_pe(bot):
    from core.performance_engine import PerformanceEngine
    db = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
    return PerformanceEngine(db)


async def show_performance_analysis(bot, message: Message) -> None:
    """Общая сводка по сделкам."""
    pe = _get_pe(bot)
    s = pe.summary()
    if not s:
        await message.answer("Нет данных")
        return
    lines = [
        "<b>Сводка по сделкам</b>",
        f"Всего: {s.get('total', 0)} | Открытых: {s.get('open_count', 0)}",
        f"TP: {s.get('tp_count', 0)} | SL: {s.get('sl_count', 0)} | TSL: {s.get('tsl_count', 0)}",
        f"Win rate: {s['win_rate']}%" if s.get('win_rate') is not None else "Win rate: —",
        f"Avg R: {s.get('avg_r', '—')} | Avg R win: {s.get('avg_r_win', '—')} | Avg R loss: {s.get('avg_r_loss', '—')}",
    ]
    await message.answer("\n".join(lines))


async def show_performance_trend(bot, message: Message) -> None:
    """По направлению LONG/SHORT."""
    pe = _get_pe(bot)
    rows = pe.by_direction()
    if not rows:
        await message.answer("Нет данных по направлениям")
        return
    lines = ["<b>По направлению</b>"]
    for r in rows:
        wr = f"{r['win_rate']}%" if r.get('win_rate') is not None else "—"
        lines.append(f"• {r['direction']}: {r['total']} сделок, WR={wr}, avgR={r.get('avg_r','—')}")
    await message.answer("\n".join(lines))


async def show_analysis_by_type(bot, message: Message) -> None:
    """По типам сигналов."""
    pe = _get_pe(bot)
    rows = pe.by_signal_type()
    if not rows:
        await message.answer("Нет данных по типам сигналов")
        return
    lines = ["<b>По типам сигналов</b>"]
    for r in rows:
        wr = f"{r['win_rate']}%" if r.get('win_rate') is not None else "—"
        lines.append(f"• {r['signal_type']}: {r['total']} сделок, WR={wr}, avgR={r.get('avg_r','—')}")
    await message.answer("\n".join(lines))


async def show_signal_history(bot, message: Message) -> None:
    """Последние 10 закрытых сделок."""
    pe = _get_pe(bot)
    trades = pe.recent_closed(limit=10)
    if not trades:
        await message.answer("История пуста")
        return
    lines = ["<b>Последние 10 сделок</b>"]
    for t in trades:
        r_str = f"R={t['R_multiple']:.2f}" if t.get("R_multiple") is not None else ""
        lines.append(
            f"• {t['symbol']} {t['direction']} {t['status']} {r_str} "
            f"({t.get('closed_at','')[:10]})"
        )
    await message.answer("\n".join(lines))


async def show_improvement_recommendations(bot, message: Message) -> None:
    """Рекомендации на основе реальной статистики."""
    pe = _get_pe(bot)
    s = pe.summary()
    rows = pe.by_signal_type()
    lines = ["<b>Рекомендации</b>"]
    if not s or not s.get("closed_count"):
        lines.append("• Недостаточно закрытых сделок для анализа")
        await message.answer("\n".join(lines))
        return
    wr = s.get("win_rate", 0) or 0
    if wr < 40:
        lines.append(f"• Низкий win rate ({wr}%) — пересмотрите фильтры входа")
    if s.get("avg_r") is not None and s["avg_r"] < 0:
        lines.append("• Отрицательный avg R — проверьте SL/TP соотношение")
    for r in rows:
        if r.get("avg_r") is not None and r["avg_r"] < -0.5 and (r["wins"] or 0) + (r["losses"] or 0) >= 20:
            lines.append(f"• {r['signal_type']}: слабая эффективность (avg R={r['avg_r']})")
    if len(lines) == 1:
        lines.append("• Показатели в норме, продолжайте стратегию")
    await message.answer("\n".join(lines))


async def show_detailed_statistics(bot, message: Message) -> None:
    """Детальная статистика: все разрезы."""
    pe = _get_pe(bot)
    s = pe.summary()
    by_regime = pe.by_regime()
    lines = ["<b>Детальная статистика</b>"]
    if s:
        lines += [
            f"Закрытых: {s.get('closed_count', 0)}",
            f"TP/SL/TSL: {s.get('tp_count',0)}/{s.get('sl_count',0)}/{s.get('tsl_count',0)}",
            f"Win rate: {s['win_rate']}%" if s.get("win_rate") is not None else "Win rate: —",
            f"Avg R: {s.get('avg_r','—')} | Avg profit%: {s.get('avg_profit_pct','—')}",
        ]
    if by_regime:
        lines.append("\n<b>По режиму рынка:</b>")
        for r in by_regime:
            wr = f"{r['win_rate']}%" if r.get('win_rate') is not None else "—"
            lines.append(f"• {r['regime']}: {r['total']} сд., WR={wr}")
    await message.answer("\n".join(lines))


async def refresh_history_data(bot, message: Message) -> None:
    """Данные обновляются в реальном времени из БД."""
    await message.answer("Данные актуальны — история читается из БД напрямую")


async def export_history_data(bot, message: Message) -> None:
    """Краткий экспорт статистики."""
    pe = _get_pe(bot)
    s = pe.summary()
    rows = pe.by_signal_type()
    lines = ["<b>Экспорт статистики</b>"]
    if s:
        lines.append(
            f"Total={s.get('total',0)} TP={s.get('tp_count',0)} SL={s.get('sl_count',0)} "
            f"WR={s.get('win_rate','—')}% avgR={s.get('avg_r','—')}"
        )
    for r in rows:
        lines.append(f"{r['signal_type']}: total={r['total']} WR={r.get('win_rate','—')}% avgR={r.get('avg_r','—')}")
    await message.answer("\n".join(lines))
