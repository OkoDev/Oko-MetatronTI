import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
from tools.pattern_mining.combinator_v2 import rsi, _calc_divergence
try:
    from tools.pattern_mining.combinator_v2 import DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS
except Exception:
    DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS = 5, 10, 100
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
HTF,LTF='4h','5m'; win=pd.Timedelta(minutes=60*DUR[HTF]); DIV_LB=10
t0=time.time()
res={'base':{'cont':[],'pull':[]},'div':{'cont':[],'pull':[]}}
for sym in PAIRS:
    dfh=get_df(HTF,sym); dfl=get_df(LTF,sym)
    if dfh is None or dfl is None: continue
    close=dfl['close'].values
    r=rsi(close,14)
    dbull,dbear,_,_=_calc_divergence(close, r, DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS)
    # recent-div окно: дивергенция в [i-DIV_LB, i]
    def div_ok(i,direction):
        a=max(0,i-DIV_LB)
        arr=dbull if direction=='long' else dbear
        return bool(arr[a:i+1].any())
    pos={ts:k for k,ts in enumerate(dfl.index)}
    hset=ote_retest_setups(dfh,only_choch=False)
    lset=[(s['entry_ts'],s) for s in ote_retest_setups(dfl,only_choch=False)]
    for h in hset:
        olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win
        tp_cont=h['to'][1]; ote_mid=(olo+ohi)/2.0; opp='short' if pdir=='long' else 'long'
        tc_b=tc_d=tp_b=tp_d=False
        for ts,s in lset:
            if ts<tc or ts>te: continue
            e=s['entry']; ei=pos.get(s['entry_ts'])
            if ei is None: continue
            # ПРОДОЛЖЕНИЕ
            if s['direction']==pdir and olo<=e<=ohi:
                rr=sim_partial(dfl,s['entry_ts'],e,s['sl'],tp_cont,pdir)
                if rr is not None:
                    if not tc_b: res['base']['cont'].append((pdir,rr)); tc_b=True
                    if not tc_d and div_ok(ei,pdir): res['div']['cont'].append((pdir,rr)); tc_d=True
            # ОТКАТ
            if s['direction']==opp:
                ok = (pdir=='long' and e>ohi) or (pdir=='short' and e<olo)
                if ok:
                    rr=sim_partial(dfl,s['entry_ts'],e,s['sl'],ote_mid,opp)
                    if rr is not None:
                        if not tp_b: res['base']['pull'].append((opp,rr)); tp_b=True
                        if not tp_d and div_ok(ei,opp): res['div']['pull'].append((opp,rr)); tp_d=True
        # (берём первые в каждой категории)
    print(f'{sym} base_c={len(res["base"]["cont"])} div_c={len(res["div"]["cont"])} {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not len(a): return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>4} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
print('\n=== 4h→5m: БЕЗ дивергенции vs С 5m RSI-дивергенцией ===')
for k,lbl in [('base','БЕЗ фильтра  '),('div','С 5m-div     ')]:
    c=res[k]['cont']; p=res[k]['pull']
    print(f'[{lbl}] ПРОДОЛЖ:',st(c))
    print(f'[{lbl}] ОТКАТ  :',st(p))
    print(f'[{lbl}] ОБЕ    :',st(c+p))
