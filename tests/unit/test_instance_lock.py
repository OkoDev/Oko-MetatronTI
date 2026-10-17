# -*- coding: utf-8 -*-
"""Single-instance на замке ОС (core/infra/instance_lock.py, инцидент 15–17.10: два бота 45 ч).

Проверяется на настоящих процессах: гонка в одну миллисекунду, kill держателя, ожидание под pm2.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Держатель: берёт замок (ждёт старта до момента T, чтобы все стартовали одновременно), печатает итог, держит HOLD с.
_HOLDER = """
import os, sys, time
sys.path.insert(0, {root!r})
from core.infra import instance_lock
t_go, hold, wait_s = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
while time.time() < t_go:
    pass
ok = instance_lock.acquire(sys.argv[1], wait_s=wait_s)
print("1" if ok else "0", flush=True)
if ok:
    time.sleep(hold)
"""


def _spawn(lock, t_go=0.0, hold=0.0, wait_s=0.0):
    return subprocess.Popen([sys.executable, "-c", _HOLDER.format(root=ROOT), lock, str(t_go), str(hold), str(wait_s)],
                            stdout=subprocess.PIPE, text=True)


def test_race_exactly_one_wins(tmp_path):
    """15.10: два экземпляра в одну миллисекунду оба признали lock с мёртвым PID осиротевшим и оба его забрали.
    Условие то же — в файле PID мёртвого процесса; теперь замок получает ровно один из восьми."""
    lock = str(tmp_path / "bot_instance.lock")
    with open(lock, "w", encoding="utf-8") as f:
        f.write("4294967")                        # PID мёртвого прежнего бота (BSOD/kill)
    t_go = time.time() + 3.0                     # все процессы успеют импортироваться и стартуют разом
    procs = [_spawn(lock, t_go=t_go, hold=4.0) for _ in range(8)]
    results = [p.stdout.readline().strip() for p in procs]
    for p in procs:
        p.wait(timeout=30)
    assert results.count("1") == 1, results


def test_lock_released_when_holder_killed(tmp_path):
    """kill/BSOD не оставляет «осиротевший» замок: ОС снимает его со смертью процесса."""
    from core.infra import instance_lock
    lock = str(tmp_path / "bot_instance.lock")
    holder = _spawn(lock, hold=60.0)
    assert holder.stdout.readline().strip() == "1"
    assert instance_lock.holder_pid(lock) == holder.pid        # PID читается, пока замок держат
    probe = _spawn(lock)
    assert probe.stdout.readline().strip() == "0"              # занят — второй не проходит
    probe.wait(timeout=30)
    holder.kill()                                              # TerminateProcess — atexit не работает
    holder.wait(timeout=30)
    after = _spawn(lock)
    assert after.stdout.readline().strip() == "1"
    after.wait(timeout=30)


def test_waiter_takes_over_after_holder_exits(tmp_path):
    """Под pm2 новый экземпляр ждёт, пока старый договорит, а не выходит с кодом 1 (→ лишний спавн pm2)."""
    lock = str(tmp_path / "bot_instance.lock")
    holder = _spawn(lock, hold=3.0)
    assert holder.stdout.readline().strip() == "1"
    t0 = time.time()
    waiter = _spawn(lock, wait_s=20.0)
    assert waiter.stdout.readline().strip() == "1"
    assert 1.0 < time.time() - t0 < 15.0
    holder.wait(timeout=30)
    waiter.wait(timeout=30)
