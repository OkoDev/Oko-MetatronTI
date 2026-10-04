#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Проверка триггеров N21 — пора ли уходить с ccxt.pro на свой WS-клиент.

Зачем прибор, а не строка в бэклоге: сегодня же выяснилось, что N6, N17 и N18
висели открытыми, хотя давно закрылись, — никто их не опрашивал. Триггер без
измерения живёт ровно так же. Здесь пороги из замера 04.10 проверяются числом.

Запуск:  python scripts/check_n21_triggers.py
Выход:   0 — ни один триггер не сработал; 1 — сработал хотя бы один.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from statistics import median

# ── пороги (база — замер 04.10, см. бэклог N21) ──────────────────────────────
VPN_GB_PER_DAY = 12.0     # сентябрьский бюджет трафика
SCAN_MEDIAN_SEC = 400     # база 255 с
SCAN_MIN_SAMPLE = 30      # меньше — не выборка (04.10 две точки дали неверный знак)
SUBS_LIMIT = 600          # overhead ccxt.pro нелинеен (плато 750 с при 240 парах)
LOOP_LAG_SEC = 0.5        # прямой измеритель перегрузки loop ([EventLoop] lag), база 04.10: 0.015-0.031 с
PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
         "LINK/USDT", "AVAX/USDT", "ADA/USDT"]


def _logs(n: int = 20000) -> str:
    p = subprocess.run(["pm2", "logs", "oko-bot", "--lines", str(n), "--nostream"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=True)
    return p.stdout or ""


def scan_period(txt: str) -> tuple[float | None, int]:
    """Медиана периода скана по НЕСКОЛЬКИМ парам (одна пара ничего не доказывает)."""
    gaps: list[int] = []
    for pr in PAIRS:
        ts = re.findall(rf"(\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*\[SMC_SNAP\] {re.escape(pr)}", txt)
        sec = [datetime.fromisoformat(t).timestamp() for t in ts]
        gaps += [round(b - a) for a, b in zip(sec, sec[1:]) if 20 < (b - a) < 3000]
    return (median(gaps) if gaps else None), len(gaps)


def ws_state() -> dict:
    """Подписки и ошибки WsFeed — из селфтеста Куба (сфера WS)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/cube/selftest", timeout=30) as r:
            d = json.load(r)
        for x in d.get("results", []):
            if x.get("code") == "WS":
                m = re.search(r"tickers=(\d+)", x.get("detail", ""))
                e = re.search(r"errors=(\d+)", x.get("detail", ""))
                return {"status": x.get("status"), "tickers": int(m.group(1)) if m else 0,
                        "errors": int(e.group(1)) if e else 0, "detail": x.get("detail", "")}
    except Exception as ex:                      # noqa: BLE001
        return {"ошибка": str(ex)[:80]}
    return {}


def vpn_gb_per_day() -> float | None:
    """Трафик туннеля за 60 с → оценка в сутки. PowerShell: ТОЛЬКО латиница в -Command."""
    ps = ("$a=(Get-NetAdapterStatistics -Name 'happ-xray').ReceivedBytes; Start-Sleep -Seconds 60; "
          "$b=(Get-NetAdapterStatistics -Name 'happ-xray').ReceivedBytes; "
          "Write-Output ([math]::Round(($b-$a)*1440/1GB,2))")
    try:
        p = subprocess.run(["powershell", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=180)
        return float((p.stdout or "").strip().replace(",", "."))
    except Exception:                            # noqa: BLE001
        return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                            # noqa: BLE001
        pass

    txt = _logs()
    fired: list[str] = []
    print("ТРИГГЕРЫ N21 (уход с ccxt.pro) — пороги из замера 04.10\n")

    med, n = scan_period(txt)
    if med is None:
        print("  нагрузка   : период скана не определён (мало строк в логе)")
    elif n < SCAN_MIN_SAMPLE:
        print(f"  нагрузка   : медиана {med:.0f} с, но выборка мала (n={n} < {SCAN_MIN_SAMPLE}) — вывод не делаем")
    else:
        ok = med <= SCAN_MEDIAN_SEC
        print(f"  нагрузка   : медиана скана {med:.0f} с (n={n}) · порог {SCAN_MEDIAN_SEC} — {'ок' if ok else 'СРАБОТАЛ'}")
        if not ok:
            fired.append(f"период скана {med:.0f} с > {SCAN_MEDIAN_SEC}")

    # 🔴 04.10: сначала сюда был вписан счётчик DEGRADED — и прибор сразу соврал.
    # «[health] BingX DEGRADED — latency=3047ms» это ЗАДЕРЖКА БИРЖИ, к ccxt.pro
    # отношения не имеет. Перегрузку loop меряет [EventLoop] lag перед scan_gather.
    slow = len(re.findall(r"(?i)slow callback|Executing <", txt))
    lags = [float(v) for v in re.findall(r"\[EventLoop\] lag ([\d.]+)s", txt)]
    if lags:
        lag_med = median(lags)
        ok = lag_med <= LOOP_LAG_SEC and slow == 0
        print(f"  loop       : lag медиана {lag_med:.3f} с (n={len(lags)}) · slow callbacks {slow} · "
              f"порог {LOOP_LAG_SEC} с — {'ок' if ok else 'СРАБОТАЛ'}")
        if lag_med > LOOP_LAG_SEC:
            fired.append(f"lag event loop {lag_med:.2f} с > {LOOP_LAG_SEC}")
    else:
        print(f"  loop       : замеров lag нет · slow callbacks {slow}")
    if slow:
        fired.append(f"slow callbacks {slow}")

    degr = len(re.findall(r"BingX DEGRADED", txt))
    if degr:
        print(f"  (справочно): BingX DEGRADED {degr} — задержка БИРЖИ, не loop; триггером не считается")

    ws = ws_state()
    if "ошибка" in ws:
        print(f"  подписки   : селфтест недоступен ({ws['ошибка']})")
    else:
        t = ws.get("tickers", 0)
        print(f"  подписки   : тикеров {t} · порог {SUBS_LIMIT} · статус {ws.get('status')} — "
              f"{'ок' if t <= SUBS_LIMIT else 'СРАБОТАЛ'}")
        if t > SUBS_LIMIT:
            fired.append(f"подписок {t} > {SUBS_LIMIT}")
        if ws.get("errors", 0) > 0:
            fired.append(f"ошибки WsFeed {ws['errors']}")

    gb = vpn_gb_per_day()
    if gb is None:
        print("  трафик     : не измерен (нет адаптера happ-xray?)")
    else:
        print(f"  трафик VPN : ~{gb} ГБ/сут · порог {VPN_GB_PER_DAY} — {'ок' if gb <= VPN_GB_PER_DAY else 'СРАБОТАЛ'}")
        if gb > VPN_GB_PER_DAY:
            fired.append(f"VPN {gb} ГБ/сут > {VPN_GB_PER_DAY}")

    print("\n  продукт    : нужна ли тиковая цена В ШИНЕ для исполнения на LTF — решает человек")

    if fired:
        print("\n🔔 СРАБОТАЛО: " + " · ".join(fired))
        print("   → поднимать N21: перенос WsFeed на свой клиент + отдельный процесс")
        return 1
    print("\nни один триггер не сработал — N21 ждёт")
    return 0


if __name__ == "__main__":
    sys.exit(main())
