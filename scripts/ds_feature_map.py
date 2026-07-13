"""FEATURE MAPS: индикаторные зависимости, корреляции, importance"""
import sqlite3, json, statistics as st
from collections import defaultdict, Counter
import numpy as np

conn=sqlite3.connect('subscriptions.db'); cur=conn.cursor()

# Все ote_nested с features
cur.execute("""SELECT s.profit_pct, s.direction, tf.features_json
FROM simulated_trades s
JOIN trade_features tf ON s.id=tf.trade_id
WHERE s.status IN ('SL','TP','TSL') AND s.signal_type='ote_nested' AND s.profit_pct IS NOT NULL
  AND tf.features_json IS NOT NULL""")
rows=cur.fetchall()
print(f'Loaded: {len(rows)} trades with features\n')

# Собираем ВСЕ фичи в матрицу
all_features=set()
trade_features_list=[]
for pct,dr,fj in rows:
    feats=set()
    try:
        j=json.loads(fj); ctx=j.get('context',{})
        for cat in ['smc','trend','mom','rsi','wt','volume','pivot']:
            for k,v in ctx.get(cat,{}).items():
                if isinstance(v,(int,float)) and v==1:
                    fname=f'{cat}.{k}'
                    feats.add(fname); all_features.add(fname)
    except: pass
    trade_features_list.append((pct,dr,feats))

# Оставляем фичи с >=100 вхождений
feat_counts=Counter()
for _,_,feats in trade_features_list:
    for f in feats: feat_counts[f]+=1
common_features=sorted([f for f,c in feat_counts.items() if c>=100], key=lambda f:-feat_counts[f])
print(f'Common features (>100 trades): {len(common_features)}')

# === 1. FEATURE CORRELATION MATRIX (совместная встречаемость) ===
print('='*60)
print('FEATURE CO-OCCURRENCE MATRIX (top correlations)')
print('='*60)

# Строим матрицу N_trades x N_features
n_trades=len(trade_features_list); n_feats=len(common_features)
feat_to_idx={f:i for i,f in enumerate(common_features)}
matrix=np.zeros((n_trades,n_feats),dtype=np.int8)
for i,(_,_,feats) in enumerate(trade_features_list):
    for f in feats:
        if f in feat_to_idx: matrix[i,feat_to_idx[f]]=1

# Корреляции между фичами
print('Top 20 feature pairs (phi coefficient):')
correlations=[]
for i in range(n_feats):
    for j in range(i+1,n_feats):
        # Phi coefficient for binary
        a=matrix[:,i]; b=matrix[:,j]
        n11=np.sum(a&b); n10=np.sum(a&~b); n01=np.sum(~a&b); n00=np.sum(~a&~b)
        phi=(n11*n00-n10*n01)/np.sqrt((n11+n10)*(n11+n01)*(n00+n10)*(n00+n01)) if (n11+n10)*(n11+n01)*(n00+n10)*(n00+n01)>0 else 0
        if abs(phi)>0.3:
            correlations.append((common_features[i],common_features[j],phi,n11))

correlations.sort(key=lambda x:-abs(x[2]))
for f1,f2,phi,n in correlations[:25]:
    marker='+' if phi>0 else '-'
    print(f'  {marker} {f1:40} <-> {f2:40} phi={phi:+.3f} n={n}')

# === 2. FEATURE vs PROFIT CORRELATION (point-biserial) ===
print()
print('='*60)
print('FEATURE vs PROFIT CORRELATION (top discriminators)')
print('='*60)

profits=np.array([r[0] for r in trade_features_list])
feat_profit_corr=[]
for fname in common_features:
    idx=feat_to_idx[fname]; has_f=matrix[:,idx]==1
    if sum(has_f)<30: continue
    # Point-biserial
    with_f=profits[has_f]; without_f=profits[~has_f]
    if len(without_f)<30: continue
    diff=st.mean(with_f)-st.mean(without_f)
    # t-статистика для значимости
    n1=len(with_f); n2=len(without_f)
    s1=np.std(with_f,ddof=1); s2=np.std(without_f,ddof=1)
    se=np.sqrt(s1**2/n1+s2**2/n2) if s1>0 and s2>0 else 1
    t=diff/se if se>0 else 0
    feat_profit_corr.append((fname,diff,n1,with_f.mean(),without_f.mean(),abs(t)))

