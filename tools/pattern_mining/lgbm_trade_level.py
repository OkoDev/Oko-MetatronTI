"""
DEV-216a-v2: LightGBM TRADE-LEVEL classifier (правильный подход per D-021).

Не на всех 1.68M баров (где WR baseline 40-44%, AUC 0.547), а на TRADE-LEVEL —
строках где сработал один из топ-anchors. Это превращает миллионы шума в
~10K signal-rich trades.

Подход:
1. Для каждого топ-anchor (golden, premium_short, ...) collected trades
2. Features: все 90+ flags В МОМЕНТ entry
3. Target: R > 0 (binary), также MFE как secondary regressor
4. Output: per-anchor classifier, который усиливает entry filter

Output:
  models/lgbm_trade_classifier_<anchor_id>.txt
  data/research/2026-05-20--ph1/lgbm_trade_metrics.json
"""
from __future__ import annotations

import sys
import time
import warnings
import json
from pathlib import Path
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1"

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")

# Те же 5 anchors что в DEV-211
ANCHORS = {
    "L1_golden": {
        "factors": ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"],
        "direction": "LONG",
    },
    "L2_wt_double": {
        "factors": ["wt_os_1d", "bull_fvg_4h", "wt_os_1h"],
        "direction": "LONG",
    },
    "L3_wt_atr": {
        "factors": ["wt_os_1d", "atr_up_4h", "wt_os_1h"],
        "direction": "LONG",
    },
    "S1_bos_premium": {
        "factors": ["atr_cross_down_1d", "bear_bos_1d", "premium_4h"],
        "direction": "SHORT",
    },
    "S3_full_short": {
        "factors": ["bear_bos_1d", "bear_fvg_in_1h", "below_ema50_1h", "premium_4h"],
        "direction": "SHORT",
    },
}

PARAMS = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'num_leaves': 31,            # меньше т.к. samples малы
    'learning_rate': 0.02,
    'feature_fraction': 0.7,
    'bagging_fraction': 0.7,
    'bagging_freq': 3,
    'min_data_in_leaf': 10,      # снижено для маленьких выборок
    'lambda_l1': 0.5,
    'lambda_l2': 0.5,
    'verbose': -1,
    'seed': 42,
}


def collect_anchor_trades(anchor_factors: list, direction: str):
    """Возвращает X, y, ts, sym для всех trades anchor."""
    files = sorted(HISTORY_1H.glob("*.parquet"))

    X_list = []
    y_list = []
    ts_list = []
    sym_list = []
    flag_cols = None

    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res
        if flag_cols is None:
            flag_cols = flags.columns.tolist()

        # Anchor mask
        mask = np.ones(len(flags), dtype=bool)
        for f in anchor_factors:
            if f not in flags.columns:
                mask = mask & False
                break
            mask &= flags[f].values
        if not mask.any():
            continue

        rs = r_long if direction == "LONG" else r_short
        valid = mask & ~np.isnan(rs)
        if not valid.any():
            continue

        idx = np.where(valid)[0]
        flag_arr = flags.values.astype(np.float32)
        for i in idx:
            X_list.append(flag_arr[i])
            y_list.append(1 if rs[i] > 0 else 0)
            ts_list.append(flags.index[i])
            sym_list.append(path.stem)

    if not X_list:
        return None
    return {
        "X": np.array(X_list, dtype=np.float32),
        "y": np.array(y_list, dtype=np.int32),
        "ts": pd.to_datetime(ts_list, utc=True),
        "sym": sym_list,
        "flag_cols": flag_cols,
    }


def train_per_anchor(anchor_id: str, anchor_cfg: dict):
    data = collect_anchor_trades(anchor_cfg["factors"], anchor_cfg["direction"])
    if data is None:
        return None

    X, y, ts, sym, flag_cols = data["X"], data["y"], data["ts"], data["sym"], data["flag_cols"]
    print(f"\n=== {anchor_id} ({anchor_cfg['direction']}) ===")
    print(f"  Total trades: {len(X)} | WR baseline: {y.mean()*100:.1f}%")

    if len(X) < 100:
        print(f"  ❌ Too few trades")
        return None

    train_mask = ts < TRAIN_END
    test_mask = ~train_mask
    print(f"  Train: {train_mask.sum()} | Test: {test_mask.sum()}")

    if train_mask.sum() < 50 or test_mask.sum() < 20:
        print(f"  ❌ Insufficient train/test split")
        return None

    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=flag_cols)
    val_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    model = lgb.train(
        PARAMS,
        train_data,
        num_boost_round=500,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'val'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=30, verbose=False),
            lgb.log_evaluation(period=0),  # quiet
        ]
    )

    y_pred = model.predict(X_test)
    try:
        auc = roc_auc_score(y_test, y_pred)
        ap = average_precision_score(y_test, y_pred)
    except Exception as e:
        print(f"  ❌ Metrics calc error: {e}")
        return None

    print(f"  Test AUC: {auc:.4f} | AP: {ap:.4f} | best_iter: {model.best_iteration}")

    # Top features
    importance = pd.DataFrame({
        "feature": flag_cols,
        "gain": model.feature_importance(importance_type='gain'),
        "split": model.feature_importance(importance_type='split'),
    }).sort_values("gain", ascending=False)
    print(f"  Top-5 features:")
    for _, r in importance.head(5).iterrows():
        if r["gain"] > 0:
            print(f"    {r['feature']:<35} gain={r['gain']:.1f}")

    # Save
    model_path = MODELS_DIR / f"lgbm_trade_classifier_{anchor_id}.txt"
    model.save_model(str(model_path))

    return {
        "anchor_id": anchor_id,
        "direction": anchor_cfg["direction"],
        "n_train": int(train_mask.sum()),
        "n_test": int(test_mask.sum()),
        "wr_baseline_train": float(y_train.mean()),
        "wr_baseline_test": float(y_test.mean()),
        "auc_test": float(auc),
        "ap_test": float(ap),
        "best_iteration": int(model.best_iteration),
        "model_path": str(model_path),
        "top_features": importance.head(10).to_dict(orient="records"),
    }


def main():
    with register_run("lgbm_trade_level", params={"anchors": list(ANCHORS.keys())}) as run:
        results = []
        for anchor_id, cfg in ANCHORS.items():
            res = train_per_anchor(anchor_id, cfg)
            if res:
                results.append(res)
                run.add_output(Path(res["model_path"]))

        metrics_path = OUTPUT_DIR / "lgbm_trade_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        run.add_output(metrics_path)

        print(f"\n\n{'='*70}")
        print(f"SUMMARY")
        print(f"{'='*70}")
        print(f"{'Anchor':<22} {'Dir':<6} {'n_test':>8} {'WR_base':>8} {'AUC':>7}")
        for r in results:
            print(f"{r['anchor_id']:<22} {r['direction']:<6} {r['n_test']:>8} "
                  f"{r['wr_baseline_test']*100:>7.1f}% {r['auc_test']:>7.4f}")


if __name__ == "__main__":
    main()
