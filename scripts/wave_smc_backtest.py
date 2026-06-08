import sys; sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
import sys; sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse, detect_structure_breaks, _zz_typed
ex=ccxt.bingx()

def setup_at(dfh):
    """Сетап на ИСТОРИИ dfh (только прошлое). → (side, sl_price, mode) или None."""
    price=dfh['close'].iloc[-1]
    li=None
    for dev in (3.0,5.0):
        for imp in detect_elliott_impulse(zigzag_atr(dfh,11,dev)):
            if li is None or imp['waves'][-1][0]>li['waves'][-1][0]: li=imp
    if not li: return None
    d=li['direction']; w5=li['waves'][-1][1]; w0=li['waves'][0][1]
    b=(price-w5)/(w0-w5)*100 if d=='down' and w0!=w5 else (w5-price)/(w5-w0)*100 if w5!=w0 else 0
    zz=zigzag_atr(dfh,11,3.0); typed=_zz_typed(zz)
    lows=[p for _,p,t in typed if t=='L']; highs=[p for _,p,t in typed if t=='H']
    brks=detect_structure_breaks(dfh,length=5)
    bos=[x for x in brks if x.kind=='BOS']; choch=[x for x in brks if x.kind=='CHoCH']
    n=len(dfh)
    if b<38:  # ТРЕНД
        lb=[x for x in bos if (x.direction=='bear')==(d=='down')]
        if lb and (n-1-lb[-1].idx)<=30:
            if d=='down' and highs: return ('SHORT',highs[-1],'TREND')
            if d=='up' and lows: return ('LONG',lows[-1],'TREND')
    else:  # РАЗВОРОТ
        cc=[x for x in choch if (x.direction=='bull')==(d=='down')]
        if cc and (n-1-cc[-1].idx)<=25:
            rt=abs(price-cc[-1].price)/cc[-1].price*100
            if rt<3:
                if d=='down' and lows: return ('LONG',lows[-1],'REVERSAL')
                if d=='up' and highs: return ('SHORT',highs[-1],'REVERSAL')
    return None

def fwd(df,i,side,sl,rr=2.0,horizon=40):
    """Форвард-симуляция от бара i. → R."""
    entry=df['close'].iloc[i]; risk=abs(entry-sl)
    if risk<=0 or risk/entry>0.15: return None  # фильтр битых SL
    tp=entry+rr*risk if side=='LONG' else entry-rr*risk
    for j in range(i+1,min(i+horizon,len(df))):
        hi=df['high'].iloc[j]; lo=df['low'].iloc[j]
        if side=='LONG':
            if lo<=sl: return -1.0
            if hi>=tp: return rr
        else:
            if hi>=sl: return -1.0
            if lo<=tp: return rr
    # закрытие по концу горизонта
    last=df['close'].iloc[min(i+horizon-1,len(df)-1)]
    return ((last-entry)if side=='LONG' else(entry-last))/risk

from collections import defaultdict
res=defaultdict(list)
for sym in ['BTC','ETH','SOL','XRP','BNB','ADA','LINK','AVAX']:
    for tf,lim in [('4h',700),('1h',900)]:
        try:
            o=ex.fetch_ohlcv(f'{sym}/USDT:USDT',tf,limit=lim)
            df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
        except: continue
        for i in range(250,len(df)-41,2):
            s=setup_at(df.iloc[:i+1])
            if s:
                side,sl,mode=s
                r=fwd(df,i,side,sl)
                if r is not None: res[mode].append(r); res[f'{mode}_{side}'].append(r)
print("=== БЭКТЕСТ связки Волна+SMC (walk-forward, RR2, horizon40) ===\n")
for k in ['TREND','TREND_LONG','TREND_SHORT','REVERSAL','REVERSAL_LONG','REVERSAL_SHORT']:
    v=res.get(k,[])
    if v:
        n=len(v); avg=sum(v)/n; wr=sum(1 for x in v if x>0)/n*100
        print(f"  {k:16} n={n:4d} avgR={avg:+.3f} WR={wr:.0f}% NET={sum(v):+.0f}R")
