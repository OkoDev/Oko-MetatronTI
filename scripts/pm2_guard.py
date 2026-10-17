# -*- coding: utf-8 -*-
"""ВНЕШНИЙ СТОРОЖ PM2 (11.08.2026) — намеренно ВНЕ pm2.

Инцидент 10.08: машина умерла жёстко (в логе «Lock-файл ОСИРОТЕЛ — владелец мёртв»),
демон PM2 перезапустился ПУСТЫМ и не поднял ни одного процесса. Простой 38 часов
(10.08 00:53 → 11.08 15:07), форвард всё это время не набирался.

Штатный hb-watchdog этого не поймал по конструкции: он живёт ВНУТРИ pm2, поэтому
пустой pm2 = мёртвый сторож вместе со всем остальным. Отсюда правило:
СТОРОЖ НЕ МОЖЕТ ЖИТЬ ВНУТРИ ТОГО, ЧТО ОН СТОРОЖИТ.

Ставится в Windows Task Scheduler (каждые 10 минут). Проверяет oko-bot; если он не
online — делает `pm2 resurrect`. Пишет в logs/pm2_guard.log.

17.10 — ЦЕЛОСТНОСТЬ БОТА. pm2 7 оставляет сирот: при рестарте событие exit старого контейнера под нагрузкой
приходит ПОСЛЕ старта нового, God.handleExit принимает его за падение текущего и спаунит ещё один — текущий
живёт вне учёта pm2 (15.10 → два бота 45 ч, 23 ГБ, машина в свопе). Убить сироту нельзя: его exit pm2 снова
примет за падение и осиротит уже законный экземпляр. Устойчиво лечится только целиком: stop → убить все
oko_mtf.py и их обёртки → пауза → start. Здесь это делается, если (а) бот вне обёртки pm2 или ботов больше
одного — и картина та же через CONFIRM_S (рестарт соседней сессии проходит быстрее); (б) private бота
выше MEM_LIMIT_MB (рост ~1 ГБ/ч, утечка расследуется — потолок, чтобы не встала вся машина).
Запуск вручную: python scripts/pm2_guard.py [--dry-run]"""
import datetime as dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "pm2_guard.log")
WATCH = "oko-bot"          # ключевой процесс: если он лежит — лежит вся торговля
DRY = "--dry-run" in sys.argv
BOT_SCRIPT = "oko_mtf.py"
CONFIRM_S = 60
MEM_LIMIT_MB = 10 * 1024   # 17.10: выбор, не замер — бот + остальная нагрузка в 31,7 ГБ RAM
_HIDDEN = None
if os.name == "nt":        # окно консоли на каждый вызов powershell/taskkill — рецепт памяти 12.10: SW_HIDE
    _HIDDEN = subprocess.STARTUPINFO()
    _HIDDEN.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _HIDDEN.wShowWindow = 0


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def pm2(*args, timeout=120):
    """pm2 через shell: на Windows это pm2.cmd, напрямую не запускается."""
    return subprocess.run("pm2 " + " ".join(args), shell=True, capture_output=True,
                          text=True, timeout=timeout, encoding="utf-8", errors="replace")


def online_names():
    r = pm2("jlist")
    if r.returncode != 0 or not r.stdout.strip():
        return None                      # демон не отвечает — это само по себе тревога
    try:
        data = json.loads(r.stdout[r.stdout.index("["):])
    except Exception as e:
        log(f"ОШИБКА разбора jlist: {e}")
        return None
    return {p["name"] for p in data if p.get("pm2_env", {}).get("status") == "online"}


