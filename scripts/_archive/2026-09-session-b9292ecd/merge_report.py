import pickle, numpy as np, pandas as pd
d = pickle.load(open("merge_lab.pkl", "rb")); s, c = d["setups"], d["ctl"]
print("монет в прогоне:", len(d["syms"]), "с сетапами:", s.sym.nunique())
s["uid"] = s.sym + "|" + s.key
base = s[~s["merge"]]; mg = s[s["merge"]]
print(s.groupby("merge").agg(n=("uid", "size"), вход=("pnl", lambda x: x.notna().sum()), поглощ=("absorbed", lambda x: (x > 0).sum())))
new_ids = set(mg.uid) - set(base.uid); lost = set(base.uid) - set(mg.uid)
com = base.merge(mg, on="uid", suffixes=("_b", "_m"))
print(f"новых {len(new_ids)} · пропало {len(lost)} · общих {len(com)} · детекция сдвинулась у {(com.detect_b != com.detect_m).sum()} · вход изменился у {(com.entry_time_b.astype(str) != com.entry_time_m.astype(str)).sum()}")
m = mg.merge(c[c["merge"]].drop(columns=["merge"]), on=["sym", "key"], how="left")
m = m.drop_duplicates(["uid"])
m["group"] = np.where(m.uid.isin(new_ids), "НОВЫЕ (поглощение)", "старые")
t = m[m.pnl.notna()].copy()
t["year"] = pd.to_datetime(t.entry_time).dt.year
t["day"] = pd.to_datetime(t.entry_time).dt.floor("D")
t["sl_pct"] = (t.entry - t.stop).abs() / t.entry * 100
t["dn"] = t.groupby("day").uid.transform("size")
rs = np.random.RandomState(7)

def row(g):
    if len(g) < 5:
        return {"n": len(g)}
    dif = g.pnl - g.ctl_rand; epd = g.assign(x=dif).groupby("day").x.mean()
    bs = [epd.sample(len(epd), replace=True, random_state=rs.randint(1e6)).mean() for _ in range(800)]
    keep = g.pnl.sort_values(ascending=False).iloc[int(len(g) * .1):]
    return {"n": len(g), "дней": g.day.nunique(), "цель%": (g.outcome == "target").mean() * 100, "стоп%": (g.outcome == "stop").mean() * 100,
            "на сд": g.pnl.mean(), "медиана": g.pnl.median(), "WR": (g.pnl > 0).mean() * 100, "трейл": g.pnl_trail.mean(),
            "ктр_случ": g.ctl_rand.mean(), "ктр_время": g.ctl_time.mean(), "Δслуч": dif.mean(), "Δвремя": (g.pnl - g.ctl_time).mean(),
            "ДИ Δслуч": f"[{np.percentile(bs, 2.5):+.2f},{np.percentile(bs, 97.5):+.2f}]", "безтоп10": keep.mean(),
            "монет+%": (g.groupby("sym").pnl.sum() > 0).mean() * 100, "стоп мед": g.sl_pct.median()}

def table(title, by):
    out = []
    for k, g in t.groupby(by):
        out.append({**({"срез": k} if not isinstance(k, tuple) else {"срез": " · ".join(map(str, k))}), **row(g)})
    print(f"\n=== {title}"); print(pd.DataFrame(out).to_string(index=False, float_format=lambda x: f"{x:6.2f}"))

table("ГРУППА", "group")
table("ГРУППА × СТОРОНА", ["group", "side"])
table("ГРУППА × ГОД", ["group", "year"])
t["ядро"] = np.where(t.core_full, "полное", np.where(t.core, "фрактал+канал", "без ядра"))
table("ГРУППА × ЯДРО", ["group", "ядро"])
t["стоп"] = pd.cut(t.sl_pct, [0, 3, 6, 10, 100], labels=["<3", "3-6", "6-10", ">10"])
table("ГРУППА × РАЗМЕР СТОПА", ["group", "стоп"])
t["комп"] = np.where(t.dn >= 3, "кластер ≥3/день", "одиночка")
table("ГРУППА × КОМПАНИЯ", ["group", "комп"])
nw = t[t.group != "старые"]
table("НОВЫЕ × СКОЛЬКО ПОГЛОЩЕНО", "absorbed") if len(nw) else None
print("\nновые лонги ядра полного:", len(nw[(nw.side == "LONG") & nw.core_full]))
pickle.dump(t, open("merge_trades.pkl", "wb"))
