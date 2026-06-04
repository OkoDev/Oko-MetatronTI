import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
DUR={'1d':1440,'4h':240,'1h':60,'15m':15,'5m':5}
def load_raw(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def resample(d,r):
    return pd.DataFrame({'open':d['open'].resample(r).first(),'high':d['high'].resample(r).max(),
        'low':d['low'].resample(r).min(),'close':d['close'].resample(r).last()}).dropna()
def get_df(tf,sym):
    if tf in ('5m','15m','1h'):
        d=load_raw(tf,sym); return d.tail(120000) if d is not None else None
    base=load_raw('1h',sym); return resample(base,{'4h':'4h','1d':'1D'}[tf]) if base is not None else None
def sim_partial(df,ets,entry,sl,tp,d):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(ets)
    if ei is None: return None
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    if (d=='long' and tp<=entry) or (d=='short' and tp>=entry): return None
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1:
                    phase=2
                    if hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1:
                    phase=2
                    if lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
    return 0.5 if phase==2 else None

PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','DOGEUSDT']
HTF,LTF='4h','15m'; win=pd.Timedelta(minutes=60*DUR[HTF])
t0=time.time(); cont=[]; pull=[]
for sym in PAIRS:
    dfh=get_df(HTF,sym); dfl=get_df(LTF,sym)
    if dfh is None or dfl is None: continue
    hset=ote_retest_setups(dfh,only_choch=False)
    lset=[(s['entry_ts'],s) for s in ote_retest_setups(dfl,only_choch=False)]
    for h in hset:
        olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win
        tp_cont=h['to'][1]; ote_mid=(olo+ohi)/2.0
        opp='short' if pdir=='long' else 'long'
        took_c=took_p=False
        for ts,s in lset:
            if ts<tc or ts>te: continue
            e=s['entry']
            # ПРОДОЛЖЕНИЕ: ребёнок по тренду родителя, вход в OTE-зоне, TP=корневой target
            if (not took_c) and s['direction']==pdir and olo<=e<=ohi:
                r=sim_partial(dfl,s['entry_ts'],e,s['sl'],tp_cont,pdir)
                if r is not None: cont.append((pdir,r)); took_c=True
            # ОТКАТ: ребёнок ПРОТИВ тренда, вход ВНЕ зоны (цена ещё идёт к OTE), TP=OTE-зона
            if (not took_p) and s['direction']==opp:
                if pdir=='long' and e>ohi:    # bull-родитель: цена выше OTE, SHORT-откат вниз к зоне
                    r=sim_partial(dfl,s['entry_ts'],e,s['sl'],ote_mid,'short')
                    if r is not None: pull.append((opp,r)); took_p=True
                elif pdir=='short' and e<olo:  # bear-родитель: цена ниже OTE, LONG-откат вверх к зоне
                    r=sim_partial(dfl,s['entry_ts'],e,s['sl'],ote_mid,'long')
                    if r is not None: pull.append((opp,r)); took_p=True
            if took_c and took_p: break
    print(f'{sym} cont={len(cont)} pull={len(pull)} {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not len(a): return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>4} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
print('\n=== ДВУНАПРАВЛЕННЫЙ КУБ 4h→15m (обе стороны) ===')
print('ПРОДОЛЖЕНИЕ (по тренду, TP=4h target):', st(cont))
print('ОТКАТ      (контр-тренд, TP=4h OTE)   :', st(pull))
print('ОБЕ ВЕТКИ вместе                      :', st(cont+pull))
