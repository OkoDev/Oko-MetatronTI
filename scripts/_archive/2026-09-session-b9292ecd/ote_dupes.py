# -*- coding: utf-8 -*-
"""Есть ли в БД одна и та же сделка ote_nested в ДВУХ версиях учёта?
Тест: группы (symbol, created_at, direction) с >1 строкой; сравнить id, флаг, profit_pct, статус.
"""
import sqlite3, json, sys, warnings
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import pandas as pd

DB = r"E:\MTF BOT\CURSOR\crypto_volume_bot\subscriptions.db"
c = sqlite3.connect(DB)
df = pd.read_sql_query("""
  SELECT id, symbol, direction, created_at, status, profit_pct, entry_price, stop_loss,
         execution_mode, exchange_order_id, account_id, features_json
  FROM simulated_trades WHERE signal_type='ote_nested'
""", c)
F = df.features_json.fillna("{}").map(lambda s: json.loads(s) if s.startswith("{") else {})
df["fvg"] = F.map(lambda d: d.get("ote_cf_fvg_held"))
df["setup"] = F.map(lambda d: d.get("ote_setup_id"))
df["era"] = F.map(lambda d: d.get("data_era"))
df["reg_ts"] = F.map(lambda d: d.get("register_ts"))
df["hasflag"] = df.fvg.notna()
df["ts"] = pd.to_datetime(df.created_at, errors="coerce", utc=True)

print("всего строк ote_nested:", len(df))
print("диапазон id по наличию флага:")
print(df.groupby("hasflag").agg(n=("id", "size"), id_min=("id", "min"), id_max=("id", "max"),
                                ts_min=("ts", "min"), ts_max=("ts", "max")).to_string())
print()
print("data_era:", df.era.value_counts(dropna=False).to_dict())
print()

# 🔴 register_ts — когда строка РЕАЛЬНО записана; сравнить с created_at
df["reg"] = pd.to_datetime(df.reg_ts, errors="coerce", utc=True)
sub = df[df.reg.notna()].copy()
sub["lag_days"] = (sub.reg - sub.ts).dt.total_seconds() / 86400
print("register_ts против created_at (дней):")
print(sub.groupby("hasflag").lag_days.describe()[["count", "min", "50%", "max"]].to_string())
print()

k = ["symbol", "created_at", "direction"]
cnt = df.groupby(k).id.count()
dup_keys = cnt[cnt > 1].index
print(f"групп (symbol, created_at, direction) с >1 строкой: {len(dup_keys)} из {len(cnt)}")
d = df.set_index(k).loc[dup_keys].reset_index() if len(dup_keys) else df.iloc[0:0]
if len(d):
    mix = d.groupby(k).hasflag.nunique()
    print(f"из них групп, где есть И флаговая, И безфлаговая строка: {(mix > 1).sum()}")
    print()
    print("примеры (первые 8 групп со смешанным флагом):")
    mk = mix[mix > 1].index[:8]
    ex = d.set_index(k).loc[mk].reset_index()
    print(ex[["symbol", "created_at", "direction", "id", "hasflag", "fvg", "setup",
              "status", "profit_pct", "execution_mode", "account_id"]]
          .to_string(index=False))
