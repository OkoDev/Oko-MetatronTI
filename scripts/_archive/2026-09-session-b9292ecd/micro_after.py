"""Третий слой (Егор 13.09): микроструктура НОВОГО импульса после входа ядра, на LTF (5m с 2025, иначе 15m).
Для каждой сделки из pkl (обе стороны): от экстремума пятёрки (E0) размечаем волны нового импульса
бегущим экстремумом с подтверждением SW_H часов без обновления: w1 → откат w2 (первый откат ≥RETR от
подтверждённой w1 без обновления E0) → w3 (новый экстремум за w1) → w4 (откат от подтверждённой w3) → w5.
Проверка правил: w2 не за E0, w3 за L1, пропорции w3/w1, w2/w1. Второй вход на откате w2 (лимит на RETR),
стоп за E0, цели: L1 (конец w1) и L1 ± 0.618·w1. Картинки с микроразметкой."""
import sys, numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pathlib import Path
sys.path.insert(0, ".")
from wave5_sm import load, TF_MIN
from channel_depth import SP

PKL = sys.argv[1]; SW_H = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0; RETR = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
TAG = sys.argv[4] if len(sys.argv) > 4 else "micro"
HOLD_H = 120; COST = 0.10; BUF = 0.002
BG, FG, GRID, UP, DN, WARN, ACC = "#0d1117", "#e6edf3", "#30363d", "#3fb950", "#f85149", "#79c0ff", "#ffd33d"
out = Path(SP) / f"charts_{TAG}"; out.mkdir(exist_ok=True)


def mark_waves(h, l, i0, sgn, sw, end):
    """sgn=-1: новый импульс ВНИЗ от вершины i0 (шорт). Возвращает список точек [(i, price, label)] и события."""
    pts = [(i0, float(h[i0]) if sgn < 0 else float(l[i0]), "0")]
    # бегущий экстремум по направлению; вершина отката — против
    ext_p = pts[0][1]; ext_i = i0; state = "imp"; k = i0 + 1; wave = 1
    ret_p = None; ret_i = None; last_imp_end = None
    while k <= end and wave <= 5:
        if state == "imp":
            better = (l[k] < ext_p) if sgn < 0 else (h[k] > ext_p)
            if better:
                ext_p, ext_i = (float(l[k]), k) if sgn < 0 else (float(h[k]), k)
            elif k - ext_i >= sw:                            # экстремум импульсной волны подтверждён
                pts.append((ext_i, ext_p, str(wave))); last_imp_end = (ext_i, ext_p)
                state = "ret"; ret_p, ret_i = (float(h[k]), k) if sgn < 0 else (float(l[k]), k); wave += 1
        else:
            worse = (h[k] > ret_p) if sgn < 0 else (l[k] < ret_p)
            if worse:
                ret_p, ret_i = (float(h[k]), k) if sgn < 0 else (float(l[k]), k)
            # откат сломал структуру (за начало текущего импульсного отрезка) → стоп разметки
            prev_start = pts[-2][1]
            if (ret_p > prev_start) if sgn < 0 else (ret_p < prev_start):
                pts.append((ret_i, ret_p, "X")); break
            if k - ret_i >= sw:                              # конец коррекции подтверждён
                pts.append((ret_i, ret_p, str(wave))); state = "imp"; ext_p, ext_i = (float(l[k]), k) if sgn < 0 else (float(h[k]), k); wave += 1
        k += 1
    return pts


