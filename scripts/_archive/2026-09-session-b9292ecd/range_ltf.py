"""ОТБОЙ ОТ ГРАНИЦ ДИАПАЗОНА НА LTF (Егор 16.09: «2026 год флэта! именно поэтому я прошу тебя искать на LTF»).
Импульсная механика на 15m/5m проверена и мертва при любом триггере — потому что во флэте нет импульса.
Здесь другая механика, подходящая флэту: цена прокалывает границу суточного диапазона и ВОЗВРАЩАЕТСЯ внутрь.

Правила (каузально, только закрытые бары):
  диапазон = max(high)/min(low) за N баров ДО текущего (N = сутки: 96 баров 15m, 288 баров 5m);
  LONG: бар пробил нижнюю границу (low <= lo) и закрылся обратно внутрь (close > lo) → вход по open следующего;
  стоп: за минимумом этого бара (буфер 0.15%); цели: середина диапазона и противоположная граница;
  удержание 60 баров, кост 0.10%; ширина диапазона обязана попадать в коридор (иначе это не флэт, а обвал).
Запуск: python range_ltf.py run <тф> [монет] [процессов] · report <тф>
"""
import sys, pickle, time, glob, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/range_ltf"); OUT.mkdir(parents=True, exist_ok=True)
BARS_DAY = {"15m": 96, "5m": 288, "1h": 24}        # сутки в барах
HOLD_BARS, COST, BUF = 60, 0.10, 0.0015
STOP_K = float(__import__("os").environ.get("STOP_K", "0.25"))   # стоп за границей на долю ширины диапазона
W_MIN, W_MAX = 2.0, 25.0                            # ширина диапазона в % — коридор «это флэт, а не обвал»
T0 = pd.Timestamp("2023-02-01")


def run_symbol(args):
    sym, tf = args
    out_p = OUT / f"{tf}_{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    t0 = time.time()
    try:
        d = load_tf(sym, tf)
    except Exception as e:
        return sym, f"данные: {e}"
    n = BARS_DAY[tf]
    if len(d) < n + 500:
        return sym, "мало истории"
    d = d[d.index >= T0 - pd.Timedelta(days=3)]
    if len(d) < n + 200:
        return sym, "мало истории"
    idx = d.index.values
    o, h, l, c = (d.open.values.astype(float), d.high.values.astype(float),
                  d.low.values.astype(float), d.close.values.astype(float))
    # границы диапазона по ПРЕДЫДУЩИМ n барам (текущий не входит — иначе заглядывание)
    hi = pd.Series(h).rolling(n).max().shift(1).values
    lo = pd.Series(l).rolling(n).min().shift(1).values
    rows = []
    last_entry = -10**9
    for i in range(n + 1, len(d) - 2):
        if not np.isfinite(hi[i]) or not np.isfinite(lo[i]) or lo[i] <= 0:
            continue
        width = (hi[i] - lo[i]) / lo[i] * 100
        if not (W_MIN <= width <= W_MAX):
            continue
        if i - last_entry < n // 4:                 # не чаще раза в четверть суток на монету
            continue
        long_ = l[i] <= lo[i] and c[i] > lo[i]      # прокол вниз и возврат внутрь
        short_ = h[i] >= hi[i] and c[i] < hi[i]
        if not (long_ or short_):
            continue
        j = i + 1
        e = float(o[j])
        rng = hi[i] - lo[i]
        # стоп СТРУКТУРНЫЙ: за границей диапазона на долю его ширины. Тугой стоп за баром (медиана 0.67%)
        # давал 76% стоп-аутов — ровно закон «стоп выбивает раньше хода»: единственной плюсовой корзиной
        # в первой версии была риск >4% (WR 61.6%).
        if long_:
            sl = float(lo[i]) - STOP_K * rng
            tp_mid = (hi[i] + lo[i]) / 2; tp_far = float(hi[i])
        else:
            sl = float(hi[i]) + STOP_K * rng
            tp_mid = (hi[i] + lo[i]) / 2; tp_far = float(lo[i])
        if ((tp_mid <= e) or (sl >= e)) if long_ else ((tp_mid >= e) or (sl <= e)):
            continue
        last_entry = i
        end = min(j + HOLD_BARS, len(d) - 1)
        rec = {"sym": sym, "tf": tf, "side": "LONG" if long_ else "SHORT", "t": pd.Timestamp(idx[j]),
               "entry": e, "stop": sl, "width": width, "risk_pct": abs(e - sl) / e * 100}
        for nm, tp in (("mid", tp_mid), ("far", tp_far)):
            out_px, outc = None, None
            for k in range(j, end + 1):
                if (l[k] <= sl) if long_ else (h[k] >= sl):
                    out_px, outc = sl, "stop"; break
                if (h[k] >= tp) if long_ else (l[k] <= tp):
                    out_px, outc = tp, "target"; break
            if out_px is None:
                out_px, outc = float(c[end]), "time"
            rec[f"pnl_{nm}"] = round(((out_px - e) / e * 100) * (1 if long_ else -1) - COST, 3)
            rec[f"outcome_{nm}"] = outc
            rec[f"tgt_{nm}_pct"] = abs(tp - e) / e * 100
        rows.append(rec)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сделок за {time.time() - t0:.0f}с"


def report(tf):
    rows = [r for f in glob.glob(str(OUT / f"{tf}_*.pkl")) for r in pickle.load(open(f, "rb"))]
    if not rows:
        print(f"{tf}: пусто"); return
    d = pd.DataFrame(rows)
    d["год"] = pd.to_datetime(d.t).dt.year
    d["режим BTC"] = np.where(d["год"] <= 2024, "2023-24 тренд", "2025-26 ФЛЭТ")
    мес = (pd.to_datetime(d.t).max() - pd.to_datetime(d.t).min()).days / 30.44
    print(f"\n=== {tf}: отбой от границ суточного диапазона · сделок {len(d)} · монет {d.sym.nunique()} · {len(d)/мес:.0f} сд/мес")
    for tgt in ("mid", "far"):
        print(f"\n--- цель {'середина диапазона' if tgt=='mid' else 'противоположная граница'}")
        g = d.groupby(["режим BTC", "side"]).agg(n=(f"pnl_{tgt}", "size"), WR=(f"pnl_{tgt}", lambda x: (x > 0).mean() * 100),
                                                 ср=(f"pnl_{tgt}", "mean"), мед=(f"pnl_{tgt}", "median"),
                                                 сумма=(f"pnl_{tgt}", "sum"), риск=("risk_pct", "median"),
                                                 цель=(f"tgt_{tgt}_pct", "median"))
        print(g.round(2).to_string())
    print("\nпо годам (среднее %, цель=середина):")
    print(d.pivot_table(index="год", columns="side", values="pnl_mid", aggfunc=["mean", "size"]).round(2).to_string())


if __name__ == "__main__":
    cmd, tf = sys.argv[1], sys.argv[2]
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    random.Random(5).shuffle(syms)
    if cmd == "run":
        if len(sys.argv) > 3:
            syms = syms[:int(sys.argv[3])]
        with Pool(int(sys.argv[4]) if len(sys.argv) > 4 else 8) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, [(s, tf) for s in syms]), 1):
                if i % 100 == 0:
                    print(f"  {i}/{len(syms)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report(tf)
