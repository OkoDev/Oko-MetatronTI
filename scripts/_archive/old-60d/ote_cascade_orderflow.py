"""OrderFlow реентри-каскад (Егор 30.06): движение к HTF-OTE = серия под-импульсов, каждый
со своим LTF-OTE. Тест: серия tp1-входов на каждом LTF-сломе D после HTF-CHoCH vs одиночный вход.

Гипотеза: каскад (N×tp1) собирает бОльшую часть движения, чем 1 сделка (tp1 или дальняя цель).
Каждый вход — широкий SL (импульс-1.0) + tp1 (1R). Каскад стоп на первом SL (тренд сломан).
"""
import os, sys, sqlite3
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import pandas as pd, numpy as np
from collections import defaultdict

CACHE = "ohlcv_cache.db"
BUF, RT, MAXHOLD = 0.0015, 0.10, 2880
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
PAIRS_TF = [("4h", "1h"), ("4h", "15m"), ("4h", "5m"), ("1h", "15m"), ("1h", "5m")]
HTF_HOLD = 30          # окно жизни HTF-сетапа (HTF-баров) — горизонт каскада
MAX_LEGS = 6           # макс входов в каскаде

def _load(conn, sym, tf):
    try:
        df = pd.read_sql_query(
            "SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
            conn, params=(sym, tf))
    except Exception:
        return None
    if df is None or len(df) < 100: return None
    df["ts"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float)

SLIP = 0.30   # % слиппедж на ВХОД (реалистично с гейтом свежести; fee RT=0.10% вход+выход)

def _walk_tp1(D, entry, slv, ei, x_end, lo, hi, cl, slip=SLIP):
    """tp1 (1R) или SL — что раньше. cost = fee(вход+выход) + slip(вход). Возвращает (R_net, exit_iloc)."""
    risk = abs(entry - slv); cost = (RT + slip) / (risk / entry * 100)
    tp = entry + risk if D == "long" else entry - risk
    for j in range(ei, x_end + 1):
        if (hi[j] >= slv) if D == "short" else (lo[j] <= slv):
            return -1.0 - cost, j
        if (lo[j] <= tp) if D == "short" else (hi[j] >= tp):
            return 1.0 - cost, j
    rc = ((entry - cl[x_end]) if D == "short" else (cl[x_end] - entry)) / risk
    return rc - cost, x_end

