# -*- coding: utf-8 -*-
"""ИМПУЛЬС → ЛИМИТ 0.382 на 1h — боевой инстанс механики с лучшим OOS в проекте.

Поведение целиком в `bot/loops/impulse_fib_runner.py` (фаза 3 реестра, 22.08.2026):
раньше этот файл и `impulse_fib_15m_loop.py` были клонами, отличавшимися СЕМЬЮ
строками-параметрами. Здесь остаётся только описание инстанса.

Расчёт сетапа — в `core/smc/impulse_fib.py` ([[principle_reuse_not_duplication]]).

Отличия от `choch_wavec_loop`, которые и были причиной замены источника:
  · ДВЕ стороны — choch_wavec торгует только шорт, здесь long и short (цели разные);
  · частота — choch_wavec за сутки не дал НИ ОДНОЙ сделки (103 из 120 сетапов
    протухали за 12-барное окно);
  · стоп 2.5·ATR (~4.4%) вместо ~8.5% за начало импульса: при плече 10 старый стоп
    стоял ЗА ликвидацией — 123 ликвидации из 503 сделок против 12 у нового.

🔴 Окна инстанса: 12 баров ожидания фила и 96 баров удержания = 12 ч и 96 ч,
ровно как в замере механики. На 1h множитель ТФ равен 1.

Gated: trading.impulse_fib.enabled (по умолчанию ВЫКЛЮЧЕН).
"""
from __future__ import annotations

from bot.loops.impulse_fib_runner import Instance, make_loop, make_resolve, table_sql

INSTANCE = Instance(src="impulse_fib", tf="1h", tf_mult=1,
                    table="impulse_shadow", tag="IMPULSE")

# Имена сохранены: их импортируют `bot/core/bot.py` и `scripts/verify_impulse_fib_loop.py`.
_TABLE = table_sql(INSTANCE)
_resolve = make_resolve(INSTANCE)
impulse_fib_loop = make_loop(INSTANCE)
