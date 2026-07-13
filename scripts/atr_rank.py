# -*- coding: utf-8 -*-
"""ATR-RANK прототип (13.07, Егор «вытянуть частоту 3%+, 500 пар позволяют»).

Находка ночи: 3%-rate ote_nested 4h_1h МОНОТОНЕН по волатильности пары (<1% риск→16%,
>6%→50%, 5%+→41%), а волатильные НЕДОВЕШЕНЫ (10% потока = половина крупных движений).
Рычаг: ранжировать вселенную по воле, приоритет топ-квартилю.

Прото: (1) 1 batch ticker BingX → вола% всех перпов (24ч range/last = дешёвый ATR-прокси);
(2) ранк; (3) ВАЛИДАЦИЯ — падают ли известные 3%-производители (из БД) в топ-квартиль.
Чистый анализ, ноль живых правок. Тест: python scripts/atr_rank.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import sqlite3
import urllib.request

MIN_VOL_USD = 1_000_000    # ликвидность: не трогаем неторгуемое (слиппедж)


def _rank_universe():
    """→ [(base, vol_pct, qv, chg24)] по vol_pct desc. vol_pct = 24ч range / last."""
    d = json.load(urllib.request.urlopen(
        "https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=15))
    out = []
    for t in (d.get("data") or []):
        s = str(t.get("symbol", ""))
        if not s.endswith("-USDT"):
            continue
        try:
            hi, lo = float(t["highPrice"]), float(t["lowPrice"])
            last, qv = float(t["lastPrice"]), float(t.get("quoteVolume") or 0)
            chg = float(t.get("priceChangePercent") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if last <= 0 or qv < MIN_VOL_USD or hi <= lo:
            continue
        out.append((s[:-5], (hi - lo) / last * 100, qv, chg))
    out.sort(key=lambda x: -x[1])
    return out


def main():
    ranked = _rank_universe()
    n = len(ranked)
    q = n // 4
    print(f"=== ATR-RANK: {n} ликвидных перпов (объём>=${MIN_VOL_USD/1e6:.0f}M), вола=24ч range/last")
    print(f"\nТОП-15 по волатильности (кандидаты 3%+):")
    for base, vp, qv, chg in ranked[:15]:
        print(f"  {base:12} вола {vp:5.1f}% · Δ24ч {chg:+6.1f}% · объём ${qv/1e6:5.1f}M")
    top_q = {b for b, *_ in ranked[:q]}
    print(f"\nквартили по воле: топ-25%={ranked[q-1][1]:.1f}%+ · медиана={ranked[n//2][1]:.1f}% · низ-25%<{ranked[3*q][1]:.1f}%")

    # ВАЛИДАЦИЯ: известные 3%-производители из БД → в топ-квартиле?
    try:
        c = sqlite3.connect("subscriptions.db")
        rows = c.execute("""SELECT symbol, actual_entry_price, entry_price, original_sl, stop_loss,
          max_R_possible, features_json FROM simulated_trades WHERE signal_type='ote_nested'
          AND status IN ('SL','TP','TSL','EXPIRED') AND max_R_possible IS NOT NULL
          AND created_at>='2026-06-15'""").fetchall()
        big_syms = {}
        for sym, ae, e0, osl, sl0, mr, fj in rows:
            f = json.loads(fj or "{}")
            if f.get("ote_setup_id") != "4h_1h_pull":
                continue
            e = float(ae or e0 or 0); sl = float(osl or sl0 or 0)
            if e <= 0 or sl <= 0:
                continue
            if float(mr) * abs(e - sl) / e * 100 >= 3:
                b = sym.split("/")[0]
                big_syms[b] = big_syms.get(b, 0) + 1
        c.close()
        # доля 3%-движений на парах топ-квартиля vs остальных
        in_top = sum(v for b, v in big_syms.items() if b in top_q)
        tot = sum(big_syms.values())
        cover = sum(1 for b in big_syms if b in top_q)
        print(f"\n=== ВАЛИДАЦИЯ (3%+ движения 4h_1h из БД):")
        print(f"  всего 3%+ движений: {tot} на {len(big_syms)} парах")
        print(f"  из них на парах ТОП-25% по воле СЕЙЧАС: {in_top} ({100*in_top/max(tot,1):.0f}%)")
        print(f"  (вола дрейфует — часть прошлых движений на парах, ныне остывших; знак связи важен)")
        # текущие горячие 3%-кандидаты = топ-вола ∩ были продуктивны
        hot3 = [(b, big_syms.get(b, 0)) for b, *_ in ranked[:q] if b in big_syms]
        print(f"\n  🎯 СЕЙЧАС волатильны И исторически давали 3%+ ({len(hot3)} пар):")
        for b, cnt in sorted(hot3, key=lambda x: -x[1])[:12]:
            print(f"    {b:12} прошлых 3%+: {cnt}")
    except Exception as ex:
        print(f"[ATR-RANK] валидация: {ex}")


if __name__ == "__main__":
    main()
