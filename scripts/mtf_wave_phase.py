"""
mtf_wave_phase.py — ВОЛНОВАЯ ФАЗА НА ДВУХ ТФ: старший отдохнул, младший ожил (29.08.2026).

Вопрос Егора: «LTF может ускорить детекцию завершения импульса? или WT / cross / значимый
уровень / pivot? ну я даже не знаю что ещё — спроси рой что ли».

Рой не понадобился: все кандидаты уже лежат в матрице, и данные ответили прямо.

ЧТО ПРОВЕРЕНО И ОТКЛОНЕНО — мгновенные признаки как ЗАМЕНА эллиоттовской метки
(у них нет задержки подтверждения, поэтому они были бы лучше). Поверх боевого гейта:

    wt_ob            ×2.09, но запрещает лишь 4% сделок · Жаккар с Эллиоттом 0.025
    wt_cross_down    ×1.67, 2% · 0.005
    pivot_near_R1    ×1.54, 2% · 0.017
    vol_spike        ×1.12, 52% · 0.176
    st50_is_choch    ×0.62 (вредит)

Эталон — эллиоттовская метка ×3.26 на 21% сделок. Ни один мгновенный признак её не
заменяет: Жаккар около нуля означает, что они ловят СОВСЕМ ДРУГИЕ сделки.

🔑 ЧТО ОКАЗАЛОСЬ ВЕРНЫМ В ИДЕЕ ПРО LTF — но с обратным знаком. На 5m разметка работает
НАОБОРОТ: свежий импульс на 5m это ХОРОШО (PF 1.53), а его отсутствие плохо (0.76).
На 15m наоборот. То есть LTF не ускоряет детекцию — он меряет ДРУГОЕ явление.

Отсюда комбинация, которую и считает этот скрипт:
    старший масштаб (15m) отдохнул  +  младший (5m) ожил

    python scripts/mtf_wave_phase.py
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

from research_harness import load, line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
LAG_BARS = 8        # задержка подтверждения детектора, измерена: 6 баров + запас
T0 = "2025-01-01"   # раньше данных 5m нет


def wave_age(sym: str, ts: pd.Series, tf: str, bar_min: int):
    """Возраст последнего ПОДТВЕРЖДЁННОГО импульса. Причинно: +LAG_BARS к экстремуму."""
    from core.smc.smc_engine import detect_elliott_mtf
    try:
        d = load(sym, tf)
    except Exception:                       # noqa: BLE001
        return None
    if d is None or len(d) < 5000:
        return None
    try:
        imps = detect_elliott_mtf(d)
    except Exception:                       # noqa: BLE001
        return None
    if not imps:
        return None
    rows = []
    for im in imps:
        t = pd.Timestamp(im["waves"][-1][0])
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        rows.append(dict(t_conf=t + pd.Timedelta(minutes=bar_min * LAG_BARS), t_end=t))
    E = pd.DataFrame(rows).sort_values("t_conf")
    L = pd.DataFrame({"_ts": pd.to_datetime(ts, utc=True)}).sort_values("_ts")
    j = pd.merge_asof(L, E.rename(columns={"t_conf": "_ts"}), on="_ts",
                      direction="backward", allow_exact_matches=False)
    return ((j._ts - j.t_end).dt.total_seconds() / 3600).values


def main() -> int:
    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna() & (R._ts >= T0)].copy()

    parts = []
    for sym, g in R.groupby("sym"):
        g = g.sort_values("_ts").reset_index(drop=True)
        a15 = wave_age(sym, g._ts, "15m", 15)
        if a15 is None:
            continue
        a5 = wave_age(sym, g._ts, "5m", 5)
        g["age15"] = a15
        g["age5"] = a5 if a5 is not None else np.nan
        parts.append(g)
    R = pd.concat(parts, ignore_index=True)

    gate = R.mkt_drift_slope > 0
    clean15 = ~(R.age15.notna() & (R.age15 <= 24))     # крупный импульс отработан
    fresh5 = R.age5.notna() & (R.age5 <= 24)           # мелкий импульс живой

    print("=" * 104)
    print(f"ВОЛНОВАЯ ФАЗА НА ДВУХ ТФ · окно {T0}→ · сделок {len(R)} · монет {R.sym.nunique()}")
    print("=" * 104)
    print("задержка подтверждения: 15m → 2.0 ч · 5m → 0.67 ч (измерена, не предположена)\n")
    print(line(R[gate], "  БАЗА гейт"))
    print(line(R[gate & clean15], "  15m отдохнул"))
    print(line(R[gate & fresh5], "  5m ожил"))
    print(line(R[gate & clean15 & fresh5], "  ⭐ 15m отдохнул + 5m ожил"))
    print(line(R[gate & ~clean15 & ~fresh5], "  наоборот (зеркало)"))

    m = clean15 & fresh5
    print("\nГОД:")
    for y in sorted(R.year.unique()):
        g = R[(R.year == y) & gate]
        a, b = stat(g[m[g.index]]), stat(g)
        if a and b and b["pf"]:
            print(f"  {y}: {a['pf']:5.2f} (n={a['n']:>4}) против гейт {b['pf']:5.2f}"
                  f"  ×{a['pf']/b['pf']:.2f}  безтоп10% {a['bt']:+7.0f}  охват {a['cov']:.0f}%")

    print("\nСТОРОНА:")
    for s in ("long", "short"):
        mm = gate & (R.side == s)
        a, b = stat(R[mm & m]), stat(R[mm])
        if a and b and b["pf"]:
            print(f"  {s:<6} {a['pf']:5.2f} (n={a['n']:>4}) против {b['pf']:5.2f}"
                  f"  ×{a['pf']/b['pf']:.2f}  безтоп10% {a['bt']:+7.0f}")

    sub = R[gate & m]
    per = sub.groupby("sym").pnl.sum().sort_values(ascending=False)
    print(f"\nОХВАТ: монет {len(per)} · в плюсе {(per>0).sum()} ({(per>0).mean()*100:.0f}%)"
          f" · сумма {per.sum():+.0f}% · без лучших трёх {per.iloc[3:].sum():+.0f}%")
    print("\n🔴 ОГРАНИЧЕНИЕ: данные 5m только с 2025-01 — на 2023-2024 правило НЕ проверяемо.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
