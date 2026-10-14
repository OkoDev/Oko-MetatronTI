# -*- coding: utf-8 -*-
"""Дымовой тест спутников pm2 — чистая логика вердикта (ARCH-148.6, паспорт инструмента, правило 4).

Инструмент судит 44 процесса и отчитывается в сферу 12; если его вердикт врёт, молчащий демон останется
незамеченным (тень волн молчала 14 дней именно так). Поэтому реконструкция команды, оценка интервала cron
и классификатор покрыты golden-case'ами: по строке с известным ответом на каждую ветку."""
from __future__ import annotations

import scripts.pm2_smoke as sm


# ── reconstruct_cmd: два формата запуска pm2 ──────────────────────────────
def test_cmd_script_with_interpreter():
    """`pm2 start x.py --interpreter python`: интерпретатор отдельно, скрипт в pm_exec_path."""
    cmd = sm.reconstruct_cmd(r"E:\bot\scripts\joint_daily.py", None, "C:/py/python.exe")
    assert cmd == ["C:/py/python.exe", r"E:\bot\scripts\joint_daily.py"]


def test_cmd_python_in_exec_path_args_hold_script():
    """`pm2 start python -- scripts/x.py --flag`: python в pm_exec_path, скрипт и флаги в args."""
    cmd = sm.reconstruct_cmd("python.exe", ["scripts/cache_freshness.py", "--max-age", "3"], "ignored")
    assert cmd == ["python.exe", "scripts/cache_freshness.py", "--max-age", "3"]


def test_cmd_none_args_is_empty():
    assert sm.reconstruct_cmd(r"C:\py\python.exe", None, None) == [r"C:\py\python.exe"]


# ── cron_period_seconds: покрыть все ветки парсера ────────────────────────
def test_cron_every_n_minutes():
    assert sm.cron_period_seconds("*/30 * * * *") == 30 * 60


def test_cron_hourly_fixed_minute():
    assert sm.cron_period_seconds("5 * * * *") == 3600


def test_cron_every_n_hours():
    assert sm.cron_period_seconds("15 */6 * * *") == 6 * 3600


def test_cron_daily():
    assert sm.cron_period_seconds("40 7 * * *") == 86400


def test_cron_weekly_by_dow():
    assert sm.cron_period_seconds("30 6 * * 0") == 7 * 86400


def test_cron_none_and_garbage():
    assert sm.cron_period_seconds(None) is None
    assert sm.cron_period_seconds("broken") is None


# ── classify_proc: cron ───────────────────────────────────────────────────
def test_cron_nonzero_exit_is_failed():
    """joint-daily стоял exit=1 — это и есть громкая находка, которую ждём."""
    level, reason = sm.classify_proc(True, "online", 1, log_age_sec=10, period_sec=86400)
    assert level == "FAILED" and "exit=1" in reason


def test_cron_stopped_exit0_fresh_is_ok():
    """Нормальное состояние cron между прогонами: stopped, exit 0, лог свежий."""
    level, _ = sm.classify_proc(True, "stopped", 0, log_age_sec=3600, period_sec=86400)
    assert level == "OK"


def test_cron_stale_log_flags():
    """Суточный процесс, лог молчит 10 суток → STALE (порог 3× = 3 суток)."""
    level, reason = sm.classify_proc(True, "stopped", 0, log_age_sec=10 * 86400, period_sec=86400)
    assert level == "STALE" and "молчит" in reason


def test_cron_no_log_is_nolog():
    level, _ = sm.classify_proc(True, "stopped", 0, log_age_sec=None, period_sec=86400)
    assert level == "NOLOG"


def test_cron_exit_none_not_failed():
    """exit_code=None (ещё ни разу не отработал) — не провал."""
    level, _ = sm.classify_proc(True, "stopped", None, log_age_sec=3600, period_sec=86400)
    assert level == "OK"


# ── classify_proc: демон ──────────────────────────────────────────────────
def test_daemon_online_fresh_is_ok():
    level, _ = sm.classify_proc(False, "online", None, log_age_sec=600, period_sec=None)
    assert level == "OK"


def test_daemon_not_online_is_failed():
    level, reason = sm.classify_proc(False, "stopped", None, log_age_sec=10, period_sec=None)
    assert level == "FAILED" and "online" in reason


def test_daemon_silent_is_stale():
    """Демон online, но лог молчит дольше суток — ровно случай тени волн (14 дней)."""
    level, reason = sm.classify_proc(False, "online", None, log_age_sec=14 * 86400,
                                     period_sec=None, daemon_max_sec=sm.DAEMON_MAX_AGE_SEC)
    assert level == "STALE" and "молчит" in reason


def test_daemon_silent_boundary_below_threshold_ok():
    level, _ = sm.classify_proc(False, "online", None, log_age_sec=sm.DAEMON_MAX_AGE_SEC - 1,
                                period_sec=None)
    assert level == "OK"


# ── freshest_log_age: пустые и отсутствующие логи пропускаются ────────────
def test_freshest_ignores_empty_log(tmp_path):
    """Демон пишет только в err (out пустой) — берём свежесть err, не считаем демон молчащим.
    Ровно случай oko-api 14.10: out пустой 103 сут, err свежий."""
    import os, time
    out = tmp_path / "x-out.log"; out.write_text("")                 # пустой → пропустить
    err = tmp_path / "x-err.log"; err.write_text("живой лог")
    old = time.time() - 100 * 86400
    os.utime(out, (old, old))                                        # out старый, но пустой
    age = sm.freshest_log_age([str(out), str(err)])
    assert age is not None and age < 60                              # взяли свежий err


def test_freshest_none_when_all_empty_or_missing(tmp_path):
    empty = tmp_path / "e.log"; empty.write_text("")
    assert sm.freshest_log_age([str(empty), str(tmp_path / "nope.log"), None]) is None


# ── active_verdict ─────────────────────────────────────────────────────────
def test_active_ok():
    assert sm.active_verdict(0, "готово: 7 обновлено\n", timed_out=False)[0] == "OK"


def test_active_timeout():
    assert sm.active_verdict(-1, "", timed_out=True)[0] == "TIMEOUT"


def test_active_nonzero_exit_failed():
    assert sm.active_verdict(1, "что-то", timed_out=False)[0] == "FAILED"


def test_active_traceback_failed():
    out = "Traceback (most recent call last):\n  File ...\nValueError"
    assert sm.active_verdict(0, out, timed_out=False)[0] == "FAILED"


def test_active_empty_output_silent():
    assert sm.active_verdict(0, "   \n", timed_out=False)[0] == "SILENT"
