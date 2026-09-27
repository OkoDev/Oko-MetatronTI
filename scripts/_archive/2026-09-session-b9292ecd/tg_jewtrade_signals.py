"""Извлечение сигналов канала (тикер, сторона, уровень, стоп) и проверка на наших данных (5m кэш).
python tg_jewtrade_signals.py extract · verify"""
import sys, re
import numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
OUT = Path("G:/oko_lab/out/tg_jewtrade")
pd.set_option("display.width", 220)

if sys.argv[1] == "extract":
    d = pd.read_pickle(OUT / "posts.pkl"); t = d[d.text.str.len() > 0].copy()
    t["ticker"] = t.text.str.extract(r"\$([A-Z0-9]{2,12})")[0]
    s = t[t.ticker.notna()].copy()
    lvl = s.text.str.extract(r"(?:уровн[яе]|закреп[а-я]*(?:\s+(?:уровня|выше|ниже|цены))?|от)\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*\$")[0]
    side = s.text.str.extract(r"\b(LONG|SHORT|лонг|шорт)\b", flags=re.I)[0].str.upper().replace({"ЛОНГ": "LONG", "ШОРТ": "SHORT"})
    stop = s.text.str.extract(r"[Сс]топ\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)")[0]
    has_res = s.text.str.contains(r"\+\s?\d+([.,]\d+)?\s?%", regex=True)
    S = s.assign(level=lvl.str.replace(",", ".").astype(float), side=side, stop=stop.str.replace(",", ".").astype(float))
    S = S[S.level.notna() & S.side.notna() & ~has_res].copy()
    print(f"сигналов с уровнем и стороной: {len(S)} · со стопом {int(S.stop.notna().sum())} · {S.dt.min():%Y-%m} → {S.dt.max():%Y-%m} · монет {S.ticker.nunique()} · {S.side.value_counts().to_dict()}")
    print(S.groupby(S.dt.dt.to_period("Q")).size().to_string())
    print(S[["dt", "ticker", "side", "level", "stop"]].tail(30).to_string())
    S.to_pickle(OUT / "signals.pkl")
