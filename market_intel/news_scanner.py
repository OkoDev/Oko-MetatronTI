"""market_intel/news_scanner.py — авто-сбор заголовков из соцсетей и новостей.

Источники: CryptoPanic (бесплатный API) + CoinTelegraph RSS + декодированные твиты.
Без API-ключей. Публичные RSS/бесплатные эндпоинты.

Использование:
    python market_intel/news_scanner.py              # все источники
    python market_intel/news_scanner.py --limit 10   # топ-10 заголовков
"""
import sys, os, argparse, json, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════════════
# Источники
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_cryptopanic(limit=20):
    """CryptoPanic бесплатный RSS (новости + соцсети)."""
    try:
        url = "https://cryptopanic.com/api/v1/posts/?auth_token=&public=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for post in data.get("results", [])[:limit]:
            results.append({
                "title": post.get("title", ""),
                "source": post.get("domain", "cryptopanic"),
                "votes": post.get("votes", {}).get("total", 0),
                "url": post.get("url", ""),
                "published": post.get("published_at", ""),
            })
        return results
    except Exception as e:
        return [{"error": f"CryptoPanic: {e}"}]


def fetch_cointelegraph(limit=10):
    """CoinTelegraph RSS."""
    try:
        url = "https://cointelegraph.com/rss"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = ET.parse(resp)
        results = []
        for item in tree.findall(".//item")[:limit]:
            results.append({
                "title": item.find("title").text if item.find("title") is not None else "",
                "source": "CoinTelegraph",
                "url": item.find("link").text if item.find("link") is not None else "",
                "published": item.find("pubDate").text if item.find("pubDate") is not None else "",
            })
        return results
    except Exception as e:
        return [{"error": f"CoinTelegraph: {e}"}]


def fetch_decrypt(limit=10):
    """Decrypt RSS."""
    try:
        url = "https://decrypt.co/feed"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = ET.parse(resp)
        results = []
        for item in tree.findall(".//item")[:limit]:
            results.append({
                "title": item.find("title").text if item.find("title") is not None else "",
                "source": "Decrypt",
                "url": item.find("link").text if item.find("link") is not None else "",
                "published": item.find("pubDate").text if item.find("pubDate") is not None else "",
            })
        return results
    except Exception as e:
        return [{"error": f"Decrypt: {e}"}]


def fetch_fear_greed():
    """Fear & Greed Index."""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        item = data["data"][0]
        return {
            "value": int(item["value"]),
            "classification": item["value_classification"],
            "timestamp": item["timestamp"],
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Ключевые слова
# ═══════════════════════════════════════════════════════════════════════════════

KEYWORDS = [
    "fed", "fomc", "rate hike", "rate cut", "inflation", "cpi",
    "sec", "etf", "bitcoin etf", "regulation", "ban",
    "hack", "exploit", "liquidation", "crash", "dump",
    "binance", "coinbase", "bybit", "bingx",
    "xlm", "stellar", "xrp", "ripple", "solana", "ethereum",
]


def filter_relevant(articles):
    """Отбирает статьи по ключевым словам."""
    relevant = []
    for a in articles:
        title = a.get("title", "").lower()
        if any(kw in title for kw in KEYWORDS):
            relevant.append(a)
    return relevant


# ═══════════════════════════════════════════════════════════════════════════════

def print_report(articles, fear_greed, limit):
    print(f"\\n{'='*60}")
    print(f"  NEWS SCANNER  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    if isinstance(fear_greed, dict) and "value" in fear_greed:
        fg = fear_greed
        print(f"\\n  Fear & Greed: {fg['value']} — {fg['classification']}")

    if not articles:
        print("\\n  Нет статей.")
        return

    relevant = filter_relevant(articles)
    print(f"\\n  Всего: {len(articles)} статей, релевантных: {len(relevant)}")
    print(f"\\n  {'─'*55}")

    for i, a in enumerate(relevant[:limit]):
        src = a.get("source", "?")[:15]
        title = a.get("title", "")[:80]
        votes = a.get("votes", "")
        extra = f"  [{votes} votes]" if votes else ""
        print(f"  {i+1:2d}. [{src:15s}] {title}{extra}")

    print(f"\\n{'='*60}\\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15, help="Max headlines")
    args = ap.parse_args()

    all_articles = []

    # CryptoPanic (агрегатор — новости + твиты + реддит)
    print("  Fetching CryptoPanic...")
    cp = fetch_cryptopanic(limit=30)
    if cp and "error" not in cp[0]:
        all_articles += cp
    else:
        print(f"    {cp[0].get('error', 'no data')}")

    # CoinTelegraph
    print("  Fetching CoinTelegraph...")
    ct = fetch_cointelegraph(limit=10)
    if ct and "error" not in ct[0]:
        all_articles += ct

    # Decrypt
    print("  Fetching Decrypt...")
    dc = fetch_decrypt(limit=10)
    if dc and "error" not in dc[0]:
        all_articles += dc

    # Fear & Greed
    print("  Fetching Fear & Greed...")
    fg = fetch_fear_greed()

    print_report(all_articles, fg, args.limit)


if __name__ == "__main__":
    main()
