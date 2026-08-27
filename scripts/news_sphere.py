# -*- coding: utf-8 -*-
"""НОВОСТНАЯ СФЕРА (Сфера Контекста) — MVP (08.07, запрос Егора «агрегатор: геополитика,
соцсети, макро — понимать ПОЧЕМУ рынок двигается и что нависает»).

Пайплайн (цикл 30 мин):
  RSS (CoinDesk/Cointelegraph/CryptoSlate + Google News гео/макро) → дедуп (news_items,
  external_data.db) → классификация qwen3:8b ЛОКАЛЬНО (Ollama, think:false, JSON:
  category/tone/importance/assets/summary_ru) →
    importance >= 8  → немедленно 🗞️ в ACTION-канал
    остальное        → копится; раз в DIGEST_EVERY_H часов сводка топ-5 в FEED-канал.

LLM = локальная (бесплатно, без лимитов; ~5 ток/с хватает: 10-20 новостей/цикл по ~30с).
Правило эксплуатации: модель на 1080 (ollama GPU-баг #9722) — дайджесты фоновые, не при монтаже.
Reuse: oko_feed.store.conn (дедуп/копилка), oko_feed.alerts.send_tg (русла), RSS-фиды из
tools/market_news_digest.py. Fear&Greed в сводке.

pm2: pm2 start scripts/news_sphere.py --name news-sphere --interpreter <python>  (см. bot_pm2.js паттерн)
Тест: python scripts/news_sphere.py --once   (один цикл без ожидания)
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from oko_feed.store import conn
from oko_feed.alerts import send_tg

CYCLE_SEC = 30 * 60
DIGEST_EVERY_H = 4
URGENT_IMPORTANCE = 8           # 09.07: 9 прятал атаки по Ирану/ФРС на 4ч в дайджест (Егор);
                                # мусор-8 отсеивают self-check + дедуп похожих (_is_dup)
MAX_AGE_H = 48                  # фиды подмешивают СТАРЬЁ (Decrypt отдал новость 1.5-летней давности)
MAX_LLM_PER_CYCLE = 20          # защита от лавины на холодном старте
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "oko-analyst"           # 08.07 «прошивка»: qwen3:8b + SYSTEM-правила (oko_analyst.Modelfile)

FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("TheBlock", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Blockworks", "https://blockworks.co/feed"),
    ("BitcoinMag", "https://bitcoinmagazine.com/feed"),
    ("CNBC-Markets", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    # гео/макро контекст (запрос Егора: конфликты, климат, мировые рынки)
    ("GoogleNews-Geo", "https://news.google.com/rss/search?q=geopolitics+OR+conflict+markets&hl=en-US&gl=US&ceid=US:en"),
    ("GoogleNews-Macro", "https://news.google.com/rss/search?q=fed+OR+inflation+OR+recession+markets&hl=en-US&gl=US&ceid=US:en"),
    # толпа/сентимент (замена CryptoPanic — тот закрыл free-тир 04.2026, $50/нед — скип)
    ("Reddit-Crypto", "https://www.reddit.com/r/CryptoCurrency/top/.rss?t=day&limit=15"),
]
CRYPTOPANIC = "https://cryptopanic.com/api/v1/posts/?auth_token={key}&public=true"   # слой 4
FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"              # слой 2
UA = {"User-Agent": "Mozilla/5.0 (oko-news-sphere)"}

PROMPT = """Ты — строгий новостной аналитик крипторынка. Классифицируй новость, ответь ТОЛЬКО валидным JSON без пояснений:
{"category": "геополитика|макро|регуляция|крипто|технологии|климат|прочее", "tone": "bullish|bearish|neutral", "importance": 1-10, "assets": [...], "summary_ru": "одно предложение по-русски"}

Критерии importance (СТРОГО):
- 9-10: ПОДТВЕРЖДЁННОЕ событие, двигающее ВЕСЬ рынок ПРЯМО СЕЙЧАС: война, решение ФРС, крах крупной биржи, запрет/одобрение крипты в США/ЕС/Китае.
- 6-8: подтверждённое заметное событие (крупный хак, листинг/делистинг мейджора, важный регуляторный шаг).
- 1-5: ВСЁ остальное — обзоры, прогнозы, мнения, «аналитики считают», реклама, мелкие проекты.
Прогноз/мнение/обзор НИКОГДА не выше 5. ДВИЖЕНИЕ ЦЕН само по себе («акции растут», «нефть упала», «доллар укрепился») — это ФОН, importance ≤ 4; событие = конкретный ФАКТ (решение регулятора, атака, банкротство, закон, взлом). assets: ТОЛЬКО тикеры, явно названные в тексте (не выдумывай). summary_ru: только факты из текста, без домыслов; НЕ выдумывай причинность, которой нет в тексте. Географические названия переводи ТОЧНО (Gulf = Персидский залив); не уверен — оставь по-английски.

Примеры (few-shot):
Новость: «Fed cuts rates by 50bps in emergency meeting» → {"category":"макро","tone":"bullish","importance":10,"assets":[],"summary_ru":"ФРС экстренно снизила ставку на 50 б.п."}
Новость: «Analyst predicts Bitcoin could reach $150K by year end» → {"category":"крипто","tone":"neutral","importance":3,"assets":["BTC"],"summary_ru":"Аналитик прогнозирует рост биткоина к концу года — мнение, не событие."}
Новость: «Top 5 altcoins to watch this week» → {"category":"прочее","tone":"neutral","importance":1,"assets":[],"summary_ru":"Обзорная подборка альткоинов — не событие."}

