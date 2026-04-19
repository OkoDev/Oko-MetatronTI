"""
VerdictAggregator — DEV-146 / ARCH-68 Фаза 2.

Агрегирует WTVerdict + SMCVerdict → gate / strength modifier.

Shadow mode (verdict_gate.enabled: false):
  - только WOULD_BLOCK / WOULD_BOOST логи, не влияет на recommendation

Gate mode (verdict_gate.enabled: true):
  - противоречия с направлением → блокировка
  - совпадение с направлением → +strength

Пороги (настраиваются в config):
  verdict_gate:
    enabled: false
    smc_block_confidence: 0.65   # мин. conf SMC для блокировки
    wt_exhaustion_confidence: 0.65
    strength_boost: 5            # бонус силы при полном совпадении
    strength_penalty: -10        # штраф при противоречии (не блок)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Метки SMCVerdict
_SMC_BULL = "STRONG_BULL_ZONE"
_SMC_BEAR = "STRONG_BEAR_ZONE"
_SMC_WEAK = "WEAK_ZONE"
_SMC_NEUT = "NEUTRAL"

# Метки WTVerdict
_WT_CONT = "TREND_CONTINUATION"
_WT_REV  = "REVERSAL_SETUP"
_WT_EXHA = "EXHAUSTION"
_WT_UNC  = "UNCLEAR"


@dataclass
class VerdictGate:
    """Результат агрегации вердиктов."""
    should_block:    bool  = False   # True → заблокировать сигнал (только при enabled=True)
    would_block:     bool  = False   # True → WOULD_BLOCK в shadow mode
    strength_delta:  float = 0.0    # корректировка strength (+/-)
    reason:          str   = ""      # объяснение решения
    factors:         list  = field(default_factory=list)  # список факторов


def aggregate_verdicts(
    direction:          str,            # "LONG" / "SHORT"
    wt_verdict:         Optional[Any] = None,  # WTVerdict или None
    smc_verdict:        Optional[Any] = None,  # SMCVerdict или None
    config:             Optional[dict] = None,
    enabled:            bool = False,
    wt_exhaustion_dir:  Optional[str] = None,  # "BEARISH"|"BULLISH"|"NEUTRAL" (TR-007)
) -> VerdictGate:
    """
    Агрегирует WTVerdict + SMCVerdict для direction (LONG/SHORT).

    Если оба специалиста вернули None (нет данных) → нейтральный результат.
    enabled=True → реальный gate; False → только WOULD_BLOCK логирование.
    """
    cfg = (config or {}).get("verdict_gate", {}) if config else {}
    smc_conf_thr  = float(cfg.get("smc_block_confidence",    0.65))
    wt_exha_thr   = float(cfg.get("wt_exhaustion_confidence", 0.65))
    strength_boost = float(cfg.get("strength_boost",  5.0))
    strength_penalty = float(cfg.get("strength_penalty", -10.0))

    gate = VerdictGate()

    if wt_verdict is None and smc_verdict is None:
        return gate  # нет данных — пропускаем

    wt_label   = getattr(wt_verdict,  "label",      _WT_UNC)  if wt_verdict  else _WT_UNC
    wt_conf    = float(getattr(wt_verdict,  "confidence", 0.0)) if wt_verdict  else 0.0
    smc_label  = getattr(smc_verdict, "label",      _SMC_NEUT) if smc_verdict else _SMC_NEUT
    smc_conf   = float(getattr(smc_verdict, "confidence", 0.0)) if smc_verdict else 0.0

    factors: list[str] = []
    block    = False
    delta    = 0.0

    # ─── SMC gate ───────────────────────────────────────────────────
    if smc_verdict is not None:
        if direction == "LONG" and smc_label == _SMC_BEAR and smc_conf >= smc_conf_thr:
            block = True
            factors.append(f"SMC={_SMC_BEAR}({smc_conf:.2f})↔LONG")
        elif direction == "SHORT" and smc_label == _SMC_BULL and smc_conf >= smc_conf_thr:
            block = True
            factors.append(f"SMC={_SMC_BULL}({smc_conf:.2f})↔SHORT")
        elif direction == "LONG" and smc_label == _SMC_BULL and smc_conf >= smc_conf_thr:
            delta += strength_boost * 0.5
            factors.append(f"SMC={_SMC_BULL}({smc_conf:.2f})✓LONG")
        elif direction == "SHORT" and smc_label == _SMC_BEAR and smc_conf >= smc_conf_thr:
            delta += strength_boost * 0.5
            factors.append(f"SMC={_SMC_BEAR}({smc_conf:.2f})✓SHORT")

    # ─── WT gate ────────────────────────────────────────────────────
    if wt_verdict is not None:
        if wt_label == _WT_EXHA and wt_conf >= wt_exha_thr:
            # TR-007 13.04.2026: direction-aware EXHAUSTION gate
            # OB_bias (BEARISH) + LONG → WR=6.2% → BLOCK
            # OS_bias (BULLISH) + SHORT → BLOCK (зеркально)
            # OS_bias (BULLISH) + LONG → WR=50% → PASS
            # NEUTRAL (нет info) → старое поведение (block)
            exha_dir = wt_exhaustion_dir or "NEUTRAL"
            is_counter = (
                (exha_dir == "BEARISH" and direction == "LONG") or
                (exha_dir == "BULLISH" and direction == "SHORT")
            )
            is_aligned = (
                (exha_dir == "BULLISH" and direction == "LONG") or
                (exha_dir == "BEARISH" and direction == "SHORT")
            )
            if is_counter or exha_dir == "NEUTRAL":
                block = True
                factors.append(f"WT={_WT_EXHA}/{exha_dir}({wt_conf:.2f})↔{direction}")
            elif is_aligned:
                # Истощение в нашу сторону → PASS (OS+LONG WR=50%)
                factors.append(f"WT={_WT_EXHA}/{exha_dir}({wt_conf:.2f})✓{direction}")
        elif wt_label == _WT_REV and wt_conf >= 0.60:
            # REVERSAL_SETUP: усиливает контртрендовые входы
            delta += strength_boost
            factors.append(f"WT={_WT_REV}({wt_conf:.2f})✓")
        elif wt_label == _WT_CONT:
            # TR-007 13.04.2026: TREND_CONTINUATION в shadow — только лог, нет буста/блока
            # WR=8.3% avgR=-1.045 при n=48. Активировать при n≥150 с пересмотром логики.
            logger.debug("WT=%s conf=%.2f — shadow (n<150, no gate)", _WT_CONT, wt_conf)

    # ─── Сборка результата ──────────────────────────────────────────
    gate.factors = factors
    gate.strength_delta = round(delta, 1)
    gate.reason  = " | ".join(factors) if factors else "no_signal"

    if block:
        gate.would_block = True
        gate.strength_delta = strength_penalty  # независимо от буста — штраф
        if enabled:
            gate.should_block = True
        logger.info(
            "[VerdictGate] %s %s → %s (%s)",
            direction,
            "BLOCK" if enabled else "WOULD_BLOCK",
            gate.reason,
            f"conf_wt={wt_conf:.2f} conf_smc={smc_conf:.2f}",
        )
    elif delta != 0.0:
        logger.debug(
            "[VerdictGate] %s strength_delta=%.1f (%s)",
            direction, delta, gate.reason,
        )

    return gate
