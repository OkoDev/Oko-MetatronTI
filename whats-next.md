# Handoff — следующая сессия

**Обновлено:** 22.09.2026 00:30 UTC, ветка `arch-128-oko-sm` (Даат)

## Где мы (одним абзацем)
Направление одно — волновая семья на ядре OKO-SM (ARCH-137). За 19–21.09 построена карта «режим × механика × сторона»
(8 механик, 65k сделок, реплеи «как в бою» + оба контроля) и два слоя контекста поверх неё: нога OKO-SM и пятёрка ядра.
Главный вывод: **завершённая пятёрка ядра 4h — мастер-контекст**: разворот после пятой поднимает каждую механику,
продолжение после пятой — минус у всех. Бой при этом стоит на VST, который исполняет по несуществующим ценам, поэтому
форвард меряется переигрыванием заявок на публичных klines (`scratchpad/vst_real_resolve.py`).

## Сделано 19–21.09 (коммиты)
- `62c8510` `f6fbe1c` — OTE сведена на канон 0.5–0.79 (`core/smc/fibonacci.py`), ote_detector развязан
- `923cd9f` `bc94ccf` — тень: порог истории 400 баров, список молодых монет на /waves свёрнут
- `0213d18` — `min_rr_per_strategy.waves_long: 0.3`
- `2d9d79f` — waves_long: повторные входы по тому же импульсу разрешены, пропуски в лог
- Замеры (память): `regime_map_mechanics_v1` · `ote_nested_replay_dead_on_history` (+ зона 1h/1d хуже) ·
  `vst_phantom_fills_demo_matching` · `forward_measured_on_real_klines_no_real_account` ·
  `ote_context_counter_leg_extreme` · `wave_fifth_is_master_context`

## Ждут решения Егора
1. **ote_nested** — выключить форвард или оставить наблюдением. Реальные цены за месяц: 375 филлов, −0.68/сделку, −256%;
   сейчас 20 открытых = RISK 115% счёта.
2. **waves_long риск-каркас**: 0.5%/сделку + дневной лимит + вес монеты (с рынком × волатильная × кластер).
3. **Выход impulse_fib 1h**: 96 баров (среднее +2.3, медиана −1) или сутки/структура (среднее +1.0, медиана +0.9, WR 64%).

## Дальше по приоритету (Даат)
1. Состояние ядра волн → шина как мастер-контекст (`WaveService` сейчас считает не ядро, `mark_impulse` живёт в тени);
   вес механик по контексту ×0/×1/×2. Правка боя — с подтверждения.
2. Контекст ядра на 1d и 1h (масштаб) и merge=True; «нет импульса, но нога у экстремума».
3. impulse_fib 1h — вход: лимит 0.382 наполняется в 5% заявок; замерить вход по рынку / по слому 15m на реплее.
4. DEV-185.2 на VST: сверять `markPrice` позиции с публичным тикером перед market close (SOL закрыт по 102 при рынке 108).
5. Ревизия молчаливых пропусков в остальных лупах по образцу waves_long.
6. EQH-дверь impulse_fib_15m — пересмотр; SPOT_DUMP_GRID как таймер (WT ±75 после пятой +3.52).

## Инструменты сессии (scratchpad `C:\Users\yogoru\AppData\Local\Temp\claude\...\scratchpad\`)
`map_replays.py` (impulse_fib 1h · choch · rangefade ×3) · `map_parity.py` · `impulse_fib_exit_lab.py` ·
`vst_price_audit.py` · `vst_real_resolve.py` · `ote_variants_replay.py` · `ote_context_map.py` · `wave_phase_context.py`.
Данные: `G:/oko_lab/out/{map_replays,ote_context,wave_phase_ctx,ote_variants,vst_real_resolve*.txt}`.
Ловушки данных: BingX klines — 1m ≤1440/запрос, 5m ≤1000/запрос, всегда ПОСЛЕДНИЕ N окна.

## Состояние бота
pm2 `oko-bot` online (рестарт 21.09 18:44 UTC после фикса waves_long), 20 OPEN ote_nested; тень `wave5-shadow` online;
`structure-term` :8010 online. Реальный мини-счёт: «пока не могу, возможно позже».
