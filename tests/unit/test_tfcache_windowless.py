# -*- coding: utf-8 -*-
"""Воркеры Pool в tfcache — без окон на Windows (паспорт инструмента, вид B).

14.10: `tfcache build` (руками и из ночной pm2-задачи 04:20) плодил пустые python-окна — multiprocessing
со spawn даёт дочерним процессам новое окно консоли. Фикс: воркеры запускаются через pythonw.exe. Если
переключение собьётся — окна полезут снова и молча, поэтому эффект функции под тестом."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import multiprocessing.spawn as spw
import scripts.tfcache as tfcache


@pytest.mark.skipif(sys.platform != "win32", reason="окна консоли — поведение только Windows")
def test_workers_use_pythonw_on_windows():
    """После _use_windowless_workers исполнитель воркеров — pythonw.exe (без окна), если он есть рядом."""
    if not Path(sys.executable).with_name("pythonw.exe").exists():
        pytest.skip("pythonw.exe нет рядом с интерпретатором")
    try:
        tfcache._use_windowless_workers()
        assert spw.get_executable().lower().endswith("pythonw.exe")
    finally:
        spw.set_executable(sys.executable)   # вернуть обычный исполнитель остальным тестам


def test_noop_off_windows(monkeypatch):
    """На не-Windows функция ничего не меняет (исполнитель не трогается)."""
    monkeypatch.setattr(sys, "platform", "linux")
    before = spw.get_executable()
    tfcache._use_windowless_workers()
    assert spw.get_executable() == before
