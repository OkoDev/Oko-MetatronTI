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
COMBOS=[('4h','15m'),('4h','5m')]; win_mult=60
t0=time.time(); res={}
for htf,ltf in COMBOS:
    for sym in PAIRS:
        dfh=get_df(htf,sym); dfl=get_df(ltf,sym)
        if dfh is None or dfl is None: continue
        br,be,bh,beh=divs(dfl)          # LTF regular (bull/bear) + hidden
        hbr,hbe,hbh,hbeh=divs(dfh)      # HTF hidden
        hts=dfh.index; lts=dfl.index
        lo=dfl['low'].values; hi=dfl['high'].values; cl=dfl['close'].values
        idxl={ts:k for k,ts in enumerate(lts)}
        hset=ote_retest_setups(dfh,only_choch=False)
        win=pd.Timedelta(minutes=win_mult*DUR[htf])
        for h in hset:
            olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win
            tp=h['to'][1]; sl_inval=h['sl']  # уровень инвалидации (1.0=начало импульса)
            reg = br if pdir=='long' else be       # LTF regular в направлении тренда
            hid = hbh if pdir=='long' else hbeh    # HTF hidden в направлении тренда
            # LTF бары ВНУТРИ OTE-зоны и окна
            mask=(lts>=tc)&(lts<=te)
            zone_idx=[k for k in np.where(mask)[0] if olo<=cl[k]<=ohi]
            if not zone_idx: continue
            # A: голый OTE-ретест — первый бар в зоне
            ia=zone_idx[0]
            sl_ltf=lo[max(0,ia-10):ia].min() if pdir=='long' else hi[max(0,ia-10):ia].max()
            rA=sim(dfl,ia,cl[ia],sl_ltf,tp,pdir)
            if rA is not None: res.setdefault((htf,ltf,'A_ote_bare'),[]).append(rA)
            # B: OTE + LTF regular div В ЗОНЕ — первый regular в зоне
            ib=next((k for k in zone_idx if reg[k]), None)
            if ib is not None:
                sl_ltf=lo[max(0,ib-10):ib].min() if pdir=='long' else hi[max(0,ib-10):ib].max()
                rB=sim(dfl,ib,cl[ib],sl_ltf,tp,pdir)
                if rB is not None: res.setdefault((htf,ltf,'B_ote+reg'),[]).append(rB)
                # B2: тот же вход, но SL=инвалидация (1.0)
                rB2=sim(dfl,ib,cl[ib],sl_inval,tp,pdir)
                if rB2 is not None: res.setdefault((htf,ltf,'B2_ote+reg_invalSL'),[]).append(rB2)
            # C: OTE + LTF regular + HTF hidden активна в окне
            hmask=(hts<=te)&(hts>=tc-pd.Timedelta(minutes=2.5*DUR[htf]))
            hid_on=bool(hid[hmask].any())
            if ib is not None and hid_on:
                sl_ltf=lo[max(0,ib-10):ib].min() if pdir=='long' else hi[max(0,ib-10):ib].max()
                rC=sim(dfl,ib,cl[ib],sl_ltf,tp,pdir)
                if rC is not None: res.setdefault((htf,ltf,'C_ote+reg+hidden'),[]).append(rC)
    print(f'{htf}->{ltf} done {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not a: return 'n=0'
    r=np.array(a); return f"n={len(r):>4} avgR={r.mean():+.3f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
print('\n=== ДИВЕРГЕНЦИИ В OTE-ЗОНЕ (не в воздухе!) — continuation вход ===')
for htf,ltf in COMBOS:
    print(f'\n{htf} OTE → {ltf} вход:')
    for key,lbl in [('A_ote_bare','A. голый OTE-ретест      '),('B_ote+reg','B. OTE + regular В ЗОНЕ  '),
                    ('B2_ote+reg_invalSL','B2. ...+ SL=инвалидация  '),('C_ote+reg+hidden','C. OTE+regular+HTF hidden')]:
        print(f'  {lbl}:',st(res.get((htf,ltf,key),[])))
