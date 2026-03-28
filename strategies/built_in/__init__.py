"""
Встроенные стратегии торговли.
"""

from strategies.built_in.confluence import MultiSignalStrategy
from strategies.built_in.reversal_scanner_strategy import WtEntryStrategy
from strategies.built_in.mtf_bias import MTFBiasStrategy
from strategies.built_in.conservative import ConservativeStrategy

__all__ = [
    "MultiSignalStrategy",
    "WtEntryStrategy",
    "MTFBiasStrategy",
    "ConservativeStrategy",
]
