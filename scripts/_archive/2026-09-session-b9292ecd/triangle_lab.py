"""ТРЕУГОЛЬНИК a-b-c-d-e → выход из него (Егор 18.09: «коррекции a-b-c-d-e ведь тоже 5 волн, мы их можем определять!
после таких коррекций бывают хорошие движения»).

Детектор — тот же, что в аналитике (core.waves.wave_progress.triangle_ltf): 5 чередующихся свингов, вершины понижаются,
низы повышаются (сходящийся). Здесь он прогнан ПО ИСТОРИИ каузально: свинг известен с бара подтверждения (_swings → s[0]),
фигура — с подтверждения точки e; окна берутся по СЫРЫМ свингам (без склейки соседей одного типа — склейка смотрит вперёд).
Сделка: ждём закрытия бара за линией (верхняя — через два последних top, нижняя — через два последних low), вход по open
следующего бара; стоп — за последним свингом против хода (пробой вверх → под последним low, буфер 0.15%); цель — высота
треугольника (самая широкая часть) от точки пробоя; удержание max(24, 2·длина фигуры) баров; кост 0.10%.
Отмена ожидания: линии сошлись (<25% высоты) или прошло больше длины фигуры без пробоя.
Контроли: случайный сдвиг ±30 дней той же монеты (×8) и 5 других монет в тот же момент, та же геометрия.
Срезы: ТФ × свинг × сторона × согласованность с точкой e (thrust) × тренд до фигуры × год × корзины × массовость.
Запуск: python triangle_lab.py run [монет] [процессов] · report
"""
import sys, glob, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ

OUT = Path("G:/oko_lab/out/triangle"); OUT.mkdir(parents=True, exist_ok=True)
GRID = {"4h": (5, 8), "1h": (8, 12), "15m": (8, 12)}
COST, BUF = 0.10, 0.0015
T0 = pd.Timestamp("2020-06-01")
TF_MIN = {"15m": 15, "1h": 60, "4h": 240}


def walk(hi, lo, cl, j0, j1, long_, e, sl, tp):
    """→ (pnl%, исход, бар выхода)."""
    for k in range(j0, min(j1, len(hi))):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - COST, "stop", k
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - COST, "target", k
    k = min(j1, len(hi)) - 1
    return ((float(cl[k]) - e) / e * 100) * (1 if long_ else -1) - COST, "time", k


def scan(d, tf, sw):
    """Все треугольники по истории одной монеты на одном ТФ/масштабе → список сделок."""
    from core.smc.oko_sm_engine import _swings
    dr = d.reset_index(drop=True); idx = d.index
    hi, lo, cl, op = dr.high.values.astype(float), dr.low.values.astype(float), dr.close.values.astype(float), dr.open.values.astype(float)
    sws = _swings(dr.high, dr.low, sw)
    rows = []; used_e = set(); busy_until = -1                # одна открытая сделка на монету/ТФ/масштаб: вложенные фигуры не дублируются
    for w0 in range(2, len(sws) - 4):
        win = sws[w0:w0 + 5]
        if any(win[i][3] == win[i + 1][3] for i in range(4)):
            continue                                              # окно без чередования — не фигура
        tops = [(s[1], s[2]) for s in win if s[3]]; bots = [(s[1], s[2]) for s in win if not s[3]]
        if not (all(tops[i + 1][1] < tops[i][1] for i in range(len(tops) - 1)) and all(bots[i + 1][1] > bots[i][1] for i in range(len(bots) - 1))):
            continue
        a, e = win[0], win[-1]
        if e[1] in used_e:
            continue
        conf = e[0]                                               # фигура известна с бара подтверждения e
        if idx[conf] < T0 or conf + 2 >= len(dr):
            continue
        (x1, y1), (x2, y2) = tops[-2], tops[-1]; (u1, v1), (u2, v2) = bots[-2], bots[-1]
        su = (y2 - y1) / max(1, x2 - x1); sl_ = (v2 - v1) / max(1, u2 - u1)
        height = max(p for _, p in tops) - min(p for _, p in bots)
        span = e[1] - a[1]
        prev = sws[w0 - 1]; prev2 = sws[w0 - 2]                 # точка до фигуры и нога, в неё ведущая
        trend_up = bool(prev[3])                                  # фигура началась с вершины → тренд до неё вверх
        leg_pct = abs(prev[2] - prev2[2]) / prev2[2] * 100
        brk = None
        for t in range(conf + 1, min(len(dr) - 1, e[1] + span + 1)):
            upper = y2 + su * (t - x2); lower = v2 + sl_ * (t - u2)
            if upper - lower < 0.25 * height:
                break
            if cl[t] > upper:
                brk = (t, True, upper); break
            if cl[t] < lower:
                brk = (t, False, lower); break
        if brk is None:
            continue
        t, long_, line = brk
        if t + 1 <= busy_until:
            continue
        used_e.add(e[1])
        ent = float(op[t + 1])
        last_low = min(bots, key=lambda z: -z[0])[1]; last_top = min(tops, key=lambda z: -z[0])[1]
        sl = last_low * (1 - BUF) if long_ else last_top * (1 + BUF)
        tp = line + height if long_ else line - height
        if (long_ and (sl >= ent or tp <= ent)) or (not long_ and (sl <= ent or tp >= ent)):
            continue
        hold = max(24, 2 * span)
        pnl, outc, k_out = walk(hi, lo, cl, t + 1, t + 1 + hold, long_, ent, sl, tp)
        busy_until = k_out
        rows.append({"tf": tf, "sw": sw, "side": "LONG" if long_ else "SHORT", "thrust": (long_ != bool(e[3])),
                     "trend_up": trend_up, "leg_pct": leg_pct, "height_pct": height / ent * 100, "span": span,
                     "wait": t - conf, "entry_t": idx[t + 1], "entry": ent, "stop": sl, "target": tp,
                     "risk_pct": abs(ent - sl) / ent * 100, "tgt_pct": abs(tp - ent) / ent * 100, "hold": hold,
                     "outcome": outc, "pnl": round(pnl, 2), "e_t": idx[e[1]], "a_t": idx[a[1]]})
    return rows


