"""ARCH-118.3: чистые калькуляторы признаков (без research side-effects).

combinator_core — compute_flags + индикаторы (единый калькулятор, инвариант ARCH-118).
swing_bridge — ETL-обёртки эталонных детекторов core.smc.smc_engine.
Живут в core/ (не tools/) → live-путь (feature_snapshot, observers) импортирует чисто,
без sys.stdout hijack и HISTORY_DIR хардкода combinator_v2.py.
"""
