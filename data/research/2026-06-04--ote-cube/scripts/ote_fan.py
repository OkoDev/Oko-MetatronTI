import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, glob, time
from core.smc.smc_engine import ote_retest_setups
from tools.pattern_mining.combinator_v2 import rsi, _calc_divergence, DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS
DUR={'1d':1440,'4h':240,'1h':60,'15m':15,'5m':5}; ERA=pd.Timestamp('2026-04-15')
def load_raw(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def get_df(tf,sym):
    if tf in ('5m','15m','1h'):
        d=load_raw(tf,sym); return d.tail(120000) if d is not None else None
    base=load_raw('1h',sym)
    if base is None: return None
    return pd.DataFrame({'open':base['open'].resample({'4h':'4h','1d':'1D'}[tf]).first(),
        'high':base['high'].resample({'4h':'4h','1d':'1D'}[tf]).max(),
        'low':base['low'].resample({'4h':'4h','1d':'1D'}[tf]).min(),
        'close':base['close'].resample({'4h':'4h','1d':'1D'}[tf]).last()}).dropna()
def hid_arrs(df):
    c=df['close'].values; r=rsi(c,14)
    _,_,bh,beh=_calc_divergence(c,r,DIV_PIVOT_PRD,DIV_MAX_PP,DIV_MAX_BARS); return bh,beh
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
PAIRS=sorted(os.path.basename(p).replace('.parquet','') for p in glob.glob('data/history/15m/*.parquet'))
MATRIX={'1d':['4h','1h','15m','5m'],'4h':['1h','15m','5m'],'1h':['15m','5m']}
t0=time.time(); res={}
def add(key,ts,dirn,r):
    t=ts.tz_localize(None) if getattr(ts,'tzinfo',None) is not None else ts
    res.setdefault(key,[]).append(('POST' if t>=ERA else 'PRE',dirn,r))
for ci,sym in enumerate(PAIRS):
    dfs={}; setups={}; hids={}
    for tf in ['1d','4h','1h','15m','5m']:
        d=get_df(tf,sym)
        if d is None: continue
        dfs[tf]=d; setups[tf]=[(s['entry_ts'],s) for s in ote_retest_setups(d,only_choch=False)]
        hb,hbe=hid_arrs(d); hids[tf]=(hb,hbe,d.index)
    for htf,ltfs in MATRIX.items():
        if htf not in setups: continue
        win=pd.Timedelta(minutes=60*DUR[htf]); hwin=pd.Timedelta(minutes=2.5*DUR[htf])
        for ltf in ltfs:
            if ltf not in setups: continue
            dfl=dfs[ltf]; idxl={ts:k for k,ts in enumerate(dfl.index)}
            hb,hbe,hts=hids[htf]
            for ts_h,h in setups[htf]:
                olo,ohi=h['ote']; pdir=h['direction']; tc=h['choch_ts']; te=tc+win; tp=h['to'][1]
                ote_mid=(olo+ohi)/2.0; opp='short' if pdir=='long' else 'long'
                hid=hb if pdir=='long' else hbe
                hid_on=bool(hid[(hts<=te)&(hts>=tc-hwin)].any())
                cont_done=pull_done=False
                for ts5,s5 in setups[ltf]:
                    if ts5<tc or ts5>te: continue
                    e=s5['entry']; ei=idxl.get(s5['entry_ts'])
                    if ei is None: continue
                    # CONTINUATION
                    if (not cont_done) and s5['direction']==pdir and olo<=e<=ohi:
                        r=sim(dfl,ei,e,s5['sl'],tp,pdir)
                        if r is not None:
                            add(f'{htf}>{ltf}|cont',ts5,pdir,r)
                            if hid_on: add(f'{htf}>{ltf}|cont+hid',ts5,pdir,r)
                            cont_done=True
                    # PULLBACK
                    if (not pull_done) and s5['direction']==opp:
                        ok=(pdir=='long' and e>ohi) or (pdir=='short' and e<olo)
                        if ok:
                            r=sim(dfl,ei,e,s5['sl'],ote_mid,opp)
                            if r is not None: add(f'{htf}>{ltf}|pull',ts5,opp,r); pull_done=True
                    if cont_done and pull_done: break
    print(f'[{ci+1}/{len(PAIRS)}] {sym} {time.time()-t0:.0f}s',flush=True)
# свод
rows=[]
for key,data in res.items():
    r=np.array([x[2] for x in data]); post=[x[2] for x in data if x[0]=='POST']
    pr=np.array(post) if post else np.array([])
    rows.append((key,len(r),r.mean(),(r>0).mean()*100,r.sum(),
                 len(pr),(pr.mean() if len(pr) else float('nan'))))
rows.sort(key=lambda x:-x[2])
print('\n=== ВЕЕР: все сетапы (HTF>LTF|тип), сорт по avgR ===')
print(f'{"сетап":<20}{"n":>6}{"avgR":>8}{"WR":>6}{"sumR":>7}{"POSTn":>7}{"POSTavgR":>9}')
for k,n,a,w,s,pn,pa in rows:
    star=' ★' if (a>=0.4 and n>=50 and (pa>0 if pa==pa else False)) else ''
    pas=f'{pa:+.3f}' if pa==pa else '  --'
    print(f'{k:<20}{n:>6}{a:>+8.3f}{w:>5.0f}%{s:>+7.0f}{pn:>7}{pas:>9}{star}')
print('\n=== 🏆 ПОБЕДИТЕЛИ (avgR≥0.4, n≥50, POST>0) ===')
win=[x for x in rows if x[2]>=0.4 and x[1]>=50 and (x[6]>0 if x[6]==x[6] else False)]
for k,n,a,w,s,pn,pa in win:
    print(f'  {k:<20} n={n:>5} avgR={a:+.3f} WR={w:.0f}% POST={pa:+.3f}(n{pn})')
