"""
detector_confirmation_lag.py — ЧЕРЕЗ СКОЛЬКО БАРОВ ДЕТЕКТОР СТАНОВИТСЯ ВИДЕН (29.08.2026).

Повод — собственная ошибка. Находка «не входить 24 ч после завершения импульса» дала
PF 0.04 у запрещённых сделок, что невозможно естественным образом. Разбор: детектор
`detect_elliott_mtf` ставит `t_end` в точке ЭКСТРЕМУМА, но сам импульс становится виден
только после разворота — задержка **6 баров**. Правило с допуском 1 ч (4 бара) поэтому
использовало будущее.

🔴 Общий класс, а не частный случай: у ЛЮБОГО структурного детектора время события
и время, когда о нём МОЖНО УЗНАТЬ, — разные. Свинг подтверждается через `length` баров,
ZigZag — после разворота, импульс Эллиотта — после слома волны 4. Признак «возраст
события» причинен только если допуск БОЛЬШЕ этой задержки.

Ловушка, на которую я попался дважды: проверка усечением с крупным шагом (1500 баров)
задержку НЕ ловит — к моменту следующей проверки событие давно подтверждено. Мерить надо
бар за баром от самого события.

    python scripts/detector_confirmation_lag.py --symbols 3 --events 8
"""
from __future__ import annotations

import argparse
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

from research_harness import load, universe        # noqa: E402


def elliott_events(df: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    from core.smc.smc_engine import detect_elliott_mtf
    out = []
    for im in detect_elliott_mtf(df):
        t = pd.Timestamp(im["waves"][-1][0])
        out.append((t.tz_localize("UTC") if t.tzinfo is None else t, float(im["scale"])))
    return out


def measure(df: pd.DataFrame, events, n_events: int, max_lag: int = 60) -> list[int | None]:
    """Для последних n_events: через сколько баров ПОСЛЕ события оно появляется в разметке."""
    lags: list[int | None] = []
    for t_end, sc in events[-n_events:]:
        i_end = df.index.get_indexer([t_end], method="nearest")[0]
        found = None
        for cut in range(i_end + 1, min(i_end + max_lag, len(df))):
            if any(t == t_end and s == sc for t, s in elliott_events(df.iloc[:cut])):
                found = cut - i_end
                break
        lags.append(found)
        print(f"    scale {sc:<4} бар {i_end:>6} → "
              f"{'виден через ' + str(found) + ' баров' if found else f'НЕ виден за {max_lag}'}")
    return lags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=3)
    ap.add_argument("--events", type=int, default=8)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--bars", type=int, default=9000)
    a = ap.parse_args()

    print("=" * 96)
    print("ЗАДЕРЖКА ПОДТВЕРЖДЕНИЯ ДЕТЕКТОРА (событие → когда о нём можно узнать)")
    print("=" * 96)
    print("🔑 Признак «возраст события» причинен ТОЛЬКО если допуск больше этой задержки.\n")

    all_lags: list[int] = []
    for sym in universe(a.tf, n=a.symbols):
        try:
            d = load(sym, a.tf)
        except Exception:                       # noqa: BLE001
            continue
        if d is None or len(d) < a.bars:
            continue
        d = d.iloc[-a.bars:]
        ev = elliott_events(d)
        if not ev:
            continue
        print(f"  {sym} ({len(d)} баров, событий {len(ev)}):")
        lags = measure(d, ev, a.events)
        all_lags += [x for x in lags if x is not None]

    if not all_lags:
        print("\n🔴 событий не найдено — задержку измерить не на чем")
        return 1
    med, mx = float(np.median(all_lags)), max(all_lags)
    bar_h = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "5m": 1 / 12}.get(a.tf, 0.25)
    print("\n" + "=" * 96)
    print(f"ИТОГ: медиана {med:.0f} баров ({med*bar_h:.2f} ч) · максимум {mx} баров "
          f"({mx*bar_h:.2f} ч) · замеров {len(all_lags)}")
    print(f"🔑 БЕЗОПАСНЫЙ ЛАГ для причинных замеров: {mx} баров ({mx*bar_h:.2f} ч) — "
          "берётся МАКСИМУМ, не медиана.")
    print("   Любой признак вида «событие произошло N назад» с N меньше этого = look-ahead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
