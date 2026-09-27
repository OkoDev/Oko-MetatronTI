"""МЕХАНИКА ЯДРА НА ВСЕХ ТФ (Егор 16.09: «давай прогоны по всем тф, у нас ведь теперь это быстро»).
Вопрос: механика «коррекция после пятой» мерилась только на 4h. Работает ли она на 1h / 15m / 5m?

Что считается: тот же боевой код (core.waves.wave5_core._setups_at → ltf_status), меняется ТОЛЬКО старший ТФ.
Всё остальное масштабируется по барам, чтобы сравнение было честным (на 4h это наши боевые 96 ч / 240 ч):
  вход ищется 24 бара HTF · удержание 60 баров HTF · младший ТФ входа ≈ HTF/16 (4h→15m, 1h→5m, 15m→1m, 5m→1m).
Стоп за экстремумом пятой, цель — конец волны 4, кост 0.10% (как в бою и в прошлых замерах).
Контроли (закон: сигнал мерить против случайного входа ТОЙ ЖЕ геометрии) считает ctl.

Запуск: python tf_sweep.py run <тф> [монет] [процессов] · python tf_sweep.py ctl <тф> · python tf_sweep.py report <тф>
"""
import sys, pickle, time, random, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ

OUT = Path("G:/oko_lab/out/tf_sweep"); OUT.mkdir(parents=True, exist_ok=True)
# 17.09: окно раздвинуто назад — докачаны 2020-2021 (альтсезон). Замеры выходов без этих лет
# были односторонними: механика продолжения бережёт хвост, которого в 2023-26 почти не случалось.
T0 = pd.Timestamp("2020-06-01")
LTF = {"1d": "1h", "4h": "15m", "2h": "5m", "1h": "5m", "15m": "1m", "5m": "1m"}   # ≈ HTF/16; ниже 1m данных нет
# (для 5m это HTF/5, для 2h — HTF/24, для 1d — HTF/24: сетка ТФ проекта не даёт 90m и 7.5m)
ENTRY_BARS, HOLD_BARS = 24, 60                                # на 4h = 96 ч и 240 ч — боевые значения
COST = 0.10
WARMUP = 400                                                  # баров HTF до первого замера (ядру нужна история)


def load_1m(sym):
    b = pd.read_parquet(PARQ / f"{sym}.parquet", columns=["open", "high", "low", "close"])
    if getattr(b.index, "tz", None) is not None:
        b.index = b.index.tz_convert("UTC").tz_localize(None)
    return b


def run_symbol(args):
    sym, tf = args
    out_p = OUT / f"{tf}_{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import fast_core; fast_core.patch()          # impulses_on_bar через бинарный поиск: ×42, результат бит-в-бит тот же
    from core.waves.wave5_core import _setups_at, ltf_status, WaveParams, TF_MIN
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    t_start = time.time()
    try:
        dh = load_tf(sym, tf)
        dl = load_1m(sym) if LTF[tf] == "1m" else load_tf(sym, LTF[tf])
    except Exception as e:
        return sym, f"данные: {e}"
    if len(dh) < WARMUP + 100:
        return sym, "мало истории"
    dl_idx = dl.index.values
    tfm, ltfm = TF_MIN[tf], TF_MIN[LTF[tf]]
    entry_h, hold_h = ENTRY_BARS * tfm / 60, HOLD_BARS * tfm / 60
    P = WaveParams(); rows = []; seen = set()
    # структура/свинги/WT — один раз на монету (иначе mark_impulse пересчитывает их на каждом баре)
    dhr = dh.reset_index(drop=True); idx_h = dh.index
    hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=P.sw, internal_len=P.il)
    sws = _swings(dhr["high"], dhr["low"], P.sw); swi = _swings(dhr["high"], dhr["low"], P.il)
    wt = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    for t in range(WARMUP, len(dh)):
        now = idx_h[t] + pd.Timedelta(minutes=tfm)
        if now < T0:
            continue
        try:
            setups = _setups_at(t, dh, idx_h, hh, lh, st, sws, swi, wt, [], [], np.array([np.nan]), tfm, now, P, tf)
        except Exception:
            continue
        for s in setups:
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            if t5.tzinfo is not None:
                t5 = t5.tz_convert("UTC").tz_localize(None)
            # срез LTF-окна: булева маска по 2 млн строк на КАЖДЫЙ сетап давала 8.6 мин на монету (5m);
            # индекс отсортирован, поэтому берём позиции бинарным поиском — это и есть основная экономия
            i0 = int(np.searchsorted(dl_idx, np.datetime64(t5 - pd.Timedelta(minutes=4 * tfm)), "left"))
            i1 = int(np.searchsorted(dl_idx, np.datetime64(t5 + pd.Timedelta(hours=entry_h + hold_h)), "right"))
            w = dl.iloc[i0:i1]
            if len(w) < 100:
                continue
            nw = now.tz_localize(None) if getattr(now, "tzinfo", None) is not None else now
            ls = ltf_status(s, w, P, after=nw, entry_w_h=entry_h, hold_h=hold_h, cost_pct=COST)
            if ls.get("entry_price") is None:
                rows.append({"sym": sym, "tf": tf, "key": s["key"], "side": s["side"], "top_time": t5,
                             "entered": False, "core": s["core"], "core_full": s["core_full"],
                             "fractal": s["fractal"], "depth5": s["depth5"], "imp_pct": s["imp_pct"]})
                continue
            e, sl = ls["entry_price"], ls["stop"]
            rows.append({"sym": sym, "tf": tf, "key": s["key"], "side": s["side"], "top_time": t5,
                         "entered": True, "core": s["core"], "core_full": s["core_full"], "fractal": s["fractal"],
                         "depth5": s["depth5"], "imp_pct": s["imp_pct"], "entry": e, "stop": sl,
                         "target": s["p4_target"], "entry_t": pd.Timestamp(ls["entry_time"]),
                         "outcome": ls["outcome"], "pnl": ls["pnl_pct"],
                         "risk_pct": abs(e - sl) / e * 100, "tgt_pct": abs(s["p4_target"] - e) / e * 100,
                         "trigger": ls.get("trigger")})
    pickle.dump(rows, open(out_p, "wb"))
    n_in = sum(1 for r in rows if r.get("entered"))
    return sym, f"{len(rows)} сетапов / {n_in} входов за {time.time() - t_start:.0f}с"


