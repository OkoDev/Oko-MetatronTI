# -*- coding: utf-8 -*-
"""STRESS rangefade_L (эффективно): индикаторы раз/монету, 3 TP за проход, агрегация дёшево."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"
def load(sym,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",c,params=(sym,t0)); c.close(); return df
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0)
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
TPRS=[0.8,1.0,1.5]
def sim_multi(i,H,L,C,sl,tps,ttl=24):
    e=C[i]; end=min(i+ttl,len(C)-1); res=[None]*len(tps)
    for j in range(i+1,end+1):
        if L[j]<=sl:
            for k in range(len(tps)):
                if res[k] is None: res[k]=(sl-e)/e*100
            break
        for k,tp in enumerate(tps):
            if res[k] is None and H[j]>=tp: res[k]=(tp-e)/e*100
        if all(x is not None for x in res): break
    for k in range(len(tps)):
        if res[k] is None: res[k]=(C[end]-e)/e*100
    return res

# 🔴 136.E (01.09.2026): два дефекта выборки, оба запрещены протоколом вердикта —
#   1) t0=2024-01-01 копировалось вслепую и прятало 2023 (единственный бычий год);
#   2) `ORDER BY n DESC LIMIT 90` = монеты с длинной историей, то есть ВЫЖИВШИЕ.
# Оба лечатся флагами; поведение по умолчанию НЕ меняется, чтобы старые числа
# оставались воспроизводимыми.
import argparse as _ap
_a=_ap.ArgumentParser(); _a.add_argument("--core",action="store_true"); _a.add_argument("--since",type=int,default=2024)
_a=_a.parse_args()
t0=int(dt.datetime(_a.since,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
if _a.core:
    from scripts.research_harness import core_universe
    syms=core_universe("1h",since=f"{_a.since}-01-01",until="2026-06-01")
    print(f"ВСЕЛЕННАЯ: ЯДРО {len(syms)} монет (балансированная панель) · окно с {_a.since}")
else:
    c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 90",(t0,)).fetchall()]; c.close()
    print(f"ВСЕЛЕННАЯ: {len(syms)} монет по длине истории (НЕ балансировано) · окно с {_a.since}")
rows=[]  # (sym,year,wt, r08,r10,r15)
for sym in syms:
    d=load(sym,t0)
    if len(d)<800: continue
    d=d.reset_index(drop=True); w=wt(d).values; at=atrt(d)
    H=d.high.values; L=d.low.values; C=d.close.values; yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    for i in range(60,len(d)-1):
        if at[i]>0 and w[i]<-50:  # широкий порог, фильтруем потом
            sl=L[i-3:i+1].min()*0.997; e=C[i]
            tps=[e+R*(e-sl) for R in TPRS]
            r=sim_multi(i,H,L,C,sl,tps)
            # 🔴 136.E: добавлены ts и stop% — без них не посчитать обязательные срезы
            # протокола (кластер по дню, корзины стопа). Индексы 0-5 не сдвинуты.
            rows.append((sym,int(yr[i]),float(w[i]),r[0],r[1],r[2],int(d.time.values[i]),(e-sl)/e*100))
print(f"собрано входов (WT<-50, at>0): {len(rows)} на {len(syms)} монетах")
def agg(rs,col,cost):
    r=np.array([x[col]-cost for x in rs])
    if len(r)<20: return f"n={len(r)} мало"
    srt=np.sort(r); frag=srt[:-3].sum()
    return f"n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{np.median(r):+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп3{frag:+.0f}%"
C10=3  # индекс r10 в кортеже (r08=3,r10=4,r15=5)
print("\n=== КОСТ-ЧУВСТВИТЕЛЬНОСТЬ (WT<-60, TP1R) ===")
sub=[x for x in rows if x[2]<-60]
for cost in (0.10,0.15,0.20,0.25): print(f"  косты {cost}%: {agg(sub,4,cost)}")
print("\n=== ПО ГОДАМ (WT<-60 TP1R косты0.15) ===")
for y in (2024,2025,2026): print(f"  {y}: {agg([x for x in sub if x[1]==y],4,0.15)}")
print("\n=== ПАРАМ-РОБАСТНОСТЬ (косты0.15) ===")
for thr in (-50,-60,-70):
    s=[x for x in rows if x[2]<thr]
    print(f"  WT<{thr}: TP0.8 {agg(s,3,0.15)[:38]} | TP1.0 {agg(s,4,0.15)[:38]} | TP1.5 {agg(s,5,0.15)[:38]}")
print("\n=== PER-COIN (WT<-60 TP1R косты0.15) ===")
from collections import defaultdict
bc=defaultdict(list)
for x in sub: bc[x[0]].append(x[4]-0.15)
good=[(s,np.median(v),len(v)) for s,v in bc.items() if len(v)>=15]
pos=sum(1 for _,m,_ in good if m>0)
print(f"  монет n≥15: {len(good)} · плюс-медиана: {pos} ({100*pos/max(len(good),1):.0f}%)")
print("  топ-5 монет:", sorted([(s,round(m,2)) for s,m,_ in good],key=lambda x:-x[1])[:5])

# ── 🔴 136.E (01.09.2026): ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ ПРОТОКОЛА ВЕРДИКТА ─────────────
# Раньше печатались только косты/годы/пер-коин. Протокол требует ещё размер сетапа,
# кластер и ХРУПКОСТЬ по сделкам — без них вердикт по общей строке запрещён.
COST=0.25   # боевые косты лимитного входа ближе к 0.35; 0.25 — верх старого свипа
def _stat(rs,col=4,cost=COST):
    if len(rs)<30: return None
    n=np.array([x[col]-cost for x in rs]); w=n[n>0]; gl=-n[n<=0].sum(); srt=np.sort(n)[::-1]
    return dict(n=len(n),wr=100*(n>0).mean(),pf=(w.sum()/gl if gl else 0.0),
                avg=n.mean(),med=np.median(n),bt=srt[int(len(srt)*0.1):].sum())
def _line(nm,rs):
    s_=_stat(rs)
    if not s_: print(f"  {nm:<24} n={len(rs)} — мало"); return
    print(f"  {nm:<24} n={s_['n']:>6} WR {s_['wr']:>4.1f}% PF {s_['pf']:>5.2f} "
          f"ср {s_['avg']:>+6.3f}% мед {s_['med']:>+6.3f}% безтоп10% {s_['bt']:>+8.0f}")
print(f"\n{'='*98}\nОБЯЗАТЕЛЬНЫЕ СРЕЗЫ · WT<-60 TP1R · косты {COST}%\n{'='*98}")
_line("ВСЁ",sub)
print("\nРАЗМЕР СТОПА:")
for lo,hi in ((0,2),(2,4),(4,7),(7,100)):
    _line(f"  стоп {lo}-{hi}%",[x for x in sub if lo<=x[7]<hi])
print("\nКЛАСТЕР (≥2 монеты в один день):")
_day=defaultdict(set)
for x in sub: _day[pd.Timestamp(x[6],unit="ms").date()].add(x[0])
_line("  одиночка",[x for x in sub if len(_day[pd.Timestamp(x[6],unit='ms').date()])<2])
_line("  кластер ≥2",[x for x in sub if len(_day[pd.Timestamp(x[6],unit='ms').date()])>=2])
print("\nПО ГОДАМ (все, что есть в окне):")
for y in sorted({x[1] for x in sub}):
    _line(f"  {y}",[x for x in sub if x[1]==y])
print("\nОХВАТ МОНЕТ ПО СУММЕ:")
_per=defaultdict(float)
for x in sub: _per[x[0]]+=x[4]-COST
_v=sorted(_per.values(),reverse=True)
print(f"  монет {len(_v)} · в плюсе {sum(1 for v in _v if v>0)} "
      f"({100*sum(1 for v in _v if v>0)/max(len(_v),1):.0f}%) · сумма {sum(_v):+.0f}% · "
      f"без топ-3 {sum(_v[3:]):+.0f}% · без топ-10% {sum(_v[int(len(_v)*0.1):]):+.0f}%")

# ── 🔴🔴 БОЕВАЯ КОНФИГУРАЦИЯ (закон «сначала воспроизвести бой», 01.09.2026) ──
# Срезы выше считались на WT<-60 БЕЗ гейтов — это НЕ то, что торгует.
# config.yaml → trading.rangefade: wt_threshold -70 (1h) · max_stop_pct 4.0 ·
# min_cluster 2 · hybrid_exit (TP1R + раннер 5R под TSL) · оборот ≥$2M.
# Здесь воспроизводим то, что воспроизводимо на этих данных: порог, потолок, кластер.
print(f"\n{'='*98}\nБОЕВАЯ КОНФИГУРАЦИЯ rangefade 1h: WT<-70 · стоп≤4% · кластер≥2 · TP1R\n{'='*98}")
_live=[x for x in rows if x[2]<-70]
_dl=defaultdict(set)
for x in _live: _dl[pd.Timestamp(x[6],unit="ms").date()].add(x[0])
_line("WT<-70 (всё)",_live)
_line("  + стоп ≤4%",[x for x in _live if x[7]<=4.0])
_line("  + кластер ≥2",[x for x in _live if len(_dl[pd.Timestamp(x[6],unit='ms').date()])>=2])
_full=[x for x in _live if x[7]<=4.0 and len(_dl[pd.Timestamp(x[6],unit='ms').date()])>=2]
_line("  БОЕВАЯ (всё вместе)",_full)
print("\n  БОЕВАЯ по годам:")
for y in sorted({x[1] for x in _full}):
    _line(f"    {y}",[x for x in _full if x[1]==y])
if _full:
    _pf=defaultdict(float)
    for x in _full: _pf[x[0]]+=x[4]-COST
    _vf=sorted(_pf.values(),reverse=True)
    print(f"\n  БОЕВАЯ охват: монет {len(_vf)} · в плюсе {sum(1 for v in _vf if v>0)} "
          f"({100*sum(1 for v in _vf if v>0)/max(len(_vf),1):.0f}%) · сумма {sum(_vf):+.0f}% · "
          f"без топ-10% {sum(_vf[int(len(_vf)*0.1):]):+.0f}%")
print("\n  🔑 НЕ воспроизведено: гибридный выход (раннер 5R под TSL) и фильтр оборота $2M —")
print("     на этих данных их нет. Реальный боевой результат может отличаться в ЛУЧШУЮ сторону.")

# ── 🔴 ПОТОЛОК СТОПА: режет катастрофы или режет ЭДЖ? (01.09.2026) ───────────
# Потолок 4.0 выбран 13.08 по n=56 БОЕВЫМ сделкам после катастроф на неликвиде
# (CATE 48.6%, GPUBSC 29.4%). Вопрос: эдж больших стопов — это неликвид (тогда
# потолок оправдан и дублирует фильтр оборота) или он ШИРОКИЙ по монетам?
print(f"\n{'='*98}\nПОТОЛОК СТОПА на боевом пороге WT<-70: что именно он режет\n{'='*98}")
for lo,hi in ((0,2),(2,4),(4,7),(7,12),(12,20),(20,100)):
    _b=[x for x in _live if lo<=x[7]<hi]
    _line(f"  стоп {lo}-{hi}%",_b)
    if len(_b)>=30:
        _p=defaultdict(float)
        for x in _b: _p[x[0]]+=x[4]-COST
        _vv=sorted(_p.values(),reverse=True)
        print(f"      монет {len(_vv)} · в плюсе {sum(1 for v in _vv if v>0)} "
              f"({100*sum(1 for v in _vv if v>0)/max(len(_vv),1):.0f}%) · "
              f"без топ-10% {sum(_vv[int(len(_vv)*0.1):]):+.0f}%")
print("\n  Если 'в плюсе' высок И безтоп10% положителен в крупных корзинах —")
print("  потолок режет ЭДЖ, а не катастрофы, и лечить неликвид надо оборотом.")
