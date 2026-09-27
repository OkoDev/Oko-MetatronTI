"""ПРОБОЙ ЗНАЧИМОГО УРОВНЯ С ЗАКРЕПОМ (Егор 18.09, скрины AKE: «при закрепе уровня 0.02964 буду пробовать LONG» → +17%
за час; «что скажешь про такие пробойные стратегии и поиск значимых уровней?»).

Уровень (лонг; шорт зеркально): хай 7 дней на 1h (H7), к которому цена ВЕРНУЛАСЬ после отката ≥ 15% — до него был
ход ≥ 30% от минимума 7 дней (хай пампа). Число касаний (баров 1h с high в ±0.5% от H7, разнесённых ≥ 4 ч) — срез.
Вход на 5m: пробой = закрытие выше уровня; закреп = ещё одно закрытие выше (как у автора: две свечи над уровнем);
вход по open следующей свечи. Варианты: «первое закрытие» (без закрепа) и «закреп 2 свечи».
Стоп: под уровень (буфер 0.5%) — как у автора. Цели: 2R, 4R и «без цели» (стоп или 24 ч). Кост 0.10%.
Контроли: случайный сдвиг ±30 дней той же монеты (×8) и 5 других монет в тот же момент, та же геометрия.
Одна сделка на уровень; следующая — только по новому уровню. Запуск: python level_break_lab.py run [монет] [процессов] · report
"""
import sys, glob, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk

import os
V2 = os.environ.get("V2") == "1"          # второй круг (Егор: «от уровня до уровня», «если выбирать монеты правильно, WR вырастет?»):
                                          # стоп под волатильность монеты (ATR 1h), цель = следующий уровень (хай 90 дней)
OUT = Path("G:/oko_lab/out/level_break" + ("_v2" if V2 else "")); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01")
COST, BUF = 0.10, 0.005
W_H = 24 * 7                         # окно уровня: 7 дней на 1h
MIN_PUMP, MIN_PULL = 0.30, 0.15      # ход к уровню ≥30%, откат от уровня ≥15%
HOLD = 24 * 12                       # 24 ч в барах 5m


def levels(h, long_):
    """Список (t_ready, level, pump, pull, touches, t_hi): момент, с которого уровень «ждёт» пробоя — когда после хая
    случился откат ≥15% (лонг) — и цена ещё ниже уровня."""
    hi, lo, cl = h.high.values, h.low.values, h.close.values; idx = h.index
    out = []; i = W_H; last_level = None
    while i < len(h) - 1:
        win_h, win_l = hi[i - W_H:i], lo[i - W_H:i]
        if long_:
            k = int(win_h.argmax()); L = float(win_h[k]); base_ = float(win_l[:k + 1].min()) if k >= 0 else np.nan
            pump = L / base_ - 1 if base_ > 0 else 0
            pull = 1 - float(win_l[k:].min()) / L
            below = cl[i - 1] < L
        else:
            k = int(win_l.argmin()); L = float(win_l[k]); base_ = float(win_h[:k + 1].max())
            pump = base_ / L - 1 if L > 0 else 0
            pull = float(win_h[k:].max()) / L - 1
            below = cl[i - 1] > L
        if pump >= MIN_PUMP and pull >= MIN_PULL and below and L != last_level:
            t_hi = idx[i - W_H + k]
            seg = h.iloc[i - W_H:i]
            near = seg[(seg.high >= L * 0.995) & (seg.high <= L * 1.005)] if long_ else seg[(seg.low <= L * 1.005) & (seg.low >= L * 0.995)]
            touches = 1; last = None
            for t in near.index:
                if last is None or (t - last) >= pd.Timedelta(hours=4):
                    touches += 0 if last is None else 1
                    last = t
            out.append((idx[i], L, pump, pull, touches, t_hi)); last_level = L
        i += 1
    return out


