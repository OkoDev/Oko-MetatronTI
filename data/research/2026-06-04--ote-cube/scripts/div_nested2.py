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
    br,be,bh,beh=_calc_divergence(c,r,DIV_PIVOT_PRD,DIV_MAX_PP,DIV_MAX_BARS)
    return dict(bull_reg=br,bear_reg=be,bull_hid=bh,bear_hid=beh)
def dedup_edges(arr, min_gap):
    """вернуть индексы где flag впервые True (rising edge) + min_gap между входами"""
    out=[]; last=-10**9
    for i in range(1,len(arr)):
        if arr[i] and not arr[i-1] and (i-last)>=min_gap:
            out.append(i); last=i
    return out
def sim(df,ei,entry,sl,d,cap=8.0):
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    tpc=entry+cap*risk if d=='long' else entry-cap*risk
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1: phase=2; (None if hi[j]<tpc else None)
                if phase==2 and hi[j]>=tpc: return 0.5+0.5*cap
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=tpc: return 0.5+0.5*cap
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1: phase=2
                if phase==2 and lo[j]<=tpc: return 0.5+0.5*cap
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=tpc: return 0.5+0.5*cap
    return 0.5 if phase==2 else None
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','DOGEUSDT']
COMBOS=[('1d','15m'),('4h','15m'),('4h','5m')]
LB=10; MIN_GAP=30
t0=time.time(); res={}
for htf,ltf in COMBOS:
    hwin=pd.Timedelta(minutes=2.5*DUR[htf])  # УЗКОЕ окно: 2-3 HTF бара
    for sym in PAIRS:
        dfh=get_df(htf,sym); dfl=get_df(ltf,sym)
        if dfh is None or dfl is None: continue
        dh=divs(dfh); dl=divs(dfl); hts=dfh.index
        lo=dfl['low'].values; hi=dfl['high'].values; cl=dfl['close'].values
        def hid_active(ts5,kind):
            arr=dh['bull_hid'] if kind=='bull' else dh['bear_hid']
            m=(hts<=ts5)&(hts>=ts5-hwin); return bool(arr[m].any())
        # все hidden-edge времена для группы B
        for kind,ldir in [('bull','long'),('bear','short')]:
            reg=dl['bull_reg'] if kind=='bull' else dl['bear_reg']
            reg_idx=dedup_edges(reg, MIN_GAP)
            for i in reg_idx:
                if i<LB: continue
                ts5=dfl.index[i]; entry=cl[i]
                sl=lo[i-LB:i].min() if ldir=='long' else hi[i-LB:i].max()
                r=sim(dfl,i,entry,sl,ldir)
                if r is None: continue
                res.setdefault((htf,ltf,'C_reg_alone'),[]).append((ldir,r))
                if hid_active(ts5,kind):
                    res.setdefault((htf,ltf,'A_hid+reg'),[]).append((ldir,r))
        # группа B: hidden active, вход по hidden-edge LTF (близко к HTF hidden) БЕЗ regular подтверждения
        for kind,ldir in [('bull','long'),('bear','short')]:
            hid=dh['bull_hid'] if kind=='bull' else dh['bear_hid']
            reg=dl['bull_reg'] if kind=='bull' else dl['bear_reg']
            # для каждого HTF hidden-edge → вход на первом LTF баре после подтверждения, если НЕТ regular в окне
            hid_edges=[k for k in range(1,len(hid)) if hid[k] and not hid[k-1]]
            for hk in hid_edges:
                ts_h=hts[hk]
                # первый LTF бар >= ts_h
                jj=dfl.index.searchsorted(ts_h)
                if jj<LB or jj>=len(dfl): continue
                # есть ли regular в окне [jj-MIN_GAP, jj+MIN_GAP]? если ДА — это группа A, пропускаем
                a=max(0,jj-MIN_GAP); b=min(len(reg),jj+MIN_GAP)
                if reg[a:b].any(): continue
                entry=cl[jj]
                sl=lo[jj-LB:jj].min() if ldir=='long' else hi[jj-LB:jj].max()
                r=sim(dfl,jj,entry,sl,ldir)
                if r is not None: res.setdefault((htf,ltf,'B_hid_noreg'),[]).append((ldir,r))
    print(f'{htf}->{ltf} done {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not a: return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>4} avgR={r.mean():+.3f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
print('\n=== ВЛОЖЕННОСТЬ ДИВЕРГЕНЦИЙ (узкое окно 2.5 HTF-бара, дедуп gap=30) ===')
for htf,ltf in COMBOS:
    print(f'\n{htf} hidden → {ltf} regular:')
    print(f'  A. hidden+regular (подтв) :',st(res.get((htf,ltf,'A_hid+reg'),[])))
    print(f'  B. hidden БЕЗ regular     :',st(res.get((htf,ltf,'B_hid_noreg'),[])))
    print(f'  C. regular один (baseline):',st(res.get((htf,ltf,'C_reg_alone'),[])))
