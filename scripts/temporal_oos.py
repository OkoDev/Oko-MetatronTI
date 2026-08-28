"""
temporal_oos.py — ЧЕСТНЫЙ OOS ПО ВРЕМЕНИ (29.08.2026).

Главное незакрытое подозрение всех находок сессии. Слепой отбор харнесса делит выборку
ПО МОНЕТАМ, и окна времени у обеих половин совпадают целиком (2023-01 → 2026-08). Такой
OOS проверяет перенос между МОНЕТАМИ и ничего не говорит про перенос между ЭПОХАМИ —
а именно эпоха ломала всё в этом проекте не раз ([[impulse_2026_breaks_every_rule]]).

Симптом, который это подсвечивает: у churn, disc и типа волны ОДНА и та же болезнь —
2023 и 2026 против. Это один вопрос, а не три.

Здесь порог и правило выбираются ТОЛЬКО на прошлом, а проверяются ТОЛЬКО на будущем,
которого при выборе не существовало:

    train  2023-01 → 2024-12     (порог/правило фиксируются здесь)
    test   2025-01 → 2026-08     (открывается ОДИН раз)

Проверяются три уже названные находки, а не новый перебор — иначе временной OOS
превратится в очередную нарезку. Плюс перестановочный контроль на той же схеме:
если и шум так «переносится», значит переносится не находка, а разметка.

🔴 Что этот тест НЕ закрывает: база собрана БОЕВЫМ детектором после смены на `extremes`
(28.08). Контрольного прогона на старом детекторе нет — это отдельная задача.

    python scripts/temporal_oos.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def rules(R: pd.DataFrame) -> dict:
    """Находки сессии — НАЗВАННЫЕ заранее, не выкопанные перебором на этих данных."""
    sp = R.leg_speed_atr_15m
    return {
        "churn (≥2 младших слома / 5ч)": R.st5_count20_15m >= 2,
        "disc (откат ноги > 50%)":       R.leg_in_disc_15m == 1.0,
        "FLAT (медленная нога)":         sp <= sp.quantile(1 / 3),
        "churn × disc":                  (R.st5_count20_15m >= 2) & (R.leg_in_disc_15m == 1.0),
        "churn × FLAT":                  (R.st5_count20_15m >= 2) & (sp <= sp.quantile(1 / 3)),
    }


def main() -> int:
    R = pd.read_parquet(PQ)
    t = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[t.notna()].copy()
    t = t[t.notna()]
    R["_train"] = (t < SPLIT).values

    TR, TE = R[R._train], R[~R._train]
    b_tr, b_te = stat(TR), stat(TE)
    gate = R.mkt_drift_slope > 0

    print("=" * 104)
    print("ЧЕСТНЫЙ OOS ПО ВРЕМЕНИ · порог виден только в прошлом, проверка только в будущем")
    print("=" * 104)
    print(f"  train  {t[R._train.values].min().date()} → {t[R._train.values].max().date()}  n={len(TR)}")
    print(f"  test   {t[~R._train.values].min().date()} → {t[~R._train.values].max().date()}  n={len(TE)}")
    print(line(TR, "  БАЗА train"))
    print(line(TE, "  БАЗА test"))
    print("\n🔑 База сама рухнула между эпохами — это и есть тот сдвиг, который")
    print("   разбиение по монетам увидеть НЕ МОГЛО.")

    print("\n" + "=" * 104)
    print("НАХОДКИ: train → test")
    print("=" * 104)
    surv = []
    for name, m in rules(R).items():
        a, b = stat(TR[m[TR.index]]), stat(TE[m[TE.index]])
        if a is None:
            print(f"  {name:<32} train мало"); continue
        if b is None:
            print(f"  {name:<32} train PF {a['pf']:5.2f} → test МАЛО ДАННЫХ (n={int(m[TE.index].sum())})")
            continue
        # порог переноса — ОТНОСИТЕЛЬНО базы своей эпохи, не абсолютный
        lift_tr = a["pf"] / b_tr["pf"] if b_tr["pf"] else np.nan
        lift_te = b["pf"] / b_te["pf"] if b_te["pf"] else np.nan
        ok = lift_te > 1.15 and b["n"] >= 80
        if ok:
            surv.append(name)
        print(f"  {name:<32} train PF {a['pf']:5.2f} (×{lift_tr:.2f} к базе, n={a['n']:<5}) → "
              f"test PF {b['pf']:5.2f} (×{lift_te:.2f}, n={b['n']:<5}) "
              f"безтоп10% {b['bt']:>+7.0f}{'  ✅' if ok else ''}")
    print(f"\nПЕРЕНЕСЛОСЬ ВО ВРЕМЕНИ: {len(surv)} из {len(rules(R))}")

    print("\n── ТО ЖЕ ПОВЕРХ БОЕВОГО ДРЕЙФ-ГЕЙТА ──")
    print(line(TE[gate[TE.index]], "  test · гейт"))
    for name, m in rules(R).items():
        mm = gate[TE.index] & m[TE.index]
        if stat(TE[mm]):
            print(line(TE[mm], f"  test · гейт + {name[:26]}"))

    print("\n🎲 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ на ТОЙ ЖЕ временной схеме (30 перемешиваний):")
    rng = np.random.default_rng(11)
    noise = []
    for _ in range(30):
        pn = rng.permutation(R.pnl.values)
        Rs = R.assign(pnl=pn)
        tr, te = Rs[Rs._train], Rs[~Rs._train]
        bt = stat(te)
        k = 0
        for _, m in rules(R).items():
            s = stat(te[m[te.index]])
            if s is not None and s["n"] >= 80 and bt["pf"] and s["pf"] / bt["pf"] > 1.15:
                k += 1
        noise.append(k)
    noise = np.array(noise)
    p = float((noise >= len(surv)).mean())
    print(f"   ШУМ переносит: медиана {np.median(noise):.1f} · 95-й перцентиль "
          f"{np.percentile(noise, 95):.1f} · максимум {noise.max()}")
    print(f"   наш результат {len(surv)} · P(шум ≥ нашего) = {p:.3f}")
    print("   " + ("🟢 ПЕРЕНОС ОТЛИЧИМ ОТ ШУМА" if p < 0.05 else
                   "🔴 НЕ отличим от шума" if p > 0.15 else "🟡 на границе"))

    print("\n── ГОД ЗА ГОДОМ внутри test (не держится ли всё на одном) ──")
    for name, m in rules(R).items():
        cells = []
        for y in sorted(TE.year.unique()):
            g = TE[(TE.year == y)]
            s = stat(g[m[g.index]])
            cells.append(f"{y} PF {s['pf']:5.2f} (n={s['n']:>3})" if s else f"{y} мало    ")
        print(f"  {name:<32} " + " | ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
