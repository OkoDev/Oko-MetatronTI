# -*- coding: utf-8 -*-
"""РАЗРЕШЕНИЕ ТЕНЕВЫХ СЕТАПОВ atr_s2 (04.08, вопрос Егора «странно что atr_s2 не сработал»).
2002 сетапа записаны живьём 03.07→04.08 БЕЗ торговли: survivorship-free, без look-ahead.
Резолвим по факту: что случилось раньше — цель S2 или стоп swing12. Косты 0.25% на круг.
Это честный форвард эджа, который бэктест оценивал в +0.471%/сделку (2022-26, 4/5 лет)."""
import json, sys, time, urllib.request, numpy as np
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
COST=0.25; TTL_H=240      # 10 дней на исход
rows=[]
for ln in open("logs/atr_s2_shadow.jsonl",encoding="utf-8"):
    try: rows.append(json.loads(ln))
    except Exception: pass
bysym=defaultdict(list)
for r in rows: bysym[r["symbol"]].append(r)
print(f"сетапов {len(rows)} по {len(bysym)} монетам · тяну 1h-историю...")
def klines(base):
    for attempt in (1,2):
        try:
            u=f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT&interval=1h&limit=1000"
            d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"oko"}),timeout=12)).get("data",[])
            return [(int(k["time"]),float(k["high"]),float(k["low"])) for k in reversed(d)]
        except Exception:
            time.sleep(0.4)
    return []
res=[]; skipped=0; nodata=0
for i,(sym,setups) in enumerate(bysym.items()):
    base=sym.split("/")[0]
    kl=klines(base)
    if len(kl)<100: nodata+=len(setups); continue
    times=[k[0] for k in kl]
    for s in setups:
        ts=s["ts"]; j0=np.searchsorted(times,ts)
        if j0>=len(kl)-2: skipped+=1; continue
        e=s["entry"]; sl=s["sl"]; tp=s["s2"]
        if not (sl>e>tp): skipped+=1; continue        # SHORT: SL выше входа, цель ниже
        out=None
        for j in range(j0,min(j0+TTL_H,len(kl))):
            hi,lo=kl[j][1],kl[j][2]
            if hi>=sl: out=(e-sl)/e*100-COST; break   # стоп
            if lo<=tp: out=(e-tp)/e*100-COST; break   # цель S2
        if out is None: out=(e-kl[min(j0+TTL_H,len(kl)-1)][2])/e*100-COST  # по TTL, консервативно по low
        res.append((s,out))
    if (i+1)%40==0: print(f"  ...{i+1}/{len(bysym)} монет, разрешено {len(res)}")
r=np.array([x[1] for x in res])
print(f"\nразрешено {len(r)} · пропущено {skipped} · без данных {nodata}")
if len(r)>30:
    srt=np.sort(r); cut=max(1,len(r)//10)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    coins=defaultdict(list)
    for s,v in res: coins[s["symbol"]].append(v)
    pos=sum(1 for k,v in coins.items() if np.median(v)>0)
    print(f"\n═══ ЖИВОЙ ФОРВАРД atr_s2 (33 дня, косты {COST}%) ═══")
    print(f"  n={len(r)} WR={100*(r>0).mean():.0f}% медиана={np.median(r):+.3f}% средний={r.mean():+.3f}% "
          f"PF={pf:.2f}")
    print(f"  сумма={r.sum():+.0f}% безтоп10%={srt[:-cut].sum():+.0f}% монет в плюсе={pos}/{len(coins)}")
    print(f"  бэктест обещал: +0.471%/сделку (2022-26)")
    # разрез по риску сетапа
    print("\n  ── по дистанции стопа ──")
    for lbl,f in (("стоп<4%",lambda s:s["risk_pct"]<4),("стоп 4-8%",lambda s:4<=s["risk_pct"]<8),("стоп>8%",lambda s:s["risk_pct"]>=8)):
        sub=np.array([v for s,v in res if f(s)])
        if len(sub)>20:
            p=(sub[sub>0].sum()/abs(sub[sub<0].sum())) if (sub<0).any() else 9.9
            print(f"    {lbl:12} n={len(sub):4} WR={100*(sub>0).mean():3.0f}% мед={np.median(sub):+7.3f}% ср={sub.mean():+7.3f}% PF={p:.2f}")
