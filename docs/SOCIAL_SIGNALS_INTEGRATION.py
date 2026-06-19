# -*- coding: utf-8 -*-
"""
SOCIAL SIGNALS — код-пример интеграции (БЭКЛОГ Phase 5+)
=========================================================
НЕ ЗАПУСКАТЬ до: стабилизации ote_nested + завершения EXEC-REBUILD.
Сохранить как docs/SOCIAL_SIGNALS_INTEGRATION.py

Автор: DS (анализ) + юзер (код)
Дата: 2026-06-19
"""

# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 1: КОНФИГУРАЦИЯ (config/social_config.py)
# ═══════════════════════════════════════════════════════════

from dataclasses import dataclass
from typing import List


@dataclass
class CryptoPanicConfig:
    """CryptoPanic API — бесплатный ключ на cryptopanic.com/developers/api/"""
    api_token: str = ""
    enabled: bool = True
    base_url: str = "https://cryptopanic.com/api/v1/posts/"
    poll_interval: int = 30  # секунд
    min_impact_score: int = 6
    currencies: List[str] = None

    def __post_init__(self):
        if self.currencies is None:
            self.currencies = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"]


@dataclass
class TelegramConfig:
    """Telegram-слушатель — api_id/hash на my.telegram.org"""
    api_id: int = 0
    api_hash: str = ""
    enabled: bool = True
    session_name: str = "oko_bot_session"
    target_channels: List[str] = None
    poll_interval: int = 5

    def __post_init__(self):
        if self.target_channels is None:
            self.target_channels = [
                "treeofalpha",           # Tree of Alpha (news)
                "wu_blockchain",         # Wu Blockchain
                "coindesk",              # CoinDesk
                "theblock__crypto",      # The Block
                "binance",               # Binance announcements
            ]


@dataclass
class SocialSignalsConfig:
    """Главный конфиг социальных сигналов"""
    cryptopanic: CryptoPanicConfig = None
    telegram: TelegramConfig = None
    min_confidence: float = 0.7
    min_impact_for_trade: int = 7
    symbols_to_track: List[str] = None
    use_local_llm: bool = True           # True=Ollama, False=OpenAI
    ollama_model: str = "llama3:8b"

    def __post_init__(self):
        if self.cryptopanic is None:
            self.cryptopanic = CryptoPanicConfig()
        if self.telegram is None:
            self.telegram = TelegramConfig()
        if self.symbols_to_track is None:
            self.symbols_to_track = ["BTC", "ETH", "SOL", "BNB"]


social_config = SocialSignalsConfig()


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 2: CRYPTOPANIC CLIENT (services/social_signals/)
# ═══════════════════════════════════════════════════════════

import httpx
import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class CryptoPanicClient:
    """Free CryptoPanic API — https://cryptopanic.com/developers/api/"""

    def __init__(self, config: CryptoPanicConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=10.0)

    async def fetch_latest_posts(self, limit: int = 20) -> List[Dict]:
        if not self.config.api_token:
            logger.warning("CryptoPanic API token not set")
            return []

        params = {
            "auth_token": self.config.api_token,
            "kind": "news",
            "filter": "important",
            "currencies": ",".join(self.config.currencies),
            "limit": limit,
        }

        try:
            response = await self.client.get(self.config.base_url, params=params)
            response.raise_for_status()
            data = response.json()
            posts = data.get("results", [])
            logger.info(f"[CryptoPanic] fetched {len(posts)} posts")
            return self._normalize_posts(posts)
        except Exception as e:
            logger.error(f"[CryptoPanic] error: {e}")
            return []

    def _normalize_posts(self, posts: List[Dict]) -> List[Dict]:
        normalized = []
        for post in posts:
            currencies = [c["code"] for c in post.get("currencies", [])]
            votes = post.get("votes", {})
            vote_ratio = votes.get("positive", 0) / max(
                votes.get("positive", 0) + votes.get("negative", 0), 1
            )
            is_important = post.get("important", False)
            impact = 8 if is_important else 4
            sentiment = 0.5 if vote_ratio > 0.5 else -0.5 if vote_ratio < 0.5 else 0.0

            normalized.append({
                "source": "CRYPTOPANIC",
                "external_id": str(post["id"]),
                "author_handle": post.get("source", {}).get("title", "Unknown"),
                "url": post.get("url"),
                "content": post.get("title", "") + " | " + post.get("domain", ""),
                "mentioned_symbols": currencies or ["BTC"],
                "sentiment_score": sentiment,
                "impact_score": max(1, min(10, impact)),
                "predicted_direction": (
                    "LONG" if sentiment > 0.3 else "SHORT" if sentiment < -0.3 else "NEUTRAL"
                ),
                "confidence_score": abs(vote_ratio - 0.5) * 2,
                "published_at": post.get("published_at"),
            })
        return normalized

    async def close(self):
        await self.client.aclose()


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 3: TELEGRAM LISTENER (services/social_signals/)
# ═══════════════════════════════════════════════════════════

