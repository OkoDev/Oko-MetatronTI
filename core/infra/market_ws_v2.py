"""
MarketWS v2 — kline WebSocket в ОТДЕЛЬНОМ ПРОЦЕССЕ (обходит GIL).

Корень v1-провала: поток с 70k свечей/мин (gzip+json+DataFrame CPU) держит GIL →
scan_loop 300с→600с+. Урок: high-rate WS в Python = ТОЛЬКО процесс, не поток.

Архитектура v2:
  producer-процесс  →  multiprocessing.Queue  →  QueueReaderThread (main)  →  OhlcvCache
  (GIL изолирован)       (межпроцессный IPC)      (daemon thread, merge)       (основной)

ЭТАПЫ (как v1, за флагами market_ws.*):
  enabled=true + use_ws=false  → теневой OhlcvCache (Этап 1 SHADOW, scan на REST)
  enabled=true + use_ws=true   → основной кэш (Этап 2, scan читает WS) — после валидации ≥99%

Переиспользует MarketWS из market_ws.py (соединения/Ping/реконнект не меняем).
"""
from __future__ import annotations

import asyncio
import logging
import queue as _stdlib_queue
import threading
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ─── worker-процесс ────────────────────────────────────────────────────────────

# Throttle отправки в очередь: одну (sym,tf) не шлём чаще, чем раз в N секунд.
# 02.09.2026: было единое 5.0 для всех ТФ, и мы упирались в его потолок —
# 1734 ключа (578 пар × 3 ТФ) / 5 с = 347 сообщ/с максимум, фактически шло 280,
# то есть 81% предела. Reader делает merge в ГЛАВНОМ процессе, поэтому каждое
# сообщение стоит времени скана.
# Логика дифференциации: чем длиннее бар, тем реже его надо освежать. Раньше
# 15m-свеча обновлялась так же часто, как 3m, хотя живёт впятеро дольше.
#   3m  (бар 180 с) → 5 с  = 36 обновлений на бар   ← не трогаем, самый чувствительный
#   5m  (бар 300 с) → 8 с  = 37 обновлений
#   15m (бар 900 с) → 15 с = 60 обновлений
# Расчётный поток: 578 × (1/5 + 1/8 + 1/15) ≈ 227/с вместо 347 — минус треть.
# 🔴 Откат: вернуть единое значение _LIVE_DEDUP_DEFAULT для всех ТФ.
_LIVE_DEDUP_DEFAULT = 5.0
_LIVE_DEDUP_BY_TF = {"3m": 5.0, "5m": 8.0, "15m": 15.0, "1h": 30.0, "4h": 60.0, "1d": 120.0}


def _dedup_interval(tf: str) -> float:
    return _LIVE_DEDUP_BY_TF.get(tf, _LIVE_DEDUP_DEFAULT)


def _exit_with_parent() -> None:
    """🔴 17.10: воркер умирает вместе с ботом. daemon=True гасит его только при НОРМАЛЬНОМ выходе бота, а бот под pm2
    уходит через os._exit (сторож обёртки) или kill: воркер 8280 пережил бота на 49 мин сиротой (686 МБ + WS к бирже).
    Ждём на хэндле процесса-родителя (sentinel) — срабатывает при любой его смерти."""
    import multiprocessing
    import os
    from multiprocessing.connection import wait

    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def _watch():
        wait([parent.sentinel])
        os._exit(0)

    threading.Thread(target=_watch, daemon=True, name="mws-parent-watch").start()


