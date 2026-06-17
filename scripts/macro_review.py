#!/usr/bin/env python3
"""
Скрипт макро-обзора крипторынка для Сферы 5 КУБа (Cross-Market Node).

Генерирует шаблон обзора в obsidian/Macro-Analysis/.
Запускать каждые 2 недели (понедельник) или по триггеру значимых новостей.

Использование:
    python scripts/macro_review.py              # интерактивный режим (шаблон + подсказки)
    python scripts/macro_review.py --auto       # авто-сбор доступных метрик (без веб-поиска)
    python scripts/macro_review.py --dry-run    # показать план, не создавать файл
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows encoding safety
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# === Константы ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OBSIDIAN_MACRO_DIR = PROJECT_ROOT / "obsidian" / "Macro-Analysis"
TEMPLATE_PATH = OBSIDIAN_MACRO_DIR / "_TEMPLATE.md"
CONFIG_PATH = OBSIDIAN_MACRO_DIR / ".macro_config.json"
SCHEDULE_DAYS = 14  # каждые 2 недели

# Триггеры для внеочередного обзора
NEWS_TRIGGERS = [
    "FOMC решение",
    "MiCA дедлайн / делистинг USDT",
    "ETF рекордный отток (>$1B/день)",
    "BTC daily move >8%",
    "Крупный exchange взлом/крах",
    "CLARITY Act движение",
    "Геополитика (война, санкции)",
]

# Источники данных (URL-шаблоны — для справки, не запрашиваются скриптом)
DATA_SOURCES = {
    "FRED": "https://fred.stlouisfed.org",
    "CME_FedWatch": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "ECB": "https://www.ecb.europa.eu",
    "CryptoQuant": "https://cryptoquant.com",
    "CoinGlass": "https://www.coinglass.com",
    "Farside_ETF": "https://farside.co.uk/btc/",
}


def load_config() -> dict:
    """Загрузить конфиг с датой последнего обзора."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"last_review": None, "reviews": []}


def save_config(config: dict):
    """Сохранить конфиг."""
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def next_review_due(config: dict) -> datetime | None:
    """Когда следующий обзор по расписанию (None = можно делать сейчас)."""
    if not config["last_review"]:
        return None  # первый обзор — разрешён
    last = datetime.fromisoformat(config["last_review"])
    due = last + timedelta(days=SCHEDULE_DAYS)
    if due <= datetime.now(timezone.utc):
        return None  # просрочен — разрешён
    return due  # ещё рано — вернуть ожидаемую дату


def check_emergency_triggers() -> list[str]:
    """
    Проверить экстренные триггеры.
    В авто-режиме проверяет только локально доступные данные (BTC цена из конфига/БД).
    Для полной проверки использовать WebSearch вручную.
    """
    triggered = []
    # TODO: подключить чтение BTC цены из БД/кэша и проверку daily move
    return triggered