{prices}
Новость: «{title}»"""


def _price_context() -> str:
    """Прайс-grounding: реальные цены мейджоров в промпт — старьё/бред модель видит сама
    (лечит класс «BTC $96,750 из 2024 ушёл алертом 9/10»)."""
    try:
        d = json.loads(_get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd"))
        return (f"Текущие цены (для сверки актуальности): BTC=${d['bitcoin']['usd']:,.0f}, "
                f"ETH=${d['ethereum']['usd']:,.0f}, SOL=${d['solana']['usd']:,.0f}")
    except Exception:
        return ""


def _get(url: str, timeout: int = 20) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def fetch_rss() -> list[dict]:
    out = []
    def _ts_rfc822(s):
        try:
            from email.utils import parsedate_to_datetime
            return int(parsedate_to_datetime(s).timestamp())
        except Exception:
            return None

    def _ts_iso(s):
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None

    for src, url in FEEDS:
        try:
            root = ET.fromstring(_get(url))
            for item in root.iter("item"):                       # RSS 2.0
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title and link:
                    out.append({"source": src, "title": title[:300], "link": link[:500],
                                "ts_pub": _ts_rfc822(item.findtext("pubDate") or "")})
            ns_atom = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(f"{ns_atom}entry"):           # Atom (Reddit и др.)
                title = (entry.findtext(f"{ns_atom}title") or "").strip()
                le = entry.find(f"{ns_atom}link")
                link = (le.get("href") if le is not None else "").strip()
                if title and link:
                    ts = (_ts_iso(entry.findtext(f"{ns_atom}published") or "")
                          or _ts_iso(entry.findtext(f"{ns_atom}updated") or ""))
                    out.append({"source": src, "title": title[:300], "link": link[:500],
                                "ts_pub": ts})
        except Exception as e:
            print(f"[NEWS] {src} fetch err: {e}")
    # слой 4: CryptoPanic (агрегатор сотен источников + голоса). Ключ опционален
    # (.env CRYPTOPANIC_TOKEN, free-тир); без ключа пробуем public-режим.
    try:
        import os
        key = os.environ.get("CRYPTOPANIC_TOKEN", "")
        if not key:
            try:
                for ln in open(".env", encoding="utf-8"):
                    if ln.startswith("CRYPTOPANIC_TOKEN="):
                        key = ln.split("=", 1)[1].strip()
                        break
            except Exception:
                pass
        if key:                                       # free-тир закрыт 04.2026 — только с платным токеном
            data = json.loads(_get(CRYPTOPANIC.replace("{key}", key))) if key else {}
            for post in (data.get("results") or [])[:30]:
                title = (post.get("title") or "").strip()
                link = (post.get("url") or "").strip()
                if title and link:
                    out.append({"source": f"CPanic/{post.get('domain', '?')}",
                                "title": title[:300], "link": link[:500]})
    except Exception as e:
        print(f"[NEWS] CryptoPanic err: {e}")
    return out


def upcoming_high_impact(hours: float = 48.0) -> list[dict]:
    """📅 Слой 2: High-impact события эконом-календаря (ForexFactory JSON, бесплатный)
    на ближайшие N часов — «что НАВИСАЕТ» (запрос Егора: знать заранее, не пост-фактум)."""
    try:
        events = json.loads(_get(FF_CALENDAR))
    except Exception as e:
        print(f"[NEWS] calendar err: {e}")
        return []
    out = []
    now = time.time()
    for ev in events:
        if str(ev.get("impact", "")).lower() != "high":
            continue
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(str(ev.get("date"))).timestamp()
        except Exception:
            continue
        dh = (ts - now) / 3600
        if 0 <= dh <= hours:
            out.append({"title": ev.get("title"), "country": ev.get("country"),
                        "in_hours": round(dh, 1), "ts": int(ts)})
    return sorted(out, key=lambda x: x["in_hours"])


def _onchain_block(c, hours: int) -> list[str]:
    """⛓ On-chain отжим для сводки (Егор 08.07: «выжимать можем много, но не делаем»):
    киты Uniswap + BTC-флоу + синтетические ликвидации из НАШИХ копилок."""
    since = int(time.time()) - hours * 3600
    lines = []
    try:
        n, usd = c.execute("SELECT COUNT(*), COALESCE(SUM(amount_usd),0) FROM onchain_events "
                           "WHERE kind='whale_swap' AND ts>?", (since,)).fetchone()
        if n:
            lines.append(f"🐋 киты Uniswap: {n} свопов на ${usd/1e6:.1f}M")
        inf = c.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                        "WHERE kind='btc_inflow' AND ts>?", (since,)).fetchone()[0]
        outf = c.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                         "WHERE kind='btc_outflow' AND ts>?", (since,)).fetchone()[0]
        if inf or outf:
            net = outf - inf
            lines.append(f"₿ флоу: net {net:+.0f} BTC ({'в холд' if net > 0 else 'на биржи'})")
        row = c.execute("SELECT COUNT(*), COALESCE(SUM(usd),0) FROM liq_events WHERE ts>?",
                        (since,)).fetchone()
        if row and row[0]:
            lines.append(f"💥 ликвидации: {row[0]} событий ≈ ${row[1]/1e6:.1f}M")
    except Exception:
        pass
    return lines


_PRICE_CTX = ""                 # кэш прайс-контекста на цикл (CG дёргаем 1 раз, не на новость)

VERIFY_PROMPT = """Ты — вторая линия контроля. Первый аналитик оценил новость как КРИТИЧЕСКИ ВАЖНУЮ ({imp}/10). Перепроверь СТРОГО по правилам: 8-10 = ТОЛЬКО подтверждённое СОБЫТИЕ-факт, двигающее весь рынок прямо сейчас (война/атака, решение ФРС, крах биржи, запрет/одобрение крипты в США/ЕС/Китае). Прогноз/мнение/обзор/старая новость — НЕ критично. ДВИЖЕНИЕ ЦЕН само по себе («рынок растёт», «нефть падает», «доллар укрепился») — ФОН, НЕ критично, даже если рядом упомянут конфликт.
{prices}
Новость: «{title}»
Ответь ТОЛЬКО JSON: {"confirm": true|false, "reason_ru": "одно предложение"}"""


_SENT_CACHE: list = []          # [(ts, set(слов))] отправленных срочных — дедуп похожих тем


def _is_dup(text: str, hours: float = 8.0) -> bool:
    """Дедуп тем (09.07, Егор: «доллар из-за атак» шло дважды): Jaccard слов с уже
    отправленными за N часов > 0.45 → та же тема из другого источника, не слать."""
    now = time.time()
    words = {w.lower().strip('.,!?—:;()«»"') for w in (text or "").split() if len(w) > 3}
    if not words:
        return False
    global _SENT_CACHE
    _SENT_CACHE = [(ts, ws) for ts, ws in _SENT_CACHE if now - ts < hours * 3600]
    for _, ws in _SENT_CACHE:
        j = len(words & ws) / max(1, len(words | ws))
        if j > 0.45:
            return True
    _SENT_CACHE.append((now, words))
    return False


def verify_urgent(title: str, imp: int) -> tuple[bool, str]:
    """Self-check (Егор 08.07 «модель может сама себя перепроверять?!»): кандидат в срочный
    алерт → второй проход-адвокат дьявола. Только подтверждённое уходит в канал."""
    try:
        p = (VERIFY_PROMPT.replace("{imp}", str(imp))
             .replace("{prices}", _PRICE_CTX).replace("{title}", title))
        req = urllib.request.Request(OLLAMA, json.dumps({
            "model": MODEL, "prompt": p, "stream": False, "think": False,
            "options": {"temperature": 0.1, "num_predict": 150},
        }).encode(), {"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=240)).get("response", "")
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        d = json.loads(m.group(0)) if m else {}
        return bool(d.get("confirm")), str(d.get("reason_ru") or "")
    except Exception as e:
        print(f"[NEWS] verify err: {e}")
        return True, ""                               # проверка недоступна → fail-open (не терять событие)


def classify(title: str) -> dict | None:
    try:
        req = urllib.request.Request(OLLAMA, json.dumps({
            "model": MODEL,
            "prompt": PROMPT.replace("{prices}", _PRICE_CTX).replace("{title}", title),
            "stream": False, "think": False,
            "options": {"temperature": 0.1, "num_predict": 250},
        }).encode(), {"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=240)).get("response", "")
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        d["importance"] = int(d.get("importance") or 0)
        return d
    except Exception as e:
        print(f"[NEWS] LLM err: {e}")
        return None


def _ensure(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS news_items (
        link TEXT PRIMARY KEY, ts INTEGER, source TEXT, title TEXT,
        category TEXT, tone TEXT, importance INTEGER, assets TEXT,
        summary_ru TEXT, alerted INTEGER DEFAULT 0, digested INTEGER DEFAULT 0)""")


