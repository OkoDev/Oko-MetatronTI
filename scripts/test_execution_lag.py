# -*- coding: utf-8 -*-
"""ИСПОЛНЕНИЕ (#3 в карте) — entry_price_lag_pct / entry_lag_seconds лежат в 100% сделок
и НЕ анализировались ни разу. Известный корень убытков: «91% живых входов хуже сигнала».
Вопрос: предсказывает ли задержка/сдвиг входа исход сделки? И где порог?"""
import sqlite3, json, sys, numpy as np
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
def rep(name,v):
    if len(v)<20: print(f"    {name:34} n={len(v)}"); return
    r=np.array(v); srt=np.sort(r); cut=max(1,len(r)//10)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    print(f"    {name:34} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{np.median(r):+7.3f}% ср{r.mean():+7.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+8.0f}%")
c=sqlite3.connect("subscriptions.db")
rows=list(c.execute("""SELECT signal_type,execution_mode,profit_pct,features_json,direction
   FROM simulated_trades WHERE status NOT IN ('OPEN','PENDING_ENTRY') AND profit_pct IS NOT NULL
   AND created_at>='2026-06-01'"""))
c.close()
print(f"сделок с 2026-06-01: {len(rows)}\n")
LAGP=defaultdict(list); LAGS=defaultdict(list); PRIO=defaultdict(list); RR=defaultdict(list); SLD=defaultdict(list)
ALL=[]; byvst=defaultdict(list)
for st,em,p,fj,d in rows:
    try: f=json.loads(fj or "{}")
    except Exception: f={}
    ALL.append(p); byvst[em].append(p)
    lp=f.get("entry_price_lag_pct"); ls=f.get("entry_lag_seconds")
    pr=f.get("entry_priority"); rr=f.get("rr_at_entry"); sd=f.get("distance_to_sl_pct")
    if isinstance(lp,(int,float)):
        k=("вход ЛУЧШЕ сигнала" if lp<-0.05 else ("вход ≈ сигнал (±0.05%)" if lp<=0.05 else
           ("хуже на 0.05-0.3%" if lp<=0.3 else ("хуже на 0.3-1%" if lp<=1.0 else "хуже >1%"))))
        LAGP[k].append(p)
    if isinstance(ls,(int,float)):
        k=("<30с" if ls<30 else ("30-120с" if ls<120 else ("2-10мин" if ls<600 else ">10мин")))
        LAGS[k].append(p)
    if pr is not None: PRIO[str(pr)].append(p)
    if isinstance(rr,(int,float)): RR[("RR<1" if rr<1 else ("RR 1-2" if rr<2 else "RR≥2"))].append(p)
    if isinstance(sd,(int,float)): SLD[("стоп<2%" if sd<2 else ("стоп 2-5%" if sd<5 else ("стоп 5-10%" if sd<10 else "стоп>10%")))].append(p)
print("═══ БАЗА ═══"); rep("все сделки",ALL)
for k,v in sorted(byvst.items(),key=lambda x:-len(x[1])): rep(f"  режим {k}",v)
print("\n═══ СДВИГ ВХОДА (entry_price_lag_pct) — корень убытков ═══")
for k in ("вход ЛУЧШЕ сигнала","вход ≈ сигнал (±0.05%)","хуже на 0.05-0.3%","хуже на 0.3-1%","хуже >1%"): rep(k,LAGP.get(k,[]))
print("\n═══ ЗАДЕРЖКА ВХОДА (entry_lag_seconds) ═══")
for k in ("<30с","30-120с","2-10мин",">10мин"): rep(k,LAGS.get(k,[]))
print("\n═══ ДИСТАНЦИЯ СТОПА (проверка закона «размер против костов») ═══")
for k in ("стоп<2%","стоп 2-5%","стоп 5-10%","стоп>10%"): rep(k,SLD.get(k,[]))
print("\n═══ RR НА ВХОДЕ ═══")
for k in ("RR<1","RR 1-2","RR≥2"): rep(k,RR.get(k,[]))
print("\n═══ entry_priority ═══")
for k,v in sorted(PRIO.items(),key=lambda x:-len(x[1]))[:5]: rep(f"priority={k}",v)
