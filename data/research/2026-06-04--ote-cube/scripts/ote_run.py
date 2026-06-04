import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
from core.smc.swing_service import zigzag_atr, build_ote
from scripts.chart_verify import render_verify
ex=ccxt.bingx({'enableRateLimit':True})
o=ex.fetch_ohlcv('XLM/USDT:USDT','1m',limit=250)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
zz=zigzag_atr(df, depth=11, dev_mult=3.0)
# последний импульс = две последние ZigZag точки
a_ts,a=zz[-2]; b_ts,b=zz[-1]
ote=build_ote(a, b)
print(f'Последний импульс: {a:.5f} → {b:.5f} | direction={ote["direction"]}')
hl={f'{f}':p for f,p in ote['levels'].items()}
zones=[(ote['ote'][0], ote['ote'][1], '#ffd700', 'OTE 0.705-0.786')]
render_verify(df, f'XLM 1m — OTE/Fib от последнего импульса ({ote["direction"]})', zigzag=zz, hlines=hl, zones=zones, out='tmp_charts/xlm_ote.png')
