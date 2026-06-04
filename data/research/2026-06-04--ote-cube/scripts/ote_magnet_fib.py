import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
from core.smc.smc_engine import ote_retest_setups, detect_equal_levels, detect_fvg
ex=ccxt.bingx({'enableRateLimit':True})
FIBS=[0.0,-0.27,-0.618,-1.0]
syms=['BTC','ETH','SOL','GRT','XLM','DOGE','LINK','AVAX','ADA','DOT']
# для каждого фибо-уровня цели: есть ли EQL/FVG рядом (±0.5%) = магнит подтверждает
mag_hit={k:{'total':0,'with_magnet':0} for k in FIBS}
for sym in syms:
    try: o=ex.fetch_ohlcv(sym+'/USDT:USDT','1h',limit=500)
    except Exception: continue
    df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
    eqs=detect_equal_levels(df); fvgs=detect_fvg(df)
    eql_prices=[(l[1]+l[3])/2 for l in eqs if l[4]=='EQL']
    eqh_prices=[(l[1]+l[3])/2 for l in eqs if l[4]=='EQH']
    bull_fvg=[(min(f[1],f[2])+max(f[1],f[2]))/2 for f in fvgs if f[3]=='bull']
    bear_fvg=[(min(f[1],f[2])+max(f[1],f[2]))/2 for f in fvgs if f[3]=='bear']
    for s in ote_retest_setups(df, only_choch=False):
        rng=abs(s['from'][1]-s['to'][1]); end=s['to'][1]; d=s['direction']
        # магниты в сторону цели: short→EQL+bull_fvg (снизу), long→EQH+bear_fvg (сверху)
        magnets=(eql_prices+bull_fvg) if d=='short' else (eqh_prices+bear_fvg)
        for k in FIBS:
            tgt=end-(-k)*rng if d=='short' else end+(-k)*rng
            mag_hit[k]['total']+=1
            if any(abs(m-tgt)/tgt<=0.005 for m in magnets if tgt): mag_hit[k]['with_magnet']+=1
print('Фибо-уровень цели × есть ли EQL/FVG магнит рядом (±0.5%):')
for k in FIBS:
    t=mag_hit[k]['total']; w=mag_hit[k]['with_magnet']
    print(f'  {k:>+.3f}: магнит у {w}/{t} ({w/t*100:.0f}%) целей')
