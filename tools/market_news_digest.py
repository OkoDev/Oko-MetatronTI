#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""market_news_digest — пульс рынка: Fear&Greed + BTC/ETH динамика + крипто-новости (RSS).

Зачем: понять КОНТЕКСТ колбаса (геополитика/ФРС/ETF-отток/ликвидации), а не гадать.
Связь с торговлей: медвежий макро → SHORT-смещение (wave_smc WR72%), btc_gate блок LONG.

Источники (БЕЗ ключей):
  - Fear & Greed Index — alternative.me (публичный API)
  - BTC/ETH цена + 24h — ccxt (bingx)
  - Новости — RSS CoinDesk / Cointelegraph (фильтр по триггер-словам)

Опционально (если есть ключ в .env): CRYPTOPANIC_TOKEN — агрегатор с тональностью.

Использование:
  python tools/market_news_digest.py              # полный дайджест
  python tools/market_news_digest.py --tts         # + озвучка итога (Pavel)
  python tools/market_news_digest.py --hours 12    # новости за N часов (default 24)
"""
import sys, os, argparse, datetime as dt
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import requests
import xml.etree.ElementTree as ET

# триггер-слова (медвежьи / бычьи / нейтрально-важные) — что реально двигает рынок
TRIGGERS = {
    "🔴 риск": ["crash", "plunge", "plummet", "selloff", "sell-off", "liquidation", "liquidated",
                "dump", "tumble", "slump", "fear", "outflow", "war", "iran", "israel", "conflict",
                "sanction", "hack", "exploit", "ban", "lawsuit", "sec ", "default", "recession"],
    "🟢 рост": ["surge", "rally", "soar", "breakout", "all-time high", "ath", "inflow", "approval",
               "etf approv", "halving", "bull", "pump", "adoption", "institutional buy"],
    "🟡 макро": ["fed", "fomc", "rate cut", "rate hike", "inflation", "cpi", "dollar", "dxy",
                "powell", "treasury", "jobs report", "gdp", "tariff"],
}
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]
UA = {"User-Agent": "Mozilla/5.0 (market-digest)"}


def fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=10).json()
        d = r["data"]
        now, prev = int(d[0]["value"]), int(d[1]["value"])
        cls = d[0]["value_classification"]
        arrow = "↑" if now > prev else ("↓" if now < prev else "→")
        return f"{now}/100 ({cls}) {arrow} вчера {prev}"
    except Exception as e:
        return f"н/д ({str(e)[:30]})"


def market_snapshot():
    try:
        import ccxt
        ex = ccxt.bingx()
        out = []
        for sym in ["BTC", "ETH"]:
            t = ex.fetch_ticker(f"{sym}/USDT:USDT")
            ch = t.get("percentage")
            px = t.get("last")
            out.append(f"{sym} ${px:,.0f} ({ch:+.1f}% 24ч)" if ch is not None else f"{sym} ${px:,.0f}")
        return "  ·  ".join(out)
    except Exception as e:
        return f"н/д ({str(e)[:30]})"


def fetch_rss(name, url, since_hours):
    items = []
    try:
        raw = requests.get(url, headers=UA, timeout=12).content
        root = ET.fromstring(raw)
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            pub = it.findtext("pubDate") or ""
            ts = None
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    ts = dt.datetime.strptime(pub, fmt); break
                except Exception:
                    continue
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            if ts is None or ts >= cutoff:
                items.append((title, name, ts))
    except Exception:
        pass
    return items


def classify(title):
    tl = title.lower()
    hits = []
    for tag, words in TRIGGERS.items():
        if any(w in tl for w in words):
            hits.append(tag)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--tts", action="store_true")
    a = ap.parse_args()

    print("=" * 60)
    print(f"🗞️  ПУЛЬС РЫНКА  ·  {dt.datetime.now():%Y-%m-%d %H:%M}  ·  новости за {a.hours}ч")
    print("=" * 60)
    fg = fear_greed()
    snap = market_snapshot()
    print(f"😱 Fear&Greed: {fg}")
    print(f"📊 Рынок: {snap}")
    print("-" * 60)

    # собрать новости со всех фидов
    allnews = []
    for name, url in RSS_FEEDS:
        allnews += fetch_rss(name, url, a.hours)
    # только с триггерами, дедуп по заголовку
    seen = set(); triggered = []
    for title, src, ts in allnews:
        if not title or title in seen:
            continue
        seen.add(title)
        hits = classify(title)
        if hits:
            triggered.append((title, src, ts, hits))
    # сортировка: риск > макро > рост, потом свежесть
    order = {"🔴 риск": 0, "🟡 макро": 1, "🟢 рост": 2}
    triggered.sort(key=lambda x: (min(order.get(h, 9) for h in x[3]), -(x[2].timestamp() if x[2] else 0)))

    if not triggered:
        print(f"📭 Триггерных новостей за {a.hours}ч не найдено (всего собрано {len(allnews)})")
    else:
        print(f"🔔 ТРИГГЕРНЫЕ НОВОСТИ ({len(triggered)} из {len(allnews)} собранных):\n")
        for title, src, ts, hits in triggered[:15]:
            tg = " ".join(dict.fromkeys(h.split()[0] for h in hits))  # emoji-теги
            tstr = ts.strftime("%d.%m %H:%M") if ts else "—"
            print(f"  {tg}  [{src} · {tstr}]")
            print(f"      {title}\n")

    # сводка по тональности
    cnt = {"🔴": 0, "🟢": 0, "🟡": 0}
    for *_, hits in triggered:
        for h in hits:
            e = h.split()[0]
            if e in cnt:
                cnt[e] += 1
    bias = ("МЕДВЕЖИЙ 🔴" if cnt["🔴"] > cnt["🟢"] else
            "БЫЧИЙ 🟢" if cnt["🟢"] > cnt["🔴"] else "СМЕШАННЫЙ 🟡")
    print("-" * 60)
    print(f"⚖️  Тональность новостей: риск={cnt['🔴']} рост={cnt['🟢']} макро={cnt['🟡']} → НАСТРОЙ: {bias}")
    print(f"💡 Торговля: {'медвежий → SHORT-смещение приоритет, btc_gate блок LONG' if cnt['🔴']>cnt['🟢'] else 'бычий → LONG-сетапы, но проверь BTC' if cnt['🟢']>cnt['🔴'] else 'смешанно → ждать ясности старших ТФ'}")
    print("=" * 60)

    if a.tts:
        txt = (f"Пульс рынка. Индекс страха и жадности {fg.split('(')[0]}. "
               f"Настрой новостей {bias.split()[0]}. "
               f"{'Медвежий, шорт в приоритете.' if cnt['🔴']>cnt['🟢'] else 'Бычий, лонг сетапы.' if cnt['🟢']>cnt['🔴'] else 'Смешанный, ждём ясности.'}")
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$s.SelectVoice('Microsoft Irina Desktop'); $s.Volume=0; $s.Speak('.'); $s.Volume=100; "
              f"$s.SelectVoice('Microsoft Pavel'); $s.Speak('{txt}')")
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)


if __name__ == "__main__":
    main()
