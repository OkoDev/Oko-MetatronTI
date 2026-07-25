# -*- coding: utf-8 -*-
"""OKO-SM ВАХТА — decision-support сторож на стеке Егора (23.07). НЕ торгует. ОТДЕЛЬНЫЙ.

Егор: «собирай как отдельный для тестов, а не как замену тому что есть». Разделение труда
(вердикт 2-дневной раскопки): бот несёт вахту по парам ГЛАЗАМИ Егора, решает Егор.

Стек (всё сверено с живым графиком 1:1): oko_sm_engine (значимая старшая нога, порт OKO-SM
v163) + OkoTrend порт (WT/медиана/дивергенции) + ТОЧНЫЕ пивоты OKO (S1/R1×2.003, D/W/M) +
кластер схождений (±0.3%: пивоты/FVG/полки/сетка соседнего импульса) + двухмасштабие
(senior vs internal). Алерт когда цена ПОДХОДИТ к OTE-зоне старшей ноги / вошла в неё —
с полным контекстом и развилкой Егора (откат→по тренду / пробой→слом).

Reuse: send_tg+conn (oko_feed), CORE (oi_fast_poller), BingX klines (phase_watch-паттерн).
pm2: --name oko-sm-watch · тест: python scripts/oko_sm_watch.py --test SOL
"""
import sys, json, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")
from datetime import datetime, timezone

import pandas as pd

from core.smc.oko_sm_engine import run_structure, current_leg

SCAN_SEC = 900            # 15 мин: 4h-ноги живут часами, подход ловим с запасом
COOLDOWN_SEC = 12 * 3600  # один алерт на (символ, нога)
APPROACH_PCT = 0.015      # «подходит»: цена в 1.5% от края зоны
TOL = 0.003               # кластер ±0.3%
BARS = 1000               # 4h истории (верифицировано: ≥1000 убирает холодный старт)


