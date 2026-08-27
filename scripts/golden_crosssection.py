# -*- coding: utf-8 -*-
"""КРОСС-СЕКЦИОННЫЙ КЛАСС (не пробовали ни разу) — ранжируем монеты ДРУГ ПРОТИВ ДРУГА.
DS/рой оба назвали CSM классом, который работает там, где фейд слаб. Проверяем 3 правила:
  A) CS-REVERSAL: лонг худших за N часов, шорт лучших (кросс-секционный возврат)
  B) CS-MOMENTUM: лонг лучших, шорт худших (кросс-секционный импульс)
  C) CS-FUNDING: лонг с самым НИЗКИМ funding (толпа в шортах), шорт с самым высоким
Портфель нейтральный (равные веса long/short), ребаланс = период удержания, косты 0.25% на ногу.
ПРИЧИННО: ранг по ЗАКРЫТЫМ барам, вход по следующему. Метрика: доходность портфеля за период."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; LEG_COST=0.25
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def rep(name,rets,per_year=None):
    r=np.array(rets)
    if len(r)<30: print(f"    {name:34} периодов={len(r)}"); return
    srt=np.sort(r); cut=max(1,len(r)//10); pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=np.median(r)>0.0 and srt[:-cut].sum()>0 and pf>1.05
    ys=""
    if per_year:
        ys=" | "+" ".join(f"{y}:{np.median(v):+.3f}" for y,v in sorted(per_year.items()) if len(v)>20)
    print(f"    {name:34} период={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{np.median(r):+.3f}% ср{r.mean():+.3f}% "
          f"PF{pf:.2f} сум{r.sum():+7.0f}% безтоп10%{srt[:-cut].sum():+7.0f}%{ys} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 120",(t0,)).fetchall()]; c.close()
px={}
for s in syms:
    d=load(s,"1h",t0)
    if len(d)>3000: px[s]=pd.Series(d.close.values,index=d.time.values)
panel=pd.DataFrame(px).sort_index().ffill(limit=3)
print(f"панель: {panel.shape[1]} монет × {panel.shape[0]} часов")
# funding-панель
fp={}
c=sqlite3.connect(DB)
for s in panel.columns:
    f=pd.read_sql("SELECT time,rate FROM funding_rates WHERE symbol=? AND time>=? ORDER BY time",c,params=(s,t0))
    if len(f)>100: fp[s]=pd.Series(f.rate.values,index=f.time.values)
c.close()
fund=pd.DataFrame(fp).reindex(panel.index,method="ffill")
print(f"funding-панель: {fund.shape[1]} монет\n")
yrs=pd.to_datetime(panel.index,unit="ms").year
for HOLD in (168,336,720):
    fwd=panel.shift(-HOLD)/panel-1.0        # будущая доходность за период удержания
    for LOOK,tag in ((HOLD,"look=hold"),):
        past=panel/panel.shift(LOOK)-1.0
        res={"A) CS-REVERSAL (лонг худших)":[],"B) CS-MOMENTUM (лонг лучших)":[],"C) CS-FUNDING (лонг низкий fund)":[]}
        yr_={k:{} for k in res}
        for i in range(LOOK+1,len(panel)-HOLD,HOLD):     # неперекрывающиеся периоды
            row_past=past.iloc[i].dropna(); row_fwd=fwd.iloc[i].dropna()
            common=row_past.index.intersection(row_fwd.index)
            if len(common)<40: continue
            rp=row_past[common]; rf_=row_fwd[common]; k=max(5,len(common)//10)   # дециль
            lo=rp.nsmallest(k).index; hi=rp.nlargest(k).index
            y=int(yrs[i])
            rev=(rf_[lo].mean()-rf_[hi].mean())*100-2*LEG_COST
            mom=(rf_[hi].mean()-rf_[lo].mean())*100-2*LEG_COST
            res["A) CS-REVERSAL (лонг худших)"].append(rev); yr_["A) CS-REVERSAL (лонг худших)"].setdefault(y,[]).append(rev)
            res["B) CS-MOMENTUM (лонг лучших)"].append(mom); yr_["B) CS-MOMENTUM (лонг лучших)"].setdefault(y,[]).append(mom)
            fr=fund.iloc[i].dropna(); cf=fr.index.intersection(common)
            if len(cf)>=40:
                frr=fr[cf]; kk=max(5,len(cf)//10)
                flo=frr.nsmallest(kk).index; fhi=frr.nlargest(kk).index
                v=(rf_[flo].mean()-rf_[fhi].mean())*100-2*LEG_COST
                res["C) CS-FUNDING (лонг низкий fund)"].append(v); yr_["C) CS-FUNDING (лонг низкий fund)"].setdefault(y,[]).append(v)
        print(f"  ═══ удержание {HOLD}ч, ранг по {LOOK}ч, децили, косты {2*LEG_COST}% на круг ═══")
        for k in res: rep(k,res[k],yr_[k])
        print()
