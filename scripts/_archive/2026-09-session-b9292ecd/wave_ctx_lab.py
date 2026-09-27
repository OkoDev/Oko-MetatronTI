"""Волновой контекст на истории сделок OTE-источников (15.09, Егор: «начинай замер» — шаг 1 плана шины).
Для каждой закрытой сделки на момент сигнала, только по 4h-барам, ЗАКРЫТЫМ к created_at:
  zone_1d   — зона входа в дневной ноге аналитика (core.waves.wave_analyst.daily_leg, та же нога, что в TG/тени)
  fifth     — завершённая 4h-пятёрка ядра за последние 30 баров (5 сут): 'по ходу' (сторона сетапа = сторона сделки) / 'против' / нет
  overlap   — доля OTE-зоны источника (ote_zone_lo/hi), лежащая в полосе 0.618–0.79 ноги аналитика
Запуск: python wave_ctx_lab.py fetch | feat | report"""
import sys, json, sqlite3, pickle, time
from pathlib import Path
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).parent
BARS = HERE / "wave_ctx_4h.pkl"; FEAT = HERE / "wave_ctx_feat.pkl"
SOURCES = ("ote_nested", "oko_ote", "impulse_fib", "impulse_fib_15m", "choch_wavec")


def trades():
    c = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True)
    d = pd.read_sql("select id, signal_type src, symbol, direction, entry_price, stop_loss, take_profit, created_at, closed_at, status, "
                    "profit_pct, execution_mode, features_json from simulated_trades where signal_type in (%s) and status in ('TP','SL','TSL','EXPIRED')"
                    % ",".join("?" * len(SOURCES)), c, params=SOURCES)
    f = d.features_json.map(lambda s: json.loads(s or "{}"))
    for k in ("data_era", "ote_htf", "ote_ltf", "ote_zone_lo", "ote_zone_hi", "volume_24h"):
        d[k] = f.map(lambda x: x.get(k))
    d = d.drop(columns="features_json")
    d["ts"] = pd.to_datetime(d.created_at, utc=True, format="ISO8601")
    d["base"] = d.symbol.str.split("/").str[0]
    return d


def fetch():
    from core.waves.bingx_klines import fetch_closed
    d = trades(); bases = sorted(d.base.unique()); print("монет:", len(bases), "сделок:", len(d), d.groupby(["src", "execution_mode"]).size().to_dict())
    out = pickle.load(open(BARS, "rb")) if BARS.exists() else {}

    def one(b):
        if b in out:
            return b, out[b]
        for k in range(3):
            try:
                return b, fetch_closed(b, "4h", 1500)
            except Exception as e:
                time.sleep(2 + 3 * k); err = e
        print("  нет", b, err); return b, None
    with ThreadPoolExecutor(3) as ex:
        for i, (b, df) in enumerate(ex.map(one, bases), 1):
            out[b] = df
            if i % 50 == 0:
                print(" ", i); pickle.dump(out, open(BARS, "wb"))
    pickle.dump(out, open(BARS, "wb")); print("ok", sum(v is not None and len(v) > 0 for v in out.values()))


def feat_symbol(args):
    base, g, dh = args
    from core.waves.wave_analyst import daily_leg
    from core.waves.wave5_core import mark_impulse, WaveParams
    rows, cache = [], {}
    if dh is None or len(dh) < 300:
        return rows
    close_t = dh.index + pd.Timedelta(hours=4)
    for r in g.itertuples():
        cut = dh[close_t <= r.ts]
        if len(cut) < 250:
            continue
        bar = cut.index[-1]; long_ = r.direction == "LONG"
        if bar not in cache:
            try:
                st = mark_impulse(cut, r.ts, WaveParams(), "4h", lookback=30)
            except Exception:
                st = []
            cache[bar] = st
        st = cache[bar]
        fifth = "нет"
        if st:
            s = st[0]; fifth = "по ходу" if s["side"] == r.direction else "против"
            core_full = bool(s["core_full"])
        else:
            core_full = False
        try:
            leg = daily_leg(cut, r.ts, (not long_), float(r.entry_price), r.ts, r.ts)
        except Exception:
            leg = None
        zone, depth, ov = "нет ноги", np.nan, np.nan
        if leg:
            zone, depth = leg["zone"], leg["depth"]
            lo, hi = sorted((leg["levels"]["0.618"], leg["levels"]["0.79"]))
            if r.ote_zone_lo is not None and r.ote_zone_hi is not None:
                zl, zh = sorted((float(r.ote_zone_lo), float(r.ote_zone_hi)))
                ov = max(0.0, min(zh, hi) - max(zl, lo)) / (zh - zl) if zh > zl else np.nan
        rows.append({"id": r.id, "zone_1d": zone, "depth_1d": depth, "fifth": fifth, "fifth_core": core_full, "overlap": ov})
    return rows


def feat():
    d = trades(); bars = pickle.load(open(BARS, "rb"))
    jobs = [(b, g, bars.get(b)) for b, g in d.groupby("base")]
    with Pool(8) as p:
        res = [x for rr in p.imap_unordered(feat_symbol, jobs, chunksize=2) for x in rr]
    f = d.merge(pd.DataFrame(res), on="id", how="left")
    pickle.dump(f, open(FEAT, "wb")); print("ok", len(f), f.zone_1d.notna().sum())


if __name__ == "__main__":
    {"fetch": fetch, "feat": feat}[sys.argv[1]]()
