"""
Регрессия семьи ВОЛН в матрице (28.08.2026).

Повод — вопрос Егора «с микроструктурой ты и волны по-другому считать будешь?».
Проверка вскрыла, что ног (волн) в матрице не было ВООБЩЕ: грep `leg` по
`combinator_core` и `matrix_full` дал 0. Слом — это ТОЧКА, нога — ОТРЕЗОК; от ноги
механика отмеряет фибо, и до сих пор спросить про неё было нечем.

Второе, что вскрылось: в проекте ДВА движка структуры. Волны есть только у
`oko_sm_engine` (`leg_history`), поэтому семья берётся оттуда, а не строится заново
([[principle_reuse_not_duplication]]). Тест `test_engines_agree` охраняет именно это:
пока движки согласны, две семьи (SCALES и ВОЛНЫ) описывают одну реальность.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from matrix_full import MAJOR_LEN, MINOR_LEN, wave_features        # noqa: E402


def _series(n=4000, seed=17):
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 4, 0.06), np.full(n // 4, -0.06),
                            np.full(n // 4, 0.0), np.full(n - 3 * (n // 4), 0.04)])
    close = 100 + np.cumsum(rng.normal(0, 0.4, n) + drift)
    wick = np.abs(rng.normal(0, 0.5, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "close": close,
                         "high": close + wick, "low": close - wick,
                         "volume": rng.uniform(50, 200, n)}, index=idx)


def test_causal_future_does_not_leak():
    """🔴 Усечение будущего не меняет уже посчитанные ноги."""
    df = _series()
    cut = 2500
    full, trunc = wave_features(df, "15m"), wave_features(df.iloc[:cut], "15m")
    edge = cut - MAJOR_LEN * 2
    bad = []
    for c in trunc.columns:
        a, b = full[c].iloc[:edge].values, trunc[c].iloc[:edge].values
        if (~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, equal_nan=True))).any():
            bad.append(c)
    assert not bad, f"look-ahead в волнах: {bad}"


def test_leg_pos_is_bounded():
    """
    Положение внутри ноги обязано лежать в [0,1] почти всегда: `extreme` у движка —
    это бегущий trail, он не может быть превышен. Массовый выход за границы означал бы,
    что origin и extreme перепутаны местами или взяты из разных ног.
    """
    E = wave_features(_series(), "15m")
    p = E["leg_pos_15m"].dropna()
    assert len(p), "ни одной ноги не размечено"
    inside = ((p >= 0) & (p <= 1)).mean()
    assert inside > 0.9, f"внутри ноги только {inside*100:.1f}% баров"
    assert (p > 1.001).mean() < 0.01, "цена систематически ЗА экстремумом — ноги перепутаны"


def test_retr_is_complement_of_pos():
    """Глубина отката — производная от положения, а не независимое число."""
    E = wave_features(_series(), "15m")
    m = E[["leg_pos_15m", "leg_retr_15m"]].dropna()
    assert np.allclose(m.leg_pos_15m + m.leg_retr_15m, 1.0)


def test_ote_zone_matches_its_definition():
    """🔴 НЕГАТИВНЫЙ: зона OTE обязана совпадать со своим определением 0.618-0.79."""
    E = wave_features(_series(), "15m")
    m = E[["leg_retr_15m", "leg_in_ote_15m"]].dropna()
    expected = ((m.leg_retr_15m >= 0.618) & (m.leg_retr_15m <= 0.79)).astype(float)
    assert np.array_equal(m.leg_in_ote_15m.values, expected.values)
    share = m.leg_in_ote_15m.mean()
    assert 0.01 < share < 0.4, f"зона OTE покрывает {share*100:.1f}% — порог сломан"


def test_minor_waves_nest_inside_major_leg():
    """
    🔑 ВЛОЖЕННОСТЬ: в старшую ногу обязано укладываться НЕСКОЛЬКО младших волн.
    Если счётчик выродится в 0 или 1, «вложенность» окажется словом без содержания.
    """
    E = wave_features(_series(), "15m")
    k = E["leg_minor_breaks_15m"].dropna()
    assert len(k), "ноги не размечены"
    assert k.median() >= 2, f"медиана младших волн в ноге {k.median():.0f} — вложенности нет"
    assert (k < 0).sum() == 0, "отрицательное число волн — счётчик считает не от origin"


def test_engines_agree_on_breaks():
    """
    🔴 ДВА ДВИЖКА СТРУКТУРЫ В ПРОЕКТЕ. Волны берутся у `oko_sm_engine`, сломы для
    семьи SCALES — у `smc_engine`. Пока их события совпадают, обе семьи описывают одну
    реальность. Расхождение = две разные структуры под одними именами.
    """
    from core.smc.oko_sm_engine import run_structure
    from core.smc.smc_engine import detect_structure_breaks
    df = _series()
    dd = df.reset_index(drop=True)
    st = run_structure(dd, swing_len=MAJOR_LEN, internal_len=MINOR_LEN)
    for internal, ln in ((True, MINOR_LEN), (False, MAJOR_LEN)):
        eng = {e.i for e in st.events if e.internal is internal}
        smc = {int(b.idx) for b in detect_structure_breaks(dd, length=ln)}
        if not eng and not smc:
            continue
        jac = len(eng & smc) / max(len(eng | smc), 1)
        assert jac > 0.95, (
            f"движки разошлись на length={ln}: совпадение {jac*100:.1f}% "
            f"({len(eng)} против {len(smc)} событий)")


def test_no_constant_columns():
    E = wave_features(_series(), "15m")
    assert len(E.columns) >= 12, f"семья схлопнулась до {len(E.columns)}"
    const = [c for c in E.columns if E[c].dropna().nunique() <= 1]
    assert not const, f"константные признаки: {const}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
