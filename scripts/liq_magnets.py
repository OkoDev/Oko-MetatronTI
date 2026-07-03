# -*- coding: utf-8 -*-
"""Магниты ликвидаций — своя лайт-карта уровней (Егор 03.07: «магниты — заранее знать!»).

Методика (как Coinglass, честно = модель, не факт):
  1. Точки набора позиций — ФАКТ: часы, где OI вырос (openInterestHist 1h, ~20 дней).
     Набрано dOI монет по цене close этого часа.
  2. Плечи — эвристика LEV_DIST (распределение неизвестно, типовые 10/25/50/100x).
     Лонг-ликвидации ниже цены набора, шорт — выше; лонг/шорт 50/50.
  3. Сожжённое топливо гасим: если цена после набора уже прошла уровень — ликвидации
     там уже случились, магнит потрачен.
  4. Живое топливо биннингом → магниты: где скопление $ — туда цену «тянет»
     (стопы+ликвидации = топливо импульса, GRT-урок 03.07).

Запуск: python scripts/liq_magnets.py GRT [1000SHIB ...]
Ретро:  python scripts/liq_magnets.py GRT --before 2026-07-02T16:00   (карта на момент ДО события)
Сверка: coinglass.com LiquidationHeatMap — зоны должны совпадать по расположению.
"""
import sys, json, time, calendar, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

LEV_DIST = {10: 0.25, 25: 0.40, 50: 0.25, 100: 0.10}   # эвристика долей плеч
MMR = 0.005                                              # maintenance margin ~0.5%
BIN_PCT = 0.5                                            # шаг корзины, % от цены
RANGE_PCT = 20                                           # смотрим ±20% от цены


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def build_magnets(sym: str, before_ms: int | None = None):
    k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=1h&limit=500")
    oi = _get(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}USDT&period=1h&limit=500")
    if before_ms:                                        # ретро: мир как он был ДО события
        k = [x for x in k if int(x[0]) < before_ms]
        oi = [x for x in oi if int(x["timestamp"]) < before_ms]
    if len(oi) < 50:
        return None
    kl = {int(x[0]): (float(x[2]), float(x[3]), float(x[4])) for x in k}   # ts -> (hi, lo, close)
    px_now = float(k[-1][4])
    ts_sorted = sorted(kl)
    # живое топливо: (уровень, $) — гасим уровни, пройденные ценой ПОСЛЕ набора
    fuel = []
    oi_rows = [(int(x["timestamp"]), float(x["sumOpenInterest"])) for x in oi]
    for i in range(1, len(oi_rows)):
        ts, cur = oi_rows[i]
        d_oi = cur - oi_rows[i - 1][1]
        if d_oi <= 0 or ts not in kl:
            continue
        entry = kl[ts][2]
        usd = d_oi * entry
        later = [kl[t] for t in ts_sorted if t > ts]
        min_lo = min((x[1] for x in later), default=entry)
        max_hi = max((x[0] for x in later), default=entry)
        for lev, share in LEV_DIST.items():
            liq_l = entry * (1 - 1 / lev + MMR)          # лонг-ликвидации ниже набора
            liq_s = entry * (1 + 1 / lev - MMR)          # шорт-ликвидации выше
            if liq_l < min_lo:                            # цена туда ещё НЕ ходила — живой
                fuel.append((liq_l, usd * share * 0.5))
            if liq_s > max_hi:
                fuel.append((liq_s, usd * share * 0.5))
    # биннинг вокруг текущей цены
    lo_lim, hi_lim = px_now * (1 - RANGE_PCT / 100), px_now * (1 + RANGE_PCT / 100)
    step = px_now * BIN_PCT / 100
    bins = {}
    for lvl, usd in fuel:
        if lo_lim <= lvl <= hi_lim:
            b = round(lvl / step) * step
            bins[b] = bins.get(b, 0) + usd
    above = sorted(((b, u) for b, u in bins.items() if b > px_now), key=lambda x: -x[1])[:5]
    below = sorted(((b, u) for b, u in bins.items() if b < px_now), key=lambda x: -x[1])[:5]
    tot_a = sum(u for b, u in bins.items() if b > px_now)
    tot_b = sum(u for b, u in bins.items() if b < px_now)
    return {"px": px_now, "above": above, "below": below, "tot_above": tot_a, "tot_below": tot_b}


def fmt_usd(u):
    return f"${u/1e6:.1f}M" if u >= 1e6 else f"${u/1e3:.0f}k"


if __name__ == "__main__":
    args = sys.argv[1:]
    before_ms = None
    if "--before" in args:
        i = args.index("--before")
        before_ms = calendar.timegm(time.strptime(args[i + 1], "%Y-%m-%dT%H:%M")) * 1000
        args = args[:i] + args[i + 2:]
        print(f"[РЕТРО] карта на момент {time.strftime('%d.%m %H:%M UTC', time.gmtime(before_ms/1000))}")
    for sym in [s.upper() for s in args] or ["GRT"]:
        m = build_magnets(sym, before_ms)
        if not m:
            print(f"{sym}: нет данных OI")
            continue
        px = m["px"]
        bias = "⬆ ВВЕРХ" if m["tot_above"] > m["tot_below"] * 1.3 else \
               "⬇ ВНИЗ" if m["tot_below"] > m["tot_above"] * 1.3 else "≈ баланс"
        print(f"\n🧲 {sym} · цена {px:.6g} · топливо: сверху {fmt_usd(m['tot_above'])} "
              f"/ снизу {fmt_usd(m['tot_below'])} → магнит {bias}")
        print("  ── магниты СВЕРХУ (шорт-ликвидации, топливо роста):")
        for lvl, usd in sorted(m["above"], key=lambda x: x[0]):
            print(f"    {lvl:.6g}  ({(lvl/px-1)*100:+.1f}%)  {fmt_usd(usd)}")
        print("  ── магниты СНИЗУ (лонг-ликвидации, топливо падения):")
        for lvl, usd in sorted(m["below"], key=lambda x: -x[0]):
            print(f"    {lvl:.6g}  ({(lvl/px-1)*100:+.1f}%)  {fmt_usd(usd)}")
