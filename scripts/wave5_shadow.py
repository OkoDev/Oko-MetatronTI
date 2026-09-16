# -*- coding: utf-8 -*-
"""ТЕНЬ-ФОРВАРД ядра «коррекция после пятой волны» (14.09.2026). Без денег.

Два цикла (--loop): ПОЛНАЯ разметка всех монет после закрытия каждого 4h-бара (UTC 00/04/08/… +3 мин)
и ЛЁГКИЙ цикл каждые 15 минут по активным сетапам (вход по кроссу WT / пробою линии 2-4 на 15m, исход,
достижение фибо-прогноза). Детектор — core/waves (тот же, что в бэктесте и в /filter терминала).
Пишет data/wave5_shadow/shadow_signals.csv (все разметки, колонка `egor` — оценка разметки: верно /
степень / четвёртая не там / удлинение / …), state.json, charts/<SYM>_<дата>.png с фибо-прогнозом.
Запуск: pm2 --name wave5-shadow · python scripts/wave5_shadow.py --loop --universe bingx --min_vol 2e6 --draw
Разово: --once · Самопроверка на истории: --asof 2026-01-14T04:00 --syms NEAR/USDT (LTF/4h из кэша проекта).
"""
from __future__ import annotations

import argparse, json, sys, time, warnings
from html import escape as html_escape
from pathlib import Path

import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import ccxt
from core.waves import mark_impulse, ltf_status, WaveParams
from core.waves.wave5_core import TF_MIN
from core.waves.wave5_chart import draw_setup
from core.waves.bingx_klines import fetch_closed

DATA = ROOT / "data" / "wave5_shadow"; DATA.mkdir(parents=True, exist_ok=True)
STATE, CSV, CH = DATA / "state.json", DATA / "shadow_signals.csv", DATA / "charts"
ENTRY_W_H, HOLD_H = 96, 240
P = WaveParams()
NOW = pd.Timestamp.utcnow()


def fetch(ex, sym, tf, n):
    """Закрытые бары BingX v3 (core.waves.bingx_klines — ccxt отдавал битые 4h мелких монет, 14.09). `ex` — для совместимости."""
    return fetch_closed(sym, tf, n, now=NOW)


def _cache(sym, tf):
    from research_harness import load
    d = load(sym, tf)
    return d[d.index + pd.Timedelta(minutes=TF_MIN[tf]) <= NOW]


# Синтетика BingX — не крипта, а акции (NCSK*), валютные пары (NCFX*), товары (NCCO*) и индексы (NCSI*).
# 16.09 их было 592 из 1180 пар, и они лезли в журнал (NCCOPALLADIUM2USD = палладий). Егор: «нужно убрать
# из скана синтетику». Коротких NC-тикеров в крипте нет — фильтр по префиксам ничего живого не задевает.
SYNTH_PREFIXES = ("NCSK", "NCFX", "NCCO", "NCSI")


def is_synthetic(base: str) -> bool:
    return base.upper().startswith(SYNTH_PREFIXES)


def universe_list(ex, a):
    mk = ex.load_markets()
    if a.syms:
        return a.syms.split(",")
    if a.universe == "bingx":
        tk = ex.fetch_tickers()
        liq = sorted(((s, m["base"], (tk.get(s) or {}).get("quoteVolume") or 0) for s, m in mk.items()
                      if m.get("swap") and m.get("quote") == "USDT" and m.get("active")
                      and not is_synthetic(m["base"])), key=lambda x: -x[2])
        return [f"{b}/USDT" for _, b, v in liq if v >= a.min_vol]
    from research_harness import universe
    have = {m["base"] for s, m in mk.items() if m.get("swap") and m.get("quote") == "USDT"}
    return [s for s in universe("4h", n=a.pairs) if s.split("/")[0] in have]


def js(v):
    if isinstance(v, (pd.Timestamp, np.datetime64)): return str(v)
    if isinstance(v, (np.floating, float)): return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (list, tuple)): return [js(x) for x in v]
    return v


EXEC_Q = DATA / "exec_queue.jsonl"


