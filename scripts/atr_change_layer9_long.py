"""atr_change Слой 9 — ЗЕРКАЛО для LONG: 4h LONG-флип + cl>P, цель R1/R2/R3, защита флип/структ-стоп.
% net (ЗАКОН №1). Симметрия к SHORT (Слои 7/8). Егор: проверить лонг. Crypto bull-bias → LONG может
быть устойчивее по годам."""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_trend
CACHE="ohlcv_cache.db"; COST=0.20; BUF=0.003; K=10; MAXHOLD=180
conn=sqlite3.connect(CACHE,timeout=60)
syms=[r[0] for r in conn.execute("SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]
POL=("R1_flip","R2_flip","R3_flip","R2_struct","baseline_flip")
res={p:[] for p in POL}
for sym in syms:
    d=pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",conn,params=(sym,))
    if d is None or len(d)<300: continue
    d["dt"]=pd.to_datetime(d["time"],unit="ms",utc=True)
    df=calculate_trend(d[["high","low","close"]].assign(open=d["close"]).copy(),atr_period=43,factor=1.0)
    tr=df["trend"].values; cl=d["close"].values; hi=d["high"].values; lo=d["low"].values
    g=d.set_index("dt"); wk=g.resample("W").agg(H=("high","max"),L=("low","min"),C=("close","last"))
    P=(wk["H"]+wk["L"]+wk["C"])/3.0; rng=wk["H"]-wk["L"]
    lv=pd.DataFrame({"P":P,"R1":2*P-wk["L"],"R2":P+rng,"R3":wk["H"]+2*(P-wk["L"])}).shift(1)
    per=d["dt"].dt.to_period("W")
    V={c:per.map({p:v for p,v in zip(lv.index.to_period("W"),lv[c].values)}).values for c in lv.columns}
    fl=np.where(tr[1:]!=tr[:-1])[0]+1; fl=[x for x in fl if not np.isnan(tr[x]) and not np.isnan(tr[x-1])]
    for k in range(len(fl)-1):
        i,j=fl[k],fl[k+1]
        if tr[i]<0: continue                      # только LONG
        p=V["P"][i]
        if np.isnan(p) or cl[i]<=p: continue      # long-bias: цена выше central P
        entry=cl[i]; yr=int(d["dt"].values[i].astype("datetime64[Y]").astype(int)+1970)
        end=min(len(tr),i+MAXHOLD+1)
        # baseline: держим до обратного флипа
        res["baseline_flip"].append(((cl[j]-entry)/entry*100,yr))
        # single-target R с защитой обратным флипом (что раньше)
        for rc,pname in (("R1","R1_flip"),("R2","R2_flip"),("R3","R3_flip")):
            R=V[rc][i]
            if np.isnan(R) or R<=entry: continue
            ex=None
            for m in range(i+1,min(j+1,end)):
                if tr[m]<0: ex=cl[m]; break        # обратный флип вниз
                if hi[m]>=R: ex=R; break           # TP на сопротивлении
            if ex is None: ex=cl[min(end-1,j)]
            res[pname].append(((ex-entry)/entry*100,yr))
        # R2 + структурный стоп swing-low
        R2=V["R2"][i]
        if not np.isnan(R2) and R2>entry:
            stop=lo[max(0,i-K):i+1].min()*(1-BUF)
            if stop<entry:
                ex=None
                for m in range(i+1,end):
                    if lo[m]<=stop: ex=stop; break
                    if hi[m]>=R2: ex=R2; break
                if ex is None: ex=cl[end-1]
                res["R2_struct"].append(((ex-entry)/entry*100,yr))
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
print(f"\n{'='*72}\natr_change Слой 9 (LONG, зеркало) · символов {len(syms)} · costs={COST}%")
print("  SHORT-эталон: Слой7 S2+флип +0.248 (4/5лет+) | Слой8 S2+структ +0.685 (3/5лет, 2025-only)")
def rep(name,lst):
    if not lst: print(f"  [{name:14s}] нет"); return
    a=np.array([x[0] for x in lst])-COST; ys={}
    for v,y in lst: ys.setdefault(y,[]).append(v)
    ystr=" ".join(f"{y}:{np.array(v).mean()-COST:+.2f}" for y,v in sorted(ys.items()))
    print(f"  [{name:14s}] n={len(a):6d} mean={a.mean():+.3f} median={np.median(a):+.2f} WR={100*(a>0).mean():.0f}% | {ystr}")
for p in POL: rep(p,res[p])
