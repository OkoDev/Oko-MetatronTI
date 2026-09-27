"""ПЕРЕМЕР ote_nested «КАК В БОЮ» — реплей боевого генератора по истории (Егор 19.09: «его перемерить точно нужно…
не забывай про историю с бычьим рынком»). Структура под OTE сменилась 02.09 (ARCH-137.5), июньская матрица шкафа устарела.

Что воспроизводится (ротой из bot/loops/ote_observer_loop.py + core/smc/ote_signal_generator.py, ОДИН калькулятор):
  · срезы dfs как в лупе: 3m×600 · 5m×500 · 15m×400 · 1h×300 · 4h×200 · 1d = ресемпл 1h (так в бою!), каузально ≤ t;
  · OTESignalGenerator.generate на закрытии КАЖДОГО 1h-бара; в шкафу enabled только 4h_1h_pull;
  · FIRE проходит роутер только «premium»: 4h_1h_pull + fvg_held (иначе strength ≤ 65 < min_strength 70) — в живых
    сделках fvg_held = 100%;
  · cascade_gate (ote.cascade_gate: true): вход ПРОТИВ 1d-тренда (calculate_trend на 60 НАСТОЯЩИХ 1d барах) блокируется;
  · вход ЛИМИТОМ по sig.entry, TTL 4 бара 1h (entry_ttl_bars), филл — касание цены на 15m; SL = sig.sl, TP = sig.tp1 (1R,
    полный выход — живая медиана RR 1.0), удержание 72 ч; одна позиция на монету; кост 0.10 (лимит).
Контроли: та же геометрия — случайный сдвиг ±30 дн той же монеты (×8) и 5 других монет в тот же момент.
Данные: G:\\oko_lab\\tf (BingX/Binance 1m → ТФ), 2020-06 → 2026-09: бык 2020-21, медведь 2022, 2023, 2024, флэт 2025-26.
Запуск: python ote_nested_replay.py run [монет] [процессов] · parity · report
"""
import sys, glob, pickle, time, random, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ

