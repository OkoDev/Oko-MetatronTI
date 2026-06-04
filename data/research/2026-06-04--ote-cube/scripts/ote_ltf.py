import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, glob, os, time
from core.smc.smc_engine import ote_retest_setups
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
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','XLMUSDT','DOGEUSDT']
TAIL=20000
rows=[]; t0=time.time()
for tf in ['15m','5m']:
    for sym in PAIRS:
        p=f'data/history/{tf}/{sym}.parquet'
        if not os.path.exists(p): continue
        df=pd.read_parquet(p).tail(TAIL)
        if not isinstance(df.index,pd.DatetimeIndex): continue
        for s in ote_retest_setups(df, only_choch=False):
            r=sim_tp1(df,s)
            if r is not None: rows.append((tf,sym,str(s['entry_ts']),s['direction'],r))
    print(f'{tf} done rows={len(rows)} {time.time()-t0:.0f}s',flush=True)
R=pd.DataFrame(rows,columns=['tf','sym','entry_ts','dir','r'])
def st(d):
    if not len(d): return 'n=0'
    r=d['r'].values; return f"n={len(r):>5} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} Sharpe={r.mean()/(r.std()+1e-9):.2f}"
print('\n=== OTE-Retest LTF (15m+5m, 6 пар, tail 20K) ===')
print('ВСЕГО:', st(R))
print('-- по ТФ --'); [print(f'  {tf:>4}:', st(R[R.tf==tf])) for tf in ['15m','5m']]
print('-- направление --'); [print(f'  {d:>5}:', st(R[R.dir==d])) for d in ['long','short']]