def _mws_worker(out_queue, symbols: list, tfs: list, batch: int, shadow: bool = False,
                bind_prefix: str = "") -> None:
    """Standalone-функция для multiprocessing.Process.

    shadow=True  → очередь не используется, только stats-логирование (Этап 1)
    shadow=False → кладёт свечи в out_queue для QueueReaderThread (Этап 2)
    Вызывается через spawn (Windows default) → top-level функция, не lambda/closure.
    """
    # Windows spawn: воркер НЕ должен держать crypto_bot.log fd. Иначе при ротации
    # (RotatingFileHandler.doRollover → os.rename) в ГЛАВНОМ процессе → PermissionError
    # WinError 32 (файл занят воркером). Сбрасываем унаследованные/переоткрытые FileHandler;
    # stats воркера остаются в stdout (StreamHandler сохраняем).
    import logging as _lg
    _root = _lg.getLogger()
    for _h in _root.handlers[:]:
        if isinstance(_h, _lg.FileHandler):  # RotatingFileHandler — подкласс
            _root.removeHandler(_h)
            try:
                _h.close()
            except Exception:
                pass
    _exit_with_parent()

    import asyncio as _aio
    import threading as _thr
    import time as _time
    from core.infra.market_ws import MarketWS

    class _QueueCache:
        """Заглушка OhlcvCache: нет lock, нет данных."""
        _lock = _thr.RLock()
        _data: dict = {}

        def merge(self, key, df):
            return "ws"

    class _MarketWSQueue(MarketWS):
        def __init__(self, q, syms, tfs_, batch_, shadow_):
            super().__init__(syms, tfs_, _QueueCache(), batch_pairs=batch_, bind_prefix=bind_prefix)
            self._q = q
            self._shadow = shadow_
            self._last_sent: dict = {}  # (sym,tf) → monotonic ts
            self._held: dict = {}       # (sym,tf) → последнее придержанное прореживанием обновление

        def _on_candle(self, sym_ccxt: str, tf: str, df: pd.DataFrame) -> None:
            # 🔴 02.09: раньше здесь стоял ранний `return` для shadow — свечи не уходили
            # в очередь вообще. С новым надзором (супервайзор считает отказом застывший
            # `reader.applied`) это дало бы вечный цикл рестартов: поток «стоит» всегда,
            # потому что его намеренно не было. Теперь shadow идёт тем же путём —
            # разница только в том, что reader в shadow СЧИТАЕТ, а не мержит в кэш,
            # то есть торговый путь по-прежнему не затронут.
            # Throttle: не слать одну (sym,tf) чаще _dedup_interval(tf) сек
            # → поток 1200/s→~200/s, reader справляется без overflow
            key = (sym_ccxt, tf)
            try:
                r = df.iloc[0]
                row = {
                    "time":   int(r["time"]),
                    "open":   float(r["open"]),
                    "high":   float(r["high"]),
                    "low":    float(r["low"]),
                    "close":  float(r["close"]),
                    "volume": float(r.get("volume", 0)),
                }
            except Exception:
                self.stats["errors"] += 1
                return
            # 🔴 29.09 ФИНАЛ БАРА. Прореживание теряло последние 5–15 с бара: закрытый по потоку бар
            # не совпадал с биржевым (15m, 18 432 бара: close точно у 49.6%, объём у 18%). Придержанное
            # обновление досылается ПЕРЕД первым сообщением следующего бара — закрытый бар = финал.
            held = self._held.pop(key, None)
            if held is not None and held["time"] < row["time"]:
                self._put(sym_ccxt, tf, held)
            now = _time.monotonic()
            if now - self._last_sent.get(key, 0.0) < _dedup_interval(tf):
                self._held[key] = row
                return
            self._last_sent[key] = now
            self._put(sym_ccxt, tf, row)

        def _put(self, sym_ccxt: str, tf: str, row: dict) -> None:
            try:
                self._q.put_nowait((sym_ccxt, tf, row))
                self.stats["candles"] += 1
            except Exception:
                self.stats["errors"] += 1

    mws = _MarketWSQueue(out_queue, symbols, tfs, batch, shadow)
    loop = _aio.new_event_loop()
    _aio.set_event_loop(loop)
    try:
        loop.run_until_complete(mws.run())
    except Exception:
        pass
    finally:
        loop.close()


# ─── QueueReaderThread ─────────────────────────────────────────────────────────

