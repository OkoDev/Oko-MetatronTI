"""Отчёт по волновому контексту сделок OTE-источников. Группа мерится ПРОТИВ ПОЛНОЙ БАЗЫ своего источника и режима
исполнения (закон «фильтр против полной базы»), тест отбора — перцентиль среднего группы среди 2000 случайных подвыборок
того же размера из той же базы. Обязательные срезы: сторона, месяц, размер стопа, кластер, ликвидность, хрупкость, охват."""
import pickle, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).parent
d = pickle.load(open(HERE / "wave_ctx_feat.pkl", "rb"))
bars = pickle.load(open(HERE / "wave_ctx_4h.pkl", "rb"))
d = d[d.zone_1d.notna() & d.profit_pct.notna()].copy()
d = d[d.data_era.fillna("") != "micro_sl_artifact"]
d["month"] = d.ts.dt.strftime("%Y-%m")
d["sl_pct"] = (d.entry_price - d.stop_loss).abs() / d.entry_price * 100
d["стоп"] = pd.cut(d.sl_pct, [0, .5, 1, 2, 100], labels=["<0.5", "0.5-1", "1-2", ">2"])
d["day"] = d.ts.dt.floor("D")
d["dn"] = d.groupby(["src", "execution_mode", "day"]).id.transform("size")


def turnover(r):
    b = bars.get(r.base)
    if b is None or len(b) == 0:
        return np.nan
    w = b[b.index + pd.Timedelta(hours=4) <= r.ts].tail(42)
    return float((w.close * w.volume).median()) if len(w) else np.nan


d["turn"] = d.apply(turnover, axis=1)
d["ov"] = pd.cut(d.overlap, [-.01, 0, .5, 1.01], labels=["0", "0-0.5", ">0.5"]).astype(str).replace("nan", "нет зоны")
rs = np.random.RandomState(11)


def stats(g, base):
    if len(g) < 15:
        return {"n": len(g)}
    x = g.profit_pct.values; bx = base.profit_pct.values
    sims = np.array([bx[rs.randint(0, len(bx), len(x))].mean() for _ in range(2000)])
    keep = np.sort(x)[::-1][int(len(x) * .1):]
    return {"n": len(g), "дней": g.day.nunique(), "на сд": x.mean(), "медиана": np.median(x), "WR": (x > 0).mean() * 100,
            "Δ к базе": x.mean() - bx.mean(), "перц": (sims < x.mean()).mean() * 100, "безтоп10": keep.mean(),
            "монет+%": (g.groupby("base").profit_pct.sum() > 0).mean() * 100}


def table(title, base, by):
    out = [{"срез": "ВСЯ БАЗА", **stats(base, base)}]
    for k, g in base.groupby(by, observed=True):
        out.append({"срез": " · ".join(map(str, k)) if isinstance(k, tuple) else str(k), **stats(g, base)})
    print(f"\n--- {title}")
    print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:7.3f}"))


for (src, em), base in d.groupby(["src", "execution_mode"]):
    if len(base) < 100:
        print(f"\n##### {src} {em}: n={len(base)} — мало, пропуск"); continue
    base = base.copy()
    base["ликв"] = np.where(base.turn >= base.turn.median(), "ликвидная", "неликвидная")
    base["комп"] = np.where(base.dn >= base.dn.median(), "кластерный день", "тихий день")
    print(f"\n{'#' * 110}\n##### {src} · {em} · n={len(base)} · монет {base.base.nunique()} · {base.ts.min():%Y-%m-%d} → {base.ts.max():%Y-%m-%d}")
    table("ЗОНА ВХОДА В ДНЕВНОЙ НОГЕ", base, "zone_1d")
    table("ЗАВЕРШЁННАЯ 4h-ПЯТЁРКА ЗА 5 СУТ", base, "fifth")
    if base.overlap.notna().any():
        table("СОВПАДЕНИЕ OTE ИСТОЧНИКА С OTE НОГИ АНАЛИТИКА", base, "ov")
    for col in ("direction", "month", "стоп", "комп", "ликв"):
        table(f"ЗОНА × {col}", base, [col, "zone_1d"])
        table(f"ПЯТЁРКА × {col}", base, [col, "fifth"])
