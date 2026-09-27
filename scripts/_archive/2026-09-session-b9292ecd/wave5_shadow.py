"""ТЕНЬ-ФОРВАРД ядра «коррекция после пятой волны» (14.09.2026). Без денег.
Каждый запуск: живые бары BingX (4h, 15m) по монетам ядра → на последнем ЗАКРЫТОМ 4h-баре разметка
импульса (двухслойный OKO-SM, масштаб 15/4) → все поля ядра → состояние сетапа:
  detected (импульс виден, ждём вход) → entered (первый кросс WT / пробой линии 2-4 на 15m) → closed (цель / стоп / 10 суток).
Пишет shadow_signals.csv (колонка `egor` — для ручной оценки разметки), рисует charts_shadow/<sym>_<date>.png.
Запуск: python wave5_shadow.py [--ltf 15m] [--pairs 150] [--draw]. Повторять каждые 4 ч (после закрытия бара)."""
import sys, json, argparse, time, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, ".")
warnings.filterwarnings("ignore")
from wave5_sm import (impulses_on_bar, fractal_check, wt_pack, _swings, run_structure, calculate_wt, calculate_trend,
                      TF_MIN, MIN_IMP_PCT, MAX_IMP_PCT, INTERNAL_LEN, BUF)
from research_harness import universe
import ccxt

SP = Path(__file__).parent
STATE = SP / "shadow_state.json"; CSV = SP / "shadow_signals.csv"; CH = SP / "charts_shadow"; CH.mkdir(exist_ok=True)
SW, IL, Z, CTX_SW = 15, 4, 45.0, 10
ENTRY_W_H, HOLD_H = 96, 240


NOW = pd.Timestamp.utcnow()      # переопределяется --asof (самопроверка на истории)


def fetch(ex, sym, tf, n):
    ms = TF_MIN[tf] * 60_000; out = []; end_ms = int(NOW.timestamp() * 1000); since = end_ms - n * ms
    while len(out) < n:
        o = ex.fetch_ohlcv(sym, tf, since=since, limit=1000)
        if not o: break
        out += o; since = o[-1][0] + ms
        if len(o) < 1000 or since >= end_ms: break
    df = pd.DataFrame(out, columns=["time", "open", "high", "low", "close", "volume"]).drop_duplicates("time")
    df["ts"] = pd.to_datetime(df.time, unit="ms", utc=True); df = df.set_index("ts")[["open", "high", "low", "close", "volume"]]
    # только бары, ЗАКРЫТЫЕ к моменту NOW (последний живой бар открыт — убираем)
    return df[df.index + pd.Timedelta(minutes=TF_MIN[tf]) <= NOW]


def depth5_of(w_idx, w_px, up):
    xi = [float(v) for v in w_idx]; px = [float(v) for v in w_px]; sgn = 1.0 if up else -1.0
    slope = (px[4] - px[2]) / (xi[4] - xi[2]) if xi[4] > xi[2] else 0.0
    width = sgn * (px[3] - (px[2] + slope * (xi[3] - xi[2]))); depth = sgn * (px[5] - (px[4] + slope * (xi[5] - xi[4])))
    return depth / width if width > 0 else np.nan


