import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
from core.smc.smc_engine import ote_retest_setups
ex=ccxt.bingx({'enableRateLimit':True})
def sim(df, s, rr=3.0):
    pos={ts:i for i,ts in enumerate(df.index)}
    ei=pos.get(s['entry_ts']);
    if ei is None: return None
    e=s['entry']; sl=s['sl']; risk=s['risk']; d=s['direction']
    lo=df['low'].values; hi=df['high'].values; n=len(df)
    if d=='long':
        tp=e+rr*risk
        for j in range(ei+1,n):
            if lo[j]<=sl: return -1.0
            if hi[j]>=tp: return rr
    else:
        tp=e-rr*risk
        for j in range(ei+1,n):
            if hi[j]>=sl: return -1.0
            if lo[j]<=tp: return rr
    return None
syms=['BTC','ETH','SOL','GRT','XLM','DOGE','LINK','AVAX','ADA','DOT']
allR=[]; byd={'long':[],'short':[]}
for sym in syms:
    try: o=ex.fetch_ohlcv(sym+'/USDT:USDT','1h',limit=500)
    except Exception: continue
    df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
    for s in ote_retest_setups(df, only_choch=False):
        r=sim(df,s,3.0)
        if r is not None: allR.append(r); byd[s['direction']].append(r)
def stat(rs):
    if not rs: return 'n=0'
    rs=np.array(rs); return f'n={len(rs)} avgR={rs.mean():+.3f} WR={(rs>0).mean()*100:.0f}% sumR={rs.sum():+.1f}'
print('=== OTE-Retest Engine бэктест (фикс RR 1:3, 10 монет 1h) ===')
print('ВСЕГО :', stat(allR))
print('LONG  :', stat(byd['long']))
print('SHORT :', stat(byd['short']))
