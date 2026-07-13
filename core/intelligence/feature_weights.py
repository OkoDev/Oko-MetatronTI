# -*- coding: utf-8 -*-
"""FEATURE-WEIGHTS (09.07, идея Егора «наша система адаптивных весов подойдёт?») —
двухступенчатая система качества входа:

  СТУПЕНЬ 1 (офлайн): scripts/validate_ds_features.py --write-weights — time-split +
    режим-split валидация → БЕЛЫЙ СПИСОК робастных фич → таблица feature_weights.
    Защита от шума: авто-обучение на сотнях фич без валидации = multiple comparisons
    (пример: bear_bos_15m ФЛИПает между половинами — в белый список не попал).
  СТУПЕНЬ 2 (онлайн, этот модуль): вес фичи по формуле адаптивных весов проекта
    (update_signal_weights), но от % net (ЗАКОН №1: мерить %, не R):
        weight = clamp(1.0 + delta_pct * 0.2, 0.5, 2.0)
    Множитель сделки = произведение весов активных validated-фич, кламп [0.4, 2.5].
    WT-фичи режим-зависимы (гипотеза Егора ПОДТВЕРЖДЕНА 09.07: wt_os_1h risk-on −0.33
    vs risk-off −0.84) → вес хранится per-режим ('any' | 'risk_on' | 'risk_off').

SHADOW-фаза: множитель пишется в features_json (ds_feature_mult), на решения НЕ влияет.
После 2 недель форварда и сверки → soft-модификатор strength.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

MULT_MIN, MULT_MAX = 0.4, 2.5      # кламп итогового множителя сделки
_CACHE_TTL = 15 * 60

_cache: dict = {"ts": 0.0, "weights": {}}


def ensure_table(db_path: str) -> None:
    with sqlite3.connect(db_path, timeout=10) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS feature_weights (
            feature TEXT, regime TEXT DEFAULT 'any',
            delta_pct REAL, n INTEGER, weight REAL,
            validated INTEGER DEFAULT 1, updated_at TEXT,
            PRIMARY KEY (feature, regime))""")
        c.commit()


def load_weights(db_path: str) -> dict:
    """{(feature, regime): weight} с кэшем 15м (зовётся на каждой регистрации)."""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["weights"]:
        return _cache["weights"]
    out = {}
    try:
        with sqlite3.connect(db_path, timeout=10) as c:
            for f, r, w in c.execute(
                    "SELECT feature, regime, weight FROM feature_weights WHERE validated=1"):
                out[(f, r)] = float(w)
    except Exception as e:
        logger.debug("[FEAT-W] load: %s", e)
    _cache.update(ts=now, weights=out)
    return out


def flatten_context(snapshot: dict) -> dict:
    """context-фичи снапшота ARCH-118 → плоские бинарные ключи (методология DS-mining)."""
    flat = {}
    ctx = (snapshot or {}).get("context", {})
    for category in ("smc", "trend", "mom", "pivot", "rsi", "wt", "volume"):
        cd = ctx.get(category, {})
        if not isinstance(cd, dict):
            continue
        for k, v in cd.items():
            if isinstance(v, (int, float)) and v == 1:
                flat[f"{category}.{k}"] = 1
            elif category == "pivot" and isinstance(v, str):
                flat[f"{category}.{k}={v}"] = 1
    return flat


def score_snapshot(snapshot: dict, db_path: str,
                   risk_off: Optional[bool] = None) -> tuple[float, list]:
    """Множитель качества входа по validated-фичам. → (mult, [активные фичи])."""
    weights = load_weights(db_path)
    if not weights:
        return 1.0, []
    flat = flatten_context(snapshot)
    regime = "risk_off" if risk_off else ("risk_on" if risk_off is not None else None)
    mult, hits = 1.0, []
    for feat in flat:
        w = weights.get((feat, "any"))
        if regime is not None:
            w = weights.get((feat, regime), w)     # режимный вес приоритетнее
        if w is not None:
            mult *= w
            hits.append(f"{feat}:{w:.2f}")
    return max(MULT_MIN, min(MULT_MAX, mult)), hits
