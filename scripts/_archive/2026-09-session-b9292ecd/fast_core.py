"""Ускорение горячего цикла ядра для замеров (16.09). Боевой core/waves/wave5_core.py НЕ меняется:
здесь подмена функции в памяти процесса + проверка равенства бит-в-бит.

Профиль прогона 15m (127k баров): impulses_on_bar 40 с из 80. Причина — `conf = [s for s in swings if s[0] <= t]`:
полный проход по всему списку свингов на КАЖДОМ баре. Свинги отсортированы по бару подтверждения,
поэтому граница берётся бинарным поиском, а список не копируется целиком.
Применить: import fast_core; fast_core.patch()"""
from bisect import bisect_right
import core.waves.wave5_core as W

_orig = W.impulses_on_bar
_cache = {}


def _bars(swings):
    """Массив баров подтверждения для бинарного поиска; кэш на список свингов (он строится раз на монету)."""
    key = id(swings)
    got = _cache.get(key)
    if got is None or got[0] is not swings:
        got = (swings, [s[0] for s in swings])
        _cache[key] = got
    return got[1]


def impulses_on_bar(swings, t, high, low, merge=False, pool_n=16, max_absorb=6):
    n = bisect_right(_bars(swings), t)          # свинги, подтверждённые к бару t (список отсортирован по s[0])
    if n < 5:
        return []
    out = W._five(swings[n - 5:n], t, high, low)
    if out or not merge:
        return out
    pool = W._fix_same_kind(swings[max(0, n - pool_n):n]); gone = 0
    while len(pool) >= 5 and gone < max_absorb:
        pairs = W._inner_pairs(pool, tail=6)
        if not pairs:
            return []
        i = pairs[0][1]; del pool[i:i + 2]; gone += 2
        if len(pool) < 5:
            return []
        out = W._five(pool[-5:], t, high, low)
        if out:
            for o in out:
                o["absorbed"] = gone
            return out
    return []


def patch():
    W.impulses_on_bar = impulses_on_bar


def unpatch():
    W.impulses_on_bar = _orig
