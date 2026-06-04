import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
def load(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def resample4h(d):
    return pd.DataFrame({'open':d['open'].resample('4h').first(),'high':d['high'].resample('4h').max(),
        'low':d['low'].resample('4h').min(),'close':d['close'].resample('4h').last()}).dropna()
def sim(df,ets,entry,sl,tp,d):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(ets)
    if ei is None: return None
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    if d=='long':
        if tp<=entry: return None
        for j in range(ei+1,n):
            if lo[j]<=sl: return -1.0
            if hi[j]>=tp: return (tp-entry)/risk
    else:
        if tp>=entry: return None
        for j in range(ei+1,n):
            if hi[j]>=sl: return -1.0
            if lo[j]<=tp: return (entry-tp)/risk
    return None
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','XLMUSDT','DOGEUSDT']
HTF_WINDOW=pd.Timedelta(days=10); SL_BUF=0.30   # буфер 30% risk под 5m SL
t0=time.time()
res={'base':[],'confl':[],'conflbuf':[]}
for sym in PAIRS:
    df1h=load('1h',sym); df5=load('5m',sym)
    if df1h is None or df5 is None: continue
    df5=df5.tail(120000); t5=df5.index[0]
    df4=resample4h(df1h); df4=df4[df4.index>=t5]
    htf=ote_retest_setups(df4,only_choch=False); ltf=ote_retest_setups(df5,only_choch=False)
    ltf_ts=[(s['entry_ts'],s) for s in ltf]
    for h in htf:
        olo,ohi=h['ote']; tp=h['to'][1]; hd=h['direction']; tc=h['choch_ts']; te=tc+HTF_WINDOW
        for ts5,s5 in ltf_ts:
            if ts5<tc or ts5>te or s5['direction']!=hd: continue
            e5=s5['entry']
            if not (olo<=e5<=ohi): continue
            sl5=s5['sl']; risk=abs(e5-sl5); confl=s5.get('confluence',0)
            r=sim(df5,s5['entry_ts'],e5,sl5,tp,hd)
            if r is not None: res['base'].append((hd,r))
            if confl>=1:
                if r is not None: res['confl'].append((hd,r))
                sl_b=sl5-SL_BUF*risk if hd=='long' else sl5+SL_BUF*risk
                rb=sim(df5,s5['entry_ts'],e5,sl_b,tp,hd)
                if rb is not None: res['conflbuf'].append((hd,rb))
            break
    print(f'{sym} done {time.time()-t0:.0f}s',flush=True)
def st(a):
    if not len(a): return 'n=0'
    r=np.array([x[1] for x in a]); return f"n={len(r):>4} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
def sub(a,d): return [x for x in a if x[0]==d]
for k,lbl in [('base','БЕЗ фильтра'),('confl','confluence≥1'),('conflbuf','confluence≥1 + SL-буфер30%')]:
    print(f'\n=== {lbl} ==='); print(' всего:',st(res[k])); print('  long:',st(sub(res[k],"long"))); print(' short:',st(sub(res[k],"short")))