d = pd.read_pickle(SP + PKL)
rows = []
for _, r in d.iterrows():
    ltf = "5m" if pd.Timestamp(r.ts) >= pd.Timestamp("2025-01-15", tz="UTC") else "15m"
    dl = load(r.sym, ltf)
    if dl.empty: continue
    t = dl.index.values.astype("datetime64[ns]"); h, l, c = dl.high.values.astype(float), dl.low.values.astype(float), dl.close.values.astype(float)
    bpm = 60 // TF_MIN[ltf]; sw = int(SW_H * bpm)
    sgn = -1 if r.dir == "up" else 1                       # шорт после пятёрки вверх → новый импульс вниз
    dh = load(r.sym, "4h"); t5 = np.datetime64(dh.index[int(r.b)].to_datetime64())
    ie = int(np.searchsorted(t, np.datetime64(pd.Timestamp(r.ts).to_datetime64())))
    i5 = int(np.searchsorted(t, t5)); seg = slice(i5, ie + 1)
    if ie >= len(dl) - HOLD_H * bpm or ie <= i5:            # LTF-данные кончились до входа / окна удержания
        continue
    i0 = i5 + int(h[seg].argmax()) if sgn < 0 else i5 + int(l[seg].argmin())   # экстремум пятёрки к моменту входа ядра
    E0 = float(h[i0]) if sgn < 0 else float(l[i0])
    end = min(len(dl) - 1, ie + HOLD_H * bpm * 2)
    pts = mark_waves(h, l, i0, sgn, sw, end)
    labels = [p[2] for p in pts]
    got = {"w1": "1" in labels, "w2": "2" in labels, "w3": "3" in labels, "w4": "4" in labels, "w5": "5" in labels, "broken": "X" in labels}
    row = {"sym": r.sym, "ts": r.ts, "ltf": ltf, "core_pnl": r.pnl_w4, **got}
    P = {p[2]: p for p in pts}
    # 🔑 ROSE-урок: сколько микроволн ПОДТВЕРЖДЕНО к моменту входа ядра (точка k подтверждается на баре k+sw)
    row["waves_at_entry"] = sum(1 for p in pts if p[2] not in ("0", "X") and p[0] + sw < ie)   # бар подтверждения закрыт ДО бара входа
    row["x_at_entry"] = any(p[2] == "X" and p[0] + sw < ie for p in pts)
    row["hours_from_top"] = (ie - i0) / bpm
    if got["w1"] and got["w2"]:
        w1_ = abs(P["1"][1] - E0); row["w2_retr"] = abs(P["2"][1] - P["1"][1]) / w1_ if w1_ else np.nan
        row["t1_h"] = (P["1"][0] - i0) / bpm; row["t2_h"] = (P["2"][0] - P["1"][0]) / bpm
        if got["w3"]:
            row["w3_ext"] = abs(P["3"][1] - P["2"][1]) / w1_ if w1_ else np.nan
            row["w3_beyond_w1"] = (P["3"][1] < P["1"][1]) if sgn < 0 else (P["3"][1] > P["1"][1])
    # 🔴 РЕВЬЮ 13.09 (D1): второй вход моделируется у ВСЕХ сделок с подтверждённой w1 — не только у тех,
    # где откат «подтвердился как w2, не пробив E0» (это отбор по будущему: выброшенные = стопы).
    # (D2): второй вход строго ПОСЛЕ входа ядра (conf1 > ie), иначе E0 из окна до ie — известен из будущего.
    # (D3): на баре входа сначала лимит, затем консервативно стоп, затем цель; walk с бара входа.
    # (D4): контроль — 50 розыгрышей на сделку, среднее.
    if got["w1"]:
        w1 = abs(P["1"][1] - E0)
        conf1 = max(P["1"][0] + sw, ie)
        lvl = P["1"][1] + RETR * w1 if sgn < 0 else P["1"][1] - RETR * w1
        ei = None
        for k in range(conf1 + 1, end + 1):
            if (h[k] >= lvl) if sgn < 0 else (l[k] <= lvl): ei = k; break       # лимит исполнен первым
            if (h[k] >= E0) if sgn < 0 else (l[k] <= E0): break                 # (недостижимо без касания lvl, оставлено для ясности)
            if (l[k] < P["1"][1]) if sgn < 0 else (h[k] > P["1"][1]): break     # цена ушла за w1 → это уже w3, откат будет w4
        if ei is not None:
            e = lvl; sl = E0 * (1 + BUF) if sgn < 0 else E0 * (1 - BUF); sl_pct = abs(e - sl) / e * 100
            tg1 = P["1"][1]; tg2 = P["1"][1] + sgn * 0.618 * w1
            def walk(tp):
                for k in range(ei, min(len(dl) - 1, ei + HOLD_H * bpm) + 1):    # с бара входа, стоп раньше цели
                    if (h[k] >= sl) if sgn < 0 else (l[k] <= sl): return (sl - e) / e * 100 * sgn - COST, "stop"
                    if (l[k] <= tp) if sgn < 0 else (h[k] >= tp): return (tp - e) / e * 100 * sgn - COST, "tp"
                kk = min(len(dl) - 1, ei + HOLD_H * bpm); return (c[kk] - e) / e * 100 * sgn - COST, "time"
            row["e2_pnl1"], row["e2_how1"] = walk(tg1); row["e2_pnl2"], row["e2_how2"] = walk(tg2); row["e2_sl_pct"] = sl_pct
            row["e2_lag_h"] = (ei - i0) / bpm; row["e2_after_core"] = ei > ie
            rr1 = abs(tg1 - e) / abs(sl - e)
            lo_, hi_ = max(sw + 1, ei - 30 * 24 * bpm), min(len(dl) - HOLD_H * bpm - 2, ei + 30 * 24 * bpm)
            if hi_ > lo_ + 10:
                rs_ = np.random.RandomState(ei % 100000); cps = []
                for _ in range(50):
                    jj = rs_.randint(lo_, hi_); ce = float(c[jj])
                    csl = ce * (1 + sl_pct / 100) if sgn < 0 else ce * (1 - sl_pct / 100)
                    ctp = ce * (1 - rr1 * sl_pct / 100) if sgn < 0 else ce * (1 + rr1 * sl_pct / 100)
                    cp = None
                    for k in range(jj + 1, min(len(dl) - 1, jj + HOLD_H * bpm) + 1):
                        if (h[k] >= csl) if sgn < 0 else (l[k] <= csl): cp = (csl - ce) / ce * 100 * sgn - COST; break
                        if (l[k] <= ctp) if sgn < 0 else (h[k] >= ctp): cp = (ctp - ce) / ce * 100 * sgn - COST; break
                    if cp is None:
                        kk = min(len(dl) - 1, jj + HOLD_H * bpm); cp = (c[kk] - ce) / ce * 100 * sgn - COST
                    cps.append(cp)
                row["e2_ctl1"] = float(np.mean(cps)); row["e2_ctl_wr"] = float(np.mean(np.array(cps) > 0))
    rows.append(row)
    # картинка
    lo, hi = max(0, i5 - 20), min(len(dl) - 1, (pts[-1][0] if pts else ie) + 40 * bpm)
    w = dl.iloc[lo:hi + 1]; x = np.arange(len(w)); o_, h_, l_, c_ = w.open.values, w.high.values, w.low.values, w.close.values
    fig, ax = plt.subplots(figsize=(12, 5.5), facecolor=BG); ax.set_facecolor(BG)
    for s_ in ax.spines.values(): s_.set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8); ax.grid(color=GRID, lw=0.4, alpha=0.5)
    for i in range(len(w)):
        col = UP if c_[i] >= o_[i] else DN
        ax.vlines(x[i], l_[i], h_[i], color=col, lw=0.5, alpha=0.8)
        ax.add_patch(Rectangle((x[i] - 0.3, min(o_[i], c_[i])), 0.6, max(abs(c_[i] - o_[i]), (h_[i] - l_[i]) * 1e-3), color=col, alpha=0.9, lw=0))
    xs = [p[0] - lo for p in pts]; ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=WARN, lw=1.8, alpha=0.95, label=f"новый импульс на {ltf}: волны от вершины пятёрки")
    for xx, yy, lb in zip(xs, ys, [p[2] for p in pts]):
        ax.annotate(lb, (xx, yy), color=DN if lb == "X" else WARN, fontsize=10, fontweight="bold", xytext=(-3, 8 if sgn > 0 else -14), textcoords="offset points")
    ax.axvline(ie - lo, color=FG, lw=1.0, alpha=0.7); ax.annotate("вход ядра (линия 2-4)", (ie - lo, ax.get_ylim()[1]), color=FG, fontsize=8, rotation=90, va="top", xytext=(4, -6), textcoords="offset points")
    ax.axhline(E0 * (1 + BUF) if sgn < 0 else E0 * (1 - BUF), color=DN, lw=0.9, ls=":", label="стоп за экстремум пятёрки")
    ax.axhline(r.p4, color=ACC, lw=1.1, ls="-.", label="цель ядра = конец волны 4 (4h)")
    if "e2_pnl1" in row:
        ax.axhline(lvl, color=ACC, lw=0.9, ls="--", label=f"вход 2: откат {RETR} волны 1 → {row['e2_pnl1']:+.2f}% ({row['e2_how1']})")
        ax.axvline(ei - lo, color=ACC, lw=0.8, alpha=0.6)
    tit = f"{r.sym} · {ltf} · микроструктура после {'шорта' if sgn < 0 else 'лонга'} ядра {pd.Timestamp(r.ts):%Y-%m-%d} (ядро {r.pnl_w4:+.1f}%) · волны: {' '.join(labels)}"
    if "w2_retr" in row: tit += f" · w2 откат {row['w2_retr']:.2f}" + (f" · w3/w1 {row['w3_ext']:.2f}" if "w3_ext" in row and np.isfinite(row.get("w3_ext", np.nan)) else "")
    ax.set_title(tit, color=FG, fontsize=9)
    lg = ax.legend(loc="best", fontsize=7, facecolor=BG, edgecolor=GRID)
    for tx in lg.get_texts(): tx.set_color(FG)
    fig.tight_layout(); fig.savefig(out / f"{r.sym.replace('/', '')}_{pd.Timestamp(r.ts):%Y%m%d}_{r.pnl_w4:+.1f}.png", dpi=110, facecolor=BG); plt.close(fig)

