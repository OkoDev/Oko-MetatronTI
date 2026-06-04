import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
from core.smc.swing_service import build_ote, zigzag_atr
from scripts.chart_verify import render_verify
ex=ccxt.bingx({'enableRateLimit':True})
o=ex.fetch_ohlcv('XLM/USDT:USDT','1m',limit=900)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
df.index=pd.to_datetime(df['ts'],unit='ms',utc=True)
# найти бары близкие к твоим якорям: high≈0.22113, low(LL)≈0.21478
hi_idx=(df['high']-0.22113).abs().idxmin()
lo_idx=(df['low']-0.21478).abs().idxmin()
hp=float(df.loc[hi_idx,'high']); lp=float(df.loc[lo_idx,'low'])
print('Найдены якоря: high', round(hp,5), '@', str(hi_idx)[11:16], '| LL', round(lp,5), '@', str(lo_idx)[11:16])
ote=build_ote(hp, lp)  # bull: 0=high, 1=low → OTE near low
# окно вокруг импульса для наглядности
lo_pos=df.index.get_loc(lo_idx); hi_pos=df.index.get_loc(hi_idx)
a,b=min(hi_pos,lo_pos), max(hi_pos,lo_pos)
win=df.iloc[max(0,a-30):min(len(df),b+60)]
zz=zigzag_atr(win, depth=11, dev_mult=3.0)
# наклонная импульса high→low (привязана к якорям)
tl=[(hi_idx,hp,lo_idx,lp,'#dddddd','impulse')]
last_ts=win.index[-1]
# Fib от ПРАВОГО якоря (lo_idx, конец импульса вниз) вправо
segs=[(lo_idx,last_ts,p,'#888888',str(f)) for f,p in ote['levels'].items()]
zones=[(ote['ote'][0],ote['ote'][1],'#1e90ff','OTE 0.705-0.79 long')]
labels=[(hi_idx,hp,'0','#5b9bff'),(lo_idx,lp,'1','#5b9bff')]
render_verify(win, 'XLM 1m - OTE на ТВОИХ якорях (0.22113->0.21478, bull/long)',
  zigzag=zz, trendlines=tl, hsegments=segs, zones=zones, labels=labels, out='tmp_charts/xlm_ote_exact.png')
print('Сверка Fib с твоей разметкой:')
ref={0.5:0.21796,0.62:0.21719,0.705:0.21665,0.79:0.21611}
for f,p in ote['levels'].items():
    r=ref.get(f); m=' <- твой '+str(r)+(' OK' if r and abs(p-r)<0.0002 else '') if r else ''
    print('  ',f,':',round(p,5),m)
