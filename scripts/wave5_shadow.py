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


def universe_list(ex, a):
    mk = ex.load_markets()
    if a.syms:
        return a.syms.split(",")
    if a.universe == "bingx":
        tk = ex.fetch_tickers()
        liq = sorted(((s, m["base"], (tk.get(s) or {}).get("quoteVolume") or 0) for s, m in mk.items()
                      if m.get("swap") and m.get("quote") == "USDT" and m.get("active")), key=lambda x: -x[2])
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


def transition(prev, ls, now, sym):
    """detected → entered → closed по правилам бэктеста (core.waves.wave5_core.ltf_status: триггер после детекции,
    вход open следующего бара, стоп фиксирован на входе, исход по экстремумам баров)."""
    st = prev.get("status", "detected")
    if st == "detected" and ls.get("entry_time") is not None:
        prev["status"] = "entered"; prev["entered_at"] = str(ls["entry_time"])[:16]; prev["entry_price"] = ls["entry_price"]
        prev["entry_trigger"] = ls["trigger"]; prev["stop"] = js(ls["stop"])
        print(f"  IN   {sym:<12} {prev['side']} вход по {ls['trigger']} {prev['entered_at']} @ {ls['entry_price']:.6g} · цель {prev['p4_target']:.6g} · стоп {ls['stop']:.6g}", flush=True)
    elif st == "detected" and ls.get("entry_window_over"):
        prev["status"] = "closed"; prev["closed_at"] = now; prev["outcome"] = "no_entry"
        print(f"  --   {sym:<12} окно входа истекло без триггера", flush=True)
    if prev.get("status") == "entered" and ls.get("outcome"):
        prev["status"] = "closed"; prev["closed_at"] = str(ls["exit_time"])[:16]; prev["outcome"] = ls["outcome"]
        prev["exit_price"] = js(ls["exit_price"]); prev["pnl_pct"] = ls["pnl_pct"]
        prev["outcome_trail"] = ls.get("outcome_trail"); prev["pnl_trail"] = ls.get("pnl_trail")
        print(f"  OUT  {sym:<12} {ls['outcome']} {ls['pnl_pct']:+.2f}%", flush=True)
    for k in ("cross_first", "line24_broken", "line24_first", "line24_now", "p5_ext", "last_close"):
        prev[k] = js(ls[k])
    if prev.get("status") != "entered":
        prev["stop"] = js(ls["stop"])
    prev["w5_reached"] = ",".join(ls["w5_reached"]); prev["corr_reached"] = ",".join(ls["corr_reached"])
    prev["hours_from_top"] = round((NOW - pd.Timestamp(prev["top_time"], tz="UTC" if pd.Timestamp(prev["top_time"]).tzinfo is None else None)).total_seconds() / 3600, 1)


def detect_close(prev):
    """Момент, с которого разрешён вход: закрытие 4h-бара детекции (детекция идёт через ~3 мин после закрытия)."""
    return pd.Timestamp(prev["detected_at"], tz="UTC").floor("4h")


def save_and_report(state, a):
    if not a.asof:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
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
                "entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "outcome_trail", "pnl_trail", "cluster_3d", "cluster_norm", "mass_flush", "breadth10", "zone_1d", "depth_1d", "egor", "egor_note", "ai", "ai_note",
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
                k = f"{s}|{st['key']}"; prev = state.get(k); ls = ltf_status(st, dl, P, after=(detect_close(prev) if prev else NOW.floor('4h')), entry_w_h=ENTRY_W_H, hold_h=HOLD_H)
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
        tg_notify(state, refresh_analyst(state))
    save_and_report(state, a)


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
            r = report_for(prev["sym"], "3m", ROOT / "data" / "wave_analyst", now=NOW)
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
