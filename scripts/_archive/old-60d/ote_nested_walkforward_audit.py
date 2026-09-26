"""Walk-forward аудит ote_nested: HTF-OTE-зона на ПРЕФИКСЕ df_h[:t_entry] vs полный df.
Вопрос Егора: не заражён ли ЖИВОЙ ote_nested тем же look-ahead, что волновой фильтр?
Full-df (как honest_test) собирает входы+pnl. Для каждого входа пересчёт HTF-зоны на данных
ДО момента входа: survive если сетап с тем же choch_ts/direction и OTE содержит entry существует
в реальном времени. Сравнить mean/WR full vs walk-forward-survivors + survive-rate."""
import os,sys,sqlite3,warnings; warnings.filterwarnings("ignore")
sys.path.insert(0,"e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np,pandas as pd
from scripts.ote_nested_honest_test import _load, TF_MIN, HTF_HOLD_BARS, _ltf_entry_R
from core.smc.smc_engine import zigzag_atr, find_setups_zz
PAIRS=[("4h","15m"),("1h","15m"),("4h","1h")]
conn=sqlite3.connect("ohlcv_cache.db",timeout=60)
syms=[r[0] for r in conn.execute("SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='15m' GROUP BY symbol HAVING c>=2000 ORDER BY symbol LIMIT 60")]
from collections import defaultdict
full=[]; surv=[]; n_in=0
for si,sym in enumerate(syms):
    cache={}
    def get(tf):
        if tf not in cache: cache[tf]=_load(conn,sym,tf)
        return cache[tf]
    for htf,ltf in PAIRS:
        df_h=get(htf); df_l=get(ltf)
        if df_h is None or df_l is None or len(df_h)<100 or len(df_l)<300: continue
        try:
            setups_h=find_setups_zz(zigzag_atr(df_h),df_h)
            setups_l=find_setups_zz(zigzag_atr(df_l),df_l)
        except Exception: continue
        if not setups_h or not setups_l: continue
        posL={ts:i for i,ts in enumerate(df_l.index)}
        hold=pd.Timedelta(minutes=HTF_HOLD_BARS*TF_MIN[htf])
        for s_h in setups_h:
            D=s_h["direction"]; htf_lo,htf_hi=s_h["ote"]; h_ts=s_h["choch_ts"]; w_end=h_ts+hold
            for s_l in setups_l:
                if s_l["direction"]!=D or not(h_ts<s_l["choch_ts"]<=w_end): continue
                r=_ltf_entry_R(s_l,df_l,posL,htf_lo,htf_hi,D,TF_MIN[ltf],None,None,"off",None,None,False)
                if r is None: continue
                entry=(s_l["ote"][0]+s_l["ote"][1])/2.0
                pnl=r.get("tp1"); pnl2=r.get("struct_choch_tp1")
                if pnl is None: break
                t_entry=r["ts"]; n_in+=1
                full.append((pnl,pnl2))
                # WALK-FORWARD: HTF-зона на префиксе до входа
                dfh_pre=df_h[df_h.index<=t_entry]
                if len(dfh_pre)<100: break
                try:
                    sh_wf=find_setups_zz(zigzag_atr(dfh_pre),dfh_pre)
                except Exception:
                    sh_wf=[]
                alive=any(x["direction"]==D and x["choch_ts"]==h_ts
                          and x["ote"][0]<=entry<=x["ote"][1] for x in sh_wf)
                if alive:
                    surv.append((pnl,pnl2))
                break
    if (si+1)%15==0: print(f"...{si+1}/{len(syms)} симв, входов={n_in}",flush=True)
conn.close()
sys.stdout.reconfigure(encoding="utf-8")
def stat(lst,idx):
    v=[x[idx] for x in lst if x[idx] is not None]
    if not v: return "нет"
    a=np.array(v); return f"n={len(a):5d} mean={a.mean():+.3f} WR={100*(a>0).mean():.0f}%"
print(f"\n{'='*66}\nWALK-FORWARD аудит ote_nested (HTF-зона на префиксе) · {len(syms)} симв")
print(f"  tp1:              FULL {stat(full,0)}")
print(f"                    WF   {stat(surv,0)}")
print(f"  struct_choch_tp1: FULL {stat(full,1)}")
print(f"                    WF   {stat(surv,1)}")
print(f"  → HTF-зона выжила walk-forward: {len(surv)}/{len(full)} = {100*len(surv)/max(1,len(full)):.0f}%")
