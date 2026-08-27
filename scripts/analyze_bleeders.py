# -*- coding: utf-8 -*-
"""АНАЛИЗ СЛИВАЮЩИХ (Егор 04.08): radar_pump / radar_spring / ds_advisor.
Вопрос: дало бы им «более широкое зрение» — кластер, funding, AC-режим?
КЛАСТЕР восстанавливаем задним числом (сколько сделок ЛЮБОГО источника в окне ±15 мин).
AC-РЕЖИМ восстанавливаем из BingX klines (рыночная величина, одна на всех).
Плюс разбор по уже записанным фичам (regime/session/phase/weekly_bias)."""
import sqlite3, sys, json, urllib.request, numpy as np, pandas as pd, datetime as dt
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding="utf-8")
SRC=("radar_pump","radar_spring","ds_advisor")
BASKET=["BTC","ETH","SOL","XRP","BNB","DOGE","ADA","AVAX","LINK","DOT","LTC","TRX",
        "NEAR","APT","ARB","OP","ATOM","FIL","INJ","SUI","TIA","SEI","AAVE","UNI"]
def stat(name,rows):
    if len(rows)<8: print(f"      {name:34} n={len(rows)}"); return
    r=np.array(rows); pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    print(f"      {name:34} n={len(r):4} WR{100*(r>0).mean():3.0f}% ср{r.mean():+7.3f}% сум{r.sum():+8.2f}% PF{pf:.2f}")
# ── AC-режим из живых klines (60 дней)
print("восстанавливаю AC-режим из BingX (24 монеты × 1440 часов)...")
series={}
for b in BASKET:
    try:
        u=f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={b}-USDT&interval=1h&limit=1440"
        d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"oko"}),timeout=12)).get("data",[])
        if len(d)>800:
            arr=list(reversed(d))
            series[b]=pd.Series([float(k["close"]) for k in arr],
                                index=[int(k["time"]) for k in arr])
    except Exception: pass
print(f"  получено {len(series)} рядов")
panel=pd.DataFrame(series).sort_index()
r6=panel.pct_change(6); W=14*24
ac=(r6.rolling(W).corr(r6.shift(6)).mean(axis=1)).shift(6).dropna()
print(f"  AC-ряд: {len(ac)} точек, медиана {ac.median():+.4f}, "
      f"диапазон {ac.min():+.4f}..{ac.max():+.4f}")
AC_LO,AC_HI=-0.0672,-0.0126
acdf=pd.DataFrame({"time":ac.index.values,"v":ac.values})
# ── сделки
c=sqlite3.connect("subscriptions.db")
rows=list(c.execute(f"""SELECT id,symbol,signal_type,created_at,profit_pct,features_json,direction
   FROM simulated_trades WHERE signal_type IN {SRC} AND status NOT IN ('OPEN','PENDING_ENTRY')
   AND profit_pct IS NOT NULL ORDER BY created_at"""))
allts=[r[0] for r in c.execute("SELECT strftime('%s',created_at) FROM simulated_trades WHERE created_at>='2026-07-20'")]
c.close()
allts=sorted(int(t) for t in allts if t)
print(f"\nсделок сливающих: {len(rows)} · всего сделок в окне для кластера: {len(allts)}\n")
import bisect
for src in SRC:
    sub=[r for r in rows if r[2]==src]
    if not sub: continue
    print(f"═══ {src} (n={len(sub)}) ═══")
    stat("ВСЕ",[r[4] for r in sub])
    byc=defaultdict(list); byac=defaultdict(list); byreg=defaultdict(list); bysess=defaultdict(list)
    for r in sub:
        ts=int(dt.datetime.fromisoformat(r[3]).timestamp()); ms=ts*1000
        # кластер: сколько сделок ЛЮБОГО источника в ±15 мин
        lo=bisect.bisect_left(allts,ts-900); hi=bisect.bisect_right(allts,ts+900)
        n=hi-lo
        byc["одиночная (1)" if n<=1 else ("малый кластер 2-3" if n<=3 else "залив ≥4")].append(r[4])
        # AC-режим
        idx=acdf["time"].searchsorted(ms)-1
        if 0<=idx<len(acdf):
            v=acdf["v"].iloc[idx]
            byac["импульсный" if v>=AC_HI else ("возвратный" if v<=AC_LO else "середина")].append(r[4])
        try: f=json.loads(r[5] or "{}")
        except Exception: f={}
        byreg[str(f.get("regime"))].append(r[4]); bysess[str(f.get("session"))].append(r[4])
    print("   ── по КЛАСТЕРУ (восстановлено) ──")
    for k in ("одиночная (1)","малый кластер 2-3","залив ≥4"): stat(k,byc.get(k,[]))
    print("   ── по AC-РЕЖИМУ (восстановлено) ──")
    for k in ("импульсный","середина","возвратный"): stat(k,byac.get(k,[]))
    print("   ── по режиму (записан) ──")
    for k,v in sorted(byreg.items(),key=lambda x:-len(x[1]))[:4]: stat(k,v)
    print("   ── по сессии (записана) ──")
    for k,v in sorted(bysess.items(),key=lambda x:-len(x[1]))[:4]: stat(k,v)
    print()