def analyze(sym, dh, dl, state):
    """Разметка на последнем закрытом 4h-баре + поля ядра. Возвращает список сетапов (dict)."""
    idx_h = dh.index; hh, lh = dh.high.values.astype(float), dh.low.values.astype(float)
    dhr = dh.reset_index(drop=True); n_h = len(dhr); t = n_h - 1
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=SW, internal_len=IL)
    swings = _swings(dhr["high"], dhr["low"], SW); swings_i = _swings(dhr["high"], dhr["low"], IL)
    wt1_h, _, _, b_reg, s_reg, b_hid, s_hid, _ = wt_pack(dhr)
    # 1D из 4h
    dd = dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    dd = dd[dd.index + pd.Timedelta(days=1) <= NOW]     # только закрытые дни
    d_ev = [e for e in run_structure(dd, swing_len=CTX_SW, internal_len=3).events if not e.internal] if len(dd) > CTX_SW * 3 else []
    d_sw = _swings(dd["high"], dd["low"], CTX_SW) if len(dd) > CTX_SW * 3 else []
    d_wt = calculate_wt(dd.copy())["wt1"].values.astype(float) if len(dd) > 30 else np.array([np.nan])
    out = []
    for imp in impulses_on_bar(swings, t, hh, lh):
        w = imp["waves"]; w_idx = [int(x[0]) for x in w]; w_px = [float(x[1]) for x in w]
        a, b = w_idx[0], w_idx[5]; p0, p4, p5 = w_px[0], w_px[4], w_px[5]; up = imp["direction"] == "up"
        rng = abs(p5 - p0); imp_pct = rng / p0 * 100
        if not (MIN_IMP_PCT <= imp_pct <= MAX_IMP_PCT): continue
        if not np.isfinite(wt1_h[b]) or not ((wt1_h[b] > Z) if up else (wt1_h[b] < -Z)): continue
        fr = fractal_check(st.events, w_idx, up, t)
        dep = depth5_of(w_idx, w_px, up)
        ns = [sum(1 for s in swings_i if s[0] <= t and w_idx[k] < s[1] <= w_idx[k + 1]) for k in range(5)]
        t2, t4 = w_idx[2] - w_idx[1], w_idx[4] - w_idx[3]
        alt_type = (imp["w2_retr"] > imp["w4_retr"] and t2 < t4) or (imp["w2_retr"] < imp["w4_retr"] and t2 > t4)
        alt_form = abs(ns[1] - ns[3]) >= 2
        prev = [s for s in swings if s[0] <= t and s[1] < a]; count_ok = True; alt_w3_w1 = np.nan
        if len(prev) >= 2 and prev[-2][3] == (not up) and prev[-1][3] == up:
            p0p, p1p = float(prev[-2][2]), float(prev[-1][2]); l1p = abs(p0p - p1p)
            ok = ((p0 <= p0p) if not up else (p0 >= p0p)) and ((w_px[1] < p1p) if not up else (w_px[1] > p1p))
            alt_w3_w1 = abs(p0 - w_px[1]) / l1p if l1p else np.nan
            count_ok = not (ok and np.isfinite(alt_w3_w1) and alt_w3_w1 >= 1.0 and alt_w3_w1 > imp["w3_ext"])
        # дневной контекст (последний закрытый день)
        d_bull = d_broke = None; d_wt_last = float(d_wt[-1]) if np.isfinite(d_wt[-1]) else np.nan
        if d_ev:
            d_bull = bool(d_ev[-1].bull)
            lows = [s for s in d_sw if not s[3]]; highs = [s for s in d_sw if s[3]]
            if not up and lows: d_broke = bool(p5 < lows[-1][2])
            if up and highs: d_broke = bool(p5 > highs[-1][2])
        # линия 2-4 и статус на LTF от вершины w5
        lt = dl.index.values.astype("datetime64[ns]"); c_l = dl.close.values.astype(float)
        wt1_l, cup_l, cdn_l, *_ = wt_pack(dl.reset_index(drop=True))
        t5 = np.datetime64(idx_h[b].to_datetime64()); jb = int(np.searchsorted(lt, t5))
        x2, x4 = float(w_idx[2]), float(w_idx[4]); y2, y4 = w_px[2], w_px[4]; slope = (y4 - y2) / (x4 - x2) if x4 > x2 else 0.0
        t_x4 = np.datetime64(idx_h[int(x4)].to_datetime64())
        def line_at(m): return y4 + slope * ((x4 + (lt[m] - t_x4) / np.timedelta64(240, "m")) - x4)
        line_now = line_at(len(lt) - 1) if len(lt) else np.nan
        broke = [m for m in range(jb, len(lt)) if ((c_l[m] > line_at(m)) if not up else (c_l[m] < line_at(m)))]
        cross = cup_l if not up else cdn_l; crosses = [m for m in range(jb, len(lt)) if cross[m]]
        ext = float(dl.low.values[jb:].min()) if (not up and jb < len(lt)) else (float(dl.high.values[jb:].max()) if jb < len(lt) else p5)
        p5e = min(p5, ext) if not up else max(p5, ext)
        hours_from_top = (NOW - idx_h[b]).total_seconds() / 3600
        key = f"{sym}|{idx_h[a]:%Y%m%d%H}|{idx_h[w_idx[4]]:%Y%m%d%H}"
        # 🔑 ФИБО-ПРОГНОЗ по разметке (Егор): пока пятая идёт — где ждать её конец; когда завершена — цели коррекции
        sg = -1.0 if not up else 1.0                  # направление импульса
        w1 = abs(w_px[1] - p0); rng_e = abs(p5e - p0)
        # параллель канала через точку 3 на текущий момент (цель пятой по каналу)
        y3 = w_px[3]; x3 = float(w_idx[3]); pos_now = x4 + (lt[-1] - t_x4) / np.timedelta64(240, "m") if len(lt) else x4
        chan_now = y3 + slope * (pos_now - x3)
        fib = {"w5_eq1": p4 + sg * 1.0 * w1, "w5_618": p4 + sg * 0.618 * w1, "w5_1618": p4 + sg * 1.618 * w1, "w5_chan": chan_now,
               "corr_382": p5e - sg * 0.382 * rng_e, "corr_500": p5e - sg * 0.5 * rng_e, "corr_618": p5e - sg * 0.618 * rng_e, "corr_w4": p4}
        fib = {k: round(float(v), 8) for k, v in fib.items()}
        # линия 2-4 как функция времени (для лёгкого цикла без 4h-ряда): цена = ref + slope_h × часов от ref_time
        line_ref_time = str(idx_h[int(x4)]); line_slope_h = slope / 4.0
        row = {"key": key, "sym": sym, "side": "LONG" if not up else "SHORT", "top_time": str(idx_h[b]), "hours_from_top": round(hours_from_top, 1),
               "p0": p0, "p4_target": p4, "p5": p5, "p5_ext": p5e, "imp_pct": round(imp_pct, 1), "wt_top": round(float(wt1_h[b]), 1),
               "w2_retr": round(imp["w2_retr"], 2), "w4_retr": round(imp["w4_retr"], 2), "w3_ext": round(imp["w3_ext"], 2),
               "fractal": bool(fr["fractal_ok"]), "bos13": f"{fr.get('bos1',0)}/{fr.get('bos3',0)}", "depth5": round(dep, 2) if np.isfinite(dep) else None,
               "altern_type": bool(alt_type), "altern_form": bool(alt_form), "ns": "/".join(map(str, ns)), "count_ok": bool(count_ok),
               "alt_w3_w1": round(alt_w3_w1, 2) if np.isfinite(alt_w3_w1) else None,
               "d_bull": d_bull, "d_broke": d_broke, "d_wt": round(d_wt_last, 1) if np.isfinite(d_wt_last) else None,
               "line24_now": round(line_now, 6) if np.isfinite(line_now) else None, "line24_broken": bool(broke), "line24_first": str(dl.index[broke[0]]) if broke else None,
               "cross_first": str(dl.index[crosses[0]]) if crosses else None, "last_close": float(c_l[-1]),
               "core": bool(fr["fractal_ok"] and np.isfinite(dep) and dep >= 0.5), "core_full": bool(fr["fractal_ok"] and np.isfinite(dep) and dep >= 0.5 and (alt_type or alt_form) and count_ok),
               "line_ref_time": line_ref_time, "line_ref_price": float(y4), "line_slope_h": float(line_slope_h), **fib,
               "wave_idx": w_idx, "wave_px": w_px[:5] + [p5e], "a": a, "b": b, "t": t}
        out.append(row)
    return out


