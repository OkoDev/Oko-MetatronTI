# -*- coding: utf-8 -*-
"""RANGEFADE LOOP (Егор 30.07 «найди золотую стратегию») — первый эдж, переживший прокурора.
Бэктест 2024-26 causal: 1h ATRTrend UP + WT<порог (глубокий откат) → лонг, TP 1R, SL 3-барный лоу.
Медиана +0.66% (косты 0.15), 82% монет плюс, устойчив к топ-3, OOS-стабилен. Каветат: режим-
зависим (2025-26 силён, 2024 нет). Решающий тест — ЖИВОЕ исполнение VST (эдж умирает на филлах).

Триггер из шины (wt_snap 1h: wt1, atr_trend), SL из свежих 1h klines. Router source=rangefade.
Gated: trading.rangefade.enabled. Cap max_open. Дедуп/cooldown на пару.
"""
import asyncio
import logging
import time
import urllib.request
import datetime as _dt
import json as _json

import numpy as np
import pandas as pd

from core.smc.oko_sm_engine import run_structure

logger = logging.getLogger(__name__)
POLL_SEC = 120
_last_fire: dict = {}       # (sym:src) -> ts — кулдаун варианта
_last_fire_sym: dict = {}   # sym -> ts — кулдаун МОНЕТЫ поперёк всех вариантов (04.08: AEONBSC
                            # набрал 12 сделок и −14.52%, потому что три варианта били по очереди)


def _family(base: str) -> str:
    """Ключ семейства тикера. 04.08: живьём пришёл «кластер» NCSKTM2USD/NCSKPL2USD/NCSKMS2USD/
    NCSKVG2USD — это ОДНО семейство синтетики, а не рыночное падение. Кластер должен состоять
    из РАЗНЫХ инструментов, иначе гейт ловит корреляцию внутри одной обёртки."""
    b = "".join(ch for ch in base.upper() if ch.isalpha())
    return b[:4] if len(b) >= 4 else b


def _cfg(bot):
    return bot.config.get("trading.rangefade", {}) or {}


def _klines(base, interval, limit=40):
    """Свежие klines BingX на РОДНОМ ТФ сетапа → хронологический список. Только на триггере (редко)."""
    try:
        u = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
             f"&interval={interval}&limit={limit}")
        d = _json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "oko"}),
                                              timeout=8)).get("data", [])
        # BingX отдаёт newest-first → разворачиваем в хронологию
        return [{"high": float(k["high"]), "low": float(k["low"]), "close": float(k["close"])}
                for k in reversed(d)]
    except Exception:
        return []


# 07.08: локальные копии _ac_regime/_funding_map УДАЛЕНЫ — было два независимых кэша,
# каждый со своими 24 запросами к BingX; версия в radar_armed не получала данные
# (mkt_* писались как None во всех 39 сделках). Единый источник — core/context/market_regime.
from core.context.market_regime import (ac_regime as _ac_regime, ac_label as _ac_label,
                                        funding_map as _funding_map, turnover_map as _turnover_map,
                                        AC_LO as _AC_LO,
                                        AC_HI as _AC_HI)  # noqa: E402


def _wt_rising_closed(kl, n1=10, n2=21):
    """SHADOW 12.08: растёт ли WT на ПОСЛЕДНЕМ ЗАКРЫТОМ баре — условие бэктеста.

    Бэктест bigflush/rangefade требует `w[i] < thr AND w[i] > w[i-1]` (вход на РАЗВОРОТЕ).
    Живой вход проверяет только `w1 < thr` из шины, т.е. срабатывает всё время, пока WT
    под порогом. Возвращает None, если баров мало. Ничего не блокирует — только замер.
    """
    # rangefade/rangefade4h тянут 40 баров (200 только у bigflush15) — порог 60 давал
    # им вечный None. Для ewm(span=21) 35 баров достаточно, чтобы знак наклона был осмыслен.
    if not kl or len(kl) < 35:
        return None
    try:
        d = pd.DataFrame(kl)
        hlc = (d["high"] + d["low"] + d["close"]) / 3
        esa = hlc.ewm(span=n1).mean()
        dv = (hlc - esa).abs().ewm(span=n1).mean()
        w = ((hlc - esa) / (0.015 * dv.replace(0, float("nan")))).ewm(span=n2).mean().fillna(0).values
        return bool(w[-2] > w[-3])      # -1 = формирующийся, -2 = последний закрытый
    except Exception:
        return None


