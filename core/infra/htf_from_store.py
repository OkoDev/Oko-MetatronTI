# -*- coding: utf-8 -*-
"""Сфера 1 → бот: старшие ТФ (1h/4h/1d) из хранилища закрытых баров, текущий бар — из 15m (BACKLOG N15).

Зачем (замер 29.09, лог [OHLCV-CACHE]): 1h+4h+1d — 50–60% REST скана в обычном цикле и ~90% после рестарта.
Каждая пара перекачивается раз в TTL (≈длина свечи) в случайный момент, поэтому закрытый бар попадал в бот
с опозданием до TTL. Хранилище дописывает закрытый бар через ~4 мин после закрытия, 15m в кэше живые (WS).

Сборка = закрытые бары из хранилища + текущий бар, агрегированный из 15m кэша бота
(open первого, max/min, close последнего, сумма объёма). Любая нехватка → None → старый путь REST:
синтетика (её нет в хранилище), хранилище не догнало закрытие, 15m нет/не свежие/с дырой, мало глубины.

Режим — config `market_store.bot_htf`: off | shadow (REST как раньше + сверка в лог) | on.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Optional

import pandas as pd

from core.infra.market_store import base_of, is_synthetic, read_bars

logger = logging.getLogger(__name__)

HTF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_M15 = 900_000
_COLS = ["time", "open", "high", "low", "close", "volume"]
_RETRY_SEC = 30.0          # хранилище отстаёт → не читать диск чаще этого
_LOG_EVERY_SEC = 600.0


def forming_from_15m(df15: Optional[pd.DataFrame], tf: str, now_ms: int, why: Optional[list] = None) -> Optional[dict]:
    """Текущий (незакрытый) бар tf из 15m. None, если 15m нет, не свежие или с дырой (причина → why)."""
    def _no(reason: str):
        if why is not None:
            why.append(reason)
        return None
    if df15 is None or df15.empty:
        return _no("none")
    step = HTF_MS[tf]
    cur, last15 = now_ms // step * step, now_ms // _M15 * _M15
    t = df15["time"].to_numpy(dtype="int64")
    if t[-1] != last15:                                   # нет текущего 15m-бара
        return _no(f"stale(lag={(last15 - int(t[-1])) // 60_000}м)")
    part = df15[t >= cur]
    if len(part) != (last15 - cur) // _M15 + 1 or int(part["time"].iloc[0]) != cur:
        return _no(f"short(есть {len(part)} из {(last15 - cur) // _M15 + 1}, всего {len(t)})")
    return {"time": cur, "open": float(part["open"].iloc[0]), "high": float(part["high"].max()),
            "low": float(part["low"].min()), "close": float(part["close"].iloc[-1]),
            "volume": float(part["volume"].sum())}


def compose(closed: Optional[pd.DataFrame], df15: Optional[pd.DataFrame], tf: str, limit: int,
            now_ms: int, exhausted: bool = False) -> tuple[Optional[pd.DataFrame], str]:
    """(DataFrame в формате REST ApiEngine: time мс + OHLCV, последний бар — текущий; причина отказа).
    exhausted — в хранилище вся история монеты (прочитано меньше запрошенного): молодой монете REST тоже отдаёт
    меньше limit, поэтому короткий ответ законен (29.09: SI/UBIK — число и первый бар совпали с REST на 1h/4h/1d)."""
    step = HTF_MS[tf]
    if closed is None or closed.empty or int(closed["time"].iloc[-1]) != now_ms // step * step - step:
        return None, "store_behind"
    if len(closed) < limit - 1 and not exhausted:
        return None, "store_short"
    why: list = []
    fb = forming_from_15m(df15, tf, now_ms, why)
    if fb is None:
        return None, f"no_15m_{why[0]}"
    out = pd.concat([closed[_COLS].iloc[max(0, len(closed) - (limit - 1)):], pd.DataFrame([fb])[_COLS]],
                    ignore_index=True)
    return out.astype({"time": "int64", **{c: "float64" for c in _COLS[1:]}}), "ok"


def _read_closed(base: str, tf: str, n: int) -> pd.DataFrame:
    d = read_bars(base, tf, n=n)
    return pd.DataFrame({"time": d.index.asi8 // 1_000_000, **{c: d[c].to_numpy() for c in _COLS[1:]}})


class HtfStore:
    """Закрытые бары в памяти (перечитываются, когда ожидается новый закрытый бар) + сборка + сверка."""

    def __init__(self, mode: str, depth: dict[str, int]):
        self.mode = mode
        self._depth = depth                  # глубина чтения по ТФ (канон ApiEngine + запас)
        self._closed: dict[tuple, tuple[pd.DataFrame, float]] = {}
        self.stats: Counter = Counter()
        self._diff_examples: list[str] = []
        self._why_examples: list[str] = []
        self._last_log = time.monotonic()

    async def _closed_for(self, symbol: str, tf: str, now_ms: int, need: int) -> tuple[Optional[pd.DataFrame], bool]:
        """(закрытые бары, история исчерпана). need — сколько закрытых нужно вызывающему: запросы глубже
        канона (график 1h×530, radar 4h×400) дочитывают хранилище, а не падают в REST."""
        base = base_of(symbol)
        if is_synthetic(base):
            return None, False
        want = now_ms // HTF_MS[tf] * HTF_MS[tf] - HTF_MS[tf]
        ent = self._closed.get((base, tf))                  # (df, когда читали, история исчерпана)
        rows_ok = ent is not None and (len(ent[0]) >= need or ent[2])
        have = int(ent[0]["time"].iloc[-1]) if ent is not None and len(ent[0]) else None
        if not rows_ok or have is None or have < want:
            if rows_ok and time.monotonic() - ent[1] < _RETRY_SEC:
                return ent[0], ent[2]                       # хранилище ещё не догнало — не долбить диск
            n = max(self._depth.get(tf, 250), need + 10)
            try:
                df = await asyncio.to_thread(_read_closed, base, tf, n)
            except Exception as e:  # noqa: BLE001 — хранилище недоступно → REST как раньше
                self.stats["read_error"] += 1
                logger.debug("[HTF-STORE] %s %s чтение: %s", base, tf, e)
                return None, False
            ent = (df, time.monotonic(), len(df) < n)
            self._closed[(base, tf)] = ent
        return ent[0], ent[2]

    async def get(self, symbol: str, tf: str, limit: int, df15: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Режим on: собранный DataFrame или None (→ REST)."""
        now_ms = int(time.time() * 1000)
        closed, exhausted = await self._closed_for(symbol, tf, now_ms, limit - 1)
        if closed is None:
            self.stats["skip_synth_or_err"] += 1
            return None
        df, why = compose(closed, df15, tf, limit, now_ms, exhausted)
        self._count(symbol, tf, why)
        self._maybe_log()
        return df

    def _count(self, symbol: str, tf: str, why: str) -> None:
        """Счётчик по грубой причине; детальная — в примеры (первые 4 за окно лога)."""
        self.stats[f"{tf}_{why.split('(')[0]}"] += 1
        if why != "ok" and len(self._why_examples) < 4:
            self._why_examples.append(f"{symbol} {tf} {why}")

    async def shadow_compare(self, symbol: str, tf: str, rest: pd.DataFrame, df15: Optional[pd.DataFrame]) -> None:
        """Режим shadow: REST-ответ против сборки из хранилища. Считает расхождения, торговлю не трогает."""
        try:
            now_ms = int(time.time() * 1000)
            closed, exhausted = await self._closed_for(symbol, tf, now_ms, len(rest) - 1)
            if closed is None:
                self.stats["skip_synth_or_err"] += 1
                return
            mine, why = compose(closed, df15, tf, len(rest), now_ms, exhausted)
            self._count(symbol, tf, why)
            if mine is None:
                return
            cur = now_ms // HTF_MS[tf] * HTF_MS[tf]
            r_closed, m_closed = rest[rest["time"] < cur], mine[mine["time"] < cur]
            j = r_closed.merge(m_closed, on="time", suffixes=("_r", "_s"))
            self.stats[f"{tf}_cmp"] += 1
            if len(j) != len(r_closed):
                self._diff(f"{tf}_closed_missing", symbol, f"REST {len(r_closed)} закрытых, общих {len(j)}")
            for c in ("open", "high", "low", "close", "volume"):
                rel = ((j[f"{c}_r"] - j[f"{c}_s"]).abs() / j[f"{c}_r"].abs().clip(lower=1e-12))
                if (rel > 1e-9).any():
                    k = int(rel.to_numpy().argmax())
                    self._diff(f"{tf}_closed_{c}", symbol,
                               f"t={int(j['time'].iloc[k])} REST={j[f'{c}_r'].iloc[k]} store={j[f'{c}_s'].iloc[k]}")
            r_last, m_last = rest.iloc[-1], mine.iloc[-1]
            if int(r_last["time"]) != cur:
                self.stats[f"{tf}_rest_no_forming"] += 1
                return
            for c, tol in (("open", 1e-9), ("high", 5e-3), ("low", 5e-3), ("close", 5e-3), ("volume", 0.05)):
                rel = abs(r_last[c] - m_last[c]) / max(abs(r_last[c]), 1e-12)
                if rel > tol:
                    self._diff(f"{tf}_forming_{c}", symbol, f"REST={r_last[c]} store={m_last[c]} ({rel:.2%})")
        except Exception as e:  # noqa: BLE001 — сверка не должна мешать скану
            self.stats["cmp_error"] += 1
            logger.debug("[HTF-STORE] сверка %s %s: %s", symbol, tf, e)
        finally:
            self._maybe_log()

    def _diff(self, kind: str, symbol: str, detail: str) -> None:
        self.stats[f"DIFF_{kind}"] += 1
        if len(self._diff_examples) < 5:
            self._diff_examples.append(f"{kind} {symbol}: {detail}")

    def _maybe_log(self) -> None:
        if time.monotonic() - self._last_log < _LOG_EVERY_SEC:
            return
        self._last_log = time.monotonic()
        logger.info("[HTF-STORE] режим=%s · %s%s%s", self.mode, dict(sorted(self.stats.items())),
                    (" · РАСХОЖДЕНИЯ: " + " | ".join(self._diff_examples)) if self._diff_examples else "",
                    (" · отказы: " + " | ".join(self._why_examples)) if self._why_examples else "")
        self._diff_examples.clear()
        self._why_examples.clear()
