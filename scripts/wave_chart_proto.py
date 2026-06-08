import sys; sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot"); sys.stdout.reconfigure(encoding='utf-8')
import ccxt, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from core.smc.smc_engine import (zigzag_atr, detect_structure_breaks, detect_order_blocks,
                                  detect_fvg, detect_equal_levels, _zz_typed)
from core.indicators.indicators import calculate_pivot_points
ex=ccxt.bingx(); SYM='XLM'; TF='5m'; N=150
o=ex.fetch_ohlcv(f'{SYM}/USDT:USDT',TF,limit=N)
df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
price=df['close'].iloc[-1]; n=len(df)
fig,ax=plt.subplots(figsize=(16,9)); fig.patch.set_facecolor('#0e1117'); ax.set_facecolor('#0e1117')
for i,r in df.iterrows():
    col='#26a69a' if r['close']>=r['open'] else '#ef5350'
    ax.plot([i,i],[r['low'],r['high']],color=col,linewidth=0.7,zorder=2)
    ax.add_patch(Rectangle((i-0.3,min(r['open'],r['close'])),0.6,abs(r['close']-r['open'])or price*1e-5,facecolor=col,edgecolor=col,zorder=3))
# ZigZag + волны
zz=zigzag_atr(df,11,2.0); typed=_zz_typed(zz)
ax.plot([i for i,_,_ in typed],[p for _,p,_ in typed],color='#ffa726',linewidth=1.4,zorder=4,alpha=0.85,label='ZigZag')
for k,(idx,p,t) in enumerate(typed[-10:]):
    ax.annotate(str(k),(idx,p),color='#ffd54f',fontsize=14,fontweight='bold',zorder=7,ha='center',va='bottom' if t=='H' else 'top')
# OB (bull зелёный / bear красный)
brks=detect_structure_breaks(df,length=5)
nob=0
for b in detect_order_blocks(df,brks):
    if b.mitigated_idx!=-1: continue
    col='#26a69a' if b.kind=='bull' else '#ef5350'
    ax.add_patch(Rectangle((b.left_idx,b.bottom),n-b.left_idx,b.top-b.bottom,facecolor=col,alpha=0.13,edgecolor=col,linewidth=1.0,zorder=1))
    ax.text(n+0.5,(b.top+b.bottom)/2,f'OB {b.kind}',color=col,fontsize=7,va='center'); nob+=1
# FVG (активные, около цены)
fvgs=detect_fvg(df); nfvg=0
for f in fvgs[-12:]:
    idx,top,bot,kind=f[0],f[1],f[2],f[3]
    if abs((top+bot)/2-price)/price>0.025: continue  # только близкие
    col='#42a5f5' if kind=='bull' else '#ff7043'
    ax.add_patch(Rectangle((idx,min(top,bot)),n-idx,abs(top-bot),facecolor=col,alpha=0.18,edgecolor=col,linewidth=0.6,zorder=1,hatch='///'))
    nfvg+=1
# EQL ликвидность
eqs=detect_equal_levels(df)
for e in eqs[-4:]:
    lvl=e[1]; ax.axhline(lvl,color='#ab47bc',linestyle=':',linewidth=0.7,alpha=0.5,zorder=2)
# 4h пивоты
o4=ex.fetch_ohlcv(f'{SYM}/USDT:USDT','4h',limit=3); d4=pd.DataFrame(o4,columns=['ts','o','h','l','c','v']); pr=d4.iloc[-2]
piv=calculate_pivot_points(float(pr['h']),float(pr['l']),float(pr['c']))
for kk,c2 in [('R2','#ef5350'),('R1','#ff9800'),('PP','#ffeb3b'),('S1','#4caf50'),('S2','#26a69a')]:
    if kk in piv:
        ax.axhline(piv[kk],color=c2,linestyle='--',linewidth=0.8,alpha=0.55,zorder=2)
        ax.text(n+5,piv[kk],f'4h-{kk} {piv[kk]:.4f}',color=c2,fontsize=8,va='center')
ax.axhline(price,color='#fff',linewidth=0.6,alpha=0.5)
ax.set_title(f'{SYM} 5m — полная SMC-разметка (волна / OB×{nob} / FVG×{nfvg} / EQL / 4h-пивоты)  цена={price:.5f}',color='#e0e0e0',fontsize=12,fontweight='bold')
ax.tick_params(colors='#888'); [s.set_color('#333') for s in ax.spines.values()]
ax.legend(loc='upper left',framealpha=0.3,facecolor='#1e222d',labelcolor='#ccc')
plt.tight_layout(); out='e:/tmp/xlm_5m_full.png'
plt.savefig(out,dpi=95,facecolor='#0e1117'); print(f'OB={nob} FVG={nfvg} EQL={len(eqs)} → {out}')
