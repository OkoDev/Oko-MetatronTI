"""
recompute_smc_live_window.py — ПЕРЕСЧЁТ SMC-ПРИЗНАКОВ БОЕВЫМ ОКНОМ (ARCH-134, 29.08.2026).

Задача Егора: «пересчитывай конечно! ВСЮ МАТРИЦУ».

Замер чувствительности (`window_sensitivity.py`) показал, что пересчитывать нужно НЕ всё —
и это экономит часы:

    SCALES (две структуры)   0.0% расхождений · 0 зависимых из 20
    WAVES (ноги)             0.0%             · 0 зависимых из 14
    combinator (старая)      4.4%             · 5 зависимых из 125
    SMC-состояние           37.3%             · 35 зависимых из 60   ← только здесь

Причина ровно в природе признака: SCALES и WAVES спрашивают про ТЕКУЩЕЕ событие (последний
слом, текущая нога), а SMC-состояния считают НАКОПЛЕННЫЕ зоны — и чем длиннее история,
тем их больше. На 60k барах «ближайший уровень» почти всегда рядом, в бою такого набора нет.
Именно это обрушило находку EQH ([[eqh_liquidity_short_works_in_2026]]).

Здесь SMC-признаки пересчитываются на каждом баре сделки по ПРЕДЫДУЩИМ `--bars` барам —
ровно то окно, что подаёт боевой runner (`bars: 1000`), — и записываются в parquet
с суффиксом `_lw` (live window), рядом со старыми. Старые не стираются: сравнение
«полная история против боевого окна» само по себе результат.

    python scripts/recompute_smc_live_window.py --bars 1000
"""
from __future__ import annotations

import argparse
import sys
import time
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

from research_harness import load        # noqa: E402

# по умолчанию — обычный прогон; --input/--out позволяют пересчитать ЯДРО тем же окном
PQ = ROOT / "cache" / "matrix_run_15m.parquet"
OUT = ROOT / "cache" / "matrix_run_15m_lw.parquet"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=1000, help="окно, как у боевого runner")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--input", default=None, help="исходный parquet (по умолчанию matrix_run_15m)")
    ap.add_argument("--out", default=None, help="куда писать (по умолчанию ..._lw)")
    a = ap.parse_args()
    src = Path(a.input) if a.input else PQ
    dst = Path(a.out) if a.out else OUT
    print(f"источник: {src.name} → {dst.name}")

    from matrix_full import smc_state_features

    R = pd.read_parquet(src)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna()].copy()
    print("=" * 96)
    print(f"ПЕРЕСЧЁТ SMC БОЕВЫМ ОКНОМ · {len(R)} сделок · окно {a.bars} баров")
    print("=" * 96)

    t0 = time.time()
    parts, skipped = [], 0
    for n_sym, (sym, g) in enumerate(R.groupby("sym"), 1):
        try:
            d = load(sym, a.tf)
        except Exception:                          # noqa: BLE001
            d = None
        if d is None or len(d) < a.bars + 50:
            skipped += len(g)
            continue
        pos = d.index.get_indexer(pd.to_datetime(g._ts, utc=True), method="nearest")
        rows = []
        for i in pos:
            if i < a.bars:
                rows.append(None)
                continue
            w = d.iloc[i - a.bars:i + 1]
            try:
                # признаки на ПОСЛЕДНЕМ баре окна — ровно то, что видит бой
                rows.append(smc_state_features(w, a.tf).iloc[-1])
            except Exception:                      # noqa: BLE001
                rows.append(None)
        idx = [k for k, r in enumerate(rows) if r is not None]
        if not idx:
            skipped += len(g)
            continue
        F = pd.DataFrame([rows[k] for k in idx]).add_suffix("_lw").reset_index(drop=True)
        gg = g.iloc[idx].reset_index(drop=True)
        parts.append(pd.concat([gg, F], axis=1))
        if n_sym % 5 == 0:
            done = sum(len(p) for p in parts)
            print(f"  ... {n_sym} монет · {done} сделок · {time.time()-t0:.0f}с")

    if not parts:
        print("🔴 ничего не пересчитано")
        return 1
    X = pd.concat(parts, ignore_index=True)
    X.to_parquet(dst)
    lw = [c for c in X.columns if c.endswith("_lw")]
    print(f"\nготово за {time.time()-t0:.0f}с · сделок {len(X)} (пропущено {skipped}) · "
          f"пересчитано признаков {len(lw)}")
    print(f"→ {dst}")

    # ── сразу же: насколько версии разошлись ────────────────────────────────
    print("\n" + "=" * 96)
    print("НАСКОЛЬКО ВЕРСИИ РАЗОШЛИСЬ (Жаккар для булевых, корреляция для числовых)")
    print("=" * 96)
    rows = []
    for c in lw:
        base = c[:-3]
        if base not in X.columns:
            continue
        A, B = X[base], X[c]
        v = A.dropna()
        if v.nunique() <= 2:
            a_, b_ = A == 1.0, B == 1.0
            u = (a_ | b_).sum()
            rows.append((base, "булев", (a_ & b_).sum() / u if u else np.nan))
        else:
            rows.append((base, "числовой", A.corr(B)))
    T = pd.DataFrame(rows, columns=["признак", "тип", "совпадение"]).sort_values("совпадение")
    print(T.head(18).to_string(index=False))
    print(f"\n  медианное совпадение: {T['совпадение'].median():.3f}")
    print("  🔑 низкое совпадение = на полной истории мерился ДРУГОЙ признак.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
