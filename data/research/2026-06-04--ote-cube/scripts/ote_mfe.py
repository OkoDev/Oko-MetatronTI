import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups
def load(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'; return pd.read_parquet(p) if os.path.exists(p) else None
def resample4h(d):
    return pd.DataFrame({'open':d['open'].resample('4h').first(),'high':d['high'].resample('4h').max(),
        'low':d['low'].resample('4h').min(),'close':d['close'].resample('4h').last()}).dropna()
def mfe(df,ets,entry,sl,tp,d):
    """возвращает (max R достигнутый до SL/конца, исход 'tp'/'sl'/'open')"""
    pos={ts:i for i,ts in enumerate(df.index)}; ei=pos.get(ets)
    if ei is None: return None
    lo=df['low'].values; hi=df['high'].values; n=len(df); risk=abs(entry-sl)
    if risk<=0: return None
    best=0.0
    for j in range(ei+1,n):
        if d=='long':
            best=max(best,(hi[j]-entry)/risk)
            if lo[j]<=sl: return (best,'sl')
            if hi[j]>=tp: return (best,'tp')
        else:
            best=max(best,(entry-lo[j])/risk)
            if hi[j]>=sl: return (best,'sl')
            if lo[j]<=tp: return (best,'tp')
    return (best,'open')
PAIRS=['BTCUSDT','ETHUSDT','SOLUSDT','GRTUSDT','XLMUSDT','DOGEUSDT']
HTF_WINDOW=pd.Timedelta(days=10); t0=time.time(); rows=[]
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
            m=mfe(df5,s5['entry_ts'],e5,s5['sl'],tp,hd)
            if m: rows.append((hd,m[0],m[1]))
    print(f'{sym} done {time.time()-t0:.0f}s',flush=True)
M=pd.DataFrame(rows,columns=['dir','mfe','out'])
print(f'\n=== MFE-распределение nested-входов (n={len(M)}) ===')
print('Какую долю входов цена дотягивает до уровня R прежде чем развернуться:')
for thr in [0.5,1,2,3,5,8]:
    p=(M.mfe>=thr).mean()*100; print(f'  MFE>={thr:>3}R: {p:>4.0f}% входов')
print('\nИсходы:', dict(M.out.value_counts()))
# Симуляция частичного TP: TP1 на X R (50% позы) + остаток до 4h target
print('\n=== Частичный TP: 50% на TP1, 50% runner до 4h target ===')
def partial(M,tp1):
    out=[]
    for _,r in M.iterrows():
        hit_tp1 = r['mfe']>=tp1
        if r['out']=='tp':   # дошёл до 4h target → обе части профит
            full = r['mfe'] if False else None
            out.append(0.5*tp1 + 0.5* ( (r['mfe']) ))  # runner≈добежал; апрокс полным R до target
        elif hit_tp1:        # взяли TP1, остаток выбило по BE/SL → консервативно runner=0 (BE)
            out.append(0.5*tp1 + 0.5*0.0)
        else:                # не дошёл даже до TP1 → −1R обе части
            out.append(-1.0)
    return np.array(out)
for tp1 in [1,2,3]:
    a=partial(M,tp1); print(f'  TP1={tp1}R: avgR={a.mean():+.3f} WR={(a>0).mean()*100:.0f}% sumR={a.sum():+.0f}')
