# OTE-Куб Research — сырьё (02-04.06.2026)

> 🧰 КОНСТРУКТОР. Все сырые прогоны сохранены целиком — даже «проигрышные» и промежуточные.
> Каждая цифра = деталь для компоновки стратегий. Сводка-интерпретация: `docs/RESEARCH_OTE_CUBE_2026-06-03.md`.
> Память: `memory/ote_nested_mtf_strategy.md`.
>
> 💀 **`SETUP_LIBRARY.md` — Шкаф скелетов сетапов** (итоговый каталог: 18 сетапов по тирам 1-2-3,
> квадранты long/short, вклад по типу). ← начинай отсюда, если нужна готовая сетка покрытия.

## Карта логов (raw/) — что в каком прогоне

| Лог | Скрипт | Что меряли | Главное |
|---|---|---|---|
| `ltflog.txt` | ote_ltf.py | плоский LTF 15m/5m изолированно | +0.20 WR43% — слабо без вложенности |
| `nestedlog.txt` | ote_nested.py | nested 5m в 4h-OTE (первый) | риск ×11, n мал (рассинхрон окон) |
| `nested2log.txt` | ote_nested2.py | nested синхрон окон | риск ×10, n=72, WR12% (дальний TP) |
| `nested3log.txt` | ote_nested3.py | + confluence фильтр + SL-буфер | confluence не дискрим, буфер ВРЕДЕН |
| `mfelog.txt` | ote_mfe.py | MFE-распределение + частичный TP | 66%→1R, TP1=1R даёт +0.415 WR66% |
| `matrixlog.txt` | ote_matrix.py | матрица 11 комбо HTF×LTF | 4h→15m золото +0.471; край 1d→5m слаб |
| `cubelog.txt` | ote_cube.py | каскад 3-4 уровня | глубина=качество, 1d→4h→1h→15m WR100% |
| `bidirlog.txt` | ote_bidir.py | двунаправленный 4h→15m | откаты ≥ продолж (+0.600 vs +0.471) |
| `div5mlog.txt` | ote_div5m.py | дивергенция как trend-фильтр | срезает хвост; ОТКАТ 4h→5m +1.128! |
| `divnestedlog.txt` | div_nested.py | hidden+regular в воздухе (широкое окно) | gate фиктивный (60 баров) |
| `divnested2log.txt` | div_nested2.py | hidden+regular узкое окно, 3 группы | B(hid)>A(hid+reg); в воздухе=шум |
| `inzonelog.txt` | ote_div_inzone.py | дивергенция В OTE-зоне | OTE-якорь+div+инвал-SL: WR 14%→44% |
| `synthlog.txt` | ote_synth.py | LTF-слом + дивергенция-ВАЛИДАТОР | C(+hidden) +0.779 WR81% — формула |
| `full45log.txt` | ote_full45.py | валидация 45 пар + data-era | ОТКАТ +0.960 WR79% POST+0.753 победитель |
| `fanlog.txt` | ote_fan.py | веер всех TF-комбо + победители | (последний прогон, портфель) |

## Ключевые скрипты (scripts/)
- **ote_synth.py** — финальная формула куба (LTF-слом + hidden-валидатор).
- **ote_full45.py** — валидация на 45 парах + data-era split.
- **ote_fan.py** — веерное покрытие (все HTF×LTF × continuation/pullback) + таблица победителей.
- Ранние (ote_engine/ote_fib/ote_magnet/ote_backtest) — первые сырые эксперименты эталона OTE.

## Параметры (общие для всех прогонов)
- Данные: `data/history/{tf}/*.parquet`, tail 120K, 45 пар.
- Эталон: `core/smc/smc_engine.ote_retest_setups` (OTE 0.5-0.79, SL=levels[1.0]).
- Дивергенция: `_calc_divergence` (Pine DEV-233, prd5/pp10/bars100).
- Симуляция: частичный TP1=1R (50%) + runner до target, BE после TP1.
- data-era граница: 2026-04-15 (PRE/POST).

## Связь с паттернами DS (отдельный, комбинируемый слой)
- **DS-315** (HTF walkforward): `data/research/2026-06-03--ds315/` — 6906 MHT паттернов.
- **DS-316** (LTF nested): `data/research/2026-06-03--ds316/` — 7779, 15m WR88-97%.
- DS = СТАТИСТИКА (триггеры fvg+rsi/wt), наш куб = ГЕОМЕТРИЯ (зоны+риск). Комбинируются:
  триггер DS внутри нашей nested-структуры. Сошлись на 15m независимо.
