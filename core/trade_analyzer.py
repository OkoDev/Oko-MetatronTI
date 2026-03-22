"""
DEV-15: TradeAnalyzer — LLM-разбор SL-сделок через Claude API.

После закрытия сделки по SL — отправляет контекст (features_json + decision_trace)
в Claude, получает текстовый разбор, сохраняет в таблицу trade_analysis.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"  # дешёвый и быстрый для текстовых разборов

_PROMPT_TEMPLATE = """\
Ты — аналитик торгового бота по крипторынку. Сделка закрылась по Stop Loss (убыток). \
Дай краткий разбор: что пошло не так и какой рыночный контекст проигнорировал бот.

СДЕЛКА:
  Символ:      {symbol}
  Направление: {direction}
  Тип сигнала: {signal_type}
  Сила:        {strength}%  confidence={confidence:.2f}
  Результат:   R={r_multiple}  profit={profit_pct:.2f}%
  Длительность: {duration} мин

КОНТЕКСТ РЕШЕНИЯ:
{context_block}

Ответь 2–4 предложениями на русском языке. Только факты из контекста, без домыслов.\
"""


class TradeAnalyzer:
    """Асинхронный LLM-анализатор убыточных сделок."""

    def __init__(self, db_path: str, api_key: Optional[str] = None):
        self.db_path = db_path
        self._api_key = api_key
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self) -> None:
        """Инициализирует Anthropic client если ключ доступен."""
        key = self._api_key
        if not key:
            try:
                from core.config_loader import config
                key = config.get("anthropic.api_key") or None
            except Exception:
                pass
        if not key:
            import os
            key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            logger.info("TradeAnalyzer: ANTHROPIC_API_KEY не задан — LLM-разбор отключён")
            return
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=key)
            self._enabled = True
            logger.info("TradeAnalyzer: Anthropic client инициализирован (model=%s)", _MODEL)
        except ImportError:
            logger.warning("TradeAnalyzer: пакет anthropic не установлен — pip install anthropic")

    # ------------------------------------------------------------------
    def _load_trade(self, trade_id: int) -> Optional[dict]:
        """Читает закрытую сделку из БД."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """SELECT id, symbol, direction, signal_type, strength, confidence,
                              R_multiple, profit_pct, duration_minutes,
                              features_json, decision_trace_json
                       FROM simulated_trades WHERE id=? AND status='SL'""",
                    (trade_id,),
                ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.debug("TradeAnalyzer._load_trade(%d): %s", trade_id, e)
            return None

    def _build_context_block(self, trade: dict) -> str:
        """Формирует краткий контекст из features_json + decision_trace_json."""
        lines = []

        # decision_trace — самая информативная часть
        if trade.get("decision_trace_json"):
            try:
                dt = json.loads(trade["decision_trace_json"])
                filters = dt.get("filters", [])
                if filters:
                    lines.append("Фильтры:")
                    for f in filters[:8]:  # не перегружать контекст
                        name = f.get("name", "?")
                        passed = "✅" if f.get("passed") else "❌"
                        reason = f.get("reason", "")
                        lines.append(f"  {passed} {name}: {reason}")
                mtf = dt.get("mtf_context", {})
                if mtf:
                    lines.append(f"MTF bias={mtf.get('direction_bias','?')} "
                                 f"strength={mtf.get('bias_strength','?')} "
                                 f"zone={mtf.get('price_zone','?')}")
            except Exception:
                pass

        # features_json — дополнительный контекст
        if trade.get("features_json"):
            try:
                fj = json.loads(trade["features_json"])
                regime = fj.get("regime") or fj.get("market_regime")
                if regime:
                    lines.append(f"Режим рынка: {regime}")
                vol = fj.get("volatility")
                if vol:
                    lines.append(f"Волатильность: {vol:.2f}%")
                for key in ("confluence_factors", "sl_source", "tp_source"):
                    val = fj.get(key)
                    if val:
                        lines.append(f"{key}: {val}")
            except Exception:
                pass

        return "\n".join(lines) if lines else "Контекст недоступен"

    # ------------------------------------------------------------------
    async def analyze_sl_trade(self, trade_id: int) -> Optional[str]:
        """Анализирует SL-сделку через LLM и сохраняет в trade_analysis.

        Returns: текст разбора или None при ошибке/отключении.
        """
        if not self._enabled or self._client is None:
            return None

        trade = self._load_trade(trade_id)
        if trade is None:
            logger.debug("TradeAnalyzer: сделка #%d не найдена или не SL", trade_id)
            return None

        context_block = self._build_context_block(trade)
        prompt = _PROMPT_TEMPLATE.format(
            symbol=trade.get("symbol", "?"),
            direction=trade.get("direction", "?"),
            signal_type=trade.get("signal_type", "?"),
            strength=trade.get("strength") or 0,
            confidence=float(trade.get("confidence") or 0),
            r_multiple=trade.get("R_multiple") or "?",
            profit_pct=float(trade.get("profit_pct") or 0),
            duration=int(trade.get("duration_minutes") or 0),
            context_block=context_block,
        )

        try:
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            analysis = response.content[0].text.strip()
            prompt_tokens = getattr(response.usage, "input_tokens", None)
            self._save_analysis(trade_id, analysis, prompt_tokens)
            logger.info("TradeAnalyzer: разбор #%d сохранён (%d символов)", trade_id, len(analysis))
            return analysis
        except Exception as e:
            logger.warning("TradeAnalyzer.analyze_sl_trade(%d): %s", trade_id, e)
            return None

    def _save_analysis(self, trade_id: int, analysis: str, prompt_tokens: Optional[int]) -> None:
        """Сохраняет разбор в таблицу trade_analysis."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO trade_analysis (trade_id, analysis, model, prompt_tokens, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (trade_id, analysis, _MODEL, prompt_tokens,
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except Exception as e:
            logger.debug("TradeAnalyzer._save_analysis(%d): %s", trade_id, e)
