"""Слой 12 — R2/S2-отбой, СТОП структурный swing + ВЫХОД на уровнях (R1/P). % net.
Егор: стоп структурный, выход на уровнях. Стоп=swing-high/low K баров (не R3/не фикс%).
Выход=R1 single и лестница R1+P. По годам."""
import os,sys,sqlite3,warnings; warnings.filterwarnings("ignore")
sys.path.insert(0,"e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np,pandas as pd
CACHE="ohlcv_cache.db"; COST=0.20; BUF=0.003; MAXHOLD=60
conn=sqlite3.connect(CACHE,timeout=60)
syms=[r[0] for r in conn.execute("SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]
KS=(5,10,20)
res={}
for side in ("Sh_R2","Lo_S2"):
    for K in KS:
        res[f"{side}_K{K}_R1"]=[]; res[f"{side}_K{K}_ladder"]=[]
for sym in syms:
    d=pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",conn,params=(sym,))
    if d is None or len(d)<300: continue
    d["dt"]=pd.to_datetime(d["time"],unit="ms",utc=True)
    g=d.set_index("dt"); wk=g.resample("W").agg(H=("high","max"),L=("low","min"),C=("close","last"))
    P=(wk["H"]+wk["L"]+wk["C"])/3.0; rng=wk["H"]-wk["L"]
    lvw=pd.DataFrame({"P":P,"R1":2*P-wk["L"],"R2":P+rng,"S1":2*P-wk["H"],"S2":P-rng}).shift(1)
    per=d["dt"].dt.to_period("W")
    V={c:per.map({p:v for p,v in zip(lvw.index.to_period("W"),lvw[c].values)}).values for c in lvw.columns}
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; N=len(cl)
    yrs=d["dt"].values.astype("datetime64[Y]").astype(int)+1970
    for i in range(1,N-1):
        yr=int(yrs[i])
        # SHORT R2-отбой
        r2=V["R2"][i]; r1=V["R1"][i]; pp=V["P"][i]
        if not(np.isnan(r2) or np.isnan(r1) or np.isnan(pp)) and hi[i]>=r2 and cl[i]<r2 and hi[i-1]<r2:
            entry=cl[i]
            for K in KS:
                stop=hi[max(0,i-K):i+1].max()*(1+BUF)
                if stop<=entry or r1>=entry: continue
                end=min(N,i+MAXHOLD+1)
                # single R1
                ex=None
                for m in range(i+1,end):
                    if hi[m]>=stop: ex=stop; break
                    if lo[m]<=r1: ex=r1; break
                if ex is None: ex=cl[end-1]
                res[f"Sh_R2_K{K}_R1"].append(((entry-ex)/entry*100,yr))
                # ladder R1(½)+P(½)
                got_r1=False; exit_stop=None; exit_p=None
                for m in range(i+1,end):
                    if hi[m]>=stop: exit_stop=stop; break
                    if not got_r1 and lo[m]<=r1: got_r1=True
                    if got_r1 and lo[m]<=pp: exit_p=pp; break
                parts=[]
                if exit_stop is not None:
                    if got_r1: parts=[(entry-r1)/entry*100*0.5,(entry-exit_stop)/entry*100*0.5]
                    else: parts=[(entry-exit_stop)/entry*100]
                elif exit_p is not None:
                    parts=[(entry-r1)/entry*100*0.5,(entry-pp)/entry*100*0.5]
                else:
                    last=cl[end-1]
                    if got_r1: parts=[(entry-r1)/entry*100*0.5,(entry-last)/entry*100*0.5]
                    else: parts=[(entry-last)/entry*100]
                res[f"Sh_R2_K{K}_ladder"].append((sum(parts),yr))
        # LONG S2-отбой
        s2=V["S2"][i]; s1=V["S1"][i]
        if not(np.isnan(s2) or np.isnan(s1) or np.isnan(pp)) and lo[i]<=s2 and cl[i]>s2 and lo[i-1]>s2:
            entry=cl[i]
            for K in KS:
                stop=lo[max(0,i-K):i+1].min()*(1-BUF)
                if stop>=entry or s1<=entry: continue
                end=min(N,i+MAXHOLD+1)
                ex=None
                for m in range(i+1,end):
                    if lo[m]<=stop: ex=stop; break
                    if hi[m]>=s1: ex=s1; break
                if ex is None: ex=cl[end-1]
                res[f"Lo_S2_K{K}_R1"].append(((ex-entry)/entry*100,yr))
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
print(f"\n{'='*76}\nСлой 12 R2/S2-отбой · стоп структурный swing K · выход R1/ladder · costs={COST}%")
def rep(name,lst):
    if not lst: return
    a=np.array([x[0] for x in lst])-COST; ys={}
    for v,y in lst: ys.setdefault(y,[]).append(v)
    ystr=" ".join(f"{y}:{np.array(v).mean()-COST:+.2f}" for y,v in sorted(ys.items()))
    print(f"  [{name:16s}] n={len(a):5d} mean={a.mean():+.3f} med={np.median(a):+.2f} WR={100*(a>0).mean():.0f}% | {ystr}")
for K in KS:
    rep(f"Sh_R2_K{K}_R1",res[f"Sh_R2_K{K}_R1"])
    rep(f"Sh_R2_K{K}_ladder",res[f"Sh_R2_K{K}_ladder"])
for K in KS:
    rep(f"Lo_S2_K{K}_R1",res[f"Lo_S2_K{K}_R1"])