def _bos_down_count(kl, bars=20, swing_len=50, internal_len=5):
    """Сколько медвежьих BOS ВНУТРЕННЕЙ структуры (len5) за последние `bars` баров.

    Гейт 10.08 (n=4439 на 100 ликвидных монетах, косты 0.35%): фейдим только дислокацию,
    которая СЛОМАЛА структуру. Без BOS сетап хрупкий — PF 1.05, безтоп10% −884%, плюс лишь
    на 56 монетах из 100. С BOS — PF 1.79, безтоп10% +634%, 86/100, плюс все 3 года.
    С двумя BOS — PF 3.41, медиана +2.5%, WR 71% (идёт в сайзинг, не в гейт: частота ×1/6).
    ШКАЛА ВАЖНА: тот же гейт по swing50 ВРЕДИТ (PF 0.91) — флеш ломает внутреннюю
    структуру, а не старшую. Возвращает None если баров не хватило."""
    if len(kl) < swing_len + bars + 5:
        return None
    try:
        st = run_structure(pd.DataFrame(kl), swing_len=swing_len, internal_len=internal_len)
    except Exception:
        return None
    i0 = len(kl) - 1 - bars
    return sum(1 for e in st.events
               if e.internal and e.kind == "BOS" and not e.bull and int(e.i) >= i0)


def _atr_change(kl, n=14, lag=8):
    """ATRChange = ATR(n)/ATR(n) лагом lag − 1. >0 расширение волатильности, <0 сжатие.
    Ключ 30.07: фейдить ТОЛЬКО расширение (>0.3) — медиана +3.81% в оба года; флэт/сжатие льют."""
    if len(kl) < n + lag + 2:
        return None
    trs = []
    for i in range(1, len(kl)):
        pc = kl[i - 1]["close"]
        trs.append(max(kl[i]["high"] - kl[i]["low"], abs(kl[i]["high"] - pc), abs(kl[i]["low"] - pc)))
    if len(trs) < n + lag:
        return None
    atr_now = sum(trs[-n:]) / n
    atr_prev = sum(trs[-n - lag:-lag]) / n
    if atr_prev <= 0:
        return None
    return atr_now / atr_prev - 1


