# -*- coding: utf-8 -*-
"""Премиум-гейт ote_nested: был ли `4h_1h_pull + fvg_held` лучшим выбором?
Разрез: период × setup_id × fvg_held × исполнение × сторона. Плюс контрфакт сентября (SIM-непремиум).
Кост: комиссия круга 0.20% в июне (рыночный вход, факт из total_fee) — печатаю и gross, и net.
"""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np

DB = r"E:\MTF BOT\CURSOR\crypto_volume_bot\subscriptions.db"
c = sqlite3.connect(DB)
df = pd.read_sql_query("""
  SELECT id, symbol, direction, created_at, status, profit_pct, duration_minutes,
         execution_mode, account_id, exchange_order_id, strength, stop_loss, entry_price,
         be_activated, tsl_activated, sl_source, tp_source, features_json
  FROM simulated_trades
  WHERE signal_type='ote_nested' AND status NOT IN ('OPEN','PENDING_ENTRY','CANCELLED')
""", c)
print("закрытых сделок ote_nested:", len(df))
print("execution_mode:", df.execution_mode.value_counts(dropna=False).to_dict())
print("account_id:", df.account_id.value_counts(dropna=False).head(6).to_dict())
print()

F = df.features_json.fillna("{}").map(lambda s: json.loads(s) if s.startswith("{") else {})
for k in ("ote_setup_id", "ote_cf_fvg_held", "ote_cf_div", "ote_htf", "ote_ltf", "ote_type",
          "ote_trg_sc_star", "ote_conf_score", "router_final_strength"):
    df[k] = F.map(lambda d, k=k: d.get(k))
df["ts"] = pd.to_datetime(df.created_at, errors="coerce")
df["month"] = df.ts.dt.to_period("M").astype(str)
df["exch"] = df.exchange_order_id.notna()          # реально ушло на биржу
df["prem"] = (df.ote_setup_id == "4h_1h_pull") & (df.ote_cf_fvg_held == 1)
df["stop_pct"] = (df.entry_price - df.stop_loss).abs() / df.entry_price * 100
df = df[df.profit_pct.notna()]


def agg(g, fee=0.20):
    return pd.Series({
        "n": len(g),
        "WR%": (g.profit_pct > 0).mean() * 100,
        "gross%": g.profit_pct.mean(),
        "net%": g.profit_pct.mean() - fee,
        "сумма": g.profit_pct.sum() - fee * len(g),
        "безтоп10": (g.profit_pct.sort_values(ascending=False).iloc[int(len(g) * 0.1):].sum()
                     - fee * (len(g) - int(len(g) * 0.1))),
        "стоп%": g.stop_pct.median(),
        "БУ%": g.be_activated.fillna(0).astype(float).mean() * 100,
        "TSL%": g.tsl_activated.fillna(0).astype(float).mean() * 100,
        "мин": g.duration_minutes.median(),
    })


def show(title, d, by):
    if not len(d):
        print(f"== {title}: нет данных\n"); return
    t = d.groupby(by, dropna=False).apply(agg).reset_index()
    t = t[t.n >= 15].sort_values("net%", ascending=False)
    print(f"== {title}")
    print(t.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    print()


jun = df[df.month == "2026-06"]
print("ИЮНЬ 2026 — что было на столе, когда выбирали премиум-профиль")
show("июнь · БИРЖА (VST) · setup × fvg_held", jun[jun.exch], ["ote_setup_id", "ote_cf_fvg_held"])
show("июнь · SIM (идеальный фил) · setup × fvg_held", jun[~jun.exch], ["ote_setup_id", "ote_cf_fvg_held"])
show("июнь · БИРЖА · сторона", jun[jun.exch], ["direction"])
show("июнь · БИРЖА · премиум против остальных", jun[jun.exch], ["prem"])
show("июнь · БИРЖА · 4h_1h_pull × fvg_held × сторона",
     jun[jun.exch & (jun.ote_setup_id == "4h_1h_pull")], ["ote_cf_fvg_held", "direction"])

print("ПОСЛЕ 28.08 — контрфакт: премиум пошёл на биржу, непремиум остался в SIM")
post = df[df.ts >= "2026-08-28"]
show("после 28.08 · премиум × исполнение", post, ["prem", "exch"])
show("после 28.08 · setup × fvg_held (всё, включая SIM)", post, ["ote_setup_id", "ote_cf_fvg_held"])
show("после 28.08 · биржа · сторона", post[post.exch], ["direction"])
show("после 28.08 · биржа · div", post[post.exch], ["ote_cf_div"])
show("после 28.08 · по месяцам", post, ["month", "exch"])