elif sys.argv[1] == "verify":
    from tfcache import load_tf
    S = pd.read_pickle(OUT / "signals.pkl"); S["t_utc"] = S.dt - pd.Timedelta(hours=3)
    rows = []; cache = {}
    for r in S.itertuples():
        sym = f"{r.ticker}USDT".replace("USDTUSDT", "USDT")
        try:
            if sym not in cache:
                cache[sym] = load_tf(sym, "5m")
            m = cache[sym]
        except Exception:
            rows.append({"ticker": r.ticker, "dt": r.dt, "side": r.side, "status": "нет данных"}); continue
        if m.index[-1] < r.t_utc + pd.Timedelta(hours=6):
            rows.append({"ticker": r.ticker, "dt": r.dt, "side": r.side, "status": "кэш кончился"}); continue
        L = float(r.level); long_ = r.side == "LONG"
        i0 = int(m.index.searchsorted(r.t_utc)); px0 = float(m.close.values[max(0, i0 - 1)])
        # относительное положение уровня к цене на момент поста
        rel = (L / px0 - 1) * 100
        hi, lo, cl, op = m.high.values, m.low.values, m.close.values, m.open.values
        # закреп: 2 закрытия 5m за уровнем в течение 3 дней после поста (пробой в сторону)
        end = min(i0 + 3 * 288, len(m) - 3); ent = None
        for j in range(i0, end):
            if ((cl[j] > L and cl[j + 1] > L) if long_ else (cl[j] < L and cl[j + 1] < L)):
                ent = j + 2; break
        if ent is None:
            rows.append({"ticker": r.ticker, "dt": r.dt, "side": r.side, "status": "закрепа не было", "rel": rel}); continue
        e = float(op[ent]); sl = float(r.stop) if r.stop == r.stop else (L * (1 - 0.015) if long_ else L * (1 + 0.015))
        if (long_ and sl >= e) or (not long_ and sl <= e):
            sl = L * (1 - 0.015) if long_ else L * (1 + 0.015)
        risk = abs(e - sl) / e * 100
        res = {"ticker": r.ticker, "dt": r.dt, "side": r.side, "status": "вход", "rel": rel, "entry": e, "risk": risk,
               "wait_h": (ent - i0) / 12}
        for H in (24, 72):
            seg_h = hi[ent:ent + H * 12]; seg_l = lo[ent:ent + H * 12]
            mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
            mae = (1 - seg_l.min() / e) * 100 if long_ else (seg_h.max() / e - 1) * 100
            # стоп до пика?
            hit = None
            for k in range(ent, min(ent + H * 12, len(m))):
                if (lo[k] <= sl) if long_ else (hi[k] >= sl):
                    hit = k; break
            mfe_before_stop = mfe if hit is None else ((hi[ent:hit + 1].max() / e - 1) * 100 if long_ else (1 - lo[ent:hit + 1].min() / e) * 100)
            res.update({f"mfe{H}": mfe, f"mae{H}": mae, f"stop{H}": hit is not None, f"mfe_bs{H}": mfe_before_stop,
                        f"ret{H}": ((cl[min(ent + H * 12, len(m) - 1)] / e - 1) * 100) * (1 if long_ else -1)})
        rows.append(res)
    R = pd.DataFrame(rows); R.to_pickle(OUT / "verify.pkl")
    print("статусы:", R.status.value_counts().to_dict())
    v = R[R.status == "вход"]
    print(f"\nвошло (закреп в 3 дня): {len(v)} · медиана ожидания {v.wait_h.median():.1f} ч · риск до стопа медиана {v.risk.median():.2f}%")
    for side in ("LONG", "SHORT"):
        z = v[v.side == side]
        if not len(z):
            continue
        print(f"\n{side}: n={len(z)}")
        print(f"  24 ч: MFE мед {z.mfe24.median():.2f}% · MAE мед {z.mae24.median():.2f}% · стоп задет {z.stop24.mean()*100:.0f}% · MFE до стопа мед {z.mfe_bs24.median():.2f}% · доля MFE≥5% до стопа {(z.mfe_bs24>=5).mean()*100:.0f}% · ≥10% {(z.mfe_bs24>=10).mean()*100:.0f}% · итог через 24ч ср {z.ret24.mean():+.2f}%")
        print(f"  72 ч: MFE мед {z.mfe72.median():.2f}% · MAE мед {z.mae72.median():.2f}% · стоп задет {z.stop72.mean()*100:.0f}% · MFE до стопа мед {z.mfe_bs72.median():.2f}% · доля ≥5% {(z.mfe_bs72>=5).mean()*100:.0f}% · ≥10% {(z.mfe_bs72>=10).mean()*100:.0f}% · итог через 72ч ср {z.ret72.mean():+.2f}%")
    # простая стратегия «как он»: вход по закрепу, стоп его, выход: +5% полный или стоп или 72 ч
    def sim(z, tp):
        out = []
        for r in z.itertuples():
            if r.stop72 and r.mfe_bs72 < tp:
                out.append(-r.risk - 0.1)
            elif r.mfe_bs72 >= tp:
                out.append(tp - 0.1)
            else:
                out.append(r.ret72 - 0.1)
        return np.array(out)
    for tp in (5, 10):
        p = sim(v, tp); print(f"\n«стоп автора / тейк +{tp}% / 72 ч»: n {len(p)} · WR {(p>0).mean()*100:.0f}% · ср {p.mean():+.2f}% · сумма {p.sum():+.0f}%")
    print("\nпо годам (вход, ret72 ср, доля MFE≥10% до стопа):")
    print(v.groupby(v.dt.dt.year).agg(n=("ret72", "size"), ret72=("ret72", "mean"), mfe10=("mfe_bs72", lambda x: (x >= 10).mean() * 100), stop72=("stop72", "mean")).round(2).to_string())