def fear_greed() -> str:
    try:
        d = json.loads(_get("https://api.alternative.me/fng/?limit=1"))["data"][0]
        return f"F&G {d['value']} ({d['value_classification']})"
    except Exception:
        return ""


def _env_key(name: str) -> str:
    """Ключ из env или .env (standalone-паттерн как у CRYPTOPANIC_TOKEN/alerts)."""
    import os
    v = os.environ.get(name, "")
    if not v:
        try:
            for ln in open(".env", encoding="utf-8"):
                if ln.startswith(f"{name}="):
                    v = ln.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    return v


def _cmc_get(path: str) -> dict:
    """CMC Pro API (ключ Егора 11.07, .env CMC_API_KEY). Роль: фолбэк CG + Fear&Greed."""
    key = _env_key("CMC_API_KEY")
    if not key:
        raise RuntimeError("нет CMC_API_KEY")
    req = urllib.request.Request(f"https://pro-api.coinmarketcap.com{path}",
                                 headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _market_block(c) -> list[str]:
    """🌐 CoinGecko отжим (Егор 08.07 «выжимать будем?!»): global snapshot + trending
    (поисковый хайп ретейла). Trending копится в cg_trending — кросс с радаром
    (trending + OI BUILD = памп-кандидат ДО движения) = следующее ребро.
    11.07: CMC (ключ Егора) = фолбэк global при CG-сбое + Fear&Greed (у CG его нет)."""
    lines = []
    try:
        g = json.loads(_get("https://api.coingecko.com/api/v3/global"))["data"]
        mcap = g["total_market_cap"]["usd"] / 1e12
        chg = g.get("market_cap_change_percentage_24h_usd") or 0
        btc_d = g["market_cap_percentage"]["btc"]
        lines.append(f"рынок ${mcap:.2f}T ({chg:+.1f}%/24ч) · BTC.D {btc_d:.1f}%")
    except Exception as e:
        print(f"[NEWS] CG global err: {e}")
        try:                                    # фолбэк: CMC global-metrics
            d = _cmc_get("/v1/global-metrics/quotes/latest")["data"]
            q = d["quote"]["USD"]
            chg = q.get("total_market_cap_yesterday_percentage_change") or 0
            lines.append(f"рынок ${q['total_market_cap'] / 1e12:.2f}T ({chg:+.1f}%/24ч) "
                         f"· BTC.D {d['btc_dominance']:.1f}% (CMC)")
        except Exception as e2:
            print(f"[NEWS] CMC global err: {e2}")
    try:                                        # Fear&Greed — режимный градусник (CMC)
        fg = _cmc_get("/v3/fear-and-greed/latest")["data"]
        lines.append(f"Fear&Greed {fg['value']} ({fg['value_classification']})")
    except Exception as e:
        print(f"[NEWS] CMC F&G err: {e}")
    try:
        tr = json.loads(_get("https://api.coingecko.com/api/v3/search/trending"))
        coins = [it["item"]["symbol"].upper() for it in (tr.get("coins") or [])[:7]]
        if coins:
            # 09.07 (Егор: «SLX CASHCAT?!»): thrending CG = мем-помойка поиска; показываем
            # ТОРГУЕМЫЕ на фьючах (наш рынок), мемы — счётчиком. В копилку — всё (retail-пульс).
            tradable = [s for s in coins if s in _futures_universe()]
            memes = len(coins) - len(tradable)
            if tradable:
                lines.append("🔥 trending (торгуемые): " + " ".join(tradable)
                             + (f" · +{memes} мем" if memes else ""))
            elif memes:
                lines.append(f"🔥 trending: {memes} мем-тикеров (торгуемых нет) — чистый retail-хайп")
            c.execute("CREATE TABLE IF NOT EXISTS cg_trending (ts INTEGER, coins TEXT)")
            c.execute("INSERT INTO cg_trending VALUES (?, ?)", (int(time.time()), json.dumps(coins)))
            c.commit()
    except Exception as e:
        print(f"[NEWS] CG trending err: {e}")
    return lines


_FUT_CACHE: dict = {"ts": 0.0, "set": set()}


def _futures_universe() -> set:
    """Тикеры Binance USDT-перпов (кэш сутки) — фильтр торгуемости для trending."""
    now = time.time()
    if now - _FUT_CACHE["ts"] < 86400 and _FUT_CACHE["set"]:
        return _FUT_CACHE["set"]
    try:
        info = json.loads(_get("https://fapi.binance.com/fapi/v1/exchangeInfo"))
        syms = {s["baseAsset"].upper().replace("1000", "") for s in info.get("symbols", [])
                if s.get("quoteAsset") == "USDT"}
        _FUT_CACHE.update(ts=now, set=syms)
    except Exception as e:
        print(f"[NEWS] futures universe err: {e}")
    return _FUT_CACHE["set"]


COMPASS_PROMPT = """Ты — главный аналитик крипто-деска. Ниже агрегированная сводка за последние часы.
Дай ОДНУ интерпретацию для трейдера, ответь ТОЛЬКО валидным JSON:
{"bias": "long|short|wait", "confidence": 0-100, "reasoning_ru": "2-4 КОРОТКИХ пункта, КАЖДЫЙ с новой строки, каждый начинается с «• »", "key_risk": "одно предложение: что может сломать сценарий"}
Правила: противоречивые сигналы или мало данных → bias="wait". Скорое high-impact событие (<6ч) → почти всегда "wait" (волатильность). Не выдумывай факты вне сводки.

СВОДКА:
{data}"""


SWARM_CONF_TRIGGER = 50         # локальная уверенность ниже → зовём рой
# 18.08: cerebras заменён на openrouter — его free-tier закрыт (402 на весь каталог),
# фоновый компас месяцами голосовал бы втроём вместо четверых и молча.
# Четыре РАЗНЫХ ключа (groq/gemini/mistral/openrouter) → общий rate-limit никого не роняет.
SWARM_PROVIDERS = ["openrouter", "groq", "gemini", "mistral"]   # быстрые бесплатные голоса


def swarm_compass(data: str) -> dict | None:
    """🐝 COMPASS-SWARM (09.07): спорный вердикт → консилиум внешних LLM (reuse llm_ask,
    как team_ask, но структурное ГОЛОСОВАНИЕ JSON-вердиктами вместо текстового синтеза).
    → {bias, confidence, votes:'short:3/4', detail} или None (рой недоступен/раскол пополам).
    Оба вердикта (локальный и роевой) пишутся в compass_log → форвард покажет кто точнее."""
    try:
        sys.path.insert(0, "tools")
        from llm_ask import load_env, has_key, call_provider
    except ImportError as e:
        print(f"[SWARM] import: {e}")
        return None
    load_env()
    provs = [p for p in SWARM_PROVIDERS if has_key(p)]
    if len(provs) < 2:
        return None
    prompt = COMPASS_PROMPT.replace("{data}", data)
    votes = {}
    import concurrent.futures as cf
    def _one(p):
        try:
            # 1500 ток: thinking-модели (cerebras glm) тратят бюджет на рассуждения ДО JSON
            resp = call_provider(p, prompt, None, 1500, None)
            d = {}
            for cand in re.findall(r"\{[^{}]*\}", resp):   # ПОСЛЕДНИЙ валидный JSON
                try:
                    parsed = json.loads(cand)
                    if "bias" in parsed:
                        d = parsed
                except Exception:
                    continue
            b = str(d.get("bias") or "").lower()
            if b in ("long", "short", "wait"):
                return p, b, int(d.get("confidence") or 0)
            print(f"[SWARM] {p}: JSON с bias не найден ({resp[-80:]!r})")
        except Exception as e:
            print(f"[SWARM] {p}: {str(e)[:80]}")
        return p, None, 0
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for p, b, cf_ in ex.map(_one, provs):
            if b:
                votes[p] = (b, cf_)
    if len(votes) < 2:
        return None
    from collections import Counter
    tally = Counter(b for b, _ in votes.values())
    top, n_top = tally.most_common(1)[0]
    if n_top <= len(votes) / 2:                       # нет большинства → раскол = wait
        top, n_top = "wait", tally.get("wait", 0)
    confs = [cf_ for b, cf_ in votes.values() if b == top]
    return {"bias": top, "confidence": int(sum(confs) / len(confs)) if confs else 0,
            "votes": f"{top}:{n_top}/{len(votes)}",
            "detail": " ".join(f"{p}={b}" for p, (b, _) in votes.items())}


def _inplay_coins(c) -> list[str]:
    """🎯 Монеты 'в игре' СЕЙЧАС из всех сигнальных источников (Егор 25.07 «больше инплей монет»).
    Конфлюэнция внимания: radar(pump/spring/build) + OKO-SM скринер (OTE-зоны) + DC-торговля +
    trending. Больше источников на монету = выше в списке. → строки 'СИМ 🚀🎯...'."""
    import sqlite3 as _sq
    since2 = int(time.time()) - 7200
    coins: dict[str, list[str]] = {}

    def add(sym, tag):
        s = str(sym or "").split("/")[0].split("-")[0].upper().replace("USDT", "").strip()
        if not s:
            return
        coins.setdefault(s, [])
        if tag not in coins[s]:
            coins[s].append(tag)

    # радар (external_data.db = c) — свежие сетапы со стороной
    for tbl, ico, col in (("pump_signals", "🚀", "side"), ("spring_signals", "🌱", "dir"),
                          ("build_signals", "🔨", "side")):
        try:
            for sym, side in c.execute(f"SELECT symbol, {col} FROM {tbl} WHERE ts>?", (since2,)).fetchall():
                arrow = "↑" if str(side or "").upper() in ("BUY", "LONG", "UP") else "↓"
                add(sym, ico + arrow)
        except Exception:
            pass
    # OKO-SM скринер + DC-торговля (subscriptions.db)
    try:
        sc = _sq.connect("subscriptions.db", timeout=5)
        for sym, sco in sc.execute("SELECT symbol, conf_score FROM screener_state WHERE in_zone=1 "
                                   "AND conf_score>=3 ORDER BY conf_score DESC LIMIT 8").fetchall():
            add(sym, f"🎯{sco:.0f}")
        for (sym,) in sc.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE "
                                 "signal_type='ds_advisor' AND status IN ('OPEN','PENDING_ENTRY')").fetchall():
            add(sym, "🤖")
        sc.close()
    except Exception:
        pass
    # trending торгуемые (retail-хайп) — reuse _futures_universe
    try:
        row = c.execute("SELECT coins FROM cg_trending ORDER BY ts DESC LIMIT 1").fetchone()
        if row:
            uni = _futures_universe()
            for sym in json.loads(row[0]):
                if str(sym).upper() in uni:
                    add(sym, "🔥")
    except Exception:
        pass
    ranked = sorted(coins.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [f"{s} {''.join(tags)}" for s, tags in ranked[:10]]


def _rotation_line() -> str | None:
    """🔺 Ротация капитала — self-computed триада (marketcap_engine, MOAT сессии 24.07)."""
    try:
        from core.context.marketcap_engine import rotation_now
        r = rotation_now()
        if r and r.get("verdict"):
            return f"Ротация: {r['verdict']}"
    except Exception:
        pass
    return None


def compass(c) -> None:
    """🧭 ЧАСОВОЙ КОМПАС (Егор 08.07: «не поток, а агрегация и интерпретация — ждём/лонг/шорт»).
    Раз в час: синтез всего (новости+календарь+on-chain+рынок+USDT.D+пульс радара) → один
    вердикт в NEWS. Каждый вердикт → compass_log: форвард-скоринг покажет, угадывает ли."""
    row = c.execute("SELECT ts FROM alert_log WHERE key='compass'").fetchone()
    if row and time.time() - row[0] < 3600:
        return
    since6 = int(time.time()) - 6 * 3600
    parts = []
    # новости 6ч (топ по важности, кратко)
    news = c.execute("SELECT tone, importance, summary_ru FROM news_items WHERE ts>? AND "
                     "importance>=5 ORDER BY importance DESC LIMIT 8", (since6,)).fetchall()
    if news:
        parts.append("Новости 6ч: " + " | ".join(
            f"[{t or '?'}/{i}] {s}" for t, i, s in news if s))
    # календарь 24ч
    cal = upcoming_high_impact(24)
    if cal:
        parts.append("События 24ч: " + "; ".join(
            f"{e['title']}({e['country']}) через {e['in_hours']:.0f}ч" for e in cal[:4]))
    # рынок + толпа
    parts += [f"Рынок: {x}" for x in _market_block(c)]
    fg = fear_greed()
    if fg:
        parts.append(fg)
    # USDT.D режим (reuse ряда)
    try:
        from core.signals.usdtd_regime import _series, _MA_LEN
        import sqlite3 as _sq
        uc = _sq.connect("ohlcv_cache.db")
        ser = _series(uc)
        uc.close()
        vals = [v for _, v in ser]
        ma = sum(vals[-_MA_LEN:]) / _MA_LEN
        parts.append(f"USDT.D {vals[-1]:.2f}% vs MA20 {ma:.2f}% → "
                     f"{'risk-OFF (медвежье альтам)' if vals[-1] > ma else 'risk-on'}")
    except Exception:
        pass
    # пульс радара 1ч (из копилок)
    since1 = int(time.time()) - 3600
    try:
        sq_up = c.execute("SELECT COUNT(*) FROM liq_events WHERE ts>? AND side='SELL'", (since1,)).fetchone()[0]
        sq_dn = c.execute("SELECT COUNT(*) FROM liq_events WHERE ts>? AND side='BUY'", (since1,)).fetchone()[0]
        bld = c.execute("SELECT COUNT(*) FROM build_signals WHERE ts>?", (since1,)).fetchone()[0]
        pmp = c.execute("SELECT COUNT(*) FROM pump_signals WHERE ts>?", (since1,)).fetchone()[0]
        parts.append(f"Радар 1ч: ликвидации шортов {sq_up} / лонгов {sq_dn}, BUILD {bld}, PUMP/DUMP {pmp}")
    except Exception:
        pass
    # 🔺 ротация капитала (self-computed триада — MOAT)
    _rot = _rotation_line()
    if _rot:
        parts.append(_rot)
    # 🎯 монеты в игре (Егор 25.07) — в LLM-контекст (пусть биас учитывает) + в сообщение
    inplay = _inplay_coins(c)
    if inplay:
        parts.append("В игре сейчас (радар/скринер/DC/trending): " + ", ".join(inplay))
    if len(parts) < 2:
        return
    data = "\n".join(f"- {p}" for p in parts)
    try:
        # компас ДУМАЕТ (qwen3 hybrid-thinking, Егор 08.07): раз в час можно позволить
        # 1-2 мин размышлений — синтез противоречивых данных именно там, где reasoning
        # даёт качество. Массовая классификация остаётся think:false (скорость).
        req = urllib.request.Request(OLLAMA, json.dumps({
            "model": MODEL, "prompt": COMPASS_PROMPT.replace("{data}", data),
            "stream": False, "think": True,
            "options": {"temperature": 0.2, "num_predict": 1200},
        }).encode(), {"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=300)).get("response", "")
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        d = json.loads(m.group(0)) if m else {}
    except Exception as e:
        print(f"[COMPASS] LLM err: {e}")
        return
    bias = str(d.get("bias") or "wait").lower()
    conf = int(d.get("confidence") or 0)
    icon = {"long": "🟢 ЛОНГ-склонность", "short": "🔴 ШОРТ-склонность"}.get(bias, "⏳ ЖДЁМ")
    # 🐝 спорный вердикт (conf < порога) → рой-консилиум; оба вердикта в лог (кто точнее?)
    swarm = None
    if conf < SWARM_CONF_TRIGGER:
        swarm = swarm_compass(data)
        if swarm:
            print(f"[SWARM] локалка {bias}/{conf}% vs рой {swarm['votes']} ({swarm['detail']})")
    c.execute("""CREATE TABLE IF NOT EXISTS compass_log (
        ts INTEGER PRIMARY KEY, bias TEXT, confidence INTEGER, reasoning TEXT)""")
    for _mig in ("ALTER TABLE compass_log ADD COLUMN swarm_bias TEXT",
                 "ALTER TABLE compass_log ADD COLUMN swarm_conf INTEGER",
                 "ALTER TABLE compass_log ADD COLUMN swarm_votes TEXT"):
        try:
            c.execute(_mig)
        except Exception:
            pass
    prev = c.execute("SELECT bias, confidence FROM compass_log ORDER BY ts DESC LIMIT 1").fetchone()
    c.execute("INSERT OR REPLACE INTO compass_log(ts, bias, confidence, reasoning, "
              "swarm_bias, swarm_conf, swarm_votes) VALUES (?,?,?,?,?,?,?)",
              (int(time.time()), bias, conf, d.get("reasoning_ru"),
               (swarm or {}).get("bias"), (swarm or {}).get("confidence"),
               (swarm or {}).get("votes")))
    # 09.07 (Егор: «одно и то же каждый час»): в КАНАЛ — только при ИЗМЕНЕНИИ
    # (bias сменился или |Δconf|>=15) или раз в 3ч (жив-маркер). В compass_log — всегда (скоринг).
    changed = prev is None or prev[0] != bias or abs(int(prev[1] or 0) - conf) >= 15
    sent_row = c.execute("SELECT ts FROM alert_log WHERE key='compass_sent'").fetchone()
    stale = (not sent_row) or (time.time() - sent_row[0] >= 3 * 3600)
    if changed or stale:
        flip = "" if prev is None or prev[0] == bias else f" (был: {prev[0].upper()})"
        sw_line = ""
        if swarm:
            sw_icon = {"long": "🟢", "short": "🔴"}.get(swarm["bias"], "⏳")
            sw_line = (f"\n🐝 <b>Консилиум:</b> {sw_icon} {swarm['bias'].upper()} "
                       f"{swarm['votes'].split(':')[1]} голосов · {swarm['confidence']}%")
        _rot_block = f"\n🔺 <b>{_rot}</b>" if _rot else ""
        _ip_block = ("\n\n🎯 <b>В ИГРЕ</b> (радар🚀🌱🔨 · OTE🎯 · DC🤖 · хайп🔥):\n"
                     + "\n".join(f"• <code>{x}</code>" for x in inplay)) if inplay else ""
        send_tg(f"🧭 <b>КОМПАС: {icon}</b> · {conf}%{flip}{_rot_block}\n\n"
                f"{d.get('reasoning_ru') or ''}{sw_line}{_ip_block}\n\n"
                f"⚠️ <b>Риск:</b> {d.get('key_risk') or '—'}\n\n#COMPASS", channel="news")
        c.execute("INSERT OR REPLACE INTO alert_log VALUES ('compass_sent', ?)", (int(time.time()),))
    c.execute("INSERT OR REPLACE INTO alert_log VALUES ('compass', ?)", (int(time.time()),))
    c.commit()


def cycle() -> None:
    global _PRICE_CTX
    _PRICE_CTX = _price_context()
    c = conn()
    try:
        _ensure(c)
        fresh, stale = [], []
        now_ts = time.time()
        for it in fetch_rss():
            if c.execute("SELECT 1 FROM news_items WHERE link=?", (it["link"],)).fetchone():
                continue
            ts_pub = it.get("ts_pub")
            # фиды подмешивают СТАРЬЁ (Decrypt: BTC $96k из 2024 ушёл алертом 9/10) —
            # старше MAX_AGE_H в LLM не пускаем (в БД пишем для дедупа)
            if ts_pub is not None and now_ts - ts_pub > MAX_AGE_H * 3600:
                stale.append(it)
            else:
                fresh.append(it)
        for it in stale:
            c.execute("INSERT OR IGNORE INTO news_items(link, ts, source, title, importance) "
                      "VALUES (?,?,?,?,0)", (it["link"], int(time.time()), it["source"], it["title"]))
        if stale:
            print(f"[NEWS] старьё мимо LLM: {len(stale)}")
        # холодный старт: не гнать сотни старых заголовков через LLM
        todo, skip = fresh[:MAX_LLM_PER_CYCLE], fresh[MAX_LLM_PER_CYCLE:]
        for it in skip:                              # записать без классификации (дедуп на будущее)
            c.execute("INSERT OR IGNORE INTO news_items(link, ts, source, title, importance) "
                      "VALUES (?,?,?,?,0)", (it["link"], int(time.time()), it["source"], it["title"]))
        print(f"[NEWS] новых {len(fresh)} (LLM: {len(todo)}, мимо: {len(skip)})")
        for it in todo:
            d = classify(it["title"]) or {}
            imp = int(d.get("importance") or 0)
            c.execute("INSERT OR IGNORE INTO news_items(link, ts, source, title, category, tone, "
                      "importance, assets, summary_ru) VALUES (?,?,?,?,?,?,?,?,?)",
                      (it["link"], int(time.time()), it["source"], it["title"],
                       d.get("category"), d.get("tone"), imp,
                       json.dumps(d.get("assets") or [], ensure_ascii=False), d.get("summary_ru")))
            c.commit()
            if imp >= URGENT_IMPORTANCE:
                if _is_dup(d.get("summary_ru") or it["title"]):
                    print(f"[NEWS] дубль темы — скип: {it['title'][:70]}")
                    continue
                ok_v, why = verify_urgent(it["title"], imp)
                if not ok_v:
                    print(f"[NEWS] self-check ОТКЛОНИЛ ({why}): {it['title'][:70]}")
                    continue
                tone_dot = {"bearish": "🔴", "bullish": "🟢"}.get(str(d.get("tone")), "⚪")
                if send_tg(f"🗞️ <b>ВАЖНАЯ НОВОСТЬ</b> [{d.get('category')}] {tone_dot} {imp}/10 ✓✓\n\n"
                           f"{d.get('summary_ru') or it['title']}\n"
                           f"активы: {', '.join(d.get('assets') or []) or '—'}\n\n"
                           f'<a href="{it["link"]}">{it["source"]}</a>\n\n#NEWS', channel="news"):
                    c.execute("UPDATE news_items SET alerted=1 WHERE link=?", (it["link"],))
                    c.commit()
        # 📨 TG-посты сборщика (tg_collector, папка Егора) → та же LLM-труба (остаток бюджета)
        tg_budget = max(0, MAX_LLM_PER_CYCLE - len(todo))
        try:
            rows_tg = c.execute("SELECT channel_id, msg_id, channel, username, text, link "
                                "FROM tg_posts WHERE classified=0 ORDER BY ts DESC LIMIT ?",
                                (tg_budget,)).fetchall() if tg_budget else []
        except Exception:
            rows_tg = []                              # таблицы нет — сборщик ещё не запускался
        for ch_id, msg_id, ch, user, text, link in rows_tg:
            d = classify(text[:400]) or {}
            imp = int(d.get("importance") or 0)
            c.execute("INSERT OR IGNORE INTO news_items(link, ts, source, title, category, tone, "
                      "importance, assets, summary_ru) VALUES (?,?,?,?,?,?,?,?,?)",
                      (link, int(time.time()), f"TG/{ch}", text[:300], d.get("category"),
                       d.get("tone"), imp, json.dumps(d.get("assets") or [], ensure_ascii=False),
                       d.get("summary_ru")))
            c.execute("UPDATE tg_posts SET classified=1 WHERE channel_id=? AND msg_id=?",
                      (ch_id, msg_id))
            c.commit()
            if imp >= URGENT_IMPORTANCE and not _is_dup(d.get("summary_ru") or text[:200]):
                tone_dot = {"bearish": "🔴", "bullish": "🟢"}.get(str(d.get("tone")), "⚪")
                send_tg(f"🗞️ <b>ВАЖНОЕ ИЗ TG</b> [{d.get('category')}] {tone_dot} {imp}/10\n\n"
                        f"{d.get('summary_ru') or text[:200]}\n\n"
                        f'<a href="{link}">{ch}</a>\n\n#NEWS #TG', channel="news")
        # 📅 High-impact событие ближе 12ч → однократный алерт («не держи плечо в FOMC»)
        for ev in upcoming_high_impact(12):
            key = f"cal:{ev['ts']}:{ev['title']}"[:80]
            if not c.execute("SELECT 1 FROM alert_log WHERE key=?", (key,)).fetchone():
                send_tg(f"📅 <b>СОБЫТИЕ ЧЕРЕЗ ~{ev['in_hours']:.0f}ч</b> [{ev['country']}]\n"
                        f"{ev['title']}\n"
                        f"High-impact: волатильность/шпильки — осторожно с плечом.\n\n#CALENDAR",
                        channel="news")
                c.execute("INSERT OR REPLACE INTO alert_log VALUES (?, ?)", (key, int(time.time())))
                c.commit()
        # сводка раз в DIGEST_EVERY_H: новости + календарь 48ч + on-chain отжим
        row = c.execute("SELECT ts FROM alert_log WHERE key='news_digest'").fetchone()
        if not row or time.time() - row[0] >= DIGEST_EVERY_H * 3600:
            since = int(time.time()) - DIGEST_EVERY_H * 3600
            top = c.execute("SELECT title, category, tone, importance, summary_ru, link, source "
                            "FROM news_items WHERE ts>? AND importance>=5 AND digested=0 "
                            "ORDER BY importance DESC LIMIT 5", (since,)).fetchall()
            cal = upcoming_high_impact(48)
            chain = _onchain_block(c, DIGEST_EVERY_H)
            market = _market_block(c)
            if top or cal or chain:
                lines = [f"🗞️ <b>Новостной фон · {DIGEST_EVERY_H}ч</b> · {fear_greed()}"]
                lines += [f"🌐 {x}" for x in market]
                lines.append("")
                for t, cat, tone, imp, summ, link, src in top:
                    dot = {"bearish": "🔴", "bullish": "🟢"}.get(str(tone), "⚪")
                    # ссылка на первоисточник (09.07, «Гуам»/«доллар упал vs растёт»):
                    # 8B пересказывает вольно — проверка = один тап
                    lines.append(f'{dot} <b>{imp}</b> [{cat}] {summ or t} · <a href="{link}">{src}</a>')
                if cal:
                    lines.append("")
                    lines.append("📅 <b>Нависает (48ч):</b>")
                    for ev in cal[:4]:
                        lines.append(f"  · через {ev['in_hours']:.0f}ч [{ev['country']}] {ev['title']}")
                if chain:
                    lines.append("")
                    lines.append("⛓ <b>On-chain:</b>")
                    lines += [f"  · {x}" for x in chain]
                if send_tg("\n".join(lines) + "\n\n#NEWS_DIGEST", channel="news"):
                    c.execute("UPDATE news_items SET digested=1 WHERE ts>?", (since,))
            c.execute("INSERT OR REPLACE INTO alert_log VALUES ('news_digest', ?)", (int(time.time()),))
            c.commit()
        # 🧭 часовой компас — агрегированная интерпретация (Егор: «ждём/лонг/шорт», не поток)
        compass(c)
    finally:
        c.close()


if __name__ == "__main__":
    print(f"[NEWS-SPHERE] старт: {len(FEEDS)} фидов · цикл {CYCLE_SEC//60}м · LLM={MODEL} · "
          f"срочное >= {URGENT_IMPORTANCE} → ACTION · сводка {DIGEST_EVERY_H}ч → FEED")
    if "--once" in sys.argv:
        cycle()
        sys.exit(0)
    while True:
        try:
            cycle()
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[NEWS-SPHERE] cycle err: {e}")
        time.sleep(CYCLE_SEC)