def walk(d, t0, long_, e, sl, tp, hold_h, cost=COST):
    """Исход входа по цене e на барах, открытых не раньше t0 (стоп раньше цели на одном баре) — как в ltf_status."""
    w = d[(d.index >= t0) & (d.index < t0 + pd.Timedelta(hours=hold_h))]
    if len(w) < 12:
        return np.nan
    lo, hi = w.low.values, w.high.values
    for k in range(len(w)):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - cost
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - cost
    return ((float(w.close.values[-1]) - e) / e * 100) * (1 if long_ else -1) - cost


def controls(args):
    """Два контроля: та же монета со случайным сдвигом ±30 дней и ДРУГИЕ монеты в тот же момент — та же геометрия."""
    sym, tf, trades, others = args
    try:
        import psutil; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:
        pass
    from core.waves.wave5_core import TF_MIN          # минуты в баре — единый словарь проекта, а не свой список ТФ
    rs = random.Random(sum(map(ord, sym)) + 11)
    ltf = LTF[tf]
    hold_h = HOLD_BARS * TF_MIN[tf] / 60
    d = load_1m(sym) if ltf == "1m" else load_tf(sym, ltf)
    cache = {}; out = []
    for tr in trades:
        long_ = tr["side"] == "LONG"; et = pd.Timestamp(tr["entry_t"])
        rsk, tg = tr["risk_pct"] / 100, tr["tgt_pct"] / 100

        def geo(dd, t0):
            w = dd[dd.index >= t0]
            if len(w) < 12:
                return np.nan
            e = float(w.open.iloc[0])
            return walk(dd, w.index[0], long_, e, e * (1 - rsk) if long_ else e * (1 + rsk),
                        e * (1 + tg) if long_ else e * (1 - tg), hold_h)

        a = [geo(d, et + pd.Timedelta(minutes=rs.randint(-43200, 43200))) for _ in range(8)]
        b = []
        for o in rs.sample(others, min(5, len(others))):
            if o not in cache:
                if len(cache) > 2:
                    cache.clear()                    # максимум 3 чужих ряда в памяти
                try:
                    cache[o] = load_1m(o) if ltf == "1m" else load_tf(o, ltf)
                except Exception:
                    cache[o] = None
            if cache[o] is not None:
                b.append(geo(cache[o], et))
        out.append({"sym": sym, "tf": tf, "key": tr["key"], "ctl_rand": np.nanmean(a) if a else np.nan,
                    "ctl_time": np.nanmean(b) if b else np.nan})
    return out


def rows_of(tf):
    return [r for f in glob.glob(str(OUT / f"{tf}_*.pkl")) for r in pickle.load(open(f, "rb"))]


if __name__ == "__main__":
    cmd, tf = sys.argv[1], sys.argv[2]
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    if cmd == "run":
        random.Random(5).shuffle(syms)               # выборка монет одинаковая между ТФ и не по алфавиту
        if len(sys.argv) > 3:
            syms = syms[:int(sys.argv[3])]
        n_proc = int(sys.argv[4]) if len(sys.argv) > 4 else 8
        print(f"{tf}: монет {len(syms)} · LTF {LTF[tf]} · вход {ENTRY_BARS} баров · держим {HOLD_BARS} баров · {n_proc} процессов", flush=True)
        t0 = time.time()
        with Pool(n_proc) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, [(s, tf) for s in syms]), 1):
                if i % 25 == 0 or "ошибка" in m or "данные" in m:
                    print(f"  {i}/{len(syms)} {s}: {m}", flush=True)
        print(f"ГОТОВО за {(time.time() - t0) / 60:.1f} мин", flush=True)
    elif cmd == "ctl":
        d = pd.DataFrame([r for r in rows_of(tf) if r.get("entered")])
        n_max = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
        if len(d) > n_max:
            d = d.sample(n_max, random_state=7)      # контроли на подвыборке: 16 прогонов на сделку — дорого
        print(f"{tf}: контроли по {len(d)} сделкам", flush=True)
        jobs = [(s, tf, g.to_dict("records"), [o for o in syms if o != s]) for s, g in d.groupby("sym")]
        with Pool(int(sys.argv[4]) if len(sys.argv) > 4 else 6) as pool:
            ctl = pd.DataFrame([r for rr in pool.imap_unordered(controls, jobs) for r in rr])
        pickle.dump(ctl, open(OUT / f"ctl_{tf}.pkl", "wb"))
        print("контролей:", len(ctl))
