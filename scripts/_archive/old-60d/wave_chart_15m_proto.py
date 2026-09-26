import sys; sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot"); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from core.smc.smc_engine import (zigzag_atr, detect_elliott_impulse, detect_structure_breaks,
                                  detect_order_blocks, _zz_typed)
from core.indicators.indicators import calculate_pivot_points
ex=ccxt.bingx(); SYM='XLM'; TF='15m'
o=ex.fetch_ohlcv(f'{SYM}/USDT:USDT',TF,limit=120)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
df['ts']=pd.to_datetime(df['ts'],unit='ms'); price=df['close'].iloc[-1]
fig,ax=plt.subplots(figsize=(15,8)); fig.patch.set_facecolor('#0e1117'); ax.set_facecolor('#0e1117')
# свечи
for i,r in df.iterrows():
    col='#26a69a' if r['close']>=r['open'] else '#ef5350'
    ax.plot([i,i],[r['low'],r['high']],color=col,linewidth=0.8,zorder=2)
    ax.add_patch(Rectangle((i-0.3,min(r['open'],r['close'])),0.6,abs(r['close']-r['open'])or price*1e-5,facecolor=col,edgecolor=col,zorder=3))
# zigzag + волновые метки
zz=zigzag_atr(df,11,3.0); typed=_zz_typed(zz)
zx=[i for i,_,_ in typed]; zy=[p for _,p,_ in typed]
ax.plot(zx,zy,color='#ffa726',linewidth=1.5,zorder=4,alpha=0.8,label='ZigZag')
for n,(idx,p,t) in enumerate(typed[-6:]):
    ax.annotate(str(n+1),(idx,p),color='#ffd54f',fontsize=13,fontweight='bold',zorder=6,
                ha='center',va='bottom' if t=='H' else 'top')
# Order Blocks
brks=detect_structure_breaks(df,length=5)
for b in detect_order_blocks(df,brks):
    if b.mitigated_idx!=-1: continue
    col='#26a69a' if b.kind=='bull' else '#ef5350'
    ax.add_patch(Rectangle((b.left_idx,b.bottom),len(df)-b.left_idx,b.top-b.bottom,
                 facecolor=col,alpha=0.12,edgecolor=col,linewidth=0.7,zorder=1))
# 4h пивоты
o4=ex.fetch_ohlcv(f'{SYM}/USDT:USDT','4h',limit=3); d4=pd.DataFrame(o4,columns=['ts','o','h','l','c','v']); pr=d4.iloc[-2]
piv=calculate_pivot_points(float(pr['h']),float(pr['l']),float(pr['c']))
for k,c2 in [('R2','#ef5350'),('R1','#ff9800'),('PP','#ffeb3b'),('S1','#4caf50'),('S2','#26a69a')]:
    if k in piv:
        ax.axhline(piv[k],color=c2,linestyle='--',linewidth=0.8,alpha=0.6,zorder=2)
        ax.text(len(df)+0.5,piv[k],f'4h-{k} {piv[k]:.4f}',color=c2,fontsize=8,va='center')
# текущая цена
ax.axhline(price,color='#ffffff',linestyle='-',linewidth=0.6,alpha=0.5)
ax.set_title(f'{SYM} {TF} — Wave+SMC разметка (волна / OB / 4h-пивоты)  цена={price:.5f}',
             color='#e0e0e0',fontsize=13,fontweight='bold')
ax.tick_params(colors='#888'); [s.set_color('#333') for s in ax.spines.values()]
ax.legend(loc='upper left',framealpha=0.3,facecolor='#1e222d',labelcolor='#ccc')
plt.tight_layout()
out='e:/tmp/xlm_wave_chart.png'
plt.savefig(out,dpi=90,facecolor='#0e1117'); print(f'PNG saved: {out}')
