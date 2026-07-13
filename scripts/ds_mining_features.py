"""
DS-MINING-FEATURES: mining ЖИВЫХ закрытых сделок
Какие features_json-фичи отделяют +% net от −% net
Мера: % net (LAW №1), split по signal_type/direction/data-era
"""
import sqlite3, json, statistics as st
from collections import Counter, defaultdict

DB = "subscriptions.db"
MIN_TRADES = 30  # мин сделок для группы

def load():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    
    # Закрытые сделки
    cur.execute("""
        SELECT id, signal_type, direction, profit_pct, R_multiple, 
               max_R_possible, captured_R_pct, first_profit_r, first_drawdown_r,
               created_at, features_json, strategy_name, timeframe, symbol
        FROM simulated_trades
        WHERE status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL
    """)
    trades = {}
    for r in cur.fetchall():
        tid, stype, d, pct, R, maxR, capR, fpR, fdR, ts, fj, sname, tf, sym = r
        trades[tid] = {
            "id": tid, "signal": stype, "dir": d, "profit_pct": pct,
            "R": R or 0, "maxR": maxR or 0, "capR": capR or 0,
            "firstR": fpR or 0, "drawR": fdR or 0,
            "created_at": ts, "features_raw": fj,
            "strategy": sname or "", "tf": tf or "", "symbol": sym or "",
            "features_rich": {}
        }
    
    # Богатые features из trade_features
    cur.execute("""
        SELECT trade_id, features_json FROM trade_features
        WHERE features_json IS NOT NULL AND features_json != ''
    """)
    for trade_id, fj in cur.fetchall():
        if trade_id in trades:
            try: trades[trade_id]["features_rich"] = json.loads(fj)
            except: pass
    
    conn.close()
    return trades

def flatten(fj, prefix=""):
    """Развернуть вложенный JSON в плоский словарь бинарных фич."""
    flat = {}
    if not isinstance(fj, dict): return flat
    
    ctx = fj.get("context", {})
    for category in ["smc", "trend", "mom", "pivot", "rsi", "wt", "volume"]:
        cat_data = ctx.get(category, {})
        if not isinstance(cat_data, dict): continue
        for k, v in cat_data.items():
            if isinstance(v, (int, float)) and v == 1:
                flat[f"{category}.{k}"] = 1
            elif category == "pivot" and k in ["pivot_relation_1D", "pivot_relation_1W", "pivot_nearest_1D", "pivot_nearest_1W"]:
                flat[f"{category}.{k}={v}"] = 1
    
    # Signal type из features
    sig = fj.get("signal", {}).get("signal_type", "")
    if sig: flat[f"signal.type={sig}"] = 1
    
    return flat