def draw_setup(r, dh, ltf, out):
    from wave5_charts import draw_trade
    rr = dict(r); rr.update({"htf": "4h", "ltf": ltf, "dir": "up" if r["side"] == "SHORT" else "down", "ts": pd.Timestamp(r["top_time"]), "entry": r["last_close"],
                             "sl": r["p5_ext"] * (1 - BUF) if r["side"] == "LONG" else r["p5_ext"] * (1 + BUF), "sl_pct": abs(r["last_close"] - r["p5_ext"]) / r["last_close"] * 100,
                             "p4": r["p4_target"], "p5": r["p5_ext"], "hold": 60, "pnl_w4": 0.0, "hit_w4": False, "stopped": False, "fractal_ok": r["fractal"],
                             "bos1": int(r["bos13"].split("/")[0]), "bos3": int(r["bos13"].split("/")[1]), "bos5": 0, "line24_break": r["line24_broken"],
                             "ns2": int(r["ns"].split("/")[1]), "ns4": int(r["ns"].split("/")[3]), "tgt_f382": r["corr_382"], "tgt_f618": r["corr_618"]})
    lv = [(r["w5_eq1"], "прогноз 5 = 1", "#c8791a"), (r["w5_618"], "5 = 0.618×1", "#c8791a"), (r["w5_1618"], "5 = 1.618×1", "#c8791a", "--"),
          (r["w5_chan"], "параллель канала (цель 5)", "#ff8f00", "-."), (r["corr_500"], "коррекция 0.5", "#7e57c2")]
    draw_trade(pd.Series(rr), "4h", out, df=dh, levels=lv)


