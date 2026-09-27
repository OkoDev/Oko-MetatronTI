"""УРОВНИ ПО ЧИСЛУ КАСАНИЙ (EQH/EQL) — «торговля от уровня до уровня» (Егор 18.09: «+» на замер EQH/EQL по касаниям).
В замере пробоя хая пампа единственной живой осью было число касаний уровня ≥3 (обе стороны в плюс). Здесь уровень
строится ТОЛЬКО по касаниям, без условия пампа: свинг-экстремумы 1h (фрактал 5, каузально — подтверждение через 5 баров)
за 30 дней, склеенные в кластеры ±0.5%; касания = число свингов в кластере. Уровень = средняя цена кластера.
Два сетапа на каждом уровне, обе стороны:
  ПРОБОЙ: закрытие 1h за уровнем + закреп (второе закрытие) → вход по open следующего бара в сторону пробоя;
  ОТБОЙ:  касание уровня (в пределах 0.5%) и закрытие 1h обратно → вход по open следующего бара от уровня.
Стоп: за уровнем на ATR(24, 1h)×1 и ×2. Цель: следующий уровень по ходу (касания ≥2, дальше ≥1 ATR) — «от уровня
до уровня» — и 4R; удержание 7 дней; кост 0.10. Одна сделка на уровень и сетап. Контроли: та же монета ±30 дн (×8)
и 5 чужих монет в тот же момент, та же геометрия. Запуск: python eq_levels_lab.py run [монет] [процессов] · report
"""
import sys, glob, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk, geo

import os
RETEST = os.environ.get("RETEST") == "1"   # 18.09, скрин MSTR «перезашёл от уровня»: вход на РЕТЕСТЕ пробитого уровня
HIST = os.environ.get("HIST") == "1"       # 19.09 (Егор: «наши EQH/EQL — уровень в моменте, у автора исторический»):
                                           # окно 180 дней, хаи и низы в ОДНОМ кластере (уровень = область), флаг зеркальности,
                                           # сетапы школы уровней: пробой с закрепом · отбой · ретест · ЛОЖНЫЙ ПРОБОЙ
OUT = Path("G:/oko_lab/out/eq_levels" + ("_hist" if HIST else "_rt" if RETEST else "")); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01")
COST = 0.10
FR = 5                      # фрактал: экстремум среди ±5 баров, известен через 5 баров
WIN = 24 * (180 if HIST else 30)   # окно уровней
TOL = 0.005                 # кластер ±0.5%
HOLD = 24 * 7               # 7 дней


