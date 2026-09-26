# -*- coding: utf-8 -*-
"""OKO-CONTEXT-LOCATOR — стенд проверки модели «где мы сейчас» (Егор 22-23.06).

НЕ прод, НЕ новые формулы: композиция эталонов zigzag_atr + find_setups_zz + build_ote.
Цель: проверить, «видит» ли движок те же зоны, что Егор размечает руками (SYN/XLM).

Модель (memory/htf_significant_context_over_local.md):
  1. Значимый импульс = тот, в чью OTE цена ещё НЕ возвращалась (untested = первый ретест).
  2. «Где мы» = untested-OTE, содержащая ТЕКУЩУЮ цену (direction сетапа = контекст).
  3. Карта untested-OTE по ТФ = сетка целей/разворотов в обе стороны (premium/discount).

Запуск:
  python scripts/oko_context_locator.py --sym SYN-USDT
  python scripts/oko_context_locator.py --sym XLM-USDT
"""
import asyncio, os, sys, argparse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

from core.smc.smc_engine import zigzag_atr, find_setups_zz
from core.infra.data_collector import RealTimeData

# limit на ТФ (баров). Daily большой — чтобы захватить старый значимый импульс.
TF_LIMIT = {"1d": 700, "1D": 700, "4h": 1000, "1h": 1000, "15m": 1000, "5m": 1000}
FRESH_BARS = 12   # «первый ретест»: цена не входила в зону раньше, чем за FRESH_BARS до конца
# ZigZag: depth per-ТФ (config), dev — АДАПТИВНЫЙ (как wave_chart_lab: под ~N свингов).
# Статичный dev не универсален (XLM нужен dev=2, W dev=4) → адаптив даёт верный масштаб.
ZZ_DEPTH = {"1h": 8}     # depth из config; остальные дефолт 11
ADAPT_TARGET = 12        # целевое число zz-точек на окне (меньше = крупнее импульсы)
# Путь B: значимая структура через swings(length) — масштаб от ОКНА свинга (эталон OKO-SM)
USE_SWINGS = False       # A (adaptive zigzag) ближе для W; B (swings) ловит дно но дробит верх
SWING_LEN = {"1d": 30, "4h": 40, "1h": 50, "15m": 50, "5m": 50}  # окно значимого свинга per-ТФ


def _adaptive_dev(d, depth: int) -> float:
    from core.smc.smc_engine import zigzag_atr as _zz
    best_dev, best = 3.0, 1e9
    for dv in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        try:
            nn = len(_zz(d, depth, dv))
        except Exception:
            continue
        if abs(nn - ADAPT_TARGET) < best:
            best, best_dev = abs(nn - ADAPT_TARGET), dv
    return best_dev


