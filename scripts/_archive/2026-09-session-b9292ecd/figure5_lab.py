"""ПЯТИВОЛНОВЫЕ КОРРЕКЦИИ a-b-c-d-e ВСЕХ ФОРМ → выход из фигуры (Егор 18.09, скрин XLM 1h: после дампа — восходящий
канал из пяти волн; «после таких коррекций бывают хорошие движения»).

Расширение triangle_lab: те же 5 чередующихся свингов, но фигура классифицируется по наклону границ:
  сходящийся (вершины↓ низы↑) · расширяющийся (вершины↑ низы↓) · восходящий канал (вершины↑ низы↑; клин — если
  границы сходятся) · нисходящий канал (вершины↓ низы↓; клин — если сходятся). Флаг = канал ПРОТИВ ноги, ведущей в фигуру.
Каузально: фигура известна с бара подтверждения точки e; окна по сырым свингам. Пробой — закрытие бара за границей
(верхняя — через два последних top, нижняя — через два последних low), вход по open следующего бара; стоп за последним
свингом против хода (буфер 0.15%); ДВЕ цели: высота фигуры от точки пробоя и длина ноги, ведущей в фигуру («древко»);
удержание max(24, 2·длина фигуры) баров; кост 0.10%. Ожидание пробоя — не дольше длины фигуры.
Контроли: случайный сдвиг ±30 дней той же монеты (×8) и 5 других монет в тот же момент, та же геометрия.
Запуск: python figure5_lab.py run [монет] [процессов] · report
"""
import sys, glob, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk, geo, COST, BUF, T0

import os
QUALITY = os.environ.get("QUALITY") == "1"     # фильтр «чистой» фигуры: 3 точки стороны на одной линии (±15% высоты), фигура меньше ноги
OUT = Path("G:/oko_lab/out/figure5" + ("_q" if QUALITY else "")); OUT.mkdir(parents=True, exist_ok=True)
GRID = {"4h": (5, 8), "1h": (8, 12), "15m": (8, 12)}


def classify(tops, bots):
    up_t = all(tops[i + 1][1] > tops[i][1] for i in range(len(tops) - 1)); dn_t = all(tops[i + 1][1] < tops[i][1] for i in range(len(tops) - 1))
    up_b = all(bots[i + 1][1] > bots[i][1] for i in range(len(bots) - 1)); dn_b = all(bots[i + 1][1] < bots[i][1] for i in range(len(bots) - 1))
    if dn_t and up_b:
        return "сходящийся"
    if up_t and dn_b:
        return "расширяющийся"
    if up_t and up_b:
        return "восходящий канал"
    if dn_t and dn_b:
        return "нисходящий канал"
    return None


