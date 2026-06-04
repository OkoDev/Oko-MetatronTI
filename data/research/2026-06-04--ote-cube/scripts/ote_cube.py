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
    base=load_raw('1h',sym)
    return resample(base,{'4h':'4h','1d':'1D'}[tf]) if base is not None else None
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
CHAINS=[['1d','1h','15m'],['1d','4h','15m'],['4h','1h','15m'],['1d','4h','1h','15m'],['1d','1h','15m','5m']]
t0=time.time()
all_tfs=sorted({tf for c in CHAINS for tf in c},key=lambda x:DUR[x],reverse=True)
cache={}; dfs={}
for sym in PAIRS:
    for tf in all_tfs:
        df=get_df(tf,sym)
        if df is None: continue
        dfs[(sym,tf)]=df; cache[(sym,tf)]=[(s['entry_ts'],s) for s in ote_retest_setups(df,only_choch=False)]
    print(f'cache {sym} {time.time()-t0:.0f}s',flush=True)

def run_chain(chain):
    rs=[]; risk_l=[]; risk_r=[]
    for sym in PAIRS:
        if any((sym,tf) not in cache for tf in chain): continue
        df_entry=dfs[(sym,chain[-1])]
        roots=cache[(sym,chain[0])]
        def descend(level,parent_s,root_tp,root_sl):
            tf=chain[level]; win=pd.Timedelta(minutes=60*DUR[chain[level-1]])
            olo,ohi=parent_s['ote']; pdir=parent_s['direction']; tc=parent_s['choch_ts']; te=tc+win
            for ts,s in cache[(sym,tf)]:
                if ts<tc or ts>te or s['direction']!=pdir: continue
                if not (olo<=s['entry']<=ohi): continue
                if level==len(chain)-1:
                    r=sim_partial(df_entry,s['entry_ts'],s['entry'],s['sl'],root_tp,pdir)
                    if r is not None:
                        rs.append(r); risk_l.append(abs(s['entry']-s['sl'])); risk_r.append(abs(s['entry']-root_sl))
                    return True
                else:
                    if descend(level+1,s,root_tp,root_sl): return True
            return False
        for ts,rs0 in roots:
            descend(1,rs0,rs0['to'][1],rs0['sl'])
    if not rs: return None
    r=np.array(rs)
    return (len(r),r.mean(),(r>0).mean()*100,r.sum(),r.max(),np.mean(risk_r)/(np.mean(risk_l)+1e-9))

print('\n=== КУБ: КАСКАДНАЯ вложенность (зона⊃зона⊃вход), TP=корневой target ===')
print(f'{"цепочка":<22}{"n":>5}{"avgR":>8}{"WR":>6}{"sumR":>7}{"maxR":>7}{"risk×":>7}')
for ch in CHAINS:
    res=run_chain(ch)
    name='→'.join(ch)
    if res:
        n,a,w,s,m,rx=res
        mark=' ★' if a>0.5 else ''
        print(f'{name:<22}{n:>5}{a:>+8.3f}{w:>5.0f}%{s:>+7.0f}{m:>+7.1f}{rx:>6.1f}x{mark}')
    else:
        print(f'{name:<22}  n=0 (нет тройных совпадений)')
    print(f'  ({time.time()-t0:.0f}s)',flush=True)