f = pd.DataFrame(rows); f.to_pickle(SP + f"{TAG}_micro.pkl")
n = len(f)
print(f"сделок {n} · LTF: {f.ltf.value_counts().to_dict()} · подтверждение свинга {SW_H} ч · откат {RETR}")
print(f"микроструктура: w1 {f.w1.mean()*100:.0f}% · w1+w2 {f.w2.mean()*100:.0f}% · w3 {f.w3.mean()*100:.0f}% · w4 {f.w4.mean()*100:.0f}% · w5 {f.w5.mean()*100:.0f}% · слом структуры (X) {f.broken.mean()*100:.0f}%")
g = f[f.w2]
if len(g):
    print(f"правила: w2 откат медиана {g.w2_retr.median():.2f} (≤1.0 у {(g.w2_retr<=1).mean()*100:.0f}%) · w3 за пределы w1 у {g.w3_beyond_w1.mean()*100:.0f}% (из {g.w3.sum()} с w3) · w3/w1 медиана {g.w3_ext.median():.2f} · t1 {g.t1_h.median():.0f} ч · t2 {g.t2_h.median():.0f} ч")
    print(f"  связь: ядро+ → w3 за w1 у {g[g.core_pnl>0].w3_beyond_w1.mean()*100:.0f}% · ядро− → {g[g.core_pnl<=0].w3_beyond_w1.mean()*100:.0f}%")
