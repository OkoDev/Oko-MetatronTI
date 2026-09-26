"""
smc_confirmation_lags.py — ЗАДЕРЖКА ПОДТВЕРЖДЕНИЯ ВСЕХ SMC-ДЕТЕКТОРОВ (29.08.2026).

Продолжение `detector_confirmation_lag.py`, где та же проверка была сделана только для
`detect_elliott_mtf` (6 баров). Повод общий: находка «не входить 24 ч после импульса» дала
PF 0.04 — невозможное число — потому что признак «возраст события» мерил от ЭКСТРЕМУМА,
а событие становилось видно на 1.5 ч позже. Один детектор проверили, остальные — нет.

🔴 Класс ошибки, а не частный случай: у структурного детектора время СОБЫТИЯ и время,
когда о нём МОЖНО УЗНАТЬ, — разные величины. Свинг LuxAlgo помечается на баре экстремума,
но выпадает из `confirmed_swings` только через `length` баров. Пивот EQH/EQL требует
`eq_len` баров справа. Sponsored Candle видна сразу, но её флаги (BOS/FVG/confirmed)
досчитываются по окну `confirm_bars` ВПЕРЁД. Любой признак «событие произошло N баров
назад» причинен, только если N больше этой задержки.

МЕТОД (тот же, «усечение ряда бар за баром»): прогнать детектор на полном ряду, взять
последние события, для каждого обрезать `df.iloc[:cut]` начиная с бара события и дальше
по одному бару — на каком обрезании детектор начинает видеть ЭТО ЖЕ событие. Сопоставление
по ключу события (время + цены + тип), НЕ по порядковому номеру в списке.

🔴 Шкала: задержка = сколько баров должно ЗАКРЫТЬСЯ ПОСЛЕ бара события. 0 = видно сразу
на закрытии самого бара события. В `detector_confirmation_lag.py` печаталось `cut - i_end`,
что на 1 больше: его «6 баров» по этой шкале = 5. Эллиотт включён контрольной строкой —
если он не даёт 5, сломан замер, а не детекторы.

Ловушка, на которую ловились дважды: усечение крупным шагом задержку НЕ ловит — к моменту
следующей проверки событие давно подтверждено. Только бар за баром.

    python scripts/smc_confirmation_lags.py --symbols 3 --events 10
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
from core.smc.smc_engine import (                  # noqa: E402
    classify_structure, detect_elliott_mtf, detect_equal_levels, detect_fvg,
    detect_order_blocks, detect_sponsored_candle, detect_structure_breaks,
)

R = 12   # округление цен в ключе события (float из одного и того же ряда совпадает точно)


# ────────────────────────── детекторы → [(время события, ключ)] ──────────────────────────
# Ключ НЕ включает поля, которые по построению смотрят в будущее (mitigated_idx, is_breaker):
# иначе меряли бы не задержку подтверждения, а срок жизни зоны.

def ev_breaks(d: pd.DataFrame) -> list[tuple]:
    return [(b.ts, ("BRK", b.ts, round(b.price, R), b.kind, b.direction, b.has_volume))
            for b in detect_structure_breaks(d, 50)]


def ev_order_blocks(d: pd.DataFrame) -> list[tuple]:
    obs = detect_order_blocks(d, detect_structure_breaks(d, 50))
    return [(d.index[o.break_idx],
             ("OB", d.index[o.left_idx], d.index[o.break_idx], o.kind,
              round(o.top, R), round(o.bottom, R)))
            for o in obs]


def ev_equal_levels(d: pd.DataFrame) -> list[tuple]:
    # событие «пара равных уровней» становится фактом на ВТОРОМ пивоте → время = ts2
    return [(ts2, ("EQ", ts1, round(p1, R), ts2, round(p2, R), lab))
            for ts1, p1, ts2, p2, lab in detect_equal_levels(d)]


def ev_sponsored(d: pd.DataFrame) -> list[tuple]:
    return [(s.ts, ("SC", s.ts, s.direction, round(s.top, R), round(s.bottom, R)))
            for s in detect_sponsored_candle(d)]


def ev_sponsored_flags(d: pd.DataFrame) -> list[tuple]:
    # та же свеча, но ключ включает флаги подтверждения — они досчитываются по окну вперёд
    return [(s.ts, ("SCF", s.ts, s.direction,
                    s.broke_structure, s.has_imbalance, s.confirmed))
            for s in detect_sponsored_candle(d)]


def ev_fvg(d: pd.DataFrame) -> list[tuple]:
    # detect_fvg отдаёт TIMESTAMPS: (ts_left, top, bottom, kind, ts_i, mitigated|None)
    return [(ts_i, ("FVG", ts_left, round(top, R), round(bot, R), kind, ts_i))
            for ts_left, top, bot, kind, ts_i, _mit in detect_fvg(d)]


def ev_classify(d: pd.DataFrame) -> list[tuple]:
    return [(ts, ("CLS", ts, round(p, R), lab)) for ts, p, lab in classify_structure(d, 50)]


def ev_elliott(d: pd.DataFrame) -> list[tuple]:
    out = []
    for im in detect_elliott_mtf(d):
        t = pd.Timestamp(im["waves"][-1][0])
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        out.append((t, ("ELL", t, float(im["scale"]))))
    return out


@dataclass(frozen=True)
class Spec:
    name: str
    run: Callable[[pd.DataFrame], list[tuple]]
    anchor: str            # что считаем «баром события»
    max_lag: int = 80
    settle: bool = False   # True → мерить не появление, а момент, когда поля перестают меняться


SPECS: list[Spec] = [
    Spec("detect_structure_breaks(50)", ev_breaks, "бар пробоя (.idx)"),
    Spec("detect_order_blocks", ev_order_blocks, "бар слома (.break_idx)"),
    Spec("detect_equal_levels", ev_equal_levels, "второй пивот пары (ts2)"),
    Spec("detect_sponsored_candle", ev_sponsored, "бар свечи (.idx)"),
    Spec("  └ SC: флаги BOS/FVG/confirmed", ev_sponsored_flags, "бар свечи (.idx)",
         max_lag=20, settle=True),
    Spec("detect_fvg", ev_fvg, "третья свеча гэпа (ts_i)"),
    Spec("classify_structure(50)", ev_classify, "бар экстремума свинга"),
    Spec("detect_elliott_mtf [контроль]", ev_elliott, "конец импульса (t_end)"),
]


# ─────────────────────────────────── замер ───────────────────────────────────

def _keys(spec: Spec, d: pd.DataFrame) -> set:
    return {k for _, k in spec.run(d)}


def measure(df: pd.DataFrame, spec: Spec, n_events: int, stable: int) -> list[int | None]:
    """Задержка в барах ПОСЛЕ бара события. 0 = видно на закрытии самого бара события."""
    pos = {ts: i for i, ts in enumerate(df.index)}
    need = spec.max_lag + stable + 2
    usable = [(pos[t], k) for t, k in spec.run(df) if t in pos and pos[t] + need <= len(df)]
    if not usable:
        return []

    lags: list[int | None] = []
    for i_ev, key in usable[-n_events:]:
        lag: int | None = None
        if spec.settle:
            # поля события меняются, пока окно подтверждения не заполнится: берём ПОСЛЕДНИЙ
            # бар, на котором ключ ещё отличался от финального (иначе «не изменилось ни разу»
            # у событий с флагами False читалось бы как нулевая задержка)
            last_diff = -1
            for cut in range(i_ev + 1, i_ev + 2 + spec.max_lag):
                if key not in _keys(spec, df.iloc[:cut]):
                    last_diff = cut - i_ev - 1
            lag = last_diff + 1
        else:
            for cut in range(i_ev + 1, i_ev + 2 + spec.max_lag):
                if key not in _keys(spec, df.iloc[:cut]):
                    continue
                # устойчивость: событие не должно исчезнуть на следующих барах (порог FVG
                # считается по всему ряду, поэтому пограничный гэп может «мигать»)
                if all(key in _keys(spec, df.iloc[:c]) for c in range(cut + 1, cut + 1 + stable)):
                    lag = cut - i_ev - 1
                    break
        lags.append(lag)
    return lags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=3)
    ap.add_argument("--events", type=int, default=10)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--bars", type=int, default=9000)
    ap.add_argument("--stable", type=int, default=10, help="баров проверки, что событие не исчезло")
    ap.add_argument("--only", default="", help="подстрока имени детектора")
    a = ap.parse_args()

    bar_h = {"1m": 1 / 60, "3m": 0.05, "5m": 1 / 12, "15m": 0.25,
             "1h": 1.0, "4h": 4.0, "1d": 24.0}.get(a.tf, 0.25)
    specs = [s for s in SPECS if a.only.lower() in s.name.lower()]

    dfs: list[tuple[str, pd.DataFrame]] = []
    for sym in universe(a.tf, n=a.symbols):
        try:
            d = load(sym, a.tf)
        except Exception:                       # noqa: BLE001
            continue
        if d is None or len(d) < a.bars:
            continue
        dfs.append((sym, d.iloc[-a.bars:]))
    if not dfs:
        print("🔴 нет символов с достаточной историей — замер невозможен")
        return 1

    print("=" * 100)
    print(f"ЗАДЕРЖКА ПОДТВЕРЖДЕНИЯ SMC-ДЕТЕКТОРОВ · {a.tf} · {a.bars} баров · "
          f"{len(dfs)} символов · {a.events} событий на детектор")
    print("=" * 100)
    print("Шкала: сколько баров должно ЗАКРЫТЬСЯ ПОСЛЕ бара события. 0 = видно сразу.")
    print(f"Символы: {', '.join(s for s, _ in dfs)}\n")

    rows = []
    for spec in specs:
        t0 = time.time()
        all_lags: list[int] = []
        misses = 0
        print(f"▸ {spec.name}  (событие = {spec.anchor})")
        for sym, d in dfs:
            lags = measure(d, spec, a.events, a.stable)
            if not lags:
                print(f"    {sym:<12} событий нет")
                continue
            ok = [x for x in lags if x is not None]
            misses += len(lags) - len(ok)
            all_lags += ok
            shown = ", ".join(str(x) if x is not None else "—" for x in lags)
            print(f"    {sym:<12} n={len(lags):<3} лаги: {shown}")
        if all_lags:
            rows.append((spec.name, len(all_lags), misses,
                         float(np.median(all_lags)), max(all_lags)))
        print(f"    ⏱ {time.time() - t0:.1f}s\n")

    print("=" * 100)
    print(f"{'ДЕТЕКТОР':<38}{'замеров':>8}{'медиана':>9}{'максимум':>10}"
          f"{'макс, ч':>10}   ВИДНО СРАЗУ?")
    print("-" * 100)
    for name, n, misses, med, mx in rows:
        verdict = "✅ ДА — событие видно на своём баре" if mx == 0 else \
                  f"❌ НЕТ — признак с допуском < {mx} бар. = look-ahead"
        tail = f"  (+{misses} не подтвердились)" if misses else ""
        print(f"{name:<38}{n:>8}{med:>9.0f}{mx:>10}{mx * bar_h:>9.2f}ч   {verdict}{tail}")
    print("=" * 100)
    print("🔑 Для причинных замеров берётся МАКСИМУМ, не медиана.")
    print("🔑 Нулевая задержка = детектор годится для признака «возраст события» без поправки.")
    print("🔑 Лаг пивотных детекторов = РОВНО ИХ ПАРАМЕТР, не эмпирика: classify_structure(L) → L,")
    print("   detect_equal_levels(eq_len) → eq_len (проверено L=5/20/50, eq_len=2/3/5/10).")
    print("   detect_structure_breaks(L) → 0 при любом L: уровень свинга активируется на баре")
    print("   swing+L, то есть УЖЕ в прошлом к моменту пробоя — пробой виден на своём баре.")
    print("🔴 Лаг 0 относится к ПОЯВЛЕНИЮ и геометрии зоны. Поля mitigated_idx / is_breaker (OB)")
    print("   и mitigated (FVG) смотрят вперёд ПО ПОСТРОЕНИЮ — они в ключ события не входили.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
