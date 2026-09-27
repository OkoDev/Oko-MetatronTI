# -*- coding: utf-8 -*-
"""Июнь по дням: сделки ote_nested (биржа) × сторона против рынка (BTC).
Вопрос: перелом 21.06 — это рынок или бот?
"""
import sqlite3, json, sys, os, warnings
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import pandas as pd

ROOT = r"E:\MTF BOT\CURSOR\crypto_volume_bot"
c = sqlite3.connect(os.path.join(ROOT, "subscriptions.db"))
df = pd.read_sql_query("""
  SELECT id, symbol, direction, created_at, status, profit_pct, duration_minutes,
         exchange_order_id, be_activated, tsl_activated, entry_price, stop_loss, sl_source, features_json
  FROM simulated_trades
  WHERE signal_type='ote_nested' AND status NOT IN ('OPEN','PENDING_ENTRY','CANCELLED')
    AND created_at >= '2026-06-01' AND created_at < '2026-07-05'
""", c)
F = df.features_json.fillna("{}").map(lambda s: json.loads(s) if s.startswith("{") else {})
df["setup"] = F.map(lambda d: d.get("ote_setup_id"))
df["ts"] = pd.to_datetime(df.created_at, errors="coerce", utc=True)
df["d"] = df.ts.dt.strftime("%m-%d")
df["exch"] = df.exchange_order_id.notna()
df["stop_pct"] = (df.entry_price - df.stop_loss).abs() / df.entry_price * 100
df = df[df.profit_pct.notna() & df.exch]

t = (df.groupby(["d", "direction"])
     .agg(n=("profit_pct", "size"), WR=("profit_pct", lambda s: (s > 0).mean() * 100),
          gross=("profit_pct", "mean"), stop=("stop_pct", "median"),
          BE=("be_activated", lambda s: s.fillna(0).astype(float).mean() * 100),
          SL=("status", lambda s: (s == "SL").mean() * 100),
          mins=("duration_minutes", "median"))
     .reset_index().pivot(index="d", columns="direction"))
print("=== ИЮНЬ по дням, БИРЖА, по сторонам")
print(t.to_string(float_format=lambda x: f"{x:6.2f}"))
print()
print("=== статусы выходов по декадам")
df["dec"] = pd.cut(df.ts.dt.day, [0, 13, 20, 31], labels=["01-13", "14-20", "21-30"])
print(df.groupby(["dec", "status"]).size().unstack(fill_value=0).to_string())
print()
print("=== sl_source по декадам")
print(df.groupby(["dec", "sl_source"]).size().unstack(fill_value=0).to_string())
print()

# рынок: BTC дневной ход из кэша
cache = os.path.join(ROOT, "ohlcv_cache.db")
cc = sqlite3.connect(cache)
tabs = [r[0] for r in cc.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("таблицы кэша:", tabs[:10])
try:
    tb = "ohlcv" if "ohlcv" in tabs else tabs[0]
    cols = [r[1] for r in cc.execute(f"PRAGMA table_info({tb})")]
    print(f"{tb} колонки:", cols)
    b = pd.read_sql_query(
        f"SELECT * FROM {tb} WHERE symbol LIKE 'BTC%' AND timeframe='1d' LIMIT 5", cc)
    print(b.to_string())
    b = pd.read_sql_query(
        f"SELECT * FROM {tb} WHERE symbol LIKE 'BTC%' AND timeframe='1d'", cc)
    tcol = [x for x in b.columns if x in ("timestamp", "ts", "open_time", "time")][0]
    b["dt"] = pd.to_datetime(b[tcol], unit="ms", errors="coerce", utc=True)
    if b.dt.isna().all():
        b["dt"] = pd.to_datetime(b[tcol], errors="coerce", utc=True)
    b = b[(b.dt >= "2026-05-28") & (b.dt < "2026-07-05")].sort_values("dt")
    b["chg%"] = b.close.pct_change() * 100
    print("\n=== BTC дневной ход")
    print(b[["dt", "close", "chg%"]].to_string(index=False, float_format=lambda x: f"{x:9.2f}"))
except Exception as e:
    print("кэш BTC не прочитан:", e)