import re, asyncio
from telethon import TelegramClient, events


class TelegramListener:
    """Слушает Telegram-каналы, парсит упоминания криптовалют."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.client: TelegramClient = None
        self.new_signals_callback = None
        self.is_running = False

    async def start(self):
        if not self.config.api_id or not self.config.api_hash:
            return
        self.client = TelegramClient(
            self.config.session_name, self.config.api_id, self.config.api_hash
        )
        await self.client.start()
        self.is_running = True

        @self.client.on(events.NewMessage(chats=self.config.target_channels))
        async def handler(event):
            if event.fwd_from or event.is_reply:
                return
            text = event.message.text
            if not text or len(text) < 10:
                return
            signal = self._parse(text, event.chat_id, event.message)
            if signal and self.new_signals_callback:
                await self.new_signals_callback(signal)

        logger.info(f"[Telegram] listening to {len(self.config.target_channels)} channels")

    def _parse(self, text: str, chat_id: int, message) -> Dict | None:
        symbols = re.findall(
            r'\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|MATIC|AVAX|DOT|LINK)\b',
            text, re.IGNORECASE
        )
        if not symbols:
            return None

        # Simple impact estimation
        high_impact = ["binance", "listing", "sec", "hack", "etf", "ban", "partnership"]
        impact = 5
        for kw in high_impact:
            if kw in text.lower():
                impact += 3
                break

        # Simple sentiment
        pos_words = ["bullish", "pump", "buy", "long", "breakout", "surge"]
        neg_words = ["bearish", "dump", "crash", "sell", "short", "drop"]
        pos = sum(1 for w in pos_words if w in text.lower())
        neg = sum(1 for w in neg_words if w in text.lower())
        total = pos + neg
        sentiment = (pos - neg) / total if total > 0 else 0
        direction = "LONG" if sentiment > 0.2 else "SHORT" if sentiment < -0.2 else "NEUTRAL"

        return {
            "source": "TELEGRAM",
            "external_id": f"{chat_id}_{message.id}",
            "author_handle": message.chat.username or str(chat_id),
            "url": f"https://t.me/{message.chat.username}/{message.id}" if message.chat.username else None,
            "content": text[:500],
            "mentioned_symbols": list(set(s.upper() for s in symbols)),
            "sentiment_score": sentiment,
            "impact_score": max(1, min(10, impact)),
            "predicted_direction": direction,
            "confidence_score": 0.6 if impact >= 7 else 0.4,
            "published_at": message.date.isoformat(),
        }

    def set_new_signals_callback(self, callback):
        self.new_signals_callback = callback

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.is_running = False


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 4: AI-АНАЛИЗАТОР (Ollama или OpenAI)
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Ты — крипто-аналитик. Проанализируй новость и верни JSON:
{
  "mentioned_symbols": ["BTC"],
  "sentiment_score": 0.8,
  "impact_score": 8,
  "predicted_direction": "LONG",
  "confidence_score": 0.85,
  "reasoning": "обоснование"
}
sentiment: -1.0 (негатив) до 1.0 (позитив)
impact: 1-10 (1=шум, 5=обычная новость, 8=важно, 10=экстренно)
direction: LONG/SHORT/NEUTRAL
confidence: 0.0-1.0"""


