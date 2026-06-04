import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
from core.smc.smc_engine import ote_retest_setups
ex=ccxt.bingx({'enableRateLimit':True})
FIBS=[0.0,-0.27,-0.618,-1.0,-1.618]
def sim_fib(df,s):
    # до какого отрицательного фибо доходит до SL; R при каждом
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(s['entry_ts'])
    if ei is None: return None
    e=s['entry']; sl=s['sl']; risk=s['risk']; d=s['direction']
    rng=abs(s['from'][1]-s['to'][1]); end=s['to'][1]  # 0 уровень = конец импульса
    lo=df['low'].values; hi=df['high'].values; n=len(df)
    # цели по фибо (за end в сторону движения)
    if d=='short':
        tgts=[end-(-k)*rng for k in FIBS]  # end - |k|*rng (вниз)
    else:
        tgts=[end+(-k)*rng for k in FIBS]  # end + |k|*rng (вверх)
    reached=-1
    for j in range(ei+1,n):
        if d=='short':
            if hi[j]>=sl: break
            for idx in range(len(FIBS)-1,-1,-1):
                if lo[j]<=tgts[idx]: reached=max(reached,idx); break
        else:
            if lo[j]<=sl: break
            for idx in range(len(FIBS)-1,-1,-1):
                if hi[j]>=tgts[idx]: reached=max(reached,idx); break
    return reached  # индекс макс достигнутого фибо (-1=SL до 0)
syms=['BTC','ETH','SOL','GRT','XLM','DOGE','LINK','AVAX','ADA','DOT']
counts={i:0 for i in range(-1,len(FIBS))}
for sym in syms:
    try: o=ex.fetch_ohlcv(sym+'/USDT:USDT','1h',limit=500)
    except Exception: continue
    df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
    for s in ote_retest_setups(df, only_choch=False):
        r=sim_fib(df,s)
        if r is not None: counts[r]+=1
tot=sum(counts.values())
print(f'Распределение МАКС достигнутого фибо-уровня (n={tot}):')
print(f'  SL до TP1: {counts[-1]} ({counts[-1]/tot*100:.0f}%)')
for i,k in enumerate(FIBS):
    print(f'  дошло до {k:>+.3f}: {counts[i]} ({counts[i]/tot*100:.0f}%) [накопит. достигли {k}: {sum(counts[j] for j in range(i,len(FIBS)))}/{tot}]')