def scan(d, tf, sw):
    from core.smc.oko_sm_engine import _swings
    dr = d.reset_index(drop=True); idx = d.index
    hi, lo, cl, op = dr.high.values.astype(float), dr.low.values.astype(float), dr.close.values.astype(float), dr.open.values.astype(float)
    sws = _swings(dr.high, dr.low, sw)
    rows = []; used_e = set(); busy_until = -1
    for w0 in range(2, len(sws) - 4):
        win = sws[w0:w0 + 5]
        if any(win[i][3] == win[i + 1][3] for i in range(4)):
            continue
        tops = [(s[1], s[2]) for s in win if s[3]]; bots = [(s[1], s[2]) for s in win if not s[3]]
        kind = classify(tops, bots)
        if kind is None:
            continue
        a, e = win[0], win[-1]
        if e[1] in used_e:
            continue
        conf = e[0]
        if idx[conf] < T0 or conf + 2 >= len(dr):
            continue
        (x1, y1), (x2, y2) = tops[-2], tops[-1]; (u1, v1), (u2, v2) = bots[-2], bots[-1]
        su = (y2 - y1) / max(1, x2 - x1); sl_ = (v2 - v1) / max(1, u2 - u1)
        height = max(p for _, p in tops) - min(p for _, p in bots)
        if QUALITY:
            ok = True
            for pts in (tops, bots):
                if len(pts) == 3:
                    (i0, p0), (i1, p1), (i2, p2) = pts
                    y = p0 + (p2 - p0) * (i1 - i0) / max(1, i2 - i0)
                    ok &= abs(p1 - y) <= 0.15 * height
            if not ok:
                continue
        width_e = (y2 + su * (e[1] - x2)) - (v2 + sl_ * (e[1] - u2))          # ширина канала у точки e
        span = e[1] - a[1]
        prev = sws[w0 - 1]; prev2 = sws[w0 - 2]
        trend_up = bool(prev[3])                                            # фигура началась с вершины → нога в фигуру шла вверх
        leg = abs(prev[2] - prev2[2]); leg_pct = leg / prev2[2] * 100
        if QUALITY:
            # нога — от экстремума окна 3·span баров ДО точки prev (а не от соседнего свинга: глазами GLM/MAV —
            # «нога 15-20%» была мелкой коррекцией внутри роста, а «канал» — самим ростом). Флаг ≤ 2/3 ноги.
            j0 = max(0, prev[1] - 3 * span)
            leg = (hi[j0:prev[1] + 1].max() - prev[2]) if not prev[3] else (prev[2] - lo[j0:prev[1] + 1].min())
            leg_pct = leg / prev[2] * 100
            if leg <= 0 or height > leg / 1.5:
                continue
        sub = kind
        if kind in ("восходящий канал", "нисходящий канал"):
            conv = (su < sl_) if kind == "восходящий канал" else (sl_ > su)   # границы сходятся → клин
            sub = kind.replace("канал", "клин") if conv else kind
            flag = (kind == "восходящий канал") != trend_up                  # канал против ноги = флаг
        else:
            flag = False
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
        if (long_ and sl >= ent) or (not long_ and sl <= ent):
            continue
        hold = max(24, 2 * span)
        base = {"tf": tf, "sw": sw, "kind": kind, "sub": sub, "flag": flag, "side": "LONG" if long_ else "SHORT",
                "trend_up": trend_up, "leg_pct": leg_pct, "height_pct": height / ent * 100, "span": span, "wait": t - conf,
                "entry_t": idx[t + 1], "entry": ent, "stop": sl, "risk_pct": abs(ent - sl) / ent * 100, "hold": hold,
                "e_t": idx[e[1]], "a_t": idx[a[1]]}
        first = True
        for tgt_nm, dist in (("высота фигуры", height), ("нога в фигуру", leg)):
            tp = line + dist if long_ else line - dist
            if (long_ and tp <= ent) or (not long_ and tp >= ent):
                continue
            pnl, outc, k_out = walk(hi, lo, cl, t + 1, t + 1 + hold, long_, ent, sl, tp)
            if first:
                busy_until = k_out; first = False
            rows.append({**base, "цель": tgt_nm, "target": tp, "tgt_pct": abs(tp - ent) / ent * 100, "outcome": outc, "pnl": round(pnl, 2)})
    return rows


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
        except Exception:
            continue
        if len(d) < 500:
            continue
        trades = []
        for sw in sws_:
            trades += scan(d, tf, sw)
        if not trades:
            continue
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
    d["класс"] = np.where((d.side == "LONG") == d.trend_up, "продолжение ноги", "против ноги")
    d["форма"] = np.where(d.flag, "флаг (канал против ноги)", d["sub"])
    print(f"сделок {len(d)} · монет {d.sym.nunique()} · {pd.to_datetime(d.entry_t).min():%Y-%m} → {pd.to_datetime(d.entry_t).max():%Y-%m}\n")
    for tgt in ("высота фигуры", "нога в фигуру"):
        s = d[d["цель"] == tgt]
        print(f"\n################ ЦЕЛЬ: {tgt}")
        print("=== форма × ТФ × сторона × класс"); print(agg(s.groupby(["форма", "tf", "side", "класс"])).to_string())
    s = d[d["цель"] == "высота фигуры"]
    for tf in GRID:
        z = s[s.tf == tf]
        print(f"\n=== {tf}: форма × сторона × год (цель — высота)"); print(agg(z.groupby(["форма", "side", "год"])).to_string())
        z = z.assign(корзина=pd.cut(z.risk_pct, [0, 2, 4, 8, 15, 100], labels=["<2%", "2–4%", "4–8%", "8–15%", ">15%"]))
        print(f"\n=== {tf}: форма × сторона × корзина стопа"); print(agg(z.groupby(["форма", "side", "корзина"], observed=True)).to_string())
        z = z.assign(нога=pd.cut(z.leg_pct, [0, 5, 10, 20, 40, 1000], labels=["<5%", "5–10%", "10–20%", "20–40%", ">40%"]))
        print(f"\n=== {tf}: форма × сторона × размер ноги в фигуру"); print(agg(z.groupby(["форма", "side", "нога"], observed=True)).to_string())
        day = pd.to_datetime(z.entry_t).dt.floor("D")
        z = z.assign(масс=day.map(day.value_counts()))
        z = z.assign(масс_к=pd.cut(z["масс"], [0, 1, 3, 6, 999], labels=["1", "2–3", "4–6", "≥7"]))
        print(f"\n=== {tf}: форма × сторона × массовость дня"); print(agg(z.groupby(["форма", "side", "масс_к"], observed=True)).to_string())
        for (f_, side), q in z.groupby(["форма", "side"]):
            top = q.pnl.nlargest(max(1, int(len(q) * 0.1))).sum()
            print(f"  хрупкость {tf} {f_} {side}: n {len(q)} · сумма {q.pnl.sum():.0f} · без верхних 10% {q.pnl.sum() - top:.0f} · исходы {q.outcome.value_counts().to_dict()}")


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