def clusters(pts):
    """pts: список (цена, индекс) свингов одного типа → кластеры [(уровень, касания, последний_индекс)]."""
    pts = sorted(pts)
    out = []; cur = [pts[0]] if pts else []
    for p in pts[1:]:
        if p[0] <= cur[0][0] * (1 + 2 * TOL):
            cur.append(p)
        else:
            out.append(cur); cur = [p]
    if cur:
        out.append(cur)
    return [(float(np.mean([p for p, _ in c])), len(c), max(i for _, i in c)) for c in out]


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
        h = load_tf(sym, "1h")
    except Exception as e:
        return sym, f"данные: {e}"
    if len(h) < WIN + 200:
        return sym, "мало истории"
    hi, lo, cl, op = h.high.values, h.low.values, h.close.values, h.open.values; idx = h.index
    n = len(h)
    tr = np.maximum(h.high - h.low, np.maximum((h.high - h.close.shift()).abs(), (h.low - h.close.shift()).abs()))
    atr = tr.rolling(24).mean().values
    dol = float((h.close * h.volume).resample("1D").sum().replace(0, np.nan).median())
    # фрактальные свинги: бар i — swing high, если hi[i] = max(hi[i-FR:i+FR+1]); известен на баре i+FR
    sh = [i for i in range(FR, n - FR) if hi[i] == hi[i - FR:i + FR + 1].max()]
    sl_ = [i for i in range(FR, n - FR) if lo[i] == lo[i - FR:i + FR + 1].min()]
    sh_conf = np.array([i + FR for i in sh]); sl_conf = np.array([i + FR for i in sl_])
    rows = []; done = set(); busy = {}
    t0i = int(np.searchsorted(idx.values, np.datetime64(T0)))
    levels = []
    for t in range(max(WIN, t0i), n - 3):
        a_ = atr[t]
        if not np.isfinite(a_) or a_ <= 0:
            continue
        if t % 4 == 0:                                  # уровни пересчитываем раз в 4 часа — свинги меняются редко
            # свинги, известные к бару t, из окна
            kh = np.searchsorted(sh_conf, t, "right"); kl = np.searchsorted(sl_conf, t, "right")
            ph = [(hi[i], i) for i in sh[:kh] if i >= t - WIN]; pl = [(lo[i], i) for i in sl_[:kl] if i >= t - WIN]
            if HIST:
                # уровень = область: хаи и низы вместе; сторона уровня относительно цены — по положению; зеркальный —
                # если в кластере есть и хаи, и низы (уровень менял роль)
                pts = sorted([(p_, i, True) for p_, i in ph] + [(p_, i, False) for p_, i in pl])
                grp = []; cur = [pts[0]] if pts else []
                for q_ in pts[1:]:
                    if q_[0] <= cur[0][0] * (1 + 2 * TOL):
                        cur.append(q_)
                    else:
                        grp.append(cur); cur = [q_]
                if cur:
                    grp.append(cur)
                levels = []
                for c_ in grp:
                    L = float(np.mean([p_ for p_, _, _ in c_])); nt = sum(1 for _, _, top in c_ if top); nb = len(c_) - nt
                    levels.append((L, len(c_), max(i for _, i, _ in c_), "R" if L > cl[t] else "S", nt > 0 and nb > 0, t - min(i for _, i, _ in c_)))
            else:
                levels = [(L, k, li, "R", False, 0) for L, k, li in clusters(ph)] + [(L, k, li, "S", False, 0) for L, k, li in clusters(pl)]
        elif not (RETEST or HIST):
            continue
        if not levels:
            continue
        c = cl[t]
        for L, k, li, kind, mirror, age_h in levels:
            if k < 2:
                continue
            key = (round(L, 10), kind)
            if HIST:
                w = cl[t - 48:t]
                touched = (hi[t] >= L * (1 - TOL)) if kind == "R" else (lo[t] <= L * (1 + TOL))
                broke = (cl[t - 1] <= L and c > L) if kind == "R" else (cl[t - 1] >= L and c < L)
                bounce = touched and ((c < L * (1 - TOL)) if kind == "R" else (c > L * (1 + TOL))) and not broke
                # ложный пробой: прошлый бар ЗАКРЫЛСЯ за уровнем, текущий вернулся и закрылся по эту сторону
                false_b = ((cl[t - 1] > L and c < L * (1 - TOL)) if kind == "R" else (cl[t - 1] < L and c > L * (1 + TOL)))
                if kind == "R":
                    ab = np.where(w > L)[0]
                    rt = (len(ab) > 0 and (w[:ab[0]] < L).any() and not (w[ab[0]:] < L * (1 - TOL)).any()
                          and lo[t] <= L * (1 + TOL) and c > L * (1 + TOL) and lo[t - 1] > L * (1 + TOL))
                else:
                    ab = np.where(w < L)[0]
                    rt = (len(ab) > 0 and (w[:ab[0]] > L).any() and not (w[ab[0]:] > L * (1 + TOL)).any()
                          and hi[t] >= L * (1 - TOL) and c < L * (1 - TOL) and hi[t - 1] < L * (1 - TOL))
                conds = (("пробой", broke), ("отбой", bounce), ("ретест", rt), ("ложный пробой", false_b))
            elif RETEST:
                # ретест: за 48 баров уровень был пробит (закрытие за ним, до того — закрытия по другую сторону),
                # после пробоя не возвращался за уровень, а сейчас касание уровня и закрытие в сторону пробоя
                w = cl[t - 48:t]
                if kind == "R":
                    ab = np.where(w > L)[0]
                    ok = len(ab) > 0 and (w[:ab[0]] < L).any() and not (w[ab[0]:] < L * (1 - TOL)).any()                          and lo[t] <= L * (1 + TOL) and c > L * (1 + TOL) and lo[t - 1] > L * (1 + TOL)
                else:
                    ab = np.where(w < L)[0]
                    ok = len(ab) > 0 and (w[:ab[0]] > L).any() and not (w[ab[0]:] > L * (1 + TOL)).any()                          and hi[t] >= L * (1 - TOL) and c < L * (1 - TOL) and hi[t - 1] < L * (1 - TOL)
                conds = (("ретест", ok),)
            else:
                # событие на баре t (закрытом): пробой или отбой
                touched = (hi[t] >= L * (1 - TOL)) if kind == "R" else (lo[t] <= L * (1 + TOL))
                broke = (cl[t - 1] <= L and c > L) if kind == "R" else (cl[t - 1] >= L and c < L)
                bounce = touched and ((c < L * (1 - TOL)) if kind == "R" else (c > L * (1 + TOL))) and not broke
                conds = (("пробой", broke), ("отбой", bounce))
            for setup, cond in conds:
                if not cond or (key, setup) in done:
                    continue
                if setup == "пробой":
                    # закреп: следующий бар тоже закрывается за уровнем
                    if t + 1 >= n or not ((cl[t + 1] > L) if kind == "R" else (cl[t + 1] < L)):
                        continue
                    ent_i = t + 2; long_ = kind == "R"
                elif setup == "ретест":
                    ent_i = t + 1; long_ = kind == "R"          # от пробитого сопротивления — лонг, от пробитой поддержки — шорт
                elif setup == "ложный пробой":
                    ent_i = t + 1; long_ = kind == "S"          # ложный пробой поддержки → лонг, сопротивления → шорт
                else:
                    ent_i = t + 1; long_ = kind == "S"
                if ent_i >= n - 1 or busy.get(setup, -1) >= ent_i:
                    continue
                done.add((key, setup))
                e = float(op[ent_i])
                # следующий уровень по ходу: ближайший кластер с касаниями ≥2 дальше 1 ATR от входа
                ahead = [Lx for Lx, kx, _, kd, *_r in levels if kx >= 2 and ((Lx > e + a_) if long_ else (Lx < e - a_))]
                nxt = (min(ahead) if long_ else max(ahead)) if ahead else np.nan
                for stop_nm, m in (("ATR×1", 1.0), ("ATR×2", 2.0)):
                    sl = (L - m * a_) if long_ else (L + m * a_)
                    if (long_ and sl >= e) or (not long_ and sl <= e):
                        continue
                    r = abs(e - sl)
                    tgts = [("4R", e + 4 * r if long_ else e - 4 * r)]
                    if np.isfinite(nxt):
                        tgts.append(("след. уровень", nxt))
                    for tgt_nm, tp in tgts:
                        pnl, outc, k_out = walk(hi, lo, cl, ent_i, ent_i + HOLD, long_, e, sl, tp)
                        if stop_nm == "ATR×2" and tgt_nm == "4R":
                            busy[setup] = k_out
                        seg_h = hi[ent_i:ent_i + HOLD]; seg_l = lo[ent_i:ent_i + HOLD]
                        mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
                        rows.append({"sym": sym, "setup": setup, "side": "LONG" if long_ else "SHORT", "kind": kind, "level": L,
                                     "touches": k, "mirror": bool(mirror), "age_d": age_h / 24, "стоп_в": stop_nm, "цель": tgt_nm, "entry_t": idx[ent_i], "entry": e, "stop": sl,
                                     "target": tp, "risk_pct": r / e * 100, "tgt_pct": abs(tp - e) / e * 100, "atr_pct": a_ / e * 100,
                                     "dol": dol, "outcome": outc, "pnl": round(pnl, 2), "mfe": round(mfe, 2), "hold": HOLD,
                                     "level_age_h": t - li})
    if rows:
        rs = random.Random(sum(map(ord, sym)) + 5); oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "1h"))
            except Exception:
                pass
        for tr_ in rows:
            long_ = tr_["side"] == "LONG"; rsk, tg = tr_["risk_pct"] / 100, tr_["tgt_pct"] / 100; et = tr_["entry_t"]
            a = [geo(h, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, HOLD) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, HOLD) for o in oth]
            tr_["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            tr_["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} записей за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median"),
                 цель_пр=("tgt_pct", "median"), MFE=("mfe", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2),
                                                                             Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    d = pd.DataFrame([r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))])
    d["год"] = pd.to_datetime(d.entry_t).dt.year
    d["касания"] = pd.cut(d.touches, [1, 2, 3, 4, 99], labels=["2", "3", "4", "≥5"])
    pd.set_option("display.width", 250)
    print(f"записей {len(d)} · уровней {d.groupby(['sym', 'kind', 'level']).ngroups} · монет {d.sym.nunique()} · "
          f"{pd.to_datetime(d.entry_t).min():%Y-%m} → {pd.to_datetime(d.entry_t).max():%Y-%m}\n")
    print("=== сетап × сторона × стоп × цель"); print(agg(d.groupby(["setup", "side", "стоп_в", "цель"])).to_string())
    for setup in sorted(d.setup.unique()):
        s = d[(d.setup == setup) & (d["стоп_в"] == "ATR×2")]
        for tgt in ("4R", "след. уровень"):
            z = s[s["цель"] == tgt]
            print(f"\n=== {setup}, ATR×2, цель {tgt}: сторона × касания"); print(agg(z.groupby(["side", "касания"], observed=True)).to_string())
            if "mirror" in z.columns:
                zz = z.assign(зерк=np.where(z.mirror, "зеркальный", "односторонний"), возраст=pd.cut(z.age_d, [-1, 14, 45, 90, 400], labels=["<2 нед", "2–6 нед", "6–13 нед", ">13 нед"]))
                print(f"=== {setup}, ATR×2, цель {tgt}: сторона × зеркальность"); print(agg(zz.groupby(["side", "зерк"])).to_string())
                print(f"=== {setup}, ATR×2, цель {tgt}: сторона × возраст уровня"); print(agg(zz.groupby(["side", "возраст"], observed=True)).to_string())
            print(f"=== {setup}, ATR×2, цель {tgt}: сторона × год"); print(agg(z.groupby(["side", "год"])).to_string())
            for side in ("LONG", "SHORT"):
                q = z[z.side == side]
                if len(q):
                    top = q.pnl.nlargest(max(1, int(len(q) * 0.1))).sum()
                    print(f"  хрупкость {setup} {tgt} {side}: n {len(q)} · сумма {q.pnl.sum():.0f} · без верхних 10% {q.pnl.sum() - top:.0f} · "
                          f"исходы {q.outcome.value_counts().to_dict()} · монет+ {(q.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}%")
        z = s[s["цель"] == "4R"]
        z = z.assign(оборот=pd.cut(z.dol, [0, 1e6, 5e6, 2e7, 1e12], labels=["<1M", "1–5M", "5–20M", ">20M"]),
                     стоп=pd.cut(z.risk_pct, [0, 2, 4, 8, 100], labels=["<2%", "2–4%", "4–8%", ">8%"]))
        day = pd.to_datetime(z.entry_t).dt.floor("D"); z = z.assign(масс=day.map(day.value_counts()))
        z = z.assign(масс_к=pd.cut(z["масс"], [0, 2, 5, 10, 999], labels=["1–2", "3–5", "6–10", ">10"]))
        for ax_ in ("оборот", "стоп", "масс_к"):
            print(f"\n=== {setup}, ATR×2, 4R: сторона × {ax_}"); print(agg(z.groupby(["side", ax_], observed=True)).to_string())


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
