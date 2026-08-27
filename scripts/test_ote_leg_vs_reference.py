# -*- coding: utf-8 -*-
"""НОГА OTE: детектор против ЭТАЛОНА (07.08, подозрение Егора «ZZ и верность ноги/зоны»).

Два независимых определителя ноги:
  A) ДЕТЕКТОР ote: zigzag_atr(depth,dev) → select_significant_impulse  (то, чем торгует ote_nested)
  B) ЭТАЛОН: run_structure(swing_len=50, internal_len=5) → current_leg  (порт индикатора Егора 1:1,
     верифицирован метками живого графика: BTC 15/15, ETH 13/13, SOL 93%)

Меряем: как часто совпадает НАПРАВЛЕНИЕ, насколько расходятся origin/extreme и — главное —
ПЕРЕСЕКАЮТСЯ ЛИ OTE-зоны (0.618-0.786 отката). Если зоны не пересекаются, детектор
торгует ДРУГУЮ ногу, и весь ote-эдж мерился не там."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.smc_engine import zigzag_atr, select_significant_impulse
from core.smc.oko_sm_engine import run_structure, current_leg
DB = "ohlcv_cache.db"


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def ote_zone(origin, extreme, is_long):
    """OTE 0.618-0.786 отката ноги. LONG: откат вниз от extreme к origin."""
    if origin is None or extreme is None or origin == extreme:
        return None
    rng = abs(extreme - origin)
    if is_long:
        return (extreme - 0.786 * rng, extreme - 0.618 * rng)
    return (extreme + 0.618 * rng, extreme + 0.786 * rng)


def overlap(z1, z2):
    if not z1 or not z2:
        return None
    lo = max(z1[0], z2[0]); hi = min(z1[1], z2[1])
    if hi <= lo:
        return 0.0
    w = min(z1[1] - z1[0], z2[1] - z2[0])
    return (hi - lo) / w if w > 0 else 0.0


t0 = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>2000 ORDER BY n DESC LIMIT 12",
                                (t0,)).fetchall()]
c.close()
print(f"монет {len(syms)} · ТФ 4h · окно эталона 1000 баров · срез каждые 40 баров\n")
tot = both = dir_ok = 0
ov = []; dorig = []; dext = []
examples = []
for si, sym in enumerate(syms):
    d = load(sym, "4h", t0)
    if len(d) < 1200:
        continue
    n_sym = 0
    for i in range(1050, len(d), 40):          # причинно: только прошлые бары
        win = d.iloc[max(0, i - 1000):i + 1].reset_index(drop=True)
        tot += 1; n_sym += 1
        # A) детектор ote
        legA = None; zA_native = None
        try:
            zz = zigzag_atr(win, depth=11, dev_mult=3.0)
            imp = select_significant_impulse(win, zz, current_price=float(win.close.iloc[-1]))
            if imp:
                # 07.08: реальные ключи — from/to/direction, и готовая зона в 'ote'
                # from/to = КОРТЕЖИ (индекс, цена) — не скаляры (07.08: float(кортеж) падал,
                # и bare except прятал это; 624 среза дали 0 сравнений)
                _f, _t = imp.get("from"), imp.get("to")
                o = _f[1] if isinstance(_f, (list, tuple)) and len(_f) > 1 else _f
                e = _t[1] if isinstance(_t, (list, tuple)) and len(_t) > 1 else _t
                dr = str(imp.get("direction") or "").lower()
                if o is not None and e is not None:
                    legA = {"origin": float(o), "extreme": float(e),
                            "long": ("long" in dr or "up" in dr) or (float(e) > float(o))}
                _z = imp.get("ote")
                if isinstance(_z, (list, tuple)) and len(_z) >= 2:
                    zA_native = (min(float(_z[0]), float(_z[1])), max(float(_z[0]), float(_z[1])))
                elif isinstance(_z, dict):
                    _lo, _hi = _z.get("lo"), _z.get("hi")
                    if _lo and _hi:
                        zA_native = (min(float(_lo), float(_hi)), max(float(_lo), float(_hi)))
        except Exception:
            pass
        # B) эталон
        legB = None
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
            cl = current_leg(st)
            if cl:
                legB = {"origin": float(cl["origin"]), "extreme": float(cl["extreme"]),
                        "long": cl["trend"] == "long"}
        except Exception:
            pass
        if not legA or not legB:
            continue
        both += 1
        same = legA["long"] == legB["long"]
        dir_ok += int(same)
        # зона детектора — РОДНАЯ, если он её отдал (так торгует бот); иначе считаем сами
        zA = zA_native or ote_zone(legA["origin"], legA["extreme"], legA["long"])
        zB = ote_zone(legB["origin"], legB["extreme"], legB["long"])
        o_ = overlap(zA, zB)
        if o_ is not None:
            ov.append(o_)
        px = float(win.close.iloc[-1])
        if px > 0:
            dorig.append(abs(legA["origin"] - legB["origin"]) / px * 100)
            dext.append(abs(legA["extreme"] - legB["extreme"]) / px * 100)
        if len(examples) < 6 and o_ is not None and o_ < 0.01:
            examples.append((sym.split("/")[0], legA, legB, zA, zB))
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:10} срезов={n_sym}")
print(f"\n═══ РЕЗУЛЬТАТ: {tot} срезов, оба дали ногу в {both} ═══")
if both:
    print(f"  СОВПАДЕНИЕ НАПРАВЛЕНИЯ: {100*dir_ok/both:.1f}%  ({dir_ok}/{both})")
if ov:
    a = np.array(ov)
    print(f"  ПЕРЕСЕЧЕНИЕ OTE-ЗОН: медиана {np.median(a)*100:.1f}% · среднее {a.mean()*100:.1f}%")
    print(f"    зоны НЕ пересекаются вовсе: {100*(a<0.01).mean():.1f}% случаев")
    print(f"    пересечение >50%:           {100*(a>0.5).mean():.1f}% случаев")
if dorig:
    print(f"  расхождение origin: медиана {np.median(dorig):.2f}% от цены")
    print(f"  расхождение extreme: медиана {np.median(dext):.2f}% от цены")
if examples:
    print("\n  ── примеры полного расхождения зон ──")
    for s, A, B, zA, zB in examples:
        print(f"    {s:8} детектор: {'LONG ' if A['long'] else 'SHORT'} "
              f"нога {A['origin']:.6g}→{A['extreme']:.6g} зона {zA[0]:.6g}-{zA[1]:.6g}")
        print(f"    {'':8} ЭТАЛОН:   {'LONG ' if B['long'] else 'SHORT'} "
              f"нога {B['origin']:.6g}→{B['extreme']:.6g} зона {zB[0]:.6g}-{zB[1]:.6g}")