def generate_template(date_str: str) -> str:
    """Сгенерировать Markdown-шаблон обзора."""
    return f"""---
tags: [macro, analysis, market-review, sphere-5, cross-market]
type: macro-review
date: {date_str}
period: ЗАПОЛНИТЬ (напр. 2026-06 → 2026-12)
outlook: ЗАПОЛНИТЬ (сценарий, вероятность)
parent: "[[Macro-Analysis/Macro-Analysis-MOC]]"
author: DS (DeepSeek/DeepCode)
sources: []
---

# 🌍 Макро-анализ крипторынка — {date_str}

> [КРАТКИЙ ТЕЗИС: одно предложение — суть момента]

---

## I. Что изменилось за 2 недели

### 🏛 Центробанки
[Ставки, решения, риторика]

### 📉 Крипторынок
[BTC/ETH цена, ETF-потоки, крупные движения]

### 📰 Ключевые новости
[MiCA, CLARITY Act, регуляция, хаки, институционалы]

---

## II. Текущий срез

### 🔢 Ключевые метрики

| Индикатор | Значение | Неделю назад | Тренд |
|-----------|----------|-------------|-------|
| BTC | $00,000 | $00,000 | ↗/↘/→ |
| ETH | $0,000 | $0,000 | ↗/↘/→ |
| DXY | 00.00 | 00.00 | ↗/↘/→ |
| BTC ETF flow | ±$0B | ±$0B | ↗/↘/→ |
| Fear & Greed | 00 | 00 | ↗/↘/→ |
| ФРС ставка | 0.00-0.00% | 0.00-0.00% | ⏸ |
| USDT доминация | 0.0% | 0.0% | ↗/↘/→ |

### Оценка ликвидности
[Европейская / Азиатская / Американская сессия]

---

## III. Прогноз (обновление)

[Актуальный сценарий, вероятность, пересмотр предыдущего]

### Ключевые даты впереди
| Дата | Событие | Ожидаемое влияние |
|------|---------|-------------------|
| | | |

---

## IV. Влияние на OKO Project

[Рекомендации для Сферы 5, риск-менеджмента, Capital Allocator]

---

*Анализ: DS (DeepSeek/DeepCode), {date_str}*
*Следующий плановый обзор: [ДАТА+14]*
"""


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Макро-обзор крипторынка")
    parser.add_argument("--auto", action="store_true", help="Авто-режим без интерактива")
    parser.add_argument("--dry-run", action="store_true", help="Показать план, не создавать файл")
    parser.add_argument("--force", action="store_true", help="Создать обзор даже если не по расписанию")
    args = parser.parse_args()

    config = load_config()
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}-macro-review.md"
    filepath = OBSIDIAN_MACRO_DIR / filename

    # Проверка расписания
    due = next_review_due(config)
    if due is not None and not args.force:
        due_str = due.strftime("%Y-%m-%d %H:%M UTC")
        print(f"[SCHEDULE] Next planned review: {due_str}")
        print(f"   Use --force for emergency review.")
        return

    # Экстренные триггеры
    if not args.force and not args.auto:
        triggers = check_emergency_triggers()
        if triggers:
            print("[ALERT] Emergency triggers detected:")
            for t in triggers:
                print(f"   * {t}")

    # Проверка существующего файла
    if filepath.exists():
        print(f"[WARN] Review {filename} already exists.")
        if not args.auto:
            resp = input("Overwrite? [y/N]: ").strip().lower()
            if resp != "y":
                print("Cancelled.")
                return

    if args.dry_run:
        print(f"\n[DRY-RUN] Would create: {filepath}")
        print(f"   Template: {len(generate_template(date_str))} chars")
        print(f"   After creation — fill with WebSearch + DS expert assessment")
        return

    # Генерация шаблона
    OBSIDIAN_MACRO_DIR.mkdir(parents=True, exist_ok=True)
    template = generate_template(date_str)
    filepath.write_text(template, encoding="utf-8")

    # Обновить конфиг
    config["last_review"] = datetime.now(timezone.utc).isoformat()
    config["reviews"].append(
        {
            "date": date_str,
            "file": filename,
            "trigger": "schedule" if not args.force else "manual",
        }
    )
    save_config(config)

    print(f"\n[OK] Macro template created: {filepath}")
    print(f"   {'Fill with WebSearch + DS expert assessment' if not args.auto else 'Auto mode: template only'}")
    print(f"   Next scheduled review: {(datetime.now(timezone.utc) + timedelta(days=SCHEDULE_DAYS)).strftime('%Y-%m-%d')}")

    # Подсказки для заполнения
    if not args.auto:
        print(f"\n[DATA] Sources for filling:")
        for name, url in DATA_SOURCES.items():
            print(f"   * {name}: {url}")
        print(f"\n[TRIGGERS] Emergency review triggers:")
        for t in NEWS_TRIGGERS:
            print(f"   * {t}")


if __name__ == "__main__":
    main()
