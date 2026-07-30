# -*- coding: utf-8 -*-
"""GOLDEN TREND (Егор 30.07 «70% движений тренд, найди и в тренде») — трендовый эдж, ПРИЧИННО.
Ключ: трейлинг-выход (ATRTrend = встроенный трейл, ловит хвост), НЕ фикс-TP. Валидация для ТРЕНДА:
сумма + хрупкость(топ-10%) + profit-factor + OOS (медиана у тренда минус по природе — не требуем)."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.10
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def atrt(df,period=10,factor=3.0):  # классический supertrend для тренда (period/factor тюним)
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values
    tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df)); tl=up.copy()
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]
        td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
        tl[i]=tu[i] if tr_[i]>0 else td[i]   # трейл-линия
    return tr_,tl
def legs(df,period,factor):
    """Каждый флип ATRTrend = сделка. Вход на закрытии флип-бара, выход на противоположном флипе.
    net% по стороне. → list (year, net%)."""
    tr_,tl=atrt(df,period,factor); C=df.close.values; T=pd.to_datetime(df.time,unit="ms").dt.year.values
    out=[]; entry=None; side=0; ei=0
    for i in range(1,len(df)):
        if tr_[i]!=tr_[i-1]:  # флип
            if entry is not None:
                net=side*(C[i]-entry)/entry*100-COST
                out.append((int(T[ei]),net))
            entry=C[i]; side=int(tr_[i]); ei=i
    return out
def rep(name,rows):
    if len(rows)<20: print(f"  {name:26} n={len(rows)} мало"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r)
    cut=max(1,len(r)//10); frag=srt[:-cut].sum()  # убрать топ-10%
    wins=r[r>0]; loss=r[r<=0]; pf=(wins.sum()/abs(loss.sum())) if len(loss) and loss.sum()!=0 else 9
    aw=wins.mean() if len(wins) else 0; al=loss.mean() if len(loss) else 0
    flag="🟢🟢" if (r.sum()>0 and frag>0 and pf>1.15) else("🟡" if r.sum()>0 else "🔴")
    print(f"  {name:26} n={len(r):4} WR{100*(r>0).mean():2.0f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% PF{pf:.2f} безтоп10%{frag:+.0f}% побед{aw:+.1f}/лось{al:+.1f} {flag}")

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
split=2025  # OOS: год>=2025.5 сложно по легам; сплитуем по годам: train 2024, test 2025-26
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 90",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · трейлинг-выход по ATRTrend-флипу · косты {COST}%")
for tf in ("4h","1d"):
    print(f"\n═══ {tf} ═══")
    for period,factor in [(10,3.0),(10,2.0),(20,3.0),(7,3.0)]:
        allr=[]
        for sym in syms:
            d=load(sym,tf,t0)
            if len(d)<300: continue
            allr+=legs(d.reset_index(drop=True),period,factor)
        tr_all=[x for x in allr]
        rep(f"ATRTrend({period},{factor}) ВСЕ", tr_all)
        rep(f"  └ 2024(train)", [x for x in allr if x[0]==2024])
        rep(f"  └ 2025-26(OOS)", [x for x in allr if x[0]>=2025])
