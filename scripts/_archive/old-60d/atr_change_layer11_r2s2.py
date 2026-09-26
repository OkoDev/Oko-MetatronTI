"""Слой 11 — R2/S2-отбой (гипотеза ИЗ данных pivot_behavior_map). % net (ЗАКОН №1).
SHORT от R2 (bounce62%), цель R1/P, стоп за R3. LONG от S2 (bounce69%), цель S1/P, стоп за S3.
Стоп за СЛЕДУЮЩИЙ уровень (не тугой за R2/S2 — свит-урок). Дедуп первое касание. По годам+режим."""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0,"e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np, pandas as pd
CACHE="ohlcv_cache.db"; COST=0.20; BUF=0.003; MAXHOLD=60
conn=sqlite3.connect(CACHE,timeout=60)
syms=[r[0] for r in conn.execute("SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]
# (name, entry_lvl, stop_lvl, dir, target)
SETUPS=[("Sh R2>R1","R2","R3","short","R1"),("Sh R2>P","R2","R3","short","P"),
        ("Lo S2>S1","S2","S3","long","S1"),("Lo S2>P","S2","S3","long","P")]
res={s[0]:[] for s in SETUPS}
for sym in syms:
    d=pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",conn,params=(sym,))
    if d is None or len(d)<300: continue
    d["dt"]=pd.to_datetime(d["time"],unit="ms",utc=True); d["wk"]=d["dt"].dt.to_period("W")
    g=d.set_index("dt"); wk=g.resample("W").agg(H=("high","max"),L=("low","min"),C=("close","last"))
    P=(wk["H"]+wk["L"]+wk["C"])/3.0; rng=wk["H"]-wk["L"]
    lvw=pd.DataFrame({"P":P,"R1":2*P-wk["L"],"R2":P+rng,"R3":wk["H"]+2*(P-wk["L"]),
        "S1":2*P-wk["H"],"S2":P-rng,"S3":wk["L"]-2*(wk["H"]-P)}).shift(1)
    Pp=P.shift(1); Pp2=P.shift(2)
    per=d["dt"].dt.to_period("W")
    V={c:per.map({p:v for p,v in zip(lvw.index.to_period("W"),lvw[c].values)}).values for c in lvw.columns}
    reg=per.map({p:("BULL" if (not np.isnan(a) and not np.isnan(b) and a>b) else "BEAR") for p,a,b in zip(Pp.index.to_period("W"),Pp.values,Pp2.values)}).values
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; N=len(cl)
    yrs=d["dt"].values.astype("datetime64[Y]").astype(int)+1970
    for name,elvl,slvl,dirn,tlvl in SETUPS:
        E=V[elvl]; S=V[slvl]; T=V[tlvl]
        for i in range(1,N-1):
            e=E[i]; st=S[i]; tg=T[i]
            if np.isnan(e) or np.isnan(st) or np.isnan(tg): continue
            if dirn=="short":
                if not (hi[i]>=e and cl[i]<e and hi[i-1]<e): continue
                entry=cl[i]; stop=st*(1+BUF)
                if stop<=entry or tg>=entry: continue
            else:
                if not (lo[i]<=e and cl[i]>e and lo[i-1]>e): continue
                entry=cl[i]; stop=st*(1-BUF)
                if stop>=entry or tg<=entry: continue
            end=min(N,i+MAXHOLD+1); ex=None
            for m in range(i+1,end):
                if dirn=="short":
                    if hi[m]>=stop: ex=stop; break
                    if lo[m]<=tg: ex=tg; break
                else:
                    if lo[m]<=stop: ex=stop; break
                    if hi[m]>=tg: ex=tg; break
            if ex is None: ex=cl[end-1]
            pnl=((entry-ex) if dirn=="short" else (ex-entry))/entry*100
            res[name].append((pnl,int(yrs[i]),reg[i]))
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
print(f"\n{'='*76}\nСлой 11 R2/S2-отбой (стоп за R3/S3) · {len(syms)} симв · costs={COST}%")
def rep(name,lst):
    if not lst: print(f"  [{name:10s}] нет"); return
    a=np.array([x[0] for x in lst])-COST
    ys={}; rgs={"BULL":[],"BEAR":[]}
    for v,y,rg in lst: ys.setdefault(y,[]).append(v); rgs[rg].append(v)
    ystr=" ".join(f"{y}:{np.array(v).mean()-COST:+.2f}" for y,v in sorted(ys.items()))
    rstr=" ".join(f"{k}:{np.array(v).mean()-COST:+.3f}(n{len(v)})" for k,v in rgs.items() if v)
    print(f"  [{name:10s}] n={len(a):6d} mean={a.mean():+.3f} med={np.median(a):+.2f} WR={100*(a>0).mean():.0f}% | {ystr} | {rstr}")
for s in SETUPS: rep(s[0],res[s[0]])
