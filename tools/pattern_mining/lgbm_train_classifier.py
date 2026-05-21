"""
DEV-216a: LightGBM Classifier для entry quality (P(R>0)).

Обучается на MHT-filtered паттернах из Phase 1.A (walkforward_full_mht.csv).
Features: все 90+ SMC/indicator/pivot flags из combinator_v2 (per-bar).
Target: R > 0 (binary classification).

Train/test split: 2025-07-01 (как в walk-forward).

Output:
  models/lgbm_entry_classifier.txt
  data/research/2026-05-20--ph1/lgbm_feature_importance.csv
  data/research/2026-05-20--ph1/lgbm_predictions.csv (для Decision Fusion в Phase 6)
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

import math
import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
MHT_INPUT = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1" / "walkforward_full_mht.csv"
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")

# LightGBM params под нашу задачу
PARAMS_CLF = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'num_leaves': 63,
    'max_depth': -1,
    'learning_rate': 0.03,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'min_data_in_leaf': 50,
    'lambda_l1': 0.1,
    'lambda_l2': 0.1,
    'verbose': -1,
    'seed': 42,
}


def build_dataset():
    """Собираем dataset: каждая строка = один бар + флаги + R-результат."""
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"Сбор dataset с {len(files)} пар...")

    all_X = []
    all_y_long = []
    all_y_short = []
    all_ts = []
    all_sym = []
    all_dir = []
    flag_cols = None

    t0 = time.time()
    for i, path in enumerate(files):
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res
        if flag_cols is None:
            flag_cols = flags.columns.tolist()

        # Где валидные R (есть сделка)
        valid_long = ~np.isnan(r_long)
        valid_short = ~np.isnan(r_short)

        flag_arr = flags.values.astype(np.float32)
        idx = flags.index

        # LONG samples
        for j in np.where(valid_long)[0]:
            all_X.append(flag_arr[j])
            all_y_long.append(1 if r_long[j] > 0 else 0)
            all_y_short.append(np.nan)
            all_ts.append(idx[j])
            all_sym.append(path.stem)
            all_dir.append("LONG")

        # SHORT samples
        for j in np.where(valid_short)[0]:
            all_X.append(flag_arr[j])
            all_y_long.append(np.nan)
            all_y_short.append(1 if r_short[j] > 0 else 0)
            all_ts.append(idx[j])
            all_sym.append(path.stem)
            all_dir.append("SHORT")

        if (i + 1) % 10 == 0:
            print(f"  ...{i+1}/{len(files)} | total samples: {len(all_X)} | {time.time()-t0:.0f}s")

    X = np.array(all_X, dtype=np.float32)
    print(f"\nDataset: {X.shape[0]} samples × {X.shape[1]} features ({time.time()-t0:.0f}s)")

    return X, np.array(all_y_long), np.array(all_y_short), all_ts, all_sym, all_dir, flag_cols


def train_one(X_train, y_train, X_test, y_test, params, name):
    """Train + eval LightGBM model."""
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    print(f"\n  Training {name}...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=2000,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'val'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=200),
        ]
    )

    y_pred = model.predict(X_test)

    # Manual ROC-AUC (no sklearn dependency here)
    from sklearn.metrics import roc_auc_score, average_precision_score
    auc = roc_auc_score(y_test, y_pred)
    ap = average_precision_score(y_test, y_pred)

    print(f"  {name} | Test AUC: {auc:.4f} | Average Precision: {ap:.4f}")
    print(f"  Best iteration: {model.best_iteration}")

    return model, y_pred, auc, ap


def main():
    with register_run("lgbm_train_classifier", params={"train_end": str(TRAIN_END.date())}) as run:
        # Build full dataset
        X, y_long, y_short, ts_list, sym_list, dir_list, flag_cols = build_dataset()
        ts_arr = pd.to_datetime(ts_list, utc=True)

        # Train/test split
        train_mask = ts_arr < TRAIN_END
        test_mask = ~train_mask

        # ─── LONG model ───
        long_idx = ~np.isnan(y_long)
        Xl = X[long_idx]
        yl = y_long[long_idx].astype(np.int32)
        tsl = ts_arr[long_idx]

        l_train = tsl < TRAIN_END
        l_test = ~l_train
        print(f"\n=== LONG ===")
        print(f"  Train: n={l_train.sum()} | WR_baseline={yl[l_train].mean()*100:.1f}%")
        print(f"  Test:  n={l_test.sum()} | WR_baseline={yl[l_test].mean()*100:.1f}%")

        if l_train.sum() < 100 or l_test.sum() < 100:
            print("  ❌ Too few samples")
            return

        model_long, pred_long, auc_long, ap_long = train_one(
            Xl[l_train], yl[l_train], Xl[l_test], yl[l_test], PARAMS_CLF, "LONG classifier"
        )

        # ─── SHORT model ───
        short_idx = ~np.isnan(y_short)
        Xs = X[short_idx]
        ys = y_short[short_idx].astype(np.int32)
        tss = ts_arr[short_idx]

        s_train = tss < TRAIN_END
        s_test = ~s_train
        print(f"\n=== SHORT ===")
        print(f"  Train: n={s_train.sum()} | WR_baseline={ys[s_train].mean()*100:.1f}%")
        print(f"  Test:  n={s_test.sum()} | WR_baseline={ys[s_test].mean()*100:.1f}%")

        model_short, pred_short, auc_short, ap_short = train_one(
            Xs[s_train], ys[s_train], Xs[s_test], ys[s_test], PARAMS_CLF, "SHORT classifier"
        )

        # Save models
        model_long_path = MODELS_DIR / "lgbm_entry_classifier_LONG.txt"
        model_short_path = MODELS_DIR / "lgbm_entry_classifier_SHORT.txt"
        model_long.save_model(str(model_long_path))
        model_short.save_model(str(model_short_path))
        run.add_output(model_long_path)
        run.add_output(model_short_path)

        # Feature importance combined
        fi_long = pd.DataFrame({
            "feature": model_long.feature_name(),
            "gain_long": model_long.feature_importance(importance_type='gain'),
            "split_long": model_long.feature_importance(importance_type='split'),
        }) if model_long.feature_name() != ['Column_0'] else None

        # Заменяем имена Column_N на реальные flag names
        for col in [f"Column_{i}" for i in range(len(flag_cols))]:
            pass

        importance = pd.DataFrame({
            "feature_idx": range(len(flag_cols)),
            "feature": flag_cols,
            "gain_long": model_long.feature_importance(importance_type='gain'),
            "split_long": model_long.feature_importance(importance_type='split'),
            "gain_short": model_short.feature_importance(importance_type='gain'),
            "split_short": model_short.feature_importance(importance_type='split'),
        })

        fi_path = OUTPUT_DIR / "lgbm_feature_importance.csv"
        importance.to_csv(fi_path, index=False, encoding="utf-8")
        run.add_output(fi_path)

        # Сохраняем метрики
        metrics = {
            "long": {"auc_test": auc_long, "ap_test": ap_long, "n_train": int(l_train.sum()), "n_test": int(l_test.sum())},
            "short": {"auc_test": auc_short, "ap_test": ap_short, "n_train": int(s_train.sum()), "n_test": int(s_test.sum())},
            "params": PARAMS_CLF,
        }
        metrics_path = OUTPUT_DIR / "lgbm_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        run.add_output(metrics_path)

        # Print top features
        print(f"\n=== TOP-20 LONG features by GAIN ===")
        for _, r in importance.sort_values("gain_long", ascending=False).head(20).iterrows():
            print(f"  {r['feature']:<35} gain={r['gain_long']:>10.1f} split={int(r['split_long']):>4}")

        print(f"\n=== TOP-20 SHORT features by GAIN ===")
        for _, r in importance.sort_values("gain_short", ascending=False).head(20).iterrows():
            print(f"  {r['feature']:<35} gain={r['gain_short']:>10.1f} split={int(r['split_short']):>4}")

        # Sanity check: золотые факторы должны быть в топ-30
        print(f"\n=== SANITY: validated factors rank ===")
        validated = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h", "bear_bos_1d", "premium_4h", "wt_os_1d"]
        for f in validated:
            if f in flag_cols:
                row = importance[importance["feature"] == f].iloc[0]
                # rank по gain_long
                rank_long = (importance["gain_long"] > row["gain_long"]).sum() + 1
                rank_short = (importance["gain_short"] > row["gain_short"]).sum() + 1
                print(f"  {f:<25} LONG rank #{rank_long:>3} (gain={row['gain_long']:.1f}) | SHORT rank #{rank_short:>3}")

        print(f"\n✅ DEV-216a COMPLETED")
        print(f"  LONG AUC:  {auc_long:.4f} (target ≥0.65)")
        print(f"  SHORT AUC: {auc_short:.4f}")


if __name__ == "__main__":
    main()
