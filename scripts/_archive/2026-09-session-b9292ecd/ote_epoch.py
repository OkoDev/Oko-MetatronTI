# -*- coding: utf-8 -*-
"""ЭПОХА или СЕТАП? Июнь ote_nested: строки с fvg_held=NaN против 0/1.
Если граница по ДАТЕ — сравнение разновидностей загрязнено эпохой учёта, вердикт недействителен.
"""
import sqlite3, json, sys, warnings
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import pandas as pd

DB = r"E:\MTF BOT\CURSOR\crypto_volume_bot\subscriptions.db"
c = sqlite3.connect(DB)
df = pd.read_sql_query("""
  SELECT id, created_at, status, profit_pct, duration_minutes, execution_mode, exchange_order_id,
         be_activated, tsl_activated, entry_price, stop_loss, actual_entry_price, costs_pct,
         total_fee, qty, leverage, features_json
  FROM simulated_trades
  WHERE signal_type='ote_nested' AND status NOT IN ('OPEN','PENDING_ENTRY','CANCELLED')
""", c)
F = df.features_json.fillna("{}").map(lambda s: json.loads(s) if s.startswith("{") else {})
df["setup"] = F.map(lambda d: d.get("ote_setup_id"))
df["fvg"] = F.map(lambda d: d.get("ote_cf_fvg_held"))
df["era"] = F.map(lambda d: d.get("data_era"))
df["ts"] = pd.to_datetime(df.created_at, errors="coerce", utc=True)
df["day"] = df.ts.dt.strftime("%m-%d")
df["exch"] = df.exchange_order_id.notna()
df["flag"] = df.fvg.isna().map({True: "NaN (флага нет)", False: "флаг 0/1"})
df["stop_pct"] = (df.entry_price - df.stop_loss).abs() / df.entry_price * 100
df = df[df.profit_pct.notna()]

print("=== ГРАНИЦА ПОЯВЛЕНИЯ ФЛАГА (все сделки)")
g = df.groupby("flag").ts.agg(["min", "max", "count"])
print(g.to_string()); print()

jun = df[(df.ts >= "2026-06-01") & (df.ts < "2026-07-01")].copy()
print("=== ИЮНЬ: по дням — сколько строк с флагом и без, и результат (только БИРЖА)")
t = (jun[jun.exch].groupby(["day", "flag"])
     .agg(n=("profit_pct", "size"), WR=("profit_pct", lambda s: (s > 0).mean() * 100),
          gross=("profit_pct", "mean"), BE=("be_activated", lambda s: s.fillna(0).astype(float).mean() * 100),
          stop=("stop_pct", "median"), mins=("duration_minutes", "median"))
     .reset_index())
print(t.to_string(index=False, float_format=lambda x: f"{x:7.2f}")); print()

print("=== ИЮНЬ: data_era × flag × исполнение")
t2 = (jun.groupby(["era", "flag", "exch"])
      .agg(n=("profit_pct", "size"), WR=("profit_pct", lambda s: (s > 0).mean() * 100),
           gross=("profit_pct", "mean"), BE=("be_activated", lambda s: s.fillna(0).astype(float).mean() * 100),
           TSL=("tsl_activated", lambda s: s.fillna(0).astype(float).mean() * 100),
           stop=("stop_pct", "median"), mins=("duration_minutes", "median"),
           fee=("total_fee", "median"), lev=("leverage", "median"))
      .reset_index())
print(t2.to_string(index=False, float_format=lambda x: f"{x:7.2f}")); print()

print("=== ИЮНЬ, ТОЛЬКО ЭПОХА С ФЛАГОМ, БИРЖА: сравнение разновидностей в одной эпохе")
jf = jun[jun.exch & jun.fvg.notna()]
t3 = (jf.groupby(["setup", "fvg"])
      .agg(n=("profit_pct", "size"), WR=("profit_pct", lambda s: (s > 0).mean() * 100),
           gross=("profit_pct", "mean"), sum=("profit_pct", "sum"),
           stop=("stop_pct", "median"), mins=("duration_minutes", "median"))
      .reset_index().query("n >= 25").sort_values("gross", ascending=False))
print(t3.to_string(index=False, float_format=lambda x: f"{x:7.3f}")); print()

print("=== ИЮНЬ, ЭПОХА БЕЗ ФЛАГА, БИРЖА: те же разновидности")
jn = jun[jun.exch & jun.fvg.isna()]
t4 = (jn.groupby("setup")
      .agg(n=("profit_pct", "size"), WR=("profit_pct", lambda s: (s > 0).mean() * 100),
           gross=("profit_pct", "mean"), sum=("profit_pct", "sum"),
           stop=("stop_pct", "median"), mins=("duration_minutes", "median"))
      .reset_index().query("n >= 25").sort_values("gross", ascending=False))
print(t4.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
