"""
BUS-CATALOG — единое «меню» данных шины (PairContextBus).

Идея (юзер 16.06, «меню в ресторане»): одно место, где прописано ВСЁ что течёт
в шине — что есть, тип, кто кладёт, КАК подключить. Пришёл → выбрал «провод»
(подписка/чтение) → не шаришься по всему коду.

Самодокументируемый: поля берутся из dataclass `PairState`/`AccountState` и
`SphereEvent` АВТОМАТОМ (не дрейфнут при добавлении поля), метаданные
(источник/описание) задаются явно ниже. `validate()` ловит поля без метаданных.

Использование:
    from core.context.bus_catalog import catalog, to_markdown, validate
    cat = catalog()                # программно (dict) — для кода
    print(to_markdown())           # меню (markdown) — для человека/разработки
    missing = validate()           # поля без метаданных (дополнить)

Точка входа также из шины: bus.catalog() / bus.catalog_markdown().
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

from core.context.pair_context import PairState, AccountState, SphereEvent


# ── Метаданные L1 PairState: поле → (источник, описание) ──────────────────────
# Доступ выводится автоматом: bus.get(sym).<поле>
_PAIR_META: Dict[str, tuple] = {
    # Сфера 1 DataCollector
    "last_ohlcv_time":   ("scan_loop (Сфера 1)", "когда обновлялись свечи"),
    "ohlcv_tfs_loaded":  ("scan_loop (Сфера 1)", "какие TF загружены"),
    # Сфера 2 WSFeed / scan_loop
    "tick_price":        ("WsFeed / scan_loop (OHLCV close)", "текущая цена пары"),
    "tick_time":         ("WsFeed / scan_loop", "время последнего тика"),
    # Сфера 3 WT
    "wt_verdict":        ("scan_loop (Сфера 3)", "TREND_CONTINUATION/REVERSAL_SETUP/EXHAUSTION"),
    "wt_confidence":     ("scan_loop (Сфера 3)", "уверенность WT-вердикта 0..1"),
    "wt_snap":           ("scan_loop (Сфера 3)", "{tf: {wt1,wt2,zone,cross,atr_trend}}"),
    # Сфера 4 SMC
    "smc_verdict":       ("sub_cube (Сфера 4)", "STRONG_BULL_ZONE/WEAK_ZONE/STRONG_BEAR_ZONE"),
    "smc_confidence":    ("sub_cube (Сфера 4)", "уверенность SMC 0..1"),
    # 🔴 02.09: описание врало — схема ПЛОСКАЯ, per-TF лежит ВНУТРИ ключа by_tf.
    # Читатели (narrative_builder) обращаются плоско: snap["price_in_ote"].
    # Не путать с ctx.smc_snap у ML-сферы 4 — там {tf: {...}}, ДРУГАЯ схема.
    "smc_snap":          ("sub_cube (Сфера 4)", "плоский: price_in_ote,last_bos,nearest_*_ob,eqh/eql + by_tf{tf:..}"),
    # Сфера 5 Cross-Market
    "btc_regime":        ("scan_loop (Сфера 5)", "режим BTC TREND_UP/DOWN/RANGE/HIGH_VOL"),
    "btc_move_pct":      ("scan_loop (Сфера 5)", "движение BTC %"),
    "cross_market_time": ("scan_loop (Сфера 5)", "время cross-market снимка"),
    # Сфера 6 Regime
    "regime":            ("scan_loop (Сфера 6)", "режим пары TREND_UP/DOWN/RANGE/HIGH_VOL"),
    "reversal_mode":     ("scan_loop (Сфера 6)", "TREND/REVERSAL/UNCLEAR"),
    "sideways_bars":     ("scan_loop (Сфера 6)", "счётчик RANGE-циклов подряд"),
    "sideways_mode_active": ("scan_loop (Сфера 6)", "sideways_bars >= порог"),
    # Сфера 7 Signal Detectors
    "last_signal_type":      ("scan_loop (Сфера 7)", "тип последнего сигнала"),
    "last_signal_direction": ("scan_loop (Сфера 7)", "LONG/SHORT"),
    "last_signal_strength":  ("scan_loop (Сфера 7)", "сила сигнала"),
    "last_signal_time":      ("scan_loop (Сфера 7)", "время сигнала"),
    "active_divergence":     ("scan_loop (Сфера 7)", "активная дивергенция {type,direction,tf,strength}"),
    "anomaly_active":        ("scan_loop (Сфера 7)", "аномалия объёма активна"),
    # OTE LTF (ote_observer)
    "ote_ltf_status":    ("ote_observer", "ARMED/FIRE/None — статус 5m OTE-сетапа"),
    "ote_ltf_score":     ("ote_observer", "набрано подтверждений"),
    "ote_ltf_min":       ("ote_observer", "порог подтверждений для FIRE"),
    "ote_ltf_direction": ("ote_observer", "long/short"),
    "ote_ltf_trigger":   ("ote_observer", "FVG/OB/EQL/SC"),
    "ote_ltf_entry":     ("ote_observer", "цена входа"),
    "ote_ltf_sl":        ("ote_observer", "стоп-лосс"),
    "ote_ltf_tp1":       ("ote_observer", "частичный +1R"),
    "ote_ltf_tp":        ("ote_observer", "финальная цель (runner)"),
    "ote_ltf_setup":     ("ote_observer", "setup_id из шкафа"),
    "ote_ltf_time":      ("ote_observer", "время OTE-снимка"),
    # Сфера 8 Pivot
    "pivot_snap":        ("scan_loop (Сфера 8)", "{1W:{PP,S1,R1,..},1D:{..}}"),
    "near_pivot":        ("scan_loop (Сфера 8)", "{level,source,distance_pct}"),
    # Сфера 9 Narrative
    "last_narrative":      ("trading_intelligence (Сфера 9)", "текст нарратива"),
    "last_narrative_time": ("trading_intelligence (Сфера 9)", "время нарратива"),
    "last_p_win":          ("trading_intelligence (Сфера 9)", "P(win) ML 0..1"),
    # Сфера 10 Exit Manager
    "open_trade_id":     ("trade_simulator (Сфера 10)", "id открытой сделки"),
    "tsl_active":        ("trade_simulator (Сфера 10)", "TSL активен"),
    "tp1_hit":           ("trade_simulator (Сфера 10)", "TP1 достигнут"),
    # Сфера 11 Post-Trade
    "cascade_count":     ("trade_simulator (Сфера 11)", "длина каскада"),
    "last_direction":    ("trade_simulator (Сфера 11)", "направление последней сделки"),
    "last_close_status": ("trade_simulator (Сфера 11)", "TP/SL/TSL/EXPIRED"),
    "last_close_time":   ("trade_simulator (Сфера 11)", "время закрытия"),
    "avg_r_cascade":     ("trade_simulator (Сфера 11)", "средний R каскада"),
    "post_tsl_data":     ("trade_simulator (Сфера 11)", "данные post-TSL"),
    # ARCH-88 Loss Memory
    "sl_streak_count":     ("gates (ARCH-88)", "серия SL подряд"),
    "last_n_outcomes":     ("gates (ARCH-88)", "последние 10 исходов (deque)"),
    "pair_avg_r_last_20":  ("gates (ARCH-88)", "avg R последних 20 сделок пары"),
    "last_sl_at":          ("gates (ARCH-88)", "время последнего SL"),
    "pair_cooldown_until": ("gates (ARCH-88)", "пара заблокирована до"),
    "last_narrative_outcome": ("trade_simulator (ARCH-91)", "{status,R,lost_reason,closed_at}"),
    # Сфера 12 Self-Diagnostics
    "spheres_ok":          ("sphere_registry (Сфера 12)", "сколько сфер живы за час"),
    "last_diagnostic_time": ("sphere_registry (Сфера 12)", "время диагностики"),
    # WATCHLIST-UNI — единственное поле, которое validate() ловил без метаданных (27.08)
    "watchlist":           ("bus.set_watchlist() из любой стратегии",
                            "{стратегия: {entry, potential_pct, ...}} — заявки стратегий на пару"),
}

# ── 🔴 ЧЕГО В ШИНЕ НЕТ (сверка 27.08.2026) ────────────────────────────────────
# Проверено: шина видит OHLCV и производные от них. Мимо шины идут ВСЕ остальные
# источники, хотя данные у бота есть и решения на них принимаются:
#
#   источник                       строк в кэше   почему важно
#   funding_rates                  1 557 170      полная история 2022-2026, в замерах не используется
#   mcap_supply / mcap_meta           15 948      капитализация и supply
#   onchain_events                    10 029      киты, переводы
#   usdtd / usdtd_1h / usdtd_cg        2 617      доминация USDT
#   открытый интерес (OI)              live       берётся с Bybit мимо шины (radar_oi_d5/d15)
#   магниты, фазы, дрейф вселенной      —         считаются в стратегиях, в шину не публикуются
#
# Следствие: 213 из 230 признаков боевых решений живут вне шины. Сферы их не видят,
# feedback loop по ним невозможен, каждая стратегия тянет данные сама (дублирование).
# Реестр и план: docs/REGISTRY.md · TASKS.md → «ПЛАН ПЕРЕПРОВЕРКИ».

# ── Метаданные L2 AccountState: поле → (источник, описание) ───────────────────
# Доступ: bus.get_account(id).<поле> · positions → bus.all_positions()
_ACCOUNT_META: Dict[str, tuple] = {
    "account_id":  ("—", "id аккаунта (1/2)"),
    "equity":      ("EXEC-WS ACCOUNT_UPDATE (wb)", "баланс счёта (живой push). total → bus.total_equity()"),
    "available":   ("position_sync / REST", "доступная маржа"),
    "used_margin": ("position_sync / REST", "занятая маржа"),
    "positions":   ("EXEC-WS + position_sync", "{sym: {qty,side,entry,upnl,leverage,mark}} → bus.all_positions()"),
    "updated_at":  ("EXEC-WS / position_sync", "время обновления счёта"),
}

# ── Метаданные событий: ИМЯ → (источник, payload, описание) ───────────────────
# Доступ: bus.subscribe_async(SphereEvent.<ИМЯ>, handler)
_EVENT_META: Dict[str, tuple] = {
    "OHLCV_UPDATED":      ("scan_loop (Сфера 1)", "{tf,rows,close,volume_24h}",
                           "обновление свечей + текущая цена + оборот за сутки (из тех же свечей)"),
    "TICK_PRICE":         ("WsFeed (Сфера 2)", "{price,volume_24h}", "тик цены (если WsFeed on)"),
    "VOLUME_SPIKE":       ("scan_loop (Сфера 2)", "{ratio,tf}", "всплеск объёма"),
    "WT_VERDICT":         ("scan_loop (Сфера 3)", "{label,confidence,features}", "вердикт WT"),
    "WT_SNAP_UPDATED":    ("scan_loop (Сфера 3)", "{tf:{wt1,wt2,zone,cross,atr_trend}}", "снимок WT"),
    "SMC_VERDICT":        ("sub_cube (Сфера 4)", "{label,confidence}", "вердикт SMC"),
    "SMC_SNAP_UPDATED":   ("sub_cube (Сфера 4)", "плоский + by_tf{tf:..}", "снимок SMC (магниты TP, NOTIF)"),
    "CROSS_MARKET":       ("scan_loop (Сфера 5)", "{btc_regime,btc_move_pct,direction}", "контекст BTC"),
    "REGIME_UPDATED":     ("scan_loop (Сфера 6)", "{regime,mode}", "режим рынка"),
    "SIGNAL_DETECTED":    ("scan_loop (Сфера 7)", "{signal_type,direction,strength,tf}", "сигнал детектора"),
    "ANOMALY_DETECTED":   ("scan_loop (Сфера 7)", "{volume_ratio,tf}", "аномалия"),
    "DIVERGENCE_FOUND":   ("scan_loop (Сфера 7)", "{type,direction,tf,strength}", "дивергенция"),
    "PIVOT_TOUCH":        ("scan_loop (Сфера 7)", "{level,source,distance_pct}", "касание пивота"),
    "RECOMMENDATION_BUILT": ("trading_intelligence (Сфера 7)", "{recommendation,wt_verdict,smc_verdict,reversal_mode,...}",
                             "рекомендация собрана → Сфера 9 (синхронно) пишет нарратив в metadata"),
    "PIVOT_SNAP_UPDATED": ("scan_loop (Сфера 8)", "{1W:{..},1D:{..}}", "снимок пивотов"),
    "NARRATIVE_BUILT":    ("trading_intelligence (Сфера 9)", "{text,action,p_win,key_factors}", "нарратив решения"),
    "POSITION_OPENED":    ("trade_router (Сфера 9)", "{side,source,trade_id,final_strength,regime}", "сделка открыта"),
    "POSITION_DROPPED":   ("trade_router (Сфера 9)", "{side,source,hard_drops,strength,regime}", "сделка отклонена гейтом"),
    "TSL_MOVED":          ("trade_simulator (Сфера 10)", "{trade_id,old_sl,new_sl,tf}", "TSL сдвинут"),
    "TP1_HIT":            ("trade_simulator (Сфера 10)", "{trade_id,r_at_tp1}", "TP1 достигнут"),
    "POSITION_CLOSED":    ("trade_simulator (Сфера 10)", "{trade_id,status,r_multiple}", "позиция закрыта"),
    "TRADE_CLOSED":       ("trade_simulator (Сфера 11)", "{status,r_multiple,direction,signal_type}", "сделка закрыта (учёт)"),
    "CASCADE_UPDATED":    ("trade_simulator (Сфера 11)", "{cascade_count,avg_r,direction}", "обновление каскада"),
    "OTE_ZONE_SET":       ("ote_observer (Сфера 11)", "{ote_top,ote_bot,direction,ttl_hours}", "OTE-зона установлена"),
    "SPHERE_HEALTH":      ("sphere_registry (Сфера 12)", "{sphere_id,status,last_update}", "здоровье сферы"),
}


def _typename(t: Any) -> str:
    """Имя типа поля dataclass (t может быть строкой из __future__ annotations)."""
    s = str(t)
    return s.replace("typing.", "").replace("<class '", "").replace("'>", "")


def catalog() -> Dict[str, List[dict]]:
    """Программный каталог шины: события + L1 PairState + L2 AccountState.

    Каждая запись: name · type · source · access · desc. Поля — из dataclass (автоматом).
    """
    events = []
    for name, (src, payload, desc) in _EVENT_META.items():
        events.append({
            "name": name, "payload": payload, "source": src,
            "access": f"bus.subscribe_async(SphereEvent.{name}, handler)", "desc": desc,
        })

    pair = []
    for f in dataclasses.fields(PairState):
        if f.name == "symbol":
            continue
        src, desc = _PAIR_META.get(f.name, ("?", ""))
        pair.append({
            "name": f.name, "type": _typename(f.type), "source": src,
            "access": f"bus.get(sym).{f.name}", "desc": desc,
        })

    acct = []
    for f in dataclasses.fields(AccountState):
        src, desc = _ACCOUNT_META.get(f.name, ("?", ""))
        acc_field = "bus.all_positions()" if f.name == "positions" else f"bus.get_account(id).{f.name}"
        acct.append({
            "name": f.name, "type": _typename(f.type), "source": src,
            "access": acc_field, "desc": desc,
        })

    return {"events": events, "pair_state_L1": pair, "account_state_L2": acct}


def validate() -> List[str]:
    """Поля dataclass без метаданных (каталог отстал от кода). Пусто = в синхроне."""
    miss = []
    for f in dataclasses.fields(PairState):
        if f.name != "symbol" and f.name not in _PAIR_META:
            miss.append(f"PairState.{f.name}")
    for f in dataclasses.fields(AccountState):
        if f.name not in _ACCOUNT_META:
            miss.append(f"AccountState.{f.name}")
    for name in dir(SphereEvent):
        if name.isupper() and name not in _EVENT_META:
            miss.append(f"SphereEvent.{name}")
    return miss


def to_markdown() -> str:
    """Меню шины (markdown) — для человека/разработки."""
    cat = catalog()
    out = ["# 📖 BUS-CATALOG — меню данных шины (PairContextBus)",
           "",
           "> Авто-генерация из `core/context/bus_catalog.py`. Поля — из dataclass (не дрейфнут).",
           "> Пришёл → выбрал «провод» (подписка/чтение) → подключился. Не ищи по коду.",
           "",
           "## 🔔 СОБЫТИЯ (PUSH — реакция). `bus.subscribe_async(SphereEvent.X, handler)`",
           "",
           "| Событие | Payload | Источник | Описание |",
           "|---|---|---|---|"]
    for e in cat["events"]:
        out.append(f"| `{e['name']}` | `{e['payload']}` | {e['source']} | {e['desc']} |")

    out += ["",
            "## 🅛1 PAIR STATE (PULL — состояние пары). `bus.get(sym).<поле>`",
            "",
            "| Поле | Тип | Источник | Описание |",
            "|---|---|---|---|"]
    for p in cat["pair_state_L1"]:
        out.append(f"| `{p['name']}` | {p['type']} | {p['source']} | {p['desc']} |")

    out += ["",
            "## 🅛2 ACCOUNT STATE (PULL — портфель). `bus.get_account(id).<поле>`",
            "",
            "| Поле | Тип | Источник | Доступ | Описание |",
            "|---|---|---|---|---|"]
    for a in cat["account_state_L2"]:
        out.append(f"| `{a['name']}` | {a['type']} | {a['source']} | `{a['access']}` | {a['desc']} |")

    miss = validate()
    out += ["", "---",
            f"**Покрытие:** события {len(cat['events'])} · L1 {len(cat['pair_state_L1'])} · L2 {len(cat['account_state_L2'])}.",
            ("⚠️ Без метаданных (дополнить): " + ", ".join(miss)) if miss else "✅ Каталог в синхроне с dataclass."]
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(to_markdown())
