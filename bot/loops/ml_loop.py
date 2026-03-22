"""
Фоновые ML-циклы: обучение моделей и еженедельный отчёт.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


async def ml_training_loop(bot) -> None:
    """Первичное обучение ML через 2 мин после старта, затем каждые 24ч."""
    await asyncio.sleep(120)
    while True:
        try:
            ok = await bot.trading_intelligence.train_ml_models(training_period_days=30)
            if ok:
                logger.info("ML-модели успешно обучены/переобучены")
        except Exception as e:
            logger.warning(f"Ошибка обучения ML: {e}")

        # Этап 7: обучение R-регрессора (требует 100+ закрытых сделок с max_R_possible)
        try:
            db_path = bot.trade_simulator.db_path
            r_ok = await asyncio.get_event_loop().run_in_executor(
                None, bot.r_predictor.fit, db_path
            )
            if r_ok:
                logger.info(
                    "RPredictor обучен: %d сделок, CV RMSE=%.3f",
                    bot.r_predictor._n_samples,
                    bot.r_predictor._cv_rmse or 0,
                )
        except Exception as e:
            logger.warning("Ошибка обучения RPredictor: %s", e)

        # ARCH-12.5: автокалибровка MTF multipliers по реальным исходам
        try:
            calibrator = getattr(bot.trading_intelligence, '_auto_calibrator', None)
            if calibrator:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, calibrator.calibrate
                )
                if result.adjustments:
                    logger.info(
                        "AutoCalibrator: %d корректировок из %d сделок",
                        len(result.adjustments), result.total_trades,
                    )
                    # Отправка отчёта в TG (если есть подписчики)
                    try:
                        subscribers = getattr(bot, 'subscribers', set())
                        if subscribers and hasattr(bot, 'bot_instance'):
                            text = result.summary_text()
                            for uid in subscribers:
                                try:
                                    await bot.bot_instance.send_message(
                                        uid, text, parse_mode="HTML"
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        logger.debug("AutoCalibrator: не удалось отправить TG отчёт")
                else:
                    logger.info("AutoCalibrator: корректировки не требуются (%d сделок)", result.total_trades)
        except Exception as e:
            logger.warning("AutoCalibrator: ошибка калибровки: %s", e)

        await asyncio.sleep(86400)  # 24 часа


async def wr_health_check_loop(bot) -> None:
    """DEV-27: Rolling WR degradation detector — проверка каждые 6 часов.

    Если rolling WR (window=50) < 40% → WARNING лог.
    Если < 30% → CRITICAL лог + TG уведомление всем подписчикам.
    """
    from core.performance_engine import PerformanceEngine
    from core.config_loader import config as _cfg
    await asyncio.sleep(300)  # 5 мин после старта — дать боту прогреться
    while True:
        try:
            window = _cfg.get("monitoring.wr_check_window", 50)
            warn_thr = _cfg.get("monitoring.wr_warn_threshold", 40.0)
            crit_thr = _cfg.get("monitoring.wr_critical_threshold", 30.0)
            db_path = bot.trade_simulator.db_path
            pe = PerformanceEngine(db_path)
            result = pe.check_wr_degradation(
                window=window,
                warn_threshold=warn_thr,
                critical_threshold=crit_thr,
            )
            if result is None:
                logger.debug("wr_health_check: недостаточно данных для оценки WR")
            elif result["status"] == "critical":
                logger.critical("DEV-27 WR DEGRADATION: %s", result["message"])
                # Уведомление в TG всем подписчикам
                try:
                    subscribers = getattr(bot, 'subscribers', set())
                    if subscribers and hasattr(bot, 'bot_instance'):
                        for uid in subscribers:
                            try:
                                await bot.bot_instance.send_message(uid, result["message"])
                            except Exception:
                                pass
                except Exception:
                    pass
            elif result["status"] == "warn":
                logger.warning("DEV-27 WR WARN: %s", result["message"])
            else:
                logger.info("DEV-27 WR OK: %s", result["message"])
        except Exception as e:
            logger.exception("wr_health_check_loop: %s", e)
        await asyncio.sleep(6 * 3600)  # каждые 6 часов


async def auto_review_loop(bot) -> None:
    """DEV-12 (8.4.9): Еженедельный авто-анализ метрик системы.

    Раз в 7 дней собирает:
      - WR по signal_type (есть деградация?)
      - WR по режиму рынка (regime drift?)
      - Confidence calibration error (ECE)
      - Топ символов по WR
    Логирует отчёт + отправляет в TG администратору.
    """
    from core.performance_engine import PerformanceEngine
    from core.config_loader import config as _cfg

    await asyncio.sleep(600)  # 10 мин после старта

    while True:
        try:
            db_path = bot.trade_simulator.db_path
            pe = PerformanceEngine(db_path)

            lines = ["📊 <b>Авто-ревью метрик (DEV-12/8.4.9)</b>", ""]

            # 1. WR по signal_type
            by_type = pe.by_signal_type()
            if by_type:
                lines.append("<b>WR по signal_type:</b>")
                for row in sorted(by_type, key=lambda r: -(r.get("total") or 0))[:7]:
                    sig = row.get("signal_type", "?")
                    total = row.get("total") or 0
                    wr = row.get("win_rate") or 0
                    avg_r = row.get("avg_r") or 0
                    lines.append(f"  {sig}: WR={wr:.0f}% avgR={avg_r:+.2f} (n={total})")
                lines.append("")

            # 2. WR по режиму
            try:
                regime_stats = pe.by_regime() if hasattr(pe, "by_regime") else []
                if regime_stats:
                    lines.append("<b>WR по режиму:</b>")
                    for row in regime_stats:
                        reg = row.get("regime", "?")
                        total = row.get("total") or 0
                        wr = row.get("win_rate") or 0
                        lines.append(f"  {reg}: WR={wr:.0f}% (n={total})")
                    lines.append("")
            except Exception:
                pass

            # 3. Confidence calibration (ECE)
            try:
                op = getattr(bot.trading_intelligence, "outcome_predictor", None)
                if op and op.is_trained:
                    info = op.info()
                    cal = info.get("calibrator", {})
                    ece = cal.get("ece")
                    if ece is not None:
                        ece_label = "✅ хорошо" if ece < 0.05 else ("⚠️ умеренно" if ece < 0.10 else "❌ плохо")
                        lines.append(f"<b>Confidence ECE:</b> {ece:.3f} {ece_label}")
                        lines.append("")
            except Exception:
                pass

            # 4. Общая сводка
            summary = pe.summary()
            if summary:
                total = summary.get("total_trades", 0)
                wr = summary.get("win_rate", 0)
                avg_r = summary.get("avg_r", 0)
                lines.append(f"<b>Итого:</b> {total} сделок | WR={wr:.0f}% | avgR={avg_r:+.2f}")

            report = "\n".join(lines)
            logger.info("auto_review_loop:\n%s", report.replace("<b>", "").replace("</b>", ""))

            # Отправка администратору
            try:
                admin_id = _cfg.get("telegram.admin_id")
                if admin_id and hasattr(bot, "bot_instance"):
                    await bot.bot_instance.send_message(
                        int(admin_id), report, parse_mode="HTML"
                    )
            except Exception as tg_err:
                logger.debug("auto_review_loop: TG отправка: %s", tg_err)

        except Exception as e:
            logger.exception("auto_review_loop: %s", e)

        await asyncio.sleep(7 * 24 * 3600)  # раз в 7 дней


async def weekly_report_loop(bot) -> None:
    """Отправляет отчёт каждое воскресенье в 20:00 UTC."""
    from bot.monitoring import send_weekly_report
    while True:
        try:
            now = datetime.now(timezone.utc)
            days_to_sunday = (6 - now.weekday()) % 7 or 7
            target = now.replace(hour=20, minute=0, second=0, microsecond=0)
            target += timedelta(days=days_to_sunday)
            await asyncio.sleep((target - now).total_seconds())
            await send_weekly_report(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("weekly_report_loop: %s", e)
            await asyncio.sleep(3600)
