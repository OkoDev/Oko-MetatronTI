# -*- coding: utf-8 -*-
import os
import sys
import time
import sqlite3
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mtf_lib as L      # noqa: E402
import run_pass as RP    # noqa: E402

_BTC = {}


def btc_regime():
    if "t" in _BTC:
        return _BTC["t"], _BTC["r"]
    d = L.load("BTC/USDT", "1h")
    c = d["close"].values
    ret = np.full(len(c), 0.0)
    ret[720:] = c[720:] / c[:-720] - 1.0
    reg = np.where(ret > 0.10, 1, np.where(ret < -0.10, -1, 0))
    _BTC["t"] = d["time"].values.astype(np.int64); _BTC["r"] = reg
    return _BTC["t"], _BTC["r"]


def work(args):
    sym, ltf, t0, t1 = args
    try:
        bt, br = btc_regime()
        return RP.process(sym, ltf, t0, t1, bt, br)
    except Exception as e:
        return ("ERR", f"{sym}: {type(e).__name__}: {e}")


def universe(ltf):
    con = sqlite3.connect(f"file:{L.DB}?mode=ro", uri=True)
    a = {x[0] for x in con.execute(
        "select distinct symbol from ohlcv_cache where timeframe='1h'")}
    b = {x[0] for x in con.execute(
        "select distinct symbol from ohlcv_cache where timeframe=?", (ltf,))}
    con.close()
    return sorted(s for s in (a & b) if not s.startswith("binance:"))


if __name__ == "__main__":
    import multiprocessing as mp
    ltf = sys.argv[1]
    t0 = int(pd.Timestamp(sys.argv[2]).timestamp() * 1000)
    t1 = int(pd.Timestamp(sys.argv[3]).timestamp() * 1000)
    tag = sys.argv[4]
    nproc = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    syms = universe(ltf)
    print(f"{ltf}: {len(syms)} symbols, window {sys.argv[2]}..{sys.argv[3]}", flush=True)
    jobs = [(s, ltf, t0, t1) for s in syms]
    I, C, errs = [], [], []
    t_start = time.time()
    with mp.Pool(nproc) as p:
        for n, res in enumerate(p.imap_unordered(work, jobs, chunksize=1), 1):
            if isinstance(res[0], str) and res[0] == "ERR":
                errs.append(res[1])
            else:
                a, b = res
                if a is not None:
                    I.append(a)
                if b is not None:
                    C.append(b)
            if n % 25 == 0:
                print(f"  {n}/{len(jobs)}  {time.time()-t_start:.0f}s  imp={sum(len(x) for x in I)}",
                      flush=True)
    di = pd.concat(I, ignore_index=True) if I else pd.DataFrame()
    dc = pd.concat(C, ignore_index=True) if C else pd.DataFrame()
    di.to_pickle(os.path.join(HERE, f"imp_{tag}.pkl"))
    dc.to_pickle(os.path.join(HERE, f"ctl_{tag}.pkl"))
    print("IMP", di.shape, "CTL", dc.shape, "errs", len(errs), flush=True)
    for e in errs[:10]:
        print("ERR", e, flush=True)
