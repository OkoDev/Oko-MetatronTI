"""ВХОД impulse_fib 1h — ПРОВЕРКА И ПОЧИНКА (Егор 26.09: «вход impulse_fib 1h берем в проверку и починку»).

Проблема измерена: из 17 494 заявок, дошедших до лимита, исполнилось 1 987 — **11%**
(в бою на реальных ценах 8%: 4 фила из 52). Эдж 1h, на который мы опираемся, относится
к одной десятой его сигналов — остальные проходят мимо.

Один калькулятор: та же `find_impulses` и те же гейты, что в бою и в map_replays; отличается
ТОЛЬКО способ входа. Геометрия боя: entry = extreme + sign·fib·amp, sl = entry ∓ 2.5·ATR
(стоп ОТ ВХОДА → при другом fib меняется и стоп), tp = extreme + sign·(−1.618)·amp (от экстремума).

Варианты:
  лимит 0.236 / 0.382(бой) / 0.5 / 0.618      — глубина отката
  лимит 0.382 · ожидание 24 / 48 баров        — дольше ждём фила
  рынок на закрытии бара сигнала              — фил 100%, цена хуже
  рынок + стоп за экстремум                   — то же, но стоп структурный (за вершиной импульса)
Фильтр стопа 1.5–3.234% применяется КАЖДОМУ варианту (часть боевой конфигурации) — поэтому
у вариантов разное число сетапов, и воронка печатается для каждого.

Косты 0.10%. Контроль (та же геометрия, ±30 дн той же монеты) — для финалистов, вторым проходом.
python entry_lab_1h.py run [процессов] · report
"""
import sys, glob, pickle, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ                        # noqa: E402
from map_replays import _fill, _turn, T0, COST, MIN_TURN  # noqa: E402
from triangle_lab import walk                             # noqa: E402

OUT = Path("G:/oko_lab/out/entry_lab_1h"); OUT.mkdir(parents=True, exist_ok=True)
MIN_STOP, MAX_STOP = 1.5, 3.234

# (имя, глубина отката или None=рынок, окно ожидания, стоп «за экстремум»?)
VARIANTS = [
    ("лимит 0.236",        0.236, 12, False),
    ("лимит 0.382 (бой)",  0.382, 12, False),
    ("лимит 0.5",          0.5,   12, False),
    ("лимит 0.618",        0.618, 12, False),
    ("лимит 0.382 · ждём 24", 0.382, 24, False),
    ("лимит 0.382 · ждём 48", 0.382, 48, False),
    ("рынок",              None,  0,  False),
    ("рынок · стоп за экстремум", None, 0, True),
]


