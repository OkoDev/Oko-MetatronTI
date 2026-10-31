# -*- coding: utf-8 -*-
"""ARCH-153.1 — счётчик запросов к BingX по источникам (пассивный, на биржу ничего не добавляет).

hit(source, key) на каждый исходящий запрос; раз в минуту накопленное дописывается строкой в
logs/req_counter.jsonl: {"ts","src","n","by":{key: count}}. Источники пишут в один файл (append).
Без зависимостей — импортируется и ботом, и терминалом :8010.
"""
import json
import os
import threading
import time

_PATH = os.path.join("logs", "req_counter.jsonl")
_lock = threading.Lock()
_state = {"minute": 0, "by": {}}   # by: {src: {key: count}}


def _flush_locked():
    for src, by in _state["by"].items():
        row = {"ts": _state["minute"] * 60, "src": src, "pid": os.getpid(), "n": sum(by.values()), "by": by}
        try:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass


def hit_proc(key):
    """Источник = имя скрипта процесса (market_store_service.py и т.п.)."""
    import sys
    hit(os.path.basename(sys.argv[0]) or "proc", key)


def hit(src, key):
    """src: 'bot' | 'term'; key: 'ohlcv:15m', 'GET /openApi/...' и т.п."""
    try:
        m = int(time.time() // 60)
        with _lock:
            if _state["minute"] != m:
                _flush_locked()
                _state["minute"], _state["by"] = m, {}
            d = _state["by"].setdefault(src, {})
            d[key] = d.get(key, 0) + 1
    except Exception:
        pass
