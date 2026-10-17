# -*- coding: utf-8 -*-
"""Перепись памяти бота: ЧТО растёт (17.10.2026).

17.10 законный oko_mtf.py за 9,6 ч дорос до 10,4 ГБ private (~1 ГБ/ч), сирота с 15.10 — до 13,2 ГБ;
машина ушла в своп. Замер 18.08 «утечки нет» шёл 10 минут и рост на часах не видел.

Включается config.yaml → diagnostics.mem_census_min (0 = выкл). Фоновый поток раз в N минут пишет строку
в logs/mem_census.jsonl: private bytes процесса, объекты gc по типам (топ по числу и топ по приросту от первой
переписи), DataFrame/Series (штук и байт данных), блоки pymalloc, потоки по группам имён. Если private растёт,
а gc и DataFrame стоят — рост нативный (массивы вне DataFrame, буферы C-расширений): тогда включать
diagnostics.mem_census_tracemalloc (топ строк кода по приросту; заметно дороже, только на время расследования).

Перепись держит GIL — секунды на большой куче (длительность пишется в census_s), поэтому шаг не меньше 5 мин.
"""
from __future__ import annotations

import collections
import gc
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

from core.infra.config_loader import config

logger = logging.getLogger(__name__)

OUT = os.path.join("logs", "mem_census.jsonl")
FIRST_DELAY_S = 120
TOP_N = 40


def _private_mb() -> float | None:
    """Private bytes процесса — то же число, что PrivatePageCount у Win32_Process."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                "PrivateUsage")]

    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE          # 🔴 без restype HANDLE режется до 32 бит
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD)
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return round(pmc.PrivateUsage / 2**20, 1)


def _frame_bytes(o) -> int:
    try:
        return sum(b.values.nbytes for b in o._mgr.blocks)   # 0,5 мкс против 300 мкс у memory_usage()
    except Exception:
        return 0


def _loop_types() -> set:
    import asyncio
    out, todo = set(), [asyncio.BaseEventLoop]
    while todo:
        t = todo.pop()
        out.add(t)
        todo.extend(t.__subclasses__())
    return out


def _loop_stats(loop, thread_names: dict) -> dict:
    """17.10: с tracemalloc в боте жили 6,3 млн TimerHandle (asyncio.timeout на каждое WS-сообщение) — какой цикл их
    копит, по одной строке трассировки не видно. Очередь таймеров каждого живого цикла видна здесь без tracemalloc."""
    return {"thread": thread_names.get(getattr(loop, "_thread_id", None), "—"),
            "scheduled": len(getattr(loop, "_scheduled", ())),
            "cancelled": getattr(loop, "_timer_cancelled_count", None),
            "ready": len(getattr(loop, "_ready", ()))}


def _census(first: collections.Counter | None, prev: collections.Counter | None, t_start: float,
            tm_base) -> tuple[dict, collections.Counter]:
    t0 = time.perf_counter()
    objs = gc.get_objects()
    types = collections.Counter(f"{type(o).__module__}.{type(o).__qualname__}" for o in objs)
    pd = sys.modules.get("pandas")
    frames = {"DataFrame": [0, 0], "Series": [0, 0]}
    kinds = {pd.DataFrame: frames["DataFrame"], pd.Series: frames["Series"]} if pd is not None else {}
    loop_types = _loop_types()
    thread_names = {t.ident: t.name for t in threading.enumerate()}
    loops = []
    for o in objs:
        tp = type(o)
        acc = kinds.get(tp)
        if acc is not None:
            acc[0] += 1
            acc[1] += _frame_bytes(o)
        elif tp in loop_types and not o.is_closed():
            loops.append(_loop_stats(o, thread_names))
    n_objs = len(objs)
    del objs
    base = first or types
    grow = sorted(((k, v - base.get(k, 0)) for k, v in types.items()), key=lambda kv: -kv[1])[:TOP_N]
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_min": round((time.time() - t_start) / 60, 1),
        "private_mb": _private_mb(),
        "gc_objects": n_objs,
        "pymalloc_blocks": sys.getallocatedblocks(),
        "frames_mb": {k: [n, round(b / 2**20, 1)] for k, (n, b) in frames.items()},
        "threads": dict(collections.Counter(re.sub(r"[-_ ]?\d+(_\d+)?$", "", t.name)
                                            for t in threading.enumerate()).most_common()),
        "loops": loops,
        "top": [[k, v, v - (prev or types).get(k, 0)] for k, v in types.most_common(TOP_N)],
        "grow_from_first": [kv for kv in grow if kv[1] > 0],
    }
    if tm_base is not None:
        import tracemalloc
        snap = tracemalloc.take_snapshot()
        rec["tracemalloc_mb"] = round(tracemalloc.get_traced_memory()[0] / 2**20, 1)
        rec["tracemalloc_grow"] = [[str(s.traceback[0]), round(s.size_diff / 2**20, 2), s.count_diff]
                                   for s in snap.compare_to(tm_base, "lineno")[:25]]
    rec["census_s"] = round(time.perf_counter() - t0, 2)
    return rec, types


def _loop(step_s: float, use_tm: bool) -> None:
    t_start = time.time()
    tm_base = None
    if use_tm:
        import tracemalloc
        tracemalloc.start(1)
    time.sleep(FIRST_DELAY_S)
    if use_tm:
        tm_base = tracemalloc.take_snapshot()
    first = prev = None
    while True:
        try:
            rec, types = _census(first, prev, t_start, tm_base)
            first = first or types
            prev = types
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            logger.info("[MEM] private %s MB · gc %d · pymalloc %d · DataFrame %s · потоков %d · таймеров в циклах %s"
                        " · перепись %.1f с", rec["private_mb"], rec["gc_objects"], rec["pymalloc_blocks"],
                        rec["frames_mb"]["DataFrame"], sum(rec["threads"].values()),
                        {lp["thread"]: lp["scheduled"] for lp in rec["loops"]}, rec["census_s"])
        except Exception as e:  # noqa: BLE001 — диагностика не должна ронять бота
            logger.warning("[MEM] перепись упала: %s: %s", type(e).__name__, e)
        time.sleep(step_s)


def start() -> bool:
    """Запускает перепись, если diagnostics.mem_census_min > 0. Возвращает True, если включена."""
    step_min = float(config.get("diagnostics.mem_census_min", 0) or 0)
    if step_min <= 0:
        return False
    use_tm = bool(config.get("diagnostics.mem_census_tracemalloc", False))
    threading.Thread(target=_loop, args=(max(step_min, 5) * 60, use_tm), daemon=True, name="mem-census").start()
    logger.warning("[MEM] перепись памяти включена: шаг %.0f мин, tracemalloc=%s → %s", max(step_min, 5), use_tm, OUT)
    return True