def choch_entry_15m(setup, dl, after, swing=True):
    """Вход по СЛОМУ структуры на 15m — лучший триггер по замеру 16.09 (Δ +2.51 против +1.87 у боевого
    кросса/линии, WR 49.5% против 33%). В ядре такого входа нет: `ltf_status` знает только кросс WT и
    пробой линии 2-4. Здесь — первый CHoCH нужного направления после детекции, стоп за экстремумом пятой,
    известным к бару входа (как в ядре). Возврат: (время, цена входа, стоп) или None."""
    from core.smc.oko_sm_engine import run_structure
    try:
        long_ = setup["side"] == "LONG"
        t5 = pd.Timestamp(setup["top_time"]); t5 = t5.tz_convert(None) if t5.tzinfo else t5
        at = pd.Timestamp(after); at = at.tz_convert(None) if at.tzinfo else at
        idx = dl.index.tz_convert(None) if getattr(dl.index, "tz", None) is not None else dl.index
        x = dl.reset_index(drop=True)
        st = run_structure(x[["open", "high", "low", "close"]], swing_len=P.sw, internal_len=P.il)
        j5 = int(np.searchsorted(idx.values, np.datetime64(t5)))
        ja = int(np.searchsorted(idx.values, np.datetime64(at)))
        jw = int(np.searchsorted(idx.values, np.datetime64(t5 + pd.Timedelta(hours=ENTRY_W_H))))
        ev = [e for e in st.events if e.kind == "CHoCH" and e.internal != swing
              and e.bull == long_ and max(ja, j5) <= e.i < jw]
        if not ev or ev[0].i + 1 >= len(x):
            return None
        j = ev[0].i + 1
        ext = float(x.low.values[j5:j].min()) if long_ else float(x.high.values[j5:j].max())
        p5a = min(float(setup["p5"]), ext) if long_ else max(float(setup["p5"]), ext)
        sl = p5a * (1 - P.buf) if long_ else p5a * (1 + P.buf)
        return pd.Timestamp(idx[j]), float(x.open.values[j]), sl
    except Exception:
        return None


