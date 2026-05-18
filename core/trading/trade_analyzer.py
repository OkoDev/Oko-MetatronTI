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
Ты — аналитик торгового бота по крипторынку. Сделка закрылась по Stop Loss (убыток).
Твоя задача: на основе ТОЛЬКО переданных данных объяснить что пошло не так.

СТРОГИЕ ПРАВИЛА:
1. Используй ТОЛЬКО значения из блока КОНТЕКСТ. Если поля нет — не упоминай его.
2. НЕ выдумывай пороги, лимиты, проценты, имена фильтров (типа "strong=80", "минимум 90%").
3. Если max_R_possible >= 1.0 — сделка БЫЛА в плюсе и развернулась (TSL/exit problem).
4. Если direction противоречит mtf_direction_bias — вход против старшего тренда.
5. Если pivot_real_touch=0 — реального касания уровня НЕ БЫЛО (плохой вход).
6. Если sl_atr_ratio < 1.5 — SL слишком узкий, шум выбил.
7. Если данных мало — напиши "Недостаточно контекста для разбора" и не выдумывай.
8. Длина: 3-5 коротких предложений на русском, как трейдер. Без воды.

СДЕЛКА:
  Символ:       {symbol}
  Направление:  {direction}
  Тип сигнала:  {signal_type}
  Сила/уверен.: {strength}%  conf={confidence:.2f}
  Результат:    R={r_multiple}  profit={profit_pct:.2f}%
  Длительность: {duration} мин