class QueueReaderThread(threading.Thread):
    """Daemon thread в main процессе: читает из mp.Queue → merge в OhlcvCache.

    Работает в фоне, не блокирует event loop. Единственная точка записи в cache
    из WS-потока — lock гарантирован самим OhlcvCache._lock (RLock).
    """

    def __init__(self, q, cache, shadow: bool = True, spool_tfs: tuple = ()):
        super().__init__(daemon=True, name="mws-reader")
        self._q = q
        self._cache = cache
        self._shadow = shadow
        self._spool_tfs = spool_tfs   # Сфера 1: закрытые бары этих ТФ → очередь хранилища (market_spool)
        self._last_row: dict = {}     # (sym, tf) → последнее обновление бара — очередь не зависит от кэша бота
        # ARCH-153 (31.10): закрывшиеся бары, которые бот видел САМ. Хранилище Сферы 1 пишет
        # закрытый бар с задержкой (замер 31.10: у 552 из 610 монет последний закрытый бар 3m/5m
        # отстаёт на 2 шага), и без этого буфера сборку нельзя склеить без дыры.
        self._closed_rows: dict = {}  # (sym, tf) → deque последних закрывшихся баров
        self._running = True
        self.stats = {
            "applied": 0, "errors": 0, "shadow": shadow,
            "last_rate": 0.0, "_last_count": 0, "_last_ts": time.monotonic(),
        }
        # Диагностика merge-результатов per TF (почему 5m hit низкий: skip/replace/stale?)
        from collections import Counter as _C
        self._merge_res: _C = _C()  # ключ (tf, result) → count
        # ARCH-153 (31.10): читатель — единственное место, где есть ОБА источника (закрытые бары
        # хранилища Сферы 1 и последняя свеча WS), поэтому именно он собирает запись заново,
        # когда кэш потерял её по дыре. Раньше каждый рестарт = ~1100 REST-запросов на круг.
        cache.rebuild_hook = self._rebuild_from_store

    _BATCH_MAX = 1000  # дренируем до 1000 элементов за цикл

    def _spool(self, s: str, t: str, r: dict) -> None:
        """Пришло обновление СЛЕДУЮЩЕГО бара → последнее обновление предыдущего = финал закрытого бара → очередь.
        30.09: раньше бар шёл в очередь только на «append» кэша бота — пары без записи в кэше (сброшены на REST,
        скан их не запрашивал) молчали: 2–2.5% баров 3m/5m не доходили до хранилища даже без сбоев.
        ARCH-153 (31.10): тот же закрывшийся бар кладём в память читателя — сборка записи
        (см. `_rebuild_from_store`) берёт его оттуда, пока хранилище не дописало."""
        key = (s, t)
        prev = self._last_row.get(key)
        if prev is not None and r["time"] < prev["time"]:
            return                                     # опоздавшее сообщение старого бара — не откатываем
        self._last_row[key] = r
        if prev is not None and r["time"] > prev["time"]:
            self._remember_closed(key, prev)
            from core.infra import market_spool
            market_spool.put(s, t, prev)

    def _remember_closed(self, key: tuple, row: dict) -> None:
        """Запомнить закрывшийся бар (последние 4 на пару) — сырьё для локальной сборки записи."""
        from collections import deque as _dq
        buf = self._closed_rows.get(key)
        if buf is None:
            buf = self._closed_rows[key] = _dq(maxlen=4)
        if not buf or row["time"] > buf[-1]["time"]:
            buf.append(row)

    def _merge_one(self, s: str, t: str, r: dict) -> None:
        try:
            if t in self._spool_tfs:
                self._spool(s, t, r)          # он же ведёт _last_row для этих ТФ
            else:
                key = (s, t)
                prev = self._last_row.get(key)
                if prev is None or r["time"] >= prev["time"]:
                    self._last_row[key] = r
                if prev is not None and r["time"] > prev["time"]:
                    self._remember_closed(key, prev)
            # ARCH-130: merge_dict избегает pd.DataFrame([r]) в hot path
            _res = self._cache.merge_dict((s, t), r)
            self.stats["applied"] += 1
            self._merge_res[(t, _res)] += 1  # диагностика покрытия per TF
        except Exception as e:
            self.stats["errors"] += 1
            logger.debug("[MarketWS-v2] reader merge error: %s", e)

    # ── ARCH-153 (31.10): локальная сборка записи вместо REST ──────────────────
    _REBUILD_TFS = ("3m", "5m", "15m")
    # Хранилище отстало сильнее этого — это уже не «догоняет», а мёртвая пара: не подменяем
    _REBUILD_MAX_LAG_STEPS = 3

    def _rebuild_from_store(self, key: tuple, limit: int):
        """Собрать запись (symbol, tf): закрытые бары Сферы 1 + память читателя + текущая свеча WS.

        Возвращает DataFrame (time мс + OHLCV) или None, если собрать нельзя — тогда
        вызывающий идёт прежним путём (REST). К бирже не ходит: только диск + память.
        Зовётся из `OhlcvCache.rebuild` под его RLock.

        Почему не только хранилище: замер 31.10 — у 552 из 610 монет последний закрытый бар
        3m/5m отстаёт на 2 шага, у 15m — на 1. Склейка хранилища с текущим баром дала бы дыру
        ровно в один бар, а ряд с дырой потребителям отдавать нельзя (починка 29.09). Пропуск
        закрывает память читателя: бот видит, как бар закрывается, и держит последние 4.
        """
        s, t = key
        if t not in self._REBUILD_TFS:
            return None
        from core.infra.api_engine import _TF_STEP_MS
        from core.infra.market_store import base_of, is_synthetic, read_bars
        step = _TF_STEP_MS.get(t)
        if not step:
            return None
        base = base_of(s)
        if is_synthetic(base):                       # акции/форекс/сырьё в хранилище не пишутся
            return None
        now_bar = int(time.time() * 1000) // step * step
        cols = ["time", "open", "high", "low", "close", "volume"]
        try:
            d = read_bars(base, t, n=limit)
        except Exception:                            # noqa: BLE001 — диск/паркет недоступен → REST
            return None
        if d is None or d.empty:
            return None
        # read_bars отдаёт DatetimeIndex + OHLCV (колонки time нет) — приводим к формату ApiEngine
        store = d.assign(time=d.index.asi8 // 1_000_000)[cols]
        store = store[store["time"] < now_bar]
        if store.empty:
            return None
        last = int(store["time"].iloc[-1])
        if (now_bar - last) > step * (self._REBUILD_MAX_LAG_STEPS + len(self._closed_rows.get(key, ()))):
            return None                              # хранилище отстало настолько, что память не покроет
        tail = [store]
        # 1) бары, которые бот видел закрывшимися, но хранилище ещё не дописало
        for row in self._closed_rows.get(key, ()):
            if int(row["time"]) > last:
                tail.append(pd.DataFrame([row])[cols])
        d = pd.concat(tail, ignore_index=True).drop_duplicates("time", keep="last")
        d = d.sort_values("time").reset_index(drop=True)
        # 2) хранилище 3m/5m само с дырами (замер 31.10: чистый ряд у 178/610 по 3m и у 600/610
        # по 15m). Ряд с дырой потребителям не отдаём (починка 29.09) — но чистый ХВОСТ после
        # последней дыры годится, если он достаточно глубок.
        gaps = d["time"].diff().iloc[1:] > step
        if bool(gaps.any()):
            _pos = len(gaps) - 1 - int(gaps.values[::-1].argmax())   # позиция ПОСЛЕДНЕЙ дыры
            d = d.iloc[_pos + 1:].reset_index(drop=True)
        # 3) живой край: текущая свеча из WS сразу за последним закрытым
        cand = self._last_row.get(key)
        if len(d) and cand and int(cand.get("time", 0)) == int(d["time"].iloc[-1]) + step:
            d = pd.concat([d, pd.DataFrame([cand])[cols]], ignore_index=True)
        d = d.iloc[-limit:].reset_index(drop=True).astype(
            {"time": "int64", "open": "float64", "high": "float64",
             "low": "float64", "close": "float64", "volume": "float64"})
        if len(d) < 2:
            return None
        if not bool((d["time"].diff().iloc[1:] == step).all()):
            self.stats["rebuild_hole"] = self.stats.get("rebuild_hole", 0) + 1
            return None
        if len(d) < limit:
            # Глубина меньше канона — это ЗАКОННЫЙ ответ: чистый хвост после последней дыры.
            # Кэш запишет фактическую глубину, и глубокий потребитель честно уйдёт в REST,
            # а мелкие (20/100/150 — большинство запросов 3m/5m) получат данные даром.
            self.stats["rebuild_short"] = self.stats.get("rebuild_short", 0) + 1
        return d

    def run(self) -> None:
        while self._running:
            try:
                first = self._q.get(timeout=0.1)
            except _stdlib_queue.Empty:
                continue

            if self._shadow:
                # Shadow: scan_loop на REST, cache не используется →
                # просто дренируем очередь без pandas overhead (только счётчик)
                count = 1
                for _ in range(self._BATCH_MAX - 1):
                    try:
                        self._q.get_nowait()
                        count += 1
                    except _stdlib_queue.Empty:
                        break
                self.stats["applied"] += count
            else:
                # LIVE (use_ws=true): батч с merge в основной cache
                sym, tf, row = first
                latest: dict = {(sym, tf): row}
                for _ in range(self._BATCH_MAX - 1):
                    try:
                        s, t, r = self._q.get_nowait()
                    except _stdlib_queue.Empty:
                        break
                    prev = latest.get((s, t))
                    # 🔴 29.09: «последний выигрывает» терял ФИНАЛ бара, досланный воркером прямо перед
                    # первым сообщением следующего бара (оба в одной пачке). Новый бар → сначала финал старого.
                    if prev is not None and prev["time"] < r["time"]:
                        self._merge_one(s, t, prev)
                    latest[(s, t)] = r  # внутри одного бара последний выигрывает
                for (s, t), r in latest.items():
                    self._merge_one(s, t, r)

            # Лог раз в 60с
            now = time.monotonic()
            if now - self.stats["_last_ts"] >= 60:
                rate = (self.stats["applied"] - self.stats["_last_count"]) / (now - self.stats["_last_ts"])
                self.stats["last_rate"] = round(rate, 1)
                _lvl = logger.warning if rate <= 0 else logger.info
                _lvl("[MarketWS-v2] reader STATS (shadow=%s): rate=%.1f/s applied=%d q≈%d%s",
                     self._shadow, rate, self.stats["applied"],
                     self._q.qsize() if hasattr(self._q, "qsize") else -1,
                     "  🔴 ПОТОК СТОИТ" if rate <= 0 else "")
                # Разбивка merge-результатов per TF (диагностика WS-покрытия 5m/15m)
                if self._merge_res:
                    _by_tf: dict = {}
                    for (tf, res), n in self._merge_res.items():
                        _by_tf.setdefault(tf, {})[res] = n
                    logger.info("[MarketWS-v2] merge per TF: %s", _by_tf)
                self.stats["_last_count"] = self.stats["applied"]
                self.stats["_last_ts"] = now

    def stop(self) -> None:
        self._running = False


# ─── супервайзор ──────────────────────────────────────────────────────────────

async def _mws_supervisor(proc, out_queue, symbols, tfs, batch, cache, shadow, bot,
                          reader=None, bind_prefix: str = "") -> None:
    """
    Async-таска в main loop: раз в 30с проверяет, что worker жив И ЧТО ДАННЫЕ ИДУТ.

    🔴 02.09.2026: раньше проверялось ТОЛЬКО `proc.is_alive()`. Это пропускало самый
    неприятный отказ — процесс жив, а данных нет: WS-соединение закрылось внутри,
    реконнект не поднялся, очередь пуста, кэш тихо протухает. Никакого WARNING при
    этом не было: reader печатал `rate=0.0/s` уровнем INFO, и строка тонула в потоке
    логов. Ровно класс «молчаливый отказ», который в этом проекте уже стоил
    двух неработающих источников.

    Теперь мёртвым считается и процесс, который жив, но за два подряд окна (60 с)
    не принёс НИ ОДНОЙ свечи. Такой процесс перезапускается так же, как упавший.
    """
    import multiprocessing as mp

    stale_checks = 0          # сколько окон подряд поток данных стоит
    last_applied = -1
    while True:
        await asyncio.sleep(30)
        try:
            _applied = int(reader.stats.get("applied", 0)) if reader is not None else -1
            _frozen = False
            if reader is not None:
                if _applied == last_applied:
                    stale_checks += 1
                    if stale_checks == 2:      # ~60 с тишины
                        logger.warning(
                            "[MarketWS-v2] 🔴 процесс ЖИВ, но данных нет 60с "
                            "(applied=%d) — считаю отказом, рестарт", _applied)
                        _frozen = True
                else:
                    if stale_checks:
                        logger.info("[MarketWS-v2] поток данных восстановлен (applied=%d)",
                                    _applied)
                    stale_checks = 0
                last_applied = _applied

            if not proc.is_alive() or _frozen:
                if not proc.is_alive():
                    logger.warning("[MarketWS-v2] процесс упал (exitcode=%s) — рестарт",
                                   proc.exitcode)
                stale_checks = 0
                try:
                    proc.kill()
                except Exception:
                    pass
                new_proc = mp.Process(
                    target=_mws_worker,
                    args=(out_queue, symbols, tfs, batch, shadow, bind_prefix),
                    daemon=True, name="market-ws-v2",
                )
                new_proc.start()
                bot._market_ws_proc = new_proc
                proc = new_proc
                logger.info("[MarketWS-v2] процесс перезапущен (pid=%d)", new_proc.pid)
        except Exception as e:
            logger.warning("[MarketWS-v2] supervisor error: %s", e)


# ─── точка входа ──────────────────────────────────────────────────────────────

def start_market_ws_v2(bot) -> Optional[tuple]:
    """Запускает MarketWS v2 (процесс) если market_ws.enabled.

    Этап 1 SHADOW (use_ws=false): теневой OhlcvCache — scan на REST, сравнение.
    Этап 2 (use_ws=true): основной кэш — scan читает из WS.

    Возвращает (process, reader_thread) или None.
    """
    import multiprocessing as mp

    cfg = bot.config
    if not bool(cfg.get("market_ws.enabled", False)):
        return None

    tfs   = cfg.get("market_ws.timeframes", ["5m", "15m"]) or ["5m", "15m"]
    batch = int(cfg.get("market_ws.batch_pairs", 50))
    use_ws = bool(cfg.get("market_ws.use_ws", False))
    bind_prefix = str(cfg.get("market_ws.bind_ip_prefix", "") or "")

    symbols = list(getattr(bot.data_collector, "usdt_pairs", []) or [])
    if not symbols:
        logger.warning("[MarketWS-v2] enabled, но usdt_pairs пуст — не запускаю")
        return None

    from core.infra.api_engine import OhlcvCache
    if use_ws:
        cache  = bot.data_collector._engine._cache
        shadow = False
    else:
        cache  = OhlcvCache(maxsize=5000)
        shadow = True

    # 🔴 02.09.2026: очередь и reader создаются В ОБОИХ режимах.
    # Раньше в SHADOW было `out_queue = None, reader = None` — и это ломало сам смысл
    # теневого этапа: теневой `OhlcvCache` создавался, но НИКТО в него не писал,
    # то есть сравнить WS с REST было нечем. Хуже того, из main-процесса не было
    # видно, идут ли вообще данные: worker жужжал внутри себя, а наружу — тишина.
    # Теперь reader пишет в ТЕНЕВОЙ кэш (торговый путь не трогает) и одновременно
    # служит датчиком живости для супервайзора.
    out_queue = mp.Queue(maxsize=200_000)
    # Сфера 1 (N15 шаг 2): закрытые бары WS → очередь хранилища; пишет market-store (один писатель).
    spool_tfs = tuple(cfg.get("market_store.ws_spool_tfs", []) or []) if not shadow else ()
    reader    = QueueReaderThread(out_queue, cache, shadow=shadow, spool_tfs=spool_tfs)
    if spool_tfs:
        logger.info("[MarketWS-v2] закрытые бары %s → очередь хранилища Сферы 1", list(spool_tfs))
    reader.start()

    proc = mp.Process(
        target=_mws_worker,
        args=(out_queue, symbols, tfs, batch, shadow, bind_prefix),
        daemon=True, name="market-ws-v2",
    )
    proc.start()

    bot._market_ws_proc   = proc
    bot._market_ws_reader = reader
    bot._market_ws_queue  = out_queue

    # Супервайзор — async task в текущем event loop
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_mws_supervisor(proc, out_queue, symbols, tfs, batch, cache, shadow, bot, reader,
                                         bind_prefix=bind_prefix))
    except RuntimeError:
        pass  # вне loop — пропускаем (вызывается до start)

    from core.infra.market_ws import local_ip_by_prefix
    _ip = local_ip_by_prefix(bind_prefix)
    logger.info(
        "[MarketWS-v2] процесс запущен pid=%d (%d пар, tfs=%s, use_ws=%s, shadow=%s, сеть=%s)",
        proc.pid, len(symbols), tfs, use_ws, shadow,
        f"напрямую {_ip}" if _ip else ("через VPN (префикс не найден!)" if bind_prefix else "как у всех"),
    )
    return proc, reader
