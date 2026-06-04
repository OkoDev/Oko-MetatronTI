import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from tools.pattern_mining.combinator_v2 import rsi, _calc_divergence
try:
    from tools.pattern_mining.combinator_v2 import DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS
except Exception:
    DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS = 5, 10, 100
DUR={'1d':1440,'4h':240,'1h':60,'15m':15,'5m':5}
def load_raw(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def resample(d,r):
    return pd.DataFrame({'open':d['open'].resample(r).first(),'high':d['high'].resample(r).max(),
        'low':d['low'].resample(r).min(),'close':d['close'].resample(r).last()}).dropna()
def get_df(tf,sym):
    if tf in ('5m','15m','1h'):
        d=load_raw(tf,sym); return d.tail(120000) if d is not None else None
    base=load_raw('1h',sym); return resample(base,{'4h':'4h','1d':'1D'}[tf]) if base is not None else None
def divs(df):
    c=df['close'].values; r=rsi(c,14)
    bull_reg,bear_reg,bull_hid,bear_hid=_calc_divergence(c,r,DIV_PIVOT_PRD,DIV_MAX_PP,DIV_MAX_BARS)
    return dict(bull_reg=bull_reg,bear_reg=bear_reg,bull_hid=bull_hid,bear_hid=bear_hid)
def sim(df,ei,entry,sl,d,cap=8.0):
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    tp_cap=entry+cap*risk if d=='long' else entry-cap*risk
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1:
                    phase=2
                    if hi[j]>=tp_cap: return 0.5+0.5*cap
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=tp_cap: return 0.5+0.5*cap
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1:
                    phase=2
                    if lo[j]<=tp_cap: return 0.5+0.5*cap
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=tp_cap: return 0.5+0.5*cap
    return 0.5 if phase==2 else None
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','DOGEUSDT']
COMBOS=[('1d','15m'),('1d','5m'),('4h','15m'),('4h','5m')]
LB=10
t0=time.time()
res={}  # (htf,ltf,mode)->list
for htf,ltf in COMBOS:
    for sym in PAIRS:
        dfh=get_df(htf,sym); dfl=get_df(ltf,sym)
        if dfh is None or dfl is None: continue
        dh=divs(dfh); dl=divs(dfl)
        lo=dfl['low'].values; hi=dfl['high'].values
        # окно активности HTF hidden: для каждого LTF-бара знаем активна ли HTF hidden (bull/bear)
        hwin=pd.Timedelta(minutes=60*DUR[htf])  # держим hidden N=60 HTF-баров
        # построим для htf массив timestamp где hidden активна
        hts=dfh.index
        def htf_active(ts5,kind):  # kind='bull'/'bear'
            arr=dh['bull_hid'] if kind=='bull' else dh['bear_hid']
            # активна если был hidden флаг на HTF в окне [ts5-hwin, ts5]
            mask=(hts<=ts5)&(hts>=ts5-hwin)
            return bool(arr[mask].any())
        for kind,ldir in [('bull','long'),('bear','short')]:
            larr=dl['bull_reg'] if kind=='bull' else dl['bear_reg']
            for i in range(LB,len(dfl)):
                if not larr[i]: continue
                ts5=dfl.index[i]; entry=dfl['close'].values[i]
                sl=lo[i-LB:i].min() if ldir=='long' else hi[i-LB:i].max()
                r=sim(dfl,i,entry,sl,ldir)
                if r is None: continue
                res.setdefault((htf,ltf,'base'),[]).append((ldir,r))   # LTF regular alone
                if htf_active(ts5,kind):
                    res.setdefault((htf,ltf,'nested'),[]).append((ldir,r))  # + HTF hidden
    print(f'{htf}->{ltf} done {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not a: return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>5} avgR={r.mean():+.3f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
print('\n=== ВЛОЖЕННОСТЬ ДИВЕРГЕНЦИЙ: HTF hidden + LTF regular (runner cap 8R) ===')
for htf,ltf in COMBOS:
    b=res.get((htf,ltf,'base'),[]); nn=res.get((htf,ltf,'nested'),[])
    print(f'\n{htf} hidden → {ltf} regular:')
    print(f'  LTF regular ОДИН :',st(b))
    print(f'  + HTF hidden GATE:',st(nn))