def one(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, 0
    try:
        m = load_tf(sym, "1h")
    except Exception:
        return sym, 0
    if m is None or len(m) < 400:
        return sym, 0
    from core.smc.impulse_fib import find_impulses, _atr, HOLD_BARS, TARGET_FIB, STOP_ATR_K, VOL_LO, VOL_HI, REGIME_MIN
    d = m.reset_index(drop=True); n = len(d)
    H, L, C, V = d.high.values, d.low.values, d.close.values, d.volume.values
    aa = _atr(d); atr = aa.values
    regime = (aa / aa.rolling(100).mean()).values
    ema200 = d.close.ewm(span=200, adjust=False).mean().values
    volma = pd.Series(V).rolling(120).mean().values
    turn = _turn(m, 24); mi = m.index.values
    i0 = int(np.searchsorted(mi, np.datetime64(T0)))
    imps = find_impulses(H, L, C, atr, n, start=max(60, i0 - 100))

    rows = []
    fun = {v[0]: {"сетапов": 0, "стоп вне": 0, "без фила": 0, "сделок": 0} for v in VARIANTS}
    for a, b, up in imps:
        if b < i0 or b + 2 >= n:
            continue
        origin, extreme = float(C[a]), float(C[b]); amp = abs(extreme - origin)
        if amp <= 0:
            continue
        # гейты источника считаем ОДИН раз — они от входа не зависят
        vratio = float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0
        reg = float(regime[b]) if not np.isnan(regime[b]) else 1.0
        with_trend = bool((C[b] > ema200[b]) == up)
        if not (VOL_LO <= vratio < VOL_HI and with_trend and reg >= REGIME_MIN):
            continue
        if not (turn[b] == turn[b] and turn[b] >= MIN_TURN):
            continue
        sign = -1.0 if up else 1.0
        tp = extreme + sign * TARGET_FIB * amp
        ext_stop = (min(L[a:b + 1]) * 0.999) if up else (max(H[a:b + 1]) * 1.001)

        for name, fib, wait, struct_stop in VARIANTS:
            fun[name]["сетапов"] += 1
            if fib is None:
                e = float(C[b])                       # рынок: закрытие бара сигнала
            else:
                e = extreme + sign * fib * amp
            sl = ext_stop if struct_stop else (e - STOP_ATR_K * atr[b] if up else e + STOP_ATR_K * atr[b])
            if (up and sl >= e) or (not up and sl <= e):
                fun[name]["стоп вне"] += 1; continue
            stop_pct = abs(e - sl) / e * 100
            if not (MIN_STOP <= stop_pct <= MAX_STOP):
                fun[name]["стоп вне"] += 1; continue
            if fib is None:
                fill = b                              # рынок: входим на баре сигнала
            else:
                fill = _fill(H, L, b + 1, wait, up, e, sl)
                if fill is None:
                    fun[name]["без фила"] += 1; continue
            pnl, outc, k_out = walk(H, L, C, fill + 1, fill + 1 + HOLD_BARS, up, e, sl, tp)
            fun[name]["сделок"] += 1
            rows.append({"sym": sym, "вариант": name, "side": "LONG" if up else "SHORT",
                         "signal_t": pd.Timestamp(mi[b]), "entry_t": pd.Timestamp(mi[fill]),
                         "pnl": round(pnl, 3), "stop_pct": stop_pct, "tgt_pct": abs(tp - e) / e * 100,
                         "outcome": outc, "год": pd.Timestamp(mi[b]).year,
                         "ждал_баров": int(fill - b)})
    pickle.dump({"rows": rows, "funnel": fun}, open(out_p, "wb"))
    return sym, len(rows)


def report():
    R, F = [], {}
    for f in glob.glob(str(OUT / "*.pkl")):
        p = pickle.load(open(f, "rb"))
        R += p["rows"]
        for k, v in p["funnel"].items():
            t = F.setdefault(k, {})
            for kk, vv in v.items():
                t[kk] = t.get(kk, 0) + vv
    d = pd.DataFrame(R)
    pd.set_option("display.width", 260)
    print(f"монет {len(glob.glob(str(OUT / '*.pkl')))} · сделок всего {len(d)} · окно {d.signal_t.min():%Y-%m} → {d.signal_t.max():%Y-%m}\n")
    fn = pd.DataFrame(F).T
    fn["фил %"] = (100 * fn["сделок"] / (fn["сделок"] + fn["без фила"]).replace(0, np.nan)).round(0)
    print("=== ВОРОНКА по вариантам входа")
    print(fn.to_string())
    g = d.groupby("вариант").agg(сделок=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"),
                                 медиана=("pnl", "median"), WR=("pnl", lambda x: 100 * (x > 0).mean()),
                                 стоп=("stop_pct", "mean"), цель=("tgt_pct", "mean"))
    g["безтоп10%"] = [d[d["вариант"] == v].pnl.sum() - d[d["вариант"] == v].pnl.nlargest(max(1, len(d[d["вариант"] == v]) // 10)).sum() for v in g.index]
    print("\n=== ДЕНЬГИ по вариантам (косты уже вычтены)")
    print(g.round(2).sort_values("сумма", ascending=False).to_string())
    print("\n=== сторона × вариант (средн %)")
    print(d.pivot_table(index="вариант", columns="side", values="pnl", aggfunc="mean").round(2).to_string())
    print("\n=== год × вариант (средн %)")
    print(d.pivot_table(index="год", columns="вариант", values="pnl", aggfunc="mean").round(2).to_string())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "report":
        report()
    else:
        syms = sorted({Path(p).stem for p in glob.glob(str(Path(PARQ) / "*.parquet"))}) if Path(PARQ).exists() else []
        if not syms:
            syms = sorted({Path(p).stem for p in glob.glob("G:/oko_lab/tf/*_1h.pkl")})
            syms = [s.replace("_1h", "") for s in syms]
        nproc = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        print(f"монет: {len(syms)} · процессов: {nproc}", flush=True)
        done = 0
        with Pool(nproc) as pool:
            for sym, k in pool.imap_unordered(one, syms):
                done += 1
                if done % 25 == 0:
                    print(f"  {done}/{len(syms)}", flush=True)
        report()