def test_pair(conn, sym):
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    out = defaultdict(lambda: {"single": [], "cascade": [], "legs": [], "rows": []})
    cache = {}
    def get(tf):
        if tf not in cache: cache[tf] = _load(conn, sym, tf)
        return cache[tf]
    for htf, ltf in PAIRS_TF:
        df_h = get(htf); df_l = get(ltf)
        if df_h is None or df_l is None or len(df_l) < 300: continue
        sh = find_setups_zz(zigzag_atr(df_h), df_h)
        sl_all = find_setups_zz(zigzag_atr(df_l), df_l)
        if not sh or not sl_all: continue
        lo = df_l["low"].values; hi = df_l["high"].values; cl = df_l["close"].values
        posL = {ts: i for i, ts in enumerate(df_l.index)}
        n = len(df_l)
        for s_h in sh:
            if s_h.get("kind") != "CHoCH": continue
            D = s_h["direction"]; hlo, hhi = s_h["ote"]; h_ts = s_h["choch_ts"]
            w_end_ts = h_ts + pd.Timedelta(minutes=HTF_HOLD * TF_MIN[htf])
            # все LTF-сломы D в окне сетапа
            legs = [s for s in sl_all if s["direction"] == D and h_ts < s["choch_ts"] <= w_end_ts]
            if not legs: continue
            key = f"{htf}->{ltf} {D}"
            # каскад: последовательные входы, каждый после выхода предыдущего
            cum = 0.0; nlegs = 0; last_exit_i = -1; first_R = None; first_q = None
            for s_l in legs:
                ci = posL.get(s_l["choch_ts"])
                if ci is None or ci <= last_exit_i: continue
                olo, ohi = s_l["ote"]; entry = (olo + ohi) / 2.0
                # вход в HTF-OTE ИЛИ вдоль движения (каскадные откаты вне исходной зоны допустимы)
                ei = None
                for j in range(ci + 1, min(ci + 1 + 60, n)):
                    if lo[j] <= ohi and hi[j] >= olo: ei = j; break
                if ei is None or ei <= last_exit_i: continue
                slv = s_l["levels"][1.0] * (1 - BUF) if D == "long" else s_l["levels"][1.0] * (1 + BUF)
                if abs(entry - slv) <= 0: continue
                x_end = min(ei + MAXHOLD, n - 1)
                R, exit_i = _walk_tp1(D, entry, slv, ei, x_end, lo, hi, cl)
                if first_R is None: first_R = R; first_q = str(df_l.index[ei].to_period("Q"))
                cum += R; nlegs += 1; last_exit_i = exit_i
                if R < 0: break               # SL → тренд сломан, каскад конец
                if nlegs >= MAX_LEGS: break
            if first_R is not None:
                out[key]["single"].append(first_R)
                out[key]["cascade"].append(cum)
                out[key]["legs"].append(nlegs)
                out[key]["rows"].append((first_q, first_R, cum))
    return out

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    print(f"[cascade] пар: {len(syms)}", flush=True)
    agg = defaultdict(lambda: {"single": [], "cascade": [], "legs": []})
    wf = defaultdict(lambda: {"single": [], "cascade": []})   # quarter → R
    for i, sym in enumerate(syms):
        try:
            for k, v in test_pair(conn, sym).items():
                agg[k]["single"] += v["single"]; agg[k]["cascade"] += v["cascade"]; agg[k]["legs"] += v["legs"]
                for q, sr, cr in v["rows"]:
                    wf[q]["single"].append(sr); wf[q]["cascade"].append(cr)
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[cascade] {i+1}/{len(syms)}", flush=True)
    conn.close()
    print("\n# OrderFlow КАСКАД vs одиночный вход (сумма R на HTF-сетап)\n")
    print(f"{'связка':<18}{'n':>6}{'1вход avgR':>12}{'каскад avgR':>14}{'ср.ног':>9}{'выигрыш':>10}")
    TS = TC = 0.0; TN = 0
    for k in sorted(agg):
        s = agg[k]["single"]; c = agg[k]["cascade"]; lg = agg[k]["legs"]
        if not s: continue
        a_s = sum(s)/len(s); a_c = sum(c)/len(c); a_l = sum(lg)/len(lg)
        TS += sum(s); TC += sum(c); TN += len(s)
        print(f"{k:<18}{len(s):>6}{a_s:>+12.3f}{a_c:>+14.3f}{a_l:>9.1f}{a_c-a_s:>+10.3f}")
    print(f"\nИТОГ (slip={SLIP}%): 1вход avg={TS/TN:+.3f}R · каскад avg={TC/TN:+.3f}R · выигрыш {((TC-TS)/TN):+.3f}R/сетап ({(TC/TS-1)*100:+.0f}%)")
    print(f"\n# WF OOS по кварталам (slip={SLIP}%)")
    print(f"{'квартал':<10}{'n':>7}{'1вход':>10}{'каскад':>10}")
    cw = 0
    for q in sorted(wf):
        s = wf[q]["single"]; c = wf[q]["cascade"]
        if not s: continue
        a_s = sum(s)/len(s); a_c = sum(c)/len(c)
        cw += 1 if a_c > 0 else 0
        print(f"{q:<10}{len(s):>7}{a_s:>+10.3f}{a_c:>+10.3f}")
    qn = len([q for q in wf if wf[q]['single']])
    print(f"каскад OOS+: {cw}/{qn} кварталов")

if __name__ == "__main__":
    main()
