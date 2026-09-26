"""Тест находки Егора: MTF-согласование входа (4h-сетап валиден только если 1h той же стороны).
Мера % net (ЗАКОН №1). Изолирует эффект: aligned vs unaligned vs all. Выход фикс = 1R (не варьируем).
⚠️ ote_retest_setups на полном df = look-ahead; относительное сравнение (aligned vs all) устойчивее."""
import os,sys,sqlite3,warnings; warnings.filterwarnings("ignore")
sys.path.insert(0,"e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np, pandas as pd
from core.smc.smc_engine import ote_retest_setups
CACHE="ohlcv_cache.db"; COST=0.20; MAXHOLD=120
def load(conn,sym,tf):
    for pref in ("binance:","bingx:",""):
        d=pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",conn,params=(pref+sym,tf))
        if len(d)>100:
            d.index=pd.to_datetime(d["time"],unit="ms",utc=True); return d[["open","high","low","close"]].astype(float)
    return None
conn=sqlite3.connect(CACHE,timeout=60)
syms=[r[0].split(":")[-1] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='4h'").fetchall()]
syms=sorted(set(syms))[:200]
res={"all":[], "aligned":[], "unaligned":[]}
nsym=0
for sym in syms:
    d4=load(conn,sym,"4h"); d1=load(conn,sym,"1h")
    if d4 is None or d1 is None or len(d4)<200: continue
    try:
        s4=ote_retest_setups(d4,only_choch=False); s1=ote_retest_setups(d1,only_choch=False)
    except Exception: continue
    if not s4: continue
    nsym+=1
    hi=d4["high"].values; lo=d4["low"].values; cl=d4["close"].values
    idx={ts:i for i,ts in enumerate(d4.index)}
    for sh in s4:
        D=sh["direction"]; olo,ohi=sh["ote"]; ct=sh["choch_ts"]; sl=sh["sl"]
        ci=idx.get(ct)
        if ci is None: continue
        entry=(olo+ohi)/2; risk=abs(entry-sl)
        if risk<=0: continue
        # ретест: первый 4h бар после choch, где цена входит в зону
        ei=None
        for j in range(ci+1,min(ci+1+40,len(d4))):
            if lo[j]<=ohi and hi[j]>=olo: ei=j; break
        if ei is None: continue
        tp=entry+risk if D=="long" else entry-risk
        end=min(len(d4),ei+MAXHOLD); pnl=None
        for m in range(ei+1,end):
            if D=="long":
                if lo[m]<=sl: pnl=-abs(entry-sl)/entry*100; break
                if hi[m]>=tp: pnl=abs(tp-entry)/entry*100; break
            else:
                if hi[m]>=sl: pnl=-abs(entry-sl)/entry*100; break
                if lo[m]<=tp: pnl=abs(tp-entry)/entry*100; break
        if pnl is None: pnl=(cl[end-1]-entry)/entry*100*(1 if D=="long" else -1)
        # MTF-согласование: есть ли 1h-сетап той же стороны с choch близко к 4h choch
        aligned = any(x["direction"]==D and abs((x["choch_ts"]-ct).total_seconds())<=6*3600*8 for x in s1)
        res["all"].append(pnl)
        res["aligned" if aligned else "unaligned"].append(pnl)
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
print(f"MTF-alignment тест · {nsym} символов · выход 1R · costs={COST}%")
for k in ("all","aligned","unaligned"):
    a=np.array(res[k])-COST
    if len(a): print(f"  {k:10s} n={len(a):5d} mean%net={a.mean():+.3f} WR={100*(a>0).mean():.0f}% median={np.median(a):+.3f}")