def run_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    t_start = time.time()
    try:
        h = load_tf(sym, "1h"); d = load_tf(sym, "5m")
    except Exception as e:
        return sym, f"данные: {e}"
    if len(h) < W_H + 100 or len(d) < 2000:
        return sym, "мало истории"
    h = h[h.index >= T0 - pd.Timedelta(days=10)]
    if len(h) < W_H + 100:
        return sym, "мало истории в окне"
    dol = float((d.close * d.volume).resample("1D").sum().replace(0, np.nan).median())     # медианный дневной оборот $
    di = d.index.values; hi, lo, cl, op = d.high.values, d.low.values, d.close.values, d.open.values
    # ATR(24) на 1h — каузально, по закрытым барам; и хай/лоу 90 дней как «следующий уровень»
    tr = np.maximum(h.high - h.low, np.maximum((h.high - h.close.shift()).abs(), (h.low - h.close.shift()).abs()))
    atr24 = tr.rolling(24).mean(); h_idx = h.index.values
    hi90 = h.high.rolling(24 * 90, min_periods=24 * 20).max().shift(1); lo90 = h.low.rolling(24 * 90, min_periods=24 * 20).min().shift(1)
    rows = []
    rs = random.Random(sum(map(ord, sym)) + 3)
    for long_ in (True, False):
        busy_until = -1
        for t_ready, L, pump, pull, touches, t_hi in levels(h, long_):
            j = int(np.searchsorted(di, np.datetime64(t_ready)))
            end = int(np.searchsorted(di, np.datetime64(t_ready + pd.Timedelta(days=7))))
            j1 = None
            for k in range(j, min(end, len(d) - 3)):
                if (cl[k] > L) if long_ else (cl[k] < L):
                    j1 = k; break
            if j1 is None:
                continue
            for mode, ent_i in ((("закреп 2 свечи", j1 + 2),) if V2 else (("первое закрытие", j1 + 1), ("закреп 2 свечи", j1 + 2))):
                if mode == "закреп 2 свечи" and not ((cl[j1 + 1] > L) if long_ else (cl[j1 + 1] < L)):
                    continue
                if ent_i <= busy_until or ent_i >= len(d):
                    continue
                e = float(op[ent_i])
                if V2:
                    hk = int(np.searchsorted(h_idx, di[ent_i], "right")) - 2          # последний ЗАКРЫТЫЙ 1h бар до входа
                    if hk < 24 or not np.isfinite(atr24.iloc[hk]):
                        continue
                    a_ = float(atr24.iloc[hk]); nxt = float(hi90.iloc[hk]) if long_ else float(lo90.iloc[hk])
                    stops = (("под уровень 3%", L * 0.03), ("ATR×1 под уровень", a_), ("ATR×2 под уровень", 2 * a_))
                else:
                    stops = (("под уровень 0.5%", L * BUF), ("под уровень 3%", L * 0.03))
                for stop_nm, dist in stops:                                              # закон размера стопа — корзины
                  sl = L - dist if long_ else L + dist
                  if (long_ and sl >= e) or (not long_ and sl <= e):
                    continue
                  r = abs(e - sl)
                  tgts = [("2R", e + 2 * r if long_ else e - 2 * r), ("4R", e + 4 * r if long_ else e - 4 * r),
                          ("без цели 24ч", e * 100 if long_ else e / 100)]
                  if V2:
                      tgts = tgts[1:]
                      if np.isfinite(nxt) and ((nxt >= L * 1.03) if long_ else (nxt <= L * 0.97)):
                          tgts.append(("след. уровень 90д", nxt))
                  for tgt_nm, tp in tgts:
                    pnl, outc, k_out = walk(hi, lo, cl, ent_i, ent_i + HOLD, long_, e, sl, tp)
                    if tgt_nm == "2R" and mode == "закреп 2 свечи":
                        busy_until = k_out
                    # MFE за 24 ч — сколько давал ход
                    seg_h = hi[ent_i:ent_i + HOLD]; seg_l = lo[ent_i:ent_i + HOLD]
                    mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
                    rows.append({"sym": sym, "side": "LONG" if long_ else "SHORT", "вход": mode, "цель": tgt_nm, "стоп_в": stop_nm, "level": L,
                                 "t_ready": t_ready, "t_hi": t_hi, "entry_t": pd.Timestamp(di[ent_i]), "entry": e, "stop": sl, "target": tp,
                                 "risk_pct": r / e * 100, "tgt_pct": abs(tp - e) / e * 100, "pump": pump * 100, "pull": pull * 100,
                                 "touches": touches, "dol": dol, "outcome": outc, "pnl": round(pnl, 2), "mfe": round(mfe, 2),
                                 "hold": HOLD, "wait_bars": j1 - j, "atr_pct": (float(atr24.iloc[hk]) / e * 100) if V2 else np.nan,
                                 "nxt_pct": ((abs(nxt - e) / e * 100) if (V2 and np.isfinite(nxt)) else np.nan)})
    if rows:
        oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "5m"))
            except Exception:
                pass
        from triangle_lab import geo
        for tr in rows:
            long_ = tr["side"] == "LONG"; rsk, tg = tr["risk_pct"] / 100, min(tr["tgt_pct"] / 100, 5.0); et = tr["entry_t"]
            a = [geo(d, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, HOLD) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, HOLD) for o in oth]
            tr["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            tr["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} записей за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median"),
                 MFE=("mfe", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    d = pd.DataFrame([r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))])
    d["год"] = pd.to_datetime(d.entry_t).dt.year
    print(f"записей {len(d)} · уровней {d.groupby(['sym','side','level']).ngroups} · монет {d.sym.nunique()} · "
          f"{pd.to_datetime(d.entry_t).min():%Y-%m} → {pd.to_datetime(d.entry_t).max():%Y-%m}\n")
    print("=== сторона × стоп × вход × цель"); print(agg(d.groupby(["side", "стоп_в", "вход", "цель"])).to_string())
    b = d[(d["вход"] == "закреп 2 свечи") & (d["стоп_в"] == "под уровень 3%")]
    for tgt in ("4R", "без цели 24ч"):
        s = b[b["цель"] == tgt]
        print(f"\n=== закреп, цель {tgt}: сторона × год"); print(agg(s.groupby(["side", "год"])).to_string())
        s = s.assign(памп=pd.cut(s.pump, [0, 50, 100, 1000], labels=["30–50%", "50–100%", ">100%"]),
                     откат=pd.cut(s.pull, [0, 30, 50, 100], labels=["15–30%", "30–50%", ">50%"]),
                     касания=pd.cut(s.touches, [0, 1, 2, 99], labels=["1", "2", "≥3"]),
                     оборот=pd.cut(s.dol, [0, 1e6, 5e6, 2e7, 1e12], labels=["<1M", "1–5M", "5–20M", ">20M"]),
                     стоп=pd.cut(s.risk_pct, [0, 1, 2, 4, 100], labels=["<1%", "1–2%", "2–4%", ">4%"]))
        for ax_ in ("памп", "откат", "касания", "оборот", "стоп"):
            print(f"\n=== закреп, цель {tgt}: сторона × {ax_}"); print(agg(s.groupby(["side", ax_], observed=True)).to_string())
        day = pd.to_datetime(s.entry_t).dt.floor("D"); s = s.assign(масс=day.map(day.value_counts()))
        s = s.assign(масс_к=pd.cut(s["масс"], [0, 1, 3, 6, 999], labels=["1", "2–3", "4–6", "≥7"]))
        print(f"\n=== закреп, цель {tgt}: сторона × массовость дня"); print(agg(s.groupby(["side", "масс_к"], observed=True)).to_string())
        for side in ("LONG", "SHORT"):
            z = s[s.side == side]
            if len(z):
                top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
                print(f"  хрупкость {tgt} {side}: n {len(z)} · сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · "
                      f"исходы {z.outcome.value_counts().to_dict()} · MFE≥10%: {(z.mfe >= 10).mean() * 100:.0f}% · MFE≥17%: {(z.mfe >= 17).mean() * 100:.0f}%")


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
