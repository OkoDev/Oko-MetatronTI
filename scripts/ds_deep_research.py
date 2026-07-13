"""BTC correlation + LONG-only + exit-at-first-profit analysis"""
import sqlite3, json, statistics as st, urllib.request, ssl
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np

conn=sqlite3.connect('subscriptions.db'); cur=conn.cursor()
conn2=sqlite3.connect('ohlcv_cache.db'); cur2=conn2.cursor()

# === 1. BTC CORRELATION ===
print('='*60)
print('BTC CORRELATION: ote_nested profit vs BTC move')
print('='*60)
cur2.execute("SELECT time, close FROM ohlcv_cache WHERE symbol='BTC/USDT' AND timeframe='15m' ORDER BY time")
btc_rows=cur2.fetchall()
btc_df={r[0]:r[1] for r in btc_rows}; btc_times=sorted(btc_df.keys())

cur.execute("""SELECT s.profit_pct, s.created_at, s.direction FROM simulated_trades s
WHERE s.status IN ('SL','TP','TSL') AND s.signal_type='ote_nested' 
AND s.profit_pct IS NOT NULL AND s.created_at IS NOT NULL ORDER BY s.created_at""")
ote_rows=cur.fetchall()

btc_moves=[]
for pct,ts,dr in ote_rows:
    if not ts: continue
    try: t=datetime.fromisoformat(str(ts).replace('Z','+00:00')); t_ms=int(t.timestamp()*1000)
    except: continue
    closest=None
    for bt in btc_times:
        if bt<=t_ms: closest=bt
        else: break
    if closest:
        idx=btc_times.index(closest)
        if idx+4<len(btc_times):
            btc_entry=btc_df[closest]; btc_exit=btc_df[btc_times[idx+4]]
            btc_moves.append((pct,(btc_exit-btc_entry)/btc_entry*100,dr))

if btc_moves:
    pcts=[x[0] for x in btc_moves]; moves=[x[1] for x in btc_moves]
    corr=np.corrcoef(pcts,moves)[0,1]
    print(f'n={len(btc_moves)} corr(ote_profit, BTC_1h) = {corr:.4f}')
    
    for label,lo,hi in [('BTC dn>0.5%',-99,-0.5),('BTC flat',-0.5,0.5),('BTC up>0.5%',0.5,99)]:
        bp=[x[0] for x in btc_moves if lo<=x[1]<hi]; bd=[x for x in btc_moves if lo<=x[1]<hi]
        if len(bp)>=30:
            lng=[x[0] for x in bd if x[2]=='LONG']; sht=[x[0] for x in bd if x[2]=='SHORT']
            lng_s=f'n={len(lng)} avg={st.mean(lng):+.3f}%' if lng else ''
            sht_s=f'n={len(sht)} avg={st.mean(sht):+.3f}%' if sht else ''
            print(f'  {label:15} n={len(bp):>5} all={st.mean(bp):+.3f}% | LONG: {lng_s} | SHORT: {sht_s}')

# === 2. LONG-ONLY ===
print()
print('='*60)
print('LONG-ONLY DEEP DIVE')
print('='*60)
cur.execute("""SELECT s.symbol,s.direction,s.profit_pct,s.created_at,s.duration_minutes,s.confidence,tf.features_json
FROM simulated_trades s LEFT JOIN trade_features tf ON s.id=tf.trade_id
WHERE s.status IN ('SL','TP','TSL') AND s.signal_type='ote_nested' AND s.direction='LONG'
AND s.profit_pct IS NOT NULL AND tf.features_json IS NOT NULL""")
long_rows=cur.fetchall()
long_nets=[r[2] for r in long_rows]
print(f'LONG: n={len(long_rows)} avg={st.mean(long_nets):+.3f}% WR={sum(1 for p in long_nets if p>0)/len(long_nets)*100:.0f}%')

# OOS
s_long=sorted(long_rows,key=lambda r:r[3] if r[3] else ''); ml=int(len(s_long)*0.6)
oos_l=[r[2] for r in s_long[ml:]]; oos_avg=st.mean(oos_l) if oos_l else 0
print(f'LONG OOS: n={len(oos_l)} avg={oos_avg:+.3f}%')

# Best hours LONG
hour_l=defaultdict(list)
for r in long_rows:
    ts=r[3]
    if ts:
        try: h=datetime.fromisoformat(str(ts).replace('Z','+00:00')).hour
        except: h=-1
        if h>=0: hour_l[h].append(r[2])
