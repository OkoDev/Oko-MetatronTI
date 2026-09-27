"""Отчёт по замеру механики на разных ТФ (протокол вердикта: ни одного вывода по общей строке).
Срезы: сторона · год · режим года · размер стопа · кластер/одиночка · ликвидность · хрупкость · охват монет.
Всё сравнивается с контролем: случайный вход той же геометрии на той же монете (±30 дней) и на других монетах в тот же момент.
Запуск: python tf_sweep_report.py <тф> [ещё тф ...]"""
import sys, pickle
from pathlib import Path
import numpy as np, pandas as pd
import tf_sweep as T
from tfcache import load_tf

REGIME = {2023: "БЫК", 2024: "МЕДВЕДЬ", 2025: "МЕДВЕДЬ", 2026: "МЕДВЕДЬ"}   # посчитано coverage.py на 477 монетах


def liquidity():
    """Медианный дневной оборот монеты (close×volume) — для среза по ликвидности."""
    p = Path(__file__).with_name("liq.pkl")
    if p.exists():
        return pickle.load(open(p, "rb"))
    out = {}
    for f in sorted(Path("C:/oko_history/1m").glob("*.parquet")):
        try:
            d = load_tf(f.stem, "1d", cols=["close", "volume"])
            out[f.stem] = float((d.close * d.volume).median())
        except Exception:
            pass
    pickle.dump(out, open(p, "wb"))
    return out


def ci(x):
    """95% доверительный интервал среднего по бутстрапу ДНЕЙ (сделки одного дня зависимы — кластер)."""
    if len(x) < 20:
        return np.nan, np.nan
    rs = np.random.default_rng(3); d = pd.Series(x.values, index=x.index)
    days = d.groupby(d.index).mean() if d.index.nlevels == 1 else d
    v = days.values
    m = [np.nanmean(rs.choice(v, len(v))) for _ in range(800)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def block(d, name):
    n = len(d)
    if n == 0:
        return None
    frag = d.pnl.sum() - d.pnl.nlargest(max(1, n // 10)).sum()            # хрупкость: сумма без верхних 10%
    per_coin = d.groupby("sym").pnl.mean()
    return {"срез": name, "n": n, "монет": d.sym.nunique(), "ср%": round(d.pnl.mean(), 2),
            "мед%": round(d.pnl.median(), 2), "WR%": round((d.pnl > 0).mean() * 100),
            "ctl_время": round(d.ctl_time.mean(), 2) if d.ctl_time.notna().any() else np.nan,
            "Δ_время": round(d.pnl.mean() - d.ctl_time.mean(), 2) if d.ctl_time.notna().any() else np.nan,
            "ctl_случ": round(d.ctl_rand.mean(), 2) if d.ctl_rand.notna().any() else np.nan,
            "Δ_случ": round(d.pnl.mean() - d.ctl_rand.mean(), 2) if d.ctl_rand.notna().any() else np.nan,
            "безтоп10%": round(frag / n, 2), "монет+%": round((per_coin > 0).mean() * 100)}


def report(tf):
    d = pd.DataFrame(T.rows_of(tf))
    d = d[d.entered].copy()
    if d.empty:
        print(f"{tf}: пусто"); return
    ctl_p = T.OUT / f"ctl_{tf}.pkl"
    if ctl_p.exists():
        c = pickle.load(open(ctl_p, "rb"))
        d = d.merge(c[["sym", "key", "ctl_rand", "ctl_time"]], on=["sym", "key"], how="left")
    else:
        d["ctl_rand"] = np.nan; d["ctl_time"] = np.nan
    d["top_time"] = pd.to_datetime(d.top_time)
    d["год"] = d.top_time.dt.year
    d["день"] = d.top_time.dt.floor("D")
    liq = liquidity()
    d["оборот"] = d.sym.map(liq)
    d["ликвид"] = np.where(d["оборот"] >= d["оборот"].median(), "ликвидные", "неликвид")
    # кластер: сколько сетапов той же стороны в тот же день по всей базе
    cnt = d.groupby(["день", "side"]).size().rename("в_день")
    d = d.merge(cnt, on=["день", "side"], how="left")
    d["компания"] = np.where(d["в_день"] >= 2, "кластер ≥2", "одиночка")
    q = d.risk_pct.quantile([0.33, 0.66]).values
    d["стоп"] = np.where(d.risk_pct <= q[0], f"узкий ≤{q[0]:.1f}%",
                         np.where(d.risk_pct <= q[1], f"средний ≤{q[1]:.1f}%", f"широкий >{q[1]:.1f}%"))

    print(f"\n{'=' * 118}\n### ТФ {tf} · вход по {T.LTF[tf]} · окно {T.ENTRY_BARS} баров · держим {T.HOLD_BARS} баров · кост {T.COST}%")
    print(f"сделок {len(d)} · монет {d.sym.nunique()} · {d.top_time.min():%Y-%m} … {d.top_time.max():%Y-%m} · "
          f"контроль посчитан для {int(d.ctl_time.notna().sum())}")
    rows = [block(d, "ВСЯ БАЗА")]
    for s in ("LONG", "SHORT"):
        rows.append(block(d[d.side == s], f"сторона {s}"))
    for y in sorted(d["год"].unique()):
        rows.append(block(d[d["год"] == y], f"{y} ({REGIME.get(y, '?')})"))
    for col in ("стоп", "компания", "ликвид"):
        for v in d[col].unique():
            rows.append(block(d[d[col] == v], f"{col}: {v}"))
    for nm, mask in (("ядро fc", d.core_full), ("фрактал", d.fractal), ("ядро+фрактал", d.core_full & d.fractal)):
        rows.append(block(d[mask], f"отбор {nm}"))
    print(pd.DataFrame([r for r in rows if r]).to_string(index=False))
    base = d[d.ctl_time.notna()]
    if len(base) > 50:
        diff = (base.pnl - base.ctl_time)
        lo, hi = ci(pd.Series(diff.values, index=base["день"]))
        print(f"\nΔ к контролю по времени: {diff.mean():+.2f} п.п. · 95% ДИ по дням [{lo:+.2f}; {hi:+.2f}] "
              f"→ {'значимо' if lo > 0 or hi < 0 else 'НЕ значимо (ДИ пересекает ноль)'}")


if __name__ == "__main__":
    for tf in (sys.argv[1:] or ["4h", "1h", "15m", "5m"]):
        report(tf)
