"""ВОЛНОВОЙ КОНТЕКСТ РАДАРА — ИСТОРИЧЕСКАЯ ПРОВЕРКА (Егор 26.09: «данные нужно проверять перед вводом в бой»).

Гипотеза, полученная 26.09 на 58 сделках за 30 дней (мало!): у радара своё зрение (ZigZag 15m/24ч),
а контекст OKO-SM 4h ему помогает — вход ПРОТИВ тренда 4h давал +1.08%/сд против −0.85 ПО тренду,
и вход у ЭКСТРЕМУМА ноги +1.73 против −0.68 в середине.

Здесь проверяем это на ВСЁМ журнале радара: pump-сигналы с полной геометрией (entry/sl/tp1),
2982 штуки, 343 монеты, 03.07→26.09.2026. Исход считаем на ПУБЛИЧНЫХ 5m klines (как vst_real_resolve):
фил лимитом в пределах entry_ttl_min=45 мин, стоп до фила = сделки нет, дальше стоп/цель по касанию
(стоп приоритетнее в одном баре), горизонт 48 ч (config vst_time_exit.per_source.radar_pump = 2 дня).
Косты 0.10%. Контроль: тот же риск/цель/горизонт в СЛУЧАЙНЫЙ момент ±10 дней той же монеты (×3).
Волновой контекст — каузально, только бары 4h ДО сигнала.

python radar_wave_hist.py run [процессов] · report
"""
import sys, glob, pickle, time, json, urllib.request, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))

OUT = Path("G:/oko_lab/out/radar_wave_hist"); OUT.mkdir(parents=True, exist_ok=True)
FEED = ROOT / "oko_feed" / "external_data.db"
COST, TTL_MIN, HOLD_H, N_CTL = 0.10, 45, 48, 3


def klines5(sym, t0, t1):
    """5m из НАШИХ 1m-паркетов (решение Егора 26.09: «второе сейчас»).

    Сеть отпала: BingX не отдаёт 5m за июль — пробный прогон вернул «нет данных» по всему
    месяцу. Локальный кэш G:/oko_lab/tf/5m покрывает 2484 сигнала из 2984 (83%, до 15.09.2026);
    остаток при необходимости добираем 15m из сети — но у него фил грубее (заявка живёт 45 мин
    = 3 бара против 9).
    """
    from tfcache import load_tf
    try:
        d = load_tf(sym, "5m")
    except Exception:
        return None
    if d is None or len(d) == 0:
        return None
    return d[(d.index >= t0) & (d.index <= t1)]


