"""Отчёт сетапа №1 «пятая в процессе → вход в зоне по слому 3m». Вход choch против touch и против двух контролей той же геометрии
(случайное время той же монеты ±30 дн; тот же момент на 6 других монетах). Срезы протокола: сторона · год(режим) · зона дневной ноги ·
размер стопа · кластер · хрупкость · охват монет; ДИ перевеса бутстрапом по дням."""
import pickle, glob
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path("G:/oko_lab/out")      # результаты замеров переехали на G: (16.09)
rows = [r for f in glob.glob(str(HERE / "fifth_zone" / "*.pkl")) for r in pickle.load(open(f, "rb"))]
d = pd.DataFrame(rows); d = d[d.pnl.notna()].copy()
ctl_p = HERE / "fifth_zone_ctl.pkl"
if ctl_p.exists():
    c = pickle.load(open(ctl_p, "rb"))
    d = d.merge(c, on=["sym", "entry_t", "entry_kind"], how="left")
else:
    d["ctl_rand"] = np.nan; d["ctl_time"] = np.nan
d["year"] = pd.to_datetime(d.entry_t, utc=True).dt.year; d["day"] = pd.to_datetime(d.entry_t, utc=True).dt.floor("D")
d["dn"] = d.groupby(["entry_kind", "day"]).sym.transform("size")
d["комп"] = np.where(d.dn >= 3, "кластер ≥3/день", "одиночка")
d["стоп"] = pd.cut(d.risk_pct, [0, 1, 2, 4, 100], labels=["<1", "1-2", "2-4", ">4"])
d["RR"] = d.tgt_pct / d.risk_pct
rs = np.random.RandomState(3)
print(f"монет с файлом {len(glob.glob(str(HERE / 'fifth_zone' / '*.pkl')))} · входов {len(d)} ({d.groupby('entry_kind').size().to_dict()}) · монет {d.sym.nunique()} · "
      f"{d.entry_t.min():%Y-%m} → {d.entry_t.max():%Y-%m}")


def stats(g):
    if len(g) < 15:
        return {"n": len(g)}
    x = g.pnl.values; keep = np.sort(x)[::-1][int(len(x) * .1):]
    out = {"n": len(g), "дней": g.day.nunique(), "на сд": x.mean(), "медиана": np.median(x), "WR": (x > 0).mean() * 100,
           "цель%": (g.outcome == "target").mean() * 100, "стоп мед": g.risk_pct.median(), "RR мед": g.RR.median(),
           "безтоп10": keep.mean(), "монет+%": (g.groupby("sym").pnl.sum() > 0).mean() * 100}
    for col, nm in (("ctl_time", "время"), ("ctl_rand", "случ")):
        gg = g[g[col].notna()]
        if len(gg) >= 15:
            dif = gg.pnl - gg[col]; epd = gg.assign(x=dif).groupby("day").x.mean()
            bs = [epd.sample(len(epd), replace=True, random_state=rs.randint(1e6)).mean() for _ in range(600)]
            out[f"ктр {nm}"] = gg[col].mean(); out[f"Δ {nm}"] = dif.mean(); out[f"ДИ {nm}"] = f"[{np.percentile(bs, 2.5):+.2f},{np.percentile(bs, 97.5):+.2f}]"
    return out


def table(title, by):
    out = []
    for k, g in d.groupby(by, observed=True):
        out.append({"срез": " · ".join(map(str, k)) if isinstance(k, tuple) else str(k), **stats(g)})
    print(f"\n--- {title}"); print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))


table("ВХОД", "entry_kind")
for col in ("side", "year", "leg_zone", "стоп", "комп"):
    table(f"ВХОД × {col}", ["entry_kind", col])
table("ВХОД × СТОРОНА × ГОД", ["entry_kind", "side", "year"])
