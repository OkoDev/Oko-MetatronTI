# -*- coding: utf-8 -*-
"""ОТКУДА AUC 0.30 У WT-СПЕЦИАЛИСТА — сигнал или артефакт (Егор 07.10: «что берём дальше? WT?»).

`core/ml/mtf_wt_specialist.py` учится при каждом старте бота на ~7.6 тыс. закрытых сделок и
показывает AUC 0.301 (дашборд Куба). AUC ниже 0.5 = ранжирование ПЕРЕВЁРНУТО. Два прочтения:
  · артефакт — тогда цифра ничего не значит;
  · настоящая инверсия — тогда перевёрнутая модель даёт ~0.70, сильнейший сигнал проекта.

Подозрения по коду (до прогона):
  1. В признаках НЕТ стороны сделки: перепроданность хороша лонгу и плоха шорту — один снимок
     означает противоположное. Тот же класс, что «эдж только у лонга» у SMC (артефакт смеси).
  2. `cross_val_score(cv=5)` без перемешивания, а сделки грузятся БЕЗ ORDER BY (порядок вставки =
     время) → куски проверки идут подряд по периодам с разной долей лонгов/шортов и режимом.

Проверяем по очереди: (a) воспроизводится ли 0.30 · (b) перемешанная проверка · (c) внутри
каждой стороны · (d) признаки, выровненные по стороне · (e) честная проверка «прошлое → будущее»
и ДЕНЬГИ в верхней/нижней пятой части прогноза ([[principle_measure_pct_not_r_LAW]]).
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

from sklearn.ensemble import RandomForestClassifier                  # noqa: E402
from sklearn.metrics import roc_auc_score                             # noqa: E402
from sklearn.model_selection import StratifiedKFold, cross_val_score  # noqa: E402

from core.ml.mtf_wt_specialist import _build_wt_features             # noqa: E402
from core.trading.effective_status import is_win                     # noqa: E402

N_TF_FEATS = 5          # wt1, wt2, zone, wt_cross, atr_trend — на каждый ТФ, все знаковые


def model():
    # ровно параметры боевого fit()
    return RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=5,
                                  random_state=42, n_jobs=-1)


def load():
    cx = sqlite3.connect("subscriptions.db")
    cx.row_factory = sqlite3.Row
    rows = cx.execute("""
        SELECT id, direction, signal_type, profit_pct, status, features_json, tsl_activated,
               R_multiple, substr(replace(created_at,'T',' '),1,19) AS ct
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL') AND features_json IS NOT NULL AND features_json != '{}'
    """).fetchall()                                   # БЕЗ ORDER BY — как в боевом коде
    X, y, side, pnl, ct, src = [], [], [], [], [], []
    for r in rows:
        try:
            snap = json.loads(r["features_json"] or "{}").get("wt_snap")
        except Exception:                            # noqa: BLE001
            continue
        if not snap:
            continue
        fv = _build_wt_features(snap)
        if fv is None:
            continue
        X.append(fv)
        y.append(1 if is_win(r["status"], r["R_multiple"], r["tsl_activated"]) else 0)
        side.append(str(r["direction"] or "").upper())
        pnl.append(float(r["profit_pct"] or 0.0))
        ct.append(r["ct"])
        src.append(r["signal_type"])
    return (np.array(X, float), np.array(y), np.array(side), np.array(pnl),
            pd.to_datetime(pd.Series(ct), errors="coerce").values, np.array(src))


def aligned(X, side):
    """Признаки, выровненные по стороне: для шорта знак всех направленных величин меняется."""
    Xa = X.copy()
    sgn = np.where(side == "SHORT", -1.0, 1.0)[:, None]
    return Xa * sgn                                   # все 5 признаков на ТФ знаковые


def main() -> int:
    X, y, side, pnl, ct, src = load()
    n = len(y)
    print(f"сделок с wt_snap: {n} · доля выигрышей {y.mean()*100:.1f}% · "
          f"LONG {np.mean(side=='LONG')*100:.0f}% / SHORT {np.mean(side=='SHORT')*100:.0f}%")

    # (a) как в бою: 5 кусков подряд, без перемешивания
    a = cross_val_score(model(), X, y, cv=5, scoring="roc_auc")
    print(f"\n(a) как в бою (5 кусков подряд):           AUC {a.mean():.3f}  по кускам {np.round(a, 3).tolist()}")

    # доля лонгов в каждом куске — объясняет ли смесь сторон переворот
    edges = np.linspace(0, n, 6).astype(int)
    mix = [np.mean(side[edges[i]:edges[i + 1]] == "LONG") for i in range(5)]
    print(f"    доля LONG по кускам:                     {np.round(mix, 2).tolist()}")

    # (b) перемешанная стратифицированная проверка
    b = cross_val_score(model(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                        scoring="roc_auc")
    print(f"(b) куски перемешаны:                      AUC {b.mean():.3f}")

    # (c) внутри каждой стороны (куски подряд)
    for s in ("LONG", "SHORT"):
        m = side == s
        if m.sum() > 200 and len(set(y[m])) == 2:
            c = cross_val_score(model(), X[m], y[m], cv=5, scoring="roc_auc")
            print(f"(c) только {s:<5} (подряд):                AUC {c.mean():.3f}  n={m.sum()}")

    # (d) выровненные по стороне признаки, куски подряд
    Xa = aligned(X, side)
    d = cross_val_score(model(), Xa, y, cv=5, scoring="roc_auc")
    print(f"(d) признаки выровнены по стороне (подряд): AUC {d.mean():.3f}")

    # (e) честно: обучение на прошлом (70%), проверка на будущем (30%) — по времени
    order = np.argsort(ct)
    cut = int(n * 0.7)
    tr, te = order[:cut], order[cut:]
    print(f"\n(e) прошлое → будущее: обучение до {pd.Timestamp(ct[tr].max()):%Y-%m-%d}, "
          f"проверка {pd.Timestamp(ct[te].min()):%Y-%m-%d} → {pd.Timestamp(ct[te].max()):%Y-%m-%d} (n={len(te)})")
    for nm, XX in (("как в бою", X), ("выровнено по стороне", Xa)):
        m = model().fit(XX[tr], y[tr])
        p = m.predict_proba(XX[te])[:, 1]
        auc = roc_auc_score(y[te], p)
        q = pd.qcut(p, 5, labels=False, duplicates="drop")
        top, bot = pnl[te][q == q.max()], pnl[te][q == q.min()]
        print(f"    {nm:<22} AUC {auc:.3f} · деньги: верхняя пятая {top.mean():+.3f}% (n={len(top)}) · "
              f"нижняя пятая {bot.mean():+.3f}% (n={len(bot)}) · вся проверка {pnl[te].mean():+.3f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
