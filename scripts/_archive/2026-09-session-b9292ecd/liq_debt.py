# -*- coding: utf-8 -*-
"""ЗАКРЫТИЕ ДОЛГА: встречается ли liq_near с механикой после починки (10.09.2026).

В памяти записано: «liq_near = 0 из 1572 — механика и признак НЕ ВСТРЕЧАЮТСЯ».
Причина найдена: абсолютный порог 0.5% на 1h давал частоту 0.1% — совпадений и
не могло быть. Порог переведён в доли ATR. Проверяем на РЕАЛЬНОМ пуле сделок.

Сравниваются две версии детектора на одних и тех же барах входа:
  СТАРАЯ  — фиксированный порог 0.5%
  НОВАЯ   — 0.81·ATR(14) своего ТФ
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.calculators.swing_bridge import etl_liquidity, etl_order_blocks, _atr_pct

CACHE = "ohlcv_cache.db"
SUBS = "subscriptions.db"
TF = "1h"

cn = sqlite3.connect(SUBS)
tr = pd.read_sql(
    "SELECT symbol, direction AS side, entry_price, created_at, profit_pct, status "
    "FROM simulated_trades WHERE entry_price > 0 AND created_at IS NOT NULL "
    "ORDER BY created_at", cn)
cn.close()
tr["ts"] = pd.to_datetime(tr["created_at"], errors="coerce", utc=True, format="mixed")
# 🔴 формат-ловушка проекта: в БД символы С суффиксом (ZEC/USDT:USDT), в кэше БЕЗ
tr["symbol"] = tr["symbol"].str.replace(":USDT", "", regex=False)
tr = tr.dropna(subset=["ts"])
print(f"сделок в БД: {len(tr):,} | символов: {tr.symbol.nunique()} | "
      f"{tr.ts.min():%Y-%m-%d} → {tr.ts.max():%Y-%m-%d}\n")

cc = sqlite3.connect(CACHE)
hit_new = hit_old = tot = 0
per_sym = {}
for sym, g in tr.groupby("symbol"):
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                    "WHERE symbol=? AND timeframe=? ORDER BY time",
                    cc, params=(sym, TF))
    if len(d) < 500:
        continue
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True)
    dd = d[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
    try:
        lq = etl_liquidity(dd)
    except Exception:
        continue
    near_new = lq["liq_near_dn"] | lq["liq_near_up"]
    # СТАРАЯ версия: тот же расчёт дистанций, но фиксированный порог 0.5%
    up_d, dn_d = lq["liq_up_dist_pct"], lq["liq_dn_dist_pct"]
    near_old = (np.nan_to_num(up_d, nan=1e9) < 0.5) | (np.nan_to_num(dn_d, nan=1e9) < 0.5)
    idx = np.searchsorted(d.index.values, g["ts"].values, "right") - 1
    ok = (idx >= 0) & (idx < len(dd))
    idx = idx[ok]
    if len(idx) == 0:
        continue
    n_ = len(idx); hn = int(near_new[idx].sum()); ho = int(near_old[idx].sum())
    tot += n_; hit_new += hn; hit_old += ho
    per_sym[sym] = (n_, hn, ho)

print("=== ВСТРЕЧАЕМОСТЬ liq_near НА БАРАХ ВХОДА РЕАЛЬНЫХ СДЕЛОК (1h) ===")
print(f"  сделок сопоставлено с кэшем: {tot:,}")
print(f"  СТАРЫЙ детектор (порог 0.5%):     {hit_old:>6,}  ({hit_old/max(tot,1)*100:.2f}%)")
print(f"  НОВЫЙ детектор (0.81·ATR):        {hit_new:>6,}  ({hit_new/max(tot,1)*100:.2f}%)")
print(f"  прирост: ×{hit_new/max(hit_old,1):.1f}")

print("\n=== ПО МОНЕТАМ (топ-12 по числу сделок) ===")
print(f"{'символ':>16} {'сделок':>8} {'старый':>8} {'новый':>7}")
for sym, (n_, hn, ho) in sorted(per_sym.items(), key=lambda x: -x[1][0])[:12]:
    print(f"{sym:>16} {n_:>8,} {ho:>8,} {hn:>7,}")

# связь признака с результатом сделки
rows = []
for sym, g in tr.groupby("symbol"):
    if sym not in per_sym:
        continue
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                    "WHERE symbol=? AND timeframe=? ORDER BY time",
                    cc, params=(sym, TF))
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True)
    dd = d[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
    try:
        lq = etl_liquidity(dd)
    except Exception:
        continue
    near = lq["liq_near_dn"] | lq["liq_near_up"]
    idx = np.searchsorted(d.index.values, g["ts"].values, "right") - 1
    ok = (idx >= 0) & (idx < len(dd))
    sub = g[ok].copy()
    sub["near"] = near[idx[ok]]
    rows.append(sub[["symbol", "side", "profit_pct", "near", "status"]])
cc.close()
if rows:
    A = pd.concat(rows)
    A = A[A.profit_pct.notna()]
    print(f"\n=== СВЯЗЬ С РЕЗУЛЬТАТОМ (n={len(A):,}) ===")
    print(f"{'liq_near':>10} {'сделок':>8} {'ср profit%':>12} {'мед':>9} {'WR':>7}")
    for v in [False, True]:
        s = A[A.near == v]
        if len(s) < 30:
            continue
        print(f"{str(v):>10} {len(s):>8,} {s.profit_pct.mean():+11.3f}% "
              f"{s.profit_pct.median():+8.3f}% {(s.profit_pct > 0).mean()*100:6.1f}%")
