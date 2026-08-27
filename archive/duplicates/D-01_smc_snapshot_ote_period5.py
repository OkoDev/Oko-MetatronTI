"""
═══════════════════════════════════════════════════════════════════════════════
АРХИВ ДУБЛЯ D-01 — OTE-импульс от мелких свингов (period=5)
═══════════════════════════════════════════════════════════════════════════════
Извлечён из:  core/smc/smc_snapshot.py (build_smc_snapshot, OTE-блок)
Дата вывода:  11.06.2026
Почему выведен:
    Считал OTE-импульс от `sa.last_high`/`sa.last_low` — ПОСЛЕДНИХ свингов
    detect_structure(period=5). Брал мелкую рябь вместо значимого импульса.
    Для XLM 4h давал retracement 105% / SHORT, тогда как торговля (zigzag 11/3)
    и эталон OKO-SM = 72% / LONG. Расхождение на 5 из 6 ТФ (см. bug_ote_impulse_period5).
Чем заменён:
    `core.smc.smc_engine.ote_retest_setups(df, depth, dev)` — тот же zigzag per-ТФ,
    что торгует ote_signal_generator (единый OTE-калькулятор, конец дрейфа).
Когда может пригодиться:
    period=5 свинги ПРАВИЛЬНЫ для быстрых structure-breaks / CHoCH (мелкая
    чувствительность LTF, эталон calib_choch_length5). Если понадобится «локальный»
    мелко-свинговый импульс отдельно от значимого OTE — код ниже готов вернуться.

Спит. Не импортируется. Читаем.
═══════════════════════════════════════════════════════════════════════════════
"""

# --- старый OTE-блок smc_snapshot.py (period=5) -------------------------------
# if senior_tf is not None and senior_tf in structures_by_tf:
#     df_sr = ohlcv_by_tf[senior_tf]
#     try:
#         struct_sr = structures_by_tf[senior_tf]
#         sa = struct_sr.swing_analysis
#         bars_sr = len(df_sr)
#         if sa.last_high is not None:
#             swing_high = {
#                 "tf": senior_tf,
#                 "price": sa.last_high.value,
#                 "age_bars": max(0, bars_sr - 1 - int(sa.last_high.index)),
#             }
#         if sa.last_low is not None:
#             swing_low = {
#                 "tf": senior_tf,
#                 "price": sa.last_low.value,
#                 "age_bars": max(0, bars_sr - 1 - int(sa.last_low.index)),
#             }
#         # Направление импульса: что свежее — high или low
#         if sa.last_high is not None and sa.last_low is not None:
#             impulse_high = sa.last_high.value
#             impulse_low = sa.last_low.value
#             if impulse_high > impulse_low:
#                 direction = "LONG" if sa.last_high.index > sa.last_low.index else "SHORT"
#                 ote_direction = direction
#                 ote_tf = senior_tf
#                 fib_levels = _calc_fib_levels(impulse_high, impulse_low, direction)
#                 diff = impulse_high - impulse_low
#                 if diff > 0:
#                     if direction == "LONG":
#                         current_retracement = round(
#                             (impulse_high - current_price) / diff * 100.0, 2
#                         )
#                     else:
#                         current_retracement = round(
#                             (current_price - impulse_low) / diff * 100.0, 2
#                         )
#                     ote_top = fib_levels.get(f"{_OTE_TOP_RATIO:.3f}")
#                     ote_bot = fib_levels.get(f"{_OTE_BOT_RATIO:.3f}")
#                     if ote_top is not None and ote_bot is not None:
#                         lo, hi = min(ote_top, ote_bot), max(ote_top, ote_bot)
#                         price_in_ote = lo <= current_price <= hi
#     except Exception as e:
#         logger.debug("[SMC_SNAP] %s senior_tf(%s) error: %s", symbol, senior_tf, e)
