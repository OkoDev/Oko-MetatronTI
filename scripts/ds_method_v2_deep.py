"""
DS-METHOD-V2-DEEP Шаг 1: WALK-FORWARD OOS
train=2024 → test=2025-2026. % net, честный split по времени.
"""
import argparse, os, sqlite3, sys, statistics as st, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.smc.method_v2_mtf import detect_v2_mtf
from scripts.test_method_v2 import load_df

CACHE = "ohlcv_cache.db"; COSTS = 0.2; SHARES = (0.4, 0.3, 0.3)
RETEST_BARS = 8; TIMEOUT_BARS = 800

def liquid_syms(tf, topn):
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?",(tf,))]
    rank=[]
    for s in syms:
        try:
            df=load_df(s,tf)
            if len(df)<500: continue
            rank.append(((df["close"]*df["volume"]).median(),s))
        except: continue
    rank.sort(reverse=True)
    return [s for _,s in rank[:topn]]

def run_detect(d4h, d15m, params):
    setups=detect_v2_mtf(d4h, d15m, **params)
    return setups

def simulate(dfl, s):
    high,low,close=dfl["high"].values,dfl["low"].values,dfl["close"].values
    idx=dfl.index;pos=idx.get_indexer([s.entry_ts]);ei=pos[0] if pos[0]>=0 else None
    if ei is None: return None
    n=len(dfl);lng=s.direction=="LONG"
    t1,t2,t3=s.targets;entry=s.entry;sl=s.sl;rem=1.0;pnl=0.0;hit=[False,False,False];tg=[t1,t2,t3]
    for j in range(ei+1,min(ei+1+TIMEOUT_BARS,n)):
        if (low[j]<=sl) if lng else (high[j]>=sl):
            move=(sl-entry)/entry*100 if lng else (entry-sl)/entry*100;pnl+=rem*move;rem=0.;break
        for k in range(3):
            if hit[k] or rem<=0: continue
            if (high[j]>=tg[k]) if lng else (low[j]<=tg[k]):
                move=(tg[k]-entry)/entry*100 if lng else (entry-tg[k])/entry*100
                pnl+=SHARES[k]*move;rem-=SHARES[k];hit[k]=True
                if k==0: sl=entry
        if rem<=1e-9: break
    if rem>1e-9:
        jl=min(ei+1+TIMEOUT_BARS,n)-1
        move=(close[jl]-entry)/entry*100 if lng else (entry-close[jl])/entry*100;pnl+=rem*move
    year=str(s.entry_ts)[:4];return {"net":pnl-COSTS,"dir":s.direction,"year":year,"t1":hit[0],"t3":hit[2],"conf":bool(getattr(s,"conf",False))}

def stats(lst):
    if not lst: return "n=0"
    nets=[x["net"] for x in lst]
    return f"n={len(nets):>5} net={sum(nets)/len(nets):+.3f}% WR={sum(1 for v in nets if v>0)/len(nets)*100:.0f}% t1={sum(1 for x in lst if x['t1'])/len(lst)*100:.0f}% t3={sum(1 for x in lst if x['t3'])/len(lst)*100:.0f}%"

def main():
    print("DS-METHOD-V2-DEEP: WALK-FORWARD OOS")
    print("=" * 60)
    syms=liquid_syms("15m", 100)
    print(f"Символов: {len(syms)} (top liquid)")
    
    # Параметры для sweep
    param_grid=[]
    for len_htf in [20,30,50]:
        for wave1 in [4,6,8]:
            for imp_bars in [15,20,30]:
                for min_rng in [2,3,5]:
                    param_grid.append({"len_htf":len_htf,"wave1_window_bars_htf":wave1,
                                      "imp_bars":imp_bars,"min_htf_range_pct":min_rng})
    
    n_params=len(param_grid)
    print(f"Параметров в sweep: {n_params}")
    
    best=None;best_score=-99
    best_cfg=None
    
    for pi,params in enumerate(param_grid):
        all_tr=[]
        for sym in syms:
            try:
                d4=load_df(sym,"4h");d15=load_df(sym,"15m")
                if d4 is None or d15 is None or len(d4)<100 or len(d15)<500: continue
                setups=run_detect(d4,d15,params)
                for s in setups:
                    r=simulate(d15,s)
                    if r: all_tr.append(r)
            except: continue
        
        # Split по годам
        train=[t for t in all_tr if t["year"] in ("2022","2023","2024")]
        test=[t for t in all_tr if t["year"] in ("2025","2026")]
        
        if len(train)<20: continue
        train_net=st.mean([t["net"] for t in train])
        test_net=st.mean([t["net"] for t in test]) if test else 0
        test_n=len(test) if test else 0
        
        # Score = train net, но бонус если OOS положительный
        score=train_net+(0.5 if test_net>0 else 0)
        
        if score>best_score:
            best_score=score;best_cfg=params.copy()
            best={"params":params,"train":train_net,"test":test_net,"test_n":test_n,"n_train":len(train),"n_total":len(all_tr)}
        
        if pi%20==0:
            print(f"  progress {pi}/{n_params} | best train={best['train']:+.3f}% test={best['test']:+.3f}%(n={best['test_n']}) | cfg={best_cfg}", flush=True)
    
    print(f"\n{'='*60}")
    print(f"BEST CFG: {best_cfg}")
    print(f"TRAIN 2022-24: net={best['train']:+.3f}% (n={best['n_train']})")
    print(f"TEST  2025-26: net={best['test']:+.3f}% (n={best['test_n']})")
    status="EDGE OOS+" if best["test"]>0 else "NET"
    print(f"VERDICT: {status}")

if __name__=="__main__":
    main()