feat_profit_corr.sort(key=lambda x:-abs(x[1]))
print(f'{"feature":45} {"diff%":>8} {"withF":>8} {"withoutF":>8} {"n":>5} {"|t|":>5}')
print('-'*80)
for f,diff,n1,wf,wof,t in feat_profit_corr[:30]:
    marker='EDGE+' if diff>0.05 else 'EDGE-' if diff<-0.05 else ''
    print(f'{f:45} {diff:>+7.3f}% {wf:>+7.3f}% {wof:>+7.3f}% {n1:>5} {t:>5.1f} {marker}')

# === 3. COMBO MAP: топ-комбинации из 2-3 фич с лучшим avg% ===
print()
print('='*60)
print('FEATURE COMBO MAP (pairs with highest avg%)')
print('='*60)

combo2=defaultdict(list)
for pct,dr,feats in trade_features_list:
    flist=sorted([f for f in feats if f in feat_to_idx])
    for i in range(len(flist)):
        for j in range(i+1,len(flist)):
            key=f'{flist[i]} + {flist[j]}'
            combo2[key].append(pct)

combo2_stats=[]
for key,nets in combo2.items():
    if len(nets)>=30:
        avg=st.mean(nets); wr=sum(1 for p in nets if p>0)/len(nets)*100
        combo2_stats.append((key,len(nets),avg,wr))

combo2_stats.sort(key=lambda x:-x[2])
print('Top-20 feature pairs:')
for key,n,avg,wr in combo2_stats[:20]:
    print(f'  n={n:>4} avg={avg:+.3f}% WR={wr:.0f}% | {key}')

print()
print('Bottom-10 feature pairs:')
for key,n,avg,wr in combo2_stats[-10:]:
    print(f'  n={n:>4} avg={avg:+.3f}% WR={wr:.0f}% | {key}')

# === 4. DECISION TREE (простейший: greedy top split) ===
print()
print('='*60)
print('DECISION TREE: greedy 2-level split')
print('='*60)

def best_split(trades_subset, features_list, depth=0, prefix=''):
    if len(trades_subset)<50 or depth>=2: return
    profits_sub=np.array([t[0] for t in trades_subset])
    base_avg=profits_sub.mean()
    
    best_diff=0; best_feat=None; best_left=None; best_right=None
    for fname in features_list:
        idx=feat_to_idx.get(fname)
        if idx is None: continue
        # Get indices for this subset
        left=[t for i,t in enumerate(trades_subset) if t[2] and fname in t[2]]
        right=[t for t in trades_subset if fname not in t[2]]
        if len(left)<20 or len(right)<20: continue
        left_avg=np.array([t[0] for t in left]).mean()
        right_avg=np.array([t[0] for t in right]).mean()
        diff=abs(left_avg-right_avg)
        if diff>best_diff:
            best_diff=diff; best_feat=fname; best_left=left; best_right=right
    
    if best_feat and best_diff>0.1:
        left_avg=np.array([t[0] for t in best_left]).mean()
        right_avg=np.array([t[0] for t in best_right]).mean()
        print(f'{prefix} {best_feat}:')
        print(f'{prefix}   HAS: n={len(best_left):>4} avg={left_avg:+.3f}%')
        print(f'{prefix}   NO:  n={len(best_right):>4} avg={right_avg:+.3f}%')
        best_split(best_left, features_list, depth+1, prefix+'  ')
        best_split(best_right, features_list, depth+1, prefix+'  ')

# Top features for split
top_disc=[f for f,_,_,_,_,_ in feat_profit_corr[:20]]
best_split(trade_features_list, top_disc)

conn.close()