class SignalAnalyzer:
    """AI-powered анализ через Ollama (бесплатно) или OpenAI."""
    def __init__(self, config: SocialSignalsConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=60.0)
        self.model = config.ollama_model
        logger.info(f"[AI Analyzer] model={self.model}")

    async def analyze(self, content: str, author: str = "") -> Dict | None:
        prompt = f'Автор: @{author}\nТекст: "{content[:500]}"\nПроанализируй. Верни JSON.'
        try:
            payload = {
                "model": self.model, "prompt": prompt,
                "system": SYSTEM_PROMPT, "stream": False, "format": "json"
            }
            response = await self.client.post(
                "http://localhost:11434/api/generate", json=payload
            )
            data = response.json()
            return json.loads(data.get("response", "{}"))
        except Exception as e:
            logger.error(f"[AI] error: {e}")
            return None

    async def close(self):
        await self.client.aclose()


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 5: СТРАТЕГИЯ (8-й детектор)
# ═══════════════════════════════════════════════════════════

class SocialSentimentStrategy:
    """Генерирует сигналы из социальных новостей при высоком impact score."""

    NAME = "social_sentiment"
    DESCRIPTION = "Social media sentiment analysis for crypto trading"

    def __init__(self, db_path: str):
        import sqlite3
        self.db_path = db_path
        self.min_impact = social_config.min_impact_for_trade
        self.min_confidence = social_config.min_confidence
        logger.info(f"[{self.NAME}] initialized (min_impact={self.min_impact})")

    def check_signals(self, symbol: str = None) -> List:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """SELECT id, source, content, mentioned_symbols,
            sentiment_score, impact_score, predicted_direction, confidence_score
            FROM social_signals
            WHERE is_signal_generated = 0 AND is_processed = 1
            AND impact_score >= ? AND confidence_score >= ?
            AND processed_at > datetime('now', '-15 minutes')
            ORDER BY impact_score DESC"""

        params = [self.min_impact, self.min_confidence]
        if symbol:
            query += " AND mentioned_symbols LIKE ?"
            params.append(f'%"{symbol}"%')

        cursor.execute(query, params)
        signals = []

        for row in cursor.fetchall():
            mentioned = json.loads(row["mentioned_symbols"] or '["BTC"]')
            direction = row["predicted_direction"] or "NEUTRAL"
            if direction == "NEUTRAL":
                direction = "LONG" if row["sentiment_score"] > 0 else "SHORT"

            strength = (row["impact_score"] / 10.0) * row["confidence_score"]
            if strength < 0.5:
                continue

            signal = {
                "symbol": mentioned[0],
                "timeframe": "5m",
                "signal_type": "social_sentiment",
                "direction": direction,
                "strength": min(1.0, strength),
                "source_router": self.NAME,
                "metadata": {
                    "social_source": row["source"],
                    "impact_score": row["impact_score"],
                    "confidence_score": row["confidence_score"],
                    "content_preview": row["content"][:200],
                },
            }
            signals.append(signal)
            cursor.execute(
                "UPDATE social_signals SET is_signal_generated=1 WHERE id=?",
                (row["id"],),
            )

        conn.commit()
        conn.close()
        return signals


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 6: ОРКЕСТРАТОР (services/social_signals/__init__.py)
# ═══════════════════════════════════════════════════════════

import asyncio