def update_state(prev, r, dl, ltf, now, sym):
    """Переход статусов: detected → entered → closed. Общий для тяжёлого и лёгкого циклов."""
    st_ = prev.get("status", "detected"); long_ = r["side"] == "LONG"
    if st_ == "detected" and (r["cross_first"] or r["line24_broken"]):
        prev["status"] = "entered"; prev["entered_at"] = now; prev["entry_price"] = r["last_close"]
        prev["entry_trigger"] = "cross" if r["cross_first"] and (not r["line24_broken"] or r["cross_first"] <= (r["line24_first"] or "9")) else "line24"
        print(f"  IN   {sym:<12} {r['side']} вход по {prev['entry_trigger']} ~{r['last_close']} · цель {r['p4_target']:.6g} · стоп за {r['p5_ext']:.6g}", flush=True)
    elif st_ == "entered":
        e = prev["entry_price"]
        hit = (r["last_close"] >= r["p4_target"]) if long_ else (r["last_close"] <= r["p4_target"])
        stop = (dl.low.values[-int(4 * 60 / TF_MIN[ltf]):].min() <= r["p5_ext"]) if long_ else (dl.high.values[-int(4 * 60 / TF_MIN[ltf]):].max() >= r["p5_ext"])
        aged = (NOW - pd.Timestamp(prev["entered_at"], tz="UTC")).total_seconds() / 3600 > HOLD_H
        if hit or stop or aged:
            prev["status"] = "closed"; prev["closed_at"] = now; prev["outcome"] = "target" if hit else ("stop" if stop else "time")
            prev["pnl_pct"] = round(((r["last_close"] - e) / e * 100) * (1 if long_ else -1), 2)
            print(f"  OUT  {sym:<12} {prev['outcome']} {prev['pnl_pct']:+.2f}%", flush=True)
    # прогноз по фибо: факт против прогноза (для сверки разметки без ожидания исхода сделки)
    if st_ != "closed":
        ex_ = r["p5_ext"]; w5_hit = []
        for k in ("w5_618", "w5_eq1", "w5_chan", "w5_1618"):
            v = r.get(k) if k in r else prev.get(k)
            if v is None: continue
            if (ex_ <= v) if long_ else (ex_ >= v): w5_hit.append(k)
        prev["w5_reached"] = ",".join(w5_hit)              # какие прогнозные уровни пятой уже достигнуты экстремумом
        c = r["last_close"]; best = []
        for k in ("corr_382", "corr_500", "corr_618", "corr_w4"):
            v = r.get(k) if k in r else prev.get(k)
            if v is None: continue
            if (c >= v) if long_ else (c <= v): best.append(k)
        prev["corr_reached"] = ",".join(best)             # какие цели коррекции цена уже показала закрытием
    for kk in ("hours_from_top", "line24_broken", "line24_first", "cross_first", "last_close", "depth5", "d_wt", "p5_ext"):
        if kk in r: prev[kk] = r[kk]


