# -*- coding: utf-8 -*-
"""HYP-7, часть «фандинг»: потолок информации в фандинге за 2022–2026 тем же прибором, что OI
(scripts/oi_info_ceiling.py: взаимная информация, контроль-сдвиг всей оси времени на тех же строках).

Сетка 00/08/16 UTC. Причинность:
  цена t   = close 1h-бара, ОТКРЫТОГО в t−1ч (индекс бара = открытие, закон «вид 6»);
  фандинг  = последняя ставка с calc_time СТРОГО < t (ставка расчёта ровно в t не берётся);
  форвард  = close бара, открытого в t+h−1ч.
Состояния: фандинг (знак: <0 / базовый ≤0.01% / >0.01%) × изменение за 24ч (терциль);
цена (ret 8ч × ret 24ч, терцили); их произведение. ΔI = что фандинг добавляет СВЕРХ цены.

python scripts/funding_info_ceiling.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oi_info_ceiling as oic  # noqa: E402  — тот же прибор: mi, eq_accuracy, terciles, measure

ROOT = Path(__file__).resolve().parent.parent
oic.HORIZONS = {"8ч": 8, "24ч": 24, "72ч": 72}
oic.N_SHIFT = 20
STEP = 8 * 3600 * 1000


def build_panel() -> pd.DataFrame:
    c = sqlite3.connect(ROOT / "ohlcv_cache.db", timeout=60)
    fund = pd.read_sql("SELECT symbol, time, rate FROM funding_rates ORDER BY time", c)
    out = []
    for sym, fr in fund.groupby("symbol"):
        k = pd.read_sql("SELECT time, close, volume FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' ORDER BY time",
                        c, params=(sym,))
        if len(k) < 24 * 60:
            continue
        close = pd.Series(k.close.to_numpy(), index=k.time.to_numpy())
        qv = pd.Series((k.close * k.volume).to_numpy(), index=k.time.to_numpy())
        t0 = (k.time.iloc[0] // STEP + 4) * STEP                          # запас 32ч на ret24 и Δфандинга
        grid = np.arange(t0, k.time.iloc[-1] + 3600_000, STEP)

        def px(offset_h: int) -> np.ndarray:                              # close бара, открытого в t+offset−1ч
            return close.reindex(grid + (offset_h - 1) * 3600_000).to_numpy()

        g = pd.DataFrame({"t": grid, "px": px(0), "px_m8": px(-8), "px_m24": px(-24)})
        for nm, h in oic.HORIZONS.items():
            g[f"fwd_{nm}"] = (px(h) / g.px - 1) * 100
        f = fr[["time", "rate"]].sort_values("time")
        m = pd.merge_asof(pd.DataFrame({"t": grid - 1}), f.rename(columns={"time": "t"}), on="t",
                          direction="backward", tolerance=26 * 3600_000)   # calc_time < t строго
        m24 = pd.merge_asof(pd.DataFrame({"t": grid - 1 - 24 * 3600_000}), f.rename(columns={"time": "t"}),
                            on="t", direction="backward", tolerance=26 * 3600_000)
        g["rate"], g["rate_m24"] = m.rate.to_numpy(), m24.rate.to_numpy()
        g["qv30"] = qv.rolling(24 * 30, min_periods=24 * 10).median().reindex(grid - 3600_000).to_numpy()
        g["symbol"] = sym.split("/")[0]
        out.append(g.dropna(subset=["px", "rate"]))
    c.close()
    p = pd.concat(out, ignore_index=True)
    p["hr"] = (p.t // STEP).astype(int)                                   # ось времени = слот 8ч
    p["year"] = pd.to_datetime(p.t, unit="ms").dt.year
    p["ret8"] = (p.px / p.px_m8 - 1) * 100
    p["ret24"] = (p.px / p.px_m24 - 1) * 100
    p["d_rate"] = p.rate - p.rate_m24
    return p


def states(p: pd.DataFrame) -> dict:
    sign = np.select([p.rate < 0, p.rate <= 0.0001], [0, 1], 2)            # шорты платят / база / лонги платят
    dr = oic.terciles(p.d_rate)
    r8, r24 = oic.terciles(p.ret8), oic.terciles(p.ret24)
    rng = np.random.default_rng(7)

    def combo(*parts):
        code, bad = np.zeros(len(p), int), np.zeros(len(p), bool)
        for x in parts:
            bad |= x < 0
            code = code * 3 + np.maximum(x, 0)
        code[bad] = -1
        return code, 3 ** len(parts)

    f24 = p["fwd_24ч"].to_numpy()
    plant = np.where(np.isnan(f24), -1, (f24 > 0).astype(int) ^ (rng.random(len(p)) < 0.4))
    return {"шум 9 ячеек (контроль)": combo(rng.integers(0, 3, len(p)), rng.integers(0, 3, len(p))),
            "подсадка 24ч (контроль)": (plant.astype(int), 2),
            "цена (ret8×ret24)": combo(r8, r24),
            "фандинг (знак×Δ24ч)": combo(sign, dr),
            "цена × фандинг": combo(r8, r24, sign, dr)}


if __name__ == "__main__":
    P = build_panel()
    print("=== ИНВЕНТАРИЗАЦИЯ ===")
    print(f"строк {len(P):,} · монет {P.symbol.nunique()} · "
          f"{pd.to_datetime(P.t.min(), unit='ms'):%Y-%m-%d} → {pd.to_datetime(P.t.max(), unit='ms'):%Y-%m-%d}")
    reg = []
    for y, g in P.groupby("year"):
        first = g.sort_values("t").groupby("symbol").px.first()
        last = g.sort_values("t").groupby("symbol").px.last()
        btc = g[g.symbol == "BTC"].sort_values("t").px
        reg.append({"год": y, "строк": len(g), "монет": g.symbol.nunique(),
                    "BTC %": (btc.iloc[-1] / btc.iloc[0] - 1) * 100 if len(btc) else np.nan,
                    "медиана монеты %": ((last / first - 1) * 100).median(),
                    "доля растущих %": ((last / first) > 1).mean() * 100,
                    "фандинг <0 %": (g.rate < 0).mean() * 100, "фандинг >0.01% %": (g.rate > 0.0001).mean() * 100})
    print(pd.DataFrame(reg).round(1).to_string(index=False))

    ST = states(P)
    res = [oic.measure(P, ST, "все", False), oic.measure(P, ST, "все/относ.", True)]
    for y in sorted(P.year.unique()):
        sub = P[P.year == y].reset_index(drop=True)
        res.append(oic.measure(sub, states(sub), f"{y}", False))
    liq = P.qv30 >= P.groupby("hr").qv30.transform("median")
    for nm, m in {"ликвидные": liq, "неликвидные": ~liq}.items():
        sub = P[m.to_numpy()].reset_index(drop=True)
        res.append(oic.measure(sub, states(sub), nm, False))
    R = pd.concat(res, ignore_index=True)

    inc = []
    for (lab, hor), g in R.groupby(["срез", "гор"], sort=False):
        s = g.set_index("состояние")
        inc.append({"срез": lab, "гор": hor, "цена": s.at["цена (ret8×ret24)", "сверх_сдвига"],
                    "фандинг": s.at["фандинг (знак×Δ24ч)", "сверх_сдвига"],
                    "p_фанд": s.at["фандинг (знак×Δ24ч)", "p_сдвиг"],
                    "ΔI_от_фанд": s.at["цена × фандинг", "сверх_сдвига"] - s.at["цена (ret8×ret24)", "сверх_сдвига"],
                    "шум": s.at["шум 9 ячеек (контроль)", "сверх_сдвига"],
                    "подсадка": s.at["подсадка 24ч (контроль)", "сверх_сдвига"]})
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("\n=== ПОТОЛОК (все + относительно рынка) ===")
    show = R[R.срез.isin(["все", "все/относ."])].copy()
    print(show.round(5).to_string(index=False))
    print("\n=== СВОДКА ПО СРЕЗАМ: сверх контроля-сдвига, бит ===")
    print(pd.DataFrame(inc).round(5).to_string(index=False))

    print("\n=== НАПРАВЛЕНИЕ: форвард 24ч и 72ч (%) по знаку фандинга — по годам, обе стороны ===")
    P["знак"] = np.select([P.rate < 0, P.rate <= 0.0001], ["<0 шорты платят", "база"], ">0.01% лонги платят")
    P["rel72"] = P["fwd_72ч"] - P.groupby("hr")["fwd_72ч"].transform("median")
    print(P.dropna(subset=["fwd_72ч"]).groupby(["year", "знак"]).agg(
        n=("fwd_72ч", "size"), ср24=("fwd_24ч", "mean"), ср72=("fwd_72ч", "mean"), мед72=("fwd_72ч", "median"),
        отн_мед72=("rel72", "median"), отн_лучше=("rel72", lambda v: (v > 0).mean() * 100)).round(3).to_string())
    try:
        R.to_csv("G:/oko_lab/out/funding_info_ceiling.csv", index=False, encoding="utf-8")
        print("\nтаблица → G:/oko_lab/out/funding_info_ceiling.csv")
    except Exception:
        pass