async def rangefade_loop(bot):
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[RANGEFADE] disabled (trading.rangefade.enabled=false)")
        return
    wt_thr = float(cfg.get("wt_threshold", -60))
    tp_r = float(cfg.get("tp_r", 1.0))
    max_open = int(cfg.get("max_open", 8))
    wt_thr_4h = float(cfg.get("wt_threshold_4h", -70))
    cooldown = float(cfg.get("cooldown_h", 6)) * 3600
    # ДВА фейд-сиблинга (30.07): 1h (rangefade, чоп-режим) + 4h WT<-70 (rangefade4h, СИЛЬНЕЕ —
    # плюс в ОБА года, медиана +2.60%, WR66, 54/70 монет плюс). source различает для табло.
    # SL берём с РОДНОГО ТФ сетапа (3-барный лоу) — как в бэктесте.
    # (ТФ, порог WT, source, баров на SL, мин.дистанция стопа % — 0 = без гейта размера)
    VARIANTS = [("1h", wt_thr, "rangefade", 3, 0.0), ("4h", wt_thr_4h, "rangefade4h", 3, 0.0)]
    if cfg.get("bigflush_enabled", False):
        # BIG-FLUSH 15m: тот же фейд, но ТОЛЬКО крупный сетап (стоп>4%) — иначе косты съедают цель.
        VARIANTS.append(("15m", wt_thr_4h, "bigflush15", 3, float(cfg.get("bigflush_min_stop_pct", 4.0))))
    CAPS = {"rangefade": max_open, "rangefade4h": max_open,
            "bigflush15": int(cfg.get("bigflush_max_open", 6))}
    # 🔴 22.08 ДВА ЛИМИТА (DEV-239): позиция = рыночный риск, заявка = резерв маржи.
    # Вход у фейда ЛИМИТНЫЙ: ожидающая заявка не в рынке и слот РИСКА занимать не
    # должна ([[cap_pending_not_risk_slot]] — у impulse_fib это дало 8ч простоя).
    # Кэп заявок по умолчанию равен кэпу позиций: поток восстанавливаем, маржу не
    # раздуваем. Семейная логика (rf = rangefade+4h, bf = bigflush15) сохранена.
    CAPS_PEND = {k: int(cfg.get(f"{k}_max_pending", v)) for k, v in CAPS.items()}
    FAMILY = {"rangefade": "rf", "rangefade4h": "rf", "bigflush15": "bf"}
    WT_FLOOR = -150.0   # санитайз: WT живёт в ±100; -200/-300 = сломанный индикатор на неликвиде
    # 04.09: `min_cluster` → `min_breadth` (омонимия: см. комментарий в config.yaml).
    # Старый ключ читается запасным, чтобы правка конфига и кода не были связаны по времени.
    MIN_BREADTH = int(cfg.get("min_breadth", cfg.get("min_cluster", 2)))
    MIN_CLUSTER = MIN_BREADTH   # алиас: ниже по коду имя ещё встречается
    MIN_BOS = int(cfg.get("bigflush_min_bos", 1))  # 10.08: без BOS PF1.05/безтоп10% −884; с BOS 1.79/+634
    # 05.08 СЕССИОННЫЙ ГЕЙТ (только для 15m big-flush, где измерено): фейд живёт в ТОНКОЙ ликвидности.
    # ASIA 00-08 PF 5.49 · OFF 21-24 PF 2.83 · LONDON 08-14 PF 0.45 (ЯД) · NY 14-21 PF 0.88.
    # Механизм: в тонкие часы флеш механический (ликвидации, свипы стопов) → откатывает;
    # в LONDON/NY флеш информированный (новости, институты) → продолжается.
    # ASIA/OFF + кластер: PF 3.90, безтоп10% +738, 19/20 монет, плюс в ВСЕ три года (косты 0.35%).
    BAD_HOURS = set(range(int(cfg.get("bad_session_from_h", 8)), int(cfg.get("bad_session_to_h", 21))))
    # 05.08 ФОРМА СВЕЧИ (4h-сетап, n548): закрытие в ВЕРХНИХ 30% диапазона бара → PF 0.98 (мертво),
    # в нижних → PF 2.96. Разворотная свеча = опоздание (5-е подтверждение «подтверждение=опоздание»).
    CLOSE_POS_MAX = float(cfg.get("close_pos_max", 0.7))
    # 10.08 ДВА ФИКСА ПОСЛЕ ЖИВОГО РАЗБОРА: 4 сделки дали −126.6% из −101.5% итога.
    # (1) ПОТОЛОК СТОПА: на неликвиде 3-барный лоу уходит на 20-48% (CATE −48.56%,
    #     GPUBSC −29.42%). Медиана наших стопов 3.9%, 90-й перцентиль 13% → кап 12%
    #     режет 13% сделок и ВСЕ катастрофы. (2) ОБОРОТ: бэктест гонялся на ЛИКВИДНОЙ
    #     половине, а бот берёт все 520 пар — гейт возвращает вселенную к измеренной.
    MAX_STOP_PCT = float(cfg.get("max_stop_pct", 12.0))
    # 10.08 ГИБРИД-ВЫХОД (bigflush15): бэктест на ВСЕЛЕННОЙ БОЯ (ликвид, стоп 4-12%) —
    # TP1R МЕД +0.910% PF1.64 против гибрида по линии ATRTrend МЕД +2.839% PF1.69,
    # безтоп10% +53 → +216, плюс во все три года. Раннером правит ШТАТНЫЙ TSL.
    HYBRID_ON = bool(cfg.get("hybrid_exit", True))
    MIN_TURNOVER = float(cfg.get("min_turnover_usd", 2_000_000))
    logger.info("[RANGEFADE] loop start: %s → LONG TP%.1fR · капы %s",
                " + ".join(f"{tf} WT<{thr:.0f} ({src}{f', стоп>{mp:.0f}%' if mp else ''})"
                           for tf, thr, src, _, mp in VARIANTS), tp_r, CAPS)
    import sqlite3
    from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    from core.context.context_factory import build_market_context
    while True:
        try:
            await asyncio.sleep(POLL_SEC)
            pair_ctx = getattr(bot, "pair_context", None)
            if pair_ctx is None:
                continue
            db = bot.trade_simulator.db_path
            conn = sqlite3.connect(db, timeout=5)
            rows = conn.execute("SELECT signal_type,status,COUNT(*) FROM simulated_trades WHERE status IN "
                                "('OPEN','PENDING_ENTRY') AND signal_type IN ('rangefade','rangefade4h','bigflush15') "
                                "GROUP BY signal_type,status").fetchall()
            conn.close()
            # семейства делят кап: rf (rangefade+rangefade4h) и bf (bigflush15) — независимо.
            # 22.08: позиции и заявки считаются РАЗДЕЛЬНО (см. CAPS_PEND выше).
            n_fam = {"rf": 0, "bf": 0}          # позиции = рыночный риск
            n_fam_p = {"rf": 0, "bf": 0}        # заявки = резерв маржи
            for st_, status_, cnt in rows:
                fam = FAMILY.get(st_, "rf")
                if status_ == "OPEN":
                    n_fam[fam] = n_fam.get(fam, 0) + cnt
                else:
                    n_fam_p[fam] = n_fam_p.get(fam, 0) + cnt
            _full = lambda f: (n_fam[f] >= min(CAPS[x] for x in CAPS if FAMILY[x] == f)
                               or n_fam_p[f] >= min(CAPS_PEND[x] for x in CAPS_PEND if FAMILY[x] == f))
            if all(_full(f) for f in n_fam):
                continue
            now = time.time()
            # ПРОХОД 1: собираем кандидатов. 31.07: весь эдж в КЛАСТЕРАХ — монета, упавшая
            # ОДНА (идиосинкразия: своя новость/слом), льёт (МЕД −0.218% PF0.67); упавшая
            # ВМЕСТЕ с рынком (механическое корреляционное падение) отскакивает (+1.232% PF2.24).
            # 🔴 БУФЕР ПО БАРУ (04.09.2026) — почему кластер-гейт не работал в бою.
            # Бэктест считает кластером монеты, чей СИГНАЛЬНЫЙ БАР закрылся в одну метку.
            # Бой собирал их за ОДИН ПРОХОД цикла — а это разные вещи: `scan_loop`
            # обходит вселенную последовательно (~290 с), луп просыпается раз в 120 с,
            # поэтому в один проход попадают монеты, чей `wt_snap` обновлён в РАЗНОЕ время.
            # Замер по pm2-логам: кластер-гейт проходили **7.7%** сигналов (67 из 875)
            # против **88%** в бэктесте — расхождение в 11 раз, и стратегия почти не
            # торговала. Характерная улика: OPENLEDGER попал в «одиночки» 348 раз —
            # сигнал WT<порог это СОСТОЯНИЕ, монета остаётся кандидатом каждый проход,
            # но соседи к этому моменту устарели.
            # Лечение: копим кандидатов в буфере, живущем МЕЖДУ проходами, и группируем
            # по метке бара — тогда монеты, найденные в разные проходы внутри одного
            # бара, собираются в кластер, как в бэктесте.
            # Класс ошибки: [[universe_mismatch_backtest_vs_live]] — замер на закрытии
            # бара не описывает систему с асинхронным сканом.
            _BAR_SEC = {"3m": 180, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
            cand = {src: [] for _, _, src, _, _ in VARIANTS}
            if not hasattr(rangefade_loop, "_cluster_buf"):
                rangefade_loop._cluster_buf = {}
            _buf = rangefade_loop._cluster_buf
            for sym in pair_ctx.all_symbols():
                st = pair_ctx.get(sym)
                px = st.tick_price
                if not px:
                    continue
                for tf, thr, src, lookback, min_stop_pct in VARIANTS:
                    if (n_fam[FAMILY[src]] >= CAPS[src]
                            or n_fam_p[FAMILY[src]] >= CAPS_PEND[src]):
                        continue
                    wt = (st.wt_snap or {}).get(tf) or {}
                    w1 = wt.get("wt1")
                    at = wt.get("atr_trend")
                    if w1 is None or at is None:
                        continue
                    if not (at > 0 and w1 < thr):          # аптренд ТФ + глубокий откат
                        continue
                    if w1 < WT_FLOOR:                     # сломанный WT на неликвиде — не наш сетап
                        logger.info("[RANGEFADE] ⏭ %s [%s] WT=%.0f < %.0f — мусорный индикатор",
                                    sym, src, w1, WT_FLOOR)
                        continue
                    key = f"{sym}:{src}"
                    if now - _last_fire.get(key, 0) < cooldown:
                        continue
                    if now - _last_fire_sym.get(sym, 0) < cooldown:
                        continue        # кулдаун МОНЕТЫ: не бить одну пару разными вариантами
                    base = sym.split("/")[0]
                    # bigflush15 тянет 200 баров: тем же запросом кормим структурный гейт (BOS)
                    kl = _klines(base, tf, 200 if src == "bigflush15" else 40)
                    lows = [k["low"] for k in kl[-lookback:]] if kl else []
                    lo = min(lows) if lows else None
                    if not lo or lo >= px:
                        logger.info("[RANGEFADE] ⏭ %s [%s] нет klines/лоу выше цены (lo=%s px=%.6g)",
                                    sym, src, lo, px)
                        continue
                    # 12.08 SHADOW (не блокирует): бэктест, прошедший прокурора, требует
                    # WT РАСТУЩИЙ на закрытом баре — `w[i] < thr AND w[i] > w[i-1]`.
                    # Живой вход проверяет только `w1 < thr`, т.е. входит ПОКА WT под порогом
                    # (падающий нож). Сверка 63 живых сигналов с кэшем: 44% не проходят
                    # бэктестовое условие. Копим статистику, поведение НЕ меняем.
                    _wt_rise = _wt_rising_closed(kl)
                    logger.info("[RANGEFADE] 🔬 SHADOW-WT %s [%s] разворот_на_закрытом=%s "
                                "(бэктест берёт только True)", sym, src, _wt_rise)
                    sl = lo * 0.997
                    stop_pct = (px - sl) / px * 100
                    if min_stop_pct and stop_pct < min_stop_pct:
                        continue                # BIG-FLUSH: мелкий сетап — косты съедят цель
                    if MAX_STOP_PCT and stop_pct > MAX_STOP_PCT:
                        logger.info("[RANGEFADE] ⏭ %s [%s] стоп %.1f%% > %.0f%% — неликвидный хлам",
                                    sym, src, stop_pct, MAX_STOP_PCT)
                        continue
                    if MIN_TURNOVER:
                        # 🔴 29.09 FAIL-CLOSED. Было `if _tv is not None and _tv < MIN`: при пустой
                        # карте (bulk-запрос тикеров упал) `_tv is None` → условие ложно → гейт
                        # пропускал ВСЁ, включая хлам, ради которого его и заводили 10.08.
                        # За месяц карта ни разу не падала (4804 отсечения, 0 ошибок), то есть это
                        # страховка, а не лечение: на деньгах умолчание обязано быть запретительным
                        # ([[turnover_gate_fails_open]]).
                        _tmap = _turnover_map()
                        _tv = _tmap.get(base)
                        if not _tmap:
                            logger.warning("[RANGEFADE] ⏭ %s [%s] карта оборотов ПУСТА "
                                           "(биржа недоступна?) — пропускаю, вселенная неизвестна", sym, src)
                            continue
                        if _tv is None:
                            logger.info("[RANGEFADE] ⏭ %s [%s] пары нет в карте оборотов — "
                                        "вне вселенной бэктеста", sym, src)
                            continue
                        if _tv < MIN_TURNOVER:
                            logger.info("[RANGEFADE] ⏭ %s [%s] оборот $%.0f < $%.0f — вне вселенной бэктеста",
                                        sym, src, _tv, MIN_TURNOVER)
                            continue
                    if src == "bigflush15" and _dt.datetime.now(_dt.timezone.utc).hour in BAD_HOURS:
                        continue                # LONDON/NY: информированный флеш, не откатывает (PF 0.71)
                    # 05.08 ФОРМА СВЕЧИ (измерено на 4h-сетапе, n548): закрытие в ВЕРХНИХ 30%
                    # диапазона бара → PF 0.98 (мертво), в нижних → PF 2.96. Разворотная свеча =
                    # опоздание. Пятое подтверждение «подтверждение = опоздание».
                    if src == "rangefade4h" and kl:
                        _b = kl[-1]; _rng = _b["high"] - _b["low"]
                        if _rng > 0 and (_b["close"] - _b["low"]) / _rng > CLOSE_POS_MAX:
                            continue
                    # 10.08 СТРУКТУРНЫЙ ГЕЙТ (мысль Егора про CHoCH/BOS): фейдим только
                    # дислокацию, СЛОМАВШУЮ внутреннюю структуру. Без BOS половина сетапов —
                    # балласт: PF 1.05 против 1.79, безтоп10% −884% против +634%.
                    bos_dn = _bos_down_count(kl) if src == "bigflush15" else None
                    if src == "bigflush15" and MIN_BOS:
                        if bos_dn is None:
                            logger.warning("[RANGEFADE] ⚠ %s [%s] структура не посчиталась "
                                           "(баров %d) — пропускаю гейт BOS", sym, src, len(kl))
                        elif bos_dn < MIN_BOS:
                            logger.info("[RANGEFADE] ⏭ %s [%s] нет медв. BOS за 5ч — "
                                        "флеш не сломал структуру (хрупкая половина, PF 1.05)",
                                        sym, src)
                            continue
                    acg = _atr_change(kl)   # записываем как фичу (гейтить нельзя: без него сетап тоже плюс)
                    _c = {"sym": sym, "tf": tf, "px": px, "sl": sl, "w1": w1,
                          "stop_pct": stop_pct, "acg": acg, "base": base, "key": key,
                          "bos_dn": bos_dn}
                    cand[src].append(_c)
                    # копим в буфер по метке бара — кластер собирается за весь бар,
                    # а не за один проход цикла (см. комментарий у _BAR_SEC выше)
                    _bar = int(now // _BAR_SEC.get(tf, 900)) * _BAR_SEC.get(tf, 900)
                    _buf.setdefault((src, _bar), {})[sym] = _c
                    break
            # ПРОХОД 2: ГЕЙТ ШИРИНЫ РЫНКА — торгуем только рыночное падение (≥2 монеты одновременно).
            # 04.09: раньше назывался «кластер-гейт»; слово значило три разных вещи (см. config.yaml).
            ac_now = _ac_regime()
            ac_label = (None if ac_now is None else
                        ("импульсный" if ac_now >= _AC_HI else
                         ("возвратный" if ac_now <= _AC_LO else "середина")))
            # чистим буфер от баров старше двух периодов — память не растёт
            for _k in [k for k in _buf
                       if now - k[1] > 2 * _BAR_SEC.get(
                           next((t for t, _, s, _, _ in VARIANTS if s == k[0]), "15m"), 900)]:
                _buf.pop(_k, None)

            for _tf_v, _, src, _, _ in VARIANTS:
                _bar_now = int(now // _BAR_SEC.get(_tf_v, 900)) * _BAR_SEC.get(_tf_v, 900)
                # кластер = ВСЕ кандидаты текущего бара (из буфера), а не только
                # найденные в этом проходе; сам вход по-прежнему только для свежих
                _bar_all = list((_buf.get((src, _bar_now)) or {}).values())
                cs_now = cand.get(src) or []
                if not cs_now:
                    continue
                cs = _bar_all if len(_bar_all) >= len(cs_now) else cs_now
                if len(cs) > len(cs_now):
                    logger.info("[RANGEFADE] 🧩 [%s] ширина по БАРУ: %d монет "
                                "(в этом проходе было %d) — буфер бара %s",
                                src, len(cs), len(cs_now),
                                _dt.datetime.fromtimestamp(_bar_now, _dt.timezone.utc).strftime("%H:%M"))
                if len(cs) < MIN_CLUSTER:
                    logger.info("[RANGEFADE] ⏭ [%s] УЗКАЯ ШИРИНА: одиночный сигнал (%s) — идиосинкразия, пропуск "
                                "(в бэктесте PF 0.67 против 2.24 при широком заливе)",
                                src, ", ".join(c["sym"].split("/")[0] for c in cs))
                    continue
                fams = {_family(c["base"]) for c in cs}
                if len(fams) < MIN_CLUSTER:
                    logger.info("[RANGEFADE] ⏭ [%s] ПСЕВДО-ШИРИНА: %d монет ОДНОГО семейства %s (%s) — "
                                "это не рыночное падение, пропуск", src, len(cs), sorted(fams),
                                ", ".join(c["sym"].split("/")[0] for c in cs[:6]))
                    continue
                logger.info("[RANGEFADE] 🔔 [%s] ШИРИНА РЫНКА %d монет / %d семейств: %s · режим=%s",
                            src, len(cs), len(fams),
                            ", ".join(c["sym"].split("/")[0] for c in cs[:8]), ac_label or "?")
                # 🔴 ВХОДИМ ТОЛЬКО ПО СВЕЖИМ. Буфер бара служит ГЕЙТОМ (доказать, что
                # падение рыночное), но у его старых записей `px`/`sl` сняты минуты назад —
                # открывать по ним значило бы торговать по устаревшей цене.
                # Кластер = свойство РЫНКА, вход = свойство МОМЕНТА, это разные вещи.
                for c in cs_now:
                    if (n_fam[FAMILY[src]] >= CAPS[src]
                            or n_fam_p[FAMILY[src]] >= CAPS_PEND[src]):
                        break
                    _f = _funding_map().get(c["base"])
                    fund_now = round(_f, 5) if _f is not None else None
                    # 10.08 ГИБРИД-ВЫХОД для bigflush15 (бэктест: медиана ВТРОЕ выше TP1R,
                    # плюс во все 3 года, безтоп10% +216 при костах 0.35%). Реализация без правок
                    # механики ордеров: шлём ДВЕ половины по 0.5× риска —
                    #   «банк» с TP1R (как сейчас) и «раннер» с дальней целью, которым управляет
                    #   ШТАТНЫЙ TSL (активация +1R, линия ATRTrend, доезжает до биржи через
                    #   update_tsl_on_exchange). Родной трейл бота проверен: медиана +2.839%
                    #   против +2.705% у peak−3×ATR — не хуже, и писать свой не нужно.
                    _hybrid = (src == "bigflush15" and HYBRID_ON)
                    _legs = ([(tp_r, 0.5, "bank"), (float(cfg.get("runner_tp_r", 5.0)), 0.5, "runner")]
                             if _hybrid else [(tp_r, 1.0, "single")])
                    for _tpr, _share, _leg in _legs:
                        tp = c["px"] + _tpr * (c["px"] - c["sl"])
                        rec = TradingRecommendation(
                            symbol=c["sym"], action="BUY", direction=SignalDirection.LONG,
                            overall_strength=65, confidence=0.6, risk_level="MEDIUM", signals_count=1,
                            supporting_signals=[], conflicting_signals=[],
                            # 29.09: контекст СОБИРАЕТ ШИНА, а не луп. Раньше здесь стоял
                            # volume_24h=0.0, и оборот терялся во всех сделках источника.
                            market_context=build_market_context(bot, c["sym"], current_price=c["px"]),
                            entry_price=c["px"], stop_loss=c["sl"], take_profit=tp,
                            sl_source=f"{src}:{c['tf']}low", tp_source=f"{src}:{_tpr}R:{_leg}")
                        # САЙЗИНГ ×1.5 (потолок risk_mult_cap): два независимых усилителя —
                        #   толпа в шортах в импульсном режиме (PF 3.00) ИЛИ
                        #   два слома структуры подряд (PF 3.41, медиана +2.5%, WR 71%).
                        # В гейт «≥2 BOS» не ставим: частота падает вшестеро (0.17 против 0.96
                        # сделки/монету/мес), а по %/мес выигрывает более частый ≥1 BOS.
                        _boost = 1.0
                        if src == "bigflush15":
                            if (fund_now is not None and fund_now < 0
                                    and ac_label == "импульсный"):
                                _boost = 1.5
                            elif (c.get("bos_dn") or 0) >= 2:
                                _boost = 1.5
                        _mult = _share * _boost
                        res = await bot.trade_router.submit(rec, source=src, extra_features={
                            "signal_type_override": src, "trade_mode": src,
                            "rf_tf": c["tf"], "rf_wt1": round(c["w1"], 1), "rf_tp_r": _tpr,
                            "rf_leg": _leg,               # bank = фиксация на 1R · runner = под TSL
                            "rf_stop_pct": round(c["stop_pct"], 2),
                            "rf_cluster_size": len(cs), "rf_cluster_families": len(fams),
                            "rf_funding": fund_now,
                            "rf_ac_regime": round(ac_now, 5) if ac_now is not None else None,
                            "rf_ac_label": ac_label,
                            "risk_mult": _mult,
                            "rf_bos_dn": c.get("bos_dn"),   # медв. BOS len5 за 5ч (гейт ≥1, сайзинг ≥2)
                            "rf_atr_change": round(c["acg"], 3) if c["acg"] is not None else None})
                        if res.trade_id:
                            _last_fire[c["key"]] = now
                            _last_fire_sym[c["sym"]] = now
                            if _leg != "runner":
                                n_fam[FAMILY[src]] += 1     # кап считаем по «банковой» ноге, чтобы гибрид не съел его вдвое
                            logger.info("[RANGEFADE] ✅ %s [%s/%s] WT=%.0f стоп%.1f%% кластер=%d ×%.2f fund=%s режим=%s → trade %s exch=%s",
                                        c["sym"], src, _leg, c["w1"], c["stop_pct"], len(cs), _mult,
                                        f"{fund_now:+.4f}%" if fund_now is not None else "?",
                                        ac_label or "?", res.trade_id, res.exchange_order_id or "pending")
                            continue
                        drops = "; ".join(f"{g}:{r}" for g, r in (res.hard_drops or [])) or "unknown"
                        logger.info("[RANGEFADE] ⛔ %s [%s/%s] WT=%.0f отклонён: %s", c["sym"], src, _leg, c["w1"], drops)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[RANGEFADE] loop err: %s", e)
