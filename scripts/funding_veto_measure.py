# -*- coding: utf-8 -*-
"""
ARCH-129.1: что фандинг-вето сделало бы с боевым потоком? (01.09.2026)

Повод. Вето в `risk_intelligence` мертво дважды ([[bug_funding_veto_dead_and_units]]):
вход захардкожен `0.0`, а единицы разошлись — порог `max_funding_pct: 0.03`
прокомментирован как «% за 8h», но все три источника (ccxt, `funding_rates`,
матрица `fund_rate8`) отдают ДОЛЮ. В долях порог 0.03 = 3% за 8ч и не срабатывает
никогда: проверено — 0.00% сделок матрицы.

🔴 Перед починкой — ЗАМЕР, а не включение. Ослабление или ужесточение фильтра
требует такого же доказательства, как и любой гейт ([[gate_threshold_frequency_vs_money]]):
вопрос не «сколько отсекает», а «отсекает ли ХУДШЕЕ».

Конструкция вето: LONG блокируется при fund > +порог (платим за лонг),
SHORT блокируется при fund < −порог (платим за шорт).

Запуск: python scripts/funding_veto_measure.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts.research_harness import line, stat  # noqa: E402

MATRIX = Path("cache/matrix_core_15m.parquet")
# Порог из config, приведённый к ДОЛЯМ: 0.03% за 8ч = 0.0003.
LIVE_THRESHOLD_PCT = 0.03
LIVE_THRESHOLD_FRAC = LIVE_THRESHOLD_PCT / 100.0


def veto_mask(df: pd.DataFrame, thr_frac: float) -> pd.Series:
    """True = вето СРАБОТАЛО (сделку бы НЕ открыли)."""
    f = df["fund_rate8"]
    long_block = (df.side == "long") & (f > thr_frac)
    short_block = (df.side == "short") & (f < -thr_frac)
    return (long_block | short_block).fillna(False)


def main() -> int:
    if not MATRIX.exists():
        print(f"🔴 нет {MATRIX}")
        return 1
    df = pd.read_parquet(MATRIX)
    df = df[df.fund_rate8.notna()].copy()

    print("=" * 104)
    print(f"ФАНДИНГ-ВЕТО НА БОЕВОМ ПОТОКЕ · {len(df):,} сделок · {df.sym.nunique()} монет "
          f"· годы {sorted(df.year.unique())}")
    print(f"порог конфига {LIVE_THRESHOLD_PCT}%/8ч = {LIVE_THRESHOLD_FRAC} в долях")
    print("=" * 104)

    print("\nЕДИНИЦЫ — почему вето молчало:")
    print(f"    |fund| > 0.03 (порог как ЧИСЛО, данные в долях): "
          f"{(df.fund_rate8.abs() > 0.03).mean():.2%} сделок")
    print(f"    |fund| > 0.0003 (порог 0.03% приведён к долям):  "
          f"{(df.fund_rate8.abs() > LIVE_THRESHOLD_FRAC).mean():.2%} сделок")

    for side in ("short", "long"):
        d = df[df.side == side]
        base = stat(d)
        if base is None:
            continue
        print(f"\n{'=' * 104}\nСТОРОНА {side.upper()} · n={len(d)}\n{'=' * 104}")
        print(line(d, "БАЗА (вето выключено)"))

        for thr_pct in (0.01, 0.02, 0.03, 0.05, 0.10):
            thr = thr_pct / 100.0
            m = veto_mask(d, thr)
            kept, cut = d[~m], d[m]
            s_k, s_c = stat(kept), stat(cut)
            if s_k is None:
                continue
            cut_share = 100 * len(cut) / len(d)
            verdict = ""
            if s_c is not None:
                # 🔑 Вето полезно ТОЛЬКО если отсечённое хуже базы. Иначе оно режет доход.
                verdict = ("✅ режет ХУДШЕЕ" if s_c["pf"] < base["pf"]
                           else "🔴 режет ЛУЧШЕЕ")
            tag = " ← боевой порог" if abs(thr_pct - LIVE_THRESHOLD_PCT) < 1e-9 else ""
            print(f"\n  порог {thr_pct}%/8ч (отсекает {cut_share:.1f}%){tag}")
            print(line(kept, "    осталось"))
            if s_c is not None:
                print(line(cut, "    ОТСЕЧЕНО") + f"   {verdict}")
            else:
                print(f"    ОТСЕЧЕНО n={len(cut)} — мало для оценки")

        # разрез отсечённого по годам на боевом пороге
        m = veto_mask(d, LIVE_THRESHOLD_FRAC)
        if m.sum() >= 30:
            print(f"\n  ОТСЕЧЁННОЕ на боевом пороге, по годам:")
            for y in sorted(d.year.unique()):
                yd = d[d.year == y]
                print(line(yd[veto_mask(yd, LIVE_THRESHOLD_FRAC)], f"    {y}"))

    print("\n🔑 НЕ проверено: фандинг на баре ФИЛЛА (матрица знает бар сигнала) · "
          "\n   влияние на реальную стоимость удержания (вето — про вход, не про держание) · "
          "\n   связка с дрейф-гейтом и EQH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def blind_threshold_test() -> None:
    """
    🔴 ОБЯЗАТЕЛЬНО: выше перебрано 5 порогов × 2 стороны = 10 клеток на ОДНОЙ выборке.
    Без слепой проверки «лучший порог 0.01% для short» — подгонка, а не находка.

    IS = чётные монеты × ранние годы, OOS = нечётные × поздние. Порог выбирается
    ТОЛЬКО на IS и применяется к OOS тем же ЧИСЛОМ.
    """
    df = pd.read_parquet(MATRIX)
    df = df[df.fund_rate8.notna()].copy()
    print(f"\n{'=' * 104}")
    print("СЛЕПОЙ ТЕСТ ПОРОГА — переносится ли выбор на отложенную выборку")
    print("=" * 104)

    for side in ("short", "long"):
        d = df[df.side == side]
        IS = d[(~d.oos) & (d.year <= 2024)]
        OOS = d[d.oos & (d.year >= 2025)]
        b_is, b_oos = stat(IS), stat(OOS)
        if b_is is None or b_oos is None:
            print(f"\n{side}: мало данных")
            continue
        print(f"\n{side.upper()} · IS n={len(IS)} ({IS.sym.nunique()} монет) · "
              f"OOS n={len(OOS)} ({OOS.sym.nunique()}) · пересечение "
              f"{len(set(IS.sym) & set(OOS.sym))}")
        print(line(IS, "  БАЗА IS"))
        print(line(OOS, "  БАЗА OOS"))

        best, best_pf = None, b_is["pf"]
        for thr_pct in (0.005, 0.01, 0.02, 0.03, 0.05, 0.10):
            kept = IS[~veto_mask(IS, thr_pct / 100.0)]
            s = stat(kept)
            if s and s["pf"] > best_pf:
                best, best_pf = thr_pct, s["pf"]
        if best is None:
            print("  🔴 на IS ни один порог не улучшил базу — вето не нужно")
            continue
        print(f"  выбран на IS: порог {best}%/8ч (PF базы {b_is['pf']:.2f} → {best_pf:.2f})")

        kept_o = OOS[~veto_mask(OOS, best / 100.0)]
        s_o = stat(kept_o)
        if s_o is None:
            print("  OOS: мало данных")
            continue
        ok = s_o["pf"] > b_oos["pf"] and s_o["bt"] > b_oos["bt"]
        print(line(kept_o, f"  OOS с порогом {best}%"))
        print(f"  → перенос {'✅ ПОДТВЕРЖДЁН' if ok else '🔴 НЕ подтверждён'}: "
              f"PF {b_oos['pf']:.2f} → {s_o['pf']:.2f}, "
              f"хрупкость {b_oos['bt']:+.0f} → {s_o['bt']:+.0f}")


if __name__ != "__main__":
    pass