print("ТАЙМИНГ ВХОДА ЯДРА по микроволнам, подтверждённым к входу:")
for k, g in f.groupby("waves_at_entry"):
    ep = g.groupby(pd.to_datetime(g.ts).dt.strftime("%Y-%m-%d")).core_pnl.mean()
    print(f"  микроволн {k}: n={len(g):3d} ядро {g.core_pnl.mean():+.2f}% медиана {g.core_pnl.median():+.2f} WR {(g.core_pnl>0).mean()*100:.0f}% дней {len(ep)} дней+ {(ep>0).mean()*100:.0f}% · часов от вершины {g.hours_from_top.median():.0f}"
          + (f"  [{', '.join(f'{s.split(chr(47))[0]} {p:+.0f}' for s, p in zip(g.sym, g.core_pnl))}]" if len(g) <= 8 else ""))
for lbl, m in (("микроимпульс НЕ завершён (<5 волн, без X)", (f.waves_at_entry < 5) & (~f.x_at_entry)), ("завершён (≥5) или сломан (X)", (f.waves_at_entry >= 5) | f.x_at_entry),
               ("0-1 волна (свежая вершина)", f.waves_at_entry <= 1), ("2-4 волны", (f.waves_at_entry >= 2) & (f.waves_at_entry <= 4) & (~f.x_at_entry))):
    g = f[m]
    if len(g) >= 8:
        ep = g.groupby(pd.to_datetime(g.ts).dt.strftime("%Y-%m-%d")).core_pnl.mean()
        print(f"  {lbl:<44} n={len(g):3d} ядро {g.core_pnl.mean():+.2f}% медиана {g.core_pnl.median():+.2f} WR {(g.core_pnl>0).mean()*100:.0f}% дней+ {(ep>0).mean()*100:.0f}% мед.дня {ep.median():+.2f}")
e2 = f[f.e2_pnl1.notna()] if "e2_pnl1" in f else f.iloc[0:0]
if len(e2):
    R1 = e2.e2_pnl1 / e2.e2_sl_pct
    print(f"ВТОРОЙ ВХОД (откат w2): n={len(e2)} на сд {e2.e2_pnl1.mean():+.2f}% медиана {e2.e2_pnl1.median():+.2f} R {R1.mean():+.2f} WR {(e2.e2_pnl1>0).mean()*100:.0f}% цель(L1) {(e2.e2_how1=='tp').mean()*100:.0f}% стоп {(e2.e2_how1=='stop').mean()*100:.0f}% "
          f"стоп% {e2.e2_sl_pct.median():.2f} лаг {e2.e2_lag_h.median():.0f} ч | до 1.618: {e2.e2_pnl2.mean():+.2f}% цель {(e2.e2_how2=='tp').mean()*100:.0f}%")
    print(f"  КОНТРОЛЬ (50 розыгрышей/сделку): {e2.e2_ctl1.mean():+.2f}% WR {e2.e2_ctl_wr.mean()*100:.0f}% · перевес {(e2.e2_pnl1-e2.e2_ctl1).mean():+.2f} · "
          f"доля сделок ядра со вторым входом {len(e2)/n*100:.0f}% · по годам: " + " ".join(f"{y}:{len(x)}/{x.e2_pnl1.mean():+.1f}" for y, x in e2.groupby(pd.to_datetime(e2.ts).dt.year)))
    print("  по сделкам:", [(s.split('/')[0], round(p, 1)) for s, p in zip(e2.sym, e2.e2_pnl1)])
