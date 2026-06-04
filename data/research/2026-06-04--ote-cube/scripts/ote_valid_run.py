import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
from core.smc.swing_service import zigzag_atr, last_impulse_ote
from scripts.chart_verify import render_verify
ex=ccxt.bingx({'enableRateLimit':True})
o=ex.fetch_ohlcv('XLM/USDT:USDT','1m',limit=220)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
zz=zigzag_atr(df, depth=11, dev_mult=3.0)
ote=last_impulse_ote(zz)
a=ote['from'][1]; b=ote['to'][1]; d=ote['direction']
print('Авто-импульс:', round(a,5), '->', round(b,5), '|', d)
hl={str(f):p for f,p in ote['levels'].items()}
zones=[(ote['ote'][0], ote['ote'][1], '#1e90ff', 'OTE 0.705-0.79 '+d)]
render_verify(df, 'XLM 1m - ABTO OTE (последний импульс, '+d+')', zigzag=zz, hlines=hl, zones=zones, out='tmp_charts/xlm_ote_valid.png')
