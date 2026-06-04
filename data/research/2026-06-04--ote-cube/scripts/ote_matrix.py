import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
DUR={'1d':1440,'4h':240,'1h':60,'15m':15,'5m':5}  # минут/бар
RULE='pandas'
def load_raw(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def resample(d,rule):
    return pd.DataFrame({'open':d['open'].resample(rule).first(),'high':d['high'].resample(rule).max(),
        'low':d['low'].resample(rule).min(),'close':d['close'].resample(rule).last()}).dropna()
def get_df(tf,sym):
    if tf in ('5m','15m','1h'):
        d=load_raw(tf,sym)
        return d.tail(120000) if d is not None else None
    base=load_raw('1h',sym)
    if base is None: return None
    return resample(base,{'4h':'4h','1d':'1D'}[tf])
def sim_partial(df,ets,entry,sl,htf_tp,d):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(ets)
    if ei is None: return None
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    if d=='long' and htf_tp<=entry: return None
    if d=='short' and htf_tp>=entry: return None
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1:
                    phase=2
                    if hi[j]>=htf_tp: return 0.5 + 0.5*((htf_tp-entry)/risk)
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=htf_tp: return 0.5 + 0.5*((htf_tp-entry)/risk)
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1:
                    phase=2
                    if lo[j]<=htf_tp: return 0.5 + 0.5*((entry-htf_tp)/risk)
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=htf_tp: return 0.5 + 0.5*((entry-htf_tp)/risk)
    return 0.5 if phase==2 else None

PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','DOGEUSDT']
MATRIX={'1d':['4h','1h','15m','5m'],'4h':['4h','1h','15m','5m'],'1h':['1h','15m','5m']}
t0=time.time()
# кэш setups по (sym,tf) — считаем 1 раз
cache={}
need_tfs=set(['1d','4h','1h'])|{x for v in MATRIX.values() for x in v}
dfs={}
for sym in PAIRS:
    for tf in need_tfs:
        df=get_df(tf,sym)
        if df is None: continue
        dfs[(sym,tf)]=df
        cache[(sym,tf)]=ote_retest_setups(df,only_choch=False)
    print(f'cache {sym} {time.time()-t0:.0f}s',flush=True)

results={}
for htf,ltfs in MATRIX.items():
    for ltf in ltfs:
        win=pd.Timedelta(minutes=60*DUR[htf])
        rs=[]; risk_l=[]; risk_h=[]
        for sym in PAIRS:
            if (sym,htf) not in cache or (sym,ltf) not in cache: continue
            df_l=dfs[(sym,ltf)]
            hset=cache[(sym,htf)]; lset=[(s['entry_ts'],s) for s in cache[(sym,ltf)]]
            for h in hset:
                olo,ohi=h['ote']; tp=h['to'][1]; hd=h['direction']; tc=h['choch_ts']; te=tc+win
                for ts5,s5 in lset:
                    if ts5<tc or ts5>te or s5['direction']!=hd: continue
                    e5=s5['entry']
                    if not (olo<=e5<=ohi): continue
                    r=sim_partial(df_l,s5['entry_ts'],e5,s5['sl'],tp,hd)
                    if r is not None:
                        rs.append(r); risk_l.append(abs(e5-s5['sl'])); risk_h.append(abs(e5-h['sl']))
                    break
        if rs:
            r=np.array(rs)
            results[(htf,ltf)]=(len(r),r.mean(),(r>0).mean()*100,r.sum(),r.max(),
                                np.mean(risk_h)/(np.mean(risk_l)+1e-9))
        print(f'{htf}->{ltf} n={len(rs)} {time.time()-t0:.0f}s',flush=True)

print('\n=== МАТРИЦА ВЛОЖЕННОСТИ (частичный TP1=1R + runner до HTF target) ===')
print(f'{"HTF→LTF":<10}{"n":>5}{"avgR":>8}{"WR":>6}{"sumR":>7}{"maxR":>7}{"risk×":>7}')
for htf in ['1d','4h','1h']:
    for ltf in MATRIX[htf]:
        if (htf,ltf) in results:
            n,a,w,s,m,rx=results[(htf,ltf)]
            mark=' ★' if a>0.4 else ''
            print(f'{htf}→{ltf:<7}{n:>5}{a:>+8.3f}{w:>5.0f}%{s:>+7.0f}{m:>+7.1f}{rx:>6.1f}x{mark}')
