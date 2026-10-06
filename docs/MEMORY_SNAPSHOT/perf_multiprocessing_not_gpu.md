---
name: perf-multiprocessing-not-gpu
description: "Для CPU-bound бэктестов с независимыми парами (oko_ote_runner_test.py) рычаг — multiprocessing по символам, НЕ GPU. GPU не подходит для sequential branchy python-циклов"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

Егор спросил «а на GPU не переключить?» при долгом прогоне `scripts/oko_ote_runner_test.py` (4h→5m confs≥3, ~70-160s/символ). Ответ: GPU не ускорит — узкое место это последовательные python/numpy циклы с состоянием (курсор дивергенции в `combinator_core._calc_divergence`, nested-loop `detect_fvg_overlap`, бар-за-баром `_confirmations_bt`/раннер-выходы) — branchy serial-логика, зависящая от предыдущей итерации, а не параллельная матричная математика, которую ускоряет GPU. CuPy/Numba-CUDA здесь требовали бы полного переписывания алгоритмов под параллельную форму ради сомнительного выигрыша.

Реальный рычаг — пары символов в `test_pair()` независимы (каждая сама тащит свои OHLCV из sqlite, общего mutable state нет) → добрали `multiprocessing.Pool` по символам (`--workers`, дефолт `min(8, os.cpu_count())`). Каждый воркер открывает СВОЁ sqlite-подключение (conn не пиклится между процессами). Смоук-тест: 15 пар/6 workers — 82s факт vs ~411s serial-эквивалент (сумма individual times) — ускорение совпадает с числом воркеров за вычетом overhead.

**Why:** машина — 16 логических ядер + 2 GPU (GTX1070/1080), но GPU простаивал бы без выгоды на этой задаче; ядра CPU простаивали при serial-раннере.

**How to apply:** для ЛЮБОГО будущего bulk-бэктеста по множеству символов (не только OKO-OTE) — сначала проверить, независимы ли итерации по символу (нет общего state кроме read-only кэша), и если да — `multiprocessing.Pool`/`imap_unordered`, НЕ GPU. GPU рассматривать только если появится векторизуемая матричная операция (напр. батч-инференс ML-модели на множестве символов одновременно), не для текущих indicator-циклов.
