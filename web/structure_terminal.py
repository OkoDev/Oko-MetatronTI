# -*- coding: utf-8 -*-
"""STRUCTURE TERMINAL — развязанный live-терминал структуры рынка (24.07, Егор «полноценный
терминал, а не TG-лента»; «дашборд мёртв из-за прокси/лупов»).

Отдельный ЛЁГКИЙ процесс (порт :8010). НОЛЬ зависимости от oko-bot / :8000 / прокси / скан-лупов:
читает самодостаточные движки (marketcap_engine — доминации+ротация) + phase_state. Данные
лёгкие (CMC + Binance ticker), поэтому жив даже когда бот перезапускается / прокси выключены.

Отдаёт: /api/structure (JSON, кэш 45с) + / (self-render HTML-кокпит, поллинг 30с).
Запуск: python web/structure_terminal.py · pm2 --name structure-term (autorestart). Открыть :8010.
"""
import sys, sqlite3, time, json, urllib.request, asyncio, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from aiohttp import web

from core.context.marketcap_engine import live_dominance, rotation_now

PORT = 8010
_DB = "subscriptions.db"
_cache = {"ts": 0.0, "data": None}
_TTL = 45.0


def _phase():
    try:
        c = sqlite3.connect(_DB)
        r = c.execute("SELECT ts, phase, side, detail FROM phase_state WHERE level='macro' "
                      "ORDER BY ts DESC LIMIT 1").fetchone()
        c.close()
        if r:
            return {"ts": r[0], "phase": r[1], "side": r[2], "detail": r[3]}
    except Exception:
        pass
    return None


def _build():
    now = time.time()
    if now - _cache["ts"] < _TTL and _cache["data"] is not None:
        return _cache["data"]
    dom = None; rot = None
    try:
        dom = live_dominance()
    except Exception as e:
        print(f"[STRUCT] dominance err: {e}")
    try:
        rot = rotation_now()
    except Exception as e:
        print(f"[STRUCT] rotation err: {e}")
    data = {"ts": int(now), "dominance": dom, "rotation": rot, "phase": _phase()}
    _cache["ts"] = now; _cache["data"] = data
    return data


async def api(_req):
    return web.json_response(_build())


def _cluster_map(rows):
    """КЛАСТЕР: сколько монет прямо сейчас дают сигнал В ТУ ЖЕ СТОРОНУ и находятся в зоне/подходе.
    Наш замер: одиночный сигнал PF 0.67, кластер ≥2 монет — 2.24. Скринер сортировал по score
    одной монеты, из-за чего одиночка с высоким score обходила кластерный сетап (аудит 18.08)."""
    act = {"long": [], "short": []}
    for r in rows:
        if (r.get("in_zone") or r.get("approach")) and r.get("trend") in act:
            act[r["trend"]].append(r["symbol"])
    return act


def _screener_rows(limit=60):
    try:
        c = sqlite3.connect(_DB)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM screener_state ORDER BY in_zone DESC, approach DESC, conf_score DESC "
            "LIMIT ?", (limit,)).fetchall()]
        c.close()
        return rows
    except Exception:
        return []


# 🗣️ СЛОВАРЬ (редакция Егора 24.08): обычная форма — РОСТ / ПАДЕНИЕ, экстремальная — ПАМП / ДАМП.
# «Залив» и «пролив» из проекта убраны: их понимали в трёх разных смыслах (направление,
# падение, массовость) и читали задом наперёд. Метрика считает массовое ПАДЕНИЕ
# (WT<−60 = перепроданность), которое фейд и покупает.
_BREADTH_HI = 61        # порог из замера: ≥61 монет за 24ч → 4h-фейд PF 1.62 → 4.22 (p=0.00026)


def _breadth_now():
    """ШИРИНА ПАДЕНИЯ — сколько монет ОДНОВРЕМЕННО падает (фейд-состояние) (4h: ATRTrend↑ + WT<−60).
    Единственная метрика с доказанным множителем, а на экране её не было. Мгновенный срез
    пишем в БД → через сутки появится честное скользящее окно 24ч (как в замере)."""
    coins = _fetch_snap()
    now = int(time.time())
    syms = []
    for s, rec in coins.items():
        w = (rec.get("wt") or {}).get("4h") or {}
        if (w.get("atr") or 0) > 0 and w.get("wt1") is not None and w["wt1"] < -60:
            syms.append(s.split("/")[0])
    n_now = len(syms)
    n24 = None
    try:
        c = sqlite3.connect(_DB, timeout=5)
        c.execute("""CREATE TABLE IF NOT EXISTS breadth_log(
            ts INTEGER PRIMARY KEY, n INTEGER, syms TEXT, universe INTEGER)""")
        last = c.execute("SELECT MAX(ts) FROM breadth_log").fetchone()[0] or 0
        if now - last >= 300:            # пишем не чаще раза в 5 минут
            c.execute("INSERT OR REPLACE INTO breadth_log VALUES (?,?,?,?)",
                      (now, n_now, json.dumps(syms[:200]), len(coins)))
            c.commit()
        rows = c.execute("SELECT syms FROM breadth_log WHERE ts > ?", (now - 86400,)).fetchall()
        if rows:
            uniq = set()
            for (js,) in rows:
                try:
                    uniq.update(json.loads(js) or [])
                except Exception:
                    pass
            n24 = len(uniq)             # РАЗНЫХ монет за окно 24ч — как в замере
        c.close()
    except Exception as e:
        print(f"[BREADTH] {e}")
    return {"now": n_now, "day": n24, "universe": len(coins), "hi": _BREADTH_HI,
            "wide": bool((n24 or n_now) >= _BREADTH_HI), "syms": syms[:24], "ts": now}


async def api_breadth(_req):
    """GET /api/breadth — ширина падения: сейчас и уникальных монет за 24ч."""
    return web.json_response(_breadth_now())


def _plan_trade(r, of=None):
    """План сделки из данных скринера: вход, стоп ЗА СТРУКТУРУ, цель по ближайшему магниту.
    Ничего не выдумываем: стоп — за конец ноги OKO-SM (fib100) или за уровень поддержки/
    сопротивления, цель — ближайший уровень по ходу. Косты считаем сразу в % от стопа —
    именно они решают, жив ли эдж (37% стопа на 15m против 4% на 1d)."""
    px = r.get("px") or 0
    if not px:
        return None
    long_ = r.get("trend") == "long"
    origin = r.get("origin") or 0          # начало ноги OKO-SM
    extreme = r.get("extreme") or 0        # экстремум ноги — естественная цель возврата
    sup, res = r.get("sup_lvl") or 0, r.get("res_lvl") or 0
    # Торгуем ОТКАТ ноги: стоп за её начало (там сетап отменяется), цель — возврат к экстремуму.
    # Ближайший уровень как стоп не годится: у LTC поддержка была в 0.07% от цены, и косты
    # съедали 52% стопа. Уровни используем только чтобы отодвинуть стоп ДАЛЬШЕ, не ближе.
    if long_:
        sl = min([x for x in (origin, sup) if x and x < px] or [px * 0.97]) * 0.997
        tp = extreme if extreme > px else (res if res > px else px * 1.03)
    else:
        sl = max([x for x in (origin, res) if x and x > px] or [px * 1.03]) * 1.003
        tp = extreme if (extreme and extreme < px) else (sup if (sup and sup < px) else px * 0.97)
    risk_pct = abs(px - sl) / px * 100.0
    rew_pct = abs(tp - px) / px * 100.0
    if risk_pct <= 0:
        return None
    spread = (of or {}).get("spread")
    cost_pct = 0.1 + (spread or 0.05)      # комиссия round-trip + спред
    # Плечо решает, ЧТО СРАБОТАЕТ ПЕРВЫМ — стоп или ликвидация. Считаем боевым калькулятором
    # (core/execution/calc.clamp_leverage), а не своей формулой [[principle_reuse_not_duplication]].
    max_lev = None
    try:
        from core.execution.calc import clamp_leverage
        max_lev, _ = clamp_leverage(125, px, sl, pair_max=None, set_to_max=True)
    except Exception:
        pass
    return {"entry": round(px, 8), "sl": round(sl, 8), "tp": round(tp, 8), "max_lev": max_lev,
            "risk_pct": round(risk_pct, 2), "rew_pct": round(rew_pct, 2),
            "rr": round(rew_pct / risk_pct, 2),
            "cost_pct": round(cost_pct, 3),
            "cost_of_stop": round(cost_pct / risk_pct * 100, 1),   # косты в % от стопа
            "side": "BUY" if long_ else "SELL"}


def _why(r):        # причины — только проверяемые, порядок = по силе довода
    """Почему монета в списке — только проверяемые причины, без «сильный сигнал»."""
    w = []
    if (r.get("cluster") or 0) >= 2:
        w.append(f"кластер ×{r['cluster']}")
    if r.get("in_zone"):
        w.append("в зоне отката")
    elif r.get("approach"):
        w.append("подходит к зоне")
    hits = []
    try:
        hits = json.loads(r.get("hits") or "[]")
    except Exception:
        pass
    if hits:
        w.append(hits[0].split("(")[0])         # ближайшее схождение
    c = r.get("_cross")
    if c and c.get("dir"):
        side_ok = (c["dir"] > 0) == (r.get("trend") == "long")
        if side_ok:
            zn = f" из {c['zone']}" if c.get("zone") in ("OS", "OB") else ""
            w.append(f"кросс {'↑' if c['dir'] > 0 else '↓'}{c.get('age', '')}{zn}")
    if r.get("div_type") and (r.get("div_age") is not None) and r["div_age"] <= 5:
        w.append(f"див {r['div_type']} {r['div_age']}б")
    t = r.get("res_touches") if r.get("trend") == "short" else r.get("sup_touches")
    if t and t >= 3:
        w.append(f"уровень ×{t}")
    return w


_AGENDA_TOP = 5         # больше — это снова список, который надо анализировать (решение Егора)


def _agenda():
    """ПОВЕСТКА ДНЯ: режим рынка → светофор → готовые планы сделок.
    Собирается из уже доказанного: фаза, ширина падения, кластер, косты. Умеет говорить
    «сегодня не торгуй» — это её главная работа, а не список монет."""
    rows = _screener_rows(150)
    clu = _cluster_map(rows)
    phase = (_phase() or {}).get("phase") or ""
    brd = _breadth_now()
    _fetch_oif()
    longs, shorts, skipped = [], [], []
    for r in rows:
        side = r.get("trend")
        peers = clu.get(side) or []
        r["cluster"] = len(peers) if (r.get("in_zone") or r.get("approach")) else 0
        r["vs_phase"] = bool((side == "short" and "UP" in phase.upper())
                             or (side == "long" and "DOWN" in phase.upper()))
        if not (r.get("in_zone") or r.get("approach")):
            continue
        of = _oif_get(r["symbol"])
        plan = _plan_trade(r, of)
        # Кросс WT на ноге 4h: если он совпал со стороной сетапа и вышел ИЗ зоны OS/OB —
        # это доказанная механика (WT<−60 + разворот = фейд падения, PF 1.79), а не украшение.
        cr = _tf_state(r["symbol"], "4h") or {}
        cd, ca, cz = cr.get("cross_dir") or 0, cr.get("cross_age"), cr.get("zone")
        r["_cross"] = {"dir": cd, "age": ca, "zone": cz} if cd else None
        item = {"sym": r["symbol"], "side": side, "score": r.get("conf_score") or 0,
                "cluster": r["cluster"], "why": _why(r), "plan": plan,
                "turn": round((of or {}).get("turn", 0) / 1e6, 1) if of else None,
                "spread": round(of["spread"], 3) if of and of.get("spread") is not None else None}
        # отсев с ПРИЧИНОЙ — чтобы было видно, что система не молчит, а именно отсеяла
        if r["vs_phase"]:
            item["drop"] = f"против фазы ({phase})"
        elif (r["cluster"] or 0) < 2:
            item["drop"] = "одиночный сигнал (PF 0.67 против 2.24 у кластера)"
        elif plan and plan["cost_of_stop"] > 25:
            item["drop"] = f"косты съедят {plan['cost_of_stop']}% стопа"
        elif plan and plan["rr"] < 1.2:
            item["drop"] = f"RR {plan['rr']} — цель ближе стопа"
        elif item["turn"] is not None and item["turn"] < 5:
            item["drop"] = f"оборот {item['turn']} млн — проскальзывание"
        if item.get("drop"):
            skipped.append(item)
        elif side == "long":
            longs.append(item)
        else:
            shorts.append(item)
    longs.sort(key=lambda x: (-(x["cluster"]), -(x["score"])))
    shorts.sort(key=lambda x: (-(x["cluster"]), -(x["score"])))
    # ── режим дня и светофор ──
    wide = brd["wide"]
    if wide:
        mode = "ШИРОКОЕ ПАДЕНИЕ — фейд в силе"
        hint = "берём отскок падений; тренд-вход второстепенен"
    elif "UP" in phase.upper():
        mode = "ТРЕНД ВВЕРХ — работаем по тренду"
        hint = "лонги по тренду; фейд не берём — падения нет"
    elif "DOWN" in phase.upper():
        mode = "ТРЕНД ВНИЗ"
        hint = "шорты по тренду; лонг-фейд опасен без ширины падения"
    else:
        mode = "ДИАПАЗОН"
        hint = "работаем от границ, размер меньше обычного"
    n = len(longs) + len(shorts)
    if n == 0:
        light, reason = "red", "нет кандидатов, прошедших фильтры — сегодня смотрим, не торгуем"
    elif n <= 2:
        light, reason = "yellow", f"кандидатов мало ({n}) — работать выборочно, размером меньше"
    else:
        light, reason = "green", f"{n} кандидатов прошли кластер, фазу и косты"
    return {"phase": phase, "mode": mode, "hint": hint, "breadth": brd,
            "light": light, "reason": reason,
            "long": longs[:_AGENDA_TOP], "short": shorts[:_AGENDA_TOP],
            "skipped": skipped[:8], "ts": int(time.time())}


async def api_agenda(_req):
    """GET /api/agenda — повестка дня: режим, светофор, готовые планы сделок."""
    return web.json_response(_agenda())


async def api_screener(req):
    """GET /api/screener — таблица пар: нога/зона/схождения/WT + кластер и конфликт с фазой."""
    limit = int(req.query.get("limit", 60))
    rows = _screener_rows(limit)
    clu = _cluster_map(rows)
    phase = (_phase() or {}).get("phase") or ""
    for r in rows:
        side = r.get("trend")
        peers = clu.get(side) or []
        n = len(peers) if (r.get("in_zone") or r.get("approach")) else 0
        r["cluster"] = n                       # сколько монет в ту же сторону сейчас (вкл. себя)
        r["cluster_peers"] = [p for p in peers if p != r.get("symbol")][:8]
        # конфликт со фазой рынка: шорт при растущем рынке и наоборот — не запрет, а метка
        r["vs_phase"] = bool((side == "short" and "UP" in phase.upper())
                             or (side == "long" and "DOWN" in phase.upper()))
    return web.json_response({"rows": rows, "phase": phase, "ts": int(time.time())})


_CLEAN_ERA = "2026-07-11"   # sl_touch+costs (грязь размечена data_era)
_TRACK = ["radar_pump", "radar_spring", "radar_build", "atr_s2", "atr_change",
          "ds_advisor", "breakout", "rangefade", "rangefade4h"]


def _scoreboard():
    """⚖️ ФОРВАРД-ТАБЛО (Егор 25.07): net% каждого источника рядом → гейт «30 чистых net+»
    виден цифрой. Чистая эра (≥11.07, sl_touch+costs). net = profit_pct − costs_pct."""
    try:
        c = sqlite3.connect(_DB)
        c.row_factory = sqlite3.Row
        rows = c.execute(f"""SELECT signal_type,
              CASE WHEN execution_mode='VST' THEN 'vst' ELSE 'sim' END mode,
              COUNT(*) n,
              ROUND(AVG(CASE WHEN profit_pct>0 THEN 100.0 ELSE 0 END)) wr,
              ROUND(AVG(COALESCE(profit_pct,0)-COALESCE(costs_pct,0)),3) net
            FROM simulated_trades
            WHERE status IN ('SL','TP','TSL') AND created_at >= '{_CLEAN_ERA}'
            GROUP BY signal_type, mode""").fetchall()
        c.close()
        agg: dict = {}
        for r in rows:
            agg.setdefault(r["signal_type"], {})[r["mode"]] = {
                "n": r["n"], "wr": r["wr"], "net": r["net"]}
        return [{"src": s, "vst": agg.get(s, {}).get("vst"),
                 "sim": agg.get(s, {}).get("sim")} for s in _TRACK]
    except Exception:
        return []


async def api_scoreboard(_req):
    """GET /api/scoreboard — форвард net% по источникам (гейт-табло)."""
    return web.json_response({"board": _scoreboard(), "gate": 30, "ts": int(time.time())})


_EXT_DB = "oko_feed/external_data.db"


def _inplay():
    """🎯 Монеты 'в игре' СЕЙЧАС (Егор 25.07) — конфлюэнция внимания всех источников:
    радар(pump🚀/spring🌱/build🔨 со стороной) + OKO-SM скринер(OTE🎯) + DC🤖 + trending🔥.
    Больше источников = выше. → [{sym, tags}]. Терминал развязан → читает БД напрямую."""
    since2 = int(time.time()) - 7200
    coins: dict[str, list[str]] = {}

    def add(sym, tag):
        s = str(sym or "").split("/")[0].split("-")[0].upper().replace("USDT", "").strip()
        if not s:
            return
        coins.setdefault(s, [])
        if tag not in coins[s]:
            coins[s].append(tag)

    try:
        ed = sqlite3.connect(_EXT_DB, timeout=5)
        for tbl, ico, col in (("pump_signals", "🚀", "side"), ("spring_signals", "🌱", "dir"),
                              ("build_signals", "🔨", "side")):
            try:
                for sym, side in ed.execute(f"SELECT symbol,{col} FROM {tbl} WHERE ts>?", (since2,)):
                    add(sym, ico + ("↑" if str(side or "").upper() in ("BUY", "LONG", "UP") else "↓"))
            except Exception:
                pass
        try:
            row = ed.execute("SELECT coins FROM cg_trending ORDER BY ts DESC LIMIT 1").fetchone()
            for sym in (json.loads(row[0]) if row else []):
                add(sym, "🔥")
        except Exception:
            pass
        ed.close()
    except Exception:
        pass
    try:
        sc = sqlite3.connect(_DB, timeout=5)
        for sym, sco in sc.execute("SELECT symbol,conf_score FROM screener_state WHERE in_zone=1 "
                                   "AND conf_score>=3 ORDER BY conf_score DESC LIMIT 10"):
            add(sym, f"🎯{sco:.0f}")
        for (sym,) in sc.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE "
                                 "signal_type='ds_advisor' AND status IN ('OPEN','PENDING_ENTRY')"):
            add(sym, "🤖")
        sc.close()
    except Exception:
        pass
    ranked = sorted(coins.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"sym": s, "tags": "".join(t)} for s, t in ranked[:24]]


async def api_inplay(_req):
    """GET /api/inplay — монеты в игре сейчас (радар/скринер/DC/trending)."""
    return web.json_response({"coins": _inplay(), "ts": int(time.time())})


# ── ФИЛЬТР-КОНСТРУКТОР (Егор 29.07): составной MTF-фильтр по снапшотам Куба ──
_SNAP_URL = "http://127.0.0.1:8000/api/cube/snapshot_all"
_snap = {"ts": 0.0, "coins": {}}


def _fetch_snap():
    """Кэш bulk-снапшота из шины (60с). Бот флапнул → отдаём последний (stale, но живой)."""
    now = time.time()
    if now - _snap["ts"] < 60 and _snap["coins"]:
        return _snap["coins"]
    try:
        with urllib.request.urlopen(_SNAP_URL, timeout=15) as r:
            _snap["coins"] = json.loads(r.read()).get("coins", {})
            _snap["ts"] = now
    except Exception:
        pass
    return _snap["coins"]


def _match_block(rec, b):
    """Один TF-блок: WT-диапазон/зона/кросс + SMC OB/FVG/CHoCH/BOS на этом ТФ."""
    tf = b.get("tf", "1h")
    wt = (rec.get("wt") or {}).get(tf) or {}
    sm = (rec.get("smc") or {}).get(tf) or {}
    w1 = wt.get("wt1")
    if b.get("wt_min") is not None and (w1 is None or w1 < b["wt_min"]):
        return False
    if b.get("wt_max") is not None and (w1 is None or w1 > b["wt_max"]):
        return False
    if b.get("wt_zone") and wt.get("zone") != b["wt_zone"]:
        return False
    # Кросс — СОСТОЯНИЕ: wt1 выше сигнальной держится до обратного пересечения (Егор 19.08).
    # Момент пересечения живёт один бар и ловится отдельно — полем «≤N бар» (свежесть).
    want = b.get("wt_cross")
    if want and b.get("cross_age") is None:     # свежесть задана → проверит _match_tf_extra
        w1, w2 = wt.get("wt1"), wt.get("wt2")
        if w1 is None or w2 is None:            # старый снапшот без wt2 → мгновенный кросс
            cr = wt.get("cross") or 0
            if (want == "up" and not cr > 0) or (want == "down" and not cr < 0):
                return False
        elif (want == "up" and not w1 > w2) or (want == "down" and not w1 < w2):
            return False
    at = wt.get("atr") or 0   # ATRTrend per-TF (+1 вверх / −1 вниз) — Егор 29.07
    if b.get("atr_trend") == "up" and not at > 0:
        return False
    if b.get("atr_trend") == "down" and not at < 0:
        return False
    if b.get("ob_bull") and not sm.get("ob_bull"):
        return False
    if b.get("ob_bear") and not sm.get("ob_bear"):
        return False
    if b.get("fvg_bull") and not (sm.get("fvg_bull") or 0) > 0:
        return False
    if b.get("fvg_bear") and not (sm.get("fvg_bear") or 0) > 0:
        return False
    if b.get("choch") and sm.get("choch") != b["choch"]:
        return False
    if b.get("bos") and sm.get("bos") != b["bos"]:
        return False
    return True


def _match_global(rec, g):
    if not g:
        return True
    if g.get("regime") and rec.get("regime") != g["regime"]:
        return False
    if g.get("eqh_near") and not rec.get("eqh_near"):
        return False
    if g.get("eql_near") and not rec.get("eql_near"):
        return False
    if g.get("in_ote") and not rec.get("in_ote"):
        return False
    if g.get("near_pivot_pct") is not None:
        px = rec.get("px")
        piv = rec.get("piv") or {}
        tfmap = {"W": "1W", "D": "1D", "M": "1M"}
        tfs = [tfmap[g["pivot_tf"]]] if g.get("pivot_tf") in tfmap else ["1W", "1D", "1M"]
        levels = [g["pivot_level"]] if g.get("pivot_level") else ("PP", "R1", "R2", "R3", "S1", "S2", "S3")
        ok = False
        for t in tfs:
            d = piv.get(t) or {}
            for lv in levels:
                v = d.get(lv)
                if v and px and abs(px - v) / px * 100.0 <= g["near_pivot_pct"]:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            return False
    return True


_BINGX_FUND = "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex"
_BINGX_TICK = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"
_BYBIT_OI = "https://api.bybit.com/v5/market/tickers?category=linear"
_oif = {"ts": 0.0, "cur": {}, "prev": {}}


# 🔴 16.08: klines/ticker ходят напрямую urllib, МИМО GlobalRateLimiter клиента — при бане
# 100410 они продолжали долбить и держали бан (терминал «умирал» на 5 минут). Свой стоп-кран:
# поймали rate-limit → все прямые запросы молчат и отдают кэш, пока пауза не истечёт.
_ban = {"until": 0.0}


def _banned():
    return time.time() < _ban["until"]


def _ban_set(sec, why=""):
    _ban["until"] = max(_ban["until"], time.time() + sec)
    print(f"[LIMIT] пауза {sec:.0f}с ({why}) — прямые запросы к BingX молчат")


def _bx_json(url, timeout=15):
    """GET к публичному API с уважением к бану. None → берите кэш."""
    if _banned():
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oko"})
        d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        if str(d.get("code")) == "100410":
            _ban_set(60, "100410 rate limit")
            return None
        return d
    except Exception as e:
        if "429" in str(e) or "418" in str(e):
            _ban_set(60, str(e)[:40])
        return None


def _bx_get(url):
    d = _bx_json(url)
    return (d or {}).get("data", []) or []


def _fetch_oif():
    """Funding+объём с BingX (наша биржа, точно) + OI с Bybit (у BingX нет bulk-OI) для OI-изменения.
    Егор 29.07 «торгуем на BingX». Кэш 5 мин; prev-снап для ~5-мин OI-моментума."""
    now = time.time()
    if now - _oif["ts"] < 300 and _oif["cur"]:
        return _oif["cur"]
    cur = {}
    try:  # BingX funding + оборот
        for t in _bx_get(_BINGX_FUND):
            b = str(t.get("symbol", "")).replace("-USDT", "")
            if b:
                cur.setdefault(b, {})["fund"] = float(t.get("lastFundingRate") or 0) * 100.0
        for t in _bx_get(_BINGX_TICK):
            b = str(t.get("symbol", "")).replace("-USDT", "")
            if b in cur:
                cur[b]["turn"] = float(t.get("quoteVolume") or 0)
                ask, bid = float(t.get("askPrice") or 0), float(t.get("bidPrice") or 0)
                if ask > 0 and bid > 0:
                    cur[b]["spread"] = (ask - bid) / ((ask + bid) / 2.0) * 100.0  # % (Егор 30.07)
    except Exception:
        pass
    try:  # Bybit OI (BingX bulk-OI нет)
        lst = json.loads(urllib.request.urlopen(_BYBIT_OI, timeout=15).read())["result"]["list"]
        for t in lst:
            s = t.get("symbol", "")
            if s.endswith("USDT") and s[:-4] in cur:
                cur[s[:-4]]["oi"] = float(t.get("openInterest") or 0)
    except Exception:
        pass
    if cur:
        _oif["prev"] = _oif["cur"] or cur
        _oif["cur"] = cur
        _oif["ts"] = now
    return _oif["cur"]


def _oif_get(base):
    cur = _oif["cur"].get(base)
    if not cur:
        return None
    prev = _oif["prev"].get(base) or {}
    co, po = cur.get("oi"), prev.get("oi")
    oi_chg = ((co - po) / po * 100.0) if (co is not None and po) else None
    return {"fund": cur.get("fund"), "oi_chg": oi_chg, "turn": cur.get("turn") or 0,
            "spread": cur.get("spread")}


_vr: dict = {}          # (sym,tf) → (ts, {ratio, z, dir})
_VR_TTL = 120.0


def _vol_anomaly(sym, tf):
    """Аномалия объёма на закрытых барах: отношение к средней (единый `compute_volume_ratio`)
    + z-оценка и КУДА шёл объём. Аномалия сама по себе не сигнал: тот же всплеск бывает началом
    хода и кульминацией-выдохом, поэтому отдаём и направление бара, и его размах."""
    key = (sym, tf)
    hit = _vr.get(key)
    now = time.time()
    if hit and now - hit[0] < _VR_TTL:
        return hit[1]
    out = None
    try:
        from core.indicators.indicators import compute_volume_ratio
        bars = _klines(sym, tf, 200)
        if len(bars) >= 40:
            v = [b["v"] for b in bars[:-1]]           # без незакрытого бара
            ratio = compute_volume_ratio(v, period=20)
            last = bars[-2]
            body = (last["c"] - last["o"]) / last["o"] * 100.0 if last["o"] else 0.0
            rng = (last["h"] - last["l"]) / last["l"] * 100.0 if last["l"] else 0.0
            tail = [x for x in v[-60:]]
            mu = sum(tail) / len(tail)
            sd = (sum((x - mu) ** 2 for x in tail) / len(tail)) ** 0.5
            out = {"ratio": round(ratio, 2) if ratio else None,
                   "z": round((v[-1] - mu) / sd, 2) if sd > 0 else None,
                   "body": round(body, 2), "rng": round(rng, 2)}
            _vr[key] = (now, out)
    except Exception as e:
        print(f"[VOL] {sym}/{tf}: {e}")
    return out


_SNAP_TFS = ("5m", "15m", "1h", "4h", "1d")   # WT+ATRTrend бот ведёт по всем пяти (17.08)
_SMC_TFS = ("15m", "1h", "4h")                   # а SMC-флаги — только по этим трём
_tfs: dict = {}                     # (sym,tf) → (ts, состояние)
_TFS_TTL = 120.0
_DIVD = None