КОНТЕКСТ:
{context_block}\
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
        self._day_count = 0
        self._day_date = ""
        self._init_client()

    def _load_config(self) -> dict:
        """Читает блок trade_analyzer из config.yaml."""
        try:
            from core.infra.config_loader import config
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
                              regime, sl_source, tp_source,
                              max_R_possible, captured_R_pct, tsl_activated,
                              entry_price, stop_loss, take_profit,
                              features_json, decision_trace_json
                       FROM simulated_trades WHERE id=? AND status='SL'""",
                    (trade_id,),
                ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.debug("TradeAnalyzer._load_trade(%d): %s", trade_id, e)
            return None

    def _build_context_block(self, trade: dict) -> str:
        """Формирует подробный контекст для LLM-разбора.
        Источники: колонки simulated_trades + features_json + decision_trace_json.
        Цель: дать модели достаточно фактов чтобы не пришлось выдумывать.
        """
        lines = []

        # === Прямые колонки из БД ===
        regime = trade.get("regime")
        if regime:
            lines.append(f"Режим: {regime}")
        sl_src = trade.get("sl_source")
        tp_src = trade.get("tp_source")
        if sl_src:
            lines.append(f"SL источник: {sl_src}")
        if tp_src:
            lines.append(f"TP источник: {tp_src}")

        entry, sl, tp = trade.get("entry_price"), trade.get("stop_loss"), trade.get("take_profit")
        if entry and sl:
            sl_dist_pct = abs(float(entry) - float(sl)) / float(entry) * 100
            lines.append(f"SL дистанция: {sl_dist_pct:.2f}% от entry")

        # MFE-индикаторы (был ли trade в плюсе)
        max_r = trade.get("max_R_possible")
        cap_r = trade.get("captured_R_pct")
        tsl_act = trade.get("tsl_activated")
        if max_r is not None:
            lines.append(f"Max R достигнут: {max_r:.2f}R")
        if cap_r is not None:
            lines.append(f"Captured R: {cap_r:.1f}% от потенциала")
        if tsl_act is not None:
            lines.append(f"TSL активирован: {'да' if tsl_act else 'нет'} (порог +1R)")

        # === features_json ===
        if trade.get("features_json"):
            try:
                fj = json.loads(trade["features_json"])

                # MTF контекст
                mtf_bias = fj.get("mtf_direction_bias")
                if mtf_bias:
                    lines.append(f"MTF старший тренд: {mtf_bias}")
                mtf_str = fj.get("mtf_bias_strength")
                if mtf_str is not None:
                    lines.append(f"MTF bias strength: {mtf_str}")
                atr_bias = fj.get("atr_trend_1h_bias")
                if atr_bias:
                    lines.append(f"ATRtrend 1h: {atr_bias}")
                rev_mode = fj.get("reversal_mode")
                if rev_mode:
                    lines.append(f"Reversal mode: {rev_mode}")

                # SMC
                smc_facts = []
                if fj.get("smc_has_bos"): smc_facts.append("BOS")
                if fj.get("smc_has_choch"): smc_facts.append("CHoCH")
                if fj.get("smc_has_bullish_bos"): smc_facts.append("bull_BOS")
                if fj.get("smc_has_bearish_bos"): smc_facts.append("bear_BOS")
                if smc_facts:
                    lines.append(f"SMC: {', '.join(smc_facts)}")

                # Объём/волатильность
                vol = fj.get("volatility")
                if isinstance(vol, (int, float)):
                    lines.append(f"Волатильность: {vol:.2f}%")
                vol_24h = fj.get("volume_24h")
                if isinstance(vol_24h, (int, float)) and vol_24h > 0:
                    lines.append(f"Volume 24h: ${vol_24h/1e6:.1f}M")

                # Качество SL/входа
                sl_atr = fj.get("sl_atr_ratio")
                if sl_atr is not None:
                    lines.append(f"SL/ATR: {sl_atr}")
                rr = fj.get("rr_at_entry")
                if rr is not None:
                    lines.append(f"RR при входе: {rr}")
                ep = fj.get("entry_priority")
                if ep is not None:
                    lines.append(f"Entry priority: {ep}")

                # DEV-188 — pivot_reversal качество входа
                ptouch = fj.get("pivot_real_touch")
                if ptouch is not None:
                    lines.append(f"Касание уровня: {'да' if ptouch else 'нет (входим без касания)'}")
                pvz = fj.get("pivot_volume_z")
                if pvz is not None:
                    lines.append(f"Volume Z (объём входа): {pvz}")
                pcr = fj.get("pivot_close_rejection")
                if pcr is not None:
                    lines.append(f"Close rejection: {'да' if pcr else 'нет'}")

                # Сессия
                session = fj.get("session")
                if session:
                    lines.append(f"Сессия: {session}")

                # BTC контекст
                btc_reg = fj.get("btc_regime")
                if btc_reg:
                    lines.append(f"BTC режим: {btc_reg}")

                # Confluence
                confl = fj.get("confluence_factors")
                if confl:
                    lines.append(f"Confluence: {confl}")
            except Exception:
                pass

        # === decision_trace ===
        if trade.get("decision_trace_json"):
            try:
                dt = json.loads(trade["decision_trace_json"])
                filters = dt.get("filters", [])
                blocked = [f for f in filters if not f.get("passed")]
                if blocked:
                    lines.append("Заблокированные фильтры (но сделка прошла):")
                    for f in blocked[:5]:
                        lines.append(f"  - {f.get('name','?')}: {f.get('reason','')}")
            except Exception:
                pass

        return "\n".join(lines) if lines else "Контекст недоступен"

    # ------------------------------------------------------------------
    def _check_daily_limit(self) -> bool:
        """True если дневной лимит не исчерпан. Сбрасывает счётчик при смене дня."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day_date:
            self._day_date = today
            self._day_count = 0
        try:
            from core.infra.config_loader import config as _cfg
            max_per_day = int(_cfg.get("trade_analyzer.max_per_day", 80))
        except Exception:
            max_per_day = 80
        if self._day_count >= max_per_day:
            logger.debug("TradeAnalyzer: дневной лимит %d исчерпан", max_per_day)
            return False
        self._day_count += 1
        return True

    async def analyze_sl_trade(self, trade_id: int) -> Optional[str]:
        """Анализирует SL-сделку через LLM и сохраняет в trade_analysis."""
        if not self._enabled or self._client is None:
            return None
        if not self._check_daily_limit():
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
        if not self._check_daily_limit():
            return None
        try:
            from core.signals.signal_models import TradingRecommendation
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
