"""ELLIOTT-COMPLETION: тест завершённости импульса на pull/cont/pivot_reversal."""
import sys, time, json, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
from pathlib import Path; import pandas as pd, numpy as np, sqlite3
from core.indicators.indicators import calculate_n_down, calculate_n_up, find_swing_highs, find_swing_lows
from core.smc.smc_engine import detect_structure_breaks
from core.infra.config_loader import config as cfg; cfg.set('arch104.choch_length', 5)

db = sqlite3.connect('subscriptions.db'); db.row_factory = sqlite3.Row
trades = db.execute("""
    SELECT id, symbol, direction, R_multiple, entry_price, created_at, tp_source
    FROM simulated_trades
    WHERE signal_type IN ('ote_nested', 'pivot_reversal')
      AND status IN ('TP', 'SL', 'TSL', 'EXPIRED')
      AND R_multiple IS NOT NULL AND entry_price > 0
    ORDER BY id
""").fetchall()
print(f"Total trades: {len(trades)}")

cache = {}; results = []; t0 = time.monotonic(); computed = 0

for i, t in enumerate(trades):
    base = t['symbol'].split('/')[0]
    if base not in cache:
        p15 = Path(f'data/history/15m/{base}USDT.parquet')
        p1h = Path(f'data/history/1h/{base}USDT.parquet')
        store = {'15m': None, '1h': None, '4h': None, '1d': None}
        if p1h.exists():
            d1h = pd.read_parquet(p1h)
            if isinstance(d1h.index, pd.DatetimeIndex) and d1h.index.tz:
                d1h.index = d1h.index.tz_localize(None)
            d1h.columns = [c.lower() for c in d1h.columns]
            store['1h'] = d1h
            store['4h'] = d1h.resample('4h').agg(
                {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            store['1d'] = d1h.resample('1D').agg(
                {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        if p15.exists():
            d15 = pd.read_parquet(p15)
            if isinstance(d15.index, pd.DatetimeIndex) and d15.index.tz:
                d15.index = d15.index.tz_localize(None)
            d15.columns = [c.lower() for c in d15.columns]
            store['15m'] = d15
        cache[base] = store

    store = cache[base]
    if store['15m'] is None or store['1h'] is None:
        continue

    try:
        ets = pd.Timestamp(t['created_at'])
        if ets.tz:
            ets = ets.tz_convert('UTC').tz_localize(None)
    except Exception:
        continue

    ep = float(t['entry_price'])
    R = float(t['R_multiple'])
    td = t['direction']
    sig = t['tp_source'] or ''

    if 'pull' in sig:
        ote_type = 'pull'
    elif 'cont' in sig:
        ote_type = 'cont'
    else:
        ote_type = 'pivot_reversal'

    row_data = {'id': t['id'], 'type': ote_type, 'dir': td, 'R': R}

    for tf in ['15m', '1h', '4h', '1d']:
        df = store.get(tf)
        if df is None:
            row_data[f'n_down_{tf}'] = row_data[f'n_up_{tf}'] = -1
            continue
        df_slice = df[df.index < ets].tail(200)
        if len(df_slice) < 30:
            row_data[f'n_down_{tf}'] = row_data[f'n_up_{tf}'] = -1
            continue
        period = 3 if tf == '15m' else 5
        try:
            sh = find_swing_highs(df_slice['high'], period)
            sl = find_swing_lows(df_slice['low'], period)
            nd = calculate_n_down(sh) if len(sh) > 1 else 0
            nu = calculate_n_up(sl) if len(sl) > 1 else 0
        except Exception:
            nd = nu = 0
        row_data[f'n_down_{tf}'] = nd
        row_data[f'n_up_{tf}'] = nu

    # CHoCH on 1h
    try:
        df1h_slice = store['1h'][store['1h'].index < ets].tail(300)
        if len(df1h_slice) > 30:
            sbs = detect_structure_breaks(df1h_slice, length=5)
            last_bull = bool(sbs and sbs[-1].direction > 0)
            last_bear = bool(sbs and sbs[-1].direction < 0)
            row_data['choch_bull'] = int(last_bull)
            row_data['choch_bear'] = int(last_bear)
    except Exception:
        row_data['choch_bull'] = row_data['choch_bear'] = 0

    results.append(row_data)
    computed += 1
    if (i + 1) % 500 == 0:
        elapsed = time.monotonic() - t0
        print(f"  [{i+1}/{len(trades)}] {computed} computed, {elapsed:.0f}s", flush=True)

elapsed = time.monotonic() - t0
print(f"Done: {computed} computed in {elapsed:.0f}s")

# ── Analysis ──
dfr = pd.DataFrame(results)
print(f"\n=== PULL + PIVOT: n_down_4h vs avgR ===\n{'nd_4h':>10s} {'n':>6s} {'avgR':>8s} {'WR':>6s}")
pull_pivot = dfr[dfr['type'].isin(['pull', 'pivot_reversal'])]
for nd in range(0, 6):
    if nd == 0:
        sub = pull_pivot[pull_pivot['n_down_4h'] == 0]
    else:
        sub = pull_pivot[pull_pivot['n_down_4h'] >= nd]
    if len(sub) < 5:
        continue
    label = f'nd_4h>={nd}' if nd > 0 else 'nd_4h=0'
    print(f"{label:>10s} {len(sub):>6d} {sub.R.mean():>+8.3f} {(sub.R > 0).mean() * 100:>5.1f}%")

print(f"\n=== CONT: n_down_4h vs avgR ===\n{'nd_4h':>10s} {'n':>6s} {'avgR':>8s} {'WR':>6s}")
cont = dfr[dfr['type'] == 'cont']
for nd in range(0, 6):
    if nd == 0:
        sub = cont[cont['n_down_4h'] == 0]
    else:
        sub = cont[cont['n_down_4h'] >= nd]
    if len(sub) < 5:
        continue
    label = f'nd_4h>={nd}' if nd > 0 else 'nd_4h=0'
    print(f"{label:>10s} {len(sub):>6d} {sub.R.mean():>+8.3f} {(sub.R > 0).mean() * 100:>5.1f}%")

# Key: pull-SHORT at high n_up (mirror)
print(f"\n=== PULL-SHORT × n_up_4h ===\n{'nu_4h':>10s} {'n':>6s} {'avgR':>8s} {'WR':>6s}")
pull_short = dfr[(dfr['type'] == 'pull') & (dfr['dir'] == 'SHORT')]
for nu in range(0, 6):
    if nu == 0:
        sub = pull_short[pull_short['n_up_4h'] == 0]
    else:
        sub = pull_short[pull_short['n_up_4h'] >= nu]
    if len(sub) < 5:
        continue
    label = f'nu_4h>={nu}' if nu > 0 else 'nu_4h=0'
    print(f"{label:>10s} {len(sub):>6d} {sub.R.mean():>+8.3f} {(sub.R > 0).mean() * 100:>5.1f}%")

# CHoCH combo
print(f"\n=== PULL + CHoCH_BULL (last break up) ===\n{'choch':>10s} {'n':>6s} {'avgR':>8s} {'WR':>6s}")
for ch in [0, 1]:
    sub = pull_pivot[pull_pivot['choch_bull'] == ch]
    if len(sub) > 5:
        print(f"{'choch='+str(ch):>10s} {len(sub):>6d} {sub.R.mean():>+8.3f} {(sub.R > 0).mean() * 100:>5.1f}%")

# MTF combo: HTF completed + LTF fresh
print(f"\n=== MTF COMBO: nd_4h>=3 AND nd_1h<=1 (HTF done, LTF fresh) ===\n{'type':>15s} {'dir':>6s} {'n':>6s} {'avgR':>8s} {'WR':>6s}")
for ote_type in ['pull', 'cont', 'pivot_reversal']:
    for d in ['LONG', 'SHORT']:
        sub = dfr[(dfr['type'] == ote_type) & (dfr['dir'] == d) &
                  (dfr['n_down_4h'] >= 3) & (dfr['n_down_1h'] <= 1)]
        if len(sub) < 3:
            continue
        print(f"{ote_type:>15s} {d:>6s} {len(sub):>6d} {sub.R.mean():>+8.3f} {(sub.R > 0).mean() * 100:>5.1f}%")

dfr.to_csv('data/research/2026-06-11--elliott-completion/matrix.csv', index=False)
print(f"\nSaved to data/research/2026-06-11--elliott-completion/matrix.csv")