def light_state(prev, dl, ltf):
    """Лёгкий цикл: по сохранённой разметке и свежему LTF-ряду пересчитать вход/экстремум/линию/цели без 4h."""
    long_ = prev["side"] == "LONG"; up = not long_
    lt = dl.index.values.astype("datetime64[ns]"); c_l = dl.close.values.astype(float)
    wt1_l, cup_l, cdn_l, *_ = wt_pack(dl.reset_index(drop=True))
    t5 = np.datetime64(pd.Timestamp(prev["top_time"]).to_datetime64()); jb = int(np.searchsorted(lt, t5))
    ref_t = np.datetime64(pd.Timestamp(prev["line_ref_time"]).to_datetime64()); ref_p = float(prev["line_ref_price"]); sh = float(prev["line_slope_h"])
    def line_at(m): return ref_p + sh * ((lt[m] - ref_t) / np.timedelta64(60, "m"))
    broke = [m for m in range(jb, len(lt)) if ((c_l[m] > line_at(m)) if long_ else (c_l[m] < line_at(m)))]
    cross = cup_l if long_ else cdn_l; crosses = [m for m in range(jb, len(lt)) if cross[m]]
    ext = float(dl.low.values[jb:].min()) if (long_ and jb < len(lt)) else (float(dl.high.values[jb:].max()) if jb < len(lt) else prev["p5"])
    p5e = min(prev["p5"], ext) if long_ else max(prev["p5"], ext)
    r = dict(prev); r.update({"side": prev["side"], "cross_first": str(dl.index[crosses[0]]) if crosses else None, "line24_broken": bool(broke),
                              "line24_first": str(dl.index[broke[0]]) if broke else None, "last_close": float(c_l[-1]), "p5_ext": p5e,
                              "hours_from_top": round((NOW - pd.Timestamp(prev["top_time"])).total_seconds() / 3600, 1)})
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ltf", default="15m"); ap.add_argument("--pairs", type=int, default=150); ap.add_argument("--draw", action="store_true")
    ap.add_argument("--only-core", action="store_true", help="писать только сетапы с фракталом и каналом")
    ap.add_argument("--asof", default=None, help="самопроверка: момент в прошлом, напр. 2026-01-14T04:00")
    ap.add_argument("--syms", default=None, help="список монет через запятую вместо вселенной")
    ap.add_argument("--universe", default="cache", choices=["cache", "bingx"], help="cache = 150 монет кэша проекта · bingx = все swap USDT с оборотом ≥ --min_vol")
    ap.add_argument("--min_vol", type=float, default=2e6, help="порог оборота 24ч (USDT) для --universe bingx")
    a = ap.parse_args()
    main_scan(a)


