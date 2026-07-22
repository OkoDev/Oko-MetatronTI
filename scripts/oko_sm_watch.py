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
    if not (in_zone or approach):
        return f"вне зоны (откат {retr:.2f})" if test else None

    pivots = _oko_pivots(df)
    wt = _wt_state(df)
    # схождения на ключевых fib
    conf_lines = []
    for f in (0.705, 0.786, 0.886):
        hits = _levels_near(fibp[f], df, st, pivots)
        if hits:
            conf_lines.append(f"  {f:g} ∩ " + " ∩ ".join(hits))
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
    if test:
        return msg
    key = f"okosm:{base}:{round(o_, 8)}:{round(e_, 8)}"
    if not _cooldown_ok(key):
        return None
    from oko_feed.alerts import send_tg
    send_tg(msg, channel="action")
    return f"ALERT {base} {dseg} retr={retr:.2f} conf={len(conf_lines)}"


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
