"""Контроли для шорта-продолжения (short_after_long_h480) — оба: случайный сдвиг ±30д той же монеты и другие монеты
в тот же момент, та же геометрия (tf_sweep.controls). Горизонт 480 баров 15m = 120 ч → T.HOLD_BARS=30 при tf=4h.
Плюс срез по зоне дневной ноги (daily_leg) — как в leg_zone_lab. Запуск: python short_zone_ctl.py run 8 · report
"""
import os, sys, glob, pickle
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
os.environ.setdefault("HOLD_SUF", "_h480")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import tf_sweep as T
import short_after_long as S

CTL = S.OUT / "ctl_short.pkl"
ZONES = S.OUT / "zones.pkl"
ENTRY = "по слому 15m вниз"
TARGETS = ("цель p5", "расш 1.0 ноги")


def _init():
    import tf_sweep as TT
    TT.HOLD_BARS = 30                                  # 30 баров 4h = 120 ч = 480 баров 15m


def rows():
    return [r for f in glob.glob(str(S.OUT / "*USDT.pkl")) for r in pickle.load(open(f, "rb"))]


def zones():
    if ZONES.exists():
        return pickle.load(open(ZONES, "rb"))
    from tfcache import load_tf
    from core.waves.wave_analyst import daily_leg
    base = pd.DataFrame([r for r in T.rows_of("4h") if r.get("entered") and r["side"] == "LONG"])
    cache, zmap = {}, {}
    for r in base.itertuples():
        try:
            if r.sym not in cache:
                cache[r.sym] = (load_tf(r.sym, "4h"), load_tf(r.sym, "1d"))
            dh, dd = cache[r.sym]
            t0 = pd.to_datetime(r.key.split("|")[0], format="%Y%m%d%H")
            t5 = pd.Timestamp(r.top_time); now = t5 + pd.Timedelta(hours=4)
            leg = daily_leg(dh, t0, want_top=False, p5=float(r.stop) / (1 - 0.0015), t5x=t5, now=now, dd=dd[dd.index < now])
            zmap[(r.sym, r.key)] = (leg["zone"], leg["depth"]) if leg else ("нет ноги", np.nan)
        except Exception:
            pass
    pickle.dump(zmap, open(ZONES, "wb"))
    return zmap


def run(nproc):
    d = pd.DataFrame(rows())
    d = d[(d["вход"] == ENTRY) & (d["цель"].isin(TARGETS))]
    syms = sorted(d.sym.unique())
    jobs, by_sym = [], {}
    for s in syms:
        trades = [{**r, "side": "SHORT"} for r in d[d.sym == s].to_dict("records")]
        by_sym[s] = trades
        jobs.append((s, "4h", trades, [o for o in syms if o != s]))
    out = []
    with Pool(nproc, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(T.controls, jobs), 1):
            if res:
                for r, tr in zip(res, by_sym[res[0]["sym"]]):   # порядок внутри монеты сохранён — приклеиваем цель
                    r["цель"] = tr["цель"]; r["entry_t"] = tr["entry_t"]
            out.extend(res)
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    c = pd.DataFrame(out)
    pickle.dump(c, open(CTL, "wb"))
    print("ГОТОВО", len(c), flush=True)


def report():
    d = pd.DataFrame(rows()); d = d[(d["вход"] == ENTRY) & (d["цель"].isin(TARGETS))].copy()
    zmap = zones()
    d["зона"] = [zmap.get((s, k), ("?", np.nan))[0] for s, k in zip(d.sym, d.key)]
    d["depth"] = [zmap.get((s, k), ("?", np.nan))[1] for s, k in zip(d.sym, d.key)]
    c = pickle.load(open(CTL, "rb"))
    d = d.merge(c[["sym", "key", "цель", "entry_t", "ctl_rand", "ctl_time"]], on=["sym", "key", "цель", "entry_t"], how="left")
    d["год"] = pd.to_datetime(d.top_time).dt.year
    order = ["мелкая (<0.5)", "мелкая 0.5–0.62", "OTE 0.62–0.79", "глубокая 0.79–1.0", "за пределами ноги (>1)", "нет ноги", "?"]
    d["зона"] = pd.Categorical(d["зона"], [z for z in order if z in set(d["зона"])])

    def agg(g):
        return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                     ср=("pnl", "mean"), мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"),
                     риск=("risk_pct", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2),
                                                        Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)
    print(f"шорт после лонга, вход «{ENTRY}», горизонт 120 ч, кост 0.10 · записей {len(d)} · сетапов {d.key.nunique()} · монет {d.sym.nunique()}")
    for tgt in TARGETS:
        s = d[d["цель"] == tgt]
        print(f"\n=== {tgt} — по зоне дневной ноги"); print(agg(s.groupby("зона", observed=True)).to_string())
        z = s[s["зона"] == "за пределами ноги (>1)"]
        print(f"\n  зона >1 по годам:"); print(agg(z.groupby("год")).to_string())
        print(f"  зона >1 по исходу лонга:"); print(agg(z.groupby("long_outcome")).to_string())
        # хрупкость и корзины стопа
        top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
        print(f"  хрупкость: сумма {z.pnl.sum():.1f} · без верхних 10% {z.pnl.sum() - top:.1f}")
        z = z.assign(корзина=pd.cut(z.risk_pct, [0, 3, 6, 10, 100], labels=["<3%", "3–6%", "6–10%", ">10%"]))
        print("  корзины стопа:"); print(agg(z.groupby("корзина", observed=True)).to_string())
        z = z.assign(глубина=pd.cut(z.depth, [1, 1.1, 1.25, 1.5, 9], labels=["1–1.1", "1.1–1.25", "1.25–1.5", ">1.5"]))
        print("  глубина за началом ноги:"); print(agg(z.groupby("глубина", observed=True)).to_string())
        # массовость дня
        day = pd.to_datetime(z.entry_t).dt.floor("D")
        z = z.assign(масс=day.map(day.value_counts()))
        z = z.assign(масс_к=pd.cut(z["масс"], [0, 1, 3, 6, 999], labels=["1", "2–3", "4–6", "≥7"]))
        print("  массовость дня:"); print(agg(z.groupby("масс_к", observed=True)).to_string())


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    else:
        report()
