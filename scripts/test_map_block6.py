# -*- coding: utf-8 -*-
"""КАРТА, БЛОК 6 (07.08) — ФОРВАРД-ДАННЫЕ (истории 4 недели, бэктест невозможен).
Сшиваем живой фид с НАШИМИ реальными сделками (не с бэктестом!) по времени:
  #OI      квадрант OI×цена — единственный разделитель, доказанный DS
  #LIQ     каскады ликвидаций перед входом
  #DEPTH   стакан: дисбаланс bid/ask и стены
Данные: oko_feed/external_data.db (oi_snapshots 67k, liq_events 127k, depth_snap 8.8k).
Сделки: subscriptions.db, все VST-источники с 2026-07-09 (когда появился depth_snap)."""
import sqlite3, sys, numpy as np, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")


def norm(s):
    s = str(s or "").split(":")[0].replace("/", "-")
    return s.split("-")[0].upper()


def rep(name, v):
    if len(v) < 12:
        print(f"    {name:32} n={len(v)}"); return
    r = np.array(v)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    print(f"    {name:32} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{np.median(r):+7.3f}% "
          f"ср{r.mean():+7.3f}% PF{pf:5.2f} сум{r.sum():+8.2f}%")


# ── сделки
c = sqlite3.connect("subscriptions.db")
trades = list(c.execute("""SELECT id,symbol,signal_type,direction,created_at,profit_pct
   FROM simulated_trades WHERE execution_mode='VST' AND status NOT IN ('OPEN','PENDING_ENTRY')
   AND profit_pct IS NOT NULL AND created_at>='2026-07-09' ORDER BY created_at"""))
c.close()
print(f"сделок VST с 09.07 (появление depth_snap): {len(trades)}")
if not trades:
    sys.exit()

ext = sqlite3.connect("oko_feed/external_data.db")
# ── OI: строим ряд по монете
oi = defaultdict(list)
for sym, ts, val in ext.execute("SELECT symbol,ts,oi_usd FROM oi_snapshots WHERE oi_usd IS NOT NULL ORDER BY ts"):
    oi[norm(sym)].append((int(ts), float(val)))
# ── ликвидации
liq = defaultdict(list)
for ts, sym, usd, side in ext.execute("SELECT ts,symbol,usd,side FROM liq_events WHERE usd IS NOT NULL"):
    liq[norm(sym)].append((int(ts), float(usd), str(side or "")))
# ── стакан
dep = defaultdict(list)
for ts, sym, b, a in ext.execute("SELECT ts,symbol,bid_usd,ask_usd FROM depth_snap "
                                 "WHERE bid_usd IS NOT NULL AND ask_usd IS NOT NULL ORDER BY ts"):
    dep[norm(sym)].append((int(ts), float(b), float(a)))
ext.close()
print(f"  OI: {len(oi)} монет · ликвидации: {len(liq)} · стакан: {len(dep)}\n")

OI = defaultdict(list); LQ = defaultdict(list); DP = defaultdict(list)
matched = {"oi": 0, "liq": 0, "dep": 0}
for tid, sym, st, d, ca, p in trades:
    b = norm(sym)
    try:
        t = int(dt.datetime.fromisoformat(str(ca).replace("Z", "+00:00")).timestamp())  # 07.08: фид в СЕКУНДАХ
    except Exception:
        continue
    # OI: изменение за 1ч до входа
    ser = oi.get(b) or []
    if len(ser) > 5:
        prev = [v for ts, v in ser if t - 3600 <= ts <= t]
        if len(prev) >= 2 and prev[0] > 0:
            ch = (prev[-1] - prev[0]) / prev[0] * 100
            matched["oi"] += 1
            k = ("OI растёт >1%" if ch > 1 else ("OI падает <-1%" if ch < -1 else "OI ровно"))
            OI[k].append(p)
            # квадрант: OI × направление сделки
            OI[f"{'OI↑' if ch > 0 else 'OI↓'} + {d}"].append(p)
    # ликвидации: сумма за 30 мин до входа
    lser = [(ts, u) for ts, u, _ in (liq.get(b) or []) if t - 1800 <= ts <= t]
    if lser:
        matched["liq"] += 1
        tot = sum(u for _, u in lser)
        LQ["каскад >$100k" if tot > 100000 else ("$10-100k" if tot > 10000 else "мелкие <$10k")].append(p)
    else:
        LQ["ликвидаций не было"].append(p)
    # стакан: дисбаланс на входе
    dser = [(ts, bb, aa) for ts, bb, aa in (dep.get(b) or []) if t - 1800 <= ts <= t]
    if dser:
        matched["dep"] += 1
        _, bb, aa = dser[-1]
        if bb > 0 and aa > 0:
            r = bb / aa
            DP["биды >1.5× асков" if r > 1.5 else ("аски >1.5× бидов" if r < 0.667 else "баланс")].append(p)
print(f"сматчено: OI={matched['oi']} · ликвидации={matched['liq']} · стакан={matched['dep']}\n")
allp = [t[5] for t in trades]
print("═══ БАЗА ═══"); rep("все VST-сделки", allp)
print("\n═══ #OI КВАДРАНТ (изменение OI за 1ч до входа) ═══")
for k in ("OI растёт >1%", "OI ровно", "OI падает <-1%"):
    rep(k, OI.get(k, []))
print("  ── квадрант OI × сторона ──")
for k in ("OI↑ + LONG", "OI↑ + SHORT", "OI↓ + LONG", "OI↓ + SHORT"):
    rep(k, OI.get(k, []))
print("\n═══ #LIQ КАСКАДЫ (сумма ликвидаций за 30 мин до входа) ═══")
for k in ("каскад >$100k", "$10-100k", "мелкие <$10k", "ликвидаций не было"):
    rep(k, LQ.get(k, []))
print("\n═══ #DEPTH ДИСБАЛАНС СТАКАНА на входе ═══")
for k in ("биды >1.5× асков", "баланс", "аски >1.5× бидов"):
    rep(k, DP.get(k, []))
