# -*- coding: utf-8 -*-
"""КЛЕТКА OTE × РАЗМЕР СТОПА НА ИСТОРИИ (09.10.2026, Егор: «узкие стопы в ote-cell перемерить»).

Повод. Форвард ote-cell после починки резолвера: узкий стоп (нижняя треть, < 5.87%) LONG PF 1.55 (n=55),
широкий (> 12.45%) SHORT PF 0.14 (n=13). Закон размера 11.08 (шорт-клетка, 150 монет, 2024–26) говорил
обратное: стоп > 6% PF 1.41, 2–4% PF 1.04. Это противоречие — сначала подозреваем разницу постановок:
  · бэктест 11.08: зона 0.618–0.786, ПЕРВЫЙ вход на импульс, только SHORT, только стоп > 6%;
  · тень: зона 0.45–0.95, вход раз в 12 ч (монета, сторона), пока цена в зоне, обе стороны, стоп 0.5–25%.
Здесь обе постановки на одной истории 2022 → конец кэша, обе стороны, ВСЕ размеры стопа.

Генератор — 1:1 со scripts/test_cell_both_sides_full_window.py (структура 4h окном 1000 баров раз в сутки,
assemble_impulse n_bos≥1, вход на закрытом 1h, SL за origin ×0.997/1.003, TP1R, срок 72 бара 1h, внутри бара
сначала стоп). Отличия только в зоне, правиле повторов и фильтре стопа.

Калибровки: (1) «первый вход, каноническая зона, SHORT, 2024–26, стоп > 6%» против 11.08 (n≈500, PF 1.41);
(2) «как в тени», монеты CORE, 11.08–конец кэша против журнала ote_cell_shadow (src binance).
Запуск: python scripts/ote_cell_size_lab.py [--coins 150] [--workers 8] [--reuse]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
    pass

DB = ROOT / "ohlcv_cache.db"                 # по пути E: репозитория (symlink не разворачивать)
OUT = Path("G:/oko_lab/out/ote_cell_size_lab.parquet")
T0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
COST = 0.35
BINS = [0.5, 2, 4, 6, 9, 25]
SHADOW_T = (5.87, 12.45)                     # терцили stop_pct в журнале тени (09.10)
COOLDOWN_MS = 12 * 3600 * 1000
ZONES = {"canon": (0.618, 0.786), "wide": (0.45, 0.95)}


def load(sym, tf):
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                     "AND time>=? ORDER BY time", c, params=(sym, tf, T0))
    c.close()
    return df.drop_duplicates("time").reset_index(drop=True)


def sim(i, side, H, L, C, sl, tp, ttl=72):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if side > 0:
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        else:
            if H[j] >= sl: return (e - sl) / e * 100
            if L[j] <= tp: return (e - tp) / e * 100
    return side * (C[end] - e) / e * 100


def one(sym):
    from core.smc.oko_sm_engine import run_structure
    from core.smc.impulse_assembly import assemble_impulse, ote_zone
    d4, d1 = load(sym, "4h"), load(sym, "1h")
    if len(d4) < 1200 or len(d1) < 5000:
        return [], {}
    yc = d1.assign(y=pd.to_datetime(d1.time, unit="ms").dt.year).groupby("y").close.agg(["first", "last", "size"])
    yret = {int(y): (r["last"] / r["first"] - 1) * 100 for y, r in yc.iterrows() if r["size"] > 24 * 300}
    t4, t1 = d4.time.values, d1.time.values
    H1, L1, C1 = d1.high.values, d1.low.values, d1.close.values
    out = []
    seen_first = {}                              # (zone, side) → импульс: первый вход на импульс
    last_shadow = {}                             # side → время последнего входа «как в тени»
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        imp = assemble_impulse(st, win["high"], win["low"], internal=True)
        if not imp or imp["n_bos"] < 1:
            continue
        is_long = imp["is_long"]; sd = "LONG" if is_long else "SHORT"; side = 1 if is_long else -1
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        sl = imp["origin"] * (0.997 if is_long else 1.003)
        rng = abs(imp["extreme"] - imp["origin"])
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for zone, (a, z) in ZONES.items():
            z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], is_long, a, z)
            for mode in ("first", "shadow"):
                if mode == "first" and (zone != "canon" or seen_first.get(sd) == key):
                    continue
                if mode == "shadow" and zone != "wide":
                    continue
                for j in range(max(j0, 1), j1):
                    px = C1[j]
                    if not (z_lo <= px <= z_hi):
                        continue
                    stop = abs(px - sl) / px * 100
                    bad = (is_long and sl >= px) or ((not is_long) and sl <= px) or not (0.5 < stop < 25)
                    if bad:                      # бэктест 11.08 обрывал окно; тень просто пропускает скан
                        if mode == "first":
                            break
                        continue
                    if mode == "shadow" and t1[j] - last_shadow.get(sd, -10**15) < COOLDOWN_MS:
                        continue
                    retr = ((imp["extreme"] - px) / rng) if is_long else ((px - imp["extreme"]) / rng)
                    out.append({"sym": sym, "t": int(t1[j]), "side": sd, "mode": mode, "zone": zone,
                                "stop_pct": stop, "retr": retr,
                                "pnl": sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl))})
                    if mode == "first":
                        seen_first[sd] = key
                        break
                    last_shadow[sd] = int(t1[j])
    return out, yret


def stat(p):
    p = np.asarray(p)
    if len(p) < 10:
        return f"n={len(p):>4}  —"
    s = np.sort(p); gl = -s[s < 0].sum(); cut = max(1, len(s) // 10)
    return (f"n={len(p):>4} WR{(p > 0).mean()*100:3.0f}% мед{np.median(p):+6.2f}% ср{p.mean():+6.2f}% "
            f"PF{(s[s > 0].sum() / gl) if gl else 9.9:5.2f} безтоп10%{s[:-cut].sum():+7.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    from oi_fast_poller import CORE
    core = {c.upper() for c in CORE}
    if a.reuse and OUT.exists():
        D = pd.read_parquet(OUT)
    else:
        c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        rows = c.execute("SELECT symbol, COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? "
                         "GROUP BY symbol HAVING n>1200 ORDER BY n DESC", (T0,)).fetchall()
        c.close()
        longest = [s for s, n in rows if n > 6000][:a.coins]
        cores = [s for s, _ in rows if s.split("/")[0].upper() in core]
        syms = list(dict.fromkeys(longest + cores))
        print(f"монет {len(syms)}: {len(longest)} с длинной историей + {len(set(cores) - set(longest))} из CORE радара")
        with ProcessPoolExecutor(a.workers) as ex:
            res = list(ex.map(one, syms, chunksize=2))
        D = pd.DataFrame([r for part, _ in res for r in part])
        OUT.parent.mkdir(parents=True, exist_ok=True)
        D.to_parquet(OUT)
        Y = pd.DataFrame([{"year": y, "ret": v} for _, yr in res for y, v in yr.items()])
        Y.to_parquet(OUT.with_name("ote_cell_size_lab_years.parquet"))
    D["net"] = D.pnl - COST
    D["ts"] = pd.to_datetime(D.t, unit="ms")
    D["year"] = D.ts.dt.year
    D["base"] = D.sym.str.split("/").str[0].str.upper()
    D["core"] = D.base.isin(core)
    D["bin"] = pd.cut(D.stop_pct, BINS, labels=[f"{BINS[i]}–{BINS[i+1]}" for i in range(len(BINS) - 1)])
    D["terc"] = pd.cut(D.stop_pct, [0.5, *SHADOW_T, 25], labels=["узк<5.9", "сред", "шир>12.5"])
    # golden: стоп и цель в одном баре → стоп; цель раньше → +R
    assert sim(0, 1, np.array([0, 106.0]), np.array([0, 94.0]), np.array([100.0, 100]), 95, 105) == -5.0
    assert sim(0, -1, np.array([0, 101.0]), np.array([0, 94.0]), np.array([100.0, 100]), 105, 95) == 5.0

    print("═" * 120)
    print(f"СИГНАЛОВ {len(D)} · монет {D.sym.nunique()} · {D.ts.min():%Y-%m-%d} → {D.ts.max():%Y-%m-%d}")
    print(D.groupby(["mode", "side"]).size().unstack().to_string())

    print("\nКАЛИБРОВКА 1 — против 11.08 (первый вход, канон, SHORT, 2024–26, стоп > 6%; записано n≈500 PF 1.41):")
    k = D[(D["mode"] == "first") & (D.side == "SHORT") & (D.year >= 2024) & (D.stop_pct > 6)]
    print("   ", stat(k.net))
    f0 = pd.Timestamp("2026-08-11")
    k2 = D[(D["mode"] == "shadow") & D.core & (D.ts >= f0)]
    print(f"КАЛИБРОВКА 2 — «как в тени», CORE, с 11.08.2026 (журнал тени binance: LONG 206 / SHORT 66 до 28.09):")
    for sd in ("LONG", "SHORT"):
        print(f"    {sd:5}", stat(k2[k2.side == sd].net))

    for mode, label in (("first", "ПЕРВЫЙ ВХОД, зона 0.618–0.786 (как бэктест 11.08)"),
                        ("shadow", "КАК В ТЕНИ: зона 0.45–0.95, повтор раз в 12 ч")):
        M = D[D["mode"] == mode]
        print("\n" + "═" * 120)
        print(f"{label} · net = % − {COST}")
        for sd in ("LONG", "SHORT"):
            X = M[M.side == sd]
            print(f"  ── {sd} · все стопы: {stat(X.net)}")
            for col, title in (("bin", "корзины 11.08"), ("terc", "терцили тени")):
                print(f"     {title}:")
                for b, Y in X.groupby(col, observed=True):
                    yrs = " ".join(f"{y % 100}:{np.median(Z.net):+5.2f}" if len(Z) >= 12 else f"{y % 100}:  ?  "
                                   for y, Z in Y.groupby("year"))
                    print(f"       {str(b):9} {stat(Y.net)} | {yrs}")
    # режимы лет — посчитаны на этой же вселенной (медиана годовой доходности монеты, годы с ≥300 днями данных)
    yp = OUT.with_name("ote_cell_size_lab_years.parquet")
    if yp.exists():
        Y = pd.read_parquet(yp).groupby("year").ret.agg(["median", "size", lambda s: (s > 0).mean() * 100])
        Y.columns = ["медиана годовой %", "монет", "растущих %"]
        print("\nРЕЖИМ ЛЕТ (эта вселенная):")
        print(Y.round(1).to_string())


if __name__ == "__main__":
    main()
