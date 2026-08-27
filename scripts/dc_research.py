"""DC-RESEARCH: поиск новых стратегий в собственных данных"""
import sqlite3, json, statistics as st
from collections import defaultdict

conn=sqlite3.connect('subscriptions.db'); cur=conn.cursor()

# === 1. Инвертированные стратегии на чистой эре ===
print('=== INVERTED LEGACY (honest era >= July 11) ===')
for sig in ['atr_change','arch104','oko_ote','pivot_reversal','wt_signal','divergence','liquidity_sweep']:
    cur.execute("SELECT profit_pct,created_at FROM simulated_trades WHERE signal_type=? AND status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL",(sig,))
    rows=cur.fetchall()
    if len(rows)<30: continue
    inv=[-r[0] for r in rows]
    post=[-r[0] for r in rows if r[1] and r[1]>='2026-07-11']
    avg_inv=st.mean(inv)
    avg_post=st.mean(post) if len(post)>=5 else 0
    wr=sum(1 for p in inv if p>0)/len(inv)*100
    print(f'{sig:20} INV: n={len(inv):>5} avg={avg_inv:+.3f}% WR={wr:.0f}% | post_fix: n={len(post):>4} avg={avg_post:+.3f}%')

# === 2. BIG-фичи standalone в ote_nested ===
print()
print('=== BIG FEATURES as standalone (ote_nested) ===')
cur.execute("""SELECT s.profit_pct, tf.features_json FROM simulated_trades s
JOIN trade_features tf ON s.id=tf.trade_id
WHERE s.status IN ('SL','TP','TSL') AND s.signal_type='ote_nested' AND s.profit_pct IS NOT NULL""")
ote=cur.fetchall()
def has(fj,cat,feat):
    try: j=json.loads(fj); return j.get('context',{}).get(cat,{}).get(feat,0)==1
    except: return False

for feat,label in [('pivot.pivot_near_S3_1D','near_S3_1D'),('smc.bear_fvg_overlap_1h','bear_FVG_ov_1h'),
                   ('smc.bull_fvg_overlap_1h','bull_FVG_ov_1h'),('wt.wt_ob_1d','wt_OB_1d'),
                   ('rsi.rsi_os_15m','rsi_OS_15m'),('wt.wt_ob_4h','wt_OB_4h'),
                   ('wt.wt_os_4h','wt_OS_4h'),('smc.discount_1h','discount_1h')]:
    cat,f=feat.split('.',1)
    match=[r[0] for r in ote if has(r[1],cat,f)]
    nomatch=[r[0] for r in ote if not has(r[1],cat,f)]
    if len(match)>=20:
        av=st.mean(match); wr=sum(1 for p in match if p>0)/len(match)*100
        big=sum(1 for p in match if p>=2.5)/len(match)*100
        av_no=st.mean(nomatch)
        print(f'OTE {label:20} n={len(match):>4} avg={av:+.3f}% WR={wr:.0f}% BIG>2.5={big:.0f}% | noF: {av_no:+.3f}%')

# === 3. Комбинация: BIG-фича + тренд ===
print()
print('=== COMBO: feature + EMA50>200 4h ===')
for feat,label in [('smc.bear_fvg_overlap_1h','bear_FVG+trend'),('wt.wt_ob_4h','WT_OB+trend'),('rsi.rsi_os_15m','RSI_OS+trend')]:
    cat,f=feat.split('.',1)
    match=[r[0] for r in ote if has(r[1],cat,f) and has(r[1],'trend','ema50_above_ema200_4h')]
    if len(match)>=10:
        av=st.mean(match); big=sum(1 for p in match if p>=2.5)/len(match)*100
        wr=sum(1 for p in match if p>0)/len(match)*100
        print(f'{label:25} n={len(match):>4} avg={av:+.3f}% WR={wr:.0f}% BIG={big:.0f}%')

conn.close()
