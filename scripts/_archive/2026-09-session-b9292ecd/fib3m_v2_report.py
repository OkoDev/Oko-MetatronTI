"""Отчёт v2 (после ревью): три контроля, бутстрап Δ по дням, срезы по зоне (масштабы 10 и 5 раздельно), филлу, ядру, году."""
import glob, sys
import numpy as np, pandas as pd

SIDE = sys.argv[1] if len(sys.argv) > 1 else "down"
f = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob(f"v2_{SIDE}_*.pkl"))], ignore_index=True)
S = f[f.v == "__setup__"].copy(); T = f[f.v != "__setup__"].copy()
rng = np.random.default_rng(1)
zone = lambda x: pd.cut(x.fillna(9), [-9, .5, .62, .79, 1.0, 99], labels=["<0.5", "0.5-0.62", "OTE", "глуб 0.79-1", "за ногой"])
T["z10"], T["z5"] = zone(T.dep10), zone(T.dep5)
T["bk"] = T.risk.clip(1, 3).round().astype(int)
CA = {(b, x): S[f"ca{b}_{x}"].mean() for b in (1, 2, 3) for x in ("Y1", "Y0", "Z1")}
print(f"=== {'ЛОНГ (пятёрка вниз)' if SIDE == 'down' else 'ШОРТ (пятёрка вверх)'} · сетапов {len(S)} · монет {S.sym.nunique()} · годы {S.year.value_counts().sort_index().to_dict()}")
print("контроль ПО ВСЕМ сетапам (стоп 1/2/3%): " + " · ".join(f"{x} " + "/".join(f"{CA[(b, x)]:+.2f}" for b in (1, 2, 3)) for x in ("Y1", "Y0", "Z1")))


def boot_ci(g, col, ctl):
    dlt = (g[col] - g[ctl]).dropna(); days = g.loc[dlt.index, "day"]
    by = dlt.groupby(days).mean().values
    if len(by) < 8:
        return (np.nan, np.nan)
    bs = [rng.choice(by, len(by)).mean() for _ in range(1500)]
    return tuple(np.percentile(bs, [5, 95]))


def row(g, xn, extra):
    s = g[xn].dropna()
    if len(s) < 10:
        return None
    gg = g.loc[s.index]
    ca = np.mean([CA[(b, xn)] for b in gg.bk]) if xn in ("Y1", "Y0", "Z1") else np.nan
    lo, hi = boot_ci(gg, xn, "ctl " + xn)
    ep = gg.assign(p=s).groupby("day").p.mean()
    return {**extra, "вых": xn, "n": len(s), "стоп%": gg.risk.median(), "на сд%": s.mean(),
            "ктр исп": gg["ctl " + xn].mean(), "ктр все": ca, "ктр время": gg["ctlT " + xn].mean() if "ctlT " + xn in gg else np.nan,
            "Δ исп": s.mean() - gg["ctl " + xn].mean(), "CI90 по дням": f"[{lo:+.2f};{hi:+.2f}]",
            "WR%": (s > 0).mean() * 100, "без топ10": s.sort_values(ascending=False).iloc[int(len(s) * .1):].mean(),
            "дней+%": (ep > 0).mean() * 100, "монет+%": (gg.assign(p=s).groupby("sym").p.sum() > 0).mean() * 100,
            "годы": " ".join(f"{str(y)[2:]}:{v.mean():+.1f}/{len(v)}" for y, v in s.groupby(gg.year))}


pd.set_option("display.width", 320)
fmt = lambda v: f"{v:6.2f}"
out = [r for v, g in T.groupby("v") for xn in ("Y0", "Z1", "Y1", "X3") if (r := row(g, xn, {"вход": v}))]
print("\n--- все зоны")
print(pd.DataFrame(out).to_string(index=False, float_format=fmt))
MAIN = ["noCH · откат 0.5 · стоп 0.886", "CH · откат 0.5 · стоп 0.886", "noCH · откат 0.5 · стоп p5", "PEAK · вход на CHoCH 3m · стоп под пятую"]
for col, nm in (("z10", "зона пятой · дневной свинг 10"), ("z5", "зона пятой · дневной свинг 5"), ("fill", "тип филла"), ("fc", "отбор ядра (канал от провизорной пятой)"), ("d_bull", "1D бычья")):
    out = [r for v in MAIN for z, g in T[T.v == v].groupby(col, observed=True) for xn in ("Y0", "Z1") if (r := row(g, xn, {"вход": v[:24], nm: z}))]
    if out:
        print(f"\n--- {nm}")
        print(pd.DataFrame(out).to_string(index=False, float_format=fmt))
