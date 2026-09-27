"""Егор 13.09 (VANRY-разметка): после разворота ядра идёт НОВЫЙ импульс вверх 1-2-3-4-5 на 1h.
Второй вход = откат волны 2 (вход в третью). Каузально на 1h-барах:
  L0 = точка 5 ядра (дно). Наблюдение с момента входа ядра.
  w1: первый подтверждённый свинг-верх младшего масштаба (len=SW1) после L0 → H1.
  w2: первый бар после подтверждения H1, где low ≤ H1 − RETR·(H1−L0) и дно не обновлено → лимит на уровне.
  стоп под L0, цели: H1 (пробой вершины w1) и H1 + 0.618·w1 (≈ третья 1.618), удержание HOLD_H часов.
  контроль: случайный 1h-бар той же монеты в ±30 дн, та же геометрия (стоп%, RR)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import load, _swings
from channel_depth import add_geom, SP

SW1 = int(sys.argv[1]) if len(sys.argv) > 1 else 6       # свинг младшего масштаба на 1h (часов)
RETR = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
HOLD_H = 120; BUF = 0.002; COST = 0.10; WATCH_H = 240      # окно наблюдения после входа ядра
rs = np.random.RandomState(3)


def prep(name):
    d = pd.read_pickle(SP + name); d = d[d.pnl_w4.notna()].copy()
    for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d)
    return d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1 & d.fractal_ok & (d.depth5 >= 0.5)]


def dedup(d):
    d = d.sort_values(["sym", "ts"]); keep, last = [], {}
    for i, r in d.iterrows():
        t0 = last.get(r.sym)
        if t0 is not None and (r.ts - t0) < pd.Timedelta(days=3):
            continue
        last[r.sym] = r.ts; keep.append(i)
    return d.loc[keep]


def walk(h, l, c, j, e, sl, tgts, end):
    for k in range(j, end + 1):
        if l[k] <= sl:
            return (sl - e) / e * 100, "stop", k
        for name, tp in tgts:
            if h[k] >= tp:
                return (tp - e) / e * 100, name, k
    return (c[end] - e) / e * 100, "time", end


core = dedup(pd.concat([prep("wave5sm_4h_15m_sw20_hold240_z45.pkl"), prep("wave5sm_4h_15m_sw15_il4_hold240_z45.pkl")]))
print(f"сигналов ядра v2 (лонг, 2023-26): {len(core)} · SW1={SW1} ч · откат {RETR}")
rows = []
for sym, g in core.groupby("sym"):
    d1 = load(sym, "1h")
    if d1.empty:
        continue
    t1 = d1.index.values.astype("datetime64[ns]")
    h, l, c = d1.high.values.astype(float), d1.low.values.astype(float), d1.close.values.astype(float)
    dh4 = load(sym, "4h")
    for _, r in g.iterrows():
        t5 = np.datetime64(dh4.index[int(r.b)].to_datetime64())
        i5 = int(np.searchsorted(t1, t5)); ie = int(np.searchsorted(t1, np.datetime64(pd.Timestamp(r.ts).to_datetime64())))
        iw = min(len(d1) - 1, i5 + WATCH_H)
        if ie <= i5 or ie >= iw:
            continue
        L0 = float(l[i5:ie + 1].min()); i0 = i5 + int(l[i5:ie + 1].argmin())
        # 🔴 Правка после картинки ATOM: волна 2 не может начаться ПОСЛЕ того, как цена превысила вершину
        # волны 1. Вершину ведём как текущий максимум; она «подтверждена», когда после неё прошло ≥SW1
        # баров без обновления; откат считаем от подтверждённой вершины. Первый такой откат = волна 2.
        entry_i = None; H1 = None; hi_i = None
        hmax = float(h[i0]); hmax_i = i0
        for k in range(i0 + 1, iw + 1):
            if l[k] <= L0:                                    # дно обновлено — разметка сломана
                break
            if h[k] > hmax:
                hmax, hmax_i = float(h[k]), k
                continue
            if k - hmax_i >= SW1 and k > ie and hmax > L0:    # вершина подтверждена временем, наблюдаем после входа ядра
                lvl_k = hmax - RETR * (hmax - L0)
                if l[k] <= lvl_k:
                    entry_i, H1, hi_i = k, hmax, hmax_i; break
        if entry_i is None:
            rows.append({"sym": sym, "core_ts": r.ts, "stage": "no_w2"}); continue
        w1 = H1 - L0; lvl = H1 - RETR * w1
        t1_len = hi_i - i0; t2_len = entry_i - hi_i           # длительности волны 1 и отката (для среза по времени)
        e = lvl                                               # лимит исполнен по уровню
        sl = L0 * (1 - BUF); sl_pct = (e - sl) / e * 100
        tg = [("t1", H1), ("t2", H1 + 0.618 * w1)]
        end = min(len(d1) - 1, entry_i + HOLD_H)
        res = {}
        for name, tp in tg:
            pnl, how, k = walk(h, l, c, entry_i + 1, e, sl, [(name, tp)], end)
            res[name] = (pnl - COST, how)
        # контроль: случайный бар ±30 дн, та же геометрия
        lo, hi = max(SW1 + 1, entry_i - 720), min(len(d1) - HOLD_H - 2, entry_i + 720)
        jj = rs.randint(lo, hi); ce = float(c[jj]); csl = ce * (1 - sl_pct / 100)
        ctl = {}
        for name, tp in tg:
            rr = (tp - e) / (e - sl); ctp = ce * (1 + rr * sl_pct / 100)
            pnl, how, k = walk(h, l, c, jj + 1, ce, csl, [(name, ctp)], min(len(d1) - 1, jj + HOLD_H))
            ctl[name] = pnl - COST
        rows.append({"sym": sym, "core_ts": r.ts, "stage": "entry", "entry_ts": d1.index[entry_i], "lag_h": entry_i - i0,
                     "t1_len": t1_len, "t2_len": t2_len,
                     "w1_pct": w1 / L0 * 100, "sl_pct": sl_pct, "rr1": (H1 - e) / (e - sl), "rr2": (H1 + 0.618 * w1 - e) / (e - sl),
                     "pnl_t1": res["t1"][0], "how_t1": res["t1"][1], "pnl_t2": res["t2"][0], "how_t2": res["t2"][1],
                     "ctl_t1": ctl["t1"], "ctl_t2": ctl["t2"], "core_pnl": r.pnl_w4, "year": pd.Timestamp(r.ts).year})
f = pd.DataFrame(rows)
print("стадии:", f.stage.value_counts().to_dict())
e = f[f.stage == "entry"].copy()
if len(e):
    e.to_pickle(SP + f"wave3_after_core_sw{SW1}_r{RETR}.pkl")
    yrs = 3.5
    for k in ("t1", "t2"):
        pn, ct = e[f"pnl_{k}"], e[f"ctl_{k}"]; R = pn / e.sl_pct
        ep = e.groupby(e.entry_ts.dt.strftime("%Y-%m-%d"))[f"pnl_{k}"].mean()
        print(f"цель {k}: n={len(e)} ({len(e)/yrs:.0f}/год) на сд {pn.mean():+.2f}% медиана {pn.median():+.2f} R {R.mean():+.2f} медR {R.median():+.2f} WR {(pn>0).mean()*100:.0f}% "
              f"дошли {(e[f'how_{k}']==k).mean()*100:.0f}% стоп-аут {(e[f'how_{k}']=='stop').mean()*100:.0f}% стоп {e.sl_pct.median():.2f}% RR {e[f'rr{k[-1]}'].median():.2f} "
              f"| контроль {ct.mean():+.2f} перевес {(pn-ct).mean():+.2f} | безтоп10 {pn.sort_values(ascending=False).iloc[int(len(pn)*0.1):].mean():+.2f} монет+ {(e.groupby('sym')[f'pnl_{k}'].sum()>0).mean()*100:.0f}% дней {len(ep)} дней+ {(ep>0).mean()*100:.0f}% мед.дня {ep.median():+.2f}")
    print("  по годам (t1):", {y: (len(x), round(x.pnl_t1.mean(), 2)) for y, x in e.groupby("year")})
    print(f"  вход через {e.lag_h.median():.0f} ч после дна · волна 1 медиана {e.w1_pct.median():.1f}% · ядро на тех же сигналах {e.core_pnl.mean():+.2f}%")
    print("  связь с исходом ядра: ядро+ →", round(e[e.core_pnl > 0].pnl_t1.mean(), 2), "| ядро− →", round(e[e.core_pnl <= 0].pnl_t1.mean(), 2))
    print("  волна 1 длит. медиана", int(e.t1_len.median()), "ч · откат", int(e.t2_len.median()), "ч · по корзинам стопа (t1):",
          {f"{lo}-{hi}%": (len(x), round(x.pnl_t1.mean(), 2), round((x.pnl_t1 / x.sl_pct).mean(), 2)) for lo, hi in ((0, 3), (3, 6), (6, 99)) for x in [e[(e.sl_pct >= lo) & (e.sl_pct < hi)]] if len(x)})
