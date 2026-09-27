"""ГЛУБИНА В ДНЕВНОЙ НОГЕ КАК СРЕЗ (Егор 18.09: «если цена ушла за начало ноги — может означать разворот»).
Метка на /waves: мелкая (<0.5) · 0.5-0.62 · OTE 0.62-0.79 · глубокая 0.79-1.0 · за пределами ноги (>1).
Для нашего LONG (отскок после хода вниз) дневная нога — восходящая; depth>1 = падение прошло НИЖЕ её начала,
то есть тренд развернулся вниз, и лонг — отскок против нового тренда. Мерим, как отрабатывают сделки по зонам.
Нога считается тем же кодом, что в аналитике и в шине (core.waves.wave_analyst.daily_leg), каузально — по дневным
барам, закрытым к моменту детекции. Данные: сделки tf_sweep 4h (боевые правила).
Запуск: python leg_zone_lab.py
"""
import sys, glob, pickle
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
import tf_sweep as T
from core.waves.wave_analyst import daily_leg, leg_zone


def main():
    rows = [r for r in T.rows_of("4h") if r.get("entered") and r["side"] == "LONG"]
    d = pd.DataFrame(rows)
    ctl_p = T.OUT / "ctl_4h.pkl"
    if ctl_p.exists():
        c = pickle.load(open(ctl_p, "rb")); d = d.merge(c[["sym", "key", "ctl_time"]], on=["sym", "key"], how="left")
    else:
        d["ctl_time"] = np.nan
    zones, depths = [], []
    cache = {}
    for r in d.itertuples():
        try:
            if r.sym not in cache:
                cache[r.sym] = (load_tf(r.sym, "4h"), load_tf(r.sym, "1d"))
            dh, dd = cache[r.sym]
            t0 = pd.to_datetime(r.key.split("|")[0], format="%Y%m%d%H")
            t5 = pd.Timestamp(r.top_time); now = t5 + pd.Timedelta(hours=4)
            leg = daily_leg(dh, t0, want_top=False, p5=float(r.stop) / (1 - 0.0015), t5x=t5, now=now, dd=dd[dd.index < now])
            if leg:
                depths.append(leg["depth"]); zones.append(leg["zone"])
            else:
                depths.append(np.nan); zones.append("нет ноги")
        except Exception:
            depths.append(np.nan); zones.append("ошибка")
    d["depth"] = depths; d["зона"] = zones
    order = ["мелкая (<0.5)", "мелкая 0.5–0.62", "OTE 0.62–0.79", "глубокая 0.79–1.0", "за пределами ноги (>1)", "нет ноги"]
    d["зона"] = pd.Categorical(d["зона"], [z for z in order if z in set(d["зона"])] + [z for z in set(d["зона"]) if z not in order])
    g = d.groupby("зона", observed=True).agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                              ср=("pnl", "mean"), мед=("pnl", "median"), ctl=("ctl_time", "mean"), риск=("risk_pct", "median"))
    g["Δ"] = (g["ср"] - g["ctl"]).round(2); g["доля%"] = (g.n / len(d) * 100).round(0)
    print(f"LONG-сделки 4h: {len(d)} · с размеченной дневной ногой {int(d.depth.notna().sum())}\n")
    print(g.round(2).to_string())
    d["год"] = pd.to_datetime(d.top_time).dt.year
    print("\nзона «за пределами ноги (>1)» по годам:")
    z = d[d["зона"] == "за пределами ноги (>1)"]
    if len(z):
        print(z.groupby("год").agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                                   ctl=("ctl_time", "mean")).assign(Δ=lambda x: (x["ср"] - x["ctl"]).round(2)).round(2).to_string())
    print("\nс отбором ядро fc:")
    print(d[d.core_full].groupby("зона", observed=True).agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                                            ср=("pnl", "mean")).round(2).to_string())


if __name__ == "__main__":
    main()
