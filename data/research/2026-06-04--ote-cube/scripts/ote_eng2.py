import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
from core.smc.smc_engine import zigzag_atr, ote_retest_setups
from scripts.chart_verify import render_verify
ex=ccxt.bingx({'enableRateLimit':True})
o=ex.fetch_ohlcv('SOL/USDT:USDT','1h',limit=500)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume']); df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
setups=ote_retest_setups(df, only_choch=False)   # BOS + CHoCH
print(f'OTE-Retest сетапов (BOS+CHoCH): {len(setups)}\n')
last=df.index[-1]; tl=[]; zones=[]; segs=[]
for s in setups[-8:]:
    d=s['direction']; c='+'*s['confluence'] if s['confluence'] else '—'
    print(f"  {d.upper():5} слом@{str(s['choch_ts'])[5:16]} вход@{str(s['entry_ts'])[5:16]} entry={s['entry']:.3f} SL={s['sl']:.3f} risk={s['risk']:.3f} confl={c}")
    col='#00e676' if d=='long' else '#f23645'
    a=s['from']; b=s['to']; tl.append((a[0],a[1],b[0],b[1],col,''))
    zones.append((s['ote'][0],s['ote'][1],col,f"OTE {d} {c}"))
    segs.append((s['entry_ts'],last,s['sl'],'#999999','SL'))
render_verify(df,'SOL 1h — OTE-Retest Engine (BOS+CHoCH→OTE→ретест→вход+SL)',
  zigzag=zigzag_atr(df,11,3.0), trendlines=tl, zones=zones, hsegments=segs, out='tmp_charts/ote_engine.png')
