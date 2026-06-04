import sys; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np, os, time
from core.smc.smc_engine import ote_retest_setups, zigzag_atr, find_setups_zz

def load(tf,sym):
    p=f'data/history/{tf}/{sym}.parquet'
    if not os.path.exists(p): return None
    return pd.read_parquet(p)

def resample4h(df1h):
    o=df1h['open'].resample('4h').first(); h=df1h['high'].resample('4h').max()
    l=df1h['low'].resample('4h').min(); c=df1h['close'].resample('4h').last()
    return pd.DataFrame({'open':o,'high':h,'low':l,'close':c}).dropna()

def sim_nested(df_ltf, entry_ts, entry, sl, tp, direction):
    """симуляция входа на LTF, цель=HTF target, sl=LTF structural"""
    pos={ts:i for i,ts in enumerate(df_ltf.index)}; ei=pos.get(entry_ts)
    if ei is None: return None
    lo=df_ltf['low'].values; hi=df_ltf['high'].values; n=len(df_ltf)
    risk=abs(entry-sl)
    if risk<=0: return None
    if direction=='long':
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
LTF='5m'
HTF_WINDOW=pd.Timedelta(days=10)   # окно жизни 4h-сетапа
t0=time.time(); nested=[]; flat4h=[]
for sym in PAIRS:
    df1h=load('1h',sym); df5=load(LTF,sym)
    if df1h is None or df5 is None: continue
    df4=resample4h(df1h)
    htf_setups=ote_retest_setups(df4, only_choch=False)
    # 5m setups индексируем по времени для вложенного поиска
    df5s=df5.tail(60000)  # ограничим для скорости
    ltf_setups=ote_retest_setups(df5s, only_choch=False)
    ltf_by_ts=[(s['entry_ts'],s) for s in ltf_setups]
    for h in htf_setups:
        # плоский 4h baseline (для сравнения)
        rflat=sim_nested(df4,h['entry_ts'],h['entry'],h['sl'],h['to'][1],h['direction'])
        if rflat is not None: flat4h.append((sym,h['direction'],rflat))
        ote_lo,ote_hi=h['ote']; htf_tp=h['to'][1]; hdir=h['direction']
        t_choch=h['choch_ts']; t_end=t_choch+HTF_WINDOW
        # ищем 5m слом ТОГО ЖЕ направления, внутри окна, с входом в 4h OTE зоне
        for ts5,s5 in ltf_by_ts:
            if ts5<t_choch or ts5>t_end: continue
            if s5['direction']!=hdir: continue
            e5=s5['entry']
            if not (ote_lo<=e5<=ote_hi): continue   # вход обязан быть в 4h OTE
            r=sim_nested(df5s,s5['entry_ts'],e5,s5['sl'],htf_tp,hdir)
            if r is not None:
                nested.append((sym,hdir,r,abs(e5-s5['sl']),abs(e5-h['sl'])))
            break  # первый 5m слом в зоне = вход
    print(f'{sym} htf={len(htf_setups)} nested={len(nested)} {time.time()-t0:.0f}s',flush=True)

def st(arr):
    if not len(arr): return 'n=0'
    r=np.array(arr); return f"n={len(r):>4} avgR={r.mean():+.3f} med={np.median(r):+.2f} WR={(r>0).mean()*100:>3.0f}% sumR={r.sum():+.0f} maxR={r.max():+.1f}"
N=pd.DataFrame(nested,columns=['sym','dir','r','risk5','risk4'])
F=pd.DataFrame(flat4h,columns=['sym','dir','r'])
print('\n=== ВЛОЖЕННЫЙ: вход 5m в 4h-OTE, TP=4h target ===')
print('NESTED  всего:', st(N.r.values))
print('NESTED   long:', st(N[N.dir=="long"].r.values))
print('NESTED  short:', st(N[N.dir=="short"].r.values))
print('\n=== ПЛОСКИЙ 4h (тот же сетап, вход по 4h, SL за 4h 1.0) ===')
print('FLAT4h  всего:', st(F.r.values))
if len(N):
    print(f'\nСредний risk: 5m-вход={N.risk5.mean():.4f}  4h-вход={N.risk4.mean():.4f}  → ужатие риска x{N.risk4.mean()/(N.risk5.mean()+1e-9):.1f}')
