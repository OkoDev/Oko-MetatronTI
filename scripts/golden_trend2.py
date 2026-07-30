# -*- coding: utf-8 -*-
"""TREND + ER-GATE: спасёт ли причинный ER-гейт трендследование в чоп-году? Тюним ER-порог+ATRTrend."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.10
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def atrt(df,period,factor):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
def ER(close,n=48):
    c=pd.Series(close); return (c.diff(n).abs()/c.diff().abs().rolling(n).sum().replace(0,np.nan)).fillna(0).values
def legs(df,period,factor,er_thr,er_n):
    """ATRTrend-флип = сделка, вход только если ER>=er_thr (трендовый режим). Выход на противофлипе."""
    tr_=atrt(df,period,factor); C=df.close.values; er=ER(C,er_n); T=pd.to_datetime(df.time,unit="ms").dt.year.values
    out=[]; entry=None; side=0; ei=0
    for i in range(max(period,er_n)+1,len(df)):
        if tr_[i]!=tr_[i-1]:
            if entry is not None:
                out.append((int(T[ei]),side*(C[i]-entry)/entry*100-COST))
            if er[i]>=er_thr:  # вход только в трендовом режиме
                entry=C[i]; side=int(tr_[i]); ei=i
            else:
                entry=None
    return out
def rep(name,rows):
    if len(rows)<15: print(f"  {name:34} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    wins=r[r>0]; loss=r[r<=0]; pf=(wins.sum()/abs(loss.sum())) if len(loss) and loss.sum() else 9
    flag="🟢🟢" if(r.sum()>0 and srt[:-cut].sum()>0 and pf>1.15) else("🟡" if r.sum()>0 else "🔴")
    print(f"  {name:34} n={len(r):4} WR{100*(r>0).mean():2.0f}% сум{r.sum():+.0f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 90",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · 4h ATRTrend-ride + ER-гейт входа · тюнинг ER-порога")
# кэш загрузок
DFS={s:load(s,"4h",t0).reset_index(drop=True) for s in syms}
DFS={s:d for s,d in DFS.items() if len(d)>=300}
print(f"с данными: {len(DFS)}")
for period,factor in [(10,2.0),(10,3.0)]:
    print(f"\n═══ ATRTrend({period},{factor}) 4h ═══")
    for er_thr in [0.0,0.30,0.40,0.50]:
        allr=[]
        for s,d in DFS.items(): allr+=legs(d,period,factor,er_thr,48)
        tag=f"ER≥{er_thr}" if er_thr>0 else "без гейта"
        rep(f"{tag} ВСЕ",allr)
        rep(f"  └2024",[x for x in allr if x[0]==2024]); rep(f"  └2025-26 OOS",[x for x in allr if x[0]>=2025])
