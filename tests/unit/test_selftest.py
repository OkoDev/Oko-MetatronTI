"""
Тесты SelfTest системы (ARCH-14).

Проверяет каждый слой selftest и сводный отчёт.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core.selftest import SelfTest, SelfTestReport, SelfTestResult, run_selftest


# ---------------------------------------------------------------------------
# TestSelfTestResult
# ---------------------------------------------------------------------------

class TestSelfTestResult:
    def test_passed_result(self):
        r = SelfTestResult(layer="L1", name="Test", passed=True, critical=True)
        assert r.passed
        assert r.critical

    def test_failed_result(self):
        r = SelfTestResult(layer="L1", name="Test", passed=False, critical=True, error="bad")
        assert not r.passed
        assert r.error == "bad"


# ---------------------------------------------------------------------------
# TestSelfTestReport
# ---------------------------------------------------------------------------

class TestSelfTestReport:
    def test_all_passed(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="A", passed=True, critical=True),
            SelfTestResult(layer="L2", name="B", passed=True, critical=False),
        ])
        assert report.all_passed
        assert report.critical_passed

    def test_non_critical_fail(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="A", passed=True, critical=True),
            SelfTestResult(layer="L5", name="B", passed=False, critical=False),
        ])
        assert not report.all_passed
        assert report.critical_passed  # критические пройдены

    def test_critical_fail(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="Config", passed=False, critical=True, error="missing key"),
        ])
        assert not report.all_passed
        assert not report.critical_passed

    def test_failed_list(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="A", passed=True, critical=True),
            SelfTestResult(layer="L2", name="B", passed=False, critical=False),
            SelfTestResult(layer="L3", name="C", passed=False, critical=True),
        ])
        assert len(report.failed) == 2
        assert len(report.critical_failed) == 1

    def test_summary_text_contains_layers(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="Config", passed=True, critical=True, duration_ms=5),
            SelfTestResult(layer="L2", name="Imports", passed=False, critical=True,
                           duration_ms=3, error="import fail"),
        ])
        text = report.summary_text()
        assert "L1" in text
        assert "L2" in text
        assert "import fail" in text
        assert "КРИТИЧЕСКИЙ ОТКАЗ" in text  # есть критический провал

    def test_summary_text_all_ok(self):
        report = SelfTestReport(results=[
            SelfTestResult(layer="L1", name="Config", passed=True, critical=True),
        ])
        text = report.summary_text()
        assert "✅" in text
        assert "КРИТИЧЕСКИЙ ОТКАЗ" not in text


# ---------------------------------------------------------------------------
# TestSelfTest layers (unit, без реальных зависимостей)
# ---------------------------------------------------------------------------

class TestSelfTestLayers:
    def test_l2_imports_pass(self):
        """L2: все core модули должны импортироваться."""
        st = SelfTest()
        r = st._test_imports()
        assert r.passed, f"Import fail: {r.error}"
        assert r.layer == "L2"

    def test_l3_indicators_pass(self):
        """L3: индикаторы должны работать на синтетике."""
        st = SelfTest()
        r = st._test_indicators()
        assert r.passed, f"Indicators fail: {r.error}"
        assert "WT" in r.message

    def test_l6_multi_tf_default(self):
        """L6: дефолтный entry_timeframe (15m) валиден."""
        st = SelfTest()
        r = st._test_multi_tf_config()
        assert r.passed

    def test_l6_multi_tf_invalid(self):
        """L6: невалидный конфиг ТФ → fail."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = ["1h", "5m"]  # обратный порядок
        st = SelfTest(config=mock_cfg)
        r = st._test_multi_tf_config()
        assert not r.passed

    def test_l7_pivot_calculator(self):
        """L7: pivot calculator считает корректно."""
        st = SelfTest()
        r = st._test_pivot_calculator()
        assert r.passed, f"Pivot fail: {r.error}"
        assert "PP" in r.message

    def test_l4_database(self):
        """L4: SQLite работает."""
        st = SelfTest()
        r = st._test_database()
        assert r.passed, f"DB fail: {r.error}"


# ---------------------------------------------------------------------------
# TestRunSelftest — интеграционный (без exchange)
# ---------------------------------------------------------------------------

class TestRunSelftest:
    @pytest.mark.asyncio
    async def test_run_all_without_bot(self):
        """Полный прогон без реального бота (exchange замокан)."""
        st = SelfTest()
        with patch.object(st, '_test_exchange', new_callable=AsyncMock) as mock_ex:
            mock_ex.return_value = SelfTestResult(
                layer="L5", name="Exchange API", passed=True, critical=False,
                message="mock",
            )
            # Мокаем _test_config т.к. нет реального config.yaml
            with patch.object(st, '_test_config') as mock_cfg:
                mock_cfg.return_value = SelfTestResult(
                    layer="L1", name="Config", passed=True, critical=True,
                    message="mock config",
                )
                report = await st.run_all()

        # Не менее 8 тестов
        assert len(report.results) >= 8
        assert report.total_duration_ms > 0
        # Все кроме exchange должны быть real results
        for r in report.results:
            assert r.layer in ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12"]

    @pytest.mark.asyncio
    async def test_run_selftest_convenience(self):
        """Тест удобной функции run_selftest()."""
        with patch('core.selftest.SelfTest.run_all', new_callable=AsyncMock) as mock:
            mock.return_value = SelfTestReport(results=[
                SelfTestResult(layer="L1", name="X", passed=True, critical=True),
            ])
            report = await run_selftest()
            assert report.all_passed
