import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
from core.smc.smc_engine import ote_retest_setups
ex=ccxt.bingx({'enableRateLimit':True})
def sim_magnet(df, s):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(s['entry_ts'])
    if ei is None: return None
    e=s['entry']; sl=s['sl']; risk=s['risk']; d=s['direction']
    tp=s['to'][1]   # 0 уровень = конец импульса (дно short / вершина long) = предыдущий экстремум
    lo=df['low'].values; hi=df['high'].values; n=len(df)
    if d=='long':
        if tp<=e: return None  # цель должна быть выше входа
        for j in range(ei+1,n):
            if lo[j]<=sl: return -1.0
            if hi[j]>=tp: return (tp-e)/risk
    else:
        if tp>=e: return None
        for j in range(ei+1,n):
            if hi[j]>=sl: return -1.0
            if lo[j]<=tp: return (e-tp)/risk
    return None
def sim_fix(df,s,rr=3.0):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(s['entry_ts'])
    if ei is None: return None
    e=s['entry']; sl=s['sl']; risk=s['risk']; d=s['direction']; lo=df['low'].values; hi=df['high'].values; n=len(df)
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
mag={'long':[],'short':[]}; fix={'long':[],'short':[]}
for sym in syms:
    try: o=ex.fetch_ohlcv(sym+'/USDT:USDT','1h',limit=500)
    except Exception: continue
    df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
    for s in ote_retest_setups(df, only_choch=False):
        rm=sim_magnet(df,s); rf=sim_fix(df,s,3.0)
        if rm is not None: mag[s['direction']].append(rm)
        if rf is not None: fix[s['direction']].append(rf)
def st(rs):
    if not rs: return 'n=0'
    rs=np.array(rs); return f'n={len(rs):>3} avgR={rs.mean():+.3f} WR={(rs>0).mean()*100:>3.0f}% sumR={rs.sum():+.1f}'
print('=== TP1 = МАГНИТ (предыдущий экстремум) ===')
print('  ВСЕГО:', st(mag['long']+mag['short'])); print('  LONG :', st(mag['long'])); print('  SHORT:', st(mag['short']))
print('=== TP = фикс RR 1:3 (для сравнения) ===')
print('  ВСЕГО:', st(fix['long']+fix['short'])); print('  LONG :', st(fix['long'])); print('  SHORT:', st(fix['short']))
