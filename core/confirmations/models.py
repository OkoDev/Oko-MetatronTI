from dataclasses import dataclass, field
from typing import Literal, Optional
import time


@dataclass
class Confirmation:
    source: str           # "atr_change_1h", "zone_OS_4h", "div_regular_bull_15m" и т.д.
    symbol: str
    side: Literal['LONG', 'SHORT']
    weight: int           # стартовый вес из реестра (0-20)
    confidence: float     # 0.5-1.0
    evidence: dict = field(default_factory=dict)
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    tf: str = ""          # таймфрейм источника

    def to_dict(self) -> dict:
        return {
            'source': self.source,
            'symbol': self.symbol,
            'side': self.side,
            'weight': self.weight,
            'confidence': self.confidence,
            'evidence': self.evidence,
            'ts_ms': self.ts_ms,
            'tf': self.tf,
        }
