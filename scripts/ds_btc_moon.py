"""BTC extremes vs moon phases"""
import sqlite3, math, statistics as st
from collections import defaultdict
from datetime import datetime, timedelta

def moon_phase(date):
    y,m=date.year,date.month
    if m<=2: y-=1; m+=12
    A=y//100; B=2-A+A//4
    jd=int(365.25*(y+4716))+int(30.6001*(m+1))+date.day+B-1524.5
    return ((jd-2451550.1)/29.53058867)%1.0

def phase_name(p):
    if p<0.0625 or p>0.9375: return 'New Moon'
    elif 0.4375<=p<0.5625: return 'Full Moon'
    elif 0.1875<=p<0.3125: return '1st Quarter'
    elif 0.6875<=p<0.8125: return '3rd Quarter'
    else: return 'Other'

conn2=sqlite3.connect('ohlcv_cache.db'); cur2=conn2.cursor()

# BTC 4h
for fmt in ['BTC/USDT','binance:BTC/USDT','bingx:BTC/USDT:USDT']:
    cur2.execute('SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time',(fmt,'4h'))
    btc=cur2.fetchall()
    if btc: break

dates=[datetime.fromtimestamp(r[0]/1000) for r in btc]; closes=[r[3] for r in btc]
print(f'BTC 4h bars: {len(btc)} ({dates[0].date()} to {dates[-1].date()})')

# Extremes (window 12 bars = 2 days)
extremes=[]
for i in range(12,len(btc)-12):
    hi=btc[i][1]; lo=btc[i][2]
    prev_hi=max(r[1] for r in btc[i-12:i]); next_hi=max(r[1] for r in btc[i+1:i+13])
    prev_lo=min(r[2] for r in btc[i-12:i]); next_lo=min(r[2] for r in btc[i+1:i+13])
    if hi>=prev_hi and hi>=next_hi: extremes.append((dates[i],'TOP',hi))
    if lo<=prev_lo and lo<=next_lo: extremes.append((dates[i],'BOTTOM',lo))

print(f'Local extremes: {len(extremes)}')

pe=defaultdict(list)
for dt,etype,price in extremes:
    pe[phase_name(moon_phase(dt))].append((etype,price))

for pn in ['New Moon','Full Moon','1st Quarter','3rd Quarter']:
    ex=pe.get(pn,[])
    tops=[e for e in ex if e[0]=='TOP']; bots=[e for e in ex if e[0]=='BOTTOM']
    t_avg=st.mean([t[1] for t in tops]) if tops else 0
    b_avg=st.mean([b[1] for b in bots]) if bots else 0
    print(f'{pn:15} n={len(ex):>3} TOPS={len(tops):>3} BOTTOMS={len(bots):>3} T_avg=${t_avg:,.0f} B_avg=${b_avg:,.0f}')

# BTC move around new/full moons
print('\n=== BTC MOVE around New/Full Moon (5 days) ===')
start=dates[0]; end=dates[-1]
new_moons=[]; full_moons=[]
cur=start
while cur<=end:
    ph=moon_phase(cur)
    if ph<0.02: new_moons.append(cur)
    if 0.48<ph<0.52: full_moons.append(cur)
    cur+=timedelta(hours=6)

for label,moons in [('New Moon',new_moons),('Full Moon',full_moons)]:
    moves=[]
    for md in moons:
        bef=[c for i,c in enumerate(closes) if dates[i]>=md-timedelta(days=5) and dates[i]<md]
        aft=[c for i,c in enumerate(closes) if dates[i]>=md and dates[i]<=md+timedelta(days=5)]
        if bef and aft: moves.append((aft[-1]/bef[0]-1)*100)
    if moves:
        avg=st.mean(moves); wr=sum(1 for m in moves if m>0)/len(moves)*100
        print(f'{label}: {len(moves)} events, avg_move={avg:+.2f}% WR={wr:.0f}%')
        for m in moves: print(f'  {m:+.1f}%')

# Now
now=datetime(2026,7,11); ph=moon_phase(now)
print(f'\nNOW: phase={ph:.3f} = {phase_name(ph)}')
for d in range(0,45):
    dt=now+timedelta(days=d); ph=moon_phase(dt)
    if ph<0.02 or (0.24<ph<0.26) or (0.48<ph<0.52) or (0.74<ph<0.76):
        print(f'  {dt.date()}: {phase_name(ph)}')

conn2.close()