def bot_snapshot():
    """→ (pm2_pid, [(pid, ppid, private_mb, родитель_это_обёртка_pm2)] по всем python с oko_mtf.py,
    [(pid, мёртвый_parent_pid)] — дочерние процессы multiprocessing, чей родитель уже умер)."""
    ps = ("$all = Get-CimInstance Win32_Process; $ids = @{}; $all | ForEach-Object { $ids[[int]$_.ProcessId] = 1 }; "
          f"$all | Where-Object {{ $_.Name -eq 'python.exe' -and $_.CommandLine -like '*{BOT_SCRIPT}*' }} | "
          "ForEach-Object { $p = $_; $par = $all | Where-Object ProcessId -eq $p.ParentProcessId; "
          "'BOT {0} {1} {2} {3}' -f $p.ProcessId, $p.ParentProcessId, [math]::Round($p.PrivatePageCount/1MB), "
          "[int]([string]$par.CommandLine -like '*ProcessContainerFork*') }; "
          "$all | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*multiprocessing-fork*' } | "
          "ForEach-Object { $m = [regex]::Match([string]$_.CommandLine, 'parent_pid=(\\d+)'); "
          "if ($m.Success -and -not $ids.ContainsKey([int]$m.Groups[1].Value)) { "
          "'ORPHAN {0} {1}' -f $_.ProcessId, $m.Groups[1].Value } }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                         text=True, timeout=120, startupinfo=_HIDDEN, stdin=subprocess.DEVNULL).stdout
    rows = [ln.split() for ln in out.splitlines()]
    bots = [tuple(int(x) for x in r[1:]) for r in rows if len(r) == 5 and r[0] == "BOT"]
    orphans = [tuple(int(x) for x in r[1:]) for r in rows if len(r) == 3 and r[0] == "ORPHAN"]
    r = pm2("pid", WATCH)
    try:
        pm2_pid = int((r.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        pm2_pid = 0
    return pm2_pid, bots, orphans


def kill_tree(pid):
    """/T — вместе с дочерними (WS-воркер бота): pm2 на этой машине убивает из дерева ровно 1 pid — обёртку."""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30,
                   startupinfo=_HIDDEN, stdin=subprocess.DEVNULL)


def sweep_orphans(orphans):
    """Дочерние multiprocessing с мёртвым родителем бесполезны, но живут: 17.10 WS-воркер убитого бота 49 мин
    держал 686 МБ и соединение к бирже. Перезапуск бота для этого не нужен."""
    if not orphans:
        return
    if DRY:
        log(f"--dry-run: сироты multiprocessing (pid, мёртвый родитель) НЕ убиты: {orphans}")
        return
    for pid, _ in orphans:
        kill_tree(pid)
    log(f"СИРОТЫ multiprocessing убиты (pid, мёртвый родитель): {orphans}")
    alert(f"убиты сироты multiprocessing (родитель мёртв): {orphans}")


def bot_anomaly(pm2_pid, bots):
    """Подпись аномалии (пусто = норма): ботов больше одного или бот не под той обёрткой, которую знает pm2."""
    if pm2_pid and (len(bots) > 1 or any(ppid != pm2_pid for _, ppid, _, _ in bots)):
        return (pm2_pid, tuple(sorted(b[0] for b in bots)))
    return ()


def alert(text):
    try:
        sys.path.insert(0, ROOT)
        from oko_feed.alerts import send_tg
        send_tg(f"🛡 <b>PM2-GUARD</b>\n\n{text}\n\n#SYSTEM", channel="system")
    except Exception as e:  # noqa: BLE001 — сторож не падает от TG
        log(f"TG: {e}")


def heal_bot(reason):
    """stop → убить все oko_mtf.py и их обёртки pm2 → пауза (запоздавшие exit при stopped безвредны) → start."""
    log(f"ЛЕЧЕНИЕ {WATCH}: {reason}")
    if DRY:
        log("--dry-run: лечение пропущено")
        return
    pm2("stop", WATCH)
    _, bots, _ = bot_snapshot()
    victims = [b[1] if b[3] == 1 else b[0] for b in bots]     # обёртка pm2 → деревом уйдут бот и его воркер
    for pid in victims:
        kill_tree(pid)
    log(f"убиты деревом {victims}")
    time.sleep(10)
    sweep_orphans(bot_snapshot()[2])
    pm2("start", WATCH)
    deadline = time.time() + 150
    pm2_pid, bots = 0, []
    while time.time() < deadline:
        time.sleep(15)
        pm2_pid, bots, _ = bot_snapshot()
        if len(bots) == 1 and bots[0][1] == pm2_pid:
            break
    ok = len(bots) == 1 and bots[0][1] == pm2_pid
    log(f"после лечения: {'ОДИН бот под pm2' if ok else 'НЕ ВЫЛЕЧЕН'} (pm2 pid {pm2_pid}, боты {bots})")
    alert(f"{WATCH}: {reason}\n→ stop · убиты {len(victims)} процессов · start\n"
          f"итог: {'✅ один бот под pm2' if ok else '🔴 НЕ ВЫЛЕЧЕН — смотреть руками'}")


def check_bot_integrity():
    pm2_pid, bots, orphans = bot_snapshot()
    sweep_orphans(orphans)
    sig = bot_anomaly(pm2_pid, bots)
    if sig:
        log(f"ПОДОЗРЕНИЕ: pm2 pid {pm2_pid}, боты (pid, ppid, MB, под обёрткой) {bots} — перепроверка через {CONFIRM_S} с")
        time.sleep(CONFIRM_S)
        pm2_pid, bots, _ = bot_snapshot()
        if bot_anomaly(pm2_pid, bots) == sig:
            return heal_bot(f"сирота/дубль бота устоял {CONFIRM_S} с: pm2 pid {pm2_pid}, боты {bots}")
        log("картина сменилась (шёл рестарт) — не трогаю")
        return
    if len(bots) == 1 and bots[0][2] > MEM_LIMIT_MB:
        heal_bot(f"память бота {bots[0][2]} MB > потолка {MEM_LIMIT_MB} MB")


def main():
    names = online_names()
    if names is None:
        log("ТРЕВОГА: pm2 не отвечает или отдал мусор")
    elif WATCH in names:
        log(f"ok {WATCH} online (живых процессов {len(names)})")
        try:
            check_bot_integrity()
        except Exception as e:  # noqa: BLE001 — сторож не должен умереть от собственной проверки
            log(f"ОШИБКА проверки целостности: {type(e).__name__}: {e}")
        return 0
    else:
        log(f"ТРЕВОГА: {WATCH} НЕ online (живых {len(names)}: {sorted(names)})")
    if DRY:
        log("--dry-run: воскрешение пропущено")
        return 1
    r = pm2("resurrect", timeout=300)
    log(f"resurrect rc={r.returncode} {(r.stdout or '').strip()[-300:]}")
    after = online_names() or set()
    ok = WATCH in after
    log(f"после воскрешения: {WATCH} {'ПОДНЯТ' if ok else 'ВСЁ ЕЩЁ ЛЕЖИТ'} (живых {len(after)})")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
