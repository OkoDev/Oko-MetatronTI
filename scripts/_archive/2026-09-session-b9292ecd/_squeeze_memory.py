import re, os
D = r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot\memory"
p = os.path.join(D, 'MEMORY.md'); s = open(p, encoding='utf-8').read()
A = os.path.join(D, 'MEMORY-ARCHIVE.md'); a = open(A, encoding='utf-8').read()
moved = []


def cut(old):
    global s
    assert old in s, old[:50]
    moved.append(old.strip()); s = s.replace(old, '')


def rep(old, new):
    global s
    assert old in s, old[:50]
    s = s.replace(old, new)


cut('→ [🔴 КАСКАД СОГЛАСИЯ ВВЕРХ ПО ЛЕСТНИЦЕ — СНЯТ 09.09 как look-ahead вида 6](cascade_of_agreement_up_the_ladder.md)\n')
cut('→ [🟡🔴 WT-СХЕМА ЕГОРА: как стратегия закрыта, лонг-сторона несёт +1.4 п.п. над базой](wt_htf_zone_median_scheme_measured.md)\n')
cut('→ [🌊 ПРОГРАММА 3m + АНАЛИТИК (14.09): этапы и журнал — читать при продолжении](wave_3m_program.md)\n')
cut('→ [🔴 ЛЕСТНИЦА МИНУСОВЫХ ФИБО: цели после входа на коррекции не добирают до Б/У, контроль лучше сигнала 9 из 10](fib_minus_targets_ladder_measured.md)\n')
cut('→ [🌊 КАНОН IKIGAI В РАЗВОЛНОВКЕ](elliott_canon_ikigai_implemented.md) · [🌊 волновой детектор в PINE](okowave_pine_port_verified.md) · [🔴 `leg_span_bars` бывает отрицательным](leg_span_bars_can_be_negative.md)\n')
cut('→ [🟢🔴 ВОЛНА (ARCH-137): 1h long «короткая чистая нога»](wave_leg_1h_long_candidate.md)\n')
cut('→ [🟡 ТРИ ОСИ «SHORT У УРОВНЯ» — вердикт по EQH в файле ОТМЕНЁН](short_at_significant_level_three_axes.md) · [🟢 EQH пережил ядро 97 монет](eqh_liquidity_short_works_in_2026.md)\n')
cut('→ [🔑 ЗАВИСИМОСТЬ ОТ ОКНА: ломается ТОЛЬКО SMC](window_sensitivity_only_smc_breaks.md)\n')
cut('→ [🔴 LONG под пробитым swing-минимумом — ОПРОВЕРГНУТА](long_below_broken_swing_low.md) · [🟡🔴 RS: градиент реален, LONG-ОСЬ НЕТ](long_relative_strength_axis.md)\n')
cut('→ [🟢 отскок после капитуляции — первый живой long 15m](long_capitulation_bounce_candidate.md)\n')
cut('→ [🔑 кластер ФИЛЛОВ ≠ кластер СЕТАПОВ](cluster_of_fills_not_setups.md)\n')
cut('→ Вывод зачистки: простые правила 15m-4h после костов эджа НЕ имеют. Живут: многолетнее тонкое, ИСПОЛНЕНИЕ, редкие неэффективности, decision-support, старшие ТФ\n')
cut('→ 📦 [ВТОРОЙ КРУГ ПАМЯТИ: фейд/big-flush, инфра-эпики, дашборд, продукт](MEMORY-ARCHIVE.md)\n')

rep('→ [🔴🔴🔴 КАРТА РАМКИ: у ЛОНГА нет положительной медианы НИ НА ОДНОМ горизонте, деньги в хвосте → стоп их отрезает; кост = 22.6% часового хода](frame_map_no_positive_median_for_long.md)',
    '→ [🔴🔴🔴 КАРТА РАМКИ: у лонга нет положительной медианы ни на одном горизонте, деньги в хвосте](frame_map_no_positive_median_for_long.md)')
rep('→ [🟡 КАНДИДАТ: лонг от ГЛУБОКОЙ перепроданности WT на 1h — монотонный градиент, прошёл суррогат, 3/5 лет без перекрытия](wt_deep_oversold_long_candidate.md)\n→ 📦 оформлено как стратегия **SPOT_DUMP_GRID** (`docs/STRATEGIES/SPOT_DUMP_GRID.md`, 11.09) — спот, лонг, сетка 30-60 слотов, ≤30% депозита в сделках (вводные Егора)',
    '→ [🟡 КАНДИДАТ: лонг от глубокой перепроданности WT 1h → стратегия SPOT_DUMP_GRID (`docs/STRATEGIES/SPOT_DUMP_GRID.md`)](wt_deep_oversold_long_candidate.md)')
rep('→ [🟢🔴 ЯДРО волн на OKO-SM = ФРАКТАЛ × КАНАЛ × ЧЕРЕДОВАНИЕ × КАНОНИЧЕСКИЙ СЧЁТ (15/4): line24 19/год WR 75% цель 66%, кросс 34/год R 1.1; единица = ДЕНЬ; стоп = обмен](wave5_core_oko_sm.md) · [🟢 ТЕНЬ-ФОРВАРД запущена 13.09 — `wave5_shadow.py`, живой BingX, CSV для сверки](wave5_shadow_forward.md)',
    '→ [🟢🔴 ЯДРО волн на OKO-SM = фрактал × канал × чередование × счёт (15/4); единица = ДЕНЬ](wave5_core_oko_sm.md) · [🟢 ТЕНЬ-ФОРВАРД с 13.09 (`wave5_shadow.py`)](wave5_shadow_forward.md) · [🌊 программа 3m](wave_3m_program.md)')
