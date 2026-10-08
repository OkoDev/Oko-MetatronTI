"""09.10: правиловый вердикт шины = ATR-тренд 1h/4h, метки ATR_TREND_* (были STRONG_BULL_ZONE/…).

Слова BULL/BEAR/STRONG/WEAK обязаны остаться в метке: дашборд oko-dashboard и dc_agent разбирают её по подстрокам.
"""
import pandas as pd

from core.smc.smc_specialist import fast_smc_verdict


def _df(trend, n=40):
    return pd.DataFrame({"trend": [trend] * n})


def test_labels():
    assert fast_smc_verdict(_df(1), _df(1)) == "ATR_TREND_BULL_STRONG"
    assert fast_smc_verdict(_df(-1), _df(-1)) == "ATR_TREND_BEAR_STRONG"
    assert fast_smc_verdict(_df(1), _df(-1)) == "ATR_TREND_BULL_WEAK"
    assert fast_smc_verdict(_df(-1), None) == "ATR_TREND_BEAR_WEAK"
    assert fast_smc_verdict(_df(0), _df(1)) == "ATR_TREND_NONE"
    assert fast_smc_verdict(_df(1, n=5), _df(1)) is None


def test_substrings_for_consumers():
    v = fast_smc_verdict(_df(1), _df(1)).lower()
    assert "bull" in v and "strong" in v and "bear" not in v
    v = fast_smc_verdict(_df(-1), _df(1)).lower()
    assert "bear" in v and "weak" in v and "bull" not in v