def resolve(k, t0, long_, e, sl, tp):
    """Исход заявки на реальных ценах. Возвращает (тег, pnl%)."""
    w = k[k.index >= t0]
    if w.empty or w.index[0] > t0 + pd.Timedelta(minutes=10):
        return "нет данных", np.nan
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    n_ttl = max(1, TTL_MIN // 5); fill = None
    for j in range(min(n_ttl, len(w))):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return "стоп до фила", np.nan
        if (lo[j] <= e) if long_ else (hi[j] >= e):
            fill = j; break
    if fill is None:
        return "нет фила", np.nan
    n_hold = HOLD_H * 12
    for j in range(fill + 1, min(fill + 1 + n_hold, len(w))):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return "SL", ((sl - e) / e * 100) * (1 if long_ else -1) - COST
        if (hi[j] >= tp) if long_ else (lo[j] <= tp):
            return "TP", ((tp - e) / e * 100) * (1 if long_ else -1) - COST
    j = min(fill + n_hold, len(w) - 1)
    if j <= fill:
        return "нет данных", np.nan
    return "время", ((cl[j] - e) / e * 100) * (1 if long_ else -1) - COST


def ctl_geo(k, t0, long_, rsk, tg):
    """Контроль: тот же риск/цель/горизонт, вход по цене открытия случайного момента."""
    w = k[k.index >= t0]
    if len(w) < 12:
        return np.nan
    e = float(w.open.values[0])
    sl = e * (1 - rsk) if long_ else e * (1 + rsk)
    tp = e * (1 + tg) if long_ else e * (1 - tg)
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    n = min(HOLD_H * 12, len(w) - 1)
    for j in range(1, n + 1):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - COST
        if (hi[j] >= tp) if long_ else (lo[j] <= tp):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - COST
    return ((cl[n] - e) / e * 100) * (1 if long_ else -1) - COST


def one(args):
    sym, sigs = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, 0
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.oko_sm_engine import run_structure, current_leg
    from core.waves.wave5_core import mark_impulse, WaveParams
    from tfcache import load_tf

    d = pd.DataFrame(sigs).sort_values("t")
    t0 = d.t.min() - pd.Timedelta(days=12)
    t1 = d.t.max() + pd.Timedelta(hours=HOLD_H + 4)
    try:
        k5 = klines5(sym, t0, t1)
    except Exception:
        k5 = None
    if k5 is None or len(k5) < 100:
        pickle.dump([], open(out_p, "wb")); return sym, 0
    try:
        d4 = load_tf(sym, "4h")
    except Exception:
        d4 = None

    rs = random.Random(sum(map(ord, sym)) + 3)
    rows = []
    for r in d.itertuples():
        long_ = str(r.side).upper() == "LONG"
        e, sl, tp = float(r.entry), float(r.sl), float(r.tp1)
        if e <= 0 or sl <= 0 or tp <= 0:
            continue
        tag, pnl = resolve(k5, r.t, long_, e, sl, tp)
        rsk, tg = abs(e - sl) / e, abs(tp - e) / e
        ctl = []
        for _ in range(N_CTL):
            tc = r.t + pd.Timedelta(days=rs.uniform(-10, 10))
            if tc <= k5.index[0] or tc >= k5.index[-1] - pd.Timedelta(hours=HOLD_H):
                continue
            v = ctl_geo(k5, tc, long_, rsk, tg)
            if v == v:
                ctl.append(v)
        trend = depth = None; five = "нет"
        if d4 is not None and len(d4) > 120:
            cut = d4[d4.index < r.t]
            if len(cut) > 120:
                try:
                    st = run_structure(cut[["open", "high", "low", "close"]], swing_len=50, internal_len=5)
                    trend = st.trend
                    leg = current_leg(st); px = float(cut.close.iloc[-1])
                    if leg and leg.get("origin") is not None and leg.get("extreme") is not None:
                        o_, x_ = float(leg["origin"]), float(leg["extreme"])
                        if o_ != x_:
                            depth = (px - o_) / (x_ - o_)
                except Exception:
                    pass
                try:
                    stf = mark_impulse(cut, r.t, WaveParams(), "4h", lookback=12)
                    if stf:
                        five = "по ходу" if str(stf[0]["side"]).upper() == ("LONG" if long_ else "SHORT") else "против"
                except Exception:
                    pass
        rows.append({"sym": sym, "t": r.t, "side": "LONG" if long_ else "SHORT", "grade": r.grade,
                     "wave_leg": r.wave_leg, "исход": tag, "pnl": pnl,
                     "ctl": float(np.mean(ctl)) if ctl else np.nan,
                     "trend4h": trend, "глубина": depth, "пятёрка": five,
                     "stop_pct": rsk * 100, "tgt_pct": tg * 100})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, len(rows)


def load_sigs():
    import sqlite3
    c = sqlite3.connect(FEED)
    d = pd.read_sql("select ts, symbol, side, entry, sl, tp1, grade, wave_leg from radar_orders "
                    "where sig_type='pump' and entry>0 and sl>0 and tp1>0", c)
    d["t"] = pd.to_datetime(d.ts, unit="s")
    # имена паркетов: SYMUSDT (в журнале радара бывает «MAGMA», «ZEC/USDT», «ZECUSDT»)
    s = d.symbol.str.replace("/", "", regex=False).str.upper()
    d["sym"] = s.where(s.str.endswith("USDT"), s + "USDT")
    return d


def report():
    R = []
    for f in glob.glob(str(OUT / "*.pkl")):
        R += pickle.load(open(f, "rb"))
    d = pd.DataFrame(R)
    pd.set_option("display.width", 260)
    print(f"сигналов обработано: {len(d)} · монет {d.sym.nunique()} · окно {d.t.min():%Y-%m-%d} → {d.t.max():%Y-%m-%d}")
    print("\n=== что с заявками стало на реальном рынке")
    print(d["исход"].value_counts().to_string())
    f = d[d["исход"].isin(["SL", "TP", "время"])].copy()
    f["Δ"] = f.pnl - f.ctl
    print(f"\nисполнено: {len(f)} · средн {f.pnl.mean():+.2f} · медиана {f.pnl.median():+.2f} · "
          f"WR {100*(f.pnl>0).mean():.0f}% · контроль {f.ctl.mean():+.2f} · Δr {f['Δ'].mean():+.2f}")
    print(f"ХРУПКОСТЬ: сумма {f.pnl.sum():+.0f} · без верхних 10% {f.pnl.sum()-f.pnl.nlargest(max(1,len(f)//10)).sum():+.0f}")

    def blk(g):
        r = g.agg(n=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"),
                  медиана=("pnl", "median"), WR=("pnl", lambda x: round(100 * (x > 0).mean())))
        r["Δr"] = g["Δ"].mean().round(2)
        return r.round(2)

    f["тренд"] = [("ПРОТИВ тренда 4h" if (t == 1) != (s == "LONG") else "по тренду 4h")
                  if t in (1, -1) else "тренд не определён" for t, s in zip(f.trend4h, f.side)]
    print("\n=== × ТРЕНД 4h (гипотеза 30 дней: против +1.08 / по тренду −0.85)")
    print(blk(f.groupby("тренд")).to_string())
    g = f[f["глубина"].notna()].copy()
    if len(g):
        g["зона ноги"] = pd.cut(g["глубина"], [-99, 0.5, 0.79, 1.0, 99],
                                labels=["<0.5 (середина)", "0.5-0.79 (OTE)", "0.79-1.0 (у экстремума)", ">1 (за ногой)"])
        print("\n=== × ЗОНА НОГИ 4h (гипотеза: у экстремума +1.73 / середина −0.68)")
        print(blk(g.groupby("зона ноги", observed=True)).to_string())
    print("\n=== × ПЯТЁРКА ядра 4h")
    print(blk(f.groupby("пятёрка")).to_string())
    print("\n=== × СВОЙ счёт ног радара (wave_leg)")
    f["leg"] = np.where(f.wave_leg.isna(), "нет", np.where(f.wave_leg < 3, "leg<3 (гейт режет)", "leg>=3"))
    print(blk(f.groupby("leg")).to_string())
    print("\n=== сторона × тренд 4h (средн)")
    print(f.pivot_table(index="тренд", columns="side", values="pnl", aggfunc="mean").round(2).to_string())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "report":
        report()
    else:
        d = load_sigs()
        groups = [(s, g.to_dict("records")) for s, g in d.groupby("sym")]
        print(f"монет: {len(groups)} · сигналов: {len(d)}", flush=True)
        nproc = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        done = 0
        with Pool(nproc) as pool:
            for sym, k in pool.imap_unordered(one, groups):
                done += 1
                if done % 20 == 0:
                    print(f"  {done}/{len(groups)}", flush=True)
        report()
