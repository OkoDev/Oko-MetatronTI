"""
ARCH-104 production patterns registry (Phase 7 DEV-270).

Загружает 10 production patterns из `config/arch104_patterns.yaml` и
предоставляет API для:
  - lookup pattern by id
  - проверка factor match (anchor + LTF triggers)
  - получение exit strategy / risk policy

Использование:
  from core.confirmations.arch104_patterns import ARCH104Registry
  reg = ARCH104Registry()
  pattern = reg.get("L1_golden")
  matched = reg.find_matching(direction="LONG", active_flags={...})
"""
from __future__ import annotations

import logging
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "arch104_patterns.yaml"


@dataclass
class ARCH104Pattern:
    id: str
    direction: str
    anchor_factors: list[str]
    weight: int
    test_n: int = 0
    test_avgR: float = 0.0
    test_WR: float = 0.0
    priority: int = 3
    time_exit_hours: int = 24
    sl_lookback_bars: int = 10
    sl_buffer_pct: float = 0.1
    fallback_tp_r: float = 2.0
    tp_strategy: str = "TBD"
    risk_policy_ref: Optional[str] = None
    parent_pattern: Optional[str] = None
    ltf_triggers: list[str] = field(default_factory=list)
    detection_tf: str = "1h"                # NEW: на каком TF искать срабатывание
    scaling_role: Optional[str] = None      # NEW: fast/medium/anchor/slow (D-026)
    enabled: bool = True                    # DEV-236: false → паттерн не матчится (изоляция)


class ARCH104Registry:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.patterns: dict[str, ARCH104Pattern] = {}
        self.defaults: dict = {}
        self.risk_intel_config: dict = {}
        self.auto_retire_config: dict = {}
        self._load()

    def _load(self):
        if not self.config_path.exists():
            logger.warning("ARCH-104 patterns config not found: %s", self.config_path)
            return

        with open(self.config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.defaults = data.get("defaults", {})
        self.risk_intel_config = data.get("risk_intelligence", {})
        self.auto_retire_config = data.get("auto_retire", {})

        for pat_id, cfg in (data.get("patterns") or {}).items():
            sl_cfg = cfg.get("sl", {})
            tp_cfg = cfg.get("tp", {})
            self.patterns[pat_id] = ARCH104Pattern(
                id=pat_id,
                direction=cfg.get("direction", "LONG"),
                anchor_factors=cfg.get("anchor_factors", []),
                weight=cfg.get("weight", 10),
                test_n=cfg.get("test_n", 0),
                test_avgR=cfg.get("test_avgR", 0.0),
                test_WR=cfg.get("test_WR", 0.0),
                priority=cfg.get("priority", 3),
                time_exit_hours=cfg.get("time_exit_hours", 24),
                sl_lookback_bars=sl_cfg.get("lookback_bars", self.defaults.get("sl_lookback_bars", 10)),
                sl_buffer_pct=sl_cfg.get("buffer_pct", self.defaults.get("sl_buffer_pct", 0.1)),
                fallback_tp_r=tp_cfg.get("fallback_tp_r", 2.0),
                tp_strategy=tp_cfg.get("strategy", "TBD"),
                risk_policy_ref=cfg.get("risk_policy_ref"),
                parent_pattern=cfg.get("parent"),
                ltf_triggers=cfg.get("ltf_triggers", []),
                detection_tf=cfg.get("detection_tf", "1h"),
                scaling_role=cfg.get("scaling_role"),
                enabled=cfg.get("enabled", True),
            )

        logger.info("ARCH-104 Registry loaded: %d patterns", len(self.patterns))

    def get(self, pattern_id: str) -> Optional[ARCH104Pattern]:
        return self.patterns.get(pattern_id)

    def find_matching(self, direction: str, active_flags: set[str],
                     detection_tf: Optional[str] = None) -> list[ARCH104Pattern]:
        """Возвращает все паттерны, чьи anchor_factors все True в active_flags.

        Если detection_tf указан — фильтрует patterns по этому TF (только matching).
        Сортируется по priority и weight (best first).
        """
        matches = []
        for pat in self.patterns.values():
            if not pat.enabled:                 # DEV-236: изолированные паттерны не матчатся
                continue
            if pat.direction != direction:
                continue
            if detection_tf is not None and pat.detection_tf != detection_tf:
                continue
            if all(f in active_flags for f in pat.anchor_factors):
                matches.append(pat)
        return sorted(matches, key=lambda p: (p.priority, -p.weight))

    def list_by_direction(self, direction: str) -> list[ARCH104Pattern]:
        return [p for p in self.patterns.values() if p.direction == direction]

    def htf_gate_open(self, active_htf_flags: set[str], detection_tf: str) -> bool:
        """DEV-232: можно ли вообще фетчить LTF (5m) для пары.

        Gate открыт, если СУЩЕСТВУЕТ хотя бы один паттерн данного detection_tf,
        у которого ВСЕ его HTF-anchor-флаги (не-LTF подмножество anchor_factors)
        присутствуют в active_htf_flags. HTF-anchors — необходимое условие
        срабатывания паттерна: без них он не сматчится даже после fetch LTF.

        Проверено (29.05): 0 из 72 5m-паттернов без HTF-anchor → gate ничего
        не блокирует, только отсекает заведомо-холостые LTF-фетчи.
        """
        suffix = "_" + detection_tf
        for pat in self.patterns.values():
            if not pat.enabled:                 # DEV-236: изолированные не открывают gate
                continue
            if pat.detection_tf != detection_tf:
                continue
            htf_anchors = [f for f in pat.anchor_factors if not f.endswith(suffix)]
            if not htf_anchors:
                # Паттерн вообще без HTF-anchor — gate нельзя применять (выпал бы).
                # Сейчас таких нет, но если появятся — открываем gate (fail-open).
                return True
            if all(f in active_htf_flags for f in htf_anchors):
                return True
        return False

    def get_risk_intel_config(self) -> dict:
        return self.risk_intel_config

    def get_auto_retire_config(self) -> dict:
        return self.auto_retire_config


# ─────────── Self-test ───────────

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    reg = ARCH104Registry()
    print(f"Loaded {len(reg.patterns)} patterns")

    print(f"\nLONG patterns:")
    for p in reg.list_by_direction("LONG"):
        print(f"  {p.id:<25} weight={p.weight} priority={p.priority} test_n={p.test_n} avgR={p.test_avgR:+.3f}")

    print(f"\nSHORT patterns:")
    for p in reg.list_by_direction("SHORT"):
        print(f"  {p.id:<25} weight={p.weight} priority={p.priority} test_n={p.test_n} avgR={p.test_avgR:+.3f}")

    # Test match logic — симуляция flag set
    test_flags = {"bull_div_1d", "bull_fvg_4h", "wt_os_4h", "wt_os_1h", "discount_4h"}
    matches = reg.find_matching("LONG", test_flags)
    print(f"\nMatch for active_flags={test_flags}:")
    for m in matches:
        print(f"  → {m.id} (priority {m.priority}, weight {m.weight})")

    # Test Risk Intel config
    print(f"\nRisk Intel config: {reg.get_risk_intel_config()}")
