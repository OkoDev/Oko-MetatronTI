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

        await asyncio.sleep(86400)  # 24 часа


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