def _tf_state(sym, tf):
    """WT + ATRTrend + дивергенция по свечам — для ТФ, которых нет в снапшоте (5m/1d), и для
    дивергенции на любом ТФ. Калькуляторы штатные: `calculate_wt`, `DivergenceDetector`,
    `calculate_trend` [[principle_reuse_not_duplication]]."""
    global _DIVD
    key = (sym, tf)
    hit = _tfs.get(key)
    now = time.time()
    if hit and now - hit[0] < _TFS_TTL:
        return hit[1]
    out = None
    try:
        import pandas as pd
        from core.indicators.indicators import calculate_wt
        from core.indicators.divergence_detector import DivergenceDetector
        bars = _klines(sym, tf, 300)
        if len(bars) >= 150:
            d = pd.DataFrame([{"open": b["o"], "high": b["h"], "low": b["l"],
                               "close": b["c"], "volume": b["v"]} for b in bars])
            d = calculate_wt(d)
            w1 = float(d["wt1"].iloc[-1]); w2 = float(d["wt2"].iloc[-1])
            p1 = float(d["wt1"].iloc[-2]); p2 = float(d["wt2"].iloc[-2])
            if _DIVD is None:
                _DIVD = DivergenceDetector(pivot_period=5, lookback=50, max_bars=100,
                                           min_bars_between=5)
            dv, age = None, None
            kinds = (("R+", _DIVD.detect_regular_bullish), ("R−", _DIVD.detect_regular_bearish),
                     ("H+", _DIVD.detect_hidden_bullish), ("H−", _DIVD.detect_hidden_bearish))
            tail = d.tail(232).reset_index(drop=True)
            for a in range(13):
                sub = tail if a == 0 else tail.iloc[:len(tail) - a]
                if len(sub) < 120:
                    break
                for nm, fn in kinds:
                    try:
                        if fn(sub, indicator_col="wt1"):
                            dv, age = nm, a
                            break
                    except Exception:
                        pass
                if dv:
                    break
            # Кросс живёт РОВНО ОДИН бар: на 1d он ловится только в тот день, когда случился
            # (GRT дал кросс 17.08, а 19.08 фильтр его уже не видел — вопрос Егора).
            # Поэтому считаем возраст последнего кросса и даём фильтровать по свежести.
            w1s, w2s = d["wt1"].values, d["wt2"].values
            c_dir, c_age = 0, None
            for k in range(len(w1s) - 1, max(1, len(w1s) - 250), -1):   # состояние живёт долго
                up = w1s[k - 1] <= w2s[k - 1] and w1s[k] > w2s[k]
                dn = w1s[k - 1] >= w2s[k - 1] and w1s[k] < w2s[k]
                if up or dn:
                    c_dir = 1 if up else -1
                    c_age = len(w1s) - 1 - k
                    break
            out = {"wt1": round(w1, 1),
                   "zone": "OB" if w1 >= 60 else ("OS" if w1 <= -60 else "N"),
                   "cross": 1 if (p1 <= p2 and w1 > w2) else (-1 if (p1 >= p2 and w1 < w2) else 0),
                   "cross_dir": c_dir, "cross_age": c_age,
                   "div": dv, "div_age": age}
            _tfs[key] = (now, out)
    except Exception as e:
        print(f"[TFS] {sym}/{tf}: {e}")
    return out


def _match_tf_extra(st, b):
    """Условия блока по посчитанному состоянию (для 5m/1d) — WT/зона/кросс."""
    if st is None:
        return False
    if b.get("wt_min") is not None and st["wt1"] < b["wt_min"]:
        return False
    if b.get("wt_max") is not None and st["wt1"] > b["wt_max"]:
        return False
    if b.get("wt_zone") and st["zone"] != b["wt_zone"]:
        return False
    want = b.get("wt_cross")
    if want:
        d_ = st.get("cross_dir") or 0      # действующее состояние: куда был последний кросс
        a_ = st.get("cross_age")
        if (want == "up" and d_ <= 0) or (want == "down" and d_ >= 0):
            return False
        mx = b.get("cross_age")            # «≤N бар» — дополнительно требуем свежесть установки
        if mx is not None and (a_ is None or a_ > mx):
            return False
    return True


def _match_oif(of, g):
    """Funding-диапазон + OI-изменение + оборот (глобальные, из Bybit)."""
    need = any(g.get(k) is not None for k in ("fund_min", "fund_max", "oi_chg", "turn_min", "spread_max"))
    if not need:
        return True
    if of is None:
        return False
    if g.get("spread_max") is not None and (of.get("spread") is None or of["spread"] > g["spread_max"]):
        return False
    if g.get("fund_min") is not None and (of["fund"] is None or of["fund"] < g["fund_min"]):
        return False
    if g.get("fund_max") is not None and (of["fund"] is None or of["fund"] > g["fund_max"]):
        return False
    if g.get("oi_chg") is not None:
        v = of["oi_chg"]
        if v is None:
            return False
        if g["oi_chg"] >= 0 and v < g["oi_chg"]:      # рост ≥
            return False
        if g["oi_chg"] < 0 and v > g["oi_chg"]:       # падение ≤ (отрицательный порог)
            return False
    if g.get("turn_min") is not None and of["turn"] < g["turn_min"] * 1e6:
        return False
    return True


async def api_filter(req):
    """POST /api/filter — {blocks:[{tf,wt_min,...}], global:{...}} → монеты, прошедшие ВСЕ блоки (AND)."""
    try:
        q = await req.json()
    except Exception:
        q = {}
    blocks = q.get("blocks") or []
    g = q.get("global") or {}
    coins = _fetch_snap()
    _fetch_oif()  # прогрев OI/funding кэша
    vmin = g.get("vol_ratio_min")
    vtf = g.get("vol_tf") or "1h"
    out = []
    pre = []
    # блоки делим: снапшотные (дёшево, лежат в шине) и вычисляемые из свечей (5m/1d — дорого)
    snap_blocks = [b for b in blocks if (b.get("tf") or "1h") in _SNAP_TFS]
    calc_blocks = [b for b in blocks if (b.get("tf") or "1h") not in _SNAP_TFS]
    for sym, rec in coins.items():
        base = sym.split("/")[0]
        if all(_match_block(rec, b) for b in snap_blocks) and _match_global(rec, g) \
                and _match_oif(_oif_get(base), g):
            pre.append((sym, rec, base))
    # дивергенция теперь условие СТРОКИ ТФ (Егор 17.08) — её нет в снапшоте ни на одном ТФ,
    # поэтому любой блок с div уходит в тяжёлую фазу вместе с 5m/1d
    div_blocks = [b for b in blocks if b.get("div")]
    age_blocks = [b for b in blocks if b.get("wt_cross") and b.get("cross_age") is not None]
    if calc_blocks or div_blocks or age_blocks:
        loop = asyncio.get_running_loop()
        need_tfs = sorted({b.get("tf") or "1h" for b in calc_blocks} |
                          {b.get("tf") or "1h" for b in div_blocks} |
                          {b.get("tf") or "1h" for b in age_blocks})
        keep = []
        for i in range(0, min(len(pre), 120), 24):
            chunk = pre[i:i + 24]
            res = await asyncio.gather(*[loop.run_in_executor(_POOL, _tf_state, b, tf)
                                         for _, _, b in chunk for tf in need_tfs])
            k = 0
            for sym, rec, base in chunk:
                st = {}
                for tf in need_tfs:
                    st[tf] = res[k]; k += 1
                if not all(_match_tf_extra(st.get(b.get("tf") or "1h"), b)
                           for b in calc_blocks + age_blocks):
                    continue
                ok, found = True, None
                for b in div_blocks:                    # дивергенция на СВОЁМ ТФ у каждого блока
                    ds = st.get(b.get("tf") or "1h") or {}
                    dv, age = ds.get("div"), ds.get("div_age")
                    want = b["div"]
                    if not dv or (want != "any" and dv != want):
                        ok = False
                        break
                    mx = b.get("div_age")
                    if mx is not None and (age is None or age > mx):
                        ok = False
                        break
                    found = {"t": dv, "a": age, "tf": b.get("tf") or "1h"}
                if not ok:
                    continue
                if found:
                    rec = dict(rec); rec["_div"] = found
                keep.append((sym, rec, base))
        pre = keep
    if vmin:                    # объём считаем ТОЛЬКО по прошедшим прочие условия (это klines-запрос)
        loop = asyncio.get_running_loop()
        vres = await asyncio.gather(*[loop.run_in_executor(_POOL, _vol_anomaly, b, vtf)
                                      for _, _, b in pre[:60]])
        keep = []
        for (sym, rec, base), va in zip(pre, vres):
            if va and va.get("ratio") and va["ratio"] >= vmin:
                rec = dict(rec)
                rec["_vol"] = va
                keep.append((sym, rec, base))
        pre = keep
    for sym, rec, base in pre:
        of = _oif_get(base)
        va = rec.get("_vol") or {}
        out.append({"sym": base, "px": rec.get("px"), "regime": rec.get("regime"),
                    "np": rec.get("near_pivot"),
                    "turn": round((of["turn"] or 0) / 1e6, 1) if of else None,   # млн$ (монитор ранжирует)
                    "fund": round(of["fund"], 4) if of else None,
                    "oi_chg": round(of["oi_chg"], 1) if of and of["oi_chg"] is not None else None,
                    "spread": round(of["spread"], 4) if of and of["spread"] is not None else None,
                    "vr": va.get("ratio"), "vz": va.get("z"), "vbody": va.get("body"),
                    "div": (rec.get("_div") or {}).get("t"),
                    "div_age": (rec.get("_div") or {}).get("a"),
                    "div_tf": (rec.get("_div") or {}).get("tf")})
    # Кросс показываем ВСЕГДА, без доп. поисков: направление действующего состояния + сколько
    # баров назад установилось (Егор 19.08 «EGLD ↑2»). Считаем только для итогового списка —
    # он короткий, поэтому дёшево. Зона рядом: кросс ИЗ OS/OB сильнее прочих.
    ctf = (blocks[0].get("tf") if blocks else None) or "1h"
    if out:
        loop = asyncio.get_running_loop()
        head = out[:40]
        st_all = await asyncio.gather(*[loop.run_in_executor(_POOL, _tf_state, x["sym"], ctf)
                                        for x in head])
        for x, stt in zip(head, st_all):
            if stt:
                x["cr_dir"] = stt.get("cross_dir")
                x["cr_age"] = stt.get("cross_age")
                x["cr_zone"] = stt.get("zone")
                x["cr_tf"] = ctf
    if vmin:                              # аномальный объём — самые громкие вверху
        out.sort(key=lambda x: -(x["vr"] or 0))
    elif g.get("spread_max") is not None:   # «наименьший спред» → тесные вверху
        out.sort(key=lambda x: (x["spread"] if x["spread"] is not None else 9e9))
    else:
        out.sort(key=lambda x: x["sym"])
    return web.json_response({"coins": out, "n": len(out), "total": len(coins), "ts": int(time.time())})


# ── МНОГООКОННЫЙ МОНИТОР (Егор 14.08): фильтр → сетка живых графиков, аналог TW ──
_KL_URL = "https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={s}-USDT&interval={tf}&limit={n}"
_KL_TTL = 20.0          # свечи; последний бар дотягивается живой ценой из /api/prices (3с)
_PX_TTL = 3.0
_kl: dict = {}          # (sym,tf) → (ts, bars)
_px = {"ts": 0.0, "map": {}}
_POOL = ThreadPoolExecutor(max_workers=8)


def _klines(sym, tf, limit, end=None):
    """Свечи BingX для одной монеты (кэш 20с). v3 отдаёт от новых к старым → разворачиваем.
    end (мс) — верхняя граница: так монитор догружает историю при скролле влево."""
    key = (sym, tf, limit, end)
    hit = _kl.get(key)
    now = time.time()
    if hit and (end or now - hit[0] < _KL_TTL):     # исторический кусок неизменен → кэш навсегда
        return hit[1]
    try:
        url = _KL_URL.format(s=sym, tf=tf, n=limit) + (f"&endTime={int(end)}" if end else "")
        d = _bx_json(url, timeout=12)
        if d is None:                    # бан/сеть → отдаём последнее, что есть, и не долбим
            return hit[1] if hit else []
        raw = d.get("data") or []
        bars = [{"t": int(b["time"]) // 1000, "o": float(b["open"]), "h": float(b["high"]),
                 "l": float(b["low"]), "c": float(b["close"]), "v": float(b["volume"])}
                for b in reversed(raw)]
        if bars:
            _kl[key] = (now, bars)
        return bars
    except Exception:
        return hit[1] if hit else []


_TRP = {"ts": 0.0, "v": (43, 1.0)}


def _trend_params():
    """ATRTrend из config.yaml (бой: atr_period 43, factor 1.25) — числа только из источника."""
    if time.time() - _TRP["ts"] < 300:
        return _TRP["v"]
    try:
        import yaml
        c = ((yaml.safe_load(open("config.yaml", encoding="utf-8")) or {})
             .get("analysis", {}).get("indicators", {}).get("trend", {}))
        _TRP["v"] = (int(c.get("atr_period", 43)), float(c.get("factor", 1.0)))
    except Exception:
        pass
    _TRP["ts"] = time.time()
    return _TRP["v"]


def _atr_trend(bars):
    """ATRTrend по барам: направление (+1/−1) + линия (trendup для лонга / trenddown для шорта).
    Тот же `calculate_trend`, что кормит TSL и сигналы — один калькулятор на проект."""
    try:
        import pandas as pd
        from core.indicators.indicators import calculate_trend
        p, f = _trend_params()
        if len(bars) < p + 2:
            return None
        d = calculate_trend(pd.DataFrame([{"high": b["h"], "low": b["l"], "close": b["c"],
                                           "open": b["o"]} for b in bars]), atr_period=p, factor=f)
        out = []
        for i, b in enumerate(bars):
            t = d["trend"].iloc[i]
            ln = d["trendup"].iloc[i] if t > 0 else d["trenddown"].iloc[i]
            out.append({"t": b["t"], "d": int(t) if t == t else 0,
                        "l": float(ln) if ln == ln else None})
        return out
    except Exception as e:
        print(f"[MON] atr: {e}")
        return None


async def api_klines(req):
    """GET /api/klines?syms=BTC,ETH&tf=15m&limit=200[&end=мс][&atr=1] — свечи пачкой (окна монитора);
    end — догрузка истории при скролле влево, atr — направление+линия ATRTrend на каждый бар."""
    syms = [s.strip().upper() for s in (req.query.get("syms") or "").split(",") if s.strip()][:24]
    tf = req.query.get("tf", "15m")
    limit = min(int(req.query.get("limit", 200)), 1000)
    end = int(req.query["end"]) if req.query.get("end") else None
    loop = asyncio.get_running_loop()
    res = await asyncio.gather(*[loop.run_in_executor(_POOL, _klines, s, tf, limit, end)
                                 for s in syms])
    out = {"bars": dict(zip(syms, res)), "tf": tf, "ts": int(time.time())}
    if req.query.get("atr"):
        atr = await asyncio.gather(*[loop.run_in_executor(_POOL, _atr_trend, b) for b in res])
        out["atr"] = {s: a for s, a in zip(syms, atr) if a}
    return web.json_response(out)


def _prices():
    """Живая цена всей вселенной одним запросом BingX (кэш 3с). Только lastPrice: поле
    priceChangePercent у bulk-тикера считается за ~3-мин окно (openTime≈closeTime), не за сутки —
    изменение монитор считает из свечей."""
    now = time.time()
    if now - _px["ts"] < _PX_TTL and _px["map"]:
        return _px["map"]
    try:
        m = {}
        for t in _bx_get(_BINGX_TICK):
            b = str(t.get("symbol", "")).replace("-USDT", "")
            if b:
                m[b] = {"px": float(t.get("lastPrice") or 0)}
        if m:
            _px["map"] = m
            _px["ts"] = now
    except Exception:
        pass
    return _px["map"]


async def api_symbols(_req):
    """GET /api/symbols — все торгуемые базы (для ручного поиска монеты в мониторе)."""
    m = _prices()
    return web.json_response({"syms": sorted(m.keys()), "n": len(m)})


async def api_prices(req):
    """GET /api/prices?syms=BTC,ETH — тик цены для шапок окон (обновление последней свечи)."""
    m = _prices()
    syms = [s.strip().upper() for s in (req.query.get("syms") or "").split(",") if s.strip()]
    out = {s: m[s] for s in syms if s in m} if syms else m
    return web.json_response({"px": out, "ts": int(time.time())})


_smc_c: dict = {}       # (sym,tf) → (ts, структуры)
_SMC_TTL = 60.0


def _smc_levels(sym, tf):
    """SMC-структуры для отрисовки: FVG/OB боксы, линии CHoCH/BOS, EQH/EQL.
    Считаются ТЕМИ ЖЕ детекторами, что и TG-чарт (core/smc/smc_engine) на наших же свечах —
    один калькулятор, отличия только в отрисовке [[principle_reuse_not_duplication]]."""
    key = (sym, tf)
    hit = _smc_c.get(key)
    now = time.time()
    if hit and now - hit[0] < _SMC_TTL:
        return hit[1]
    out = {"ob": [], "fvg": [], "brk": [], "eq": [], "leg": None}
    try:
        import pandas as pd
        from core.smc.smc_engine import (detect_structure_breaks, detect_order_blocks,
                                         detect_fvg, detect_equal_levels)
        from core.smc.oko_sm_engine import run_structure, current_leg
        bars = _klines(sym, tf, 1000)         # ≥1000 баров = эталонное окно OKO-SM (без холодного старта)
        if len(bars) < 30:
            return out
        d = pd.DataFrame([{"open": b["o"], "high": b["h"], "low": b["l"],
                           "close": b["c"], "volume": b["v"]} for b in bars])
        ts = [b["t"] for b in bars]           # позиция бара → время свечи
        px = bars[-1]["c"]
        # СТРУКТУРА — движком OKO-SM (порт индикатора Егора v163, сверен с метками графика):
        # два масштаба, swing(50) = сторона, internal(5) = вход [[method_egor_two_scale_entry]]
        st = run_structure(d, swing_len=50, internal_len=5)
        sw_ev = [e for e in st.events if not e.internal][-4:]     # раздельно: internal(5) частые и
        in_ev = [e for e in st.events if e.internal][-6:]          # затопили бы swing-структуру
        for e in sorted(sw_ev + in_ev, key=lambda x: x.i):
            i0 = e.level_i if e.level_i is not None and e.level_i >= 0 else e.i
            out["brk"].append({"t0": ts[i0], "t1": ts[e.i], "p": e.level, "kind": e.kind,
                               "dir": "bull" if e.bull else "bear", "int": bool(e.internal)})
        leg = current_leg(st)
        if leg:                               # нога старшего масштаба + Strong High / Weak Low
            out["leg"] = {"t0": ts[leg["origin_i"]], "p0": leg["origin"],
                          "t1": ts[leg["extreme_i"]], "p1": leg["extreme"], "side": leg["trend"]}
        out["trail"] = {"up": st.trail_up, "dn": st.trail_dn}
        brks = detect_structure_breaks(d, length=5)    # OB привязаны к сломам smc_engine
        for o in detect_order_blocks(d, brks):
            if o.mitigated_idx != -1:         # пробитый OB не рисуем
                continue
            out["ob"].append({"t0": ts[o.left_idx], "top": o.top, "bot": o.bottom, "kind": o.kind})
        out["ob"] = out["ob"][-6:]
        for f in detect_fvg(d)[-15:]:
            if f[5] is not None:              # закрытый гэп — не рисуем (каша слева)
                continue
            top, bot = f[1], f[2]
            if px and abs((top + bot) / 2 - px) / px > 0.03:   # только вблизи цены (±3%, как TG)
                continue
            i0 = int(f[0]) if isinstance(f[0], (int, float)) else 0
            out["fvg"].append({"t0": ts[min(max(i0, 0), len(ts) - 1)],
                               "top": max(top, bot), "bot": min(top, bot), "kind": f[3]})
        out["fvg"] = out["fvg"][-10:]
        hi, lo = d["high"].values, d["low"].values
        for e in detect_equal_levels(d)[-20:]:   # кандидатов берём с запасом: снятые отсеются ниже
            i1, i2 = int(e[0]), int(e[2])
            i2 = min(max(i2, 0), len(ts) - 1)
            p = (float(e[1]) + float(e[3])) / 2
            swept = ((hi[i2 + 1:] > p).any() if e[4] == "EQH"    # ликвидность уже снята —
                     else (lo[i2 + 1:] < p).any())               # уровень отработан, не рисуем
            if swept:
                continue
            out["eq"].append({"t0": ts[min(max(i1, 0), len(ts) - 1)], "t1": ts[i2],
                              "p": p, "kind": e[4]})
        out["eq"] = out["eq"][-4:]
        _smc_c[key] = (now, out)
    except Exception as e:
        print(f"[MON] smc {sym}/{tf}: {e}")
    return out


async def api_levels(req):
    """GET /api/levels?syms=BTC,ETH&tf=15m — контекст Куба на окно: пивоты W/D (цены из шины) +
    FVG/OB/CHoCH/BOS/EQH-EQL, посчитанные детекторами smc_engine на наших свечах."""
    syms = [s.strip().upper() for s in (req.query.get("syms") or "").split(",") if s.strip()][:24]
    tf = req.query.get("tf", "15m")
    coins = _fetch_snap()
    idx = {k.split("/")[0].upper(): v for k, v in coins.items()}
    loop = asyncio.get_running_loop()
    smc_all = await asyncio.gather(*[loop.run_in_executor(_POOL, _smc_levels, s, tf) for s in syms])
    out = {}
    for s, smc_draw in zip(syms, smc_all):
        rec = idx.get(s) or {}
        smc = (rec.get("smc") or {}).get(tf) or {}
        out[s] = {"piv": rec.get("piv") or {}, "regime": rec.get("regime"),
                  "ob": smc_draw["ob"], "fvg": smc_draw["fvg"],
                  "brk": smc_draw["brk"], "eq": smc_draw["eq"], "leg": smc_draw.get("leg"),
                  "flags": {"CHoCH": smc.get("choch"), "BOS": smc.get("bos"),
                            "EQH": bool(rec.get("eqh_near")), "EQL": bool(rec.get("eql_near")),
                            "OTE": bool(rec.get("in_ote"))}}
    return web.json_response({"lv": out, "ts": int(time.time())})


# ── ТОРГОВЛЯ С ГРАФИКА (Егор 14.08): VST ⇄ LIVE, размер риском или маржой ──
# Ордера уходят боевым BingXClient (place_bracket_order) — второго торгового пути не заводим.
# 🔴 Терминал слушает 0.0.0.0 (графики видны в локальной сети), поэтому ордера принимаются
# ТОЛЬКО с localhost: иначе любой в сети открывал бы позиции без пароля.
_tcl: dict = {}
_lev_cache: dict = {}
_tcl_lock = None        # гонка на создании клиента = осиротевшие ClientSession («Unclosed session»)


def _is_local(req):
    ip = (req.remote or "").strip()
    return ip in ("127.0.0.1", "::1", "localhost")


async def _trade_client(mode):
    global _tcl_lock
    if _tcl_lock is None:
        _tcl_lock = asyncio.Lock()
    async with _tcl_lock:                 # без блокировки два параллельных запроса создавали
        return await _trade_client_impl(mode)   # двух клиентов, второй затирал первого в кэше


_tcl_fail: dict = {}    # неудачные попытки: без этого каждый запрос заново пробовал ОБА ключа
                        # (2 приватных вызова) и сам держал бан 100410


async def _trade_client_impl(mode):
    if mode in _tcl:
        return _tcl[mode]
    if time.time() < _tcl_fail.get(mode, 0):
        return None                      # недавно не вышло — не долбим биржу ещё раз
    """Клиент BingX под режим. У BingX ключ ОДИН на аккаунт, демо/реал решает домен, поэтому
    для LIVE сначала пробуем BINGX_API_KEY, а если он отвергнут (100413 — отозван/протух),
    переходим на рабочий ключ аккаунта с боевым доменом (проверено 14.08)."""
    if mode in _tcl:
        return _tcl[mode]
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        from core.exchange.bingx_client import BingXClient, VST_BASE_URL, LIVE_BASE_URL
        kv = (os.environ.get("BINGX_VST_API_KEY") or "").strip()
        sv = (os.environ.get("BINGX_VST_SECRET_KEY") or "").strip()
        if mode == "vst":
            if not kv:
                return None
            _tcl[mode] = BingXClient(kv, sv, VST_BASE_URL)
            return _tcl[mode]
        kl = (os.environ.get("BINGX_API_KEY") or "").strip()
        sl_ = (os.environ.get("BINGX_SECRET_KEY") or "").strip()
        for key, sec, tag in ((kl, sl_, "BINGX_API_KEY"), (kv, sv, "ключ аккаунта (fallback)")):
            if not key:
                continue
            cl = BingXClient(key, sec, LIVE_BASE_URL)
            try:
                r = await cl.get("/openApi/swap/v2/user/balance")
                if str(r.get("code")) == "0":
                    print(f"[TRADE] LIVE-клиент на {tag}")
                    _tcl[mode] = cl
                    return cl
                print(f"[TRADE] LIVE {tag} отвергнут: {r.get('code')} {r.get('msg')}")
            except Exception as e:
                print(f"[TRADE] LIVE {tag}: {e}")
            await cl.close()
        _tcl_fail[mode] = time.time() + 90       # пауза перед следующей попыткой
        return None
    except Exception as e:
        print(f"[TRADE] клиент {mode}: {e}")
        _tcl_fail[mode] = time.time() + 90
        return None