def _kl(base, interval="4h", lim=BARS):
    url = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
           f"&interval={interval}&limit={min(lim,1440)}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oko-watch"})
        d = json.load(urllib.request.urlopen(req, timeout=15)).get("data", [])
    except Exception:
        return None
    if not d:
        return None
    df = pd.DataFrame([(int(k["time"]), float(k["open"]), float(k["high"]), float(k["low"]),
                        float(k["close"])) for k in d],
                      columns=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    return df if len(df) >= 300 else None


def _wt_state(df):
    """OkoTrend порт: wt1/медиана/свежая дивергенция (≤10 бар)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    dd = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    wt1 = ((ap - esa) / (0.015 * dd)).ewm(span=21, adjust=False).mean()
    ma = wt1.ewm(span=200, adjust=False).mean()
    w = wt1.values; hv, lv = df["high"].values, df["low"].values
    divB = divS = False
    pb = pt = None
    for t in range(max(4, len(w) - 12), len(w)):
        w4, w3, w2, w1_, w0 = w[t-4], w[t-3], w[t-2], w[t-1], w[t]
        if w4 < w2 and w3 < w2 and w2 > w1_ and w2 > w0:
            if pt is not None and hv[t-2] > pt[1] and w2 < pt[0]:
                divS = True
            pt = (w2, hv[t-2])
        if w4 > w2 and w3 > w2 and w2 < w1_ and w2 < w0:
            if pb is not None and lv[t-2] < pb[1] and w2 > pb[0]:
                divB = True
            pb = (w2, lv[t-2])
    return {"wt": float(w[-1]), "ma": float(ma.iloc[-1]), "divB": divB, "divS": divS}


def _oko_pivots(df):
    """Текущие D/W/M пивоты по ТОЧНОЙ формуле OKO-SM (из ПРОШЛОГО завершённого периода)."""
    ts = pd.to_datetime(df["time"], unit="ms", utc=True)
    out = {}
    for rule, name in (("%Y-%m-%d", "D"), ("%G-%V", "W"), ("%Y-%m", "M")):
        key = ts.dt.strftime(rule)
        ks = key.unique()
        if len(ks) < 2:
            continue
        prev = df[key == ks[-2]]
        H, L, C = prev["high"].max(), prev["low"].min(), prev["close"].iloc[-1]
        pp = (H + L + C) / 3
        out[name] = {"PP": pp, "S1": pp*2.003-H, "S2": pp-(H-L), "S3": pp*2-(2*H-L),
                     "R1": pp*1.997-L, "R2": pp+(H-L), "R3": pp*2+(H-2*L)}
    return out


_W = {"W": 3.0, "M": 3.0, "D": 1.0, "сосед": 2.0, "FVG": 1.0, "полка": 0.5}


def _hit_weight(name):
    for k, w in _W.items():
        if name.startswith(k):
            return w
    return 0.5


def _levels_near(price, df, st, pivots):
    """Именованные источники в ±0.3% от price: пивоты / FVG / полки(len5) / сетка соседа."""
    hits = []
    for per, lv in pivots.items():
        for nm, v in lv.items():
            if abs(price - v) / price <= TOL:
                hits.append(f"{per}-{nm}({v:.6g})")
    hv, lvv = df["high"].values, df["low"].values
    for t in range(max(2, len(df) - 120), len(df)):
        if lvv[t] > hv[t-2] and abs(price - hv[t-2]) / price <= TOL:
            hits.append(f"FVG({hv[t-2]:.6g})")
        elif hv[t] < lvv[t-2] and abs(price - lvv[t-2]) / price <= TOL:
            hits.append(f"FVG({lvv[t-2]:.6g})")
    from core.smc.oko_sm_engine import _swings
    for conf_i, sw_i, p, is_top in _swings(df["high"], df["low"], 5)[-24:]:
        if abs(price - p) / price <= TOL:
            hits.append(f"полка({p:.6g})")
    # сетка соседнего импульса (последняя нога противоположного тренда)
    legs = st.leg_history
    cur = legs[-1]
    prev = None
    for i in range(len(legs) - 2, -1, -1):
        if legs[i] is not None and cur is not None and legs[i]["trend"] != cur["trend"]:
            prev = legs[i]; break
    if prev:
        po, pe = prev["origin"], prev["extreme"]
        for f in (0.0, 0.382, 0.5, 0.618, 0.705, 0.786, 1.0, -0.27, -0.62):
            lvl = pe - f * (pe - po)
            if lvl > 0 and abs(price - lvl) / price <= TOL:
                hits.append(f"сосед-fib{f:g}({lvl:.6g})")
                break
    return list(dict.fromkeys(hits))[:6]


def _store_screener(base, leg, px, retr, in_zone, approach, score, hits_by_fib, wt, st, fibp, noise):
    """Скринер-строка пары → screener_state (последний снапшот на символ). Читает :8010."""
    import sqlite3 as _sq
    hits_flat = sorted({h for hs in hits_by_fib.values() for h in hs},
                       key=lambda h: -_hit_weight(h))[:8]
    c = _sq.connect("subscriptions.db", timeout=5)
    c.execute("""CREATE TABLE IF NOT EXISTS screener_state(
        symbol TEXT PRIMARY KEY, ts INTEGER, trend TEXT, origin REAL, extreme REAL,
        px REAL, retr REAL, in_zone INTEGER, approach INTEGER, noise INTEGER,
        conf_score REAL, hits TEXT, wt REAL, wt_ma REAL, div INTEGER,
        itrend_sync INTEGER, fib618 REAL, fib705 REAL, fib786 REAL, fib100 REAL)""")
    long_ = leg["trend"] == "long"
    c.execute("INSERT OR REPLACE INTO screener_state VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (base, int(time.time()), leg["trend"], leg["origin"], leg["extreme"],
               px, round(float(retr), 4), int(in_zone), int(approach), int(noise),
               round(float(score), 2), json.dumps(hits_flat, ensure_ascii=False),
               round(wt["wt"], 1), round(wt["ma"], 1),
               int(wt["divB"] if long_ else wt["divS"]),
               int((st.itrend > 0) == long_),
               fibp[0.618], fibp[0.705], fibp[0.786], fibp[1.0]))
    c.commit()
    c.close()


def _cooldown_ok(key):
    from oko_feed.store import conn
    c = conn()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
        row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < COOLDOWN_SEC:
            return False
        c.execute("INSERT OR REPLACE INTO alert_log VALUES (?,?)", (key, int(time.time())))
        c.commit()
        return True
    finally:
        c.close()


def scan_one(base, test=False):
    df = _kl(base)
    if df is None:
        return None
    st = run_structure(df, record_legs=True)
    leg = current_leg(st)
    if leg is None:
        return "нет старшей ноги" if test else None
    o_, e_ = leg["origin"], leg["extreme"]
    px = float(df["close"].iloc[-1])
    span = e_ - o_
    long_ = leg["trend"] == "long"
    fibp = {f: e_ - f * span for f in (0.618, 0.705, 0.786, 0.886, 1.0)}
    z_edge, z_deep = fibp[0.618], fibp[0.886]
    # состояние подхода (LONG: цена падает к зоне сверху; SHORT зеркально — span<0 всё учитывает)
    if long_:
        in_zone = z_deep <= px <= z_edge
        approach = (not in_zone) and px > z_edge and (px - z_edge) / px <= APPROACH_PCT
        retr = (e_ - px) / span if span else 0
    else:
        in_zone = z_edge <= px <= z_deep
        approach = (not in_zone) and px < z_edge and (z_edge - px) / px <= APPROACH_PCT
        retr = (px - e_) / (o_ - e_) if span else 0
    # СКРИНЕР (26.07, Неделя-1 плана DC): метрики считаем ВСЕГДА (не только у зоны) и пишем
    # КАЖДУЮ пару в screener_state — :8010 отдаёт таблицей. Алерт-гейты ниже не тронуты.
    atr = float((df["high"] - df["low"]).rolling(20).mean().iloc[-1])
    noise = abs(span) < 4 * atr
    pivots = _oko_pivots(df)
    wt = _wt_state(df)
    conf_lines = []
    best_score = 0.0
    hits_by_fib = {}
    for f in (0.705, 0.786, 0.886):
        hits = _levels_near(fibp[f], df, st, pivots)
        hits_by_fib[f] = hits
        if hits:
            sc = sum(_hit_weight(h) for h in hits)
            best_score = max(best_score, sc)
            conf_lines.append(f"  {f:g} ∩ " + " ∩ ".join(hits))
    try:
        _store_screener(base, leg, px, retr, in_zone, approach, best_score,
                        hits_by_fib, wt, st, fibp, noise)
    except Exception as _se:
        print(f"[OKO-SM-WATCH] screener store {base}: {_se}")

    if not (in_zone or approach):
        return f"вне зоны (откат {retr:.2f})" if test else None
    if noise:
        return "нога < 4×ATR (шум)" if test else None
    # ГЕЙТ КАЧЕСТВА (Егор: «куча мусорных алертов не прокатит»): в зоне score≥3, на подходе ≥5
    need = 3.0 if in_zone else 5.0
    if best_score < need:
        return f"score {best_score:.1f} < {need} (слабое схождение)" if test else None
    itn = "синхрон" if (st.itrend > 0) == long_ else "коррекция (internal против)"
    div = "R+ свежая" if (wt["divB"] if long_ else wt["divS"]) else "нет"
    dseg = "LONG" if long_ else "SHORT"
    dt0 = datetime.fromtimestamp(int(df["time"].iloc[leg["origin_i"]])/1000, timezone.utc).strftime("%d.%m")
    dt1 = datetime.fromtimestamp(int(df["time"].iloc[leg["extreme_i"]])/1000, timezone.utc).strftime("%d.%m")
    state = "🎯 В OTE-ЗОНЕ" if in_zone else "→ подходит к зоне"
    msg = (f"🔭 <b>OKO-SM ВАХТА:</b> <code>{base}</code> 4h\n\n"
           f"Нога <b>{dseg}</b> {o_:.6g} → {e_:.6g} ({dt0}→{dt1}) · internal: {itn}\n"
           f"Цена {px:.6g} — <b>{state}</b> (откат {retr:.2f})\n"
           f"Зона: 0.618={fibp[0.618]:.6g} · 0.705={fibp[0.705]:.6g} · "
           f"0.786={fibp[0.786]:.6g} · слом(1.0)={fibp[1.0]:.6g}\n"
           + (("⭐ Схождения:\n" + "\n".join(conf_lines) + "\n") if conf_lines else "схождений в зоне нет\n")
           + f"WT {wt['wt']:+.0f} (медиана {wt['ma']:+.0f}) · див: {div}\n\n"
           f"<i>Развилка: откат от зоны → {dseg} по старшему на {e_:.6g} · "
           f"пробой {fibp[1.0]:.6g} → слом старшего</i>\n"
           f'📊 <a href="https://ru.tradingview.com/chart/?symbol=BINGX%3A{base}USDT.P">график</a>'
           f"\n\n#{base} #OKOSM_WATCH")
    png_bytes = None
    try:
        import asyncio as _aio
        from core.ui.chart_builder import build_signal_chart
        _ok = {"leg": (int(df["time"].iloc[leg["origin_i"]]), leg["origin"],
                       int(df["time"].iloc[leg["extreme_i"]]), leg["extreme"]),
               "zone": (fibp[0.618], fibp[0.886]),
               "levels": [(f, fibp[f], bool(hits_by_fib.get(f))) for f in (0.618, 0.705, 0.786)],
               "break": fibp[1.0]}
        png_bytes = _aio.run(build_signal_chart(f"{base}/USDT:USDT", tf="4h", bot=None,
                                                wave_overlay=True, okosm=_ok))
    except Exception as _ce:
        print(f"[OKO-SM-WATCH] chart {base}: {_ce}")
    png = None
    if png_bytes:
        import tempfile, os
        png = os.path.join(tempfile.gettempdir(), f"okosm_{base}.png")
        with open(png, "wb") as fh:
            fh.write(png_bytes)
    if png is None:
        try:
            png = _render_chart(base, df, leg, fibp, hits_by_fib, px)
        except Exception as _ce:
            print(f"[OKO-SM-WATCH] chart-fb {base}: {_ce}")
    cap = (f"🔭 <b>{base}</b> 4h · нога <b>{dseg}</b> {o_:.6g}→{e_:.6g} · <b>{state}</b> (откат {retr:.2f})\n"
           + ("⭐ " + conf_lines[0].strip() + "\n" if conf_lines else "")
           + f"WT {wt['wt']:+.0f}/мед {wt['ma']:+.0f} · див {div}\n"
           f"Откат от зоны → {dseg} на {e_:.6g} · пробой {fibp[1.0]:.6g} → слом\n#{base} #OKOSM")
    if test:
        return (png or "чарт не собрался") + "\n" + msg
    key = f"okosm:{base}:{round(o_, 8)}:{round(e_, 8)}"
    if not _cooldown_ok(key):
        return None
    sent = False
    if png:
        try:
            from oko_feed.alerts import send_tg_photo
            with open(png, "rb") as fh:
                sent = send_tg_photo(fh.read(), caption=cap, channel="action")
        except Exception as _pe:
            print(f"[OKO-SM-WATCH] photo {base}: {_pe}")
    if not sent:
        from oko_feed.alerts import send_tg
        send_tg(msg, channel="action")
    return f"ALERT {base} {dseg} retr={retr:.2f} score={best_score:.1f}"


def _render_chart(base, df, leg, fibp, hits_by_fib, px):
    """Свечи 4h (хвост) + нога + OTE-зона + fib-уровни. → путь PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import os, tempfile
    W = 160
    n = len(df)
    i0 = max(0, n - W)
    d = df.iloc[i0:].reset_index(drop=True)
    x = range(len(d))
    fig, ax = plt.subplots(figsize=(11, 5.6), facecolor="#0e1117")
    ax.set_facecolor("#0e1117")
    up = d["close"] >= d["open"]
    ax.vlines(x, d["low"], d["high"], color="#555", lw=0.7)
    ax.bar(x, (d["close"] - d["open"]).abs(), 0.62,
           bottom=d[["open", "close"]].min(axis=1),
           color=["#26a69a" if u else "#ef5350" for u in up])
    # нога
    ox, ex = leg["origin_i"] - i0, leg["extreme_i"] - i0
    ox = max(0, ox); ex = max(0, ex)
    ax.plot([ox, ex], [leg["origin"], leg["extreme"]], color="#ff9800", lw=2.5, zorder=5)
    # зона + уровни
    lo, hi = sorted((fibp[0.618], fibp[0.886]))
    ax.axhspan(lo, hi, color="#ffd54f", alpha=0.13)
    for f in (0.618, 0.705, 0.786, 1.0):
        v = fibp[f]
        strong = bool(hits_by_fib.get(f))
        ax.axhline(v, color="#ffd54f" if f != 1.0 else "#e91e63",
                   lw=2.0 if strong else 0.8, ls="-" if strong else "--", alpha=0.9)
        ax.text(len(d) + 1, v, f"{f:g} {v:.6g}" + (" *" if strong else ""),
                color="#ffd54f" if f != 1.0 else "#e91e63", fontsize=8, va="center")
    ax.plot(len(d) - 1, px, "o", color="#fff", ms=5)
    ax.set_title(f"{base} 4h · OKO-SM ВАХТА", color="#ddd", fontsize=11)
    ax.tick_params(colors="#777", labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#333")
    ax.set_xlim(-2, len(d) + 14)
    fig.tight_layout()
    out = os.path.join(tempfile.gettempdir(), f"okosm_{base}.png")
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def main():
    if "--test" in sys.argv:
        base = sys.argv[sys.argv.index("--test") + 1].upper()
        print(scan_one(base, test=True) or "нет данных")
        return
    from oi_fast_poller import CORE
    print(f"[OKO-SM-WATCH] вахта глазами Егора: {len(CORE)} монет · скан {SCAN_SEC}с · "
          f"нога(50/5)+OTE+пивоты OKO+кластер+WT/див · НЕ торгует")
    while True:
        try:
            hits = []
            for b in CORE:
                r = scan_one(b)
                if r:
                    hits.append(r)
                time.sleep(0.3)
            if hits:
                print(f"[OKO-SM-WATCH] {time.strftime('%H:%M:%S')}: {hits}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[OKO-SM-WATCH] err: {e}")
        time.sleep(SCAN_SEC)


if __name__ == "__main__":
    main()
