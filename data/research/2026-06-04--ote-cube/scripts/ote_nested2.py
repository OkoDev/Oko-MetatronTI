import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups

def load(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'
    return pd.read_parquet(p) if os.path.exists(p) else None
def resample4h(d):
    return pd.DataFrame({'open':d['open'].resample('4h').first(),'high':d['high'].resample('4h').max(),
        'low':d['low'].resample('4h').min(),'close':d['close'].resample('4h').last()}).dropna()
def sim(df,entry_ts,entry,sl,tp,d):
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(entry_ts)
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
LTF='5m'; HTF_WINDOW=pd.Timedelta(days=10)
t0=time.time(); nested=[]; flat4h=[]
for sym in PAIRS:
    df1h=load('1h',sym); df5=load(LTF,sym)
    if df1h is None or df5 is None: continue
    df5=df5.tail(120000)                 # ≈400 дней 5m
    t5_start=df5.index[0]
    df4=resample4h(df1h)
    df4=df4[df4.index>=t5_start]          # СИНХРОН: 4h только в окне 5m
    htf=ote_retest_setups(df4, only_choch=False)
    ltf=ote_retest_setups(df5, only_choch=False)
    ltf_ts=[(s['entry_ts'],s) for s in ltf]
    for h in htf:
        rf=sim(df4,h['entry_ts'],h['entry'],h['sl'],h['to'][1],h['direction'])
        if rf is not None: flat4h.append((sym,h['direction'],rf))
        olo,ohi=h['ote']; tp=h['to'][1]; hd=h['direction']; tc=h['choch_ts']; te=tc+HTF_WINDOW
        for ts5,s5 in ltf_ts:
            if ts5<tc or ts5>te or s5['direction']!=hd: continue
            e5=s5['entry']
            if not (olo<=e5<=ohi): continue
            r=sim(df5,s5['entry_ts'],e5,s5['sl'],tp,hd)
            if r is not None: nested.append((sym,hd,r,abs(e5-s5['sl']),abs(e5-h['sl'])))
            break
    print(f'{sym} htf={len(htf)} nested={len(nested)} {time.time()-t0:.0f}s',flush=True)

def st(a):
    if not len(a): return 'n=0'
    r=np.array(a); return f"n={len(r):>4} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
N=pd.DataFrame(nested,columns=['sym','dir','r','risk5','risk4']); F=pd.DataFrame(flat4h,columns=['sym','dir','r'])
print('\n=== NESTED (5m в 4h-OTE, синхрон окон) ===')
print(' всего:', st(N.r.values)); print('  long:', st(N[N.dir=="long"].r.values)); print(' short:', st(N[N.dir=="short"].r.values))
print('\n=== FLAT 4h (те же сетапы) ==='); print(' всего:', st(F.r.values))
if len(N): print(f'\nrisk: 5m={N.risk5.mean():.3f} 4h={N.risk4.mean():.3f} → x{N.risk4.mean()/(N.risk5.mean()+1e-9):.1f}')
print('по парам nested:', dict(N.groupby('sym').size()) if len(N) else {})
