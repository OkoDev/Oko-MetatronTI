# -*- coding: utf-8 -*-
"""r_predictor_leak_audit — квантифицировать data-leak в RPredictor CV (#7 BACKLOG).

Корень (DS-аудит): `cross_val_score(cv=5)` = KFold по НЕ-упорядоченным по времени данным
→ фолды мешают прошлое/будущее = оптимистичная оценка (leak). Честно = TimeSeriesSplit
(train=прошлое, test=будущее). Скрипт НЕ трогает бот — read-only SELECT + офлайн-обучение.

Выводит для каждого target (max_R_possible vs realized r_multiple) и каждой схемы CV:
R² и RMSE. Разрыв KFold-shuffle → TimeSeriesSplit = величина утечки. + наивный baseline
(predict train-mean) для OOS-gate (модель ДОЛЖНА бить baseline на forward-CV).

Запуск: python scripts/r_predictor_leak_audit.py [--db subscriptions.db] [--vst-only]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold, TimeSeriesSplit, cross_val_score

sys.path.insert(0, ".")
from core.ml.r_predictor import RPredictor   # reuse _build_feature_vector (один калькулятор)


def load(db_path: str, vst_only: bool):
    """Хронологически (ORDER BY id) — чтобы TimeSeriesSplit был осмыслен."""
    rp = RPredictor()
    q = """SELECT id, strength, confidence, direction, signal_type, regime,
                  max_R_possible, r_multiple, features_json, execution_mode
           FROM simulated_trades
           WHERE status != 'OPEN' AND max_R_possible IS NOT NULL AND max_R_possible > 0
                 AND r_multiple IS NOT NULL"""
    if vst_only:
        q += " AND execution_mode='VST'"
    q += " ORDER BY id ASC"
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(q).fetchall()
    X, y_mfe, y_real = [], [], []
    for row in rows:
        feat = rp._build_feature_vector(dict(row))
        if feat is not None:
            X.append(feat)
            y_mfe.append(float(row["max_R_possible"]))
            y_real.append(float(row["r_multiple"]))
    return np.array(X, float), np.array(y_mfe, float), np.array(y_real, float)


def _model():
    return GradientBoostingRegressor(n_estimators=200, max_depth=4, learning_rate=0.05,
                                     subsample=0.8, random_state=42)


def baseline_rmse_timeseries(y, n_splits=5):
    """Наивный прогноз = среднее train-фолда. RMSE на forward-фолдах (OOS-gate-порог)."""
    tss = TimeSeriesSplit(n_splits=n_splits)
    errs = []
    for tr, te in tss.split(y):
        pred = y[tr].mean()
        errs.append(np.sqrt(np.mean((y[te] - pred) ** 2)))
    return float(np.mean(errs))


def evaluate(name, X, y):
    print(f"\n── target = {name} (n={len(y)}, mean={y.mean():.3f}, std={y.std():.3f}) ──")
    schemes = {
        "KFold shuffle=True  (МАКС утечка)": KFold(n_splits=5, shuffle=True, random_state=42),
        "KFold shuffle=False (текущий код)": KFold(n_splits=5, shuffle=False),
        "TimeSeriesSplit     (ЧЕСТНЫЙ)":     TimeSeriesSplit(n_splits=5),
    }
    for label, cv in schemes.items():
        r2 = cross_val_score(_model(), X, y, cv=cv, scoring="r2")
        rmse = -cross_val_score(_model(), X, y, cv=cv, scoring="neg_root_mean_squared_error")
        print(f"  {label}:  R²={r2.mean():+.3f}   RMSE={rmse.mean():.3f}")
    base = baseline_rmse_timeseries(y)
    print(f"  naive baseline (TS, predict-mean):  RMSE={base:.3f}  ← модель должна быть НИЖЕ (OOS-gate)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    ap.add_argument("--vst-only", action="store_true")
    a = ap.parse_args()
    X, y_mfe, y_real = load(a.db, a.vst_only)
    print(f"=== R-PREDICTOR LEAK AUDIT === db={a.db} vst_only={a.vst_only}  выборка={len(y_mfe)}")
    if len(y_mfe) < 100:
        print("мало данных"); return
    evaluate("max_R_possible (текущий)", X, y_mfe)
    evaluate("r_multiple (realized, реестр #7)", X, y_real)
    print("\nИтог: разрыв KFold-shuffle → TimeSeriesSplit = величина утечки. "
          "Если TS R²≈0 или RMSE≥baseline — модель НЕ обобщает (OOS-gate должен НЕ активировать).")


if __name__ == "__main__":
    main()
