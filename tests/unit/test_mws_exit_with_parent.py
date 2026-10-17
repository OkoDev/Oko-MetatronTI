# -*- coding: utf-8 -*-
"""Воркер MarketWS v2 умирает вместе с ботом (core/infra/market_ws_v2._exit_with_parent, инцидент 17.10:
продюсер 8280 пережил убитого бота на 49 мин — 686 МБ и WS-соединение к бирже)."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# «Бот»: запускает воркер через multiprocessing (spawn, как в бою), печатает его PID и висит.
_PARENT = """
import multiprocessing as mp, sys, time
sys.path.insert(0, {root!r})

def worker():
    from core.infra.market_ws_v2 import _exit_with_parent
    _exit_with_parent()
    while True:
        time.sleep(1)

if __name__ == "__main__":
    p = mp.Process(target=worker, daemon=True)
    p.start()
    print(p.pid, flush=True)
    time.sleep(120)
"""


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def test_worker_dies_when_parent_is_killed(tmp_path):
    script = tmp_path / "parent.py"
    script.write_text(_PARENT.format(root=ROOT), encoding="utf-8")
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline().strip())
    time.sleep(3)                                   # воркер импортировал модуль и поставил сторожа
    assert _alive(child_pid)
    parent.kill()                                   # TerminateProcess — как Stop-Process -Force / os._exit без atexit
    parent.wait(timeout=30)
    deadline = time.time() + 15
    while time.time() < deadline and _alive(child_pid):
        time.sleep(0.5)
    alive = _alive(child_pid)
    if alive:
        subprocess.run(["taskkill", "/F", "/PID", str(child_pid)], capture_output=True)
    assert not alive, "воркер пережил родителя — сирота"
