#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Пересчёт SMC-снимков для закрытых сделок текущим детектором (ускорение сферы SMC).

🔴 Задача. Сфера SMC молчит: `fitted=False, n=0`. Это не поломка — 02.09 ввели
версионирование схемы (ARCH-137.6: «училась на СМЕСИ НЕСОВМЕСТИМЫХ ДАННЫХ»),
и 7593 старых снимка отброшены: их считал ПРЕЖНИЙ детектор, который совпадал
с эталоном лишь в 16% событий. Ждать 50 свежих сделок при темпе 1.4/сут — три недели.

Решение: снимки можно не ждать, а ПЕРЕСЧИТАТЬ. Сделки закрыты, цены известны,
история свечей есть — считаем признаки тем же кодом, что работает в бою
(`_build_smc_snap_from_df`), и получаем однородную выборку схемы v3 сразу.

🔴 ПРИЧИННОСТЬ. Бары берутся через `market_store.closed_bars(..., now=вход)` —
функция отдаёт только бары, ЗАКРЫТЫЕ до указанного момента. Это тот же приём,
которым меряются реплеи; класс ошибок look-ahead у нас записан отдельно, и
повторять его здесь нельзя: модель, обученная на будущем, покажет красивый AUC
и проиграет в бою.

Запуск:
    python scripts/smc_backfill_snaps.py --limit 3000          # пересчитать
    python scripts/smc_backfill_snaps.py --train               # обучить из пересчитанного
    python scripts/smc_backfill_snaps.py --limit 3000 --train  # то и другое
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "subscriptions.db"
OUT = ROOT / "oko_feed" / "smc_backfill.db"

# 🔴🔴 ОКНА = БОЕВЫЕ, БАЙТ В БАЙТ. Это не стилистика.
# 05.10 первая версия считала 4h=200 · 1h=200 · 15m=200, а бой считает
# `trading_intelligence.py:2151-2153` (15m/1h) и `:2208` (1d):
#       15m=100 · 1h=100 · 4h=60 · 1d=60
# Детекторы ЧУВСТВИТЕЛЬНЫ К ДЛИНЕ РЯДА, и расхождение било прямо по признакам:
#   4h: ote_zone 15% против боевых 5% (×3) · brk_internal 68% против 100%
#   1h: ob_bull 85% против 77% · fvg_dist_atr пропущен 0% против 5%
# Причина у структуры физическая: `core/structure/pivots.py:31` ищет опорные точки
# только среди баров [0 … len−window]. При window=50 и 60 барах это бары 0–9,
# то есть СТАРШИЙ слой в бою почти недоступен — и модель, обученная на 200 барах,
# в бою получает другой признак под тем же именем.
# Это train/serve skew, которого `SNAP_SCHEMA_VERSION` НЕ ловит: схема формально
# та же v3. Закон [[law_reproduce_live_config_first]] — сначала воспроизвести бой.
TFS = (("1d", 60), ("4h", 60), ("1h", 100), ("15m", 100))
# старая широкая раскладка — только для сравнения «широкие против боевых»
TFS_WIDE = (("1d", 60), ("4h", 200), ("1h", 200), ("15m", 200))


