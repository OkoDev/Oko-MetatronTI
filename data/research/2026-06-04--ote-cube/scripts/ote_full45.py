import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, glob, time
from core.smc.smc_engine import ote_retest_setups
from tools.pattern_mining.combinator_v2 import rsi, _calc_divergence, DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS
DUR={'4h':240,'15m':15,'5m':5}; ERA=pd.Timestamp('2026-04-15')
def load_raw(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def get_df(tf,sym):
    if tf in ('5m','15m'):
        d=load_raw(tf,sym); return d.tail(120000) if d is not None else None
    base=load_raw('1h',sym)
    if base is None: return None
    return pd.DataFrame({'open':base['open'].resample('4h').first(),'high':base['high'].resample('4h').max(),
        'low':base['low'].resample('4h').min(),'close':base['close'].resample('4h').last()}).dropna()
def hidden(df,bull=True):
    c=df['close'].values; r=rsi(c,14)
    _,_,bh,beh=_calc_divergence(c,r,DIV_PIVOT_PRD,DIV_MAX_PP,DIV_MAX_BARS)
    return bh if bull else beh
def sim(df,ei,entry,sl,tp,d):
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    if (d=='long' and tp<=entry) or (d=='short' and tp>=entry): return None
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1: phase=2
                if phase==2 and hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1: phase=2
                if phase==2 and lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
    return 0.5 if phase==2 else None
PAIRS=sorted(os.path.basename(p).replace('.parquet','') for p in glob.glob('data/history/15m/*.parquet'))
t0=time.time(); res={}
def add(key,ts,dirn,r):
    t=ts.tz_localize(None) if getattr(ts,'tzinfo',None) is not None else ts
    era='POST' if t>=ERA else 'PRE'
    res.setdefault(key,[]).append((era,dirn,r))
for ci,sym in enumerate(PAIRS):
    dfh=get_df('4h',sym); df15=get_df('15m',sym); df5=get_df('5m',sym)
    if dfh is None: continue
    hbull=hidden(dfh,True); hbear=hidden(dfh,False); hts=dfh.index
    win=pd.Timedelta(minutes=60*DUR['4h']); hwin=pd.Timedelta(minutes=2.5*DUR['4h'])
    hset=ote_retest_setups(dfh,only_choch=False)
    if df15 is not None:
        l15=[(s['entry_ts'],s) for s in ote_retest_setups(df15,only_choch=False)]
        idx15={ts:k for k,ts in enumerate(df15.index)}
        for h in hset:
            olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win; tp=h['to'][1]
            hid=hbull if pdir=='long' else hbear
            hid_on=bool(hid[(hts<=te)&(hts>=tc-hwin)].any())
            for ts5,s5 in l15:
                if ts5<tc or ts5>te or s5['direction']!=pdir: continue
                if not (olo<=s5['entry']<=ohi): continue
                ei=idx15.get(s5['entry_ts'])
                if ei is None: continue
                r=sim(df15,ei,s5['entry'],s5['sl'],tp,pdir)
                if r is not None:
                    add('A_slom',ts5,pdir,r)
                    if hid_on: add('C_slom+hid',ts5,pdir,r)
                break
    if df5 is not None:
        l5=[(s['entry_ts'],s) for s in ote_retest_setups(df5,only_choch=False)]
        idx5={ts:k for k,ts in enumerate(df5.index)}
        for h in hset:
            olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win
            ote_mid=(olo+ohi)/2.0; opp='short' if pdir=='long' else 'long'
            for ts5,s5 in l5:
                if ts5<tc or ts5>te or s5['direction']!=opp: continue
                e=s5['entry']
                ok=(pdir=='long' and e>ohi) or (pdir=='short' and e<olo)
                if not ok: continue
                ei=idx5.get(s5['entry_ts'])
                if ei is None: continue
                r=sim(df5,ei,e,s5['sl'],ote_mid,opp)
                if r is not None: add('PULL_5m',ts5,opp,r)
                break
    print(f'[{ci+1}/{len(PAIRS)}] {sym} {time.time()-t0:.0f}s',flush=True)
def st(rows):
    if not rows: return 'n=0'
    r=np.array([x[2] for x in rows]); return f"n={len(r):>5} avgR={r.mean():+.3f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
def era(rows,e): return [x for x in rows if x[0]==e]
def dr(rows,d): return [x for x in rows if x[1]==d]
print('\n=== ФИНАЛ 45 пар: формула куба C + откат, data-era split (граница 15.04) ===')
for key,lbl in [('A_slom','A. 4h OTE->15m слом (baseline)'),('C_slom+hid','C. +hidden-ВАЛИДАТОР (формула)'),('PULL_5m','ОТКАТ 4h OTE->5m (контр-тренд)')]:
    rows=res.get(key,[])
    print(f'\n{lbl}:')
    print(f'  ВСЕ : {st(rows)}')
    print(f'  PRE : {st(era(rows,"PRE"))}')
    print(f'  POST: {st(era(rows,"POST"))}')
    print(f'  long: {st(dr(rows,"long"))} | short: {st(dr(rows,"short"))}')
