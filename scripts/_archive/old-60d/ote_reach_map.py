"""ШАГ 1 — объективная КАРТА движения OTE (0 параметров подгонки).
После входа в HTF-OTE значимой ноги: куда доходит цена (reach-rate fib-целей) ДО пробоя SL,
сколько возвратов в OTE по пути (= под-откаты = доборы каскада), профиль MFE.
Решает: есть ли что собирать каскадом/пирамидой к measured-move цели. Мерим объективно."""
import os, sys, sqlite3
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import pandas as pd, numpy as np
from collections import defaultdict

CACHE = "ohlcv_cache.db"
BUF, MAXHOLD = 0.0015, 2880
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
PAIRS_TF = [("4h", "15m"), ("4h", "5m"), ("1h", "15m"), ("1h", "5m")]
FIB_K = [0.5, 1.0, 1.5, 1.618, 2.0, 2.618]   # measured move за конец импульса (=цели продолжения)

def _load(conn, sym, tf):
    try:
        df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                               conn, params=(sym, tf))
    except Exception: return None
    if df is None or len(df) < 300: return None
    df["ts"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.set_index("ts")[["open","high","low","close"]].astype(float)

def test_pair(conn, sym):
    from core.smc.smc_engine import zigzag_atr, ote_retest_setups
    out = defaultdict(lambda: {"reach": defaultdict(int), "n": 0, "pullbacks": [], "mfe": []})
    cache = {}
    def get(tf):
        if tf not in cache: cache[tf] = _load(conn, sym, tf)
        return cache[tf]
    for htf, ltf in PAIRS_TF:
        df_h = get(htf); df_l = get(ltf)
        if df_h is None or df_l is None: continue
        try:
            setups = ote_retest_setups(df_h, only_choch=True)
        except Exception: continue
        if not setups: continue
        lo = df_l["low"].values; hi = df_l["high"].values
        posL = {ts: i for i, ts in enumerate(df_l.index)}; n = len(df_l)
        key = f"{htf}->{ltf}"
        for s in setups:
            D = s["direction"]; olo, ohi = s["ote"]; slv0 = s["sl"]
            imp_from = s["from"][1]; imp_to = s["to"][1]; imp_len = imp_to - imp_from
            if imp_len == 0: continue
            ci = posL.get(s["choch_ts"])
            if ci is None: continue
            # вход = первое касание OTE на LTF после слома
            ei = None
            for j in range(ci + 1, min(ci + 1 + 80, n)):
                if lo[j] <= ohi and hi[j] >= olo: ei = j; break
            if ei is None: continue
            entry = (olo + ohi) / 2.0
            sl = slv0 * (1 - BUF) if D == "long" else slv0 * (1 + BUF)
            x_end = min(ei + MAXHOLD, n - 1)
            o = out[key]; o["n"] += 1
            # цели fib (measured move)
            tgts = {k: imp_from + k * imp_len for k in FIB_K}
            reached = set(); mfe = 0.0; in_zone = True; pb = 0
            for j in range(ei, x_end + 1):
                # SL?
                if (hi[j] >= sl) if D == "short" else (lo[j] <= sl): break
                # MFE в R
                risk = abs(entry - sl)
                fav = ((entry - lo[j]) if D == "short" else (hi[j] - entry)) / risk
                mfe = max(mfe, fav)
                # достигнутые цели
                for k, tg in tgts.items():
                    hit = (lo[j] <= tg) if D == "short" else (hi[j] >= tg)
                    if hit: reached.add(k)
                # подсчёт возвратов в OTE-зону (под-откаты = доборы)
                back = lo[j] <= ohi and hi[j] >= olo
                if back and not in_zone: pb += 1; in_zone = True
                elif not back: in_zone = False
            for k in reached: o["reach"][k] += 1
            o["pullbacks"].append(pb); o["mfe"].append(mfe)
    return out

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    print(f"[reach-map] пар: {len(syms)}", flush=True)
    agg = defaultdict(lambda: {"reach": defaultdict(int), "n": 0, "pullbacks": [], "mfe": []})
    for i, sym in enumerate(syms):
        try:
            for k, v in test_pair(conn, sym).items():
                a = agg[k]; a["n"] += v["n"]; a["pullbacks"] += v["pullbacks"]; a["mfe"] += v["mfe"]
                for fk, c in v["reach"].items(): a["reach"][fk] += c
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[reach-map] {i+1}/{len(syms)}", flush=True)
    conn.close()
    print("\n# КАРТА ДВИЖЕНИЯ OTE — reach-rate целей (measured move) + под-откаты\n")
    print(f"{'связка':<14}{'n':>7} | " + " ".join(f"fib{k:>5}" for k in FIB_K) + " | ср.откатов  MFEмед")
    for key in sorted(agg):
        a = agg[key]; nn = a["n"]
        if not nn: continue
        rr = " ".join(f"{100*a['reach'][k]/nn:>6.0f}%" for k in FIB_K)
        pb = sum(a["pullbacks"])/len(a["pullbacks"]) if a["pullbacks"] else 0
        mfemed = float(np.median(a["mfe"])) if a["mfe"] else 0
        print(f"{key:<14}{nn:>7} | {rr} | {pb:>6.2f}      {mfemed:>.2f}R")
    print("\nfib1.0=конец импульса · fib1.5/2/2.618=measured move за конец (цели продолжения к −1/−2)")
    print("ср.откатов = сколько раз цена вернулась в OTE после выхода (= потенц. доборы каскада)")

if __name__ == "__main__":
    main()
