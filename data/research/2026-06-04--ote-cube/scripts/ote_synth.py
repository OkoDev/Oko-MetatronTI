import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
from tools.pattern_mining.combinator_v2 import rsi, _calc_divergence, DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS
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
    return _calc_divergence(c,r,DIV_PIVOT_PRD,DIV_MAX_PP,DIV_MAX_BARS)  # br,be,bh,beh
def sim(df,ei,entry,sl,tp,d):
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    tp1=entry+risk if d=='long' else entry-risk
    if (d=='long' and tp<=entry) or (d=='short' and tp>=entry): return None
    phase=1; be=entry
    for j in range(ei+1,n):
        if d=='long':
            if phase==1:
                if lo[j]<=sl: return -1.0
                if hi[j]>=tp1: phase=2
                if phase==2 and hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
            else:
                if lo[j]<=be: return 0.5
                if hi[j]>=tp: return 0.5+0.5*((tp-entry)/risk)
        else:
            if phase==1:
                if hi[j]>=sl: return -1.0
                if lo[j]<=tp1: phase=2
                if phase==2 and lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
            else:
                if hi[j]>=be: return 0.5
                if lo[j]<=tp: return 0.5+0.5*((entry-tp)/risk)
    return 0.5 if phase==2 else None
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','DOGEUSDT']
COMBOS=[('4h','15m'),('4h','5m')]; VAL_LB=20
t0=time.time(); res={}
for htf,ltf in COMBOS:
    win=pd.Timedelta(minutes=60*DUR[htf]); hwin=pd.Timedelta(minutes=2.5*DUR[htf])
    for sym in PAIRS:
        dfh=get_df(htf,sym); dfl=get_df(ltf,sym)
        if dfh is None or dfl is None: continue
        br,be,bh,beh=divs(dfl); hbr,hbe,hbh,hbeh=divs(dfh)
        hts=dfh.index; lts=dfl.index; idxl={ts:k for k,ts in enumerate(lts)}
        hset=ote_retest_setups(dfh,only_choch=False)
        lset=[(s['entry_ts'],s) for s in ote_retest_setups(dfl,only_choch=False)]
        for h in hset:
            olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win
            tp=h['to'][1]; sl_inval=h['sl']
            reg = br if pdir=='long' else be
            hid = hbh if pdir=='long' else hbeh
            hid_on=bool(hid[(hts<=te)&(hts>=tc-hwin)].any())
            # LTF-СЛОМ того же направления, вход в OTE-зоне, в окне (continuation)
            for ts5,s5 in lset:
                if ts5<tc or ts5>te or s5['direction']!=pdir: continue
                e5=s5['entry']
                if not (olo<=e5<=ohi): continue
                ei=idxl.get(s5['entry_ts'])
                if ei is None: continue
                sl_ltf=s5['sl']
                # валидатор regular: был regular div в окне перед входом
                reg_on=bool(reg[max(0,ei-VAL_LB):ei+1].any())
                rA=sim(dfl,ei,e5,sl_ltf,tp,pdir)            # A: слом, SL=LTF
                rAi=sim(dfl,ei,e5,sl_inval,tp,pdir)         # A+inval SL
                if rA is not None:
                    res.setdefault((htf,ltf,'A_slom'),[]).append((pdir,rA))
                    if reg_on: res.setdefault((htf,ltf,'B_slom+regVAL'),[]).append((pdir,rA))
                    if hid_on: res.setdefault((htf,ltf,'C_slom+hidVAL'),[]).append((pdir,rA))
                    if reg_on and hid_on: res.setdefault((htf,ltf,'D_slom+reg+hid'),[]).append((pdir,rA))
                if rAi is not None:
                    res.setdefault((htf,ltf,'A2_slom_invalSL'),[]).append((pdir,rAi))
                    if reg_on and hid_on: res.setdefault((htf,ltf,'D2_full_invalSL'),[]).append((pdir,rAi))
                break  # первый слом в зоне
    print(f'{htf}->{ltf} done {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not a: return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>4} avgR={r.mean():+.3f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
def split(a,d): return [x for x in a if x[0]==d]
print('\n=== СИНТЕЗ: LTF-СЛОМ в OTE + дивергенция-ВАЛИДАТОР (не точка входа) ===')
for htf,ltf in COMBOS:
    print(f'\n{htf} OTE → {ltf} слом:')
    for key,lbl in [('A_slom','A. слом в зоне (SL=LTF)   '),('A2_slom_invalSL','A2. слом (SL=инвалид 1.0)'),
                    ('B_slom+regVAL','B. +regular ВАЛИДАТОР    '),('C_slom+hidVAL','C. +hidden ВАЛИДАТОР     '),
                    ('D_slom+reg+hid','D. +оба валидатора       '),('D2_full_invalSL','D2. оба + SL=инвалидация ')]:
        a=res.get((htf,ltf,key),[])
        print(f'  {lbl}:',st(a))
    # LONG/SHORT split для лучшей группы
    d=res.get((htf,ltf,'D_slom+reg+hid'),[])
    if d: print(f'     [D split] long:',st(split(d,'long')),'| short:',st(split(d,'short')))