def _register_manual(symbol, direction, mode, oid, qty, entry, sl, tp):
    """Ручная сделка → таблица manual_positions. 🔴 БЕЗ этого бот считает позицию рассинхроном
    и закрывает по рынку: D-070 orphan_autoclose=live уже съел RPL/YFI/MELANIA/RSR (14.08).
    Отдельная таблица, НЕ simulated_trades — иначе TSL-updater переставит стоп, а форвард-табло
    посчитает ручную сделку своей статистикой."""
    try:
        c = sqlite3.connect(_DB, timeout=5)
        c.execute("""CREATE TABLE IF NOT EXISTS manual_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, direction TEXT NOT NULL, mode TEXT,
            order_id TEXT, qty REAL, entry REAL, sl REAL, tp REAL,
            opened_at INTEGER, closed_at INTEGER DEFAULT NULL)""")
        c.execute("INSERT INTO manual_positions(symbol,direction,mode,order_id,qty,entry,sl,tp,"
                  "opened_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (symbol, direction, mode, str(oid or ""), qty, entry, sl, tp, int(time.time())))
        c.commit()
        c.close()
        print(f"[TRADE] {symbol} {direction} записана в manual_positions (бот не тронет)")
    except Exception as e:
        print(f"[TRADE] 🔴 manual_positions: {e} — бот может закрыть позицию как orphan!")


_acc_cache: dict = {}
_ACC_TTL = 45.0         # приватные ручки лимитируются жёстко: не чаще раза в 45с на режим


async def api_account(req):
    """GET /api/account?mode=vst|live — доступная маржа + открытые позиции по монете."""
    if not _is_local(req):
        return web.json_response({"error": "торговля только с localhost"}, status=403)
    mode = "live" if req.query.get("mode") == "live" else "vst"
    hit = _acc_cache.get(mode)
    if hit and time.time() - hit[0] < _ACC_TTL:
        return web.json_response(hit[1])
    cl = await _trade_client(mode)
    if not cl:
        return web.json_response({"error": f"нет рабочего ключа BingX для {mode.upper()}"}, status=400)
    try:
        # ОДИН вызов /user/balance вместо двух (get_balance + сырой запрос за equity) —
        # приватные ручки лимитируются жёстко, а мы их дублировали на каждый опрос (16.08)
        raw = ((await asyncio.wait_for(cl.get("/openApi/swap/v2/user/balance"), timeout=8)
                ).get("data") or {}).get("balance") or {}
        bal = float(raw.get("availableMargin") or 0)
        positions = await asyncio.wait_for(cl.get_positions(), timeout=8) or []
        has_pos = any(abs(float(p.get("positionAmt") or 0)) > 0 for p in positions)
        orders = (await asyncio.wait_for(cl.get_open_orders(), timeout=8) or []) if has_pos else []
        prot: dict = {}
        for o in orders:
            b = str(o.get("symbol", "")).replace("-USDT", "")
            t = str(o.get("type", "")).upper()
            sp = float(o.get("stopPrice") or 0)
            if not b or not sp:
                continue
            k = "sl" if "STOP" in t else ("tp" if "TAKE_PROFIT" in t else None)
            if k:
                lst = prot.setdefault(b, {}).setdefault(k, [])
                if sp not in lst:
                    lst.append(sp)
        # Separate Isolated: по одной паре может висеть НЕСКОЛЬКО позиций (каждая сделка своя,
        # со своими SL/TP). Для окна монитора сворачиваем их в одну строку: объём — сумма,
        # вход — средневзвешенный, уровни защиты — все уникальные.
        agg: dict = {}
        for p in positions:
            amt = abs(float(p.get("positionAmt") or 0))
            if not amt:
                continue
            b = str(p.get("symbol", "")).replace("-USDT", "")
            side = str(p.get("positionSide") or "LONG").upper()
            e = agg.setdefault((b, side), {"sym": b, "side": side, "qty": 0.0, "notional": 0.0,
                                           "pnl": 0.0, "n": 0})
            e["qty"] += amt
            e["notional"] += amt * float(p.get("avgPrice") or 0)
            e["pnl"] += float(p.get("unrealizedProfit") or 0)
            e["n"] += 1
        pos = []
        for e in agg.values():
            pr = prot.get(e["sym"]) or {}
            pos.append({"sym": e["sym"], "side": e["side"], "qty": round(e["qty"], 8),
                        "entry": (e["notional"] / e["qty"]) if e["qty"] else 0,
                        "pnl": e["pnl"], "n": e["n"],
                        "sl": (pr.get("sl") or [None])[0] if pr.get("sl") else None,
                        "tp": (pr.get("tp") or [None])[0] if pr.get("tp") else None,
                        "sls": pr.get("sl") or [], "tps": pr.get("tp") or []})
        eq = float(raw.get("equity") or 0) or None          # из того же ответа, без второго запроса
        used = float(raw.get("usedMargin") or 0) or None
        upnl = float(raw.get("unrealizedProfit") or 0) or None
        out = {"mode": mode, "balance": bal, "pos": pos,
               "equity": eq, "used": used, "upnl": upnl}
        _acc_cache[mode] = (time.time(), out)
        return web.json_response(out)
    except asyncio.TimeoutError:
        stale = _acc_cache.get(mode)
        if stale:                                # биржа притормозила — отдаём последнее известное
            out = dict(stale[1]); out["stale"] = True
            return web.json_response(out)
        return web.json_response({"error": "биржа ограничила запросы (rate limit) — подожди минуту"},
                                 status=503)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_levinfo(req):
    """GET /api/levinfo?sym=BTW&mode=live — лимиты ПАРЫ: максимальное плечо и сколько объёма
    биржа реально даёт открыть. Без этого панель считала маржу по запрошенному плечу (x20),
    а биржа резала до максимума пары (BTW: x10) → «Insufficient margin» уже после подтверждения."""
    if not _is_local(req):
        return web.json_response({"error": "только с localhost"}, status=403)
    sym = str(req.query.get("sym") or "").upper()
    mode = "live" if req.query.get("mode") == "live" else "vst"
    cl = await _trade_client(mode)
    if not cl or not sym:
        return web.json_response({"error": "нет клиента или символа"}, status=400)
    hit = _lev_cache.get((mode, sym))
    if hit and time.time() - hit[0] < 600:
        return web.json_response(hit[1])
    try:
        d = await asyncio.wait_for(cl.get_leverage_info(f"{sym}/USDT:USDT"), timeout=8) or {}
        out = {
            "sym": sym,
            "max_long": int(d.get("maxLongLeverage") or 0) or None,
            "max_short": int(d.get("maxShortLeverage") or 0) or None,
            "cur_long": int(d.get("longLeverage") or 0) or None,
            "cur_short": int(d.get("shortLeverage") or 0) or None,
            "avail_long": float(d.get("availableLongVal") or 0) or None,   # объём в USDT
            "avail_short": float(d.get("availableShortVal") or 0) or None}
        _lev_cache[(mode, sym)] = (time.time(), out)
        return web.json_response(out)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_trade(req):
    """POST /api/trade — bracket-ордер с графика.
    {sym, side:BUY|SELL, mode:vst|live, lev, sl, tp, size:{kind:risk|usd|pct, v}}
    risk — % депозита, теряемый на стопе (объём считается от расстояния до SL);
    usd / pct — маржа в долларах / процентах депозита, объём = маржа × плечо."""
    if not _is_local(req):
        return web.json_response({"error": "торговля только с localhost"}, status=403)
    try:
        q = await req.json()
    except Exception:
        q = {}
    sym = str(q.get("sym") or "").upper()
    side = "BUY" if str(q.get("side", "")).upper() == "BUY" else "SELL"
    mode = "live" if q.get("mode") == "live" else "vst"
    lev = max(1, min(int(q.get("lev") or 5), 125))
    sl, tp = float(q.get("sl") or 0), float(q.get("tp") or 0)
    size = q.get("size") or {}
    kind, v = str(size.get("kind") or "risk"), float(size.get("v") or 0)
    if not sym or sl <= 0 or tp <= 0 or v <= 0:
        return web.json_response({"error": "нужны sym, sl, tp и размер"}, status=400)
    px = (_prices().get(sym) or {}).get("px") or 0
    if px <= 0:
        return web.json_response({"error": f"нет цены для {sym}"}, status=400)
    if side == "BUY" and not (sl < px < tp):
        return web.json_response({"error": "для LONG нужно SL < цена < TP"}, status=400)
    if side == "SELL" and not (tp < px < sl):
        return web.json_response({"error": "для SHORT нужно TP < цена < SL"}, status=400)
    cl = await _trade_client(mode)
    if not cl:
        return web.json_response({"error": f"нет рабочего ключа BingX для {mode.upper()}"}, status=400)
    try:
        bal = await asyncio.wait_for(cl.get_balance(), timeout=10) or 0.0
        if kind == "risk":
            risk_usd = bal * v / 100.0
            qty = risk_usd / abs(px - sl)
        else:
            margin = v if kind == "usd" else bal * v / 100.0
            qty = margin * lev / px
        our_sym = f"{sym}/USDT:USDT"
        qty = await cl.quantize_qty(our_sym, qty)
        info = await cl.get_contract_info(our_sym)
        notional = qty * px
        if qty <= 0 or qty < (info.get("min_qty") or 0):
            return web.json_response({"error": f"объём {qty} меньше минимального "
                                               f"{info.get('min_qty')}"}, status=400)
        if notional < (info.get("min_notional") or 0):
            return web.json_response({"error": f"объём ${notional:.2f} меньше минимума "
                                               f"${info.get('min_notional')}"}, status=400)
        need = notional / lev + notional * 0.001      # маржа + комиссия входа/выхода
        if need > bal:
            return web.json_response({"error": f"нужно ${need:.2f} (маржа ${notional/lev:.2f} "
                                               f"+ комиссия), свободно ${bal:.2f}"}, status=400)
        li = {}
        try:
            li = await cl.get_leverage_info(our_sym) or {}
        except Exception:
            pass
        try:                     # SL-safety: при высоком плече ликвидация срабатывает РАНЬШЕ стопа
            from core.execution.calc import clamp_leverage
            safe_lev, _r = clamp_leverage(lev, px, sl, pair_max=None)
            if safe_lev < lev:
                return web.json_response(
                    {"error": f"плечо x{lev} опасно: ликвидация окажется ближе стопа "
                              f"(стоп {abs(px - sl) / px * 100:.2f}%). Максимум x{safe_lev}"},
                    status=400)
        except Exception as _le:
            print(f"[TRADE] liq-safety: {_le}")
        mx = int(li.get("maxLongLeverage" if side == "BUY" else "maxShortLeverage") or 0)
        if mx and lev > mx:                       # биржа не даст больше — считаем по правде
            return web.json_response({"error": f"плечо x{lev} недоступно на {sym}: максимум x{mx}"},
                                     status=400)
        av = float(li.get("availableLongVal" if side == "BUY" else "availableShortVal") or 0)
        if av and notional > av:
            return web.json_response({"error": f"объём ${notional:.2f} больше доступного на "
                                               f"{sym}: биржа даёт ${av:.2f}"}, status=400)
        sl_q = await cl.quantize_price(our_sym, sl)
        tp_q = await cl.quantize_price(our_sym, tp)
        r = await cl.place_bracket_order(our_sym, side, qty, sl_q, tp_q, leverage=lev)
        ok = str(r.get("code")) == "0"
        oid = ((r.get("data") or {}).get("order") or {}).get("orderId")
        if ok:
            _register_manual(our_sym, "LONG" if side == "BUY" else "SHORT", mode, oid,
                             qty, px, sl_q, tp_q)
        print(f"[TRADE] {mode.upper()} {side} {sym} qty={qty} lev={lev} sl={sl_q} tp={tp_q} "
              f"→ code={r.get('code')} msg={r.get('msg')}")
        return web.json_response({"ok": ok, "order_id": oid, "qty": qty, "notional": notional,
                                  "margin": notional / lev, "px": px, "mode": mode,
                                  "error": None if ok else (r.get("msg") or str(r))})
    except Exception as e:
        print(f"[TRADE] ошибка: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_protect(req):
    """POST /api/protect — перенос SL или TP открытой позиции (линию тянут мышью на графике).
    {sym, mode, kind:sl|tp, price}. Порядок: сначала СТАВИМ новый ордер, потом отменяем старый —
    позиция не остаётся без защиты ни на секунду (если новый не прошёл, старый жив)."""
    if not _is_local(req):
        return web.json_response({"error": "торговля только с localhost"}, status=403)
    try:
        q = await req.json()
    except Exception:
        q = {}
    sym = str(q.get("sym") or "").upper()
    mode = "live" if q.get("mode") == "live" else "vst"
    kind = "tp" if q.get("kind") == "tp" else "sl"
    price = float(q.get("price") or 0)
    if not sym or price <= 0:
        return web.json_response({"error": "нужны sym и цена"}, status=400)
    cl = await _trade_client(mode)
    if not cl:
        return web.json_response({"error": f"нет рабочего ключа BingX для {mode.upper()}"}, status=400)
    our_sym = f"{sym}/USDT:USDT"
    try:
        # Separate Isolated: позиций по паре может быть несколько, и openOrders НЕ отдаёт
        # positionId → связать ордер с конкретной позицией нельзя. Поэтому двигаем защиту ВСЕХ
        # позиций монеты: иначе часть осталась бы без стопа.
        plist = [p for p in (await cl.get_positions() or [])
                 if str(p.get("symbol", "")).replace("-USDT", "") == sym
                 and abs(float(p.get("positionAmt") or 0)) > 0]
        if not plist:
            return web.json_response({"error": f"нет открытой позиции по {sym}"}, status=400)
        pos_side = str(plist[0].get("positionSide") or "LONG").upper()
        px = (_prices().get(sym) or {}).get("px") or float(plist[0].get("markPrice") or 0)
        if pos_side == "LONG" and ((kind == "sl" and price >= px) or (kind == "tp" and price <= px)):
            return web.json_response({"error": "для LONG: SL под ценой, TP над ценой"}, status=400)
        if pos_side == "SHORT" and ((kind == "sl" and price <= px) or (kind == "tp" and price >= px)):
            return web.json_response({"error": "для SHORT: SL над ценой, TP под ценой"}, status=400)
        close_side = "SELL" if pos_side == "LONG" else "BUY"
        pr = await cl.quantize_price(our_sym, price)
        old = [o for o in (await cl.get_open_orders(our_sym) or [])
               if str(o.get("symbol", "")).replace("-USDT", "") == sym
               and (("STOP" in str(o.get("type", "")).upper()) if kind == "sl"
                    else ("TAKE_PROFIT" in str(o.get("type", "")).upper()))]
        placed, errs = 0, []
        for p in plist:                     # на каждую позицию — свой ордер (её qty и positionId)
            qty = abs(float(p.get("positionAmt") or 0))
            pid = p.get("positionId")
            if kind == "sl":
                r = await cl.place_stop_order(our_sym, close_side, pos_side, pr, qty, position_id=pid)
            else:
                r = await cl.place_tp_order(our_sym, close_side, pos_side, pr, qty, position_id=pid)
            if str(r.get("code")) == "0":
                placed += 1
            else:
                errs.append(f"{r.get('code')} {r.get('msg')}")
        if not placed:                      # ни один не встал → старую защиту НЕ трогаем
            print(f"[TRADE] {mode.upper()} перенос {kind.upper()} {sym} → отказ: {errs}")
            return web.json_response({"error": "; ".join(errs) or "отказ биржи"}, status=400)
        for o in old:                       # новые стоят — снимаем прежние
            try:
                await cl.cancel_order(our_sym, str(o.get("orderId")))
            except Exception as e:
                print(f"[TRADE] отмена старого {kind}: {e}")
        print(f"[TRADE] {mode.upper()} {kind.upper()} {sym} → {pr} "
              f"(позиций {placed}/{len(plist)}, снято старых {len(old)})")
        return web.json_response({"ok": True, "price": pr, "kind": kind, "n": placed,
                                  "error": "; ".join(errs) or None})
    except Exception as e:
        print(f"[TRADE] protect: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def _cancel_cond(cl, our_sym, sym):
    """Снимает условные ордера (SL/TP) символа. Возвращает сколько снято.
    Нужно после закрытия: BingX не всегда убирает их сам — у VELVET висели ТРИ TP от закрытых
    позиций (14.08), такой ордер однажды сработает по пустому месту."""
    n = 0
    for o in (await cl.get_open_orders(our_sym) or []):
        if str(o.get("symbol", "")).replace("-USDT", "") != sym:
            continue
        t = str(o.get("type", "")).upper()
        if "STOP" not in t and "TAKE_PROFIT" not in t:
            continue          # обычные лимитки-входы не трогаем
        try:
            await cl.cancel_order(our_sym, str(o.get("orderId")))
            n += 1
        except Exception as e:
            print(f"[TRADE] cancel {o.get('orderId')}: {e}")
    return n


async def api_close(req):
    """POST /api/close — закрытие позиции с графика. {sym, mode, part} (part: 1=всю, 0.5=половину).
    Полное: закрываем каждую позицию пары → снимаем её условные ордера → снимаем с учёта.
    Частичное: закрываем долю → переставляем SL/TP на ОСТАТОК (старые висели бы на полный объём).
    Если позиции нет, а условные ордера есть — просто чистим их (уборка хвостов)."""
    if not _is_local(req):
        return web.json_response({"error": "торговля только с localhost"}, status=403)
    try:
        q = await req.json()
    except Exception:
        q = {}
    sym = str(q.get("sym") or "").upper()
    mode = "live" if q.get("mode") == "live" else "vst"
    part = float(q.get("part") or 1.0)
    part = 1.0 if part > 1 or part <= 0 else part
    if not sym:
        return web.json_response({"error": "нужен sym"}, status=400)
    cl = await _trade_client(mode)
    if not cl:
        return web.json_response({"error": f"нет рабочего ключа BingX для {mode.upper()}"}, status=400)
    our_sym = f"{sym}/USDT:USDT"
    try:
        plist = [p for p in (await cl.get_positions() or [])
                 if str(p.get("symbol", "")).replace("-USDT", "") == sym
                 and abs(float(p.get("positionAmt") or 0)) > 0]
        if not plist:
            n = await _cancel_cond(cl, our_sym, sym)
            _close_manual(our_sym)
            return web.json_response({"ok": True, "closed": 0, "cancelled": n,
                                      "msg": f"позиции нет, снято висящих ордеров: {n}"})
        old = [o for o in (await cl.get_open_orders(our_sym) or [])
               if str(o.get("symbol", "")).replace("-USDT", "") == sym] if part < 1 else []
        pos_side = str(plist[0].get("positionSide") or "LONG").upper()
        close_side = "SELL" if pos_side == "LONG" else "BUY"   # сторона ордера SL/TP (reduce)
        # 🔴 close_position_market ждёт сторону ОТКРЫТИЯ (внутри сам инвертирует): BUY=закрыть LONG.
        # Передашь сторону закрытия — биржа ищет противоположную позицию и отвечает
        # 101205 "No position to close" (поймано 14.08 на частичном закрытии).
        open_side = "BUY" if pos_side == "LONG" else "SELL"
        closed, left, errs = 0, 0.0, []
        for p in plist:
            qty_all = abs(float(p.get("positionAmt") or 0))
            pid = p.get("positionId")
            qty = await cl.quantize_qty(our_sym, qty_all * part)
            if qty <= 0:
                continue
            r = await cl.close_position_market(our_sym, open_side, qty,
                                               one_click_on_fail=(part >= 1), position_id=pid)
            if str(r.get("code")) == "0":
                closed += 1
                left += max(0.0, qty_all - qty)
            else:
                errs.append(f"{r.get('code')} {r.get('msg')}")
        if not closed:
            return web.json_response({"error": "; ".join(errs) or "биржа отказала"}, status=400)
        cancelled = await _cancel_cond(cl, our_sym, sym)
        if part >= 1:
            _close_manual(our_sym)
        else:
            # остаток должен остаться под защитой: возвращаем SL/TP на прежние цены, но на остаток
            lv = {}
            for o in old:
                t = str(o.get("type", "")).upper()
                sp = float(o.get("stopPrice") or 0)
                if sp and "STOP" in t:
                    lv["sl"] = sp
                elif sp and "TAKE_PROFIT" in t:
                    lv["tp"] = sp
            rest = await cl.quantize_qty(our_sym, left)
            if rest > 0:
                pid0 = plist[0].get("positionId")
                if lv.get("sl"):
                    await cl.place_stop_order(our_sym, close_side, pos_side, lv["sl"], rest,
                                              position_id=pid0)
                if lv.get("tp"):
                    await cl.place_tp_order(our_sym, close_side, pos_side, lv["tp"], rest,
                                            position_id=pid0)
        print(f"[TRADE] {mode.upper()} CLOSE {sym} part={part} позиций={closed}/{len(plist)} "
              f"ордеров снято={cancelled}")
        return web.json_response({"ok": True, "closed": closed, "cancelled": cancelled,
                                  "part": part, "error": "; ".join(errs) or None})
    except Exception as e:
        print(f"[TRADE] close: {e}")
        return web.json_response({"error": str(e)}, status=500)


def _close_manual(symbol):
    """Снимает ручную позицию с учёта (иначе строка маскировала бы настоящий orphan)."""
    try:
        c = sqlite3.connect(_DB, timeout=5)
        c.execute("UPDATE manual_positions SET closed_at=? WHERE symbol=? AND closed_at IS NULL",
                  (int(time.time()), symbol))
        c.commit()
        c.close()
    except Exception as e:
        print(f"[TRADE] manual_positions close: {e}")


async def api_pair(req):
    """GET /api/pair/{base} — полная строка пары из screener_state."""
    base = req.match_info["base"].upper()
    rows = [r for r in _screener_rows(500) if r["symbol"] == base]
    return web.json_response(rows[0] if rows else {"error": f"{base} нет в скринере"})


# ── ОБЩАЯ ОБОЛОЧКА ТРЁХ СТРАНИЦ (Егор 14.08: «разделился на три страницы, нужен UX») ──
# Кокпит/фильтр/монитор были тремя вёрстками со своими токенами и разрозненными ссылками.
# Общие токены + одна навигация: видно, где ты, и переход в один клик. Плюс базовая доступность:
# видимый фокус для клавиатуры, ≥34px высота пунктов, уважение prefers-reduced-motion.
_CSS_BASE = """
:root{--bg:#0b0e14;--card:#141922;--line:#232a36;--tx:#d1d6e0;--dim:#7b8496;--dim2:#5b6480;
 --up:#26a69a;--dn:#ef5350;--gold:#e0b25c;--y:#ffca28;--o:#ff9800;--r:#ef5350;--g:#26a69a}
*{box-sizing:border-box;margin:0}
a{color:inherit}
:focus-visible{outline:2px solid var(--gold);outline-offset:2px;border-radius:4px}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
.nav{display:flex;align-items:center;gap:2px;padding:0 4px;border-bottom:1px solid var(--line);
 background:var(--card);flex:0 0 auto}
.nav a{display:inline-flex;align-items:center;min-height:34px;padding:0 14px;text-decoration:none;
 color:var(--dim);font-size:13px;border-bottom:2px solid transparent;transition:.12s}
.nav a:hover{color:var(--tx);background:rgba(255,255,255,.03)}
.nav a[aria-current=page]{color:var(--gold);border-bottom-color:var(--gold);font-weight:600}
.nav .brand{font-weight:700;color:var(--tx);font-size:13px;letter-spacing:.4px;padding:0 12px 0 8px}
.nav .sp{margin-left:auto;color:var(--dim);font-size:12px;padding-right:10px}
"""


def _nav(active):
    """Одна навигация на всех страницах. Текущий раздел помечен и цветом, и aria-current,
    и жирностью — не только цветом (дальтонизм)."""
    items = [("/", "Повестка", "что делать прямо сейчас"),
             ("/cockpit", "Кокпит", "состояние рынка подробно"),
             ("/filter", "Фильтр", "конструктор условий"),
             ("/monitor", "Монитор", "сетка графиков"),
             ("/guide", "Инструкция", "как всем этим пользоваться")]
    out = ['<nav class=nav aria-label="Разделы терминала"><span class=brand>OKO</span>']
    for href, name, hint in items:
        cur = ' aria-current=page' if href == active else ''
        out.append(f'<a href="{href}"{cur} title="{hint}">{name}</a>')
    out.append('<span class=sp id=navstat></span></nav>')
    return "".join(out)


_AGENDA_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKO · Повестка</title><style>__CSS_BASE__
body{background:var(--bg);color:var(--tx);font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:16px 18px 40px}
.mode{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--card);
 border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.mode .big{font-size:19px;font-weight:700}
.mode .hint{color:var(--dim);font-size:13px}
.mode .brd{margin-left:auto;text-align:right;font-size:12px;color:var(--dim)}
.mode .brd b{display:block;font-size:20px;color:var(--tx)}
.light{display:flex;align-items:center;gap:12px;margin-top:10px;border-radius:12px;
 padding:12px 16px;border:1px solid var(--line);font-size:14px}
.light .dot{width:12px;height:12px;border-radius:50%;flex:0 0 auto}
.light.green{background:rgba(38,166,154,.08);border-color:#134a44}
.light.green .dot{background:var(--up)}
.light.yellow{background:rgba(255,202,40,.08);border-color:#5a4a12}
.light.yellow .dot{background:var(--y)}
.light.red{background:rgba(239,83,80,.08);border-color:#5a1f1e}
.light.red .dot{background:var(--dn)}
.light b{font-weight:700}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.col h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
 margin:4px 0 8px;display:flex;align-items:center;gap:8px}
.col h2 .n{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1px 8px;
 font-size:11px;color:var(--tx)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;
 margin-bottom:10px;transition:.12s}
.card:hover{border-color:#3a4658}
.card.long{border-left:3px solid var(--up)}
.card.short{border-left:3px solid var(--dn)}
.card .hd{display:flex;align-items:baseline;gap:10px}
.card .sym{font-size:17px;font-weight:700}
.card .sd{font-size:11px;font-weight:700;padding:2px 7px;border-radius:5px}
.sd.long{color:var(--up);background:rgba(38,166,154,.12)}
.sd.short{color:var(--dn);background:rgba(239,83,80,.12)}
.card .sc{margin-left:auto;color:var(--dim);font-size:12px}
.why{display:flex;gap:5px;flex-wrap:wrap;margin:8px 0}
.why span{font-size:11px;color:var(--dim);background:var(--bg);border:1px solid var(--line);
 border-radius:6px;padding:2px 7px}
.why span.k{color:var(--gold);border-color:#5a4a28}
.lv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0;font-variant-numeric:tabular-nums}
.lv div{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 8px}
.lv .t{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.lv .v{font-size:13px;font-weight:600;margin-top:1px}
.lv .tp .v{color:var(--up)}.lv .sl .v{color:var(--dn)}
.meta{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--dim);margin-top:2px}
.meta b{color:var(--tx)}
.meta .warn{color:var(--o)}
.act{display:flex;gap:8px;margin-top:10px}
.btn{cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--tx);
 border-radius:8px;padding:7px 12px;font:inherit;font-size:12.5px;text-decoration:none;
 display:inline-flex;align-items:center;gap:6px;min-height:34px;transition:.12s}
.btn:hover{border-color:#3a4658;background:rgba(255,255,255,.03)}
.btn.pri{color:var(--gold);border-color:#5a4a28;background:rgba(224,178,92,.1)}
.empty{color:var(--dim);font-size:13px;padding:14px;background:var(--card);
 border:1px dashed var(--line);border-radius:12px;text-align:center}
.skip{margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.skip h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin-bottom:8px}
.skip .row{display:flex;gap:10px;align-items:center;padding:4px 0;font-size:12.5px;
 border-top:1px solid var(--line)}
.skip .row:first-of-type{border-top:0}
.skip .s{font-weight:600;min-width:70px}
.skip .r{color:var(--dim)}
.upd{color:var(--dim);font-size:12px;margin-top:12px}
</style></head><body>
__NAV__
<div class=wrap>
  <div class=mode id=mode>…</div>
  <div class="light" id=light></div>
  <div class=cols>
    <div class=col><h2>🟢 Лонг <span class=n id=nlong>0</span></h2><div id=longs></div></div>
    <div class=col><h2>🔴 Шорт <span class=n id=nshort>0</span></h2><div id=shorts></div></div>
  </div>
  <div class=skip id=skip style=display:none></div>
  <div class=upd id=upd></div>
</div>
<script>
function card(x){
 var p=x.plan||{};
 var why=(x.why||[]).map(function(w){
   var key=w.indexOf('кластер')===0||w.indexOf('див')===0;
   return '<span class="'+(key?'k':'')+'">'+w+'</span>';}).join('');
 var costWarn=p.cost_of_stop>15;
 var q='/monitor?sym='+x.sym+'&side='+p.side+'&entry='+p.entry+'&sl='+p.sl+'&tp='+p.tp;
 return '<div class="card '+x.side+'">'+
  '<div class=hd><span class=sym>'+x.sym+'</span>'+
   '<span class="sd '+x.side+'">'+(x.side=='long'?'LONG':'SHORT')+'</span>'+
   '<span class=sc>score '+(x.score||0).toFixed(1)+'</span></div>'+
  '<div class=why>'+why+'</div>'+
  '<div class=lv>'+
   '<div><div class=t>вход</div><div class=v>'+p.entry+'</div></div>'+
   '<div class=sl><div class=t>стоп −'+p.risk_pct+'%</div><div class=v>'+p.sl+'</div></div>'+
   '<div class=tp><div class=t>цель +'+p.rew_pct+'%</div><div class=v>'+p.tp+'</div></div>'+
  '</div>'+
  '<div class=meta><span>RR <b>'+p.rr+'</b></span>'+
   (p.max_lev?('<span title="при большем плече ликвидация окажется ближе стопа — вынесет раньше защиты">плечо ≤ <b>x'+p.max_lev+'</b></span>'):'')+
   '<span class="'+(costWarn?'warn':'')+'">косты <b>'+p.cost_of_stop+'%</b> от стопа</span>'+
   (x.turn!=null?('<span>оборот <b>'+x.turn+'</b> млн</span>'):'')+
   (x.spread!=null?('<span>спред <b>'+x.spread+'%</b></span>'):'')+'</div>'+
  '<div class=act><a class="btn pri" href="'+q+'" target=_blank>→ на график с планом</a>'+
   '<a class=btn href="https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.sym+'USDT.P&interval=240" target=_blank>TW</a></div>'+
 '</div>';
}
async function load(){
 try{
  var r=await fetch('/api/agenda',{cache:'no-store'});var d=await r.json();
  var b=d.breadth||{};
  document.getElementById('mode').innerHTML=
   '<div><div class=big>'+d.mode+'</div><div class=hint>'+d.hint+'</div></div>'+
   '<div class=brd>ширина падения<b>'+(b.day!=null?b.day:b.now)+' / '+b.hi+'</b>'+
    'фаза '+(d.phase||'—')+'</div>';
  var L=document.getElementById('light');
  L.className='light '+d.light;
  L.innerHTML='<span class=dot></span><span><b>'+
   (d.light=='green'?'Работаем':d.light=='yellow'?'Осторожно':'Сегодня не торгуем')+
   '.</b> '+d.reason+'</span>';
  document.getElementById('longs').innerHTML=(d.long||[]).map(card).join('')||
   '<div class=empty>нет лонг-кандидатов, прошедших фильтры</div>';
  document.getElementById('shorts').innerHTML=(d.short||[]).map(card).join('')||
   '<div class=empty>нет шорт-кандидатов, прошедших фильтры</div>';
  document.getElementById('nlong').textContent=(d.long||[]).length;
  document.getElementById('nshort').textContent=(d.short||[]).length;
  var sk=document.getElementById('skip');
  if((d.skipped||[]).length){sk.style.display='';
   sk.innerHTML='<h3>Отсеяны — и почему</h3>'+(d.skipped).map(function(x){
    return '<div class=row><span class="s '+x.side+'" style="color:'+(x.side=='long'?'var(--up)':'var(--dn)')+'">'+
     x.sym+'</span><span class=r>'+x.drop+'</span></div>';}).join('');
  }else sk.style.display='none';
  document.getElementById('upd').textContent='обновлено '+new Date(d.ts*1000).toLocaleTimeString('ru')+
   ' · список пересобирается каждые 60 секунд';
 }catch(e){
  document.getElementById('light').className='light red';
  document.getElementById('light').innerHTML='<span class=dot></span>нет связи с терминалом';
 }
}
load();setInterval(load,60000);
</script></body></html>"""


_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKO · Структура рынка</title><style>__CSS_BASE__
body{background:var(--bg);color:var(--tx);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{padding:18px;max-width:1100px;margin:0 auto}
h1{font-size:17px;font-weight:600;letter-spacing:.3px}h1 small{color:var(--dim);font-weight:400;font-size:12px}
.row{display:grid;gap:14px;margin-top:16px}.tri{grid-template-columns:repeat(3,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.card .lbl{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.card .val{font-size:34px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
.card .d{font-size:13px;margin-top:2px}.up{color:var(--up)}.dn{color:var(--dn)}
.banner{border-radius:12px;padding:16px 18px;font-size:16px;font-weight:600;border:1px solid var(--line)}
.b-y{background:rgba(255,202,40,.10);border-color:#5a4a12;color:var(--y)}
.b-g{background:rgba(38,166,154,.10);border-color:#134a44;color:var(--g)}
.b-r{background:rgba(239,83,80,.10);border-color:#5a1f1e;color:var(--r)}
.b-o{background:rgba(255,152,0,.10);border-color:#5a3d0f;color:var(--o)}
.b-w{background:var(--card)}
.meta{color:var(--dim);font-size:12px;margin-top:6px}.phase{margin-top:14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--up);margin-right:6px;animation:p 2s infinite}
@keyframes p{50%{opacity:.3}}.err{color:var(--dn)}
.gold{color:#e0b25c}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0 4px}
.chip{font-size:12px;padding:4px 11px;border-radius:20px;border:1px solid var(--line);color:var(--dim);
  background:transparent;cursor:pointer;user-select:none;transition:.15s;font-family:inherit}
.chip:hover{border-color:#3a4658;color:var(--tx)}
.chip.on{background:rgba(224,178,92,.14);border-color:#5a4a28;color:#e0b25c}
#scr th{padding:6px 8px;cursor:pointer;white-space:nowrap;user-select:none}
#scr th:hover{color:var(--tx)}#scr th .ar{opacity:.5;font-size:9px}
#scr td{padding:6px 8px;border-top:1px solid var(--line)}
#scr tbody tr{transition:background .1s}#scr tbody tr:hover{background:rgba(255,255,255,.03)}
#scr a{color:inherit;text-decoration:none}#scr a:hover{color:#e0b25c;text-decoration:underline}
.sbar{display:inline-block;height:5px;border-radius:3px;background:linear-gradient(90deg,#5a4a28,#e0b25c);vertical-align:middle;margin-left:6px}
.lk{color:var(--dim);font-size:10.5px;letter-spacing:.03em}
.ipwrap{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.ipc{display:inline-flex;align-items:center;gap:5px;padding:6px 10px;border-radius:9px;
  background:var(--bg);border:1px solid var(--line);font-size:13px;text-decoration:none;color:var(--tx);transition:.12s}
.ipc:hover{border-color:#5a4a28;color:#e0b25c}
.ipc b{font-weight:600}.ipc .tg{font-size:12px;letter-spacing:-1px}
.ipc.hot{border-color:#5a4a28}
.sbgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:9px;margin-top:10px}
.sbcell{border:1px solid var(--line);border-radius:9px;padding:9px 11px;background:var(--bg)}
.sbsrc{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.sbnet{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.sbmeta{font-size:11px;color:var(--dim2,#5b6480);margin-top:2px}
.sbbar{height:4px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}
.sbbar span{display:block;height:100%}
</style></head><body>
__NAV__
<div class=wrap>
<h1><span class=dot></span>Структура рынка <small id=age>…</small></h1>
<div class="row tri" id=tri></div>
<div class=row style=margin-top:14px><div class=banner b-w id=rot>…</div></div>
<div class="card phase" id=phase></div>
<div class=card style=margin-top:14px>
  <div class=lbl>🌊 ШИРИНА ПАДЕНИЯ <span class=dim style=text-transform:none>· сколько монет падает
    ОДНОВРЕМЕННО (4h: ATRTrend↑ + WT&lt;−60) · порог 61 → фейд PF 1.62→4.22 (p=0.00026)</span></div>
  <div id=breadth style=margin-top:6px>…</div>
</div>
<div class=card style=margin-top:14px>
  <div class=lbl>⚖️ ФОРВАРД-ТАБЛО · net% источников <span class=dim style=text-transform:none>· чистая эра ≥11.07 · гейт 30 net+ → реальные деньги</span></div>
  <div class=sbgrid id=board></div>
</div>
<div class=card style=margin-top:14px>
  <div class=lbl>🎯 В ИГРЕ сейчас <span class=dim style=text-transform:none>· радар🚀🌱🔨 · OTE🎯 · DC🤖 · хайп🔥 (сортировка: конфлюэнция внимания)</span></div>
  <div class=ipwrap id=inplay></div>
</div>
<div class=card style=margin-top:14px>
  <div class=lbl>🔭 СКРИНЕР OKO-SM · нога старшего 4h · схождения · WT <span id=scount class=dim></span></div>
  <div class=chips id=filters>
    <span class=chip data-f=all>все</span>
    <span class=chip data-f=zone>🎯 в зоне</span>
    <span class=chip data-f=approach>→ подход</span>
    <span class=chip data-f=long>LONG</span>
    <span class=chip data-f=short>SHORT</span>
    <span class=chip data-f=conf>score ≥ 3</span>
    <span class=chip data-f=cluster title="≥2 монеты в ту же сторону">🔗 кластер ≥2</span>
    <span class=chip data-f=breakout>⚡ пробой (≤3% к уровню)</span>
  </div>
  <div style="overflow-x:auto;margin-top:6px">
  <table id=scr style="width:100%;border-collapse:collapse;font-size:12.5px;text-align:left;font-variant-numeric:tabular-nums">
    <thead><tr style="color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.05em">
      <th data-s=symbol>пара</th><th data-s=trend>нога</th><th data-s=retr>откат</th>
      <th data-s=status>статус</th><th data-s=cluster title="сколько монет прямо сейчас дают сигнал в ту же сторону и стоят в зоне/подходе. Одиночка PF 0.67 против кластера ≥2 — 2.24">кластер</th><th data-s=conf_score>score <span class=ar>▼</span></th>
      <th data-s=res_dist>уровень ↑↓</th><th>схождения</th><th data-s=wt>WT</th><th data-s=div>див</th><th></th></tr></thead>
    <tbody></tbody>
  </table></div>
</div>
<div class=meta id=foot></div>
</div>
<script>
function arrow(x){return x>0.001?'<span class=up>▲ '+x.toFixed(3)+'</span>':x<-0.001?'<span class=dn>▼ '+x.toFixed(3)+'</span>':'· '+x.toFixed(3)}
function bcls(v){if(!v)return'b-w';if(v.includes('🟢'))return'b-g';if(v.includes('🟡'))return'b-y';if(v.includes('🔴'))return'b-r';if(v.includes('🟠'))return'b-o';return'b-w'}
async function tick(){
 try{const r=await fetch('/api/structure',{cache:'no-store'});const d=await r.json();
  const dm=d.dominance,rt=d.rotation;
  const du=rt?rt.d_usdtd:0,db=rt?rt.d_btcd:0,da=rt?rt.d_alt_pct:0;
  const cards=[['USDT.D',dm?dm.usdt_d:null,du,'пп'],['BTC.D',dm?dm.btc_d:null,db,'пп'],['ALT.D',dm?dm.alt_d:null,da,'% mcap']];
  document.getElementById('tri').innerHTML=cards.map(c=>
   '<div class=card><div class=lbl>'+c[0]+'</div><div class=val>'+(c[1]!=null?c[1].toFixed(2)+'%':'—')+'</div><div class=d>'+arrow(c[2])+' <span style=color:var(--dim)>'+c[3]+' /'+(rt?rt.window_h:'?')+'ч</span></div></div>').join('');
  const rot=document.getElementById('rot');rot.className='banner '+bcls(rt&&rt.verdict);rot.textContent=rt?rt.verdict:'ротация: нет данных (CMC)';
  const ph=d.phase;document.getElementById('phase').innerHTML=ph?('<div class=lbl>ФАЗА РЫНКА</div><div style=font-size:18px;font-weight:600;margin-top:4px>'+ph.phase+'</div><div class=meta>'+(ph.detail||'')+'</div>'):'<div class=lbl>ФАЗА</div><div class=meta>нет данных phase_state</div>';
  const cov=dm?(' · покрытие '+(dm.cov_mcap*100).toFixed(0)+'% mcap'):'';
  document.getElementById('foot').textContent='total '+(dm?('$'+(dm.total_mcap/1e12).toFixed(3)+'T'):'—')+cov+' · self-computed (без TW/прокси)';
  document.getElementById('age').textContent='обновлено '+new Date(d.ts*1000).toLocaleTimeString('ru');
 }catch(e){document.getElementById('age').innerHTML='<span class=err>сервер недоступен</span>';}
}
var SR={rows:[],sort:'conf_score',dir:-1,filt:'all'};
function lvlCell(x){
 var up=(x.res_lvl!=null)?{l:x.res_lvl,t:x.res_touches,d:x.res_dist,a:'↑',c:'var(--up)',s:'лонг-пробой'}:null;
 var dn=(x.sup_lvl!=null)?{l:x.sup_lvl,t:x.sup_touches,d:x.sup_dist,a:'↓',c:'var(--dn)',s:'шорт-пробой'}:null;
 var n=(up&&dn)?(Math.abs(up.d)<=Math.abs(dn.d)?up:dn):(up||dn);
 if(!n)return '<span class=dim>—</span>';
 var near=Math.abs(n.d)<=3;
 return '<span title="'+n.s+'" style="color:'+(near?'#e0b25c':n.c)+'">'+n.a+(+n.l).toPrecision(4)+
   '</span> <span class=lk>×'+(n.t||0)+' '+(n.d>0?'+':'')+(n.d||0).toFixed(1)+'%</span>';
}
// ДИВ: тип (R=regular разворотная, H=hidden продолжения; +бычья / −медвежья) и свежесть в барах.
// Свежая (≤3 бара) — ярко, старше — приглушённо: дивергенция 10 баров назад на 4h это ~2 суток.
function divCell(x){
 var t=x.div_type;if(!t)return '<span class=dim>—</span>';
 var bull=t.indexOf('+')>0,a=(x.div_age==null?0:x.div_age);
 var col=bull?'var(--up)':'var(--dn)';
 return '<span style="color:'+col+';opacity:'+(a<=3?1:.55)+'" title="'+
  (t[0]=='R'?'regular — разворотная':'hidden — продолжение тренда')+
  ', обнаружена '+a+' бар(ов) назад">'+t+'</span> <span class=lk>'+a+'б</span>';}
// Кластер: ≥2 монеты в ту же сторону = PF 2.24 против 0.67 у одиночки. Показываем числом,
// одиночек приглушаем — чтобы высокий score одиночного сетапа не выглядел сильнее кластерного.
function cluCell(x){
 var n=x.cluster||0;
 if(!n)return '<span class=dim>—</span>';
 var col=n>=2?'var(--up)':'var(--dim)';
 var tip=n>=2?('вместе с: '+(x.cluster_peers||[]).join(', ')):'одиночный сигнал — PF 0.67 против 2.24 у кластера';
 return '<span style="color:'+col+';font-weight:'+(n>=2?700:400)+'" title="'+tip+'">×'+n+'</span>';}
function scRender(){
 var f=SR.filt,rows=SR.rows.filter(function(x){
  if(f=='zone')return x.in_zone;if(f=='approach')return x.approach;
  if(f=='long')return x.trend=='long';if(f=='short')return x.trend=='short';
  if(f=='conf')return x.conf_score>=3;
  if(f=='cluster')return (x.cluster||0)>=2;
  if(f=='breakout')return (x.res_dist!=null&&x.res_dist<=3)||(x.sup_dist!=null&&x.sup_dist>=-3);return true;});
 var k=SR.sort;rows.sort(function(a,b){
  if(k=='symbol'||k=='trend')return SR.dir*String(a[k]||'').localeCompare(String(b[k]||''));
  var va=k=='status'?(a.in_zone?2:a.approach?1:0):(a[k]||0),vb=k=='status'?(b.in_zone?2:b.approach?1:0):(b[k]||0);
  return SR.dir*(va-vb);});
 document.getElementById('scount').textContent='· '+rows.length;
 var mx=Math.max.apply(null,rows.map(function(x){return x.conf_score||0}).concat([5]));
 document.querySelector('#scr tbody').innerHTML=rows.map(function(x){
  var st=x.in_zone?'<span class=gold>🎯 в зоне</span>':(x.approach?'→ подход':'—');
  var legc=x.trend=='long'?'var(--up)':'var(--dn)';
  var hits=(JSON.parse(x.hits||'[]')).slice(0,3).join(' ∩ ')||'—';
  var bw=Math.round(36*(x.conf_score||0)/mx);
  var tw='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.symbol+'USDT.P&interval=240';
  var bx='https://bingx.com/ru/perpetual/'+x.symbol+'-USDT';
  return '<tr>'+
   '<td style="font-weight:600"><a href="'+tw+'" target=_blank>'+x.symbol+'</a></td>'+
   '<td style="color:'+legc+'">'+(x.trend||'—').toUpperCase()+
     (x.vs_phase?' <span title="сигнал против фазы рынка ('+(SR.phase||'')+') — не запрет, но повод проверить" style=color:var(--o)>⚠</span>':'')+'</td>'+
   '<td>'+(x.retr!=null?Math.round(x.retr*100)+'%':'—')+'</td>'+
   '<td>'+st+(x.noise?' <span style=color:var(--dim)>шум</span>':'')+'</td>'+
   '<td>'+cluCell(x)+'</td>'+
   '<td style="font-weight:600;color:'+(x.conf_score>=3?'#e0b25c':'inherit')+'">'+(x.conf_score||0).toFixed(1)+
     '<span class=sbar style="width:'+bw+'px"></span></td>'+
   '<td>'+lvlCell(x)+'</td>'+
   '<td style="color:var(--dim);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+hits+'</td>'+
   '<td>'+(x.wt>0?'+':'')+Math.round(x.wt||0)+'</td>'+
   '<td>'+divCell(x)+'</td>'+
   '<td class=lk><a href="'+bx+'" target=_blank>BINGX↗</a></td></tr>';
 }).join('')||'<tr><td colspan=10 style="padding:10px;color:var(--dim)">скринер наполняется (цикл вахты 15 мин)…</td></tr>';
}
async function scr(){try{var r=await fetch('/api/screener?limit=150',{cache:'no-store'});var d=await r.json();
 SR.rows=d.rows||[];SR.phase=d.phase||'';scRender();}catch(e){}}
// Расшифровка значков при наведении — кто именно обратил внимание на монету
var TAGH=[['🚀','радар: ПАМП — всплеск объёма и цены'],['🌱','радар: ПРУЖИНА — сжатие перед выносом'],
 ['🔨','радар: НАКОПЛЕНИЕ — набор позиции в диапазоне'],['🎯','скринер OKO-SM: цена в OTE-зоне ноги 4h (цифра = score схождений)'],
 ['🤖','DC-советник держит по монете сделку'],['🔥','хайп: монета в тренде CoinGecko'],
 ['↑','сторона LONG'],['↓','сторона SHORT']];
function tagHint(t){
 var out=[];TAGH.forEach(function(p){if(t.indexOf(p[0])>=0)out.push(p[0]+' — '+p[1]);});
 return (out.join('\\n')||t)+'\\n\\nЧем больше значков, тем выше конфлюэнция внимания.';}
async function ip(){try{var r=await fetch('/api/inplay',{cache:'no-store'});var d=await r.json();
 document.getElementById('inplay').innerHTML=(d.coins||[]).map(function(x){
  var multi=(x.tags.match(/[🚀🌱🔨🎯🤖🔥]/gu)||[]).length>=2;
  var tw='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.sym+'USDT.P&interval=240';
  return '<a class="ipc'+(multi?' hot':'')+'" href="'+tw+'" target=_blank title="'+
   tagHint(x.tags).replace(/"/g,'&quot;')+'"><b>'+x.sym+'</b><span class=tg>'+x.tags+'</span></a>';
 }).join('')||'<span class=dim style=font-size:13px>тихо — активных сетапов нет</span>';
}catch(e){}}
document.querySelectorAll('#scr th[data-s]').forEach(function(th){th.addEventListener('click',function(){
 var k=th.getAttribute('data-s');SR.dir=(SR.sort==k)?-SR.dir:-1;SR.sort=k;
 document.querySelectorAll('#scr th .ar').forEach(function(a){a.remove()});
 var ar=document.createElement('span');ar.className='ar';ar.textContent=SR.dir<0?' ▼':' ▲';th.appendChild(ar);scRender();});});
document.querySelectorAll('#filters .chip').forEach(function(ch){ch.addEventListener('click',function(){
 document.querySelectorAll('#filters .chip').forEach(function(c){c.classList.remove('on')});
 ch.classList.add('on');SR.filt=ch.getAttribute('data-f');scRender();});});
document.querySelector('#filters .chip[data-f=all]').classList.add('on');
async function brd(){
 try{var r=await fetch('/api/breadth',{cache:'no-store'});var d=await r.json();
  var n=d.day!=null?d.day:d.now, wide=n>=d.hi;
  var pct=Math.min(100,Math.round(100*n/d.hi));
  document.getElementById('breadth').innerHTML=
   '<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">'+
    '<span style="font-size:32px;font-weight:700;color:'+(wide?'var(--g)':'var(--tx)')+'">'+n+'</span>'+
    '<span style=color:var(--dim)>монет за 24ч · сейчас '+d.now+' · вселенная '+d.universe+'</span>'+
    '<span style="margin-left:auto;font-weight:600;color:'+(wide?'var(--g)':'var(--dim)')+'">'+
     (wide?'ШИРОКОЕ ПАДЕНИЕ — фейд в силе':'узко — фейд слабый (нужно ≥'+d.hi+')')+'</span></div>'+
   '<div style="height:6px;border-radius:3px;background:var(--line);margin-top:8px;overflow:hidden">'+
    '<span style="display:block;height:100%;width:'+pct+'%;background:'+(wide?'var(--g)':'#5a4a28')+'"></span></div>'+
   (d.syms&&d.syms.length?('<div style=margin-top:8px;color:var(--dim);font-size:12px>льют сейчас: '+
     d.syms.join(' · ')+'</div>'):'');
 }catch(e){}}
async function sb(){try{var r=await fetch('/api/scoreboard',{cache:'no-store'});var d=await r.json();var g=d.gate||30;
 document.getElementById('board').innerHTML=(d.board||[]).map(function(x){
  var v=x.vst,s=x.sim;                              // VST = гейт (реал исполнение); SIM = shadow-research
  var prim=v||s,shadow=!v&&s;                       // нет VST → показываем SIM как shadow
  if(!prim)return '<div class=sbcell><div class=sbsrc>'+x.src+'</div><div class=sbnet style=color:var(--dim)>—</div><div class=sbmeta>нет сделок</div></div>';
  var pos=prim.net>0,c=pos?'var(--up)':'var(--dn)';
  var prog=Math.min(100,Math.round(100*((v?v.n:0))/g));
  return '<div class=sbcell><div class=sbsrc>'+x.src+(shadow?' <span style=color:#e0b25c>shadow</span>':'')+'</div>'+
   '<div class=sbnet style="color:'+c+'">'+(pos?'+':'')+prim.net.toFixed(2)+'%</div>'+
   '<div class=sbmeta>'+(v?('VST n '+v.n+'/'+g+' · WR '+v.wr+'%'):('SIM n '+s.n+' · WR '+s.wr+'%'))+
     (v&&s?(' <span style=color:var(--dim2)>· sim '+(s.net>0?'+':'')+s.net.toFixed(2)+'%</span>'):'')+'</div>'+
   '<div class=sbbar><span style="width:'+prog+'%;background:'+c+'"></span></div></div>';
 }).join('');
}catch(e){}}
tick();scr();ip();sb();brd();setInterval(tick,30000);setInterval(scr,60000);setInterval(ip,60000);setInterval(sb,120000);setInterval(brd,120000);
</script></body></html>"""


def _page(html, active):
    """Собирает страницу: общие токены + навигация с отметкой текущего раздела."""
    return html.replace("__CSS_BASE__", _CSS_BASE).replace("__NAV__", _nav(active))


async def agenda_page(_req):
    """GET / — ПОВЕСТКА ДНЯ: главный экран. Режим рынка → светофор → готовые планы сделок.
    Кокпит уехал на /cockpit как «подробности» (решение Егора 18.08)."""
    return web.Response(text=_page(_AGENDA_HTML, "/"), content_type="text/html",
                        headers={"Cache-Control": "no-store"})


async def index(_req):
    return web.Response(text=_page(_HTML, "/cockpit"), content_type="text/html")


_FILTER_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKO · Фильтр-конструктор</title><style>__CSS_BASE__
body{background:var(--bg);color:var(--tx);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
 padding-bottom:64px}
.wrap{padding:16px 18px;max-width:1180px;margin:0 auto}
h1{font-size:17px;font-weight:600;display:flex;align-items:center;gap:10px}
h1 .st{color:var(--dim);font-size:12px;font-weight:400}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:10px}
.sect{padding:10px 14px}
.sect+.sect{border-top:1px solid var(--line)}
.lbl{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em;
 margin-bottom:8px;display:flex;align-items:center;gap:8px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:13px}
.grp{display:inline-flex;align-items:center;gap:5px;background:var(--bg);border:1px solid var(--line);
 border-radius:8px;padding:5px 9px;min-height:32px;transition:.12s}
.grp.act{border-color:#5a4a28;background:rgba(224,178,92,.07)}
.grp b{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
.grp.act b{color:var(--gold)}
input,select{background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:6px;
 padding:3px 6px;font:inherit;font-size:12.5px;min-height:24px}
input[type=number]{width:56px}
input[type=checkbox]{accent-color:var(--gold);cursor:pointer;width:14px;height:14px}
label{cursor:pointer;user-select:none;display:inline-flex;align-items:center;gap:5px}
select{cursor:pointer}
/* ── строка ТФ: свёрнутая показывает сводку, развёрнутая — поля ── */
.tf{border-top:1px solid var(--line)}
.tf:first-child{border-top:0}
.tfhd{display:flex;align-items:center;gap:10px;padding:9px 14px;cursor:pointer;user-select:none}
.tfhd:hover{background:rgba(255,255,255,.02)}
.tfhd .nm{font-weight:700;color:var(--gold);min-width:34px;font-size:13px}
.tfhd .sum{color:var(--dim);font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tfhd .sum b{color:var(--tx);font-weight:600}
.tfhd .cnt{background:rgba(224,178,92,.14);color:var(--gold);border-radius:10px;padding:1px 8px;
 font-size:11px;font-weight:700}
.tfhd .ar{color:var(--dim);font-size:10px;transition:.15s}
.tf.open .tfhd .ar{transform:rotate(90deg)}
.tfbody{display:none;padding:2px 14px 12px}
.tf.open .tfbody{display:block}
.tf .note{color:var(--dim2);font-size:11px;margin-left:4px}
/* ── нижняя панель результата ── */
.bar{position:fixed;left:0;right:0;bottom:0;z-index:40;background:var(--card);
 border-top:1px solid var(--line);padding:8px 18px;display:flex;align-items:center;gap:14px;
 box-shadow:0 -6px 24px rgba(0,0,0,.35)}
.bar .n{font-size:22px;font-weight:700;color:var(--gold);font-variant-numeric:tabular-nums}
.bar .of{color:var(--dim);font-size:12px}
.bar .sp{margin-left:auto;display:flex;gap:8px;align-items:center}
.btn{cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--tx);
 border-radius:8px;padding:6px 12px;font:inherit;font-size:12.5px;min-height:32px;transition:.12s}
.btn:hover{border-color:#3a4658;background:rgba(255,255,255,.03)}
.btn.pri{color:var(--gold);border-color:#5a4a28;background:rgba(224,178,92,.1)}
.btn.gh{color:var(--dim)}
.btn.clr{color:var(--dn);border-color:#5a1f1e;background:rgba(239,83,80,.08)}
.btn.clr:hover{background:rgba(239,83,80,.16);border-color:var(--dn)}
.btn.clr[disabled]{opacity:.35;pointer-events:none}
.xs{cursor:pointer;color:var(--dim);font-size:11px;border:1px solid var(--line);border-radius:6px;
 padding:2px 8px;min-height:22px;display:none;align-items:center;gap:4px}
.xs:hover{color:var(--dn);border-color:#5a1f1e}
.xs.on{display:inline-flex}
.lbl .xs{margin-left:auto}
.res{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.res a{color:var(--tx);text-decoration:none;padding:6px 10px;background:var(--bg);
 border:1px solid var(--line);border-radius:8px;font-size:13px;display:inline-flex;
 align-items:center;gap:6px;transition:.12s}
.res a:hover{border-color:var(--gold);color:var(--gold)}
.res small{color:var(--dim);font-size:11px}
.empty{color:var(--dim);font-size:13px;padding:6px 2px}
.spin{width:12px;height:12px;border:2px solid var(--line);border-top-color:var(--gold);
 border-radius:50%;display:inline-block;animation:sp .7s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
</style></head><body>
__NAV__
<div class=wrap>
<h1>Фильтр-конструктор <span class=st id=age></span></h1>

<div class=card>
  <div class=sect>
    <div class=lbl>Рынок <span class=note style=text-transform:none>структура и уровни</span>
      <span class="xs" data-clear=market>✕ сбросить</span></div>
    <div class=row id=g_market></div>
  </div>
  <div class=sect>
    <div class=lbl>Толпа и ликвидность <span class=note style=text-transform:none>деньги и цена входа</span>
      <span class="xs" data-clear=flow>✕ сбросить</span></div>
    <div class=row id=g_flow></div>
  </div>
</div>

<div class=card id=blocks></div>

<div class=card>
  <div class=sect>
    <div class=lbl>Пресеты <span class=note style=text-transform:none>сохранённые наборы условий</span></div>
    <div class=row>
      <input id=ps_name placeholder="имя набора" style=width:150px aria-label="Имя пресета">
      <button class=btn onclick=psSave()>💾 сохранить</button>
      <span id=ps_list class=row style=gap:6px></span>
    </div>
  </div>
</div>

<div class=card>
  <div class=sect>
    <div class=lbl>Найдено <span id=srt class=note style=text-transform:none></span></div>
    <div class=res id=list><div class=empty>задай условия — список появится здесь</div></div>
  </div>
</div>
</div>

<div class=bar>
  <span class=n id=cnt>—</span>
  <span class=of>из <span id=tot>?</span> · активных условий <b id=acnt style=color:var(--tx)>0</b></span>
  <span id=busy></span>
  <span class=sp>
    <button class="btn clr" id=btn_reset onclick=reset() title="снять все условия">✕ сбросить всё</button>
    <button class="btn pri" onclick=openMon()>🖥 монитор графиков →</button>
  </span>
</div>

<script>
var TFS=['5m','15m','1h','4h','1d'];
var SMCTF=['15m','1h','4h'];         // SMC-флаги ведёт шина только по этим ТФ
var DIVOPT='<option value="">—</option><option value=any>любая</option><option value="R+">R+</option>'+
 '<option value="R−">R−</option><option value="H+">H+</option><option value="H−">H−</option>';

// ── ГЛОБАЛЬНЫЕ УСЛОВИЯ: разнесены по смыслу, а не в одну кучу ──
document.getElementById('g_market').innerHTML=
 '<span class=grp><b>режим</b><select id=g_regime><option value="">любой</option><option>TREND_UP</option><option>TREND_DOWN</option><option>RANGE</option></select></span>'+
 '<span class=grp title="цена рядом с пивотом выбранного ТФ и уровня"><b>пивот</b><label><input type=checkbox id=g_pv> ≤</label><input type=number id=g_pvpct value=1.5 step=0.1 style=width:48px>%<select id=g_pvtf><option value="">любой ТФ</option><option value=W>недельный</option><option value=D>дневной</option><option value=M>месячный</option></select><select id=g_pvlv><option value="">любой</option><option>PP</option><option>R1</option><option>R2</option><option>R3</option><option>S1</option><option>S2</option><option>S3</option></select></span>'+
 '<span class=grp title="равные вершины — ликвидность сверху"><label><input type=checkbox id=g_eqh> EQH рядом</label></span>'+
 '<span class=grp title="равные донья — ликвидность снизу"><label><input type=checkbox id=g_eql> EQL рядом</label></span>'+
 '<span class=grp title="цена в зоне отката 0.618–0.786"><label><input type=checkbox id=g_ote> в OTE</label></span>';

document.getElementById('g_flow').innerHTML=
 '<span class=grp title="ставка финансирования BingX"><b>funding</b><input type=number id=g_fmin placeholder=min step=0.005 style=width:56px>..<input type=number id=g_fmax placeholder=max step=0.005 style=width:56px>%</span>'+
 '<span class=grp title="изменение открытого интереса за ~5 минут"><b>OI</b><select id=g_oidir><option value="">—</option><option value=up>рост ≥</option><option value=down>падение ≥</option></select><input type=number id=g_oipct value=2 step=0.5 style=width:46px>%</span>'+
 '<span class=grp title="суточный оборот: ниже 10 млн проскальзывание съедает эдж"><b>оборот ≥</b><input type=number id=g_turn placeholder=любой style=width:60px>млн$</span>'+
 '<span class=grp title="спред BingX: прямой налог на каждый вход"><b>спред ≤</b><input type=number id=g_spread placeholder=0.05 step=0.01 style=width:56px>%</span>'+
 '<span class=grp title="объём последнего ЗАКРЫТОГО бара к средней за 20 баров"><b>объём ≥</b><input type=number id=g_vr placeholder=3 step=0.5 style=width:46px>×<select id=g_vtf><option value=5m>5m</option><option value=15m>15m</option><option value=1h selected>1h</option><option value=4h>4h</option><option value=1d>1d</option></select></span>';

// ── БЛОКИ ТФ: аккордеон, свёрнутый показывает сводку активных условий ──
document.getElementById('blocks').innerHTML=TFS.map(function(tf){
 var full=SMCTF.indexOf(tf)>=0;      // ATRTrend есть у всех ТФ, SMC — только у трёх
 return '<div class=tf id="tf_'+tf+'"><div class=tfhd data-tf="'+tf+'">'+
   '<span class=ar>▶</span><span class=nm>'+tf+'</span>'+
   '<span class=sum id="sum_'+tf+'">все условия выключены</span>'+
   '<span class=cnt id="cn_'+tf+'" style=display:none>0</span>'+
   '<span class="xs" id="cl_'+tf+'" data-cleartf="'+tf+'" title="снять условия этого ТФ">✕</span></div>'+
  '<div class=tfbody><div class=row>'+
   '<span class=grp><b>WT</b><input type=number id="'+tf+'_wtmin" placeholder=min>..<input type=number id="'+tf+'_wtmax" placeholder=max></span>'+
   '<span class=grp><b>зона</b><select id="'+tf+'_wtzone"><option value="">—</option><option>OB</option><option>OS</option><option>N</option></select></span>'+
   '<span class=grp title="кросс WT как СОСТОЯНИЕ: ↑ = wt1 выше сигнальной, держится до обратного пересечения. Поле «≤бар» — дополнительно требовать, чтобы состояние установилось недавно (свежий кросс)"><b>кросс</b><select id="'+tf+'_wtcross"><option value="">—</option><option value=up>↑</option><option value=down>↓</option></select><input type=number id="'+tf+'_crage" placeholder="≤бар" style=width:48px></span>'+
   '<span class=grp title="дивергенция WT: R — разворотная, H — продолжение тренда"><b>див</b><select id="'+tf+'_div">'+DIVOPT+'</select><input type=number id="'+tf+'_divage" placeholder="≤бар" style=width:48px></span>'+
   '<span class=grp><b>ATRTrend</b><select id="'+tf+'_atr"><option value="">—</option><option value=up>↑ вверх</option><option value=down>↓ вниз</option></select></span>'+
   (full?('<span class=grp><label><input type=checkbox id="'+tf+'_obb"> OB↑</label><label><input type=checkbox id="'+tf+'_obr"> OB↓</label><label><input type=checkbox id="'+tf+'_fvb"> FVG↑</label><label><input type=checkbox id="'+tf+'_fvr"> FVG↓</label></span>'+
    '<span class=grp><b>CHoCH</b><select id="'+tf+'_choch"><option value="">—</option><option>UP</option><option>DOWN</option></select></span>'+
    '<span class=grp><b>BOS</b><select id="'+tf+'_bos"><option value="">—</option><option>UP</option><option>DOWN</option></select></span>')
    :'<span class=note>SMC-флаги (OB/FVG/CHoCH/BOS) шина ведёт только по 15m/1h/4h</span>')+
  '</div></div></div>';}).join('');

function num(id){var e=document.getElementById(id);if(!e)return null;var v=e.value;return v===''?null:parseFloat(v);}
function val(id){var e=document.getElementById(id);return e?(e.value||null):null;}
function chk(id){var e=document.getElementById(id);return e?e.checked:false;}

function blockOf(tf){                       // условия одного ТФ + человекочитаемая сводка
 var b={tf:tf},s=[];
 if(num(tf+'_wtmin')!=null){b.wt_min=num(tf+'_wtmin');s.push('WT≥'+b.wt_min);}
 if(num(tf+'_wtmax')!=null){b.wt_max=num(tf+'_wtmax');s.push('WT≤'+b.wt_max);}
 if(val(tf+'_wtzone')){b.wt_zone=val(tf+'_wtzone');s.push('зона '+b.wt_zone);}
 if(val(tf+'_wtcross')){b.wt_cross=val(tf+'_wtcross');
  if(num(tf+'_crage')!=null)b.cross_age=num(tf+'_crage');
  s.push('кросс '+(b.wt_cross=='up'?'↑':'↓')+(b.cross_age!=null?('≤'+b.cross_age+'б'):''));}
 if(val(tf+'_div')){b.div=val(tf+'_div');
  if(num(tf+'_divage')!=null)b.div_age=num(tf+'_divage');
  s.push('див '+b.div+(b.div_age!=null?('≤'+b.div_age+'б'):''));}
 if(val(tf+'_atr')){b.atr_trend=val(tf+'_atr');s.push('ATR '+(b.atr_trend=='up'?'↑':'↓'));}
 if(chk(tf+'_obb')){b.ob_bull=true;s.push('OB↑');}
 if(chk(tf+'_obr')){b.ob_bear=true;s.push('OB↓');}
 if(chk(tf+'_fvb')){b.fvg_bull=true;s.push('FVG↑');}
 if(chk(tf+'_fvr')){b.fvg_bear=true;s.push('FVG↓');}
 if(val(tf+'_choch')){b.choch=val(tf+'_choch');s.push('CHoCH '+b.choch);}
 if(val(tf+'_bos')){b.bos=val(tf+'_bos');s.push('BOS '+b.bos);}
 return {b:b,n:s.length,sum:s};
}
function buildQuery(){
 var blocks=[],total=0;
 TFS.forEach(function(tf){
  var r=blockOf(tf);total+=r.n;
  var el=document.getElementById('sum_'+tf),cn=document.getElementById('cn_'+tf);
  el.innerHTML=r.n?r.sum.map(function(x){return '<b>'+x+'</b>';}).join(' · '):'все условия выключены';
  cn.style.display=r.n?'':'none';cn.textContent=r.n;
  if(r.n)blocks.push(r.b);
 });
 var g={};
 if(val('g_regime'))g.regime=val('g_regime');
 if(chk('g_pv')){g.near_pivot_pct=num('g_pvpct')||1.5;
  if(val('g_pvtf'))g.pivot_tf=val('g_pvtf');if(val('g_pvlv'))g.pivot_level=val('g_pvlv');}
 if(chk('g_eqh'))g.eqh_near=true;
 if(chk('g_eql'))g.eql_near=true;
 if(chk('g_ote'))g.in_ote=true;
 if(num('g_fmin')!=null)g.fund_min=num('g_fmin');
 if(num('g_fmax')!=null)g.fund_max=num('g_fmax');
 if(val('g_oidir')){var p=num('g_oipct')||2;g.oi_chg=(val('g_oidir')=='up'?p:-p);}
 if(num('g_turn')!=null)g.turn_min=num('g_turn');
 if(num('g_spread')!=null)g.spread_max=num('g_spread');
 if(num('g_vr')!=null){g.vol_ratio_min=num('g_vr');g.vol_tf=val('g_vtf')||'1h';}
 total+=Object.keys(g).length;
 document.getElementById('acnt').textContent=total;
 var rb=document.getElementById('btn_reset');
 if(rb){rb.disabled=(total===0);rb.textContent=total?('✕ сбросить всё ('+total+')'):'✕ сбросить всё';}
 TFS.forEach(function(t){                      // ✕ у ТФ — только если там что-то задано
  var c=document.getElementById('cl_'+t);
  if(c)c.classList.toggle('on',blockOf(t).n>0);});
 var mk=document.querySelector('[data-clear=market]'),fl=document.querySelector('[data-clear=flow]');
 var nm=['g_regime','g_pv','g_eqh','g_eql','g_ote'].filter(function(i){
  var e=document.getElementById(i);return e&&(e.type==='checkbox'?e.checked:!!e.value);}).length;
 var nf=['g_fmin','g_fmax','g_oidir','g_turn','g_spread','g_vr'].filter(function(i){
  var e=document.getElementById(i);return e&&!!e.value;}).length;
 if(mk)mk.classList.toggle('on',nm>0);
 if(fl)fl.classList.toggle('on',nf>0);
 markActive();
 return {blocks:blocks,global:g};
}
function markActive(){                      // подсветка групп, где что-то задано
 document.querySelectorAll('.grp').forEach(function(g){
  var on=false;
  g.querySelectorAll('input,select').forEach(function(e){
   if(e.type==='checkbox'){if(e.checked)on=true;}
   else if(e.value&&e.id!=='g_pvpct'&&e.id!=='g_oipct')on=true;});
  g.classList.toggle('act',on);});
}
document.querySelectorAll('.tfhd').forEach(function(h){
 h.onclick=function(e){
  if(e.target.dataset.cleartf)return;          // клик по ✕ не должен схлопывать блок
  document.getElementById('tf_'+h.dataset.tf).classList.toggle('open');};});
function clearFields(root){                    // снять условия в пределах контейнера
 root.querySelectorAll('input,select').forEach(function(x){
  if(x.id==='ps_name')return;
  if(x.type==='checkbox')x.checked=false;
  else if(x.id!=='g_pvpct'&&x.id!=='g_oipct'&&x.id!=='g_vtf')x.value='';});
 apply();
}
document.addEventListener('click',function(e){
 var sec=e.target.dataset&&e.target.dataset.clear;
 if(sec){e.stopPropagation();
  clearFields(document.getElementById(sec=='market'?'g_market':'g_flow').closest('.sect'));return;}
 var tf=e.target.dataset&&e.target.dataset.cleartf;
 if(tf){e.stopPropagation();clearFields(document.getElementById('tf_'+tf));}
});

// ── ПРЕСЕТЫ ──
var PS={};try{PS=JSON.parse(localStorage.getItem('oko_presets')||'{}');}catch(e){}
function psRender(){
 var box=document.getElementById('ps_list');
 var ks=Object.keys(PS);
 box.innerHTML=ks.length?ks.map(function(k){
  return '<span class=grp style=gap:6px><span class=psl data-k="'+k+'" style="cursor:pointer;color:var(--gold)">'+k+'</span>'+
   '<span class=psx data-k="'+k+'" title="удалить" style="cursor:pointer;color:var(--dim)">✕</span></span>';
 }).join(''):'<span class=note>пока нет — задай условия и сохрани</span>';
 box.querySelectorAll('.psl').forEach(function(e){e.onclick=function(){psLoad(e.dataset.k);};});
 box.querySelectorAll('.psx').forEach(function(e){e.onclick=function(){
  delete PS[e.dataset.k];localStorage.setItem('oko_presets',JSON.stringify(PS));psRender();};});
}
function psSave(){
 var n=(document.getElementById('ps_name').value||'').trim();
 if(!n){alert('Дай набору имя — потом найдёшь его одним кликом');return;}
 PS[n]=buildQuery();localStorage.setItem('oko_presets',JSON.stringify(PS));
 document.getElementById('ps_name').value='';psRender();
}
function psLoad(k){
 var q=PS[k];if(!q)return;
 resetFields();
 var g=q.global||{};
 if(g.regime)document.getElementById('g_regime').value=g.regime;
 if(g.near_pivot_pct!=null){document.getElementById('g_pv').checked=true;
  document.getElementById('g_pvpct').value=g.near_pivot_pct;
  if(g.pivot_tf)document.getElementById('g_pvtf').value=g.pivot_tf;
  if(g.pivot_level)document.getElementById('g_pvlv').value=g.pivot_level;}
 document.getElementById('g_eqh').checked=!!g.eqh_near;
 document.getElementById('g_eql').checked=!!g.eql_near;
 document.getElementById('g_ote').checked=!!g.in_ote;
 if(g.fund_min!=null)document.getElementById('g_fmin').value=g.fund_min;
 if(g.fund_max!=null)document.getElementById('g_fmax').value=g.fund_max;
 if(g.oi_chg!=null){document.getElementById('g_oidir').value=g.oi_chg>=0?'up':'down';
  document.getElementById('g_oipct').value=Math.abs(g.oi_chg);}
 if(g.turn_min!=null)document.getElementById('g_turn').value=g.turn_min;
 if(g.spread_max!=null)document.getElementById('g_spread').value=g.spread_max;
 if(g.vol_ratio_min!=null){document.getElementById('g_vr').value=g.vol_ratio_min;
  if(g.vol_tf)document.getElementById('g_vtf').value=g.vol_tf;}
 (q.blocks||[]).forEach(function(b){
  var tf=b.tf;if(TFS.indexOf(tf)<0)return;
  document.getElementById('tf_'+tf).classList.add('open');
  var set=function(id,v){var e=document.getElementById(id);if(e&&v!=null)e.value=v;};
  set(tf+'_wtmin',b.wt_min);set(tf+'_wtmax',b.wt_max);set(tf+'_wtzone',b.wt_zone);
  set(tf+'_wtcross',b.wt_cross);set(tf+'_crage',b.cross_age);
  set(tf+'_div',b.div);set(tf+'_divage',b.div_age);
  set(tf+'_atr',b.atr_trend);set(tf+'_choch',b.choch);set(tf+'_bos',b.bos);
  var ck=function(id,v){var e=document.getElementById(id);if(e)e.checked=!!v;};
  ck(tf+'_obb',b.ob_bull);ck(tf+'_obr',b.ob_bear);ck(tf+'_fvb',b.fvg_bull);ck(tf+'_fvr',b.fvg_bear);
 });
 apply();
}

function openMon(){window.open('/monitor','_blank');}
function resetFields(){
 document.querySelectorAll('input,select').forEach(function(x){
  if(x.id==='ps_name')return;
  if(x.type==='checkbox')x.checked=false;
  else if(x.id!=='g_pvpct'&&x.id!=='g_oipct')x.value='';});
 document.getElementById('g_vtf').value='1h';
}
function reset(){resetFields();apply();}

var _busy=false;
async function apply(){
 var q=buildQuery();
 try{localStorage.setItem('oko_filter_q',JSON.stringify(q));}catch(e){}
 if(_busy)return;_busy=true;
 document.getElementById('busy').innerHTML='<span class=spin></span>';
 try{
  var r=await fetch('/api/filter',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(q)});
  var d=await r.json();
  document.getElementById('cnt').textContent=d.n;
  document.getElementById('tot').textContent=d.total;
  document.getElementById('age').textContent='· обновлено '+new Date(d.ts*1000).toLocaleTimeString('ru');
  document.getElementById('srt').textContent=d.n?('сортировка: '+(q.global.vol_ratio_min?'по объёму':
   (q.global.spread_max!=null?'по спреду':'по алфавиту'))):'';
  document.getElementById('list').innerHTML=(d.coins||[]).map(function(x){
   var tw='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.sym+'USDT.P&interval=60';
   var t='';
   if(x.cr_dir){
    var up=x.cr_dir>0, zn=(x.cr_zone=='OS'||x.cr_zone=='OB')?(' из '+x.cr_zone):'';
    t+='<small style="color:'+(up?'var(--up)':'var(--dn)')+'" title="кросс WT '+(up?'вверх':'вниз')+
     ' на '+(x.cr_tf||'')+', установился '+x.cr_age+' бар(ов) назад'+
     (zn?(', '+(up?'из перепроданности — разворот вверх':'из перекупленности — разворот вниз')):'')+
     '">'+(up?'↑':'↓')+x.cr_age+(zn?'<b>'+zn+'</b>':'')+'</small>';}
   if(x.div)t+='<small style="color:'+(x.div.indexOf('+')>0?'var(--up)':'var(--dn)')+
    '" title="дивергенция '+(x.div[0]=='R'?'regular — разворотная':'hidden — продолжение')+
    ' на '+(x.div_tf||'')+', '+x.div_age+' бар назад">'+x.div+' '+(x.div_tf||'')+'</small>';
   if(x.vr!=null)t+='<small style="color:'+(x.vbody>0?'var(--up)':'var(--dn)')+
    '" title="объём ×'+x.vr+' к средней, тело бара '+x.vbody+'%">V×'+x.vr+'</small>';
   if(x.fund!=null&&Math.abs(x.fund)>0.02)t+='<small style="color:'+(x.fund>0?'var(--dn)':'var(--up)')+
    '" title="funding">f'+(x.fund>0?'+':'')+x.fund.toFixed(3)+'</small>';
   if(x.spread!=null)t+='<small title="спред">sp'+x.spread.toFixed(3)+'%</small>';
   return '<a href="'+tw+'" target=_blank>'+x.sym+t+'</a>';
  }).join('')||'<div class=empty>нет монет под эти условия — ослабь параметры</div>';
 }catch(e){
  document.getElementById('list').innerHTML='<div class=empty style=color:var(--dn)>ошибка запроса'+
   ' (бот или шина недоступны?)</div>';
 }finally{_busy=false;document.getElementById('busy').innerHTML='';}
}
document.addEventListener('input',function(){clearTimeout(window._t);window._t=setTimeout(apply,400);});
document.addEventListener('change',function(){clearTimeout(window._t);window._t=setTimeout(apply,120);});
psRender();apply();setInterval(apply,30000);
</script></body></html>"""


async def guide_page(_req):
    """GET /guide — инструкция по терминалу (docs/TERMINAL_GUIDE.md, рендер markdown на месте).
    Лежит в репозитории, а не в коде: правится как обычный документ проекта."""
    try:
        md = open("docs/TERMINAL_GUIDE.md", encoding="utf-8").read()
    except Exception as e:
        md = f"# Инструкция не найдена\n\n`docs/TERMINAL_GUIDE.md`: {e}"
    body = json.dumps(md)          # markdown рендерим в браузере, без внешних библиотек
    html = ("<!doctype html><html lang=ru><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>OKO · Инструкция</title><style>__CSS_BASE__"
            "body{background:var(--bg);color:var(--tx);font:15px/1.65 -apple-system,Segoe UI,Roboto,sans-serif}"
            ".wrap{max-width:900px;margin:0 auto;padding:22px 20px 80px}"
            "h1{font-size:24px;margin:22px 0 10px}h2{font-size:19px;margin:26px 0 8px;color:var(--gold);"
            "border-bottom:1px solid var(--line);padding-bottom:6px}h3{font-size:16px;margin:18px 0 6px}"
            "p{margin:8px 0}ul,ol{margin:8px 0 8px 22px}li{margin:3px 0}"
            "code{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:1px 5px;"
            "font-size:13px;color:var(--gold)}"
            "pre{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:12px 14px;"
            "overflow-x:auto}pre code{border:0;background:none;color:var(--tx)}"
            "table{border-collapse:collapse;margin:10px 0;width:100%;font-size:13.5px}"
            "th,td{border:1px solid var(--line);padding:6px 9px;text-align:left}"
            "th{background:var(--card);color:var(--dim);font-weight:600}"
            "blockquote{border-left:3px solid #5a4a28;margin:10px 0;padding:4px 12px;color:var(--dim);"
            "background:rgba(224,178,92,.05)}hr{border:0;border-top:1px solid var(--line);margin:22px 0}"
            "strong{color:#fff}a{color:var(--gold)}</style></head><body>__NAV__<div class=wrap id=doc></div>"
            "<script>var MD=" + body + ";"
            # мини-рендер: заголовки, таблицы, списки, код, цитаты — без внешних зависимостей
            "function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}"
            "function inl(s){return esc(s)"
            ".replace(/`([^`]+)`/g,'<code>$1</code>')"
            ".replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>')"
            ".replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,'<a href=\"$2\">$1</a>');}"
            "var out=[],lines=MD.split('\\n'),i=0,inCode=false,tbl=null;"
            "while(i<lines.length){var L=lines[i];"
            "if(L.indexOf('```')===0){inCode=!inCode;out.push(inCode?'<pre><code>':'</code></pre>');i++;continue;}"
            "if(inCode){out.push(esc(L));i++;continue;}"
            "if(/^\\|/.test(L)){var cells=L.split('|').slice(1,-1);"
            "if(/^\\|[\\s:|-]+\\|$/.test(L)){i++;continue;}"
            "if(!tbl){tbl=1;out.push('<table><tr>'+cells.map(function(c){return '<th>'+inl(c.trim())+'</th>';}).join('')+'</tr>');}"
            "else out.push('<tr>'+cells.map(function(c){return '<td>'+inl(c.trim())+'</td>';}).join('')+'</tr>');"
            "i++;continue;}"
            "if(tbl){out.push('</table>');tbl=null;}"
            "var m=L.match(/^(#{1,4})\\s+(.*)$/);"
            "if(m){out.push('<h'+m[1].length+'>'+inl(m[2])+'</h'+m[1].length+'>');i++;continue;}"
            "if(/^>\\s?/.test(L)){out.push('<blockquote>'+inl(L.replace(/^>\\s?/,''))+'</blockquote>');i++;continue;}"
            "if(/^---+$/.test(L)){out.push('<hr>');i++;continue;}"
            "if(/^[-*]\\s+/.test(L)){out.push('<ul>');"
            "while(i<lines.length&&/^[-*]\\s+/.test(lines[i])){out.push('<li>'+inl(lines[i].replace(/^[-*]\\s+/,''))+'</li>');i++;}"
            "out.push('</ul>');continue;}"
            "if(/^\\d+\\.\\s+/.test(L)){out.push('<ol>');"
            "while(i<lines.length&&/^\\d+\\.\\s+/.test(lines[i])){out.push('<li>'+inl(lines[i].replace(/^\\d+\\.\\s+/,''))+'</li>');i++;}"
            "out.push('</ol>');continue;}"
            "if(L.trim())out.push('<p>'+inl(L)+'</p>');i++;}"
            "if(tbl)out.push('</table>');"
            "document.getElementById('doc').innerHTML=out.join('\\n');</script></body></html>")
    return web.Response(text=_page(html, "/guide"), content_type="text/html",
                        headers={"Cache-Control": "no-store"})


async def filter_page(_req):
    return web.Response(text=_page(_FILTER_HTML, "/filter"), content_type="text/html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


_MONITOR_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKO · Монитор</title><script src="/vendor/lightweight-charts.js"></script><style>__CSS_BASE__
body{background:var(--bg);color:var(--tx);font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
 height:100vh;display:flex;flex-direction:column;overflow:hidden}
#bar{display:flex;gap:8px;align-items:center;padding:6px 10px;border-bottom:1px solid var(--line);
 flex-wrap:wrap;flex:0 0 auto}
.grp{display:inline-flex;align-items:center;gap:4px;background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:3px 6px;min-height:30px}
.grp b{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;margin-right:2px}
.bt{cursor:pointer;user-select:none;padding:4px 9px;border-radius:6px;color:var(--dim);font-size:12px;
 border:1px solid transparent;transition:.12s;min-height:24px;display:inline-flex;align-items:center}
.bt:hover{color:var(--tx)}.bt.on{background:rgba(224,178,92,.14);border-color:#5a4a28;color:var(--gold)}
#grid{flex:1;display:grid;gap:6px;padding:6px;overflow:hidden}
.cell{background:var(--card);border:1px solid var(--line);border-radius:10px;display:flex;
 flex-direction:column;overflow:hidden;min-height:0}
.chd{display:flex;align-items:center;gap:7px;padding:4px 8px;border-bottom:1px solid var(--line);
 flex:0 0 auto;cursor:default;user-select:none}
/* развёрнутое окно НЕ накрывает панель — иначе ТФ, слои и алерты становятся недоступны */
.cell.zoom{position:fixed;left:8px;right:8px;bottom:8px;top:var(--zt,92px);z-index:60;
 box-shadow:0 12px 48px rgba(0,0,0,.6);border-color:#3a4658}
.chd .tools{display:none}
.cell.zoom .chd .tools{display:inline-flex;align-items:center;gap:2px;margin-left:8px;
 padding-left:8px;border-left:1px solid var(--line)}
.chd .tools .bt{padding:2px 7px;font-size:11px;min-height:20px}
.chd .ztf{display:inline-flex;gap:1px;margin-right:4px}
.chd .zsep{width:1px;height:14px;background:var(--line);margin:0 4px;display:inline-block}
.chd .tg{font-size:11px;letter-spacing:-1px}
.chd .zi{margin-left:4px;color:var(--dim);font-size:10px}
.chd .sy{font-weight:700;font-size:13px;color:var(--tx);text-decoration:none}
.chd .sy:hover{color:var(--gold)}
.chd .pz{font-variant-numeric:tabular-nums;font-size:12px}
.chd .fl{margin-left:auto;display:flex;gap:3px;flex-wrap:nowrap;overflow:hidden}
.fg{font-size:9.5px;padding:1px 5px;border-radius:5px;border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.fg.b{color:var(--up);border-color:#134a44}.fg.s{color:var(--dn);border-color:#5a1f1e}
.fg.g{color:var(--gold);border-color:#5a4a28}
.cbody{flex:1;min-height:0;position:relative}
.ov{position:absolute;inset:0;pointer-events:none;z-index:2}
.cwt{flex:0 0 88px;border-top:1px solid var(--line);position:relative}
.ovw{position:absolute;inset:0;pointer-events:none;z-index:2}
.empty{grid-column:1/-1;display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:14px}
.trd{flex:0 0 auto;display:flex;align-items:center;gap:5px;padding:4px 6px;border-top:1px solid var(--line);
 font-size:11px;flex-wrap:wrap;background:rgba(0,0,0,.2)}
.trd input{width:44px;padding:1px 4px;font-size:11px}
.trd select{padding:1px 3px;font-size:11px}
.trd .go{cursor:pointer;padding:2px 9px;border-radius:5px;font-weight:700;font-size:11px;border:1px solid}
.go.buy{color:var(--up);border-color:#134a44;background:rgba(38,166,154,.12)}
.go.sell{color:var(--dn);border-color:#5a1f1e;background:rgba(239,83,80,.12)}
.go.x{color:var(--tx);border-color:#3a4658;background:rgba(255,255,255,.05)}
.chd .cx{cursor:pointer;font-size:10px;padding:1px 5px;border-radius:4px;border:1px solid #3a4658;
 color:var(--dim);margin-left:3px}
.chd .cx:hover{color:var(--dn);border-color:#5a1f1e}
.go:hover{filter:brightness(1.35)}
.trd .rr{color:var(--dim);margin-left:auto;white-space:nowrap}
.chd .tb{cursor:pointer;font-size:11px;color:var(--dim);padding:0 3px;border-radius:4px}
.chd .tb:hover{color:var(--gold)}.chd .tb.on{color:var(--gold)}
.chd .fav{cursor:pointer;font-size:12px;color:var(--dim);padding:0 2px;border-radius:4px}
.chd .fav:hover{color:var(--gold)}.chd .fav.on{color:var(--gold)}
#bar .live{color:var(--dn);font-weight:700}
.dd{position:relative}
.dd .ddt{padding:4px 5px;color:var(--dim)}
.dd.open .ddt{color:var(--gold)}
.ddm{display:none;position:absolute;top:calc(100% + 5px);left:0;z-index:80;background:var(--card);
 border:1px solid var(--line);border-radius:9px;padding:7px 8px;min-width:186px;
 box-shadow:0 10px 30px rgba(0,0,0,.5)}
.dd.open .ddm{display:block}
.ddm label{display:flex;align-items:center;gap:7px;padding:4px 5px;border-radius:6px;cursor:pointer;
 font-size:12px;color:var(--tx);min-height:26px}
.ddm label:hover{background:rgba(255,255,255,.04)}
.ddm input{accent-color:var(--gold);cursor:pointer;width:14px;height:14px}
.ddm .sec{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
 padding:6px 5px 2px;border-top:1px solid var(--line);margin-top:4px}
.ddm .sec:first-child{border-top:0;margin-top:0}
.ddm .all{color:var(--gold);font-size:11px;cursor:pointer;padding:4px 5px;display:inline-block}
#bar input{background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:6px;
 padding:3px 7px;font:inherit;font-size:12px;min-height:24px}
#alog{position:fixed;right:10px;bottom:10px;z-index:90;display:flex;flex-direction:column;gap:6px;
 max-width:320px;pointer-events:none}
.altoast{background:var(--card);border:1px solid #5a4a28;border-left:3px solid var(--gold);
 border-radius:8px;padding:7px 10px;font-size:12px;box-shadow:0 8px 24px rgba(0,0,0,.5);
 animation:alin .18s ease-out}
.altoast b{color:var(--gold)}.altoast .t{color:var(--dim);font-size:10.5px}
@keyframes alin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.cell.alerted{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
</style></head><body>
__NAV__
<div id=bar>
  <span class=grp><b>сетка</b><span class="bt" data-g=4>2×2</span><span class="bt on" data-g=9>3×3</span><span class="bt" data-g=16>4×4</span></span>
  <span class=grp><b>тф</b><span class="bt" data-tf=5m>5m</span><span class="bt on" data-tf=15m>15m</span><span class="bt" data-tf=1h>1h</span><span class="bt" data-tf=4h>4h</span><span class="bt" data-tf=1d>1d</span></span>
  <span class=grp><b>состав</b><span class="bt on" id=b_live>live-фильтр</span><span class="bt" id=b_pin>закреплено</span><span class="bt" id=b_pos>мои позиции<span id=posn></span></span><span class="bt" id=b_play title="монеты из кокпита: радар 🚀🌱🔨 · OTE 🎯 · DC 🤖 · хайп 🔥">🎯 в игре<span id=playn></span></span><span class="bt" id=b_fav title="избранное: ★ в шапке окна добавляет/убирает монету">★ избранное<span id=favn></span></span></span>
  <span class="grp dd" id=lvgrp><span class="bt" id=b_lv>уровни Куба</span><span class="bt ddt" id=b_lv_dd role=button tabindex=0 aria-label="Выбрать слои" title="какие элементы рисовать">▾</span>
    <div class=ddm id=lvmenu role=group aria-label="Слои уровней Куба"></div></span>
  <span class=grp><span class="bt" id=b_wt>WT</span><span class="bt" id=b_atr>ATRTrend</span></span>
  <span class="grp dd" id=algrp><span class="bt" id=b_al>🔔 алерты<span id=aln></span></span><span class="bt ddt" id=b_al_dd role=button tabindex=0 aria-label="Настройка алертов" title="что сигналить">▾</span>
    <div class=ddm id=almenu role=group aria-label="Типы алертов"></div></span>
  <span class=grp><b>поиск</b><input id=q_sym list=symlist placeholder="BTC, SEI…" autocomplete=off
    aria-label="Найти монету и добавить в избранное" style="width:96px"><datalist id=symlist></datalist></span>
  <span class=grp><b>счёт</b><span class="bt on" id=b_acc_vst>VST</span><span class="bt" id=b_acc_live>LIVE</span><span id=bal style=color:var(--dim);font-size:11px>—</span></span>
  <span class=grp><b>рисовать</b><span class="bt" data-t=hl role=button tabindex=0 aria-label="Горизонтальный уровень" title="горизонтальный уровень">↔</span><span class="bt" data-t=tl role=button tabindex=0 aria-label="Трендовая линия" title="трендовая линия">╱</span><span class="bt" data-t=rc role=button tabindex=0 aria-label="Прямоугольник" title="прямоугольник">▭</span><span class="bt" data-t=fb role=button tabindex=0 aria-label="Фибо-сетка" title="фибо-сетка">fib</span><span class="bt" id=b_clr role=button tabindex=0 aria-label="Стереть разметку" title="стереть разметку окна">🗑</span></span>
  <span class=grp><span class="bt" id=pg_p>‹</span><span id=pg style=color:var(--dim);font-size:12px>1/1</span><span class="bt" id=pg_n>›</span></span>
  <span style=color:var(--dim);font-size:12px><b id=cnt style=color:var(--gold)>0</b> монет <span id=age></span></span>
</div>
<div id=grid></div>
<div id=alog aria-live=polite></div>
<script>
var S={syms:[],pinned:null,page:0,grid:9,tf:'15m',live:true,lv:false,wt:false,atr:false,
 lim:200,q:null,cells:{},acc:'vst',bal:0,tool:null,src:'filter',pos:{},zoom:null};
var PIVC={PP:'#ffeb3b',R1:'#ef5350',R2:'#ef5350',R3:'#ef5350',S1:'#26a69a',S2:'#26a69a',S3:'#26a69a'};
// Слои «уровней Куба» — каждый включается отдельно (Егор 16.08): на графике должно быть только то,
// что нужно СЕЙЧАС, иначе окно превращается в кашу из зон и линий.
var LAYERS=[['СТРУКТУРА',null],['leg','нога OKO-SM (SH/WL)'],['brk','сломы swing (CHoCH/BOS)'],
 ['brk_int','сломы internal (мелкие)'],['ЗОНЫ',null],['fvg','FVG'],['ob','Order Blocks'],
 ['eq','EQH / EQL'],['УРОВНИ',null],['piv_d','пивоты дневные'],['piv_w','пивоты недельные'],
 ['badges','бейджи в шапке']];
var LV={};try{LV=JSON.parse(localStorage.getItem('oko_layers')||'null')||{};}catch(e){}
LAYERS.forEach(function(l){if(l[1]&&LV[l[0]]===undefined)LV[l[0]]=true;});   // по умолчанию всё вкл
function lvSave(){try{localStorage.setItem('oko_layers',JSON.stringify(LV));}catch(e){}}
try{S.q=JSON.parse(localStorage.getItem('oko_filter_q')||'null');}catch(e){}
// План сделки из ПОВЕСТКИ: ?sym=LTC&side=BUY&entry=..&sl=..&tp=.. — открываем монету и сразу
// рисуем сделку (как инструмент «длинная позиция» в TW), панель заполнена, остаётся нажать.
var PLAN=null;(function(){
 var u=new URLSearchParams(location.search),sym=(u.get('sym')||'').toUpperCase();
 if(!sym)return;
 PLAN={sym:sym,side:u.get('side')||'BUY',entry:+u.get('entry')||0,sl:+u.get('sl')||0,tp:+u.get('tp')||0};
 S.src='plan';S.syms=[sym];S.grid=4;
})();
if(!S.q)S.q={blocks:[],global:{}};
var CO={layout:{background:{color:'#141922'},textColor:'#7b8496',fontSize:10,attributionLogo:false},
 grid:{vertLines:{color:'#1b212b'},horzLines:{color:'#1b212b'}},
 rightPriceScale:{borderColor:'#232a36'},timeScale:{borderColor:'#232a36',timeVisible:true,secondsVisible:false},
 crosshair:{mode:0},handleScale:true,handleScroll:true};
var WTL=[[80,'#ef5350',1],[60,'#ef5350',0],[0,'#555555',0],[-60,'#26a69a',0],[-80,'#26a69a',1]];
function cols(){return S.grid==4?2:S.grid==9?3:4;}
function vis(){return S.syms.slice(S.page*S.grid,(S.page+1)*S.grid);}
// WT 1:1 с core/indicators/indicators.py (n1=10, n2=21, wt2 = SMA4 от wt1)
function ema(a,span){var k=2/(span+1),p=a[0],o=[];for(var i=0;i<a.length;i++){p=i?a[i]*k+p*(1-k):a[0];o.push(p);}return o;}
function calcWt(b){var h=b.map(function(x){return (x.h+x.l+x.c)/3;});
 var esa=ema(h,10),d=ema(h.map(function(x,i){return Math.abs(x-esa[i]);}),10);
 var ci=h.map(function(x,i){return d[i]?(x-esa[i])/(0.015*d[i]):0;}),w1=ema(ci,21);
 var w2=w1.map(function(_,i){var s=w1.slice(Math.max(0,i-3),i+1);return s.reduce(function(a,b){return a+b;},0)/s.length;});
 return b.map(function(x,i){return {t:x.t,a:w1[i],b:w2[i]};});}
function mkCell(sym){
 var el=document.createElement('div');el.className='cell';
 el.innerHTML='<div class=chd><a class=sy target=_blank>'+sym+'</a><span class=pz>—</span>'+
  '<span class=fav role=button tabindex=0 aria-label="В избранное" title="в избранное (★)">☆</span>'+
  '<span class=tb role=button tabindex=0 aria-label="Торговая панель" title="торговая панель">⚡</span>'+
  '<span class=tools>'+                       // видны в развёрнутом окне (Егор 14.08)
   '<span class=ztf>'+['5m','15m','1h','4h','1d'].map(function(t){
     return '<span class="bt ztfb" data-ztf="'+t+'">'+t+'</span>';}).join('')+'</span>'+
   '<span class="bt zlv" role=button tabindex=0 aria-label="Уровни Куба" title="уровни Куба вкл/выкл">Куб</span>'+
   '<span class="bt zwt" role=button tabindex=0 aria-label="Панель WT" title="WT вкл/выкл">WT</span>'+
   '<span class="bt zatr" role=button tabindex=0 aria-label="ATRTrend" title="ATRTrend вкл/выкл">ATR</span>'+
   '<span class=zsep></span>'+
   '<span class="bt" data-t=hl role=button tabindex=0 aria-label="Горизонтальный уровень" title="уровень">↔</span>'+
   '<span class="bt" data-t=tl role=button tabindex=0 aria-label="Трендовая линия" title="трендовая">╱</span>'+
   '<span class="bt" data-t=rc role=button tabindex=0 aria-label="Прямоугольник" title="прямоугольник">▭</span>'+
   '<span class="bt" data-t=fb role=button tabindex=0 aria-label="Фибо-сетка" title="фибо">fib</span>'+
   '<span class="bt tclr" role=button tabindex=0 aria-label="Стереть разметку окна" title="стереть разметку">🗑</span>'+
  '</span><span class=fl></span></div>'+
  '<div class=cbody></div>'+(S.wt?'<div class=cwt></div>':'');
 el.querySelector('.sy').href='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+sym+'USDT.P&interval='+
  ({'5m':'5','15m':'15','1h':'60','4h':'240','1d':'D'}[S.tf]||'15');
 document.getElementById('grid').appendChild(el);
 var body=el.querySelector('.cbody');
 var ch=LightweightCharts.createChart(body,Object.assign({},CO,{width:body.clientWidth,height:body.clientHeight}));
 var cs=ch.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,
  wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
 var vs=ch.addHistogramSeries({priceScaleId:'v',priceFormat:{type:'volume'}});
 ch.priceScale('v').applyOptions({scaleMargins:{top:0.82,bottom:0}});
 var ov=document.createElement('canvas');ov.className='ov';body.appendChild(ov);
 var o={el:el,ch:ch,cs:cs,vs:vs,lines:[],sym:sym,body:body,ov:ov,fit:false};
 if(S.wt){var wb=el.querySelector('.cwt');
  o.wch=LightweightCharts.createChart(wb,Object.assign({},CO,{width:wb.clientWidth,height:wb.clientHeight,
   timeScale:{visible:false,borderColor:'#232a36'},rightPriceScale:{borderColor:'#232a36'},
   handleScale:false,handleScroll:false}));
  o.w1=o.wch.addLineSeries({color:'#e91e63',lineWidth:1});     // wt1 / wt2 — цвета как в TG-чарте
  o.w2=o.wch.addLineSeries({color:'#4caf50',lineWidth:1});
  WTL.forEach(function(l){o.w1.createPriceLine({price:l[0],color:l[1],lineWidth:1,   // 80/60/0/−60/−80
   lineStyle:l[2]?0:2,axisLabelVisible:false,title:l[0]?String(l[0]):''});});
  o.ovw=document.createElement('canvas');o.ovw.className='ovw';wb.appendChild(o.ovw);
  ch.timeScale().subscribeVisibleLogicalRangeChange(function(r){if(r&&o.wch){
   o.wch.timeScale().setVisibleLogicalRange(r);drawWt(o);}});}
 ch.timeScale().subscribeVisibleLogicalRangeChange(function(r){drawOv(o);
  if(r&&r.from<6)more(o);});      // доехали до левого края → расширяем окно истории
 body.addEventListener('mousedown',function(e){if(S.tool&&e.button===0)onDraw(o,e);},true);
 body.addEventListener('mousemove',function(e){if(!S.tool||!o.pend)return;
  var r=body.getBoundingClientRect();o.hover=ptOf(o,e);drawOv(o);},true);
 body.addEventListener('contextmenu',function(e){if(objs(o.sym).length)onErase(o,e);});
 var fv=el.querySelector('.fav');
 if(FAV.indexOf(sym)>=0){fv.classList.add('on');fv.textContent='★';}
 fv.onclick=function(){favToggle(sym,fv);};
 el.querySelector('.tb').onclick=function(){toggleTrade(o,this);};
 el.querySelectorAll('.ztfb').forEach(function(b){                 // ТФ прямо из развёрнутого окна
  b.classList.toggle('on',b.dataset.ztf===S.tf);
  b.onclick=function(){var t=b.dataset.ztf;
   document.querySelector('[data-tf="'+t+'"]').click();               // общий переключатель ТФ
   Object.keys(S.cells).forEach(function(k){
    S.cells[k].el.querySelectorAll('.ztfb').forEach(function(x){
     x.classList.toggle('on',x.dataset.ztf===t);});});};});
 var zsync=function(){                                              // подсветка слоёв в шапке
  el.querySelector('.zlv').classList.toggle('on',S.lv);
  el.querySelector('.zwt').classList.toggle('on',S.wt);
  el.querySelector('.zatr').classList.toggle('on',S.atr);};
 zsync();
 el.querySelector('.zlv').onclick=function(){document.getElementById('b_lv').click();
  Object.keys(S.cells).forEach(function(k){var q=S.cells[k].el.querySelector('.zlv');
   if(q)q.classList.toggle('on',S.lv);});};
 el.querySelector('.zwt').onclick=function(){document.getElementById('b_wt').click();};
 el.querySelector('.zatr').onclick=function(){document.getElementById('b_atr').click();
  Object.keys(S.cells).forEach(function(k){var q=S.cells[k].el.querySelector('.zatr');
   if(q)q.classList.toggle('on',S.atr);});};
 el.querySelectorAll('.tools [data-t]').forEach(function(b){       // те же инструменты, что вверху
  b.onclick=function(){setTool(S.tool===b.dataset.t?null:b.dataset.t);};});
 el.querySelector('.tclr').onclick=function(){DRAW[o.sym]=[];o.pend=null;saveDraw();drawOv(o);};
 el.querySelector('.chd').addEventListener('dblclick',function(e){   // на весь экран и обратно
  if(e.target.closest('a,.tb,.cx'))return;zoomCell(o);});
 body.addEventListener('mousedown',function(e){tradeGrab(o,e);});
 body.addEventListener('mousemove',function(e){tradeDrag(o,e);});
 window.addEventListener('mouseup',function(){if(o.grab)dropGrab(o);});
 o.ro=new ResizeObserver(function(){ch.resize(body.clientWidth,body.clientHeight);
  if(o.wch){var w=el.querySelector('.cwt');o.wch.resize(w.clientWidth,w.clientHeight);drawWt(o);}drawOv(o);});
 o.ro.observe(body);
 return o;}
// Догрузка истории: BingX отдаёт до 1440 баров за раз — расширяем окно целиком, а не клеим куски
// (склейка ломала бы рекуррентные ATR/WT на стыке холодным стартом).
async function refresh(c){    // одиночное окно со своим (расширенным) лимитом
 try{var r=await fetch('/api/klines?tf='+S.tf+'&limit='+c.lim+'&syms='+c.sym+(S.atr?'&atr=1':''),{cache:'no-store'});
  var d=await r.json(),b=(d.bars||{})[c.sym];if(b&&b.length)applyBars(c,b,(d.atr||{})[c.sym]);
 }catch(e){}}
async function more(c){                        // потолок BingX klines v3 — 1000 баров за запрос
 if(c.busy||(c.lim||S.lim)>=1000||!c.bars)return;c.busy=true;
 var nl=Math.min(1000,(c.lim||S.lim)+400),was=c.bars.length;
 c.lim=nl;await refresh(c);
 if(c.bars.length<=was)c.lim=1000;            // биржа отдала всё, что есть — больше не просим
 c.busy=false;}
// Оверлей структур: боксы FVG/OB, линии слома CHoCH/BOS, EQH/EQL — lightweight-charts
// умеет только горизонтальные priceLine, зоны рисуем сами по координатам его шкал.
// Перерисовка через requestAnimationFrame: несколько запросов в одном кадре схлопываются
// в один, а в фоновой вкладке rAF не вызывается вовсе → монитор перестаёт жечь CPU впустую.
function drawOv(c){
 if(document.hidden||c._raf)return;
 c._raf=requestAnimationFrame(function(){c._raf=0;drawOvNow(c);});}
function drawOvNow(c){
 var cv=c.ov,dpr=window.devicePixelRatio||1,W=c.body.clientWidth,H=c.body.clientHeight;
 if(cv.width!==W*dpr||cv.height!==H*dpr){cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';}
 var g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);
 // область САМОГО графика: канвас накрывает ячейку целиком, а справа ценовая шкала, снизу — время
 var GW=W,GH=H;
 try{GW=W-(c.ch.priceScale('right').width()||0);GH=H-(c.ch.timeScale().height()||0);}catch(e){}
 g.save();g.beginPath();g.rect(0,0,GW,GH);g.clip();
 drawAtr(c,g,GW);
 drawTools(c,g,GW,GH);
 drawTrade(c,g,GW,GH);
 var v=c.lv;if(!S.lv||!v){g.restore();return;}
 var ts=c.ch.timeScale(),y=function(p){return c.cs.priceToCoordinate(p);};
 var x=function(t){var q=ts.timeToCoordinate(t);return q==null?null:q;};
 // Структуры считаются на 1000 барах, а в окне графика их может быть 200 → у события нет своего
 // бара и координата null. Начало обрезаем по левому краю, конец — по правому; если объект целиком
 // в невидимой истории, НЕ рисуем (иначе тянулся линией через весь экран — Егор 14.08).
 var tF=(c.bars&&c.bars.length)?c.bars[0].t:0;
 var x0=function(t){var q=x(t);return q!=null?q:(t<tF?0:null);};
 var xE=function(t){var q=x(t);return q!=null?q:(t>tF?GW:null);};
 function box(t0,top,bot,fill,line,label){
  var a=x0(t0),yt=y(top),yb=y(bot);if(a==null||yt==null||yb==null)return;
  if(yb<0||yt>GH)return;                                  // зона вне видимого диапазона цен
  g.fillStyle=fill;g.fillRect(a,yt,GW-a,yb-yt);
  g.strokeStyle=line;g.lineWidth=1;g.strokeRect(a,yt,GW-a,yb-yt);
  if(label&&yb-yt>9){g.fillStyle=line;g.font='9px -apple-system,Segoe UI,sans-serif';
   g.fillText(label,Math.min(a+3,GW-30),(yt+yb)/2+3);}}
 if(LV.fvg)(v.fvg||[]).forEach(function(f){   // FVG всегда зелёным (Егор 14.08) — сторону читаем по структуре
  box(f.t0,f.top,f.bot,'rgba(38,166,154,.13)','rgba(38,166,154,.5)','FVG');});
 if(LV.ob)(v.ob||[]).forEach(function(o){var bull=o.kind=='bull';
  box(o.t0,o.top,o.bot,bull?'rgba(38,166,154,.10)':'rgba(239,83,80,.10)',
   bull?'rgba(38,166,154,.5)':'rgba(239,83,80,.5)','OB');});
 if(v.leg&&LV.leg){var la=x0(v.leg.t0),le=xE(v.leg.t1),p0=y(v.leg.p0),p1=y(v.leg.p1);  // нога OKO-SM
  if(p0!=null&&p1!=null&&la!=null&&le!=null){
   g.strokeStyle='#ffa726';g.lineWidth=1.4;g.globalAlpha=.85;
   g.beginPath();g.moveTo(la,p0);g.lineTo(le,p1);g.stroke();g.globalAlpha=1;
   g.fillStyle='#ffa726';g.font='bold 9px -apple-system,Segoe UI,sans-serif';
   g.fillText(v.leg.side=='long'?'SH':'WL',Math.min(le+3,GW-18),p1+3);}}
 (v.brk||[]).forEach(function(b){
  if(b.int?!LV.brk_int:!LV.brk)return;          // swing и internal включаются отдельно
  var a=x0(b.t0),e=xE(b.t1),p=y(b.p);
  if(p==null||p<0||p>GH||a==null||e==null)return;
  g.strokeStyle=b.dir=='bull'?'#26a69a':'#ef5350';
  g.globalAlpha=b.int?.45:1;g.lineWidth=b.int?0.8:1.2;      // internal(5) тоньше, swing(50) — основа
  g.setLineDash(b.kind=='CHoCH'?[]:[3,3]);                  // CHoCH сплошная, BOS пунктир (как в TG)
  g.beginPath();g.moveTo(a,p);g.lineTo(e,p);g.stroke();g.setLineDash([]);
  g.fillStyle=g.strokeStyle;g.font=(b.int?'':'bold ')+(b.int?8:9)+'px -apple-system,Segoe UI,sans-serif';
  g.fillText(b.kind,Math.max(2,(a+e)/2-14),p-3);g.globalAlpha=1;});
 if(LV.eq)(v.eq||[]).forEach(function(q){var a=x0(q.t0),e=xE(q.t1),p=y(q.p);
  if(p==null||p<0||p>GH||a==null||e==null)return;
  g.strokeStyle='#ffd54f';g.lineWidth=1;g.setLineDash([1,2]);
  g.beginPath();g.moveTo(a,p);g.lineTo(Math.max(e,a+18),p);g.stroke();g.setLineDash([]);
  g.fillStyle='#ffd54f';g.font='bold 9px -apple-system,Segoe UI,sans-serif';
  g.fillText(q.kind,Math.max(2,e+3),p-2);});
 // Пивоты как в TG-чарте: линия ОТ НАЧАЛА периода (день/неделя), дневные пунктиром, недельные
 // сплошной жирнее, справа цветной бейдж с ценой.
 function periodX(sec){                       // координата начала текущего дня/недели
  if(!c.bars||!c.bars.length)return 0;
  var last=c.bars[c.bars.length-1].t;
  var st=sec==86400?Math.floor(last/86400)*86400
                   :Math.floor((last+259200)/604800)*604800-259200;   // epoch = четверг → −3 дня
  for(var i=0;i<c.bars.length;i++)if(c.bars[i].t>=st){var q=x(c.bars[i].t);return q==null?0:q;}
  return 0;}
 g.font='bold 8.5px -apple-system,Segoe UI,sans-serif';
 [['1D',86400,true,'D','piv_d'],['1W',604800,false,'W','piv_w']].forEach(function(pt){
  if(!LV[pt[4]])return;
  var lv=(v.piv||{})[pt[0]]||{},xs=periodX(pt[1]);
  Object.keys(lv).forEach(function(k){var p=y(lv[k]);if(p==null||p<8||p>GH-4)return;
   var col=PIVC[k]||'#888',dim=(k=='R2'||k=='S2'||k=='R3'||k=='S3');
   var tx=pt[3]+':'+k+' '+(+lv[k]).toPrecision(6),w=g.measureText(tx).width+7;
   g.strokeStyle=col;g.globalAlpha=dim?.45:.85;g.lineWidth=pt[2]?1:1.4;   // сплошные обе шкалы,
   g.beginPath();g.moveTo(xs,p);g.lineTo(Math.max(xs,GW-w-4),p);g.stroke();  // W чуть жирнее (Егор)
   g.fillStyle=col;g.globalAlpha=dim?.55:.9;g.fillRect(GW-w-2,p-6,w,12);g.globalAlpha=1;
   g.fillStyle='#131722';g.fillText(tx,GW-w+1,p+3);});});
 g.restore();}
// ── СВОЯ РАЗМЕТКА (Егор 14.08): уровень / трендовая / прямоугольник / фибо ──
// Инструментов рисования у lightweight-charts нет (они в платной Charting Library), поэтому
// объекты держим в координатах время↔цена и рисуем сами — переживают зум, скролл и перезагрузку.
var DRAW={};try{DRAW=JSON.parse(localStorage.getItem('oko_draw')||'{}');}catch(e){}
var FIB=[0,0.382,0.5,0.618,0.705,0.786,1];
function saveDraw(){try{localStorage.setItem('oko_draw',JSON.stringify(DRAW));}catch(e){}}
function objs(sym){return DRAW[sym]||(DRAW[sym]=[]);}
// ATRTrend одной ломаной: зелёная пока тренд вверх, красная — вниз, на флипе РАЗРЫВ
// (иначе линия соединяет верхнюю границу с нижней и рисует «канал» вместо supertrend).
function drawAtr(c,g,GW){
 if(!S.atr||!c.atr||!c.bars)return;
 // Батчим: одна ломаная на участок одного направления. Раньше каждый бар = отдельный
 // beginPath+stroke → 1000 вызовов на окно × 16 окон каждые 3с (вкладка ела 39% ядра).
 var ts=c.ch.timeScale(),prev=null,pd=0,open=false;
 g.lineWidth=1.3;g.setLineDash([]);
 function flush(){if(open){g.stroke();open=false;}}
 c.atr.forEach(function(p){
  if(p.l==null||!p.d){flush();prev=null;pd=0;return;}
  var x=ts.timeToCoordinate(p.t);
  if(x==null||x<-50||x>GW+50){flush();prev=null;pd=0;return;}   // вне экрана — не рисуем
  var yy=c.cs.priceToCoordinate(p.l);
  if(yy==null){flush();prev=null;pd=0;return;}
  if(prev&&pd===p.d){
   if(!open){g.strokeStyle=p.d>0?'#26a69a':'#ef5350';g.beginPath();g.moveTo(prev.x,prev.y);open=true;}
   g.lineTo(x,yy);
  }else flush();
  prev={x:x,y:yy};pd=p.d;});
 flush();}
// Координата времени С ПРОДОЛЖЕНИЕМ ВПРАВО: timeToCoordinate знает только существующие бары,
// поэтому правее последнего бара считаем по шагу сетки — разметку можно тянуть в будущее (Егор).
function barStep(c){
 var b=c.bars;return (b&&b.length>1)?(b[b.length-1].t-b[b.length-2].t):900;}
function xFut(c,t){
 var ts=c.ch.timeScale(),q=ts.timeToCoordinate(t);
 if(q!=null)return q;
 var b=c.bars;if(!b||b.length<2)return null;
 var tl=b[b.length-1].t,xl=ts.timeToCoordinate(tl);if(xl==null)return null;
 if(t<tl)return null;                       // левее данных — пусть обрежется клипом
 var xp=ts.timeToCoordinate(b[b.length-2].t),sp=(xp!=null)?(xl-xp):6;
 return xl+(t-tl)/barStep(c)*sp;}
function drawTools(c,g,GW,GH){
 var ts=c.ch.timeScale(),y=function(p){return c.cs.priceToCoordinate(p);};
 var X=function(t){return xFut(c,t);};
 function seg(o,prev){
  var a=X(o.t0),b=X(o.t1),p0=y(o.p0),p1=y(o.p1);
  if(p0==null||p1==null)return null;
  if(a==null)a=prev?0:null;if(b==null)b=GW;
  return a==null?null:{a:a,b:b,p0:p0,p1:p1};}
 function one(o,act){
  g.globalAlpha=act?.7:1;
  if(o.k=='hl'){var p=y(o.p);if(p==null)return;
   g.strokeStyle='#e0b25c';g.lineWidth=1.2;g.setLineDash([]);
   g.beginPath();g.moveTo(0,p);g.lineTo(GW,p);g.stroke();
   g.fillStyle='#e0b25c';g.font='9px -apple-system,Segoe UI,sans-serif';
   g.fillText((+o.p).toPrecision(6),2,p-3);return;}
  var s=seg(o,true);if(!s)return;
  if(o.k=='tl'){g.strokeStyle='#e0b25c';g.lineWidth=1.2;g.setLineDash([]);
   g.beginPath();g.moveTo(s.a,s.p0);g.lineTo(s.b,s.p1);g.stroke();}
  else if(o.k=='rc'){g.strokeStyle='#e0b25c';g.lineWidth=1;
   g.fillStyle='rgba(224,178,92,.10)';
   g.fillRect(Math.min(s.a,s.b),Math.min(s.p0,s.p1),Math.abs(s.b-s.a),Math.abs(s.p1-s.p0));
   g.strokeRect(Math.min(s.a,s.b),Math.min(s.p0,s.p1),Math.abs(s.b-s.a),Math.abs(s.p1-s.p0));}
  else if(o.k=='fb'){                    // 1 у первой точки, 0 у второй (Егор); 0.618-0.786 = OTE
   var yo=y(o.p1),ye=y(o.p0);if(yo==null||ye==null)return;
   var g618=yo+(ye-yo)*0.618,g786=yo+(ye-yo)*0.786;
   g.fillStyle='rgba(224,178,92,.10)';g.fillRect(s.a,Math.min(g618,g786),GW-s.a,Math.abs(g786-g618));
   g.font='8.5px -apple-system,Segoe UI,sans-serif';
   FIB.forEach(function(f){var yy=yo+(ye-yo)*f;if(yy<0||yy>GH)return;
    var ote=(f==0.618||f==0.705||f==0.786);
    g.strokeStyle=ote?'#e0b25c':'#5a6478';g.lineWidth=ote?1:0.8;g.setLineDash(f==0||f==1?[]:[3,3]);
    g.beginPath();g.moveTo(s.a,yy);g.lineTo(GW,yy);g.stroke();g.setLineDash([]);
    g.fillStyle=ote?'#e0b25c':'#7b8496';g.fillText(f.toFixed(3),s.a+2,yy-2);});}
  g.globalAlpha=1;}
 objs(c.sym).forEach(function(o){one(o,false);});
 if(c.pend&&c.hover){                    // «резинка» второй точки
  var h=c.hover,t=c.pend;
  one({k:t.k,t0:t.t0,p0:t.p0,t1:h.t,p1:h.p},true);}}
// ── ТОРГОВЛЯ С ГРАФИКА: SL/TP тянутся мышью, размер риском или маржой ──
function applyPlan(c){
 // Переход «→ на график с планом»: рисуем сделку и открываем панель с готовыми уровнями.
 // Вызывается ПОСЛЕ загрузки баров: toggleTrade без цены молча выходит (!px), и план терялся.
 if(!PLAN||PLAN.sym!==c.sym||c._planned)return;
 if(!c.bars||!c.bars.length)return;
 c._planned=true;
 if(!c.trade)toggleTrade(c,c.el.querySelector('.tb'));
 if(!c.trade)return;
 if(PLAN.sl)c.trade.sl=PLAN.sl;
 if(PLAN.tp)c.trade.tp=PLAN.tp;
 c.trade.plan=true;
 var p=c.el.querySelector('.trd');            // сторону из повестки подсвечиваем в панели
 if(p){var b=p.querySelector(PLAN.side==='SELL'?'.sell':'.buy');
  if(b)b.style.boxShadow='0 0 0 2px '+(PLAN.side==='SELL'?'#5a1f1e':'#134a44');}
 tradeInfo(c);drawOv(c);
 if(S.src=='plan'&&S.syms.length===1&&!c.el.classList.contains('zoom'))
  setTimeout(function(){zoomCell(c);},150);   // одна монета — показываем крупно
}
function toggleTrade(c,btn){
 if(c.trade){c.trade=null;var p=c.el.querySelector('.trd');if(p)p.remove();
  if(btn)btn.classList.remove('on');drawOv(c);return;}
 var px=(c.bars&&c.bars.length)?c.bars[c.bars.length-1].c:0;if(!px)return;
 c.trade={sl:px*0.985,tp:px*1.03};                 // старт для LONG, дальше тянешь мышью
 if(btn)btn.classList.add('on');
 var p=document.createElement('div');p.className='trd';
 p.innerHTML='<span class="go buy">BUY</span><span class="go sell">SELL</span>'+
  '<span style=color:var(--dim)>x</span><input class=lev value=5 type=number min=1 max=125>'+
  '<select class=sk><option value=risk>риск %</option><option value=usd>маржа $</option>'+
  '<option value=pct>маржа %</option></select><input class=sv value=1 type=number step=0.1>'+
  '<span class="go x cl1" role=button tabindex=0 aria-label="Закрыть позицию" title="закрыть позицию по рынку и снять её SL/TP">✕</span>'+
  '<span class="go x clh" role=button tabindex=0 aria-label="Закрыть половину позиции" title="закрыть половину, защиту переставить на остаток">½</span>'+
  '<span class="go x be" role=button tabindex=0 aria-label="Стоп в безубыток" title="стоп в безубыток (на цену входа)">БУ</span>'+
  '<span class=rr></span>';
 c.el.appendChild(p);
 fetch('/api/levinfo?mode='+S.acc+'&sym='+c.sym).then(function(r){return r.json();})
  .then(function(d){if(d&&!d.error){c.plim=d;
   var lv=p.querySelector('.lev'),mx=Math.max(d.max_long||1,d.max_short||1);
   lv.max=mx;lv.title='максимум на '+c.sym+': x'+mx;
   if(+lv.value>mx)lv.value=mx;
   tradeInfo(c);}}).catch(function(){});
 p.querySelector('.buy').onclick=function(){sendOrder(c,'BUY');};
 p.querySelector('.sell').onclick=function(){sendOrder(c,'SELL');};
 p.querySelector('.cl1').onclick=function(){closePos(c,1);};
 p.querySelector('.clh').onclick=function(){closePos(c,0.5);};
 p.querySelector('.be').onclick=function(){toBreakeven(c);};
 p.addEventListener('input',function(e){
  if(e.target.classList.contains('lev')&&c.lim){      // не даём ввести больше, чем даёт биржа
   var mx=Math.max(c.lim.max_long||0,c.lim.max_short||0);
   if(mx&&+e.target.value>mx)e.target.value=mx;}
  tradeInfo(c);});
 tradeInfo(c);drawOv(c);}
function tradeCalc(c){
 var t=c.trade,px=(c.bars&&c.bars.length)?c.bars[c.bars.length-1].c:0;
 if(!t||!px)return null;
 var p=c.el.querySelector('.trd');if(!p)return null;
 var lev=Math.max(1,+p.querySelector('.lev').value||1),kind=p.querySelector('.sk').value,
     v=+p.querySelector('.sv').value||0,bal=S.bal||0,dist=Math.abs(px-t.sl);
 if(!dist)return null;
 var qty,risk,notional;
 if(kind=='risk'){risk=bal*v/100;qty=risk/dist;notional=qty*px;}
 else{var m=(kind=='usd')?v:bal*v/100;notional=m*lev;qty=notional/px;risk=qty*dist;}
 var margin=notional/lev,fee=notional*0.001;      // комиссия входа+выхода тейкером, грубо 0.1%
 var lim=c.plim||{},mxl=Math.max(lim.max_long||0,lim.max_short||0);
 var av=Math.max(lim.avail_long||0,lim.avail_short||0);
 var levBad=(mxl&&lev>mxl)?mxl:0;                 // биржа не даст такое плечо на этой паре
 var volBad=(av&&notional>av)?av:0;               // и не даст такой объём
 // 🔴 ПЛЕЧО РЕШАЕТ, ЧТО СРАБОТАЕТ ПЕРВЫМ — стоп или ликвидация. Формула боевая
 // (core/execution/calc.clamp_leverage): safe = 1/(sl_frac + буфер 1.5% на maint+slip+funding).
 var slFrac=dist/px, safeLev=Math.max(1,Math.floor(1/(slFrac+0.015)));
 var liqPx=(t.sl<px)?px*(1-1/lev):px*(1+1/lev);   // приближённая цена ликвидации
 var liqBad=(lev>safeLev)?safeLev:0;
 return {lev:lev,kind:kind,v:v,qty:qty,risk:risk,notional:notional,margin:margin,
         need:margin+fee,free:bal,levBad:levBad,volBad:volBad,
         liqBad:liqBad,liqPx:liqPx,safeLev:safeLev,slPct:slFrac*100,
         fits:((margin+fee)<=bal)&&!levBad&&!volBad&&!liqBad,
         rr:Math.abs(t.tp-px)/dist,px:px};}
function maxNotional(c){                          // сколько влезает при текущем плече и балансе
 var p=c.el.querySelector('.trd');if(!p)return 0;
 var lev=Math.max(1,+p.querySelector('.lev').value||1);
 return (S.bal||0)*0.95*lev;}                     // 5% запас на комиссию и колебание цены
function tradeInfo(c){
 var r=tradeCalc(c),el=c.el.querySelector('.trd');if(!el)return;
 var box=el.querySelector('.rr'),buy=el.querySelector('.buy'),sell=el.querySelector('.sell');
 if(!r){box.textContent='—';return;}
 // Не хватает маржи — говорим ДО отправки и гасим кнопки (раньше отказ прилетал уже с биржи)
 box.innerHTML='RR <b style=color:var(--tx)>'+r.rr.toFixed(2)+'</b> · риск <b style=color:var(--dn)>$'+
  r.risk.toFixed(2)+'</b> · объём $'+r.notional.toFixed(0)+' · маржа '+
  '<b style="color:'+(r.fits?'var(--tx)':'var(--dn)')+'">$'+r.margin.toFixed(2)+'</b>'+
  ' <span class=mx title="подставить максимум под баланс" style="cursor:pointer;color:var(--gold)">'+
  'своб. $'+r.free.toFixed(2)+'</span>'+
  ' <span title="цена ликвидации при текущем плече — стоп ОБЯЗАН быть ближе неё" style="color:'+
   (r.liqBad?'var(--dn)':'var(--dim)')+'">ликв '+(+r.liqPx).toPrecision(5)+'</span>'+
  (r.liqBad?' <b class=fixlev style="color:var(--dn);cursor:pointer" title="поставить безопасное плечо">'+
    '× ликвидация ближе стопа → x'+r.liqBad+'</b>'
   :r.levBad?' <b style=color:var(--dn)>× плечо: макс x'+r.levBad+'</b>'
   :r.volBad?' <b style=color:var(--dn)>× биржа даёт $'+r.volBad.toFixed(0)+'</b>'
   :r.fits?'':' <b style=color:var(--dn)>× не хватает</b>');
 [buy,sell].forEach(function(b){if(b){b.style.opacity=r.fits?1:.35;
  b.style.pointerEvents=r.fits?'auto':'none';}});
 var fx=box.querySelector('.fixlev');
 if(fx)fx.onclick=function(){var lv=el.querySelector('.lev');if(lv){lv.value=r.liqBad;tradeInfo(c);}};
 var mx=box.querySelector('.mx');
 if(mx)mx.onclick=function(){                     // клик по «своб.» — максимум, что влезает
  var p=c.el.querySelector('.trd'),sk=p.querySelector('.sk'),sv=p.querySelector('.sv');
  sk.value='usd';sv.value=((S.bal||0)*0.95).toFixed(2);tradeInfo(c);};}
function grabbable(c){          // что можно тянуть: планируемые уровни и защита открытой позиции
 var a=[],p=S.pos&&S.pos[c.sym];
 if(c.trade){a.push(['sl',c.trade.sl]);a.push(['tp',c.trade.tp]);}
 if(p){(p.sls||[]).forEach(function(v){a.push(['psl',v]);});     // защита позиции тоже тянется:
       (p.tps||[]).forEach(function(v){a.push(['ptp',v]);});}    // все уровни монеты едут вместе
 return a;}
function tradeGrab(c,e){
 if(S.tool)return;
 var r=c.body.getBoundingClientRect(),my=e.clientY-r.top;
 grabbable(c).forEach(function(l){if(c.grab)return;
  var y=c.cs.priceToCoordinate(l[1]);if(y!=null&&Math.abs(y-my)<7)c.grab=l[0];});
 if(c.grab){e.preventDefault();e.stopPropagation();
  c.ch.applyOptions({handleScroll:false,handleScale:false});}}
function tradeDrag(c,e){
 var r=c.body.getBoundingClientRect(),my=e.clientY-r.top;
 if(!c.grab){                                      // курсор над линией — показываем «схватить»
  var near=false;
  grabbable(c).forEach(function(l){var y=c.cs.priceToCoordinate(l[1]);
   if(y!=null&&Math.abs(y-my)<7)near=true;});
  if(!S.tool)c.body.style.cursor=near?'ns-resize':'';return;}
 var p=c.cs.coordinateToPrice(my);if(p==null||p<=0)return;
 if(c.grab=='psl'||c.grab=='ptp'){var o=S.pos[c.sym],k=(c.grab=='psl')?'sls':'tps';
  o[k]=[p];o[c.grab=='psl'?'sl':'tp']=p;}     // тянем группу: все уровни монеты на одну цену
 else{c.trade[c.grab]=p;tradeInfo(c);}
 drawOv(c);}
async function dropGrab(c){                        // отпустили линию защиты → двигаем ордер на бирже
 var k=c.grab;c.grab=null;
 c.ch.applyOptions({handleScroll:!S.tool,handleScale:!S.tool});
 if(k!='psl'&&k!='ptp')return;
 var p=S.pos&&S.pos[c.sym];if(!p)return;
 var kind=(k=='psl')?'sl':'tp',price=p[kind];
 if(S.acc=='live'&&!confirm('🔴 РЕАЛЬНЫЙ счёт\\nперенести '+kind.toUpperCase()+' по '+c.sym+
   ' на '+(+price).toPrecision(6)+'?')){acct();return;}
 try{var r=await fetch('/api/protect',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sym:c.sym,mode:S.acc,kind:kind,price:price})});
  var d=await r.json();
  if(!d.ok)alert('❌ '+kind.toUpperCase()+' не перенесён: '+(d.error||'отказ биржи'));
 }catch(e){alert('❌ сеть: '+e);}
 acct();}                                          // подтягиваем фактическое состояние с биржи
function drawTrade(c,g,GW,GH){
 var px=(c.bars&&c.bars.length)?c.bars[c.bars.length-1].c:0;
 g.font='bold 9px -apple-system,Segoe UI,sans-serif';
 function line(p,col,tx,dash,right){
  var y=c.cs.priceToCoordinate(p);if(y==null||y<0||y>GH)return;
  g.strokeStyle=col;g.lineWidth=dash?1.4:1.1;g.setLineDash(dash?[6,3]:[]);
  g.beginPath();g.moveTo(0,y);g.lineTo(GW,y);g.stroke();g.setLineDash([]);
  var w=g.measureText(tx).width+8,x=right?GW-w-2:2;
  g.fillStyle=col;g.fillRect(x,y-6,w,12);
  g.fillStyle='#131722';g.fillText(tx,x+4,y+3);}
 var pos=S.pos&&S.pos[c.sym];          // ОТКРЫТАЯ ПОЗИЦИЯ: вход + реальные SL/TP с биржи
 if(pos){
  var pl=(pos.pnl>=0?'+':'')+pos.pnl.toFixed(2),nn=(pos.n>1?(' ×'+pos.n):'');
  line(pos.entry,'#e0b25c',pos.side+nn+' '+(+pos.qty).toPrecision(6)+' @ '+
   (+pos.entry).toPrecision(6)+' · $'+pl,false,false);
  (pos.sls||[]).forEach(function(v){line(v,'#ef5350','SL '+(+v).toPrecision(6),false,true);});
  (pos.tps||[]).forEach(function(v){line(v,'#26a69a','TP '+(+v).toPrecision(6),false,true);});}
 var t=c.trade;if(!t)return;           // ПЛАНИРУЕМЫЕ уровни (пунктиром, тянутся мышью)
 [[t.sl,'#ef5350','SL'],[t.tp,'#26a69a','TP']].forEach(function(l){
  var d=px?((l[0]-px)/px*100):0;
  line(l[0],l[1],l[2]+' '+(+l[0]).toPrecision(6)+' ('+(d>0?'+':'')+d.toFixed(2)+'%)',true,false);});}
async function sendOrder(c,side){
 var r=tradeCalc(c);if(!r){alert('нет данных для расчёта');return;}
 if(r.levBad){alert('Плечо x'+r.lev+' недоступно на '+c.sym+': максимум x'+r.levBad+
  '.\\nБиржа посчитает маржу по СВОЕМУ плечу — отсюда «Insufficient margin».');return;}
 if(r.volBad){alert('Объём $'+r.notional.toFixed(0)+' больше доступного: биржа даёт $'+
  r.volBad.toFixed(0)+' по этой паре.');return;}
 if(r.liqBad){alert('Опасное плечо: при x'+r.lev+' ликвидация (~'+(+r.liqPx).toPrecision(6)+
  ') окажется БЛИЖЕ стопа — позицию вынесет раньше, чем сработает защита.\\nСтоп '+
  r.slPct.toFixed(2)+'% → безопасное плечо x'+r.liqBad+'.');return;}
 if(r.levBad){alert('Плечо x'+r.lev+' недоступно на '+c.sym+': максимум x'+r.levBad+'.');return;}
 if(r.volBad){alert('Объём $'+r.notional.toFixed(0)+' больше доступного: биржа даёт $'+
  r.volBad.toFixed(0)+'.');return;}
 if(!r.fits){alert('Не хватает маржи: нужно $'+r.need.toFixed(2)+' (позиция $'+r.notional.toFixed(0)+
  ' ÷ плечо '+r.lev+' + комиссия), свободно $'+r.free.toFixed(2)+
  '.\\nУменьши размер, подними плечо или нажми «своб.» для максимума.');return;}
 var t=c.trade,px=r.px;
 if(side=='BUY'&&!(t.sl<px&&px<t.tp)){alert('для LONG: SL под ценой, TP над ценой');return;}
 if(side=='SELL'&&!(t.tp<px&&px<t.sl)){alert('для SHORT: TP под ценой, SL над ценой');return;}
 var txt=side+' '+c.sym+' · '+S.acc.toUpperCase()+' · x'+r.lev+'\\nобъём $'+r.notional.toFixed(0)+
  ' (маржа $'+r.margin.toFixed(2)+')\\nSL '+(+t.sl).toPrecision(6)+' · TP '+(+t.tp).toPrecision(6)+
  '\\nриск $'+r.risk.toFixed(2)+' · RR '+r.rr.toFixed(2)+
  '\\nсвободно на счёте $'+r.free.toFixed(2);
 if(!confirm((S.acc=='live'?'🔴 РЕАЛЬНЫЕ ДЕНЬГИ\\n\\n':'VST-демо\\n\\n')+txt))return;
 try{var res=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sym:c.sym,side:side,mode:S.acc,lev:r.lev,sl:t.sl,tp:t.tp,
    size:{kind:r.kind,v:r.v}})});
  var d=await res.json();
  if(d.ok){alert('✅ ордер отправлен · '+d.qty+' '+c.sym+' · id '+(d.order_id||'—'));acct();}
  else alert('❌ '+(d.error||'отказ биржи'));
 }catch(e){alert('❌ сеть: '+e);}}
async function closePos(c,part){
 var p=S.pos&&S.pos[c.sym];
 if(!p){if(!confirm('Позиции по '+c.sym+' нет. Снять висящие SL/TP-ордера?'))return;}
 else{var t=(part>=1?'Закрыть ВСЮ позицию':'Закрыть ПОЛОВИНУ')+' '+c.sym+' '+p.side+
   ' ('+(+p.qty).toPrecision(6)+', PnL $'+p.pnl.toFixed(2)+')'+
   (part>=1?'\\nи снять её SL/TP-ордера?':'\\nзащита переедет на остаток.');
  if(!confirm((S.acc=='live'?'🔴 РЕАЛЬНЫЙ счёт\\n\\n':'')+t))return;}
 try{var r=await fetch('/api/close',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sym:c.sym,mode:S.acc,part:part})});
  var d=await r.json();
  if(d.ok)alert('✅ '+(d.msg||('закрыто позиций: '+d.closed+', снято ордеров: '+d.cancelled)));
  else alert('❌ '+(d.error||'отказ биржи'));
 }catch(e){alert('❌ сеть: '+e);}
 acct();}
async function toBreakeven(c){                     // стоп на цену входа — тот же перенос защиты
 var p=S.pos&&S.pos[c.sym];if(!p){alert('нет открытой позиции');return;}
 var px=(c.bars&&c.bars.length)?c.bars[c.bars.length-1].c:0;
 var bad=(p.side=='LONG')?(px<=p.entry):(px>=p.entry);
 if(bad&&!confirm('Цена ещё не ушла в плюс — стоп в безубыток сработает почти сразу. Всё равно?'))return;
 try{var r=await fetch('/api/protect',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sym:c.sym,mode:S.acc,kind:'sl',price:p.entry})});
  var d=await r.json();
  if(!d.ok)alert('❌ '+(d.error||'отказ биржи'));
 }catch(e){alert('❌ сеть: '+e);}
 acct();}
async function acct(loud){
 if(document.hidden&&!loud)return;              // фоновая вкладка не тратит лимит приватных ручек
 try{var r=await fetch('/api/account?mode='+S.acc,{cache:'no-store'});var d=await r.json();
  if(d.error){document.getElementById('bal').innerHTML='<span style=color:var(--dn)>'+d.error+'</span>';
   S.bal=0;
   if(loud&&S.acc=='live'){alert('LIVE недоступен:\\n'+d.error+'\\n\\nВозвращаю на VST.');
    S.acc='vst';setBt('#b_acc_vst,#b_acc_live',document.getElementById('b_acc_vst'));
    document.getElementById('b_acc_live').classList.remove('live');acct();}
   return;}
  S.bal=d.balance||0;
  S.pos={};(d.pos||[]).forEach(function(p){S.pos[p.sym]=p;});
  var pn=posSyms().length;
  document.getElementById('posn').textContent=pn?(' '+pn):'';
  if(S.src=='pos'&&posSyms().join()!==S.syms.join())pullSyms();   // позиция открылась/закрылась
  var pnl=(d.pos||[]).reduce(function(a,p){return a+(p.pnl||0);},0);
  document.getElementById('bal').innerHTML='$'+S.bal.toFixed(2)+(d.pos&&d.pos.length?
   (' · поз '+d.pos.length+' <span style="color:'+(pnl>=0?'var(--up)':'var(--dn)')+'">'+
    (pnl>=0?'+':'')+pnl.toFixed(2)+'$</span>'):'');
  Object.keys(S.cells).forEach(function(s){var c=S.cells[s];
   if(c.trade)tradeInfo(c);
   var p=S.pos[s];                     // бейдж позиции в шапке окна + перерисовка линий
   var b=c.el.querySelector('.pos');
   if(p&&!b){b=document.createElement('span');b.className='fg pos';c.el.querySelector('.chd').insertBefore(b,c.el.querySelector('.fl'));}
   if(b){if(p){b.className='fg pos '+(p.side=='LONG'?'b':'s');
     b.innerHTML=p.side+' '+(p.pnl>=0?'+':'')+p.pnl.toFixed(2)+'$<span class=cx role=button tabindex=0 aria-label="Закрыть позицию" title="закрыть позицию">✕</span>';
     b.querySelector('.cx').onclick=function(e){e.stopPropagation();closePos(c,1);};}else b.remove();}
   drawOv(c);});
 }catch(e){}}
function ptOf(c,e){
 var r=c.body.getBoundingClientRect(),x=e.clientX-r.left,yy=e.clientY-r.top;
 var ts=c.ch.timeScale(),t=ts.coordinateToTime(x),p=c.cs.coordinateToPrice(yy);
 if(t==null&&c.bars&&c.bars.length>1){      // клик правее последнего бара → время в будущем
  var b=c.bars,tl=b[b.length-1].t,xl=ts.timeToCoordinate(tl);
  var xp=ts.timeToCoordinate(b[b.length-2].t),sp=(xl!=null&&xp!=null)?(xl-xp):6;
  t=(xl!=null&&sp>0)?tl+Math.round((x-xl)/sp)*barStep(c):tl;}
 return {t:t,p:p};}
function onDraw(c,e){
 if(!S.tool)return;
 e.preventDefault();e.stopPropagation();
 var q=ptOf(c,e);if(q.p==null||q.t==null)return;
 if(S.tool=='hl'){objs(c.sym).push({k:'hl',p:q.p});saveDraw();drawOv(c);return;}
 if(!c.pend){c.pend={k:S.tool,t0:q.t,p0:q.p};return;}
 objs(c.sym).push({k:c.pend.k,t0:c.pend.t0,p0:c.pend.p0,t1:q.t,p1:q.p});
 c.pend=null;c.hover=null;saveDraw();drawOv(c);}
function onErase(c,e){                   // правый клик — стереть ближайший объект
 e.preventDefault();
 var r=c.body.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 var a=objs(c.sym),best=-1,bd=12;
 a.forEach(function(o,i){var d=1e9,py=o.k=='hl'?c.cs.priceToCoordinate(o.p):null;
  if(py!=null)d=Math.abs(py-my);
  else{var y0=c.cs.priceToCoordinate(o.p0),y1=c.cs.priceToCoordinate(o.p1);
   if(y0!=null&&y1!=null)d=Math.min(Math.abs(y0-my),Math.abs(y1-my));}
  if(d<bd){bd=d;best=i;}});
 if(best>=0){a.splice(best,1);saveDraw();drawOv(c);}}
// Заливка между wt1/wt2 + зоны OB/OS (в TG-чарте это fill_between + axhline)
function drawWt(c){
 if(!c.ovw||!c.wtd||document.hidden)return;
 var cv=c.ovw,wb=c.el.querySelector('.cwt'),dpr=window.devicePixelRatio||1;
 var W=wb.clientWidth,H=wb.clientHeight;
 if(cv.width!==W*dpr||cv.height!==H*dpr){cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';}
 var g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);
 var ts=c.wch.timeScale(),y=function(v){return c.w1.priceToCoordinate(v);};
 var yob=y(60),yos=y(-60);
 if(yob!=null&&yob>0){g.fillStyle='rgba(239,83,80,.07)';g.fillRect(0,0,W,yob);}       // зона OB
 if(yos!=null&&yos<H){g.fillStyle='rgba(38,166,154,.07)';g.fillRect(0,yos,W,H-yos);}  // зона OS
 g.beginPath();var started=false;
 c.wtd.forEach(function(p){var x=ts.timeToCoordinate(p.t),a=y(p.a);
  if(x==null||a==null)return;started?g.lineTo(x,a):(g.moveTo(x,a),started=true);});
 for(var i=c.wtd.length-1;i>=0;i--){var p=c.wtd[i],x=ts.timeToCoordinate(p.t),b=y(p.b);
  if(x==null||b==null)continue;g.lineTo(x,b);}
 if(started){g.closePath();g.fillStyle='rgba(33,150,243,.15)';g.fill();}}
function renderGrid(){
 var g=document.getElementById('grid');
 g.style.gridTemplateColumns='repeat('+cols()+',1fr)';
 g.style.gridTemplateRows='repeat('+Math.ceil(S.grid/cols())+',1fr)';
 var need=vis(),keep={};
 need.forEach(function(s){keep[s]=1;});
 Object.keys(S.cells).forEach(function(s){if(!keep[s]){S.cells[s].ro.disconnect();
  S.cells[s].ch.remove();if(S.cells[s].wch)S.cells[s].wch.remove();S.cells[s].el.remove();delete S.cells[s];}});
 var msg=g.querySelector('.empty');if(msg)msg.remove();
 need.forEach(function(s){if(!S.cells[s])S.cells[s]=mkCell(s);else g.appendChild(S.cells[s].el);});
 if(!need.length)g.innerHTML='<div class=empty>нет монет под условия фильтра — ослабь параметры на <a href="/filter" style=color:var(--gold)>/filter</a></div>';
 document.getElementById('pg').textContent=(S.page+1)+'/'+Math.max(1,Math.ceil(S.syms.length/S.grid));
 document.getElementById('cnt').textContent=S.syms.length;
 need.forEach(function(s){var c=S.cells[s],t=(S.playTags||{})[s];   // метки источников «в игре»
  if(!c)return;var b=c.el.querySelector('.plt');
  if(t&&!b){b=document.createElement('span');b.className='fg plt';
   c.el.querySelector('.chd').insertBefore(b,c.el.querySelector('.fl'));}
  if(b){if(t){b.innerHTML='<span class=tg>'+t+'</span>';b.title=tagHint(t);}else b.remove();}});
 if(S.tool)setTool(S.tool);}      // новые ячейки тоже переводим в режим рисования
// Точность шкалы по цене монеты: дефолтные 2 знака превращали 0.0026833 в «0.00» (Егор 14.08)
function precOf(p){p=Math.abs(p||0);
 return p>=100?2:p>=10?3:p>=1?4:p>=0.01?6:p>=0.0001?8:10;}
function applyBars(c,b,atr){
 c.bars=b;c.atr=atr||null;
 var pr=precOf(b[b.length-1].c);
 if(c.prec!==pr){c.prec=pr;
  c.cs.applyOptions({priceFormat:{type:'price',precision:pr,minMove:1/Math.pow(10,pr)}});}
 var cut=b[b.length-1].t-86400,ref=null;    // опора для Δ%: бар суточной давности…
 for(var i=b.length-1;i>=0;i--){if(b[i].t<=cut){ref=b[i].c;break;}}
 c.ref=ref!=null?ref:b[0].o;                // …а если истории меньше суток — начало окна
 c.rlbl=ref!=null?'24ч':Math.round((b[b.length-1].t-b[0].t)/3600)+'ч';
 c.cs.setData(b.map(function(x,i){var o={time:x.t,open:x.o,high:x.h,low:x.l,close:x.c};
  if(atr&&atr[i]&&atr[i].d){var up=atr[i].d>0;    // перекраска баров по ATRTrend (как в OKO-SM)
   o.color=up?'#26a69a':'#ef5350';o.borderColor=o.color;o.wickColor=o.color;}
  return o;}));
 c.vs.setData(b.map(function(x){return {time:x.t,value:x.v,color:x.c>=x.o?'rgba(38,166,154,.4)':'rgba(239,83,80,.4)'};}));
 // линия ATRTrend рисуется на канвасе (drawAtr): line-серия соединяла точки ЧЕРЕЗ пропуски,
 // из-за чего вместо одной переключающейся линии выходили две — зелёная снизу и красная сверху
 if(c.w1){var w=calcWt(b);c.wtd=w;
  c.w1.setData(w.map(function(x){return {time:x.t,value:x.a};}));
  c.w2.setData(w.map(function(x){return {time:x.t,value:x.b};}));
  var mk=[];                                 // кроссы wt1×wt2 (как точки в TG-чарте)
  for(var j=1;j<w.length;j++){var up=w[j-1].a<=w[j-1].b&&w[j].a>w[j].b,dn=w[j-1].a>=w[j-1].b&&w[j].a<w[j].b;
   if(up||dn)mk.push({time:w[j].t,position:'inBar',shape:'circle',size:0.5,color:up?'#26a69a':'#ef5350'});}
  c.w1.setMarkers(mk.slice(-60));drawWt(c);}
 applyPlan(c);                               // план из повестки — только когда свечи пришли
 alBar(c);                                   // ATRTrend/WT/объём — по ЗАКРЫТОМУ бару
 if(!c.fit){                                 // поле справа ~20% (место под проекцию уровней)
  var off=Math.max(4,Math.round(b.length*0.20));
  c.ch.timeScale().applyOptions({rightOffset:off});
  c.ch.timeScale().setVisibleLogicalRange({from:0,to:b.length-1+off});
  c.fit=true;}                              // зум пользователя дальше не сбрасываем
 drawOv(c);}
async function pullBars(){
 var need=vis();if(!need.length||document.hidden)return;   // фоновая вкладка не грузит биржу
 try{var r=await fetch('/api/klines?tf='+S.tf+'&limit='+S.lim+'&syms='+need.join(',')+(S.atr?'&atr=1':''),
   {cache:'no-store'});
  var d=await r.json();
  need.forEach(function(s){var b=(d.bars||{})[s],c=S.cells[s];if(!b||!b.length||!c)return;
   if(c.lim&&c.lim>S.lim){refresh(c);return;}   // окно расширено скроллом — обновляем своим лимитом
   c.lim=S.lim;applyBars(c,b,(d.atr||{})[s]);});
  document.getElementById('age').textContent='· свечи '+new Date(d.ts*1000).toLocaleTimeString('ru');
 }catch(e){}}
var _pxTick=0;
async function pullPx(){
 var need=vis();if(!need.length||document.hidden)return;
 _pxTick++;
 try{var r=await fetch('/api/prices?syms='+need.join(','),{cache:'no-store'});var d=await r.json();
  need.forEach(function(s){var p=(d.px||{})[s],c=S.cells[s];if(!p||!c)return;
   var z=c.el.querySelector('.pz'),ch=c.ref?(p.px-c.ref)/c.ref*100:null;
   z.innerHTML=(+p.px).toPrecision(6)+(ch==null?'':' <span style="color:'+(ch>=0?'var(--up)':'var(--dn)')+
     '">'+(ch>=0?'+':'')+ch.toFixed(2)+'%</span> <span style=color:var(--dim);font-size:10px>'+c.rlbl+'</span>');
   alCheck(s,p.px);                                     // пересечения уровней между тиками
   S.prevPx=S.prevPx||{};S.prevPx[s]=p.px;
   var b=c.bars&&c.bars[c.bars.length-1];if(!b)return;   // дотягиваем незакрытый бар живой ценой
   b.c=p.px;b.h=Math.max(b.h,p.px);b.l=Math.min(b.l,p.px);
   c.cs.update({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c});
   if(_pxTick%3===0)drawOv(c);});    // оверлей от тика цены почти не меняется — раз в ~9с
 }catch(e){}}
async function pullLv(){
 var need=vis();if(!need.length||(document.hidden&&S.lv))return;
 if(!S.lv){Object.keys(S.cells).forEach(function(s){var c=S.cells[s];
  c.lines.forEach(function(l){c.cs.removePriceLine(l);});c.lines=[];c.lv=null;
  c.el.querySelector('.fl').innerHTML='';drawOv(c);});return;}
 try{var r=await fetch('/api/levels?tf='+S.tf+'&syms='+need.join(','),{cache:'no-store'});var d=await r.json();
  need.forEach(function(s){var v=(d.lv||{})[s],c=S.cells[s];if(!v||!c)return;
   c.lv=v;
   c.lines.forEach(function(l){c.cs.removePriceLine(l);});c.lines=[];
   [['1D','#3f4a5c'],['1W','#5a4a28']].forEach(function(pt){var lv=(v.piv||{})[pt[0]]||{};
    Object.keys(lv).forEach(function(k){
     c.lines.push(c.cs.createPriceLine({price:lv[k],color:pt[1],lineWidth:1,lineStyle:2,
      axisLabelVisible:false,title:pt[0][1]+' '+k}));});});
   var h=[],f=v.flags||{},nb=function(a,k){return (a||[]).filter(function(x){return x.kind==k;}).length;};
   var fg=function(cls,txt,hint){return '<span class="fg '+cls+'" title="'+hint+'">'+txt+'</span>';};
   if(v.leg)h.push(fg(v.leg.side=='long'?'b':'s','нога '+v.leg.side.toUpperCase(),
    'Нога старшего масштаба OKO-SM (swing 50): от origin к экстремуму — от неё считаем откат и OTE'));
   var sw=(v.brk||[]).filter(function(b){return !b.int;}).slice(-1)[0];
   if(sw)h.push(fg(sw.dir=='bull'?'b':'s',sw.kind+(sw.dir=='bull'?'↑':'↓'),
    sw.kind=='CHoCH'?'CHoCH — смена характера: первый пробой ПРОТИВ тренда (разворот)'
                    :'BOS — пробой ПО тренду (продолжение)'));
   if(nb(v.ob,'bull'))h.push(fg('b','OB↑'+nb(v.ob,'bull'),'Order Block бычий: спокойная свеча перед сломом вверх — зона спроса'));
   if(nb(v.ob,'bear'))h.push(fg('s','OB↓'+nb(v.ob,'bear'),'Order Block медвежий: зона предложения'));
   if(nb(v.fvg,'bull'))h.push(fg('b','FVG↑'+nb(v.fvg,'bull'),'Fair Value Gap вверх: незакрытый трёхсвечный имбаланс — магнит для возврата цены'));
   if(nb(v.fvg,'bear'))h.push(fg('s','FVG↓'+nb(v.fvg,'bear'),'Fair Value Gap вниз: незакрытый имбаланс'));
   (v.eq||[]).slice(-1).forEach(function(q){h.push(fg('g',q.kind,
    q.kind=='EQH'?'Equal Highs — равные вершины: скопление стопов сверху, цель для свипа'
                 :'Equal Lows — равные донья: ликвидность снизу'));});
   if(f.OTE)h.push(fg('g','OTE','Optimal Trade Entry: цена в зоне отката 0.618–0.786 ноги'));
   if(v.regime)h.push(fg('',v.regime,'Режим рынка: TREND_UP / TREND_DOWN / RANGE'));
   c.el.querySelector('.fl').innerHTML=LV.badges?h.join(''):'';
   drawOv(c);});
 }catch(e){}}
// Расшифровка значков «в игре» — кто именно обратил внимание на монету (подсказка при наведении)
var TAGH=[['🚀','радар: ПАМП — всплеск объёма и цены'],['🌱','радар: ПРУЖИНА — сжатие перед выносом'],
 ['🔨','радар: НАКОПЛЕНИЕ — набор позиции в диапазоне'],['🎯','скринер OKO-SM: цена в OTE-зоне ноги 4h (цифра = score схождений)'],
 ['🤖','DC-советник держит по монете сделку'],['🔥','хайп: монета в тренде CoinGecko'],
 ['↑','сторона LONG'],['↓','сторона SHORT']];
function tagHint(t){
 var out=[];TAGH.forEach(function(p){if(t.indexOf(p[0])>=0)out.push(p[0]+' — '+p[1]);});
 return (out.join('\\n')||t)+'\\n\\nЧем больше значков, тем выше конфлюэнция внимания.';}
// ── АЛЕРТЫ (Егор 16.08) ─────────────────────────────────────────────────────
// Работают, пока вкладка открыта (v1). Ловим ПЕРЕСЕЧЕНИЕ уровня — сравниваем прошлую цену
// с текущей, а не «цена близко»: иначе одно касание даёт десятки повторов. Кулдаун на
// (монета+тип+уровень) добивает остаток спама. Перенос на сервер — в бэклоге.
var ALT=[['ЦЕНОВЫЕ',null],['al_line','моя линия (уровень / трендовая)'],['al_piv','пивот D/W'],
 ['al_zone','вход в зону FVG / OB'],['СОБЫТИЯ',null],['al_atr','смена ATRTrend'],
 ['al_wt','кросс WT'],['al_vol','аномалия объёма (≥3×)'],['ПРОЧЕЕ',null],
 ['al_sound','звук'],['al_notify','уведомления системы']];
var AL={};try{AL=JSON.parse(localStorage.getItem('oko_alerts')||'null')||{};}catch(e){}
ALT.forEach(function(a){if(a[1]&&AL[a[0]]===undefined)AL[a[0]]=(a[0]!='al_notify');});
var ALON=false,ALSEEN={},ALFEED=[],_ac=null;
function alSave(){try{localStorage.setItem('oko_alerts',JSON.stringify(AL));}catch(e){}}
function beep(){
 if(!AL.al_sound)return;
 try{_ac=_ac||new (window.AudioContext||window.webkitAudioContext)();
  var o=_ac.createOscillator(),g=_ac.createGain();
  o.frequency.value=880;o.connect(g);g.connect(_ac.destination);
  g.gain.setValueAtTime(.0001,_ac.currentTime);
  g.gain.exponentialRampToValueAtTime(.12,_ac.currentTime+.01);
  g.gain.exponentialRampToValueAtTime(.0001,_ac.currentTime+.22);
  o.start();o.stop(_ac.currentTime+.24);}catch(e){}}
function alFire(sym,kind,text){
 var key=sym+'|'+kind+'|'+text,now=Date.now();
 if(ALSEEN[key]&&now-ALSEEN[key]<900000)return;     // кулдаун 15 мин на то же событие
 ALSEEN[key]=now;
 var tm=new Date().toLocaleTimeString('ru');
 ALFEED.unshift({sym:sym,text:text,tm:tm});ALFEED=ALFEED.slice(0,30);
 document.getElementById('aln').textContent=' '+ALFEED.length;
 var box=document.getElementById('alog');
 var el=document.createElement('div');el.className='altoast';
 el.innerHTML='<b>'+sym+'</b> '+text+' <span class=t>'+tm+'</span>';
 box.appendChild(el);setTimeout(function(){el.remove();},9000);
 var c=S.cells[sym];
 if(c){c.el.classList.add('alerted');setTimeout(function(){c.el.classList.remove('alerted');},4000);}
 beep();
 if(AL.al_notify&&window.Notification&&Notification.permission=='granted')
  try{new Notification('OKO · '+sym,{body:text});}catch(e){}}
function fmtP(p){return (+p).toPrecision(6);}
function alCheck(sym,px){                          // px — свежая цена; prev — цена прошлого тика
 if(!ALON)return;
 var c=S.cells[sym],prev=(S.prevPx||{})[sym];
 if(prev==null||px==null||prev==px)return;
 var lo=Math.min(prev,px),hi=Math.max(prev,px),up=px>prev;
 var cross=function(v){return v!=null&&v>lo&&v<=hi;};   // уровень пройден между тиками
 if(AL.al_line)(DRAW[sym]||[]).forEach(function(o){
  if(o.k=='hl'&&cross(o.p))alFire(sym,'line',(up?'↑':'↓')+' пробой моей линии '+fmtP(o.p));
  if(o.k=='tl'&&c&&c.bars&&c.bars.length){          // трендовая: цена на «сейчас» по наклону
   var t=c.bars[c.bars.length-1].t;
   if(o.t1!=o.t0){var k=(o.p1-o.p0)/(o.t1-o.t0),v=o.p0+k*(t-o.t0);
    if(cross(v))alFire(sym,'tl',(up?'↑':'↓')+' пробой трендовой '+fmtP(v));}}});
 if(AL.al_piv&&c&&c.lv&&c.lv.piv)['1D','1W'].forEach(function(tf){
  var lv=c.lv.piv[tf]||{};
  Object.keys(lv).forEach(function(k){
   if(cross(lv[k]))alFire(sym,'piv',(up?'↑':'↓')+' пивот '+tf[1]+':'+k+' '+fmtP(lv[k]));});});
 if(AL.al_zone&&c&&c.lv){
  (c.lv.fvg||[]).forEach(function(z){
   var inNow=px>=z.bot&&px<=z.top,inPrev=prev>=z.bot&&prev<=z.top;
   if(inNow&&!inPrev)alFire(sym,'fvg','вошла в FVG '+fmtP(z.bot)+'–'+fmtP(z.top));});
  (c.lv.ob||[]).forEach(function(z){
   var inNow=px>=z.bot&&px<=z.top,inPrev=prev>=z.bot&&prev<=z.top;
   if(inNow&&!inPrev)alFire(sym,'ob','вошла в OB '+(z.kind=='bull'?'↑':'↓')+' '+fmtP(z.bot)+'–'+fmtP(z.top));});}}
function alBar(c){                                 // события по ЗАКРЫТОМУ бару (не по тику)
 if(!ALON||!c.bars||c.bars.length<3)return;
 var last=c.bars[c.bars.length-2],key=c.sym+'|bar|'+last.t;
 if(c._alBar==key)return;c._alBar=key;
 if(AL.al_atr&&c.atr&&c.atr.length>2){
  var a=c.atr,n=a.length-2;
  if(a[n]&&a[n-1]&&a[n].d&&a[n-1].d&&a[n].d!==a[n-1].d)
   alFire(c.sym,'atr','смена ATRTrend '+(a[n].d>0?'вверх ↑':'вниз ↓'));}
 if(AL.al_wt&&c.wtd&&c.wtd.length>2){
  var w=c.wtd,m=w.length-2;
  var upx=w[m-1].a<=w[m-1].b&&w[m].a>w[m].b,dnx=w[m-1].a>=w[m-1].b&&w[m].a<w[m].b;
  if(upx||dnx)alFire(c.sym,'wt','кросс WT '+(upx?'вверх ↑':'вниз ↓')+' ('+w[m].a.toFixed(0)+')');}
 if(AL.al_vol&&c.bars.length>25){
  var v=c.bars.slice(-22,-1).map(function(b){return b.v;});
  var ma=v.slice(0,20).reduce(function(x,y){return x+y;},0)/20;
  if(ma>0&&last.v/ma>=3)alFire(c.sym,'vol','объём ×'+(last.v/ma).toFixed(1)+
   ' ('+(last.c>=last.o?'вверх':'вниз')+')');}}
// ИЗБРАННОЕ: свой список для наблюдения, переживает перезагрузку (localStorage)
var FAV=[];try{FAV=JSON.parse(localStorage.getItem('oko_fav')||'[]');}catch(e){}
function favSave(){try{localStorage.setItem('oko_fav',JSON.stringify(FAV));}catch(e){}
 document.getElementById('favn').textContent=FAV.length?(' '+FAV.length):'';}
function favToggle(sym,el){
 var i=FAV.indexOf(sym);
 if(i<0)FAV.push(sym);else FAV.splice(i,1);
 favSave();
 if(el){el.classList.toggle('on',FAV.indexOf(sym)>=0);el.textContent=FAV.indexOf(sym)>=0?'★':'☆';}
 if(S.src=='fav')pullSyms();}
function posSyms(){return Object.keys(S.pos||{}).sort();}
async function playSyms(){               // «в игре» = конфлюэнция внимания источников (как в кокпите)
 try{var r=await fetch('/api/inplay',{cache:'no-store'});var d=await r.json();
  S.playTags={};(d.coins||[]).forEach(function(c){S.playTags[c.sym]=c.tags;});
  return (d.coins||[]).map(function(c){return c.sym;});
 }catch(e){return S.syms;}}
async function pullSyms(){
 if(S.src=='plan'){S.syms=[PLAN.sym];return;}      // пришли с планом — показываем только её
 if(S.src=='fav'){
  var fv=FAV.slice().sort();
  if(fv.join()!==S.syms.join()){S.syms=fv;
   if(S.page*S.grid>=S.syms.length)S.page=0;
   renderGrid();await pullBars();pullPx();pullLv();}
  return;}
 if(S.src=='play'){
  var pl=await playSyms();
  document.getElementById('playn').textContent=pl.length?(' '+pl.length):'';
  if(pl.join()!==S.syms.join()){S.syms=pl;
   if(S.page*S.grid>=S.syms.length)S.page=0;
   renderGrid();await pullBars();pullPx();pullLv();}
  return;}
 if(S.src=='pos'){                       // вкладка «мои позиции»: состав = монеты с позициями
  var next=posSyms();
  if(next.join()!==S.syms.join()){S.syms=next;
   if(S.page*S.grid>=S.syms.length)S.page=0;
   renderGrid();await pullBars();pullPx();pullLv();}
  return;}
 if(!S.live){if(S.pinned)S.syms=S.pinned;return;}
 try{var r=await fetch('/api/filter',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(S.q)});var d=await r.json();
  var next=(d.coins||[]).slice()                          // ликвидные вперёд: первые окна = значимые
   .sort(function(a,b){return (b.turn||0)-(a.turn||0);}).map(function(x){return x.sym;});
  if(next.join()!==S.syms.join()){S.syms=next;
   if(S.page*S.grid>=S.syms.length)S.page=0;
   renderGrid();await pullBars();pullPx();pullLv();}
 }catch(e){}}
function zoomCell(c){                    // двойной клик по шапке — окно на весь экран (Esc/повтор — назад)
 var bar=document.getElementById('bar');
 document.documentElement.style.setProperty('--zt',   // верх окна = под панелью управления
  Math.round(bar.getBoundingClientRect().bottom+6)+'px');
 var on=c.el.classList.toggle('zoom');
 Object.keys(S.cells).forEach(function(s){if(S.cells[s]!==c)S.cells[s].el.classList.remove('zoom');});
 S.zoom=on?c.sym:null;
 var z=c.el.querySelector('.zi');
 if(on&&!z){z=document.createElement('span');z.className='zi';z.textContent='⤢ Esc';
  c.el.querySelector('.chd').appendChild(z);}
 else if(!on&&z)z.remove();
 setTimeout(function(){                  // дать layout примениться, затем пересчитать графики
  c.ch.resize(c.body.clientWidth,c.body.clientHeight);
  if(c.wch){var w=c.el.querySelector('.cwt');c.wch.resize(w.clientWidth,w.clientHeight);drawWt(c);}
  drawOv(c);},60);}
function setBt(sel,el){document.querySelectorAll(sel).forEach(function(b){b.classList.remove('on');});el.classList.add('on');}
document.querySelectorAll('[data-g]').forEach(function(b){b.onclick=function(){
 setBt('[data-g]',b);S.grid=+b.dataset.g;S.page=0;renderGrid();pullBars().then(function(){pullPx();pullLv();});};});
document.querySelectorAll('#bar [data-tf]').forEach(function(b){b.onclick=function(){
 setBt('#bar [data-tf]',b);S.tf=b.dataset.tf;
 Object.keys(S.cells).forEach(function(k){                     // подсветка ТФ в шапках окон
  S.cells[k].el.querySelectorAll('.ztfb').forEach(function(x){
   x.classList.toggle('on',x.dataset.ztf===S.tf);});});
 Object.keys(S.cells).forEach(function(s){S.cells[s].lim=S.lim;S.cells[s].fit=false;});  // новый ТФ — новое окно
 Object.keys(S.cells).forEach(function(s){S.cells[s].el.querySelector('.sy').href=
  'https://ru.tradingview.com/chart/?symbol=BINGX%3A'+s+'USDT.P&interval='+({'5m':'5','15m':'15','1h':'60','4h':'240','1d':'D'}[S.tf]);});
 pullBars().then(function(){pullPx();pullLv();});};});
document.getElementById('b_live').onclick=function(){S.src='filter';S.live=true;S.pinned=null;
 setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',this);pullSyms();};
document.getElementById('b_pin').onclick=function(){S.src='filter';S.live=false;S.pinned=S.syms.slice();
 setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',this);};
document.getElementById('b_fav').onclick=function(){S.src='fav';S.page=0;
 setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',this);S.syms=[];pullSyms();};
document.getElementById('b_play').onclick=function(){S.src='play';S.page=0;
 setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',this);S.syms=[];pullSyms();};
document.getElementById('b_pos').onclick=function(){S.src='pos';S.page=0;
 setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',this);S.syms=[];pullSyms();};
document.getElementById('b_lv').onclick=function(){S.lv=!S.lv;this.classList.toggle('on',S.lv);pullLv();};
(function(){                                   // выпадающее меню слоёв
 var menu=document.getElementById('lvmenu'),grp=document.getElementById('lvgrp');
 menu.innerHTML=LAYERS.map(function(l){
  if(!l[1])return '<div class=sec>'+l[0]+'</div>';
  return '<label><input type=checkbox data-l="'+l[0]+'"'+(LV[l[0]]?' checked':'')+'>'+l[1]+'</label>';
 }).join('')+'<div class=sec>всё</div><span class=all data-all=1>включить</span> '+
  '<span class=all data-all=0>выключить</span>';
 function apply(){lvSave();
  Object.keys(S.cells).forEach(function(s){drawOv(S.cells[s]);});
  pullLv();}                                   // бейджи перестраиваются там же
 menu.addEventListener('change',function(e){
  var k=e.target.getAttribute('data-l');if(!k)return;LV[k]=e.target.checked;apply();});
 menu.addEventListener('click',function(e){
  var a=e.target.getAttribute('data-all');if(a===null)return;
  LAYERS.forEach(function(l){if(l[1])LV[l[0]]=(a==='1');});
  menu.querySelectorAll('input[data-l]').forEach(function(i){i.checked=(a==='1');});
  apply();});
 document.getElementById('b_al').onclick=function(){         // мастер-тумблер алертов
  ALON=!ALON;this.classList.toggle('on',ALON);
  if(ALON&&AL.al_notify&&window.Notification&&Notification.permission=='default')
   Notification.requestPermission();
  if(ALON)beep();};
 var am=document.getElementById('almenu'),ag=document.getElementById('algrp');
 am.innerHTML=ALT.map(function(a){
  if(!a[1])return '<div class=sec>'+a[0]+'</div>';
  return '<label><input type=checkbox data-a="'+a[0]+'"'+(AL[a[0]]?' checked':'')+'>'+a[1]+'</label>';
 }).join('')+'<div class=sec>лента</div><div id=alfeed style="max-height:150px;overflow:auto;'+
  'font-size:11px;color:var(--dim);padding:2px 5px">пока пусто</div>';
 am.addEventListener('change',function(e){
  var k=e.target.getAttribute('data-a');if(!k)return;AL[k]=e.target.checked;alSave();
  if(k=='al_notify'&&e.target.checked&&window.Notification)Notification.requestPermission();});
 document.getElementById('b_al_dd').onclick=function(e){e.stopPropagation();
  ag.classList.toggle('open');
  if(ag.classList.contains('open'))document.getElementById('alfeed').innerHTML=
   ALFEED.length?ALFEED.map(function(f){return '<div><b style=color:var(--tx)>'+f.sym+'</b> '+
    f.text+' <span style=opacity:.7>'+f.tm+'</span></div>';}).join(''):'пока пусто';};
 document.addEventListener('click',function(e){if(!ag.contains(e.target))ag.classList.remove('open');});
 // РУЧНОЙ ПОИСК монеты: Enter добавляет в избранное и показывает его (Егор 16.08)
 var q=document.getElementById('q_sym');
 fetch('/api/symbols').then(function(r){return r.json();}).then(function(d){
  document.getElementById('symlist').innerHTML=(d.syms||[]).map(function(x){
   return '<option value="'+x+'">';}).join('');S.allSyms=d.syms||[];}).catch(function(){});
 q.addEventListener('keydown',function(e){
  if(e.key!='Enter')return;
  var v=(q.value||'').trim().toUpperCase().replace(/[-\\/]?USDT.*$/,'');
  if(!v)return;
  if(S.allSyms&&S.allSyms.length&&S.allSyms.indexOf(v)<0){
   var hit=S.allSyms.filter(function(x){return x.indexOf(v)===0;})[0];
   if(!hit){alert('Нет такой пары на BingX: '+v);return;}
   v=hit;}
  if(FAV.indexOf(v)<0){FAV.push(v);favSave();}
  q.value='';
  S.src='fav';S.page=0;setBt('#b_live,#b_pin,#b_pos,#b_play,#b_fav',document.getElementById('b_fav'));
  S.syms=[];pullSyms();});
 document.getElementById('b_lv_dd').onclick=function(e){e.stopPropagation();
  grp.classList.toggle('open');
  if(grp.classList.contains('open')&&!S.lv)document.getElementById('b_lv').click();};
 document.addEventListener('click',function(e){
  if(!grp.contains(e.target))grp.classList.remove('open');});
})();
document.getElementById('b_atr').onclick=function(){S.atr=!S.atr;this.classList.toggle('on',S.atr);pullBars();};
function setTool(t){                    // при активном инструменте график не таскаем — иначе клик уедет
 S.tool=t;
 document.querySelectorAll('[data-t]').forEach(function(b){b.classList.toggle('on',b.dataset.t===t);});
 Object.keys(S.cells).forEach(function(s){var c=S.cells[s];c.pend=null;c.hover=null;
  c.body.style.cursor=t?'crosshair':'';
  c.ch.applyOptions({handleScroll:!t,handleScale:!t});drawOv(c);});}
document.querySelectorAll('[data-t]').forEach(function(b){b.onclick=function(){
 setTool(S.tool===b.dataset.t?null:b.dataset.t);};});
document.getElementById('b_clr').onclick=function(){
 vis().forEach(function(s){DRAW[s]=[];var c=S.cells[s];if(c){c.pend=null;drawOv(c);}});saveDraw();};
document.addEventListener('keydown',function(e){
 if(e.key=='Escape'){if(S.zoom&&S.cells[S.zoom])zoomCell(S.cells[S.zoom]);else setTool(null);return;}
 if(e.code=='Space'){e.preventDefault();page(e.shiftKey?-1:1);}    // пробел — следующая страница
 if(e.key=='ArrowRight')page(1);if(e.key=='ArrowLeft')page(-1);});
document.getElementById('b_wt').onclick=function(){S.wt=!S.wt;this.classList.toggle('on',S.wt);
 Object.keys(S.cells).forEach(function(s){var c=S.cells[s];c.ro.disconnect();c.ch.remove();
  if(c.wch)c.wch.remove();c.el.remove();delete S.cells[s];});
 renderGrid();pullBars().then(function(){pullPx();pullLv();});};
function page(d){                   // d=+1/−1, по кругу (пробел листает вперёд)
 var n=Math.max(1,Math.ceil(S.syms.length/S.grid));
 S.page=((S.page+d)%n+n)%n;renderGrid();pullBars().then(function(){pullPx();pullLv();});}
document.getElementById('pg_p').onclick=function(){page(-1);};
document.getElementById('pg_n').onclick=function(){page(1);};
document.getElementById('b_acc_vst').onclick=function(){S.acc='vst';
 setBt('#b_acc_vst,#b_acc_live',this);this.classList.remove('live');acct();};
document.getElementById('b_acc_live').onclick=function(){
 if(!confirm('Переключить на РЕАЛЬНЫЙ счёт? Ордера пойдут живыми деньгами.'))return;
 S.acc='live';setBt('#b_acc_vst,#b_acc_live',this);this.classList.add('live');acct(true);};
document.addEventListener('visibilitychange',function(){    // вернулись на вкладку — догнать
 if(!document.hidden){pullBars().then(function(){pullPx();pullLv();});acct();}});
favSave();
(async function(){await pullSyms();renderGrid();await pullBars();pullPx();pullLv();acct();})();
setInterval(pullSyms,30000);setInterval(pullBars,20000);setInterval(pullPx,3000);
setInterval(pullLv,60000);setInterval(acct,60000);
</script></body></html>"""


async def monitor_page(_req):
    """GET /monitor — сетка живых графиков по монетам, прошедшим фильтр (Егор 14.08)."""
    return web.Response(text=_page(_MONITOR_HTML, "/monitor"), content_type="text/html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


def main():
    app = web.Application()
    app.router.add_get("/", agenda_page)
    app.router.add_get("/cockpit", index)
    app.router.add_get("/api/structure", api)
    app.router.add_get("/api/screener", api_screener)
    app.router.add_get("/api/breadth", api_breadth)
    app.router.add_get("/api/agenda", api_agenda)
    app.router.add_get("/api/scoreboard", api_scoreboard)
    app.router.add_get("/api/inplay", api_inplay)
    app.router.add_post("/api/filter", api_filter)
    app.router.add_get("/filter", filter_page)
    app.router.add_get("/guide", guide_page)
    app.router.add_get("/monitor", monitor_page)
    app.router.add_get("/api/klines", api_klines)
    app.router.add_get("/api/prices", api_prices)
    app.router.add_get("/api/symbols", api_symbols)
    app.router.add_get("/api/levels", api_levels)
    app.router.add_get("/api/account", api_account)
    app.router.add_get("/api/levinfo", api_levinfo)
    app.router.add_post("/api/trade", api_trade)
    app.router.add_post("/api/protect", api_protect)
    app.router.add_post("/api/close", api_close)
    app.router.add_get("/api/pair/{base}", api_pair)
    _vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "vendor")
    if os.path.isdir(_vendor):
        app.router.add_static("/vendor", _vendor)
    print(f"[STRUCT] терминал структуры → http://localhost:{PORT} (развязан от oko-bot/прокси)")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