def analyze_tf(df: pd.DataFrame, tf: str) -> list[dict]:
    """Все сетапы ТФ с пометкой untested/где-цена (на готовых эталонах)."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if USE_SWINGS:
        from core.smc.smc_engine import confirmed_swings
        _sw = confirmed_swings(d, SWING_LEN.get(tf, 50))   # значимые swing-точки (окно=length)
        zz = [(d.index[i], p) for i, p, _k in _sw if i < len(d.index)]
    else:
        _dp = ZZ_DEPTH.get(tf, 11)
        zz = zigzag_atr(d, depth=_dp, dev_mult=_adaptive_dev(d, _dp))
    setups = find_setups_zz(zz, d)
    # ЭКСТРЕМУМ-ИМПУЛЬСЫ (Егор 23.06): вся нога от значимого LOW к HIGH (крайние, не соседние)
    try:
        from core.smc.smc_engine import _zz_typed, build_ote
        _ppos = {ts: i for i, ts in enumerate(d.index)}
        # окно АКТУАЛЬНОГО тренда = от последнего ПРОТИВОПОЛОЖНОГО CHoCH-разворота (не фикс-окно)
        _chs = [(_ppos.get(s.get("choch_ts")), s["direction"]) for s in (setups or [])
                if s.get("kind") == "CHoCH" and _ppos.get(s.get("choch_ts")) is not None]
        if _chs:
            _li, _ld = _chs[-1]
            _opp = [i for i, dd in _chs if dd != _ld and i < _li]
            _wmin = _opp[-1] if _opp else max(0, _li - 400)
        else:
            _wmin = max(0, len(d) - 400)
        _P = [(_ppos.get(ts), p, k) for ts, p, k in _zz_typed(zz)
              if _ppos.get(ts) is not None and _ppos.get(ts) >= _wmin]
        _L = [(i, p) for i, p, k in _P if k == "L"]; _H = [(i, p) for i, p, k in _P if k == "H"]

        def _mk(ai, ap, bi, bp):    # a=начало, b=конец ноги
            o = build_ote(bp, ap)   # 0=конец, 1=начало → long(bull)/short(bear) по знаку
            o["from"] = (d.index[ai], ap); o["to"] = (d.index[bi], bp)
            o["choch_ts"] = d.index[bi]; o["broken_level"] = None; o["broken_ts"] = None
            o["kind"] = "IMP"; o["struct"] = "bull" if bp > ap else "bear"
            return o

        _ex = []
        if _L and _H:
            _ml = min(_L, key=lambda x: x[1]); _ha = [h for h in _H if h[0] > _ml[0]]
            if _ha:    # восходящий: глоб. LOW → макс HIGH после него
                _mh = max(_ha, key=lambda x: x[1]); _ex.append(_mk(_ml[0], _ml[1], _mh[0], _mh[1]))
            _mh2 = max(_H, key=lambda x: x[1]); _la = [l for l in _L if l[0] > _mh2[0]]
            if _la:    # нисходящий: глоб. HIGH → мин LOW после него
                _ml2 = min(_la, key=lambda x: x[1]); _ex.append(_mk(_mh2[0], _mh2[1], _ml2[0], _ml2[1]))
        setups = _ex + (setups or [])
    except Exception as _e:
        import traceback; print("[extreme]", _e); traceback.print_exc()
    if not setups:
        return []
    pos = {ts: i for i, ts in enumerate(d.index)}
    hi = d["high"].values; lo = d["low"].values
    n = len(d)
    cur_lo, cur_hi, cur_cl = lo[-1], hi[-1], d["close"].values[-1]
    out = []
    for s in setups:
        olo, ohi = s["ote"]
        ci = pos.get(s["choch_ts"])
        if ci is None:
            continue
        # заходы цены в OTE-зону ПОСЛЕ конца импульса (бар пересёк [olo,ohi])
        visits = []  # индексы баров в зоне
        for j in range(ci + 1, n):
            if hi[j] >= olo and lo[j] <= ohi:
                visits.append(j)
        first_touch = visits[0] if visits else None
        # «тронута раньше» = был заход за пределами свежего окна
        touched_before = first_touch is not None and first_touch < n - FRESH_BARS
        price_in_now = (cur_hi >= olo and cur_lo <= ohi)
        # untested = до свежего окна цена в зоне НЕ была (или вовсе впервые сейчас)
        untested = not touched_before
        # размах импульса (значимость по величине ноги)
        span = abs(s["to"][1] - s["from"][1])
        span_pct = span / s["from"][1] * 100 if s["from"][1] else 0.0
        # premium/discount относительно equilibrium импульса (level 0.5)
        eq = s["levels"][0.5]
        zone = "premium" if cur_cl > eq else "discount"
        # ИНВАЛИДАЦИЯ: цена пробила 0.79 в сторону отката → импульс мёртв (Егор 23.06)
        l079 = s["levels"].get(0.79); inv = False
        if l079 is not None:
            if s["direction"] == "short":
                _sg = hi[ci + 1:]; inv = bool(len(_sg)) and float(_sg.max()) > l079
            else:
                _sg = lo[ci + 1:]; inv = bool(len(_sg)) and float(_sg.min()) < l079
        # цена в диапазоне ОТКАТА ноги (между концом 0.0 и началом 1.0) — «откат идёт, ждём OTE»
        _l0 = s["levels"].get(0.0); _l1 = s["levels"].get(1.0)
        price_in_leg = bool(_l0 and _l1) and (min(_l0, _l1) <= cur_cl <= max(_l0, _l1))
        out.append({
            "tf": tf, "dir": s["direction"], "kind": s["kind"], "struct": s["struct"],
            "ote_lo": olo, "ote_hi": ohi, "eq": eq,
            "from_i": pos.get(s["from"][0]), "to_i": pos.get(s["to"][0]),
            "choch_i": pos.get(s["choch_ts"]),
            "broken_level": s.get("broken_level"),
            "broken_i": pos.get(s.get("broken_ts")),
            "from_ts": str(s["from"][0])[:16], "from_p": s["from"][1],
            "to_ts": str(s["to"][0])[:16], "to_p": s["to"][1],
            "choch_ts": str(s["choch_ts"])[:16],
            "span_pct": span_pct, "n_visits": len(visits),
            "untested": untested, "price_in_now": price_in_now, "zone_now": zone,
            "invalidated": inv, "price_in_leg": price_in_leg,
            "ote705": s["levels"][0.705], "ote062": s["levels"][0.62],
            "fib": {f: s["levels"].get(f) for f in (0.0, 0.5, 0.62, 0.705, 0.79, 1.0, -0.62, -1.0, -1.618)},
        })
    return out


def find_entry(all_setups: dict, tf_base: str, price: float, n_base: int):
    """Актуальный reversal-вход: свежий CHoCH базового ТФ у цены → entry/SL/цель/R:R."""
    base = all_setups.get(tf_base, [])
    chochs = [s for s in base if s["kind"] == "CHoCH" and s.get("to_i") is not None]
    near = [s for s in chochs
            if s["to_i"] >= n_base - 150 and abs(s["ote705"] - price) / price <= 0.25]
    if not near:
        return None
    es = near[-1]
    is_short = es["dir"] == "short"
    entry = es["ote705"]
    sl = es["from_p"] * (1.002 if is_short else 0.998)
    cand = []
    for _tf, ss in all_setups.items():
        for s in ss:
            if not s["untested"]:
                continue
            mid = (s["ote_lo"] + s["ote_hi"]) / 2
            if (is_short and mid < entry) or (not is_short and mid > entry):
                cand.append((abs(mid - entry), mid, _tf))
    if not cand:
        return None
    cand.sort()
    _, tgt, ttf = cand[0]
    rr = abs(tgt - entry) / abs(entry - sl) if entry != sl else 0.0
    return {"dir": es["dir"], "entry": entry, "sl": sl,
            "target": tgt, "target_tf": ttf, "rr": rr}


def locate(all_setups: dict[str, list[dict]], price: float) -> None:
    """Печать: где мы (untested OTE содержит цену) + карта untested-целей по ТФ."""
    print(f"\n  ТЕКУЩАЯ ЦЕНА: {price:.6f}")
    print("\n  === ГДЕ МЫ СЕЙЧАС (untested-OTE, содержащая цену) ===")
    found_here = False
    for tf in all_setups:
        for s in all_setups[tf]:
            if s["price_in_now"] and s["untested"]:
                found_here = True
                ctx = "SHORT-контекст (premium, OTE near high)" if s["dir"] == "short" \
                      else "LONG-контекст (discount, OTE near low)"
                print(f"  [{tf:>3}] {ctx}")
                print(f"        OTE {s['ote_lo']:.6f}–{s['ote_hi']:.6f}  (0.705={s['ote705']:.6f}, 0.62={s['ote062']:.6f})")
                print(f"        импульс {s['struct']}/{s['kind']} {s['from_p']:.6f}→{s['to_p']:.6f} "
                      f"(размах {s['span_pct']:.1f}%, заходов={s['n_visits']}) с {s['from_ts']}")
                print(f"        зона={s['zone_now']} eq={s['eq']:.6f}")
    if not found_here:
        print("  (нет untested-OTE на текущей цене — цена между зонами)")

    print("\n  === КАРТА untested-OTE (цели/адреса, цена НЕ внутри) ===")
    rows = []
    for tf in all_setups:
        for s in all_setups[tf]:
            if s["untested"] and not s["price_in_now"]:
                mid = (s["ote_lo"] + s["ote_hi"]) / 2
                side = "ВВЕРХ" if mid > price else "ВНИЗ"
                dist = abs(mid - price) / price * 100
                rows.append((dist, tf, s, side, mid))
    rows.sort()
    for dist, tf, s, side, mid in rows[:12]:
        tgt = "LONG-зона" if s["dir"] == "long" else "SHORT-зона"
        print(f"  [{tf:>3}] {side:>5} {dist:5.1f}%  {tgt:10} OTE {s['ote_lo']:.6f}–{s['ote_hi']:.6f} "
              f"(0.705={s['ote705']:.6f})  импульс {s['span_pct']:.0f}% заходов={s['n_visits']}")


def render_context_chart(df_base, all_setups, price, sym, tf_base, path, zoom=0):
    """МОЙ слой (НЕ эталонный chart_builder): свечи + untested-OTE + слом/вход.
    zoom>0 → последние zoom свечей (крупный акцент на слом+вход)."""
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    d = df_base.copy(); d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close", "volume"]]
    n_full = len(d)
    offset = 0
    if zoom and n_full > zoom:
        offset = n_full - zoom
        d = d.iloc[-zoom:]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(marketcolors=mc, facecolor="#131722", figcolor="#131722",
                               gridcolor="#1e2130", gridstyle="--", y_on_right=True,
                               rc={"text.color": "#d1d4dc", "ytick.color": "#787b86",
                                   "xtick.color": "#787b86"})
    fig, axes = mpf.plot(d, type="candle", style=style, volume=True, returnfig=True,
                         figsize=(16, 9), tight_layout=True,
                         title=f"{sym} {tf_base} — OKO  (цена={price:.5g})")
    ax = axes[0]; n = len(d)
    pmin, pmax = float(d["low"].min()), float(d["high"].max())

    def _x(full_i):
        return max(0, min(full_i - offset, n - 1))

    for tf, setups in all_setups.items():
        for s in setups:
            if not s["untested"]:
                continue
            lo, hi = s["ote_lo"], s["ote_hi"]
            if hi < pmin or lo > pmax:
                continue
            col = "#ef5350" if s["dir"] == "short" else "#26a69a"
            here = s["price_in_now"]
            ax.axhspan(lo, hi, color=col, alpha=0.28 if here else 0.10, zorder=0)
            tag = "★ГДЕ МЫ" if here else "цель"
            ax.text(n * 0.01, hi, f"{tag} {tf} {s['dir']} {s['span_pct']:.0f}%",
                    color=col, fontsize=8, va="bottom", ha="left", zorder=6,
                    bbox=dict(facecolor="#131722", edgecolor=col, alpha=0.8,
                              boxstyle="round,pad=0.15"))
    # СЛОЙ ВХОДА: последний reversal-CHoCH базового ТФ → слом/вход/SL/цель/R:R
    base_setups = all_setups.get(tf_base, [])
    chochs = [s for s in base_setups if s["kind"] == "CHoCH" and s.get("to_i") is not None]
    # слом В НАПРАВЛЕНИИ контекста старшего (htf dir) у цены — продолжение тренда
    # (не broken_level в OTE: тот брал противоположный long-разворот). Слом «от LL» для short-4h.
    near = [s for s in chochs if s["to_i"] >= n_full - 150
            and s["dir"] == htf["dir"] and abs(s["ote705"] - price) / price <= 0.3]
    es = near[-1] if near else None
    if es is not None:
        is_short = es["dir"] == "short"
        entry = es["ote705"]; sl = es["from_p"] * (1.002 if is_short else 0.998)
        ecol = "#ef5350" if is_short else "#26a69a"
        # импульс — тонкая нога-контекст from→to
        if es.get("from_i") is not None and es.get("to_i") is not None and es["to_i"] >= offset:
            fx, tx = _x(es["from_i"]), _x(es["to_i"])
            ax.plot([fx, tx], [es["from_p"], es["to_p"]], color="#ffd700",
                    linewidth=1.4, alpha=0.7, zorder=4)
        # ★ САМ СЛОМ структуры (CHoCH/BOS) + ЛИНИЯ СЛОМА (пробитый уровень)
        bl = es.get("broken_level"); ci = es.get("choch_i"); bi = es.get("broken_i")
        if bl is not None and ci is not None and ci >= offset:
            cix = _x(ci); bix = _x(bi) if bi is not None else 0
            ax.plot([bix, n - 1], [bl, bl], color="#ff9800", linewidth=1.8, zorder=5)
            ax.text(bix, bl, " линия слома", color="#ff9800", fontsize=9,
                    va="bottom", ha="left", zorder=7)
            ax.axvline(cix, color="#ff9800", linewidth=1.0, linestyle=":", alpha=0.6, zorder=4)
            ax.scatter([cix], [bl], color="#ff9800", s=140, marker="X",
                       edgecolors="#fff", linewidths=0.6, zorder=8)
            ax.text(cix, bl, f"  ★СЛОМ {es['kind']}", color="#ff9800", fontsize=11,
                    va="top", ha="left", zorder=8,
                    bbox=dict(facecolor="#131722", edgecolor="#ff9800", boxstyle="round,pad=0.2"))
        x0 = n * 0.40
        ax.plot([x0, n - 1], [entry, entry], color=ecol, linewidth=1.8, zorder=6)
        ax.text(x0, entry, f" ВХОД {'SHORT' if is_short else 'LONG'} {entry:.5g}",
                color="#fff", fontsize=11, va="bottom", ha="left", zorder=7,
                bbox=dict(facecolor=ecol, edgecolor="none", boxstyle="round,pad=0.25"))
        ax.plot([x0, n - 1], [sl, sl], color="#ff1744", linewidth=1.3, linestyle="--", zorder=6)
        ax.text(x0, sl, f" SL {sl:.5g}", color="#ff1744", fontsize=10, va="top", zorder=7)
        cand = []
        for _tf, ss in all_setups.items():
            for s in ss:
                if not s["untested"]:
                    continue
                mid = (s["ote_lo"] + s["ote_hi"]) / 2
                if (is_short and mid < entry) or (not is_short and mid > entry):
                    cand.append((abs(mid - entry), mid, _tf))
        if cand:
            cand.sort()
            _, tgt, ttf = cand[0]
            rr = abs(tgt - entry) / abs(entry - sl) if entry != sl else 0
            in_win = pmin <= tgt <= pmax
            ty = tgt if in_win else (pmax if tgt > pmax else pmin)
            extra = "" if in_win else (" ↑вне окна" if tgt > pmax else " ↓вне окна")
            ax.plot([x0, n - 1], [ty, ty], color="#00e676", linewidth=1.6, zorder=6)
            ax.text(x0, ty, f" ЦЕЛЬ {ttf} {tgt:.5g}  R:R={rr:.1f}{extra}", color="#fff",
                    fontsize=11, va="top" if in_win else "bottom", ha="left", zorder=7,
                    bbox=dict(facecolor="#00897b", edgecolor="none", boxstyle="round,pad=0.25"))
            ax.annotate("", xy=(n - 1, ty), xytext=(n - 1, entry),
                        arrowprops=dict(arrowstyle="-|>", color="#00e676", lw=2.2), zorder=7)
    else:
        ax.text(n * 0.5, price, "нет свежего reversal у цены — ЖДЁМ слом",
                color="#ffd700", fontsize=12, va="bottom", ha="center", zorder=7,
                bbox=dict(facecolor="#131722", edgecolor="#ffd700", boxstyle="round,pad=0.3"))
    ax.axhline(price, color="#ffffff", linestyle=":", linewidth=1.2, zorder=5)
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)


async def _load_df(rt, sym: str, tf: str):
    df = await rt.get_ohlcv(sym, timeframe=tf, limit=min(TF_LIMIT.get(tf, 800), 1000))
    if df is None or df.empty:
        return None
    if "time" in df.columns:
        df = df.set_index(pd.to_datetime(df["time"], unit="ms"))
    return df


def render_oko(db, h, sig, sym, zone_tf, break_tf, price, path, zoom=160):
    """MTF-вложенность: OTE-зона СТАРШЕГО (импульс) + слом/вход/SL/цели МЛАДШЕГО (detect_oko_ote)."""
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    d = db.copy(); d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close", "volume"]]
    nf = len(d); off = 0
    if zoom and nf > zoom:
        off = nf - zoom; d = d.iloc[-zoom:]
    pos = {ts: i for i, ts in enumerate(db.index)}
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(marketcolors=mc, facecolor="#131722", figcolor="#131722",
                               gridcolor="#1e2130", gridstyle="--", y_on_right=True,
                               rc={"text.color": "#d1d4dc", "ytick.color": "#787b86",
                                   "xtick.color": "#787b86"})
    fig, axes = mpf.plot(d, type="candle", style=style, volume=True, returnfig=True,
                         figsize=(16, 9), tight_layout=True,
                         title=f"{sym}  {break_tf}←{zone_tf}  detect_oko_ote  (цена={price:.5g})")
    ax = axes[0]; n = len(d)

    def _x(i):
        return max(0, min((i if i is not None else 0) - off, n - 1))

    # OTE-зона СТАРШЕГО (импульс старшего ТФ = контекст)
    if h:
        olo, ohi = h["ote"]
        hcol = "#26a69a" if h["direction"] == "long" else "#ef5350"
        ax.axhspan(olo, ohi, color=hcol, alpha=0.16, zorder=0)
        ax.text(n * 0.01, ohi, f" OTE {zone_tf} {h['direction']} (импульс старшего)",
                color=hcol, fontsize=10, va="bottom", ha="left", zorder=6,
                bbox=dict(facecolor="#131722", edgecolor=hcol, boxstyle="round,pad=0.2"))
    # сигнал detect_oko_ote (слом/вход младшего)
    if sig is not None:
        is_short = sig.direction == "short"
        ecol = "#ef5350" if is_short else "#26a69a"
        x0 = n * 0.40
        try:
            ci = pos.get(pd.to_datetime(sig.choch_ts))
            if ci is not None and ci >= off:
                ax.axvline(_x(ci), color="#ff9800", linewidth=1.0, linestyle=":", alpha=0.7, zorder=4)
                ax.text(_x(ci), price, " ★слом мл.", color="#ff9800", fontsize=10, rotation=90,
                        va="bottom", zorder=7)
        except Exception:
            pass
        ax.plot([x0, n - 1], [sig.entry, sig.entry], color=ecol, linewidth=1.9, zorder=6)
        ax.text(x0, sig.entry, f" ВХОД {'SHORT' if is_short else 'LONG'} {sig.entry:.5g}  RR={sig.rr}",
                color="#fff", fontsize=11, va="bottom", ha="left", zorder=7,
                bbox=dict(facecolor=ecol, edgecolor="none", boxstyle="round,pad=0.25"))
        ax.plot([x0, n - 1], [sig.sl, sig.sl], color="#ff1744", linewidth=1.3, linestyle="--", zorder=6)
        ax.text(x0, sig.sl, f" SL {sig.sl:.5g}", color="#ff1744", fontsize=10, va="top", zorder=7)
        for tp, lbl in (sig.targets or [])[:3]:
            ax.plot([x0, n - 1], [tp, tp], color="#00e676", linewidth=1.3, zorder=6)
            ax.text(x0, tp, f" {lbl} {tp:.5g}", color="#fff", fontsize=9, va="bottom", ha="left",
                    zorder=7, bbox=dict(facecolor="#00897b", edgecolor="none", boxstyle="round,pad=0.2"))
    else:
        ax.text(n * 0.5, price, "detect_oko_ote: нет свежего сетапа (ждём слом младшего в OTE старшего)",
                color="#ffd700", fontsize=11, va="bottom", ha="center", zorder=7,
                bbox=dict(facecolor="#131722", edgecolor="#ffd700", boxstyle="round,pad=0.3"))
    ax.axhline(price, color="#ffffff", linestyle=":", linewidth=1.2, zorder=5)
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)


async def _oko(sym: str, zone_tf: str, break_tf: str):
    """MTF-вложенность через detect_oko_ote (эталон): импульс старший + слом младший."""
    from core.infra.data_collector import RealTimeData
    from core.smc.oko_ote import detect_oko_ote
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    rt = RealTimeData()
    dz = await _load_df(rt, sym, zone_tf)
    db = await _load_df(rt, sym, break_tf)
    await rt.close()
    if dz is None or db is None:
        print("нет данных"); return
    price = float(db["close"].iloc[-1])
    htf = find_setups_zz(zigzag_atr(dz), dz)
    h = htf[-1] if htf else None
    if h:
        olo, ohi = h["ote"]
        print(f"OTE СТАРШЕГО [{zone_tf}] {h['direction']}: {olo:.6g}–{ohi:.6g} "
              f"(импульс {h['from'][1]:.6g}→{h['to'][1]:.6g})")
    sig = None
    try:
        sig = detect_oko_ote(sym, dz, db, zone_tf, break_tf, only_latest=True, min_confs=0)
    except Exception as e:
        import traceback; print("detect_oko_ote error:", e); traceback.print_exc()
    if sig is not None:
        print(f"СИГНАЛ {sig.direction}: вход={sig.entry:.6g} SL={sig.sl:.6g} TP={sig.tp:.6g} "
              f"RR={sig.rr} depth={sig.depth} confs[{sig.zone_ts}]")
    else:
        print("detect_oko_ote: нет свежего сетапа (ждём слом младшего в OTE старшего)")
    path = f"e:/tmp/oko_{sym}_{break_tf}from{zone_tf}.png"
    try:
        render_oko(db, h, sig, sym, zone_tf, break_tf, price, path)
        print(f"CHART → {path}")
    except Exception as e:
        import traceback; print("render error:", e); traceback.print_exc()


def render_synth(db, htf, es, sym, zone_tf, break_tf, price, path, zoom=220, all_setups=None):
    """СИНТЕЗ: ЗНАЧИМЫЙ untested-импульс старшего (OTE) + слом/вход младшего внутри неё."""
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    d = db.copy(); d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close", "volume"]]
    nf = len(d)
    import numpy as _np
    pos = {ts: i for i, ts in enumerate(db.index)}
    from core.smc.smc_engine import zigzag_atr as _zza, find_setups_zz as _fsz, _zz_typed as _zzt
    _zz = _zza(db.copy())
    _typed = _zzt(_zz)
    _struct_setups = _fsz(_zz, db)   # КАНОНИЧЕСКИЙ детектор (тот же, что красит BOS/CHoCH ниже)
    # КОНЕЦ значимого импульса на break_tf (нужно и для фибо-диагонали, и для слома):
    # позиция экстремума-старта/конца импульса по СОВПАДЕНИЮ цены на break_tf-серии
    _imp_sp = htf.get("from_p"); _imp_ep = htf.get("to_p")
    _arr_s = db["high"].values if htf["dir"] == "short" else db["low"].values
    _arr_e = db["low"].values if htf["dir"] == "short" else db["high"].values
    _ist = int(_np.argmin(_np.abs(_arr_s - _imp_sp))) if _imp_sp else 0
    _iend = int(_np.argmin(_np.abs(_arr_e - _imp_ep))) if _imp_ep else nf - 1
    # СЛОМ структуры (метод Егора, 24.06: «импульс вверх → слом структуры вниз, импульс вниз →
    # слом структуры вверх») — НЕ отдельный алгоритм (был баг: бил по «глобальному экстремуму
    # ретрейсмента», находил слом не там, см. фидбэк по AIO), а первый bull/bear-слом из
    # КАНОНИЧЕСКОГО find_setups_zz ПОСЛЕ конца импульса (_iend), направление противоположно
    # импульсу: bull (пробой high вверх) после нисходящего импульса, bear после восходящего.
    _want_struct = "bear" if htf["dir"] == "long" else "bull"
    _slom = next((s for s in _struct_setups if s["struct"] == _want_struct
                  and (pos.get(s["choch_ts"]) or 0) >= _iend), None)
    # АДАПТИВНОЕ окно: расширить влево чтобы влез КОНЕЦ импульса (откуда считается слом),
    # иначе линия слома и контекст за кадром (метод Егора — широкий обзор)
    _start = nf - zoom if (zoom and nf > zoom) else 0
    _start = min(_start, max(0, _iend - 10))   # окно включает конец импульса (старт откатa)
    off = _start; d = d.iloc[off:]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(marketcolors=mc, facecolor="#131722", figcolor="#131722",
                               gridcolor="#1e2130", gridstyle="--", y_on_right=True,
                               rc={"text.color": "#d1d4dc", "ytick.color": "#787b86",
                                   "xtick.color": "#787b86"})
    fig, axes = mpf.plot(d, type="candle", style=style, volume=True, returnfig=True,
                         figsize=(16, 9), tight_layout=True, panel_ratios=(7, 1.2),
                         title=f"{sym}  {break_tf}←{zone_tf}  СИНТЕЗ (значимый untested + слом)  (цена={price:.5g})")
    ax = axes[0]; n = len(d)
    for _ax in fig.axes:                       # даты ГОРИЗОНТАЛЬНО (не повёрнуты)
        for _lbl in _ax.get_xticklabels():
            _lbl.set_rotation(0); _lbl.set_ha("center")
    pmin, pmax = float(d["low"].min()), float(d["high"].max())

    def _x(i):
        return max(0, min((i or 0) - off, n - 1))

    def _cy(v):
        # ax.text() НЕ обрезается осями (clip_on=False по умолчанию) — если зона старшего
        # ТФ (OTE/уровень) далеко за пределами окна break_tf (напр. 1d-импульс GRT с HH=0.255,
        # а 4h-окно живёт в 0.018-0.045), подпись на реальной цене раздувает bbox_inches="tight"
        # до тысяч пикселей (24.06: GRT 1674×9830 вместо ~1674×900). Подпись прижимаем к краю окна.
        return min(max(v, pmin), pmax)

    olo, ohi = htf["ote_lo"], htf["ote_hi"]
    hcol = "#26a69a" if htf["dir"] == "long" else "#ef5350"
    ax.axhspan(olo, ohi, color=hcol, alpha=0.18, zorder=0)
    ax.text(n * 0.01, _cy(ohi), f" OTE {zone_tf} {htf['dir']} ЗНАЧИМЫЙ untested "
            f"(импульс {htf['span_pct']:.0f}%, заходов={htf['n_visits']})",
            color=hcol, fontsize=10, va="bottom", ha="left", zorder=6,
            bbox=dict(facecolor="#131722", edgecolor=hcol, boxstyle="round,pad=0.2"))

    # ФИБО htf-импульса (0.5/0.62/0.705/0.79/1.0 откат + -1/-1.618 расширения-цели)
    _fib = htf.get("fib", {})
    _fstyle = {0.0: ("#8a8a8a", "-", "0"), 0.5: ("#cccccc", "-", "0.5"),
               0.62: ("#26a69a", ":", "0.62"), 0.705: ("#ffa726", "-", "0.705"),
               0.79: ("#ef5350", ":", "0.79"), 1.0: ("#2196f3", "-", "1.0"),
               -0.62: ("#26a69a", "--", "-0.62 цель"), -1.0: ("#26a69a", "--", "-1.0 цель"),
               -1.618: ("#26a69a", "--", "-1.618 цель")}
    # _ist/_iend (экстремумы старта/конца импульса на break_tf) уже посчитаны выше для окна
    _fx0 = _x(_ist)
    # импульс HH→LL диагональю (как dashed в эталоне OKO-SM)
    # диагональ рисуем ТОЛЬКО если вершина импульса в кадре (иначе HH далеко вверху
    # ломает вертикальный масштаб — напр. 1d-импульс GRT с HH=0.255)
    if _imp_sp and pmin * 0.85 <= _imp_sp <= pmax * 1.15:
        ax.plot([_x(_ist), _x(_iend)], [_imp_sp, _imp_ep], color="#ffd700", linewidth=1.6,
                linestyle="--", alpha=0.85, zorder=5)
    for _ff, (_fc, _fls, _flb) in _fstyle.items():
        _lv = _fib.get(_ff)
        if _lv is None or not (pmin * 0.92 <= _lv <= pmax * 1.08):
            continue
        ax.plot([_fx0, n - 1], [_lv, _lv], color=_fc, linestyle=_fls, linewidth=1.3, alpha=0.9, zorder=4)
        # _cy: уровень допущен с запасом 8% за pmin/pmax (видно ЛИНИЮ чуть выше/ниже кадра),
        # но подпись без зажима повисает в воздухе ОТДЕЛЬНО от рамки графика (24.06, AIO
        # 5m←1h: «фиба разная» — 0.705/0.62 плавали над канвой) — тот же класс бага что и canvas-раздув.
        ax.text(n - 1 + n * 0.005, _cy(_lv), f"{_flb} ({_lv:.5g})", color="#fff", fontsize=9,
                fontweight="bold", ha="left", va="center", zorder=8,
                bbox=dict(facecolor=_fc, edgecolor="none", alpha=0.9, boxstyle="round,pad=0.15"))

    # все ДРУГИЕ значимые untested-зоны (обе стороны) — где ещё бывают сетапы (long зелёные / short красные)
    if all_setups:
        for _tf, _ss in all_setups.items():
            for _s in _ss:
                if not _s["untested"] or _s is htf:
                    continue
                _lo, _hi = _s["ote_lo"], _s["ote_hi"]
                if _hi < pmin or _lo > pmax:
                    continue
                _c = "#26a69a" if _s["dir"] == "long" else "#ef5350"
                ax.axhspan(_lo, _hi, color=_c, alpha=0.07, zorder=0)
                ax.text(n * 0.99, (_lo + _hi) / 2, f"{_tf} {_s['dir']} {_s['span_pct']:.0f}% ",
                        color=_c, fontsize=7, va="center", ha="right", zorder=6, alpha=0.85)

    # ── СТРУКТУРА break_tf: зигзаг HH/HL/LH/LL + сломы BOS/CHoCH (как эталон Егора) ──
    # _zz/_typed/_struct_setups уже посчитаны в начале функции (один калькулятор, не дублируем)
    try:
        _seq = [(pos.get(ts), p, t) for ts, p, t in _typed if pos.get(ts) is not None]
        _vis = [(i, p, t) for i, p, t in _seq if i >= off]
        if len(_vis) >= 2:
            ax.plot([_x(i) for i, _, _ in _vis], [p for _, p, _ in _vis],
                    color="#ffffff", linestyle=":", linewidth=1.0, alpha=0.65, zorder=4)
        prev_h = prev_l = None
        for i, p, t in _seq:
            if t == "H":
                lab = "HH" if (prev_h is not None and p > prev_h) else "LH"; prev_h = p; pc = "#ef5350"
            else:
                lab = "HL" if (prev_l is not None and p > prev_l) else "LL"; prev_l = p; pc = "#26a69a"
            if i >= off:
                ax.text(_x(i), p, lab, color=pc, fontsize=7, fontweight="bold",
                        ha="center", va="bottom" if t == "H" else "top", zorder=7)
        # сломы: горизонт. отрезок от пробитой вершины (broken_ts) до точки слома (choch_ts)
        for s in _struct_setups:
            bl = s.get("broken_level"); ci = pos.get(s["choch_ts"]); bi = pos.get(s.get("broken_ts"))
            if bl is None or ci is None or ci < off:
                continue
            bull = s["struct"] == "bull"
            bc = "#26a69a" if bull else "#ef5350"
            arrow = "↑" if bull else "↓"
            ls = "--" if s["kind"] == "CHoCH" else (0, (2, 3))
            x1 = _x(bi) if bi is not None else _x(ci)
            ax.plot([x1, _x(ci)], [bl, bl], color=bc, linestyle=ls, linewidth=1.0, alpha=0.75, zorder=5)
            ax.text((x1 + _x(ci)) / 2, _cy(bl), f"{s['kind']}{arrow}", color=bc, fontsize=7,
                    fontweight="bold", ha="center", va="bottom", zorder=7)
    except Exception as _e:
        import traceback; print("[структура]", _e); traceback.print_exc()

    # ── ПОЛНАЯ SMC (как wave_chart_lab): OB + FVG + EQH/EQL ──
    try:
        from core.smc.smc_engine import (detect_order_blocks, detect_fvg,
                                         detect_equal_levels, detect_structure_breaks)
        _d2 = db.copy(); _d2.columns = [c.lower() for c in _d2.columns]
        _d2 = _d2.reset_index(drop=True)
        _brks = detect_structure_breaks(_d2, length=5)
        for _b in detect_order_blocks(_d2, _brks):
            if _b.mitigated_idx != -1 or _b.left_idx < off:
                continue
            _col = "#26a69a" if _b.kind == "bull" else "#ef5350"
            x0b = _x(_b.left_idx)
            ax.add_patch(plt.Rectangle((x0b, _b.bottom), (n - 1) - x0b, _b.top - _b.bottom,
                         facecolor=_col, alpha=0.09, edgecolor=_col, linewidth=0.6, zorder=1))
            ax.annotate("OB", ((x0b + n) / 2, (_b.top + _b.bottom) / 2), color=_col,
                        fontsize=6, fontweight="bold", va="center", ha="center", zorder=6, alpha=0.8)
        for _f in detect_fvg(_d2)[-15:]:
            if _f[5] is not None or _f[0] < off:
                continue
            _top, _bot, _kind = _f[1], _f[2], _f[3]
            if abs((_top + _bot) / 2 - price) / price > 0.04:
                continue
            _fc = "#42a5f5" if _kind == "bull" else "#ff7043"
            x0f = _x(_f[0])
            ax.add_patch(plt.Rectangle((x0f, min(_top, _bot)), (n - 1) - x0f, abs(_top - _bot),
                         facecolor=_fc, alpha=0.12, edgecolor=_fc, linewidth=0.5, zorder=1, hatch="///"))
        for _eq in detect_equal_levels(_d2)[-8:]:
            _i1, _ep1, _i2, _ekind = _eq[0], _eq[1], _eq[2], _eq[4]
            _aft = _d2.iloc[_i2 + 1:]
            _swept = len(_aft) and ((_ekind == "EQH" and _aft["high"].max() > _ep1 * 1.001)
                                    or (_ekind == "EQL" and _aft["low"].min() < _ep1 * 0.999))
            if _swept:
                continue
            ax.axhline(_ep1, color="#ab47bc", linestyle=(0, (1, 2)), linewidth=0.9, alpha=0.6, zorder=2)
            if _i1 >= off:
                ax.annotate(_ekind, (_x(_i1), _ep1), color="#ab47bc", fontsize=7,
                            fontweight="bold", zorder=6)
    except Exception as _e:
        import traceback; print("[SMC]", _e); traceback.print_exc()

    # ЛИНИЯ СЛОМА (метод Егора) — _slom уже найден в начале функции: ПЕРВЫЙ структурный
    # слом КАНОНИЧЕСКОГО find_setups_zz после конца импульса (_iend), направление
    # противоположно импульсу (24.06 фидбэк по AIO: «ты слом не там ищешь» — старый код
    # искал «глобальный экстремум ретрейсмента» отдельным алгоритмом и ловил произвольную,
    # часто позднюю точку вместо ПЕРВОГО реального структурного слома; теперь переиспользуем
    # тот же детектор, что красит BOS/CHoCH ниже — один калькулятор, не два).
    if _slom is not None:
        _bl = _slom.get("broken_level"); _ci = pos.get(_slom["choch_ts"]); _bi = pos.get(_slom.get("broken_ts"))
        if _bl is not None and _ci is not None:
            x1 = _x(_bi) if _bi is not None else _x(_ci)
            ax.plot([x1, _x(_ci)], [_bl, _bl], color="#ff9800", linewidth=2.4, zorder=6)
            ax.scatter([_x(_ci)], [_bl], color="#ff9800", s=130, marker="X",
                       edgecolors="#fff", linewidths=0.7, zorder=8)
            _plbl = "HH" if _slom["struct"] == "bull" else "LL"
            ax.text(_x(_ci), _cy(_bl), f" ★СЛОМ {break_tf} ({_plbl} {_bl:.5g})", color="#ff9800",
                    fontsize=10, va="bottom", ha="left", zorder=8)

    if es is not None:
        is_short = es["dir"] == "short"
        ecol = "#ef5350" if is_short else "#26a69a"
        entry = es["ote705"]; sl = es["from_p"] * (1.002 if is_short else 0.998)
        x0 = _x(ci) if ci is not None else int(n * 0.62)   # боксы/линии от МОМЕНТА входа (слома)
        # ЦЕЛЬ = фибо-расширение htf (-0.62/-1.0/-1.618) в сторону входа
        _fb = htf.get("fib", {}); tgt = None
        for _ext in (-0.62, -1.0, -1.618):
            _lv = _fb.get(_ext)
            if _lv is not None and ((_lv > entry) if not is_short else (_lv < entry)):
                tgt = _lv; break
        if tgt is None:
            tgt = entry * (1.05 if not is_short else 0.95)
        rr = abs(tgt - entry) / abs(entry - sl) if entry != sl else 0.0
        # PROFIT-бокс (вход→TP, зелёный) + RISK-бокс (вход→SL, красный) = TradingView Position
        ax.add_patch(plt.Rectangle((x0, min(entry, tgt)), (n - 1) - x0, abs(tgt - entry),
                     facecolor="#26a69a", alpha=0.16, edgecolor="#26a69a", linewidth=1.0, zorder=2))
        ax.add_patch(plt.Rectangle((x0, min(entry, sl)), (n - 1) - x0, abs(entry - sl),
                     facecolor="#ef5350", alpha=0.16, edgecolor="#ef5350", linewidth=1.0, zorder=2))
        # линии + ЦЕНЫ у правого края (вход/TP/SL)
        ax.plot([x0, n - 1], [entry, entry], color="#ffffff", linewidth=1.6, zorder=6)
        ax.text(n - 1, _cy(entry), f" ВХОД {'SHORT' if is_short else 'LONG'} {entry:.6g}",
                color="#fff", fontsize=10, va="center", ha="left", zorder=8,
                bbox=dict(facecolor=ecol, edgecolor="none", boxstyle="round,pad=0.2"))
        ax.plot([x0, n - 1], [tgt, tgt], color="#26a69a", linewidth=1.5, zorder=6)
        ax.text(n - 1, _cy(tgt), f" TP {tgt:.6g}  R:R={rr:.1f}", color="#fff", fontsize=10,
                va="center", ha="left", zorder=8,
                bbox=dict(facecolor="#00897b", edgecolor="none", boxstyle="round,pad=0.2"))
        ax.plot([x0, n - 1], [sl, sl], color="#ff1744", linewidth=1.5, linestyle="--", zorder=6)
        ax.text(n - 1, _cy(sl), f" SL {sl:.6g}", color="#fff", fontsize=10, va="center", ha="left",
                zorder=8, bbox=dict(facecolor="#c62828", edgecolor="none", boxstyle="round,pad=0.2"))
    else:
        ax.text(n * 0.5, price, f"ждём слом {break_tf} в OTE старшего",
                color="#ffd700", fontsize=12, va="bottom", ha="center", zorder=7,
                bbox=dict(facecolor="#131722", edgecolor="#ffd700", boxstyle="round,pad=0.3"))
    ax.axhline(price, color="#ffffff", linestyle=":", linewidth=1.2, zorder=5)
    # вертикальный отступ от краёв (график не прижат, линия на LL видна)
    _rng = (pmax - pmin) or 1.0
    ax.set_ylim(pmin - _rng * 0.13, pmax + _rng * 0.07)
    # правое поле 20% — свечи влево, справа место (как TradingView)
    for _ax in fig.axes:
        _ax.set_xlim(-1, (n - 1) + n * 0.20)
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)


async def _synth_one(rt, sym, zone_tf, break_tf):
    """Один проход synth → (htf, es, db, price) или None."""
    dz = await _load_df(rt, sym, zone_tf)
    db = await _load_df(rt, sym, break_tf)
    if dz is None or db is None:
        return None
    price = float(db["close"].iloc[-1])
    zs = analyze_tf(dz, zone_tf)
    _now = [s for s in zs if s["price_in_now"] and not s["invalidated"]]
    _leg = [s for s in zs if s["price_in_leg"] and not s["invalidated"]]
    htf = (max(_now, key=lambda s: s["span_pct"]) if _now
           else max(_leg, key=lambda s: s["span_pct"]) if _leg else None)
    if htf is None:
        return None
    olo, ohi = htf["ote_lo"], htf["ote_hi"]
    brk = analyze_tf(db, break_tf); nb = len(db)
    cand = [s for s in brk if s["kind"] == "CHoCH" and s.get("to_i") is not None
            and s["to_i"] >= nb - 150 and olo <= s["ote705"] <= ohi]
    es = cand[-1] if cand else None
    return (htf, es, db, price)


async def _scan_synth(scan_n: int, zone_tf: str, break_tf: str):
    """Скан пар → synth-сетапы с РЕАЛЬНЫМ сломом младшего в OTE значимого импульса старшего."""
    import sqlite3
    from core.infra.data_collector import RealTimeData
    try:
        db = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
        rows = db.execute("SELECT DISTINCT symbol FROM simulated_trades "
                          "ORDER BY created_at DESC LIMIT 150").fetchall()
        db.close()
    except Exception as e:
        print("DB error:", e); rows = []
    pairs, seen = [], set()
    for (s,) in rows:
        base = s.split("/")[0].replace(":USDT", "").replace("USDT", "")
        p = base + "USDT"
        if base and p not in seen:
            seen.add(p); pairs.append(p)
    pairs = pairs[:scan_n]
    rt = RealTimeData()
    print(f"SCAN-SYNTH {len(pairs)} пар: значимый untested {zone_tf}-импульс (цена внутри) + слом {break_tf} в OTE...")
    hits = []
    for p in pairs:
        try:
            r = await _synth_one(rt, p, zone_tf, break_tf)
        except Exception:
            continue
        if r is None:
            continue
        htf, es, dbf, price = r
        if es is not None:
            prox = abs(es["ote705"] - price) / price
            hits.append((prox, p, htf, es, dbf, price))
            print(f"  ✓ {p:13} htf {htf['dir']} OTE-импульс {htf['span_pct']:.0f}% | "
                  f"слом {break_tf} {es['dir']} вход={es['ote705']:.6g} (цена_откл {prox*100:.1f}%)")
    await rt.close()
    if not hits:
        print("Нет пар с реальным сломом в OTE значимого импульса сейчас."); return
    hits.sort()   # ближе цена к входу = свежее
    _, bp, bhtf, bes, bdb, bpr = hits[0]
    path = f"e:/tmp/synth_{bp}_{break_tf}from{zone_tf}.png"
    try:
        render_synth(bdb, bhtf, bes, bp, zone_tf, break_tf, bpr, path)
        print(f"\n  BEST: {bp}  {bes['dir']}  →  {path}")
    except Exception as e:
        import traceback; print("render error:", e); traceback.print_exc()


async def _oko_synth(sym: str, zone_tf: str, break_tf: str):
    """СИНТЕЗ: untested-выбор ЗНАЧИМОГО импульса старшего (не htf[-1]) + слом младшего в OTE."""
    from core.infra.data_collector import RealTimeData
    rt = RealTimeData()
    dz = await _load_df(rt, sym, zone_tf)
    db = await _load_df(rt, sym, break_tf)
    await rt.close()
    if dz is None or db is None:
        print("нет данных"); return
    price = float(db["close"].iloc[-1])
    zone_setups = analyze_tf(dz, zone_tf)
    # ЗНАЧИМЫЙ = ЖИВОЙ; ПРИОРИТЕТ: цена в OTE (готов) → иначе в ноге (ждём откат); крупнейший span
    _now = [s for s in zone_setups if s["price_in_now"] and not s["invalidated"]]
    _leg = [s for s in zone_setups if s["price_in_leg"] and not s["invalidated"]]
    htf = (max(_now, key=lambda s: s["span_pct"]) if _now
           else max(_leg, key=lambda s: s["span_pct"]) if _leg else None)
    if htf is None:
        print(f"нет ЖИВОГО значимого импульса [{zone_tf}] (все инвалид/цена вне ноги)"); return
    olo, ohi = htf["ote_lo"], htf["ote_hi"]
    print(f"ЗНАЧИМЫЙ импульс [{zone_tf}] {htf['dir']}: OTE {olo:.6g}–{ohi:.6g} "
          f"(импульс {htf['from_p']:.6g}→{htf['to_p']:.6g}, {htf['span_pct']:.0f}%, заходов={htf['n_visits']}, "
          f"цена_внутри={htf['price_in_now']})")
    brk = analyze_tf(db, break_tf); nb = len(db)
    cand = [s for s in brk if s["kind"] == "CHoCH" and s.get("to_i") is not None
            and s["to_i"] >= nb - 150 and olo <= s["ote705"] <= ohi]
    es = cand[-1] if cand else None
    if es is not None:
        print(f"СЛОМ {break_tf} в OTE: {es['dir']} вход={es['ote705']:.6g} SL≈{es['from_p']:.6g}")
    else:
        print(f"нет свежего слома {break_tf} в OTE старшего — ЖДЁМ (дисциплина)")
    _sn = sym.replace("/", "").replace(":", "")
    path = f"e:/tmp/synth_{_sn}_{break_tf}from{zone_tf}.png"
    try:
        render_synth(db, htf, es, sym, zone_tf, break_tf, price, path,
                     zoom=500, all_setups={zone_tf: zone_setups, break_tf: brk})
        print(f"CHART → {path}")
    except Exception as e:
        import traceback; print("render error:", e); traceback.print_exc()


async def _scan(scan_n: int):
    """Сканировать активные пары → найти актуальные reversal-входы (15m) → график лучшего."""
    import sqlite3
    from core.infra.data_collector import RealTimeData
    try:
        db = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
        rows = db.execute("SELECT DISTINCT symbol FROM simulated_trades "
                          "ORDER BY created_at DESC LIMIT 150").fetchall()
        db.close()
    except Exception as e:
        print("DB error:", e); rows = []
    pairs, seen = [], set()
    for (s,) in rows:
        base = s.split("/")[0].replace(":USDT", "").replace("USDT", "")
        p = base + "USDT"
        if base and p not in seen:
            seen.add(p); pairs.append(p)
    pairs = pairs[:scan_n]
    rt = RealTimeData()
    print(f"SCAN {len(pairs)} пар на актуальный reversal-вход (15m, R:R≥1.5)...")
    hits = []
    for p in pairs:
        asx = {}; n15 = 0; pr = None; df15 = None
        for tf in ["4h", "1h", "15m"]:
            try:
                df = await rt.get_ohlcv(p, timeframe=tf, limit=1000)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            if "time" in df.columns:
                df = df.set_index(pd.to_datetime(df["time"], unit="ms"))
            if pr is None:
                pr = float(df["close"].iloc[-1])
            asx[tf] = analyze_tf(df, tf)
            if tf == "15m":
                n15 = len(df); df15 = df
        if pr is None or df15 is None:
            continue
        e = find_entry(asx, "15m", pr, n15)
        if e and e["rr"] >= 1.5:
            hits.append((e["rr"], p, pr, e, asx, df15))
            print(f"  ✓ {p:13} {e['dir']:5} entry={e['entry']:.6g} SL={e['sl']:.6g} "
                  f"цель[{e['target_tf']}]={e['target']:.6g} R:R={e['rr']:.1f}")
    await rt.close()
    if not hits:
        print("Нет пар со свежим reversal-входом сейчас (R:R≥1.5)."); return
    # приоритет: цена ещё у входа (≤10%, свежий слом виден), затем max R:R
    hits.sort(key=lambda x: (abs(x[2] - x[3]["entry"]) / x[3]["entry"] > 0.10, -x[0]))
    _, bp, bpr, be, basx, bdf = hits[0]
    path = f"e:/tmp/entry_{bp}_15m.png"
    try:
        render_context_chart(bdf, basx, bpr, bp, "15m", path, zoom=140)
        print(f"\n  BEST: {bp}  {be['dir']}  R:R={be['rr']:.1f}  →  {path}")
    except Exception as e:
        import traceback; print("render error:", e); traceback.print_exc()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", type=str, default="SYNUSDT")
    ap.add_argument("--tfs", type=str, default="1d,4h,1h,15m,5m")
    ap.add_argument("--chart", action="store_true", help="нарисовать untested-OTE на свечах")
    ap.add_argument("--chart-tf", type=str, default="1d", help="базовый ТФ для графика")
    ap.add_argument("--scan", action="store_true", help="найти пары с актуальным reversal-входом")
    ap.add_argument("--scan-n", type=int, default=25, help="сколько пар сканировать")
    ap.add_argument("--oko", action="store_true", help="MTF detect_oko_ote: импульс старший + слом младший")
    ap.add_argument("--synth", action="store_true", help="СИНТЕЗ: untested-выбор значимого импульса + слом младшего")
    ap.add_argument("--zone", type=str, default="1h", help="старший ТФ (импульс/OTE)")
    ap.add_argument("--brk", type=str, default="15m", help="младший ТФ (слом/вход)")
    args = ap.parse_args()
    tfs = [t.strip() for t in args.tfs.split(",")]

    if args.scan and not args.synth:
        await _scan(args.scan_n)
        return
    if args.oko:
        await _oko(args.sym.replace("-", "").upper(), args.zone, args.brk)
        return
    if args.synth:
        if args.scan:
            await _scan_synth(args.scan_n, args.zone, args.brk)
        else:
            await _oko_synth(args.sym.replace("-", "").upper(), args.zone, args.brk)
        return

    sym = args.sym.replace("-", "").upper()
    rt = RealTimeData()
    print(f"OKO-CONTEXT-LOCATOR  sym={sym}  tfs={tfs}")
    all_setups = {}
    dfs = {}
    price = None
    for tf in tfs:
        try:
            df = await rt.get_ohlcv(sym, timeframe=tf, limit=min(TF_LIMIT.get(tf, 800), 1000))
        except Exception as e:
            print(f"  [{tf}] fetch error: {e}")
            continue
        if df is None or df.empty:
            print(f"  [{tf}] нет данных")
            continue
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], unit="ms"))  # ms→datetime (фикс 1970)
        if price is None:
            price = float(df["close"].iloc[-1])
        setups = analyze_tf(df, tf)
        all_setups[tf] = setups
        dfs[tf] = df
        unt = sum(1 for s in setups if s["untested"])
        print(f"  [{tf:>3}] баров={len(df)}  сетапов={len(setups)}  untested={unt}  "
              f"диапазон {df.index[0].date()}…{df.index[-1].date()}")
    await rt.close()

    if price is None:
        print("Нет данных ни по одному ТФ"); return
    locate(all_setups, price)

    if args.chart and args.chart_tf in dfs:
        path = f"e:/tmp/locator_{sym}_{args.chart_tf}.png"
        try:
            render_context_chart(dfs[args.chart_tf], all_setups, price, sym, args.chart_tf, path)
            print(f"\n  CHART → {path}")
        except Exception as e:
            import traceback; print(f"  CHART error: {e}"); traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
