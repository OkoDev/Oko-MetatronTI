"""Проверка и настройка DeepSeek-R1:14b для Oko MTF.

Запуск:
  python scripts/setup_r1.py

Проверяет:
  1. Ollama установлен и запущен
  2. deepseek-r1:14b скачан
  3. Модель отвечает на тестовый запрос
  4. TradeAnalyzer видит модель
"""
import sys, subprocess, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(msg: str) -> bool:
    print(f"  {msg}...", end=" ")
    return True


def fail(msg: str):
    print(f"❌ {msg}")


def ok(msg: str = ""):
    print(f"✅ {msg}")


def main():
    print("=" * 55)
    print("  DeepSeek-R1:14b — проверка для Oko MTF")
    print("=" * 55)

    # 1. Ollama installed?
    print("\n1. Ollama")
    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        version = r.stdout.strip() or r.stderr.strip()
        ok(version)
    except FileNotFoundError:
        fail("Ollama не установлен. Скачай: https://ollama.com")
        return
    except Exception as e:
        fail(str(e))
        return

    # 2. R1:14b downloaded?
    print("\n2. Модель deepseek-r1:14b")
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if "deepseek-r1:14b" in r.stdout:
            ok("установлена")
        else:
            print("НЕ установлена. Качаем...")
            subprocess.run(["ollama", "pull", "deepseek-r1:14b"], check=True)
            ok("скачана")
    except Exception as e:
        fail(str(e))
        return

    # 3. Test query
    print("\n3. Тестовый запрос (5+5?)")
    try:
        r = subprocess.run(
            ["ollama", "run", "deepseek-r1:14b", "Сколько будет 5+5? Ответь одной цифрой."],
            capture_output=True, text=True, timeout=60
        )
        output = r.stdout.strip()
        if "10" in output:
            ok("ответила правильно")
        else:
            print(f"⚠️ ответ: {output[:100]}...")
    except subprocess.TimeoutExpired:
        print("⚠️ Медленно (CPU-режим?). На GPU — быстрее.")
    except Exception as e:
        fail(str(e))

    # 4. TradeAnalyzer config
    print("\n4. TradeAnalyzer (config.yaml)")
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        ta = cfg.get("trade_analyzer", {})
        provider = ta.get("provider", "disabled")
        model = ta.get("model", "")
        if provider == "ollama" and "deepseek" in model.lower():
            ok(f"provider=ollama, model={model}")
        elif provider == "ollama":
            print(f"⚠️ Ollama включён, но модель={model} (не deepseek).")
            print(f"   Исправить: trade_analyzer.model: deepseek-r1:14b")
        else:
            print(f"⚠️ provider={provider}. Для R1 нужно:")
            print(f"   trade_analyzer:")
            print(f"     provider: ollama")
            print(f"     model: deepseek-r1:14b")
    except Exception as e:
        fail(str(e))

    # 5. DS-R1-Analyzer
    print("\n5. DS-R1-Analyzer (scripts/ds_r1_analyzer.py)")
    script = ROOT / "scripts" / "ds_r1_analyzer.py"
    if script.exists():
        ok("готов. Запуск: python scripts/ds_r1_analyzer.py 'вопрос'")
    else:
        fail("файл не найден")

    print(f"\n{'=' * 55}")
    print("  Готово. Использование:")
    print(f"    python scripts/ds_r1_analyzer.py 'почему arch104 прибыльнее pivot?'")
    print(f"    python scripts/ds_r1_analyzer.py 'разбери XLM/USDT за 7 дней'")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
