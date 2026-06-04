import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, glob, os, time
from core.smc.smc_engine import ote_retest_setups
ERA='2026-04-15'
def sim_tp1(df,s):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(s['entry_ts'])
    if ei is None: return None
    e=s['entry']; sl=s['sl']; risk=s['risk']; d=s['direction']; tp=s['to'][1]
    lo=df['low'].values; hi=df['high'].values; n=len(df)
    if d=='long':
        if tp<=e: return None
        for j in range(ei+1,n):
            if lo[j]<=sl: return -1.0
            if hi[j]>=tp: return (tp-e)/risk
    else:
        if tp>=e: return None
        for j in range(ei+1,n):
            if hi[j]>=sl: return -1.0
            if lo[j]<=tp: return (e-tp)/risk
    return None
rows=[]
t0=time.time()
for tf in ['1h','15m']:
    files=sorted(glob.glob(f'data/history/{tf}/*.parquet'))
    for k,path in enumerate(files):
        sym=os.path.basename(path).replace('.parquet','')
        df=pd.read_parquet(path)
        if not isinstance(df.index,pd.DatetimeIndex): continue
        for s in ote_retest_setups(df, only_choch=False):
            r=sim_tp1(df,s)
            if r is not None:
                rows.append((tf,sym,str(s['entry_ts']),s['direction'],r))
    # 4h resample из 1h
    if tf=='1h':
        for path in files:
            sym=os.path.basename(path).replace('.parquet','')
            d1=pd.read_parquet(path)
            d4=d1.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
            for s in ote_retest_setups(d4, only_choch=False):
                r=sim_tp1(d4,s)
                if r is not None: rows.append(('4h',sym,str(s['entry_ts']),s['direction'],r))
    print(f'{tf} done, rows={len(rows)}, {time.time()-t0:.0f}s', flush=True)
R=pd.DataFrame(rows,columns=['tf','sym','entry_ts','dir','r'])
R['entry_ts']=pd.to_datetime(R['entry_ts'],utc=True)
R['era']=np.where(R['entry_ts']>=pd.Timestamp(ERA,tz='UTC'),'POST','PRE')
R.to_csv('e:/tmp/ote_backtest.csv',index=False)
def st(d):
    if not len(d): return 'n=0'
    r=d['r'].values; return f"n={len(r):>5} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} Sharpe={r.mean()/(r.std()+1e-9):.2f}"
print('\n=== OTE-Retest BASELINE (голый вход + TP1=0) ===')
print('ВСЕГО :', st(R))
print('\n-- по ТФ --')
for tf in ['15m','1h','4h']: print(f'  {tf:>4}:', st(R[R.tf==tf]))
print('\n-- data-era (граница 15.04.2026) --')
for era in ['PRE','POST']: print(f'  {era:>4}:', st(R[R.era==era]))
print('\n-- direction (POST era) --')
post=R[R.era=='POST']
for d in ['long','short']: print(f'  {d:>5}:', st(post[post.dir==d]))
