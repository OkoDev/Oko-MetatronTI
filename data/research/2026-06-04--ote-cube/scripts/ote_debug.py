import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
from core.smc.smc_engine import zigzag_atr, find_setups_zz
ex=ccxt.bingx({'enableRateLimit':True})
o=ex.fetch_ohlcv('SOL/USDT:USDT','1h',limit=300)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
zz=zigzag_atr(df,11,3.0); setups=find_setups_zz(zz,df)
chochs=[s for s in setups if s.get('kind')=='CHoCH']
print(f'всего setups={len(setups)} CHoCH={len(chochs)}')
pos={ts:i for i,ts in enumerate(df.index)}
low=df['low'].values; high=df['high'].values; n=len(df)
for s in chochs[-5:]:
    ci=pos.get(s['choch_ts']); ote_lo,ote_hi=s['ote']
    print(f"\nCHoCH {s['direction']} @{str(s['choch_ts'])[5:16]} OTE={ote_lo:.3f}-{ote_hi:.3f} levels1.0={s['levels'][1.0]:.3f}")
    if ci is None: print('  ci None'); continue
    # цена после choch
    found=False
    for j in range(ci+1,min(ci+61,n)):
        if low[j]<=ote_hi and high[j]>=ote_lo:
            print(f'  РЕТЕСТ найден @bar+{j-ci} ({str(df.index[j])[5:16]}) low={low[j]:.3f} high={high[j]:.3f}'); found=True; break
    if not found:
        # показать диапазон цен после
        seg_lo=low[ci+1:min(ci+61,n)].min(); seg_hi=high[ci+1:min(ci+61,n)].max()
        print(f'  НЕТ ретеста за 60 баров. Цена после: {seg_lo:.3f}-{seg_hi:.3f} (OTE {ote_lo:.3f}-{ote_hi:.3f})')
