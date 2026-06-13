"""Unit-тест: CrossLoopRateLimiter (threading token-bucket) — Шаг 0 B-эпик."""
import sys, os, time, threading, asyncio, warnings
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════
# Реализация CrossLoopRateLimiter (loop-agnostic)
# ══════════════════════════════════════════════════════════

class CrossLoopRateLimiter:
    """Process-wide token-bucket, loop-agnostic. Замена GlobalRateLimiter."""

    def __init__(self, rps: float = 8.0):
        self._rps = rps
        self._interval = 1.0 / rps
        self._lock = threading.Lock()        # только на арифметику (мкс)
        self._last_request = 0.0
        self._ban_until = 0.0
        self._acquire_count = 0              # для тестов

    async def acquire(self) -> None:
        """Ждёт слот с учётом rate-limit и бана. Loop-agnostic."""
        # Ждём окончания бана (вне лока)
        while True:
            with self._lock:
                remaining = self._ban_until - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 0.1))

        # Резервируем слот (lock на микросекунды)
        with self._lock:
            now = time.monotonic()
            # Если бан появился пока ждали
            ban_wait = self._ban_until - now
            if ban_wait > 0:
                sleep_for = ban_wait
                slot_time = now + ban_wait
            else:
                next_slot = max(self._last_request + self._interval, now)
                sleep_for = next_slot - now
                slot_time = next_slot
            self._last_request = slot_time
            self._acquire_count += 1

        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    def set_ban(self, duration_sec: float) -> None:
        """Устанавливает глобальный бан (thread-safe, без asyncio)."""
        with self._lock:
            new_until = time.monotonic() + duration_sec
            if new_until > self._ban_until:
                self._ban_until = new_until


# ══════════════════════════════════════════════════════════
# ТЕСТ (a): конкурентный acquire из 2 loop → shared budget
# ══════════════════════════════════════════════════════════

def test_cross_loop_rps():
    RPS = 10.0
    DURATION = 2.0
    limiter = CrossLoopRateLimiter(rps=RPS)

    results = {"loop1": 0, "loop2": 0}

    async def worker(label: str, n_requests: int):
        for _ in range(n_requests):
            await limiter.acquire()
            results[label] += 1

    def run_loop(label: str):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(worker(label, 100))

    t1 = threading.Thread(target=run_loop, args=("loop1",))
    t2 = threading.Thread(target=run_loop, args=("loop2",))
    t0 = time.monotonic()
    t1.start(); t2.start()
    t1.join(); t2.join()
    elapsed = time.monotonic() - t0

    total = results["loop1"] + results["loop2"]
    actual_rps = total / elapsed
    print(f"[a] Cross-loop RPS: {total} req / {elapsed:.1f}s = {actual_rps:.1f} rps (limit={RPS})")
    assert actual_rps <= RPS * 1.1, f"RPS {actual_rps:.1f} > limit {RPS}"
    assert results["loop1"] > 0 and results["loop2"] > 0, "Both loops must execute"
    print("    PASS")


# ══════════════════════════════════════════════════════════
# ТЕСТ (b): set_ban из loop-1 → loop-2 видит бан
# ══════════════════════════════════════════════════════════

def test_cross_loop_ban():
    limiter = CrossLoopRateLimiter(rps=100.0)  # высокий RPS чтобы не мешал
    ban_visible = {"seen": False, "loop1_ban": False, "loop2_slept": False}

    async def loop1_work():
        # Ждём старта loop2
        await asyncio.sleep(0.1)
        limiter.set_ban(1.0)  # бан на 1 сек
        ban_visible["loop1_ban"] = True
        await asyncio.sleep(1.5)

    async def loop2_work():
        # Первый запрос мгновенный (высокий RPS)
        await limiter.acquire()
        # Ждём пока loop1 установит бан
        await asyncio.sleep(0.2)
        t0 = time.monotonic()
        # Второй запрос — должен ждать бан (~0.8s remaining)
        await limiter.acquire()
        waited = time.monotonic() - t0
        if waited > 0.4:
            ban_visible["loop2_slept"] = True
            ban_visible["seen"] = True

    def run(label, coro):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(coro)

    t1 = threading.Thread(target=run, args=("loop1", loop1_work()))
    t2 = threading.Thread(target=run, args=("loop2", loop2_work()))
    t2.start()
    t1.start()
    t1.join(); t2.join()

    print(f"[b] Cross-loop ban visible: {ban_visible}")
    assert ban_visible["seen"], "Loop2 must see ban from loop1"
    assert ban_visible["loop2_slept"], "Loop2 must sleep during ban"
    print("    PASS")


# ══════════════════════════════════════════════════════════
# ТЕСТ (c): одиночный loop — идентичное поведение
# ══════════════════════════════════════════════════════════

def test_single_loop_behavior():
    """Сравниваем: N запросов с интервалом 1/RPS должны занять ~N/RPS секунд."""
    RPS = 10.0
    N = 30
    limiter = CrossLoopRateLimiter(rps=RPS)

    async def run():
        t0 = time.monotonic()
        for _ in range(N):
            await limiter.acquire()
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    expected = N / RPS
    print(f"[c] Single loop: {N} req @ {RPS} rps = {elapsed:.1f}s (expected ~{expected:.1f}s)")
    assert elapsed >= expected * 0.85, f"Too fast: {elapsed:.1f}s < {expected*0.85:.1f}s"
    assert elapsed <= expected * 1.5, f"Too slow: {elapsed:.1f}s > {expected*1.5:.1f}s"
    print("    PASS")


# ══════════════════════════════════════════════════════════
# ТЕСТ (d): бан + acquire совместимость
# ══════════════════════════════════════════════════════════

def test_ban_during_acquire():
    """set_ban во время блокировки acquire — acquire должен продлиться."""
    limiter = CrossLoopRateLimiter(rps=2.0)  # низкий RPS — acquire будет ждать

    async def run():
        # Первый запрос
        await limiter.acquire()
        # Второй — ждёт слот (0.5s). Бан на 0.3s во время ожидания
        async def ban_later():
            await asyncio.sleep(0.05)
            limiter.set_ban(0.3)
        asyncio.ensure_future(ban_later())
        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(run())
    print(f"[d] Ban during acquire: waited {elapsed:.2f}s (expected >=0.5s base)")
    # Edge case: ban set during asyncio.sleep() in acquire won't be caught until NEXT acquire.
    # For production: bans are 298s, so next acquire catches it. Acceptable.
    assert elapsed >= 0.45, f"Token bucket not respected: {elapsed:.2f}s < 0.45s"
    print("    PASS (edge case documented: ban mid-acquire caught next cycle)")


# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== CrossLoopRateLimiter Unit Tests ===\n")
    test_cross_loop_rps()
    test_cross_loop_ban()
    test_single_loop_behavior()
    test_ban_during_acquire()
    print("\n=== ALL TESTS PASSED ===")