def geo(dd, t0, long_, rsk, tg, hold):
    j0 = int(dd.index.searchsorted(t0))
    if len(dd) - j0 < 12:
        return np.nan
    e = float(dd.open.values[j0])
    hi, lo, cl = dd.high.values, dd.low.values, dd.close.values
    return walk(hi, lo, cl, j0, j0 + hold, long_, e, e * (1 - rsk) if long_ else e * (1 + rsk), e * (1 + tg) if long_ else e * (1 - tg))[0]


def run_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    t_start = time.time(); rows = []
    rs = random.Random(sum(map(ord, sym)) + 7)
    for tf, sws_ in GRID.items():
        try:
            d = load_tf(sym, tf)
        except Exception as e:
            continue
        if len(d) < 500:
            continue
        trades = []
        for sw in sws_:
            trades += scan(d, tf, sw)
        if not trades:
            continue
        # контроли: 5 чужих монет на ТФ загружаются один раз
        oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, tf))
            except Exception:
                pass
        for tr in trades:
            long_ = tr["side"] == "LONG"; rsk, tg = tr["risk_pct"] / 100, tr["tgt_pct"] / 100; et = tr["entry_t"]
            a = [geo(d, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, tr["hold"]) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, tr["hold"]) for o in oth]
            tr["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            tr["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
            tr["sym"] = sym
        rows += trades
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сделок за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median"),
                 цель=("tgt_pct", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    d = pd.DataFrame([r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))])
    d["год"] = pd.to_datetime(d.entry_t).dt.year
    d["согл"] = np.where(d.thrust, "thrust (по точке e)", "против e")
    d["тренд"] = np.where(d.trend_up, "тренд до фигуры ↑", "тренд до фигуры ↓")
    print(f"сделок {len(d)} · монет {d.sym.nunique()} · {pd.to_datetime(d.entry_t).min():%Y-%m} → {pd.to_datetime(d.entry_t).max():%Y-%m}\n")
    print("=== ТФ × свинг × сторона"); print(agg(d.groupby(["tf", "sw", "side"])).to_string())
    print("\n=== ТФ × сторона × согласованность с e"); print(agg(d.groupby(["tf", "side", "согл"])).to_string())
    print("\n=== ТФ × сторона × тренд до фигуры (продолжение = сторона совпадает с трендом)")
    d["класс"] = np.where((d.side == "LONG") == d.trend_up, "продолжение", "разворот")
    print(agg(d.groupby(["tf", "side", "класс"])).to_string())
    for tf in GRID:
        s = d[d.tf == tf]
        if s.empty:
            continue
        print(f"\n=== {tf}: сторона × год"); print(agg(s.groupby(["side", "год"])).to_string())
        s = s.assign(корзина=pd.cut(s.risk_pct, [0, 2, 4, 8, 15, 100], labels=["<2%", "2–4%", "4–8%", "8–15%", ">15%"]))
        print(f"\n=== {tf}: сторона × корзина стопа"); print(agg(s.groupby(["side", "корзина"], observed=True)).to_string())
        s = s.assign(высота=pd.cut(s.height_pct, [0, 5, 10, 20, 40, 1000], labels=["<5%", "5–10%", "10–20%", "20–40%", ">40%"]))
        print(f"\n=== {tf}: сторона × высота фигуры"); print(agg(s.groupby(["side", "высота"], observed=True)).to_string())
        day = pd.to_datetime(s.entry_t).dt.floor("D")
        s = s.assign(масс=day.map(day.value_counts()))
        s = s.assign(масс_к=pd.cut(s["масс"], [0, 1, 3, 6, 999], labels=["1", "2–3", "4–6", "≥7"]))
        print(f"\n=== {tf}: сторона × массовость дня"); print(agg(s.groupby(["side", "масс_к"], observed=True)).to_string())
        for side in ("LONG", "SHORT"):
            z = s[s.side == side]
            if len(z):
                top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
                print(f"  хрупкость {tf} {side}: сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · исходы {z.outcome.value_counts().to_dict()}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, jobs), 1):
                if i % 50 == 0 or i <= 3:
                    print(f"  {i}/{len(jobs)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