class SocialSignalsService:
    """Главный оркестратор сбора и обработки социальных сигналов."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.cryptopanic = CryptoPanicClient(social_config.cryptopanic)
        self.telegram = TelegramListener(social_config.telegram)
        self.analyzer = SignalAnalyzer(social_config)
        self.is_running = False
        self.telegram.set_new_signals_callback(self._on_telegram)

    async def start(self):
        logger.info("[SocialSignals] starting...")
        if social_config.telegram.enabled:
            await self.telegram.start()
        self.is_running = True
        if social_config.cryptopanic.enabled:
            asyncio.create_task(self._poll_cryptopanic())

    async def stop(self):
        self.is_running = False
        await self.telegram.stop()
        await self.cryptopanic.close()
        await self.analyzer.close()

    async def _poll_cryptopanic(self):
        while self.is_running:
            try:
                posts = await self.cryptopanic.fetch_latest_posts(20)
                for post in posts:
                    await self._process(post)
                await asyncio.sleep(social_config.cryptopanic.poll_interval)
            except Exception as e:
                logger.error(f"[CryptoPanic poll] {e}")
                await asyncio.sleep(60)

    async def _on_telegram(self, signal: dict):
        await self._process(signal)

    async def _process(self, data: dict):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM social_signals WHERE external_id=?",
            (data["external_id"],)
        )
        if cursor.fetchone():
            conn.close()
            return

        # AI-анализ
        if data.get("impact_score", 5) < 5:
            analysis = await self.analyzer.analyze(
                data.get("content", ""), data.get("author_handle", "")
            )
            if analysis:
                data.update(analysis)

        cursor.execute("""INSERT OR IGNORE INTO social_signals (
            source, external_id, author_handle, url, content,
            mentioned_symbols, sentiment_score, impact_score,
            predicted_direction, confidence_score, published_at, is_processed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""", (
            data.get("source"), data.get("external_id"),
            data.get("author_handle"), data.get("url"),
            data.get("content"), json.dumps(data.get("mentioned_symbols", ["BTC"])),
            data.get("sentiment_score", 0), data.get("impact_score", 5),
            data.get("predicted_direction", "NEUTRAL"), data.get("confidence_score", 0.5),
            data.get("published_at"),
        ))
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 7: ИНТЕГРАЦИЯ В БОТА (main.py)
# ═══════════════════════════════════════════════════════════
"""
# В main.py добавить:

from services.social_signals import SocialSignalsService
from strategies.built_in.social_sentiment import SocialSentimentStrategy

social_service = SocialSignalsService(db_path)
await social_service.start()

strategy_manager.register_strategy(SocialSentimentStrategy(db_path))

# При выключении:
await social_service.stop()
"""


# ═══════════════════════════════════════════════════════════
# ЧАСТЬ 8: МИГРАЦИЯ БД (создание таблицы social_signals)
# ═══════════════════════════════════════════════════════════

SOCIAL_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS social_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT CHECK(source IN ('CRYPTOPANIC', 'TELEGRAM', 'TWITTER')) NOT NULL,
    external_id TEXT UNIQUE NOT NULL,
    author_handle TEXT,
    author_followers_count INTEGER DEFAULT 0,
    url TEXT,
    content TEXT NOT NULL,
    mentioned_symbols TEXT,
    sentiment_score REAL,
    impact_score INTEGER CHECK(impact_score >= 1 AND impact_score <= 10),
    predicted_direction TEXT CHECK(predicted_direction IN ('LONG', 'SHORT', 'NEUTRAL')),
    confidence_score REAL,
    published_at DATETIME,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_processed BOOLEAN DEFAULT 0,
    is_signal_generated BOOLEAN DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_social_source_time ON social_signals(source, processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_impact ON social_signals(impact_score DESC, processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_unprocessed ON social_signals(processed_at) WHERE is_processed = 0;
"""

# ═══════════════════════════════════════════════════════════
# ЗАПУСК (после стабилизации + EXEC-REBUILD):
#
# 1. CryptoPanic: cryptopanic.com/developers/api/ → токен
# 2. Telegram: my.telegram.org → api_id + api_hash
# 3. Ollama (опц.): ollama pull llama3:8b
# 4. pip install httpx telethon
# 5. Применить миграцию (DDL выше)
# 6. Раскомментировать интеграцию в main.py
# ═══════════════════════════════════════════════════════════
