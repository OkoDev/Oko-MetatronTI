"""Ускоренная проверка «зона OTE дневной ноги аналитика» на ИСТОРИИ вместо ожидания форварда (Егор 15.09: «1–2 недели долго»).
Боевой генератор ote_nested (core.smc.ote_signal_generator, шкаф config/ote_setups.yaml — сейчас включён 4h_1h_pull)
прогоняется по сетке закрытых 1h-баров на 1m-паркетах Binance (C:/oko_history/1m, 145 монет, 2022-12…2026-08).
🔴 Срезы по ВРЕМЕНИ ЗАКРЫТИЯ бара (look-ahead вида 6). FIRE → исход как в бою с 27.06: полный выход на tp1 (+1R) или стоп,
не дольше 7 суток (иначе по закрытию), по 5m-барам после момента сигнала; кост 0.10%.
Признак на момент сигнала: зона и глубина цены входа в дневной ноге (wave_analyst.daily_leg, 1D из закрытых дней).
Запуск: python ote_replay.py run [N]  → out/ote_replay/<SYM>.pkl ; python ote_replay.py report"""
import sys, os, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
OUT = Path("G:/oko_lab/out/ote_replay"); OUT.mkdir(parents=True, exist_ok=True)
TFS = {"3m": ("3min", 3), "5m": ("5min", 5), "15m": ("15min", 15), "1h": ("1h", 60), "4h": ("4h", 240), "1d": ("1D", 1440)}
TAIL = {"3m": 600, "5m": 500, "15m": 400, "1h": 300, "4h": 200, "1d": 60}   # ровно как живой ote_observer_loop._fetch_df
HOLD_MIN = 7 * 24 * 60
T0 = pd.Timestamp("2023-02-01")


def build(sym):
    full = {}
    for tf, (rule, m) in TFS.items():
        d = load_tf(sym, tf)                                            # предрасчитанный кэш G:\oko_lab\tf
        full[tf] = (d, (d.index + pd.Timedelta(minutes=m)).values)      # бары и их время ЗАКРЫТИЯ
    return full


def run_symbol(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from core.smc.ote_signal_generator import OTESignalGenerator
    from core.waves.wave_analyst import daily_leg
    gen = OTESignalGenerator()
    try:
        full = build(sym)
    except Exception as e:
        return sym, f"данные: {e}"
    d1h, c1h = full["1h"]
    d5, c5 = full["5m"]
    grid = c1h[(c1h >= np.datetime64(T0)) & (c1h <= c1h[-1] - np.timedelta64(HOLD_MIN, "m"))]
    rows, busy = [], {}
    t_start = time.time()
    for T in grid:
        dfs = {}
        for tf, (d, c) in full.items():
            j = int(np.searchsorted(c, T, side="right"))
            if j >= 60:
                dfs[tf] = d.iloc[max(0, j - TAIL[tf]):j]
        if "4h" not in dfs or "1h" not in dfs:
            continue
        try:
            sigs = gen.generate(sym, dfs)
        except Exception:
            continue
        for s in sigs:
            if s.status != "FIRE":
                continue
            key = (s.setup_id, s.direction, round(float(s.ote_zone[0]), 10), round(float(s.ote_zone[1]), 10))
            if key in busy and T < busy[key]:
                continue
            long_ = s.direction == "long"; e = float(s.entry); sl = float(s.sl); tp = float(s.tp1)
            if e <= 0 or (long_ and not (sl < e < tp)) or ((not long_) and not (tp < e < sl)):
                continue
            j0 = int(np.searchsorted(c5, T, side="right"))        # первый 5m-бар, закрывшийся ПОСЛЕ момента сигнала
            j1 = min(len(d5), j0 + HOLD_MIN // 5)
            hi, lo, cl = d5.high.values[j0:j1], d5.low.values[j0:j1], d5.close.values[j0:j1]
            x, how, k_ex = None, "time", len(hi) - 1
            for k in range(len(hi)):
                if (lo[k] <= sl) if long_ else (hi[k] >= sl):
                    x, how, k_ex = sl, "stop", k; break
                if (hi[k] >= tp) if long_ else (lo[k] <= tp):
                    x, how, k_ex = tp, "tp1", k; break
            if x is None:
                if not len(cl):
                    continue
                x = float(cl[-1])
            busy[key] = c5[j0 + k_ex] if j0 + k_ex < len(c5) else T
            d4, c4 = full["4h"]; dd, cd = full["1d"]
            j4 = int(np.searchsorted(c4, T, side="right")); jd = int(np.searchsorted(cd, T, side="right"))
            Tt = pd.Timestamp(T)
            try:
                leg = daily_leg(d4.iloc[:j4], Tt, (not long_), e, Tt, Tt, dd=dd.iloc[max(0, jd - 250):jd])
            except Exception:
                leg = None
            rows.append({"sym": sym, "ts": Tt, "setup": s.setup_id, "side": "LONG" if long_ else "SHORT", "entry": e, "sl": sl, "tp1": tp,
                         "risk_pct": abs(e - sl) / e * 100, "outcome": how,
                         "pnl": ((x - e) / e * 100) * (1 if long_ else -1) - 0.10,
                         "trigger": s.trigger_type, "conf": s.conf_score, "confs": "+".join(s.confirmations or []),
                         "zone_1d": leg["zone"] if leg else "нет ноги", "depth_1d": leg["depth"] if leg else np.nan})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} FIRE за {time.time() - t_start:.0f}с"


if __name__ == "__main__":
    if sys.argv[1] == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        random.Random(7).shuffle(syms)
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        print("монет:", len(syms), flush=True)
        with Pool(10) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, syms), 1):
                print(f"{i}/{len(syms)} {s}: {msg}", flush=True)