def analyze(trades):
    # Только сделки с богатыми features
    rich = [t for t in trades.values() if t["features_rich"]]
    print(f"Всего закрытых: {len(trades)}")
    print(f"С богатыми features: {len(rich)}")
    
    if not rich: return
    
    # Общая статистика
    all_nets = [t["profit_pct"] for t in rich]
    print(f"\nALL: n={len(all_nets)} avg={st.mean(all_nets):+.3f}% "
          f"sum={sum(all_nets):+.1f}% WR={sum(1 for p in all_nets if p>0)/len(all_nets)*100:.0f}%")
    
    # === 1. Split по signal_type/direction ===
    print(f"\n{'='*70}")
    print("SPLIT ПО SIGNAL_TYPE / DIRECTION")
    print(f"{'signal':20} {'dir':5} {'n':>6} {'avg%':>8} {'sum%':>8} {'WR':>5}")
    print("-" * 55)
    
    sig_groups = defaultdict(list)
    for t in rich:
        key = f"{t['signal']}/{t['dir']}"
        sig_groups[key].append(t["profit_pct"])
    
    sig_stats = []
    for key, nets in sorted(sig_groups.items(), key=lambda x: -len(x[1])):
        if len(nets) < MIN_TRADES: continue
        avg = st.mean(nets)
        wr = sum(1 for p in nets if p > 0) / len(nets) * 100
        sig_stats.append((key, len(nets), avg, sum(nets), wr))
        print(f"{key:25} {len(nets):>6} {avg:>+7.3f}% {sum(nets):>+7.1f}% {wr:>4.0f}%")
    
    # === 2. Mining фич: какие чаще в положительных сделках ===
    print(f"\n{'='*70}")
    print("MINING ФИЧ: prevalence в POSITIVE vs NEGATIVE сделках")
    
    pos_trades = [t for t in rich if t["profit_pct"] > 0]
    neg_trades = [t for t in rich if t["profit_pct"] < 0]
    print(f"POS={len(pos_trades)} NEG={len(neg_trades)}")
    
    # Собираем все фичи
    pos_flat = Counter()
    neg_flat = Counter()
    for t in pos_trades:
        for k in flatten(t["features_rich"]):
            pos_flat[k] += 1
    for t in neg_trades:
        for k in flatten(t["features_rich"]):
            neg_flat[k] += 1
    
    all_features = set(pos_flat.keys()) | set(neg_flat.keys())
    
    # Для каждой фичи: prevalence в pos vs neg
    feat_stats = []
    for feat in all_features:
        p_pos = pos_flat[feat] / len(pos_trades) * 100
        p_neg = neg_flat[feat] / len(neg_trades) * 100
        diff = p_pos - p_neg
        feat_stats.append((feat, p_pos, p_neg, diff, pos_flat[feat], neg_flat[feat]))
    
    feat_stats.sort(key=lambda x: -abs(x[3]))  # по модулю разницы
    
    print(f"\n{'feature':45} {'pos%':>6} {'neg%':>6} {'diff':>7} {'n_pos':>6} {'n_neg':>6}")
    print("-" * 85)
    for feat, p_pos, p_neg, diff, n_pos, n_neg in feat_stats[:40]:
        marker = "+" if diff > 0 else "-"
        print(f"{feat:45} {p_pos:>5.1f} {p_neg:>5.1f} {diff:>+6.1f} {marker} {n_pos:>5} {n_neg:>5}")
    
    # === 3. Top features с наибольшей разницей в % net ===
    print(f"\n{'='*70}")
    print("ФИЧИ С НАИБОЛЬШЕЙ РАЗНИЦЕЙ В % NET")
    
    feat_nets = defaultdict(list)
    for t in rich:
        for feat in flatten(t["features_rich"]):
            feat_nets[feat].append(t["profit_pct"])
    
    feat_net_stats = []
    for feat, nets in feat_nets.items():
        if len(nets) < MIN_TRADES: continue
        with_f = st.mean(nets)
        without_f = st.mean([t["profit_pct"] for t in rich 
                            if feat not in flatten(t["features_rich"])]) if len(rich) - len(nets) >= MIN_TRADES else 0
        feat_net_stats.append((feat, len(nets), with_f, without_f, with_f - without_f))
    
    feat_net_stats.sort(key=lambda x: -abs(x[4]))
    
    print(f"\n{'feature':45} {'n':>5} {'withF':>8} {'withoutF':>8} {'delta':>8}")
    print("-" * 75)
    for feat, n, wf, wof, delta in feat_net_stats[:25]:
        marker = "EDGE+" if delta > 0 else "EDGE-"
        print(f"{feat:45} {n:>5} {wf:>+7.3f}% {wof:>+7.3f}% {delta:>+7.3f}% {marker}")
    
    # === 4. Split по data-era ===
    print(f"\n{'='*70}")
    print("SPLIT ПО DATA-ERA")
    
    era_data = defaultdict(list)
    for t in rich:
        raw = t.get("features_raw", "")
        era = "unknown"
        if raw:
            try:
                j = json.loads(raw)
                era = j.get("data_era", "unknown")
            except: pass
        era_data[era].append(t["profit_pct"])
    
    for era in sorted(era_data.keys()):
        nets = era_data[era]
        if len(nets) < MIN_TRADES: continue
        print(f"  {era:15} n={len(nets):>5} avg={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
    
    # === 5. Итог ===
    print(f"\n{'='*70}")
    print("ВЕРДИКТ")
    # Топ-5 фич с положительной дельтой
    edge_features = [(f, n, delta) for f, n, wf, wof, delta in feat_net_stats if delta > 0.05]
    edge_features.sort(key=lambda x: -x[2])
    
    if edge_features:
        print(f"Фичи с edge (delta > 0.05%, n≥{MIN_TRADES}): {len(edge_features)}")
        for f, n, d in edge_features[:10]:
            print(f"  ✅ {f}: +{d:.3f}% (n={n})")
    else:
        print("Фич с edge НЕ найдено.")

if __name__ == "__main__":
    trades = load()
    analyze(trades)