OUT = Path("G:/oko_lab/out/ote_nested_replay"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01")
COST = 0.10
TAILS = {"3m": 600, "5m": 500, "15m": 400, "1h": 300, "4h": 200}
TTL_H, HOLD_H = 4, 72
MIN_STRENGTH = 70


def _strength(sig):
    s = max(60, min(95, 55 + int(sig.weight * 30)))
    premium = getattr(sig, "setup_id", "") == "4h_1h_pull" and "fvg_held" in (sig.confirmations or [])
    return s if premium else min(s, 65)


def replay_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.ote_signal_generator import OTESignalGenerator
    from core.smc.smc_engine import ote_retest_setups
    from core.indicators.indicators import calculate_trend
    t_start = time.time()
    try:
        D = {tf: load_tf(sym, tf) for tf in ("3m", "5m", "15m", "1h", "4h", "1d")}
    except Exception as e:
        return sym, f"данные: {e}"
    h1 = D["1h"]
    if len(h1) < 1000:
        return sym, "мало истории"
    gen = OTESignalGenerator()
    idx = {tf: D[tf].index.values for tf in D}
    d15 = D["15m"]; i15 = d15.index.values; hi15, lo15, cl15 = d15.high.values, d15.low.values, d15.close.values
    rows = []; busy_until = pd.Timestamp.min; n_fire = n_prem = n_gate = n_nofill = 0
    start = max(int(np.searchsorted(h1.index.values, np.datetime64(T0))), 300)
    # 1d-тренд считаем раз в день (60 настоящих 1d баров, как в _cascade_1d_shadow)
    trend_cache = {}
    # ⚡ предпроверка: generate (~60 мс со всеми LTF-детекторами) зовём только когда цена 1h в какой-то OTE-зоне
    # 4h-сетапов — зоны считаются тем же ote_retest_setups, что внутри generate, раз на новый 4h-бар
    zz_depth, zz_dev = gen._zz("4h"); zones = []; zones_k4 = -1
    for t_i in range(start, len(h1) - 1):
        t = h1.index[t_i]
        if t < busy_until:
            continue
        k4 = int(np.searchsorted(idx["4h"], np.datetime64(t), "right"))
        if k4 < 50:
            continue
        if k4 != zones_k4:
            zones_k4 = k4
            try:
                st4 = ote_retest_setups(D["4h"].iloc[max(0, k4 - TAILS["4h"]):k4], depth=zz_depth, dev_mult=zz_dev,
                                        only_choch=False, provisional=True)
                zones = [x["ote"] for x in st4]
            except Exception:
                zones = []
        px = float(h1.close.values[t_i])
        if not any(lo_ <= px <= hi_ for lo_, hi_ in zones):
            continue
        dfs = {}
        for tf, n in TAILS.items():
            k = int(np.searchsorted(idx[tf], np.datetime64(t), "right"))    # бары с индексом ≤ t (закрытые к t+1h)
            if k < 50:
                dfs = None; break
            dfs[tf] = D[tf].iloc[max(0, k - n):k]
        if not dfs:
            continue
        h = dfs["1h"]
        dfs["1d"] = pd.DataFrame({"open": h.open.resample("1D").first(), "high": h.high.resample("1D").max(),
                                  "low": h.low.resample("1D").min(), "close": h.close.resample("1D").last()}).dropna()
        try:
            sigs = gen.generate(sym, dfs)
        except Exception:
            continue
        fires = [s for s in sigs if s.status == "FIRE"]
        if not fires:
            continue
        n_fire += len(fires)
        sig = max(fires, key=lambda s: (_strength(s), s.conf_score))
        if _strength(sig) < MIN_STRENGTH:
            continue
        n_prem += 1
        long_ = str(sig.direction).lower() == "long"
        # cascade_gate: против 1d-тренда — блок
        day = t.floor("D")
        if day not in trend_cache:
            k1 = int(np.searchsorted(idx["1d"], np.datetime64(day)))          # 1d бары, закрытые до сегодняшнего дня
            dd = D["1d"].iloc[max(0, k1 - 60):k1]
            try:
                tr = calculate_trend(dd.copy())["trend"].iloc[-1] if len(dd) >= 43 else np.nan
            except Exception:
                tr = np.nan
            trend_cache[day] = tr
        tr = trend_cache[day]
        if tr == tr and ((tr < 0) if long_ else (tr > 0)):
            n_gate += 1
            continue
        e, sl, tp = float(sig.entry), float(sig.sl), float(sig.tp1)
        if not (e > 0 and sl > 0 and tp > 0) or (long_ and not (sl < e < tp)) or (not long_ and not (tp < e < sl)):
            continue
        # лимитный вход: касание entry в течение TTL_H после сигнала (бары 15m после закрытия часа t)
        j0 = int(np.searchsorted(i15, np.datetime64(t + pd.Timedelta(hours=1))))
        j_ttl = int(np.searchsorted(i15, np.datetime64(t + pd.Timedelta(hours=1 + TTL_H))))
        fill = None
        for j in range(j0, min(j_ttl, len(d15))):
            if (lo15[j] <= e) if long_ else (hi15[j] >= e):
                fill = j; break
        if fill is None:
            n_nofill += 1
            rows.append({"sym": sym, "t": t, "side": "LONG" if long_ else "SHORT", "filled": False, "entry": e, "stop": sl, "target": tp,
                         "conf": "+".join(sig.confirmations or []), "trg": sig.trigger_type, "risk_pct": abs(e - sl) / e * 100,
                         "tgt_pct": abs(tp - e) / e * 100, "pnl": np.nan, "outcome": "no_fill", "mfe": np.nan})
            busy_until = t + pd.Timedelta(hours=TTL_H)
            continue
        end = int(np.searchsorted(i15, np.datetime64(pd.Timestamp(i15[fill]) + pd.Timedelta(hours=HOLD_H))))
        pnl, outc, k_out = None, "time", min(end, len(d15)) - 1
        for k in range(fill, min(end, len(d15))):
            if (lo15[k] <= sl) if long_ else (hi15[k] >= sl):
                pnl, outc, k_out = ((sl - e) / e * 100) * (1 if long_ else -1), "stop", k; break
            if (hi15[k] >= tp) if long_ else (lo15[k] <= tp):
                pnl, outc, k_out = ((tp - e) / e * 100) * (1 if long_ else -1), "target", k; break
        if pnl is None:
            pnl = ((float(cl15[k_out]) - e) / e * 100) * (1 if long_ else -1)
        seg_h, seg_l = hi15[fill:k_out + 1], lo15[fill:k_out + 1]
        mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
        rows.append({"sym": sym, "t": t, "side": "LONG" if long_ else "SHORT", "filled": True, "entry": e, "stop": sl, "target": tp,
                     "conf": "+".join(sig.confirmations or []), "trg": sig.trigger_type, "risk_pct": abs(e - sl) / e * 100,
                     "tgt_pct": abs(tp - e) / e * 100, "pnl": round(pnl - COST, 3), "outcome": outc, "mfe": round(mfe, 2),
                     "entry_t": pd.Timestamp(i15[fill]), "hold": HOLD_H, "trend1d": tr})
        busy_until = pd.Timestamp(i15[k_out]) + pd.Timedelta(minutes=15)
    # контроли для филлов
    filled = [r for r in rows if r["filled"]]
    if filled:
        from triangle_lab import geo
        rs = random.Random(sum(map(ord, sym)) + 9); oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "15m"))
            except Exception:
                pass
        hold_bars = HOLD_H * 4
        for r in filled:
            long_ = r["side"] == "LONG"; rsk, tg = r["risk_pct"] / 100, r["tgt_pct"] / 100; et = r["entry_t"]
            a = [geo(d15, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, hold_bars) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, hold_bars) for o in oth]
            r["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            r["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump({"rows": rows, "n_fire": n_fire, "n_prem": n_prem, "n_gate": n_gate, "n_nofill": n_nofill}, open(out_p, "wb"))
    return sym, f"FIRE {n_fire} · premium {n_prem} · гейт 1d {n_gate} · без филла {n_nofill} · сделок {len(filled)} за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median"),
                 MFE=("mfe", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    P = [pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*.pkl"))]
    d = pd.DataFrame([r for p in P for r in p["rows"]])
    tot = {k: sum(p[k] for p in P) for k in ("n_fire", "n_prem", "n_gate", "n_nofill")}
    f = d[d.filled].copy(); f["год"] = pd.to_datetime(f.entry_t).dt.year
    print(f"монет {len(P)} · FIRE {tot['n_fire']} · premium (прошли min_strength) {tot['n_prem']} · блок 1d-гейта {tot['n_gate']} · "
          f"заявок без филла {tot['n_nofill']} ({tot['n_nofill'] / max(1, tot['n_nofill'] + len(f)) * 100:.0f}%) · сделок {len(f)} · "
          f"{pd.to_datetime(f.entry_t).min():%Y-%m} → {pd.to_datetime(f.entry_t).max():%Y-%m}\n")
    pd.set_option("display.width", 250)
    print("=== сторона"); print(agg(f.groupby("side")).to_string())
    print("\n=== сторона × год"); print(agg(f.groupby(["side", "год"])).to_string())
    f["conf_к"] = f.conf.str.replace("fvg_held", "F").str.replace("wt_cross", "W").str.replace("atr", "A").str.replace("div", "D").str.replace("vol", "V")
    print("\n=== сторона × подтверждения"); print(agg(f.groupby(["side", "conf_к"])).to_string())
    f["корзина"] = pd.cut(f.risk_pct, [0, 2, 4, 6, 10, 100], labels=["<2%", "2–4%", "4–6%", "6–10%", ">10%"])
    print("\n=== сторона × корзина стопа"); print(agg(f.groupby(["side", "корзина"], observed=True)).to_string())
    day = pd.to_datetime(f.entry_t).dt.floor("D"); f["масс"] = day.map(day.value_counts())
    f["масс_к"] = pd.cut(f["масс"], [0, 1, 3, 6, 999], labels=["1", "2–3", "4–6", "≥7"])
    print("\n=== сторона × массовость дня"); print(agg(f.groupby(["side", "масс_к"], observed=True)).to_string())
    for side in ("LONG", "SHORT"):
        z = f[f.side == side]
        if len(z):
            top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
            print(f"  хрупкость {side}: n {len(z)} · сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · исходы {z.outcome.value_counts().to_dict()} · монет+ {(z.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}%")


def parity():
    """Сверка с живыми сделками 28.08–15.09: на срезе в час сигнала реплей обязан дать FIRE того же направления."""
    import sqlite3, json
    con = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True)
    live = pd.read_sql("SELECT symbol, direction, created_at, entry_price, stop_loss, take_profit, features_json FROM simulated_trades "
                       "WHERE source_router='ote_nested' AND created_at BETWEEN '2026-08-29' AND '2026-09-15' ORDER BY created_at", con)
    live["sym"] = live.symbol.str.split("/").str[0] + "USDT"; live["t"] = pd.to_datetime(live.created_at).dt.tz_localize(None).dt.floor("h")
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.ote_signal_generator import OTESignalGenerator
    gen = OTESignalGenerator(); ok = tot = 0; res = []
    for sym, grp in live.groupby("sym"):
        try:
            D = {tf: load_tf(sym, tf) for tf in ("3m", "5m", "15m", "1h", "4h")}
        except Exception:
            continue
        idx = {tf: D[tf].index.values for tf in D}
        for r in grp.itertuples():
            t = r.t - pd.Timedelta(hours=1)                      # сигнал в бою даётся ПОСЛЕ закрытия часа → срез по закрытому бару
            dfs = {}
            for tf, n in TAILS.items():
                k = int(np.searchsorted(idx[tf], np.datetime64(t), "right")); dfs[tf] = D[tf].iloc[max(0, k - n):k]
            h = dfs["1h"]
            dfs["1d"] = pd.DataFrame({"open": h.open.resample("1D").first(), "high": h.high.resample("1D").max(),
                                      "low": h.low.resample("1D").min(), "close": h.close.resample("1D").last()}).dropna()
            hit = False
            for dt_ in (0, 1, -1):
                tt = t + pd.Timedelta(hours=dt_)
                if dt_:
                    for tf, n in TAILS.items():
                        k = int(np.searchsorted(idx[tf], np.datetime64(tt), "right")); dfs[tf] = D[tf].iloc[max(0, k - n):k]
                    h = dfs["1h"]
                    dfs["1d"] = pd.DataFrame({"open": h.open.resample("1D").first(), "high": h.high.resample("1D").max(),
                                              "low": h.low.resample("1D").min(), "close": h.close.resample("1D").last()}).dropna()
                try:
                    sigs = gen.generate(sym, dfs)
                except Exception:
                    sigs = []
                fires = [s for s in sigs if s.status == "FIRE" and str(s.direction).upper() == r.direction]
                if fires:
                    hit = True; e = float(fires[0].entry)
                    res.append((sym, str(r.t), r.direction, round(e, 6), round(r.entry_price, 6), round((e / r.entry_price - 1) * 100, 2)))
                    break
            tot += 1; ok += hit
    print(f"parity: {ok}/{tot} живых сделок воспроизведены FIRE того же направления (±1 ч)")
    for x in res[:12]:
        print("  ", x)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        if os.environ.get("MIN_YEARS"):                        # вселенная: монеты с историей ≥ N лет (бык 2020-21 обязателен)
            import pyarrow.parquet as pq
            keep = []
            for s_ in syms:
                try:
                    md = pq.read_metadata(PARQ / f"{s_}.parquet")
                    if md.num_rows >= float(os.environ["MIN_YEARS"]) * 365 * 1440 * 0.9:
                        keep.append(s_)
                except Exception:
                    pass
            syms = keep
            print(f"вселенная: {len(syms)} монет с историей ≥ {os.environ['MIN_YEARS']} лет", flush=True)
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(replay_symbol, jobs), 1):
                print(f"  {i}/{len(jobs)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    elif cmd == "parity":
        parity()
    else:
        report()
