# -*- coding: utf-8 -*-
"""POB (Point of Break) — детект + честный бэктест (07.07, запрос Егора по TRADING_ENCYCLOPEDIA).

Энциклопедия §1.4: POB = зона проторговки перед сломом структуры (от экстремума до BOS).
Вход от 0.5 зоны, стоп за зону, цель = ликвидность.

Оцифровка:
  1. Слом = detect_structure_breaks (LuxAlgo BOS/CHoCH: свинг активируется через length баров
     как в Pine — point-in-time честно; +объём на пробое опционально).
  2. POB-зона = [min(low), max(high)] баров от свинг-экстремума ноги до бара слома.
  3. Вход = ЛИМИТКА на 0.5 зоны, ждём ретеста <= retest_bars баров. Не коснулась — сетапа нет.
  4. SL за зону + буфер 0.2% (закон свит-ликвидности). TP = RR-мультипль (сетка).
  5. Интрабар: бар касается SL и TP → SL-first (консервативный стандарт).
  6. Метрика: % net (ЗАКОН №1), costs=0.15% (лимит-вход + market-выход), по годам.

Запуск: python scripts/test_pob.py [--tf 1h] [--vol]  (--vol = требовать объём на пробое)
"""
import sys, sqlite3, time
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

from core.smc.smc_engine import detect_structure_breaks

SYMS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK", "AVAX", "DOT",
        "LTC", "ARB", "OP", "NEAR", "ATOM"]
TF = "--tf" in sys.argv and sys.argv[sys.argv.index("--tf") + 1] or "1h"
NEED_VOL = "--vol" in sys.argv
RETEST_BARS = 60
SL_BUF = 0.002          # 0.2% за зону
COSTS = 0.15            # % net: лимит-вход ~0.02-0.07 + market-выход ~0.05-0.13
RRS = (1.5, 2.0, 3.0)
LENGTH = 50             # swing length детектора (дефолт движка)


def load(sym: str) -> pd.DataFrame | None:
    c = sqlite3.connect("ohlcv_cache.db")
    df = pd.read_sql_query(
        "SELECT time, open, high, low, close, volume FROM ohlcv_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time", c, params=(f"{sym}/USDT", TF))
    c.close()
    if len(df) < 1000:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms")
    return df[["open", "high", "low", "close", "volume"]]


def run_symbol(sym: str) -> list[dict]:
    df = load(sym)
    if df is None:
        return []
    breaks = detect_structure_breaks(df, length=LENGTH)
    h, l = df["high"].values, df["low"].values
    n = len(df)
    out = []
    for br in breaks:
        if NEED_VOL and not br.has_volume:
            continue
        bi = br.idx                              # бар слома (close пробил уровень)
        si = br.from_idx                         # бар свинг-уровня (начало проторговки)
        if bi is None or si is None or si < 0 or bi <= si:
            continue
        seg_lo = float(l[si:bi + 1].min())
        seg_hi = float(h[si:bi + 1].max())
        zone = seg_hi - seg_lo
        if zone <= 0:
            continue
        bull = br.direction == "bull"
        entry = seg_lo + zone * 0.5              # 0.5 POB-зоны
        sl = (seg_lo * (1 - SL_BUF)) if bull else (seg_hi * (1 + SL_BUF))
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry > 0.15:     # санити: риск >15% = мусорная зона
            continue
        # ретест: первый бар ПОСЛЕ слома, коснувшийся 0.5 зоны (лимит-филл)
        ei = None
        for j in range(bi + 1, min(bi + 1 + RETEST_BARS, n)):
            if l[j] <= entry <= h[j]:
                ei = j
                break
            # цена ушла за SL до ретеста — сетап отменён (стоп прошили без нас)
            if (bull and l[j] < sl) or (not bull and h[j] > sl):
                break
        if ei is None:
            continue
        # исполнение: с бара ei идём до SL/TP (интрабар, SL-first)
        res = {}
        for rr in RRS:
            tp = entry + rr * risk * (1 if bull else -1)
            outcome = None
            for j in range(ei, min(ei + 500, n)):
                hit_sl = (l[j] <= sl) if bull else (h[j] >= sl)
                hit_tp = (h[j] >= tp) if bull else (l[j] <= tp)
                if j == ei:                       # на баре входа вход по entry (лимит)
                    pass
                if hit_sl:                        # SL-first при обоюдном касании
                    outcome = -(risk / entry * 100) - COSTS
                    break
                if hit_tp:
                    outcome = rr * risk / entry * 100 - COSTS
                    break
            if outcome is None:
                continue                          # не закрылась за 500 баров — не считаем
            res[rr] = outcome
        if res:
            out.append({"sym": sym, "kind": br.kind, "bull": bull,
                        "year": df.index[ei].year, **{f"rr{rr}": v for rr, v in res.items()}})
    return out


def main():
    t0 = time.time()
    rows = []
    for s in SYMS:
        r = run_symbol(s)
        rows.append((s, r))
        print(f"  {s}: {len(r)} сетапов", flush=True)
    allr = [x for _, r in rows for x in r]
    print(f"\n=== POB бэктест {TF} × {len(SYMS)} монет, vol_filter={NEED_VOL}, "
          f"costs={COSTS}%, SL-first интрабар ({time.time()-t0:.0f}s) ===")
    print(f"всего сетапов с ретестом 0.5: {len(allr)}")
    df = pd.DataFrame(allr)
    if df.empty:
        return
    for rr in RRS:
        col = f"rr{rr}"
        if col not in df.columns:
            continue
        v = df[col].dropna()
        wr = (v > 0).mean() * 100
        print(f"\n--- TP={rr}R: n={len(v)} avg={v.mean():+.3f}% net · WR={wr:.0f}% ---")
        for kind, g in df.groupby("kind"):
            gv = g[col].dropna()
            if len(gv) >= 30:
                print(f"  {kind:6}: n={len(gv):5} avg={gv.mean():+.3f}% WR={(gv>0).mean()*100:.0f}%")
        for yr, g in df.groupby("year"):
            gv = g[col].dropna()
            if len(gv) >= 30:
                print(f"  {yr}: n={len(gv):5} avg={gv.mean():+.3f}% WR={(gv>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