def main_scan(a):
    global NOW
    NOW = pd.Timestamp(a.asof, tz="UTC") if a.asof else pd.Timestamp.utcnow()
    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}}); mk = ex.load_markets()
    have = {m["base"] for s, m in mk.items() if m.get("swap") and m.get("quote") == "USDT"}
    if a.syms:
        syms = a.syms.split(",")
    elif a.universe == "bingx":
        tk = ex.fetch_tickers()
        liq = sorted(((s_, m["base"], (tk.get(s_) or {}).get("quoteVolume") or 0) for s_, m in mk.items()
                      if m.get("swap") and m.get("quote") == "USDT" and m.get("active")), key=lambda x: -x[2])
        syms = [f"{b}/USDT" for s_, b, v in liq if v >= a.min_vol]
        print(f"вселенная BingX: {len(syms)} монет с оборотом ≥ {a.min_vol/1e6:.0f}M", flush=True)
    else:
        syms = [s for s in universe("4h", n=a.pairs) if s.split("/")[0] in have]
    state = ({} if a.asof else (json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}))
    now = NOW.strftime("%Y-%m-%d %H:%M")
    print(f"[{now} UTC] тень: {len(syms)} монет · LTF {a.ltf}", flush=True)
    found = []
    for i, s in enumerate(syms, 1):
        bx = f"{s.split('/')[0]}/USDT:USDT"
        try:
            dh = fetch(ex, bx, "4h", 1000); dl = fetch(ex, bx, a.ltf, int(ENTRY_W_H * 60 / TF_MIN[a.ltf]) * 4)
            from wave5_sm import load as _load_cache
            if len(dh) < 400 and a.asof:            # --asof: 4h из кэша проекта, если биржа не отдала историю
                dh = _load_cache(s, "4h"); dh = dh[dh.index + pd.Timedelta(hours=4) <= NOW].tail(1000)
            if len(dl) < 200:                       # биржа держит 15m ~30 дн, 5m меньше: для --asof берём LTF из кэша проекта
                dl = _load_cache(s, a.ltf); dl = dl[dl.index + pd.Timedelta(minutes=TF_MIN[a.ltf]) <= NOW].tail(int(ENTRY_W_H * 60 / TF_MIN[a.ltf]) * 4)
            if len(dh) < 400 or len(dl) < 200:
                print(f"  [skip] {s}: мало данных 4h={len(dh)} {a.ltf}={len(dl)}", flush=True); continue
            for r in analyze(s, dh, dl, state):
                if a.only_core and not r["core"]: continue
                found.append(r)
                k = r["key"]; prev = state.get(k)
                if prev is None:
                    r["detected_at"] = now; r["status"] = "detected"; state[k] = {kk: v for kk, v in r.items() if kk not in ("wave_idx", "wave_px")}
                    print(f"  NEW  {s:<12} {r['side']} вершина {r['top_time'][:16]} ({r['hours_from_top']:.0f} ч) импульс {r['imp_pct']}% фрактал {r['fractal']} канал {r['depth5']} черед {int(r['altern_type'])}/{int(r['altern_form'])} счёт {r['count_ok']} 1D {r['d_bull']}/{r['d_broke']} WT1D {r['d_wt']} | линия2-4 {'ПРОБИТА' if r['line24_broken'] else 'нет'} кросс {r['cross_first'] or 'нет'} · {'ЯДРО' if r['core_full'] else ('канал' if r['core'] else '')}", flush=True)
                    update_state(state[k], r, dl, a.ltf, now, s)
                    if a.draw:
                        try: draw_setup(r, dh, a.ltf, CH / f"{s.replace('/', '')}_{pd.Timestamp(r['top_time']):%Y%m%d}.png")
                        except Exception as ex_: print("   (картинка не удалась:", ex_, ")")
                else:
                    update_state(prev, r, dl, a.ltf, now, s)
        except Exception as ex_:
            print(f"  [skip] {s}: {type(ex_).__name__} {ex_}", flush=True)
        if i % 25 == 0: print(f"  {i}/{len(syms)}", flush=True)
    save_and_report(state, a)