rep('→ [🔴🟢 ТФ ЯДРА (16.09): живёт ТОЛЬКО 4h (+0.79); 2h/1d/15m/5m = ноль при любом триггере](wave5_mechanics_across_timeframes.md) · [🟡 кандидат: вход по слому SWING 15m, LONG+ядро Δ +2.51](candidate_choch_swing_entry_4h.md)',
    '→ [🔴🟢 ТФ ЯДРА: живёт ТОЛЬКО 4h](wave5_mechanics_across_timeframes.md) · [🟡 кандидат: вход по слому SWING 15m, Δ +2.51](candidate_choch_swing_entry_4h.md)')
rep('→ [🔑 2025-26 = ФЛЭТ BTC (итог ~0, размах 70%); «медведь» в таблицах = дрейф альтов, ДРУГАЯ ОСЬ](regime_2026_is_btc_range_not_bear.md) · [🌊 цели ABC: берутся втрое чаще, денег вдвое меньше](rebound_targets_abc_measured.md)',
    '→ [🔑 2025-26 = ФЛЭТ BTC; «медведь» в таблицах = дрейф альтов](regime_2026_is_btc_range_not_bear.md) · [🌊 цели ABC: чаще, но денег вдвое меньше](rebound_targets_abc_measured.md)')
rep('→ [🔴🔑 LTF = СЛОЙ ИСПОЛНЕНИЯ, НЕ ИСТОЧНИК СИГНАЛА: импульс и отбой от границ на 15m мертвы, но вход по слому 15m для сетапа 4h даёт +4](ltf_is_execution_layer_not_signal_source.md)',
    '→ [🔴🔑 LTF = СЛОЙ ИСПОЛНЕНИЯ, НЕ ИСТОЧНИК СИГНАЛА](ltf_is_execution_layer_not_signal_source.md)')
rep('→ [🔴 ФЕЙД ЗАВЕРШЁННОГО ИМПУЛЬСА = ХВОСТ, А НЕ ЭДЖ](elliott_impulse_fade_tail_not_edge.md) · [🔴 ПРОБОЙ КОРРЕКЦИЙ a-b-c-d-e (флаг/треугольник/клин) = случайный вход, 1.8 млн сделок](five_wave_corrections_breakout_measured.md) · [🔴 ПРОБОЙ ХАЯ ПАМПА С ЗАКРЕПОМ = ноль, живёт только число касаний ≥3](level_breakout_pump_high_measured.md)',
    '→ [🔴 ФЕЙД ИМПУЛЬСА = хвост](elliott_impulse_fade_tail_not_edge.md) · [🔴 ПРОБОЙ КОРРЕКЦИЙ a-b-c-d-e = случайный вход (1.8 млн)](five_wave_corrections_breakout_measured.md) · [🔴🔴 УРОВНИ (5 кругов, 4.5 млн): пробой/отбой/ретест/ложный = случайный; «своя игра» +7 п.п. WR, денег нет](level_breakout_pump_high_measured.md)')
rep('**Второй круг (перенесено 14.09 в [MEMORY-ARCHIVE](MEMORY-ARCHIVE.md)):** режим рынка и гейты ширины · импульсная механика боевого · приборы врали (косты в БД, фантомы, спред VST) · молчаливые отказы конфигов · эпики/инфра/скан/TradingView — открывать ПО ПОВОДУ.',
    '**В [MEMORY-ARCHIVE](MEMORY-ARCHIVE.md):** второй круг (режим/гейты ширины, импульсная механика, приборы врали, молчаливые отказы конфигов, эпики/инфра) + закрытые направления (каскад согласия, WT-схема, лестница фибо, RS-ось, EQH, капитуляция, кластер филлов) — открывать ПО ПОВОДУ.')
rep('→ [🔴🔑 «OTE» = ПЯТЬ РАЗНЫХ ЗОН в коде (0.21-0.79 … 0.705-0.786): признак истинен то 61%, то 8% времени](ote_canon_five_definitions.md)',
    '→ [🔴🔑 «OTE» = ПЯТЬ РАЗНЫХ ЗОН в коде — канон не выбран](ote_canon_five_definitions.md)')
rep('- Отчёты 21.08: [карта гипотез](https://claude.ai/code/artifact/9a6d82cd-9a08-47c4-91b6-9ed0dffa8d0b) · [три отменённых вердикта](https://claude.ai/code/artifact/1b7bf405-19d5-4693-a175-56d62ae7b42e) · данные в `obsidian/Research/`\n', '')
rep('- 📘 [Методичка Эллиотта для Егора (артефакт, 13 глав, схемы)](elliott_guide_artifact.md) · страница ядра волн: https://claude.ai/code/artifact/455e8973-98a7-43c1-907f-13447d2608f4',
    '- 📘 [Методичка Эллиотта (артефакт)](elliott_guide_artifact.md) · страница ядра волн: https://claude.ai/code/artifact/455e8973-98a7-43c1-907f-13447d2608f4 · отчёты 21.08 и данные — `obsidian/Research/`')
rep('> Sweep 10.09.2026: 28.6 КБ → цель ≤15 КБ. Хвосты-описания после ссылок вырезаны — они и раздували индекс.',
    '> Sweep 19.09.2026: ≤15 КБ. Закрытые направления → MEMORY-ARCHIVE.')
s = re.sub(r'\n{3,}', '\n\n', s)
open(p, 'w', encoding='utf-8').write(s)
a = a.rstrip('\n') + '\n\n## 📦 Перенесено из MEMORY.md 19.09.2026 (бюджет индекса) — закрытые/второстепенные направления\n' + '\n'.join(moved) + '\n'
open(A, 'w', encoding='utf-8').write(a)
print('MEMORY.md', os.path.getsize(p), 'байт · перенесено строк', len(moved))
