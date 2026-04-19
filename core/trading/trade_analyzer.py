"""
DEV-15: TradeAnalyzer — LLM-разбор SL-сделок.

Поддерживаемые провайдеры (config.yaml → trade_analyzer.provider):
  anthropic  — Claude (pip install anthropic)
  groq       — Llama3/Mixtral, бесплатно (pip install openai, ключ: console.groq.com)
  openai     — GPT-4o-mini (pip install openai)
  openrouter — агрегатор, есть бесплатные модели (pip install openai)
  ollama     — локально без интернета (pip install openai, ollama должен быть запущен)
  disabled   — отключить

Пример config.yaml:
  trade_analyzer:
    provider: groq
    api_key: "gsk_..."
    model: "llama-3.1-8b-instant"
    # base_url: ""   # опционально — переопределить URL
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Дефолтные модели по провайдеру
_PROVIDER_DEFAULTS = {
    "anthropic":  {"model": "claude-haiku-4-5-20251001", "base_url": None},
    "groq":       {"model": "llama-3.1-8b-instant",      "base_url": "https://api.groq.com/openai/v1"},
    "openai":     {"model": "gpt-4o-mini",               "base_url": None},
    "openrouter": {"model": "meta-llama/llama-3.1-8b-instruct:free", "base_url": "https://openrouter.ai/api/v1"},
    "ollama":     {"model": "llama3",                    "base_url": "http://localhost:11434/v1"},
}

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

Ответь кратко как трейдер 2–3 предложениями на русском языке. Только факты из контекста, без домыслов.\
"""


