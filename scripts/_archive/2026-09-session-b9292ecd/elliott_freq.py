import sys, sqlite3
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
import pandas as pd, numpy as np
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse

DB = r"e:/MTF BOT/CURSOR/crypto_volume_bot/ohlcv_cache.db"
SYMS = ['ADA/USDT','ATOM/USDT','AVAX/USDT','BNB/USDT','BTC/USDT','DOGE/USDT','DOT/USDT',
        'ETH/USDT','LINK/USDT','LTC/USDT','NEAR/USDT','SOL/USDT','TRX/USDT','XRP/USDT']
TFS = ['15m','1h','4h']
DEVS = [3.0,5.0,8.0]

def load(sym, tf):
    conn = sqlite3.connect(DB)
    q = "SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time"
    df = pd.read_sql(q, conn, params=(sym,tf))
    conn.close()
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    df = df.set_index('time')
    return df

rows = []
for tf in TFS:
    for sym in SYMS:
        df = load(sym, tf)
        n = len(df)
        for dev in DEVS:
            zz = zigzag_atr(df, 11, dev)
            imps = detect_elliott_impulse(zz)
            n_imp = len(imps)
            n_text = sum(1 for i in imps if i.get('textbook'))
            # length in bars: from wave0 ts to wave5 ts
            lens = []
            covered = np.zeros(n, dtype=bool)
            idx = df.index
            for imp in imps:
                t0 = imp['waves'][0][0]; t5 = imp['waves'][5][0]
                try:
                    i0 = idx.get_loc(t0); i5 = idx.get_loc(t5)
                except KeyError:
                    continue
                lens.append(i5 - i0)
                covered[i0:i5+1] = True
            per10k = n_imp / n * 10000 if n else 0
            rows.append(dict(tf=tf, sym=sym, dev=dev, n_bars=n, n_zz=len(zz), n_imp=n_imp,
                              per10k=round(per10k,2), pct_textbook=round(100*n_text/n_imp,1) if n_imp else None,
                              len_median=int(np.median(lens)) if lens else None,
                              len_q1=int(np.percentile(lens,25)) if lens else None,
                              len_q3=int(np.percentile(lens,75)) if lens else None,
                              coverage_pct=round(100*covered.sum()/n,2)))
        print(f"done {tf} {sym}", flush=True)

out = pd.DataFrame(rows)
out.to_csv(r"C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad\elliott_freq_raw.csv", index=False)

print("\n=== AGG by tf,dev ===")
agg = out.groupby(['tf','dev']).agg(
    n_imp_total=('n_imp','sum'), per10k_mean=('per10k','mean'),
    textbook_mean=('pct_textbook','mean'), len_median=('len_median','median'),
    coverage_mean=('coverage_pct','mean')
).round(2)
print(agg)
