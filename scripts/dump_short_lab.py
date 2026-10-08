# -*- coding: utf-8 -*-
"""ШОРТ ПО РЫНКУ В НАЧАЛЕ СЛИВА (Егор 08.10, пункт 3: шорт-механики бота входят лимитом на откате и в прямом сливе
не исполняются — 9 заявок висят; «система должна очень быстро реагировать на происходящее на рынке»).

ЗАДАНО ДО ПРОГОНА:
  · событие — первый час эпизода, когда за 2 ч ≥ 50% монет журнала упали сильнее 3% (порог маркет-пульса, ≈7 раз в
    месяц); вход по рынку на open следующего часа (как fwd/geo журнала); причинно — ширина по ЗАКРЫТЫМ часам;
  · корзины в событии: все монеты · лидеры падения (нижняя треть хода за 2 ч) · отстающие (верхняя треть);
  · исходы, кост 0.35: шорт по рынку 4 ч и 24 ч (−fwd), стоп/цель 1.5/3 ATR и 4/8 ATR 72 ч (geo_*_short);
    зеркально — лонг тех же монет (вопрос «шортить слив или покупать»);
  · сравнение — те же исходы у обычного часа (сетка `ctrl` журнала, каждые 72 ч на монету);
  · журнал `G:/oko_lab/joint/1h` (469 монет, 2023-01 → 2026-10-06).

Запуск: python scripts/dump_short_lab.py [процессов]
"""
from __future__ import annotations

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402

JOURNAL = Path("G:/oko_lab/joint/1h")
EV = Path("G:/oko_lab/joint/events")
COST, THR, SHARE = 0.35, -0.03, 0.50
COLS = ["close", "fwd_4", "fwd_24", "geo_tight_short", "geo_wide_short", "geo_tight_long", "geo_wide_long", "liq"]


def _r2(f):
    c = pd.read_parquet(f, columns=["close"]).close
    c.index = c.index.tz_convert(None) if c.index.tz is not None else c.index
    return (c / c.shift(2) - 1).rename(f.stem)


def _rows(args):
    f, hours = args
    J = pd.read_parquet(f, columns=["sym"] + COLS)
    J.index = J.index.tz_convert(None) if J.index.tz is not None else J.index
    J["r2"] = J.close / J.close.shift(2) - 1
    out = J[J.index.isin(hours)].copy()
    out["ts"] = out.index
    return out.reset_index(drop=True)


def outcomes(T: pd.DataFrame) -> pd.DataFrame:
    """Доход сделки −кост: шорт по рынку (−fwd) и по стопу/цели (geo_*_short уже со знаком шорта); лонг — зеркально."""
    return pd.DataFrame({
        "short_4h": -T.fwd_4 - COST, "short_24h": -T.fwd_24 - COST,
        "short_geo_tight": T.geo_tight_short - COST, "short_geo_wide": T.geo_wide_short - COST,
        "long_4h": T.fwd_4 - COST, "long_24h": T.fwd_24 - COST,
        "long_geo_tight": T.geo_tight_long - COST, "long_geo_wide": T.geo_wide_long - COST}, index=T.index)


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    files = sorted(JOURNAL.glob("*.parquet"))
    with Pool(procs) as pool:
        R2 = pd.concat(pool.map(_r2, files), axis=1)
    n = R2.notna().sum(axis=1)
    sh = ((R2 < THR).sum(axis=1) / n)[n >= 50]
    on = sh >= SHARE
    start = on & ~on.shift(1, fill_value=False)
    hours = set(sh.index[start])
    # §0A.2 golden: эпизод «0.4, 0.6, 0.7, 0.2, 0.55» → старты на 2-м и 5-м часах
    g = pd.Series([0.4, 0.6, 0.7, 0.2, 0.55]) >= SHARE
    assert list((g & ~g.shift(1, fill_value=False)).values) == [False, True, False, False, True]
    print(f"эпизодов слива (2ч, ≥{SHARE:.0%} монет вниз >{-THR:.0%}): {len(hours)} · {min(hours)} → {max(hours)}")
    with Pool(procs) as pool:
        E = pd.concat(pool.map(_rows, [(f, hours) for f in files]), ignore_index=True)
    E = E[E.fwd_24.notna()]
    E["ep"] = E.ts
    E["third"] = E.groupby("ep").r2.transform(lambda x: pd.qcut(x.rank(method="first"), 3, labels=["лидеры", "середина", "отстающие"]))
    O = outcomes(E)
    C = pd.read_parquet(EV / "ctrl.parquet")
    C = C[C.fwd_24.notna()]
    OC = outcomes(C)
    print(f"сделок в событиях: {len(E)} · монет {E.sym.nunique()} · обычный час (контроль): {len(C)}")
    print(E[["sym", "ts", "r2", "fwd_4", "fwd_24", "third"]].head(4).round(4).to_string(index=False))

    E["y"] = pd.to_datetime(E.ts).dt.year
    print(f"\n{'исход':<18}{'обычный час':>13}{'все в сливе':>13}{'лидеры':>10}{'отстающие':>11}   по годам (все в сливе)")
    for col in O.columns:
        yy = " ".join(f"{y} {v:+.2f}" for y, v in O[col].groupby(E.y).mean().items())
        print(f"{col:<18}{OC[col].mean():>+13.2f}{O[col].mean():>+13.2f}{O[col][E.third == 'лидеры'].mean():>+10.2f}"
              f"{O[col][E.third == 'отстающие'].mean():>+11.2f}   {yy}")
    print(f"\nмедианы: шорт 24ч в сливе {O.short_24h.median():+.2f} (обычный {OC.short_24h.median():+.2f}) · "
          f"лонг 24ч в сливе {O.long_24h.median():+.2f} (обычный {OC.long_24h.median():+.2f})")

    # карточки: событие против обычного часа (тот же исход, те же монеты вселенной)
    for col in ("short_4h", "short_24h", "short_geo_wide", "long_24h", "long_geo_wide"):
        A = pd.concat([pd.DataFrame({"sym": E.sym, "ts": E.ts, "pnl": O[col], "liq": E.liq, "ev": True}),
                       pd.DataFrame({"sym": C.sym, "ts": pd.to_datetime(C.index if "ts" not in C else C.ts),
                                     "pnl": OC[col], "liq": C.liq, "ev": False})], ignore_index=True)
        A["ts"] = pd.to_datetime(A.ts)
        A["ts"] = A.ts.dt.tz_localize(None) if A.ts.dt.tz is not None else A.ts
        A["side"] = "SHORT" if col.startswith("short") else "LONG"      # карточке нужна сторона
        A = A[np.isfinite(A.pnl.values)].reset_index(drop=True)          # normalize выкидывает пустые — маска должна совпасть
        D = V.normalize(A, pnl="pnl", ts="ts", liq="liq")
        V.card(D, A.ev.values, name=f"слив (2ч ≥50%) → {col}", study="dump-short")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
