# -*- coding: utf-8 -*-
"""ПЕРЕМЕР СЕМЬИ ЛИКВИДНОСТИ НА МЕХАНИКЕ, КОТОРАЯ ВХОДИТ У УРОВНЯ (04.09.2026).

Зачем: на `impulse_fib` семья ликвидности оказалась ПУСТА — `liq_near_*` = 0 из 1572
сделок, `liq_sweep_*` = 2/13 ([[matrix_1h_core_liq_zero_findings]]). Импульсный вход
случается там, где цена НЕ у зоны стопов, поэтому признак и механика не встречаются.
Фейд перепроданности входит ПОСЛЕ пролива — то есть часто сразу после свипа.

Боевая геометрия воспроизведена по `bot/loops/rangefade_loop.py` (закон
law_reproduce_live_config_first):
  · 1h WT < -60 (4h: < -70) → LONG-фейд
  · SL = 3-барный лоу с РОДНОГО ТФ, потолок стопа 12% (кап от 10.08: режет катастрофы)
  · TP = 1R
Гейты сессии / формы свечи / оборота НЕ вшиты, а идут СРЕЗАМИ — иначе не увидеть их вклад.

🔴 Косты вычитаются ЯВНОЙ ставкой: `costs_pct` в БД заполнен у 6% сделок и полагаться
на него нельзя ([[costs_pct_filled_only_6pct]]).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import collect, feature_cols, stat, line, blind_select, blind_select_num  # noqa: E402
from matrix_full import extra_flags, market_context                                             # noqa: E402

WT_THR = {"1h": -60.0, "4h": -70.0, "15m": -70.0}
HOLD = {"1h": 96, "4h": 24, "15m": 384}      # та же КАЛЕНДАРНАЯ длительность
MAX_STOP_PCT = 12.0
SL_BARS = 3


def make_rangefade(tf: str):
    thr = WT_THR.get(tf, -60.0)
    hold = HOLD.get(tf, 96)

    def mechanic(df: pd.DataFrame, _tf: str) -> list[dict]:
        from core.indicators.indicators import calculate_wt
        dd = df.reset_index(drop=True)
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)
        try:
            wt = np.asarray(calculate_wt(dd)["wt1"].values, dtype=float)
        except Exception:                                   # noqa: BLE001
            return []
        if len(wt) != n:
            return []
        out = []
        for b in range(60, n - hold - 1):
            if not (wt[b] < thr):                           # перепроданность
                continue
            if wt[b - 1] < thr:                             # только ПЕРВЫЙ бар входа в зону
                continue
            e = float(C[b])
            sl = float(L[max(0, b - SL_BARS + 1):b + 1].min())
            if not (0 < sl < e):
                continue
            sp = (e - sl) / e * 100.0
            if sp > MAX_STOP_PCT or sp <= 0:
                continue
            tp = e + (e - sl)                               # TP = 1R
            pnl = None
            for q in range(b + 1, min(b + 1 + hold, n)):
                if L[q] <= sl:
                    pnl = (sl - e) / e * 100.0
                    break
                if H[q] >= tp:
                    pnl = (tp - e) / e * 100.0
                    break
            if pnl is None:
                pnl = (float(C[min(b + hold, n - 1)]) - e) / e * 100.0
            out.append({"entry_bar": b, "pnl_pct": pnl, "side": "long",
                        "stop_pct": sp, "wt_at": float(wt[b])})
        return out

    return mechanic


def main() -> int:
    ap = argparse.ArgumentParser(description="Ликвидность на фейде перепроданности")
    ap.add_argument("--tf", default="1h", choices=["15m", "1h", "4h"])
    ap.add_argument("--symbols", type=int, default=0)
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--cost", type=float, default=0.35, help="ставка костов, %% на сделку")
    ap.add_argument("--perm", type=int, default=200)
    args = ap.parse_args()

    print("=" * 104)
    print(f"ФЕЙД ПЕРЕПРОДАННОСТИ + СЕМЬЯ ЛИКВИДНОСТИ · ТФ {args.tf} · WT < {WT_THR[args.tf]} · "
          f"SL={SL_BARS}-барный лоу (кап {MAX_STOP_PCT}%) · TP=1R · косты {args.cost}%")
    print("=" * 104)

    M = market_context()
    R = collect(make_rangefade(args.tf), tf=args.tf,
                n_symbols=0 if args.core else args.symbols, core=args.core,
                cost=args.cost,
                extra=lambda df, tf, sym: extra_flags(df, tf, sym, M=M))
    if R.empty:
        print("🔴 сделок нет")
        return 1

    print(f"\nсобрано: {len(R)} сделок · {R.sym.nunique()} монет · признаков {len(feature_cols(R))}")

    print("\n" + "=" * 104)
    print(f"ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ · {R.sym.nunique()} монет · {len(R)} сделок")
    print("=" * 104)
    print(line(R, "ВСЁ"))
    print("\nГОД:")
    for y in sorted(R.year.unique()):
        print(line(R[R.year == y], str(y)))
    print("\nРАЗМЕР СТОПА:")
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        print(line(R[(R.stop_pct >= lo) & (R.stop_pct < hi)], f"{lo}-{hi}%"))

    # ── ГЛАВНОЕ: встретились ли признак и механика ──────────────────────────
    print("\n" + "=" * 104)
    print("🔑 СЕМЬЯ ЛИКВИДНОСТИ НА ЭТОЙ МЕХАНИКЕ (на impulse_fib она была ПУСТА)")
    print("=" * 104)
    tf = args.tf
    for c in [f"liq_sweep_dn_{tf}", f"liq_sweep_up_{tf}", f"liq_near_dn_{tf}",
              f"liq_near_up_{tf}", f"liq_void_bull_{tf}", f"liq_void_bear_{tf}",
              f"inducement_bull_{tf}", f"inducement_bear_{tf}"]:
        if c not in R.columns:
            print(f"   {c:30s} — нет колонки")
            continue
        v = R[c].astype(float).fillna(0)
        print(line(R[v > 0], f"{c} = TRUE"))
        print(f"      частота на сделках: {100.0 * (v > 0).mean():.1f}%")

    print("\nДИСТАНЦИЯ ДО ЛИКВИДНОСТИ — терцили:")
    for c in [f"liq_dn_dist_pct_{tf}", f"liq_up_dist_pct_{tf}"]:
        if c not in R.columns:
            continue
        v = R[c].astype(float)
        if v.notna().sum() < 60:
            print(f"   {c}: мало значений ({int(v.notna().sum())})")
            continue
        q = v.quantile([0.33, 0.66]).values
        print(line(R[v <= q[0]], f"{c} близко"))
        print(line(R[(v > q[0]) & (v <= q[1])], f"{c} средне"))
        print(line(R[v > q[1]], f"{c} далеко"))

    # ── слепой отбор по ВСЕЙ матрице + перестановочный контроль ─────────────
    print("\n" + "=" * 104)
    print("СЛЕПОЙ ОТБОР ПО ВСЕЙ МАТРИЦЕ (IS→OOS, монеты не пересекаются)")
    print("=" * 104)
    blind_select(R)
    blind_select_num(R, n_perm=args.perm)

    out = ROOT / "cache" / f"rangefade_liq_{args.tf}.parquet"
    try:
        R.to_parquet(out)
        print(f"\nсырые сделки → {out}")
    except Exception as e:                                  # noqa: BLE001
        print(f"\n(parquet не сохранён: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