def _ddl(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS smc_samples (
        trade_id   INTEGER PRIMARY KEY,
        symbol     TEXT,
        created_at TEXT,
        status     TEXT,
        y          INTEGER,
        snap_json  TEXT,
        tfs_ok     INTEGER
    )""")
    con.commit()


def _trades(limit: int, since: str, until: str = "2099-01-01") -> list:
    """Окно сделок. `until` нужен, чтобы брать МЕСЯЦ, а не только последние по id:
    в БД 57 779 закрытых сделок с марта 2026, и без границы сверху выборка всегда
    садится на свежий хвост — то есть на один режим рынка."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, symbol, created_at, status, R_multiple, tsl_activated, entry_price "
            "FROM simulated_trades "
            "WHERE status IN ('TP','SL','TSL','EXPIRED') "
            "  AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?) "
            "ORDER BY id DESC LIMIT ?", (since, until, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def backfill(limit: int, since: str, until: str = "2099-01-01",
             tfs: tuple = TFS) -> int:
    import pandas as pd
    from core.infra import market_store as ms
    from core.ml.mtf_smc_specialist import _build_smc_snap_from_df
    from core.trading.effective_status import is_win

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(OUT)
    _ddl(out)
    done = {r[0] for r in out.execute("SELECT trade_id FROM smc_samples")}

    rows = _trades(limit, since, until)
    todo = [r for r in rows if r["id"] not in done]
    print(f"сделок в окне: {len(rows)} · уже пересчитано: {len(rows) - len(todo)} · к работе: {len(todo)}")

    ok = skipped = 0
    t0 = time.time()
    for i, tr in enumerate(todo, 1):
        try:
            # 🔴 Индекс в хранилище tz-aware (UTC): naive-метка даёт
            # «Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp».
            now = pd.Timestamp(str(tr["created_at"]).replace("Z", "+00:00"))
            if now.tzinfo is None:
                now = now.tz_localize("UTC")
            price = float(tr.get("entry_price") or 0) or None
            snap, got = {}, 0
            for tf, n in tfs:
                try:
                    df = ms.closed_bars(tr["symbol"], tf, n, now=now)
                except Exception:
                    continue
                if df is None or len(df) < 30:
                    continue
                px = price or float(df["close"].iloc[-1])
                snap[tf] = _build_smc_snap_from_df(df, px)
                got += 1
            if got < 2:                      # меньше двух ТФ — образец бесполезен
                skipped += 1
                continue
            y = 1 if is_win(tr["status"], tr.get("R_multiple"), tr.get("tsl_activated")) else 0
            out.execute("INSERT OR REPLACE INTO smc_samples VALUES (?,?,?,?,?,?,?)",
                        (tr["id"], tr["symbol"], str(tr["created_at"]), tr["status"],
                         y, json.dumps(snap, ensure_ascii=False), got))
            ok += 1
            if ok % 100 == 0:
                out.commit()
                sp = ok / max(0.1, time.time() - t0)
                print(f"  {i}/{len(todo)} · готово {ok} · пропущено {skipped} · {sp:.1f}/с")
        except KeyboardInterrupt:
            break
        except Exception as e:                       # noqa: BLE001
            skipped += 1
            if skipped <= 3:
                print(f"  сделка {tr['id']}: {type(e).__name__}: {str(e)[:70]}")
    out.commit()
    total = out.execute("SELECT COUNT(*) FROM smc_samples").fetchone()[0]
    out.close()
    print(f"\nпересчитано за прогон: {ok} · пропущено: {skipped} · всего в базе: {total}")
    return total


def train(sides: tuple = ("LONG", "SHORT")) -> int:
    """Обучение по стороне.

    🔴 ТРИ РЕДАКЦИИ ВЫВОДА — хроника, чтобы не переоткрывать по кругу.

    1) авг–окт, 2328 образцов, широкие окна: LONG +0.083 · SHORT +0.003
       → «эдж только у лонга». Оказалось артефактом двухмесячного окна.
    2) март–окт, 9278, широкие окна (200 баров):
          блок НЕДЕЛЯ: LONG +0.023 · SHORT +0.032
          блок МЕСЯЦ:  LONG +0.037 · SHORT −0.002
       → схемы не согласны, шорт выглядит мёртвым при строгом блоке.
    3) апр–окт, 7785, **БОЕВЫЕ окна** (60–100 баров, как в бою):
          блок НЕДЕЛЯ: LONG +0.033 · SHORT **+0.052** · обе +0.041
          блок МЕСЯЦ:  LONG +0.029 · SHORT **+0.020**
       → обе схемы СОГЛАСНЫ по знаку на обеих сторонах, шорт не хуже лонга.

    Редакция 2 была испорчена train/serve skew: снимки считались на 200 барах,
    а бой считает на 60–100 ([[train_serve_skew_window_length]]). Skew не завышал,
    а ЗАНИЖАЛ и путал знак — на правильных окнах сигнал чище.

    Поэтому по умолчанию обе стороны. `--sides LONG` остаётся точкой контроля.

    🔴 Также: CV здесь группированный по неделям, а НЕ `cv=5`. Прежний `cv=5` по
    отсортированной по времени выборке завышал число (0.566 на случайных фолдах)
    за счёт соседства сделок: 1164 из 2328 лежат в одной шестидневке.
    """
    from core.ml.mtf_smc_specialist import (_build_smc_features, _MODEL_FILE,
                                            SNAP_SCHEMA_VERSION)
    try:
        import joblib
        import numpy as np
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_selection import SelectKBest, f_classif
        from sklearn.model_selection import GroupKFold, cross_val_score
    except ImportError as e:
        print("sklearn/joblib недоступны:", e)
        return 1

    con = sqlite3.connect(f"file:{OUT}?mode=ro", uri=True)
    rows = con.execute("SELECT trade_id, snap_json, y, created_at FROM smc_samples").fetchall()
    con.close()
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    side_of = dict(db.execute("SELECT id, direction FROM simulated_trades").fetchall())
    db.close()

    want = {s.upper() for s in sides}
    X, y, ts = [], [], []
    for trade_id, snap_json, label, created in rows:
        if str(side_of.get(trade_id, "")).upper() not in want:
            continue
        fv = _build_smc_features(json.loads(snap_json))
        if fv is not None:
            X.append(fv)
            y.append(label)
            ts.append(created)
    print(f"сторона: {'+'.join(sorted(want))} · образцов: {len(X)} · "
          f"побед: {sum(y)} ({sum(y) / max(1, len(y)) * 100:.1f}%)")
    if len(X) < 200 or len(set(y)) < 2:
        print("мало данных или один класс — обучение не имеет смысла")
        return 1

    Xa, ya = np.array(X), np.array(y)
    weeks = pd.to_datetime(pd.Series(ts), format="mixed", utc=True) \
              .dt.to_period("W").astype(str).values
    k = max(4, min(len(Xa) // 20, Xa.shape[1]))
    sel = SelectKBest(f_classif, k=k).fit(Xa, ya)
    idx = list(np.where(sel.get_support())[0])
    Xs = Xa[:, idx]

    model = RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=5,
                                   class_weight="balanced", random_state=42, n_jobs=-1)
    cv = GroupKFold(n_splits=min(5, len(set(weeks))))
    auc = cross_val_score(model, Xs, ya, cv=cv, groups=weeks, scoring="roc_auc").mean()
    # 🔴 Порог — не 0.5, а ПЕРЕМЕШАННАЯ метка на той же схеме фолдов: GroupKFold
    # по неразмеченным группам даёт систематический сдвиг (у лонга контроль 0.468).
    rng = np.random.default_rng(42)
    ctrl = [cross_val_score(model, Xs, rng.permutation(ya), cv=cv, groups=weeks,
                            scoring="roc_auc").mean() for _ in range(5)]
    model.fit(Xs, ya)
    print(f"признаков отобрано: {k} · недель в выборке: {len(set(weeks))}")
    print(f"AUC (блок = неделя) = {auc:.3f} · контроль (метка перемешана) = "
          f"{np.mean(ctrl):.3f} ± {np.std(ctrl):.3f} · Δ = {auc - np.mean(ctrl):+.3f}")
    print("  (прошлые замеры: смесь версий 0.379 · однородный месяц 0.551 · старая сфера 4 — 0.180)")
    if auc - np.mean(ctrl) < 0.02:
        print("🔴 Δ над контролем меньше 0.02 — модель НЕ сохранена, говорить ей не о чем")
        return 1

    # 🔴 Квантили p_win на обучающей выборке — чтобы порог можно было задавать
    # ОТНОСИТЕЛЬНО («верхние 10% своих предсказаний»), а не абсолютным числом.
    # Абсолютный 0.65 из конфига недостижим: диапазон модели [0.397, 0.537].
    _p = model.predict_proba(Xs)[:, 1]
    p_q = [float(x) for x in np.quantile(_p, np.linspace(0, 1, 101))]
    print(f"p_win на обучении: min {_p.min():.3f} · медиана {np.median(_p):.3f} · "
          f"max {_p.max():.3f}  (порог конфига 0.65 "
          f"{'ДОСТИЖИМ' if _p.max() >= 0.65 else '🔴 НЕДОСТИЖИМ'})")

    path = ROOT / _MODEL_FILE
    joblib.dump({"model": model, "feat_idx": idx, "cv_auc": float(auc),
                 "ctrl_auc": float(np.mean(ctrl)), "n_samples": int(len(Xs)),
                 "source": f"backfill_v{SNAP_SCHEMA_VERSION}", "sides": sorted(want),
                 "p_quantiles": p_q}, path)
    print(f"модель сохранена: {path.name} · говорить разрешено только: {sorted(want)}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="сколько сделок пересчитать")
    ap.add_argument("--since", default="2026-07-01", help="с какой даты брать сделки")
    ap.add_argument("--until", default="2099-01-01", help="до какой даты (не включая)")
    ap.add_argument("--train", action="store_true", help="обучить модель из пересчитанного")
    ap.add_argument("--sides", default="LONG",
                    help="стороны через запятую; по умолчанию обе (на боевых окнах "
                         "шорт не хуже лонга: Δ +0.052 против +0.033 при блоке «неделя»)")
    ap.add_argument("--wide", action="store_true",
                    help="широкие окна 200 баров ВМЕСТО боевых — только для сравнения, "
                         "обучать на этом нельзя (train/serve skew)")
    a = ap.parse_args()
    if a.limit:
        tfs = TFS_WIDE if a.wide else TFS
        print("окна: " + " · ".join(f"{t}={n}" for t, n in tfs)
              + ("   🔴 ШИРОКИЕ, не боевые" if a.wide else "   (боевые)"))
        backfill(a.limit, a.since, a.until, tfs)
    if a.train:
        sys.exit(train(tuple(s.strip() for s in a.sides.split(",") if s.strip())))