print('Best LONG hours:')
ha=[(h,st.mean(nets),len(nets)) for h,nets in hour_l.items() if len(nets)>=20]
ha.sort(key=lambda x:-x[1])
for h,avg,n in ha[:8]: print(f'  {h:02d}:00 n={n:>4} avg={avg:+.3f}%')

# LONG by weekday
day_l=defaultdict(list); dn=['Mo','Tu','We','Th','Fr','Sa','Su']
for r in long_rows:
    ts=r[3]
    if ts:
        try: d=datetime.fromisoformat(str(ts).replace('Z','+00:00')).weekday(); day_l[d].append(r[2])
        except: pass
for d in range(7):
    nets=day_l[d]
    if nets: print(f'  {dn[d]} n={len(nets):>4} avg={st.mean(nets):+.3f}%')

# LONG by n_true
print('LONG by n_true:')
for th in [51,60,65,69,73]:
    above=[r for r in long_rows if r[6] and json.loads(r[6]).get('meta',{}).get('n_true',0)>=th]
    if len(above)>=20:
        nets=[r[2] for r in above]; avg=st.mean(nets)
        wr=sum(1 for p in nets if p>0)/len(nets)*100
        print(f'  n_true>={th:>2}: n={len(above):>4} avg={avg:+.3f}% WR={wr:.0f}%')

# === 3. EXIT AT FIRST PROFIT ===
print()
print('='*60)
print('EXIT AT FIRST PROFIT vs HOLD')
print('='*60)
cur.execute("""SELECT s.profit_pct,s.first_profit_r,s.R_multiple,s.duration_minutes
FROM simulated_trades s WHERE s.status IN ('SL','TP','TSL') AND s.signal_type='ote_nested'
AND s.profit_pct IS NOT NULL AND s.first_profit_r IS NOT NULL AND s.first_profit_r>0""")
fp_rows=cur.fetchall()
if fp_rows:
    fp_r=[r[1] for r in fp_rows]; fin_r=[r[3] for r in fp_rows if r[3] is not None]
    fin_pct=[r[0] for r in fp_rows]
    print(f'n={len(fp_rows)} trades with first_profit>0')
    print(f'first_profit_R avg={st.mean(fp_r):+.3f}R')
    print(f'final_profit_pct avg={st.mean(fin_pct):+.3f}%')
    # Сколько сделок где first_profit_r > финальный R * 0.7?
    better=sum(1 for r in fp_rows if r[3] and r[1]>r[3]*0.7)
    print(f'First > 70% of Final: {better}/{len(fp_rows)} ({better/len(fp_rows)*100:.0f}%)')
    
    # По first_profit_r бакетам
    for lo,hi,label in [(0,0.3,'0-0.3R'),(0.3,0.5,'0.3-0.5R'),(0.5,0.7,'0.5-0.7R'),(0.7,1.0,'0.7-1R'),(1.0,99,'>1R')]:
        b=[r for r in fp_rows if lo<=r[1]<hi]
        if len(b)>=15:
            f_avg_r=st.mean([r[1] for r in b])
            fn_avg_pct=st.mean([r[0] for r in b])
            print(f'  first={label}: n={len(b)} firstR={f_avg_r:.3f} finalPct={fn_avg_pct:+.3f}%')

# === 4. BTC.D + USDT.D (API) ===
print()
print('='*60)
print('BTC.D / MARKET CONTEXT (API)')
print('='*60)
try:
    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    req=urllib.request.Request('https://api.coingecko.com/api/v3/global')
    with urllib.request.urlopen(req,timeout=10,context=ctx) as r:
        data=json.loads(r.read())
    mcap=data['data']['market_cap_percentage']
    print(f"BTC.D: {mcap.get('btc','?')}%")
    print(f"ETH.D: {mcap.get('eth','?')}%")
    print(f"Total mcap: ${data['data']['total_market_cap']['usd']:,.0f}")
    
    req2=urllib.request.Request('https://api.alternative.me/fng/?limit=1')
    with urllib.request.urlopen(req2,timeout=10,context=ctx) as r:
        fg=json.loads(r.read())
    print(f"Fear & Greed: {fg['data'][0]['value']} ({fg['data'][0]['value_classification']})")
except Exception as e:
    print(f'API error: {e}')

conn.close(); conn2.close()
