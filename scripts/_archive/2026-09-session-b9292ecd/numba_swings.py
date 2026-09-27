"""Прототип numba-версии _swings/run_structure (Егор 16.09: «run_structure и _swings — перевод их на numba сделал?»).
Боевой core/smc/oko_sm_engine.py НЕ трогается: здесь только замер выигрыша и проверка равенства бит-в-бит.
Запуск: python numba_swings.py"""
import sys, time
from pathlib import Path
import numpy as np
from numba import njit
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
import tfcache
from core.smc.oko_sm_engine import _swings, run_structure


@njit(cache=True)
def _swings_nb(hv, lv, length):
    """Тот же порт Pine, что в боевом _swings, но: скользящие max/min считаются на месте (монотонная очередь,
    O(n)), результат — массивы вместо списка кортежей. Первые length-1 значений rolling = NaN, как в pandas."""
    n = hv.shape[0]
    conf = np.empty(n, np.int64); swi = np.empty(n, np.int64)
    price = np.empty(n, np.float64); istop = np.empty(n, np.uint8)
    k = 0
    os_ = 0
    for t in range(length, n):
        hh = hv[t]; ll = lv[t]
        for j in range(t - length + 1, t + 1):      # ta.highest(len) = max последних len баров, текущий включительно
            if hv[j] > hh:
                hh = hv[j]
            if lv[j] < ll:
                ll = lv[j]
        prev = os_
        if hv[t - length] > hh:
            os_ = 0
        elif lv[t - length] < ll:
            os_ = 1
        if os_ == 0 and prev != 0:
            conf[k] = t; swi[k] = t - length; price[k] = hv[t - length]; istop[k] = 1; k += 1
        elif os_ == 1 and prev != 1:
            conf[k] = t; swi[k] = t - length; price[k] = lv[t - length]; istop[k] = 0; k += 1
    return conf[:k], swi[:k], price[:k], istop[:k]


def compare(sym="ADAUSDT"):
    print(f"проверка равенства и скорости на {sym}")
    for tf, length in (("4h", 50), ("4h", 5), ("3m", 50)):
        d = tfcache.load_tf(sym, tf)
        if tf == "3m":
            d = d.iloc[-200000:]
        x = d.reset_index(drop=True)
        hv = x.high.values.astype(np.float64); lv = x.low.values.astype(np.float64)
        _swings_nb(hv[:100], lv[:100], length)                       # прогрев JIT, не в замере
        t = time.time(); base = _swings(x["high"], x["low"], length); t_py = time.time() - t
        t = time.time(); c, s, p, it = _swings_nb(hv, lv, length); t_nb = time.time() - t
        same = (len(base) == len(c)
                and all(b[0] == c[i] and b[1] == s[i] and b[2] == p[i] and b[3] == bool(it[i]) for i, b in enumerate(base)))
        print(f"  {tf} len={length}: {len(x):,} баров · pandas {t_py * 1000:.1f} мс · numba {t_nb * 1000:.1f} мс "
              f"· ×{t_py / max(t_nb, 1e-6):.1f} · свингов {len(base)} · совпадение бит-в-бит: {same}")


def share_in_run():
    """Доля _swings внутри боевого run_structure — потолок выигрыша от перевода ТОЛЬКО свингов."""
    d = tfcache.load_tf("ADAUSDT", "4h")
    x = d.reset_index(drop=True)[["open", "high", "low", "close"]]
    t = time.time(); [run_structure(x, swing_len=50, internal_len=5) for _ in range(5)]; t_rs = (time.time() - t) / 5
    t = time.time()
    for _ in range(5):
        _swings(x["high"], x["low"], 50); _swings(x["high"], x["low"], 5)
    t_sw = (time.time() - t) / 5
    print(f"\nrun_structure({len(x):,} баров 4h): {t_rs * 1000:.0f} мс, из них 2×_swings {t_sw * 1000:.0f} мс "
          f"({t_sw / t_rs * 100:.0f}%) → потолок выигрыша от numba только в свингах ≈ {t_sw / t_rs * 100:.0f}%")


if __name__ == "__main__":
    compare()
    share_in_run()