class TradeAnalyzer:
    """Асинхронный LLM-анализатор убыточных сделок. Мультипровайдерный."""

    def __init__(self, db_path: str, api_key: Optional[str] = None):
        self.db_path = db_path
        self._api_key = api_key
        self._client = None
        self._provider = "disabled"
        self._model = ""
        self._enabled = False
        self._init_client()

    def _load_config(self) -> dict:
        """Читает блок trade_analyzer из config.yaml."""
        try:
            from core.config_loader import config
            cfg = config.get("trade_analyzer", {}) or {}
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    def _init_client(self) -> None:
        cfg = self._load_config()
        provider = cfg.get("provider", "disabled").lower()

        if provider == "disabled" or not provider:
            logger.info("TradeAnalyzer: LLM-разбор отключён (provider=disabled)")
            return

        # Ключ: из конфига, аргумента, env
        key = self._api_key or cfg.get("api_key") or None
        if not key:
            import os
            env_map = {
                "anthropic":  "ANTHROPIC_API_KEY",
                "groq":       "GROQ_API_KEY",
                "openai":     "OPENAI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "ollama":     None,  # ollama не требует ключа
            }
            env_var = env_map.get(provider)
            if env_var:
                key = os.environ.get(env_var)

        defaults = _PROVIDER_DEFAULTS.get(provider, {})
        model    = cfg.get("model") or defaults.get("model", "")
        base_url = cfg.get("base_url") or defaults.get("base_url")

        if provider == "anthropic":
            if not key:
                logger.info("TradeAnalyzer: ANTHROPIC_API_KEY не задан — разбор отключён")
                return
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=key)
                self._provider = "anthropic"
                self._model    = model
                self._enabled  = True
                logger.info("TradeAnalyzer: Anthropic (%s) готов", model)
            except ImportError:
                logger.warning("TradeAnalyzer: pip install anthropic")

        elif provider in ("groq", "openai", "openrouter", "ollama"):
            # Все используют OpenAI-совместимый SDK
            if provider != "ollama" and not key:
                logger.info("TradeAnalyzer: api_key для %s не задан — разбор отключён", provider)
                return
            try:
                from openai import AsyncOpenAI
                kwargs = {"api_key": key or "ollama"}
                if base_url:
                    kwargs["base_url"] = base_url
                self._client   = AsyncOpenAI(**kwargs)
                self._provider = provider
                self._model    = model
                self._enabled  = True
                logger.info("TradeAnalyzer: %s (%s) готов", provider, model)
            except ImportError:
                logger.warning("TradeAnalyzer: pip install openai  (нужен для %s)", provider)

        else:
            logger.warning("TradeAnalyzer: неизвестный провайдер '%s'", provider)

    # ------------------------------------------------------------------
    def _load_trade(self, trade_id: int) -> Optional[dict]:
        """Читает закрытую сделку из БД."""
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
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

        if trade.get("decision_trace_json"):
            try:
                dt = json.loads(trade["decision_trace_json"])
                filters = dt.get("filters", [])
                if filters:
                    lines.append("Фильтры:")
                    for f in filters[:8]:
                        name   = f.get("name", "?")
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
        """Анализирует SL-сделку через LLM и сохраняет в trade_analysis."""
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
            if self._provider == "anthropic":
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                analysis      = response.content[0].text.strip()
                prompt_tokens = getattr(response.usage, "input_tokens", None)
            else:
                # OpenAI-совместимый (groq / openai / openrouter / ollama)
                response = await self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                analysis      = response.choices[0].message.content.strip()
                usage         = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None

            self._save_analysis(trade_id, analysis, prompt_tokens)
            logger.info("TradeAnalyzer: разбор #%d сохранён (%d символов)", trade_id, len(analysis))
            return analysis

        except Exception as e:
            logger.warning("TradeAnalyzer.analyze_sl_trade(%d): %s", trade_id, e)
            return None

    # ------------------------------------------------------------------
    async def analyze_signal(self, recommendation: object) -> Optional[str]:
        """DEV-151: Groq-комментарий к новому сигналу перед отправкой в TG.

        Возвращает 1-3 предложения анализа или None если LLM недоступен.
        """
        if not self._enabled or self._client is None:
            return None
        try:
            from core.signal_models import TradingRecommendation
            symbol    = getattr(recommendation, "symbol", "?")
            direction = str(getattr(recommendation, "direction", "?"))
            if hasattr(recommendation.direction, "value"):
                direction = recommendation.direction.value
            signal_type = getattr(recommendation, "signal_type", "?")
            if hasattr(signal_type, "value"):
                signal_type = signal_type.value
            strength   = getattr(recommendation, "overall_strength", 0)
            confidence = float(getattr(recommendation, "confidence", 0) or 0)
            action     = getattr(recommendation, "action", "?")
            meta       = getattr(recommendation, "metadata", {}) or {}

            # Контекст из metadata
            ctx_lines = []
            regime = meta.get("regime") or meta.get("market_regime")
            if regime:
                ctx_lines.append(f"Режим рынка: {regime}")
            rev_mode = meta.get("reversal_mode")
            if rev_mode:
                ctx_lines.append(f"Сценарий: {rev_mode}")
            mtf = meta.get("mtf_context") or {}
            if isinstance(mtf, dict) and mtf.get("direction_bias"):
                ctx_lines.append(
                    f"MTF bias: {mtf.get('direction_bias')} ({mtf.get('aligned_pct', '?')}% TF согласовано)"
                )
            smc = meta.get("smc_context") or {}
            if isinstance(smc, dict):
                if smc.get("smc_has_bos"):
                    ctx_lines.append("SMC: BOS подтверждён")
                if smc.get("smc_ob_active"):
                    ctx_lines.append("SMC: Order Block активен")
                if smc.get("smc_fvg_active"):
                    ctx_lines.append("SMC: FVG активна")
            wt_verdict = meta.get("wt_verdict") or {}
            if isinstance(wt_verdict, dict) and wt_verdict.get("label"):
                ctx_lines.append(
                    f"WT Verdict: {wt_verdict.get('label')} (conf={wt_verdict.get('confidence', 0):.2f})"
                )
            sl  = getattr(recommendation, "stop_loss", None)
            tp  = getattr(recommendation, "take_profit", None)
            ep  = getattr(recommendation, "entry_price", None)
            if ep and sl and tp and float(ep) > 0:
                rr = abs(float(tp) - float(ep)) / max(abs(float(ep) - float(sl)), 1e-9)
                ctx_lines.append(f"RR при входе: {rr:.2f}")

            ctx_block = "\n".join(ctx_lines) if ctx_lines else "Нет дополнительного контекста"

            prompt = (
                f"Ты — аналитик торгового бота по крипторынку. Оцени новый торговый сигнал.\n\n"
                f"СИГНАЛ:\n"
                f"  Символ:      {symbol}\n"
                f"  Действие:    {action} ({direction})\n"
                f"  Тип:         {signal_type}\n"
                f"  Сила:        {strength:.0f}%  confidence={confidence:.2f}\n\n"
                f"КОНТЕКСТ:\n{ctx_block}\n\n"
                f"Ответь 1–2 предложениями на русском: стоит ли доверять этому сигналу "
                f"и на что обратить внимание. Без воды, только факты."
            )

            if self._provider == "anthropic":
                response = await self._client.messages.create(
                    model=self._model, max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()
            else:
                response = await self._client.chat.completions.create(
                    model=self._model, max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning("TradeAnalyzer.analyze_signal: %s", e)
            return None

    def _save_analysis(self, trade_id: int, analysis: str, prompt_tokens: Optional[int]) -> None:
        """Сохраняет разбор в таблицу trade_analysis."""
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
                conn.execute(
                    """INSERT INTO trade_analysis (trade_id, analysis, model, prompt_tokens, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (trade_id, analysis, f"{self._provider}/{self._model}", prompt_tokens,
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except Exception as e:
            logger.debug("TradeAnalyzer._save_analysis(%d): %s", trade_id, e)
