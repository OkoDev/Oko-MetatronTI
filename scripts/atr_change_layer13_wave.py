"""Слой 13 — R2/S2-отбой + ВОЛНОВОЙ фильтр фазы (Elliott). % net (ЗАКОН №1).
Гипотеза: вход только когда у R2 завершился 5-волновой bull-импульс (исчерпан) / у S2 bear-импульс.
Стоп за вершину волны 5 (структура, цена уже развернулась). Сравнить R2/S2-отбой без волны vs +волна.
Детектор: detect_elliott_impulse(zigzag_atr(df,11,dev)). ts=bar index (RangeIndex)."""
import os,sys,sqlite3,warnings; warnings.filterwarnings("ignore")
sys.path.insert(0,"e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np,pandas as pd
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse
CACHE="ohlcv_cache.db"; COST=0.20; BUF=0.003; MAXHOLD=60; WIN=10; DEV=5.0
conn=sqlite3.connect(CACHE,timeout=60)
syms=[r[0] for r in conn.execute("SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]
res={"Sh_R2_base":[],"Sh_R2_wave":[],"Lo_S2_base":[],"Lo_S2_wave":[]}
for sym in syms:
    d=pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",conn,params=(sym,))
    if d is None or len(d)<300: continue
    dt=pd.to_datetime(d["time"],unit="ms",utc=True)
    df=d[["high","low","close"]].copy(); df.index=range(len(df))   # RangeIndex → ts=bar idx
    # волновые импульсы
    try:
        imps=detect_elliott_impulse(zigzag_atr(df,11,DEV))
    except Exception:
        imps=[]
    up_tops=[(int(im["waves"][5][0]),float(im["waves"][5][1])) for im in imps if im["direction"]=="up"]
    dn_bots=[(int(im["waves"][5][0]),float(im["waves"][5][1])) for im in imps if im["direction"]=="down"]
    # недельные уровни
    dw=pd.DataFrame({"high":d["high"],"low":d["low"],"close":d["close"]}); dw.index=dt
    wk=dw.resample("W").agg(H=("high","max"),L=("low","min"),C=("close","last"))
    P=(wk["H"]+wk["L"]+wk["C"])/3.0; rng=wk["H"]-wk["L"]
    lvw=pd.DataFrame({"P":P,"R1":2*P-wk["L"],"R2":P+rng,"S1":2*P-wk["H"],"S2":P-rng}).shift(1)
    per=dt.dt.to_period("W")
    V={c:per.map({p:v for p,v in zip(lvw.index.to_period("W"),lvw[c].values)}).values for c in lvw.columns}
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; N=len(cl)
    yrs=dt.values.astype("datetime64[Y]").astype(int)+1970
    def sim_short(i,entry,stop,tg):
        end=min(N,i+MAXHOLD+1)
        for m in range(i+1,end):
            if hi[m]>=stop: return (entry-stop)/entry*100
            if lo[m]<=tg: return (entry-tg)/entry*100
        return (entry-cl[end-1])/entry*100
    def sim_long(i,entry,stop,tg):
        end=min(N,i+MAXHOLD+1)
        for m in range(i+1,end):
            if lo[m]<=stop: return (entry-stop)/entry*100*-1
            if hi[m]>=tg: return (tg-entry)/entry*100
        return (cl[end-1]-entry)/entry*100
    for i in range(1,N-1):
        yr=int(yrs[i])
        r2=V["R2"][i]; r1=V["R1"][i]
        if not(np.isnan(r2) or np.isnan(r1)) and hi[i]>=r2 and cl[i]<r2 and hi[i-1]<r2 and r1<cl[i]:
            entry=cl[i]
            # base: стоп за R3? нет — используем волновой если есть, иначе swing10 для base
            stop_base=hi[max(0,i-10):i+1].max()*(1+BUF)
            if stop_base>entry:
                res["Sh_R2_base"].append((sim_short(i,entry,stop_base,r1),yr))
            # wave: рядом завершённый bull-импульс (вершина в окне [i-WIN,i])
            top=[(tb,tp) for tb,tp in up_tops if i-WIN<=tb<=i]
            if top:
                tp_price=max(t[1] for t in top)      # вершина волны 5
                stop_w=max(tp_price,hi[i])*(1+BUF)
                if stop_w>entry:
                    res["Sh_R2_wave"].append((sim_short(i,entry,stop_w,r1),yr))
        s2=V["S2"][i]; s1=V["S1"][i]
        if not(np.isnan(s2) or np.isnan(s1)) and lo[i]<=s2 and cl[i]>s2 and lo[i-1]>s2 and s1>cl[i]:
            entry=cl[i]
            stop_base=lo[max(0,i-10):i+1].min()*(1-BUF)
            if stop_base<entry:
                res["Lo_S2_base"].append((sim_long(i,entry,stop_base,s1),yr))
            bot=[(tb,tp) for tb,tp in dn_bots if i-WIN<=tb<=i]
            if bot:
                bt_price=min(t[1] for t in bot)
                stop_w=min(bt_price,lo[i])*(1-BUF)
                if stop_w<entry:
                    res["Lo_S2_wave"].append((sim_long(i,entry,stop_w,s1),yr))
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
print(f"\n{'='*74}\nСлой 13 R2/S2-отбой + ВОЛНОВОЙ фильтр (Elliott dev={DEV}, окно {WIN}) · costs={COST}%")
def rep(name,lst):
    if not lst: print(f"  [{name:12s}] нет"); return
    a=np.array([x[0] for x in lst])-COST; ys={}
    for v,y in lst: ys.setdefault(y,[]).append(v)
    ystr=" ".join(f"{y}:{np.array(v).mean()-COST:+.2f}" for y,v in sorted(ys.items()))
    print(f"  [{name:12s}] n={len(a):5d} mean={a.mean():+.3f} med={np.median(a):+.2f} WR={100*(a>0).mean():.0f}% | {ystr}")
for k in ("Sh_R2_base","Sh_R2_wave","Lo_S2_base","Lo_S2_wave"): rep(k,res[k])