def save_and_report(state, a):
    if not a.asof: STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    df = pd.DataFrame(list(state.values()))
    if len(df):
        if "egor" not in df: df["egor"] = ""
        cols = ["status", "sym", "side", "top_time", "hours_from_top", "imp_pct", "fractal", "depth5", "altern_type", "altern_form", "count_ok", "d_bull", "d_broke", "d_wt",
                "core", "core_full", "w5_reached", "corr_reached", "line24_broken", "cross_first", "entry_trigger", "entered_at", "entry_price", "p4_target", "p5_ext", "outcome", "pnl_pct", "egor",
                "w5_eq1", "w5_618", "w5_1618", "w5_chan", "corr_382", "corr_500", "corr_618", "key"]
        df = df.reindex(columns=[c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols])
        if not a.asof: df.sort_values(["status", "top_time"], ascending=[True, False]).to_csv(CSV, index=False, encoding="utf-8-sig")
    act = df[df.status != "closed"] if len(df) else df
    print(f"\n[{NOW:%Y-%m-%d %H:%M} UTC] активных сетапов: {len(act)} (ядро полное: {int(act.core_full.sum()) if len(act) else 0}, канал: {int(act.core.sum()) if len(act) else 0}) · всего в журнале {len(df)} · {CSV.name}", flush=True)
    if len(act):
        cols = [c for c in ("status", "sym", "side", "top_time", "hours_from_top", "imp_pct", "fractal", "depth5", "altern_type", "altern_form", "count_ok", "d_wt", "w5_reached", "corr_reached", "line24_broken", "cross_first", "core_full") if c in act]
        print(act[cols].to_string(index=False), flush=True)


def watch(a):
    """Лёгкий цикл (каждые 15 мин): только активные сетапы, только LTF."""
    global NOW
    NOW = pd.Timestamp.utcnow(); now = NOW.strftime("%Y-%m-%d %H:%M")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    act = {k: v for k, v in state.items() if v.get("status") != "closed" and "line_ref_time" in v}
    if not act:
        print(f"[{now} UTC] watch: активных сетапов нет", flush=True); return
    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print(f"[{now} UTC] watch: {len(act)} активных", flush=True)
    for k, prev in act.items():
        s = prev["sym"]; bx = f"{s.split('/')[0]}/USDT:USDT"
        try:
            dl = fetch(ex, bx, a.ltf, int(ENTRY_W_H * 60 / TF_MIN[a.ltf]) * 2)
            if len(dl) < 100: print(f"  [skip] {s}: {a.ltf}={len(dl)}", flush=True); continue
            r = light_state(prev, dl, a.ltf); update_state(prev, r, dl, a.ltf, now, s)
        except Exception as ex_:
            print(f"  [skip] {s}: {type(ex_).__name__} {ex_}", flush=True)
    save_and_report(state, a)


def run_loop(a):
    """Два цикла: full — после закрытия каждого 4h-бара (UTC 00/04/08/…, +3 мин); watch — каждые 15 мин."""
    last_full = None
    while True:
        now = pd.Timestamp.utcnow()
        bar_close = now.floor("4h")            # последнее закрытие 4h-бара
        due_full = (now - bar_close) >= pd.Timedelta(minutes=3) and (last_full is None or last_full < bar_close)
        try:
            if due_full:
                a.asof = None; main_scan(a); last_full = bar_close
            else:
                watch(a)
        except Exception as ex_:
            print(f"[loop] ошибка: {type(ex_).__name__} {ex_}", flush=True)
        # спать до следующей четверти часа + 20 с
        nxt = (pd.Timestamp.utcnow().floor("15min") + pd.Timedelta(minutes=15, seconds=20))
        time.sleep(max(30, (nxt - pd.Timestamp.utcnow()).total_seconds()))


if __name__ == "__main__":
    import sys as _sys
    if "--loop" in _sys.argv:
        _sys.argv.remove("--loop")
        ap0 = argparse.ArgumentParser(); ap0.add_argument("--ltf", default="15m"); ap0.add_argument("--pairs", type=int, default=150); ap0.add_argument("--draw", action="store_true")
        ap0.add_argument("--only-core", action="store_true"); ap0.add_argument("--asof", default=None); ap0.add_argument("--syms", default=None)
        ap0.add_argument("--universe", default="cache"); ap0.add_argument("--min_vol", type=float, default=2e6)
        run_loop(ap0.parse_args())
    elif "--watch" in _sys.argv:
        _sys.argv.remove("--watch")
        ap0 = argparse.ArgumentParser(); ap0.add_argument("--ltf", default="15m"); ap0.add_argument("--asof", default=None)
        watch(ap0.parse_args())
    else:
        main()