def _already_sent(uid: str) -> bool:
    """Был ли такой сигнал уже выпущен. Дедуп держим в отдельном файле, а НЕ в state.json: по state
    ходят reentry_watch и выгрузка CSV, служебные ключи там ломали бы формат записей."""
    p = DATA / "exec_sent.json"
    try:
        sent = set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()
    except Exception:
        sent = set()
    if uid in sent:
        return True
    sent.add(uid)
    try:
        p.write_text(json.dumps(sorted(sent)[-8000:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return False


def emit_exec(prev, sym, variant, entry, stop, target, extra=None):
    """Сигнал на исполнение в VST (Егор 17.09: «на vst все в бой… все кандидаты с индивидуальной пометкой»).
    Тень — отдельный процесс, роутер живёт в боте, поэтому мост — очередь: строка JSON на сигнал.
    Читает её `bot/loops/waves_long_loop.py`, дедуп по полю `uid`. Вариант входа пишется в `wv_variant`,
    признаки отбора — рядом, чтобы результат потом резался по ним (ядро / импульс / ширина стопа / массовость)."""
    try:
        rec = {"ts": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
               "uid": f"{sym}|{prev.get('key')}|{variant}", "sym": sym, "side": prev.get("side"),
               "wv_variant": variant, "entry": js(entry), "stop": js(stop), "target": js(target),
               "wv_top_time": str(prev.get("top_time"))[:16], "wv_core_full": bool(prev.get("core_full")),
               "wv_core": bool(prev.get("core")), "wv_fractal": bool(prev.get("fractal")),
               "wv_imp_pct": js(prev.get("imp_pct")), "wv_depth5": js(prev.get("depth5")),
               "wv_risk_pct": round(abs(entry - stop) / entry * 100, 2) if entry and stop else None,
               "wv_mass_day": int(prev.get("_mass_day") or 0)}
        rec.update(extra or {})
        with open(EXEC_Q, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  EXEC {sym:<12} {variant} @ {entry:.6g} стоп {stop:.6g} → очередь VST", flush=True)
    except Exception as e_:  # noqa: BLE001
        print(f"  [exec] {sym}: не записал сигнал — {type(e_).__name__} {e_}", flush=True)


def transition(prev, ls, now, sym):
    """detected → entered → closed по правилам бэктеста (core.waves.wave5_core.ltf_status: триггер после детекции,
    вход open следующего бара, стоп фиксирован на входе, исход по экстремумам баров)."""
    st = prev.get("status", "detected")
    if st == "detected" and ls.get("entry_time") is not None:
        prev["status"] = "entered"; prev["entered_at"] = str(ls["entry_time"])[:16]; prev["entry_price"] = ls["entry_price"]
        prev["entry_trigger"] = ls["trigger"]; prev["stop"] = js(ls["stop"])
        print(f"  IN   {sym:<12} {prev['side']} вход по {ls['trigger']} {prev['entered_at']} @ {ls['entry_price']:.6g} · цель {prev['p4_target']:.6g} · стоп {ls['stop']:.6g}", flush=True)
        if prev.get("side") == "LONG":          # семейство waves_long: шорты в бой не идут (замер 16.09)
            emit_exec(prev, sym, ls["trigger"], ls["entry_price"], ls["stop"], prev.get("p4_target"))
    elif st == "detected" and ls.get("entry_window_over"):
        prev["status"] = "closed"; prev["closed_at"] = now; prev["outcome"] = "no_entry"
        print(f"  --   {sym:<12} окно входа истекло без триггера", flush=True)
    if prev.get("status") == "entered" and ls.get("outcome"):
        prev["status"] = "closed"; prev["closed_at"] = str(ls["exit_time"])[:16]; prev["outcome"] = ls["outcome"]
        prev["exit_price"] = js(ls["exit_price"]); prev["pnl_pct"] = ls["pnl_pct"]
        prev["outcome_trail"] = ls.get("outcome_trail"); prev["pnl_trail"] = ls.get("pnl_trail")
        print(f"  OUT  {sym:<12} {ls['outcome']} {ls['pnl_pct']:+.2f}%", flush=True)
    # 🔴 16.09 (Егор, REDSTONE): у ЗАКРЫТЫХ записей stop/p5_ext продолжали обновляться — в CSV стоп 17.5% при факте 6.3%
    # и убытке −6.43%. После закрытия запись замораживается: живыми остаются только наблюдения по активным сетапам.
    if prev.get("status") == "closed":
        prev["hours_from_top"] = round((NOW - pd.Timestamp(prev["top_time"], tz="UTC" if pd.Timestamp(prev["top_time"]).tzinfo is None else None)).total_seconds() / 3600, 1)
        return
    for k in ("cross_first", "line24_broken", "line24_first", "line24_now", "p5_ext", "last_close"):
        prev[k] = js(ls[k])
    if prev.get("status") != "entered":
        prev["stop"] = js(ls["stop"])
    prev["w5_reached"] = ",".join(ls["w5_reached"]); prev["corr_reached"] = ",".join(ls["corr_reached"])
    prev["hours_from_top"] = round((NOW - pd.Timestamp(prev["top_time"], tz="UTC" if pd.Timestamp(prev["top_time"]).tzinfo is None else None)).total_seconds() / 3600, 1)


def reentry_watch(state, now):
    """♻️ ПОСЛЕ ВЫБИТОГО СТОПА монета остаётся под наблюдением (Егор 16.09: «иначе теряем монету вместе с пробитым стопом»).
    Пятая удлинилась → ждём новый экстремум и первый слом 3m против хода (core.waves.wave5_core.reentry_status — тот же код,
    что в замере), окно 96 ч от вершины. Сделка БУМАЖНАЯ: поля re_* в журнале, пост в канал ответом на пост сетапа."""
    from core.waves.wave5_core import reentry_status
    from core.waves.wave_tg import tg_config, send_text
    post = tg_config().get("post_trades", True) and tg_config().get("enabled")
    for k, v in state.items():
        if v.get("outcome") != "stop" or v.get("re_status") == "closed":
            continue
        t5 = pd.Timestamp(v["top_time"], tz="UTC" if pd.Timestamp(v["top_time"]).tzinfo is None else None)
        if v.get("re_status") != "entered" and NOW > t5 + pd.Timedelta(hours=ENTRY_W_H):
            v["re_status"] = "closed"; v["re_outcome"] = "no_entry"; continue
        try:
            d3 = fetch_closed(v["sym"].split("/")[0], "3m", 3000)
            r = reentry_status(v, d3, v["closed_at"], P, entry_w_h=ENTRY_W_H, hold_h=HOLD_H)
        except Exception as e_:
            print(f"  [повтор] {v['sym']}: {type(e_).__name__} {e_}", flush=True); continue
        if r["entry_price"] is None:
            continue
        first = v.get("re_status") is None
        v.update(re_status="entered", re_entry=js(r["entry_price"]), re_stop=js(r["stop"]), re_entry_at=str(r["entry_time"])[:16])
        if first:
            print(f"  RE   {v['sym']:<12} {v['side']} повторный вход по слому 3m {v['re_entry_at']} @ {r['entry_price']:.6g} · стоп {r['stop']:.6g}", flush=True)
            if v.get("side") == "LONG":         # пятый вариант семейства waves_long — повторный вход по слому 3m
                emit_exec(v, v["sym"], "reentry_3m", r["entry_price"], r["stop"], v.get("p4_target"),
                          extra={"wv_mode": r.get("mode"), "wv_first_stop": js(v.get("stop"))})
            if post:
                rid = v["tg_last"] if isinstance(v.get("tg_last"), int) and v["tg_last"] > 0 else None
                txt = (f"♻️ <b>{html_escape(v['sym'].split('/')[0])}</b> · {v['side']} · ПОВТОРНЫЙ вход по слому 3m {v['re_entry_at']} UTC @ {r['entry_price']:.6g}\n"
                       f"цель {v['p4_target']:.6g} · стоп {r['stop']:.6g} (первый стоп был {v['stop']:.6g}) · бумажная сделка")
                mid = send_text(txt, reply_to=rid)
                if (mid.get("result") or {}).get("message_id"):
                    v["tg_last"] = mid["result"]["message_id"]
        if r["outcome"]:
            v.update(re_status="closed", re_outcome=r["outcome"], re_pnl_pct=r["pnl_pct"], re_closed_at=str(r["exit_time"])[:16])
            print(f"  RE-OUT {v['sym']:<10} {r['outcome']} {r['pnl_pct']:+.2f}%", flush=True)
            if post:
                icon = {"target": "✅", "stop": "⛔", "time": "⏱"}.get(r["outcome"], "•")
                rid = v["tg_last"] if isinstance(v.get("tg_last"), int) and v["tg_last"] > 0 else None
                send_text(f"{icon} <b>{html_escape(v['sym'].split('/')[0])}</b> · повторный вход закрыт: {r['outcome']} {r['pnl_pct']:+.2f}% (бумажная)", reply_to=rid)


def detect_close(prev):
    """Момент, с которого разрешён вход: закрытие 4h-бара детекции (детекция идёт через ~3 мин после закрытия)."""
    return pd.Timestamp(prev["detected_at"], tz="UTC").floor("4h")


def save_and_report(state, a, mode="watch", n_univ=None):
    if not a.asof:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        # статус для страницы /waves (Егор 16.09: «на странице нет новых сетапов» — чтобы «новых нет» читалось как факт)
        act = [v for v in state.values() if v.get("status") != "closed"]
        last_new = max((str(v.get("detected_at", "")) for v in state.values()), default="")
        prev = {}
        try:
            prev = json.loads((DATA / "status.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        st_ = {"at": NOW.strftime("%Y-%m-%d %H:%M"), "mode": mode, "journal": len(state), "active": len(act), "last_new": last_new,
               "universe": n_univ if n_univ is not None else prev.get("universe"),
               "last_full": NOW.strftime("%Y-%m-%d %H:%M") if mode == "full" else prev.get("last_full")}
        (DATA / "status.json").write_text(json.dumps(st_, ensure_ascii=False, indent=1), encoding="utf-8")
    try:                                              # оценки со страницы :8010/waves (reviews.json) → в записи
        rv = json.loads((DATA / "reviews.json").read_text(encoding="utf-8"))
        for k, s in state.items():
            r = rv.get(k) or {}
            s["egor"] = r.get("egor", s.get("egor", "")); s["egor_note"] = r.get("egor_note", "")
            s["ai"] = r.get("ai", ""); s["ai_note"] = r.get("ai_note", "")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[reviews] {e}", flush=True)
    df = pd.DataFrame(list(state.values()))
    if len(df):
        if "egor" not in df: df["egor"] = ""
        cols = ["status", "sym", "side", "top_time", "hours_from_top", "imp_pct", "fractal", "depth5", "altern_type", "altern_form", "count_ok",
                "d_bull", "d_broke", "d_wt", "core", "core_full", "w5_reached", "corr_reached", "line24_broken", "cross_first", "entry_trigger",
                "entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "outcome_trail", "pnl_trail", "re_status", "re_entry_at", "re_entry", "re_stop", "re_outcome", "re_pnl_pct", "cluster_3d", "cluster_norm", "mass_flush", "breadth10", "zone_1d", "depth_1d", "egor", "egor_note", "ai", "ai_note",
                "w5_618", "w5_eq1", "w5_1618", "w5_chan", "corr_382", "corr_500", "corr_618", "key"]
        df = df.reindex(columns=[c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols])
        if not a.asof:
            df.sort_values(["status", "top_time"], ascending=[True, False]).to_csv(CSV, index=False, encoding="utf-8-sig")
    act = df[df.status != "closed"] if len(df) else df
    print(f"\n[{NOW:%Y-%m-%d %H:%M} UTC] активных: {len(act)} (ядро полное {int(act.core_full.sum()) if len(act) else 0}, канал {int(act.core.sum()) if len(act) else 0}) · журнал {len(df)} · {CSV}", flush=True)
    if len(act):
        cols = [c for c in ("status", "sym", "side", "top_time", "hours_from_top", "imp_pct", "fractal", "depth5", "altern_type", "altern_form", "count_ok", "d_wt", "w5_reached", "corr_reached", "line24_broken", "cross_first", "core_full") if c in act]
        print(act[cols].to_string(index=False), flush=True)


def full_scan(a):
    global NOW
    NOW = pd.Timestamp(a.asof, tz="UTC") if a.asof else pd.Timestamp.utcnow(); now = NOW.strftime("%Y-%m-%d %H:%M")
    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    syms = universe_list(ex, a)
    state = {} if a.asof else (json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    print(f"[{now} UTC] полная разметка: {len(syms)} монет · LTF {a.ltf}", flush=True)
    n_ltf = int(ENTRY_W_H * 60 / TF_MIN[a.ltf]) * 4
    R72 = []
    for i, s in enumerate(syms, 1):
        bx = f"{s.split('/')[0]}/USDT:USDT"
        try:
            dh = fetch(ex, bx, "4h", 1000)
            if len(dh) > 20:
                R72.append(float(dh.close.iloc[-1] / dh.close.iloc[-19] - 1))      # ход за 72 ч — для ширины слива
            if len(dh) < 400 and a.asof: dh = _cache(s, "4h").tail(1000)
            setups = mark_impulse(dh, NOW, P, "4h") if len(dh) >= 400 else []
            if not setups:
                if len(dh) < 400: print(f"  [skip] {s}: 4h={len(dh)}", flush=True)
                continue
            dl = fetch(ex, bx, a.ltf, n_ltf)
            if len(dl) < 200: dl = _cache(s, a.ltf).tail(n_ltf)
            if len(dl) < 200: print(f"  [skip] {s}: {a.ltf}={len(dl)}", flush=True); continue
            for st in setups:
                if a.only_core and not st["core"]: continue
                k = f"{s}|{st['key']}"; prev = state.get(k)
                # 16.09 (Егор: «тут ничего нового!»): ключ ядра = начало импульса + конец волны 4, БЕЗ вершины пятой.
                # Пятая продлевается → вершина/стоп/цель новые, ключ прежний. Если по нему лежит ЗАКРЫТАЯ запись,
                # обновлять её нельзя (заморозка 15.09), и сетап пропадал молча: так 16.09 потерялись 6 сигналов.
                # Новая вершина при закрытой записи = отдельный сетап.
                if prev is not None and prev.get("status") == "closed" and str(prev.get("top_time")) != str(st["top_time"]):
                    k = f"{k}|{pd.Timestamp(st['top_time']):%Y%m%d%H}"; prev = state.get(k)
                _after = detect_close(prev) if prev else NOW.floor('4h')
                ls = ltf_status(st, dl, P, after=_after, entry_w_h=ENTRY_W_H, hold_h=HOLD_H)
                # 17.09 (Егор: «вариант входа по слому swing 15m тоже добавить в тень и VST»):
                # отдельный кандидат семейства — не заменяет боевой вход, идёт параллельно со своей пометкой.
                if st["side"] == "LONG":
                    for _sw, _nm in ((True, "choch_swing_15m"), (False, "choch_int_15m")):
                        _ch = choch_entry_15m(st, dl, _after, swing=_sw)
                        if _ch and not _already_sent(f"{s}|{st['key']}|{_nm}"):
                            emit_exec(st, s, _nm, _ch[1], _ch[2], st.get("p4_target"),
                                      extra={"wv_choch_time": str(_ch[0])[:16]})
                if prev is None:
                    prev = {kk: js(v) for kk, v in st.items() if kk not in ("wave_idx", "wave_px")}
                    prev.update({"sym": s, "detected_at": now, "status": "detected", "egor": ""})
                    state[k] = prev; transition(prev, ls, now, s)
                    print(f"  NEW  {s:<12} {st['side']} вершина {pd.Timestamp(st['top_time']):%m-%d %H:%M} ({st['hours_from_top']:.0f} ч) импульс {st['imp_pct']}% фрактал {st['fractal']} канал {st['depth5']} черед {int(st['altern_type'])}/{int(st['altern_form'])} счёт {st['count_ok']} 1D {st['d_bull']}/{st['d_broke']} WT1D {st['d_wt']} | линия {'ПРОБИТА' if ls['line24_broken'] else 'нет'} кросс {str(ls['cross_first'])[:16] if ls['cross_first'] else 'нет'} · {'ЯДРО' if st['core_full'] else ('канал' if st['core'] else '')}", flush=True)
                    if a.draw:
                        try: draw_setup({**st, "sym": s}, dh, ls, CH / f"{s.replace('/', '')}_{pd.Timestamp(st['top_time']):%Y%m%d}.png")
                        except Exception as e_: print(f"   (картинка: {e_})", flush=True)
                else:
                    for kk in ("depth5", "d_wt", "hours_from_top"): prev[kk] = js(st[kk])
                    transition(prev, ls, now, s)
        except Exception as e_:
            print(f"  [skip] {s}: {type(e_).__name__} {e_}", flush=True)
        if i % 50 == 0: print(f"  {i}/{len(syms)}", flush=True)
    if not a.asof:
        mark_market(state, now, R72, len(syms))
        reentry_watch(state, now)
        tg_notify(state, refresh_analyst(state))
    save_and_report(state, a, mode="full", n_univ=len(syms))


def write_ai_review(key, prev):
    """🧪 Строка «ИИ» на /waves: вердикт правил методички (core.waves.wave_audit) → reviews.json. Оценку Егора не трогаем."""
    from core.waves.wave_audit import audit_setup
    try:
        aj = None
        if prev.get("analyst_json"):
            pj = ROOT / "data" / "wave_analyst" / prev["analyst_json"]
            if pj.exists():
                aj = json.loads(pj.read_text(encoding="utf-8"))
        res = audit_setup(prev, aj)
        rp = DATA / "reviews.json"
        rv = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        rec = rv.setdefault(key, {})
        rec.update({"ai": res["ai"], "ai_note": res["ai_note"], "ai_ts": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M")})
        rp.write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
        prev["ai"], prev["ai_note"] = res["ai"], res["ai_note"]
    except Exception as e_:
        print(f"  [ИИ-сверка] {prev.get('sym')}: {type(e_).__name__} {e_}", flush=True)


def mark_market(state, now, r72, n_univ):
    """Рыночный момент для сетапов этого скана (замер 14.09, memory wave_3m_program):
    · breadth10/20 — доля монет вселенной с ходом за 72 ч < −10% / −20% (высокая 10-78% — лучше, экстремальная >78% — хуже);
    · cluster_3d — сколько РАЗНЫХ монет дали пятёрку той же стороны за ПРОШЛЫЕ 3 дня (без текущего дня);
      cluster_norm — приведено к вселенной замера (145 монет); mass_flush — cluster_norm ≥ 7 (Δ +1.8 п.п., но 20 дней в замере)."""
    arr = np.array(r72, float) if r72 else np.array([])
    b10 = round(float((arr < -0.10).mean()), 3) if arr.size else None
    b20 = round(float((arr < -0.20).mean()), 3) if arr.size else None
    for k, v in state.items():
        if v.get("detected_at") == now and v.get("breadth10") is None:
            v["breadth10"], v["breadth20"], v["universe_n"] = b10, b20, n_univ
    for k, v in state.items():
        if v.get("cluster_3d") is not None:
            continue
        d0 = pd.Timestamp(v["detected_at"], tz="UTC").floor("1D")
        others = {x["sym"] for x in state.values() if x["sym"] != v["sym"] and x.get("side") == v.get("side")
                  and d0 - pd.Timedelta(days=3) <= pd.Timestamp(x["detected_at"], tz="UTC") < d0}
        v["cluster_3d"] = len(others)
        un = v.get("universe_n") or n_univ
        v["cluster_norm"] = round(len(others) * 145 / max(un, 1), 1)
        v["mass_flush"] = bool(v["cluster_norm"] >= 7)


def refresh_analyst(state):
    """🌊 Волновой разбор (core.waves.wave_analyst) для каждого активного сетапа раз в 4h: схема для /waves,
    зона пятой в дневной ноге (OTE/глубокая/за пределами) — главный признак по замеру 14.09."""
    from core.waves.wave_analyst import report_for
    reports = {}
    for k, prev in state.items():
        if prev.get("status") == "closed":
            continue
        try:
            r = report_for(prev["sym"], "3m", ROOT / "data" / "wave_analyst", now=NOW, parts=True)
            prev.update({"analyst_png": r["png"], "analyst_json": r["json"], "zone_1d": r["zone"], "depth_1d": r["depth"]})
            reports[k] = r
            print(f"  разбор {prev['sym']}: {r['zone']} ({r['depth']}) → {r['png']}", flush=True)
            write_ai_review(k, prev)
        except Exception as e_:
            print(f"  [разбор] {prev['sym']}: {type(e_).__name__} {e_}", flush=True)
    return reports


def tg_notify(state, reports=None):
    """📤 Канал Oko_Waves (core.waves.wave_tg, настройки data/wave5_shadow/tg.json). Всё по сетапу — ЦЕПОЧКОЙ ответов
    (Егор 15.09: «обновление — ответным сообщением на предыдущую версию, так динамику видно»):
    новый сетап — схема (ответом на последний пост этой монеты, если был) → обновление разбора, когда изменился его
    отпечаток (state_diff: счёт, зона, слом, волна A, касание зоны, треугольник) → вход → выход. `tg_last` — id последнего
    сообщения цепочки, `tg_sig` — отпечаток последней опубликованной версии. Только то, что появилось после `since`."""
    from core.waves.wave_tg import tg_config, publish_report, send_text, state_diff, message_id
    cfg = tg_config()
    if not cfg.get("enabled"):
        return
    since = cfg.get("since", ""); out_dir = ROOT / "data" / "wave_analyst"

    def chain(v, res):
        mid = message_id(res)
        if mid:
            v["tg_last"] = mid
        return bool(mid)
    for k, v in state.items():
        try:
            name = html_escape(v["sym"].split("/")[0]); r = (reports or {}).get(k)
            if cfg.get("post_new", True) and str(v.get("detected_at", "")) >= since and not v.get("tg_new") and r:
                prev_sym = [x.get("tg_last") for x in state.values() if x is not v and x.get("sym") == v["sym"] and x.get("tg_last")]
                extra = f"Сетап тени: пятая {'вниз' if v['side'] == 'LONG' else 'вверх'} на 4h, импульс {v.get('imp_pct')}%, цель — конец 4-й {v['p4_target']:.6g}"
                res = publish_report(r, out_dir, side=v["side"], extra=html_escape(extra), reply_to=max(prev_sym) if prev_sym else None)
                v["tg_new"] = message_id(res) or -1; chain(v, res); v["tg_sig"] = r.get("state")
                print(f"  TG   {v['sym']}: сетап {'ок' if res.get('ok') else res}", flush=True)
            elif r and v.get("tg_last") and v.get("status") != "closed":
                changes = state_diff(v.get("tg_sig"), r.get("state"), r.get("price") or 0)
                if changes:
                    res = publish_report(r, out_dir, side=v["side"], note="; ".join(changes), reply_to=v["tg_last"])
                    if chain(v, res):
                        v["tg_sig"] = r.get("state")
                    print(f"  TG   {v['sym']}: обновление ({'; '.join(changes)}) {'ок' if res.get('ok') else res}", flush=True)
            if not v.get("tg_last"):                  # без поста сетапа вход/выход не публикуем — цепочке не к чему крепиться
                continue
            if cfg.get("post_trades", True) and v.get("entered_at") and str(v["entered_at"]) >= since and not v.get("tg_in"):
                txt = "\n".join([f"▶️ <b>{name}</b> · {v['side']} · вход по {v.get('entry_trigger')} {v['entered_at']} UTC @ {v['entry_price']:.6g}",
                                 f"цель {v['p4_target']:.6g} · стоп {v['stop']:.6g}"])
                v["tg_in"] = chain(v, send_text(txt, reply_to=v.get("tg_last")))
            if (cfg.get("post_trades", True) and v.get("status") == "closed" and v.get("pnl_pct") is not None
                    and str(v.get("closed_at", "")) >= since and not v.get("tg_out")):
                icon = {"target": "✅", "stop": "⛔", "time": "⏱"}.get(v.get("outcome"), "•")
                lines = [f"{icon} <b>{name}</b> · {v['side']} · выход {v.get('outcome')} {v['closed_at']} UTC · {v['pnl_pct']:+.2f}%"]
                if v.get("pnl_trail") is not None:
                    lines.append(f"с трейлом: {v.get('outcome_trail')} {v['pnl_trail']:+.2f}%")
                v["tg_out"] = chain(v, send_text("\n".join(lines), reply_to=v.get("tg_last")))
        except Exception as e_:
            print(f"  [TG] {v.get('sym')}: {type(e_).__name__} {e_}", flush=True)


def watch(a):
    global NOW
    NOW = pd.Timestamp.utcnow(); now = NOW.strftime("%Y-%m-%d %H:%M")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    act = {k: v for k, v in state.items() if v.get("status") != "closed"}
    if not act:
        print(f"[{now} UTC] watch: активных нет", flush=True); return
    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print(f"[{now} UTC] watch: {len(act)} активных", flush=True)
    n_ltf = int(ENTRY_W_H * 60 / TF_MIN[a.ltf]) * 2
    for k, prev in act.items():
        s = prev["sym"]; bx = f"{s.split('/')[0]}/USDT:USDT"
        try:
            n_need = min(3000, int((NOW - pd.Timestamp(prev["top_time"], tz="UTC" if pd.Timestamp(prev["top_time"]).tzinfo is None else None)) / pd.Timedelta(minutes=TF_MIN[a.ltf])) + 100)
            dl = fetch(ex, bx, a.ltf, max(n_ltf, n_need))                 # история от вершины пятой: нужна для входа и исхода
            if len(dl) < 100: print(f"  [skip] {s}: {a.ltf}={len(dl)}", flush=True); continue
            ls = ltf_status(prev, dl, P, after=detect_close(prev), entry_w_h=ENTRY_W_H, hold_h=HOLD_H); transition(prev, ls, now, s)
        except Exception as e_:
            print(f"  [skip] {s}: {type(e_).__name__} {e_}", flush=True)
    reentry_watch(state, now)
    tg_notify(state)
    save_and_report(state, a)


def run_loop(a):
    last_full = None
    while True:
        now = pd.Timestamp.utcnow(); bar_close = now.floor("4h")
        due = (now - bar_close) >= pd.Timedelta(minutes=3) and (last_full is None or last_full < bar_close)
        try:
            if due: full_scan(a); last_full = bar_close
            else: watch(a)
        except Exception as e_:
            print(f"[loop] ошибка: {type(e_).__name__} {e_}", flush=True)
        nxt = pd.Timestamp.utcnow().floor("15min") + pd.Timedelta(minutes=15, seconds=20)
        time.sleep(max(30, (nxt - pd.Timestamp.utcnow()).total_seconds()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ltf", default="15m"); ap.add_argument("--pairs", type=int, default=150); ap.add_argument("--draw", action="store_true")
    ap.add_argument("--only-core", action="store_true"); ap.add_argument("--asof", default=None); ap.add_argument("--syms", default=None)
    ap.add_argument("--universe", default="cache", choices=["cache", "bingx"]); ap.add_argument("--min_vol", type=float, default=2e6)
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    if a.loop: run_loop(a)
    elif a.watch: watch(a)
    else: full_scan(a)


if __name__ == "__main__":
    main()
