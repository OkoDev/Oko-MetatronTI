#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Суточный учёт трафика: счётчики адаптеров в CSV раз в N минут.

🔴 Зачем (05.10): за сутки трафик VPN мерился окнами по 1–10 минут и соврал ТРИЖДЫ
в обе стороны — «вклад в пределах шума», «удваивает туннель», «выигрыша нет».
Серия из трёх десятиминутных окон в ОДНОМ режиме дала 26.69 / 9.17 / 8.93 ГБ/сут,
то есть разброс втрое. Причина: прогрев после рестарта заливает REST-доборами,
а бот за день перезапускается десятки раз. Вывод: трафик меряется СУТКАМИ,
и окна с рестартом надо отбрасывать — для этого пишем uptime бота рядом.

Запуск (pm2):  python scripts/traffic_log.py
Отчёт:         python scripts/traffic_log.py --report [часов]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "oko_feed" / "traffic_log.csv"
ADAPTERS = ("happ-xray", "Ethernet")
INTERVAL_SEC = 600          # 10 минут: мельче — ловим фазу скана, крупнее — теряем детали
WARMUP_SEC = 900            # окно считается «прогревом», если бот моложе этого


def _counters() -> dict:
    """rx/tx по адаптерам одним вызовом PowerShell (латиница — кириллица в -Command ломает парсер)."""
    names = ",".join(f"'{a}'" for a in ADAPTERS)
    ps = (f"Get-NetAdapterStatistics -Name {names} | "
          "ForEach-Object { \"$($_.Name);$($_.ReceivedBytes);$($_.SentBytes)\" }")
    kw = {}
    if sys.platform == "win32":
        # 12.10: под pm2 у процесса нет консоли — powershell получал новую, и Windows Terminal показывал её окном
        # каждые 10 минут (поймано ловушкой окон). SW_HIDE — то же, что Python сам ставит при shell=True.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                          # SW_HIDE
        kw["startupinfo"] = si
    try:
        p = subprocess.run(["powershell", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=60, **kw)
        out = {}
        for line in (p.stdout or "").strip().splitlines():
            parts = line.strip().split(";")
            if len(parts) == 3:
                out[parts[0]] = (int(parts[1]), int(parts[2]))
        return out
    except Exception:                               # noqa: BLE001
        return {}


def _bot_uptime_sec() -> int:
    """Сколько живёт oko-bot: окна сразу после рестарта — прогрев, их не усредняем."""
    try:
        import json
        p = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=60, shell=True)
        for proc in json.loads(p.stdout or "[]"):
            if proc.get("name") == "oko-bot":
                return int((time.time() * 1000 - proc["pm2_env"]["pm_uptime"]) / 1000)
    except Exception:                               # noqa: BLE001
        pass
    return -1


def run() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    new = not OUT.exists()
    prev = _counters()
    prev_t = time.time()
    print(f"[traffic] пишу в {OUT.name}, интервал {INTERVAL_SEC} с, адаптеры: {', '.join(ADAPTERS)}",
          flush=True)
    while True:
        time.sleep(INTERVAL_SEC)
        cur, now = _counters(), time.time()
        dt_min = (now - prev_t) / 60
        up = _bot_uptime_sec()
        rows = []
        for a in ADAPTERS:
            if a not in cur or a not in prev:
                continue
            rx = (cur[a][0] - prev[a][0]) / 1024 / dt_min          # КБ/мин
            tx = (cur[a][1] - prev[a][1]) / 1024 / dt_min
            rows.append({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "adapter": a,
                "rx_kb_min": round(rx, 1),
                "tx_kb_min": round(tx, 1),
                "rx_gb_day": round(rx * 1440 / 1024 / 1024, 2),
                "bot_uptime_sec": up,
                "warmup": int(0 <= up < WARMUP_SEC),               # окно после рестарта
            })
        if rows:
            with OUT.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                if new:
                    w.writeheader()
                    new = False
                w.writerows(rows)
            vpn = next((r for r in rows if r["adapter"] == "happ-xray"), None)
            if vpn:
                print(f"[traffic] VPN {vpn['rx_gb_day']} ГБ/сут"
                      f"{' (прогрев)' if vpn['warmup'] else ''}", flush=True)
        prev, prev_t = cur, now


def report(hours: float) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                               # noqa: BLE001
        pass
    if not OUT.exists():
        print("лога ещё нет — запусти учёт: pm2 start ... traffic_log.py")
        return 1
    cutoff = time.time() - hours * 3600
    data: dict[str, list] = {a: [] for a in ADAPTERS}
    warm: dict[str, int] = {a: 0 for a in ADAPTERS}
    with OUT.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["ts"]).timestamp()
            except Exception:                       # noqa: BLE001
                continue
            if ts < cutoff or r["adapter"] not in data:
                continue
            if r.get("warmup") == "1":
                warm[r["adapter"]] += 1             # прогрев в статистику НЕ берём
                continue
            data[r["adapter"]].append(float(r["rx_gb_day"]))
    print(f"ТРАФИК ЗА {hours:.0f} ч (окна по {INTERVAL_SEC // 60} мин, прогревы исключены)\n")
    for a in ADAPTERS:
        v = sorted(data[a])
        if not v:
            print(f"  {a:<12} данных нет (окон прогрева: {warm[a]})")
            continue
        med = v[len(v) // 2]
        print(f"  {a:<12} медиана {med:>6.2f} ГБ/сут · p90 {v[int(len(v) * 0.9)]:>6.2f} · "
              f"мин {v[0]:>5.2f} · макс {v[-1]:>6.2f} · окон {len(v)} (прогрев {warm[a]})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", nargs="?", const=24, type=float, help="отчёт за N часов (по умолчанию 24)")
    a = ap.parse_args()
    sys.exit(report(a.report) if a.report else run())
