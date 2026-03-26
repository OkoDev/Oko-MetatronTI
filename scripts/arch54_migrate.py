"""
ARCH-54: Автоматический рефакторинг core/ — разбивка по папкам.
Запуск: python scripts/arch54_migrate.py
"""
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(BASE, "core")

# Маппинг: папка -> список файлов (без .py)
FOLDERS = {
    "indicators": [
        "indicators", "divergence_detector", "trend_signals",
        "market_regime", "anomaly_model", "bounce_detector", "dynamic_thresholds",
    ],
    "pivots": [
        "pivot_levels", "pivot_reversal", "pivot_calculator_fixed", "mtf_pivot_integration",
    ],
    "signals": [
        "signal_models", "signal_checkers", "signal_watch_list",
        "wt_15m_reversal_scanner", "structure_detector",
    ],
    "mtf": [
        "mtf_checker", "mtf_interpreter", "multi_tf_resolver",
    ],
    "infra": [
        "api_engine", "data_collector", "config_loader", "data_quality", "entry_config",
    ],
    "trading": [
        "trade_simulator", "trade_analyzer", "performance_engine", "regime_strategy",
    ],
    "confluence": [
        "confluence_scanner", "confluence_state_machine",
    ],
}

# Уже готовы (пропускаем)
ALREADY_DONE = {"db", "ui", "ml"}


def make_init(folder_path: str, modules: list[str]) -> str:
    names = ", ".join(f'"{m}"' for m in modules)
    lines = [
        f'"""',
        f"ARCH-54: {os.path.basename(folder_path)}/ — автоматически сгенерированный __init__.py",
        f'"""',
        f"__all__ = [{names}]",
        "",
    ]
    return "\n".join(lines)


def make_stub(module: str, folder: str) -> str:
    return (
        f"# ARCH-54: файл перемещён в core/{folder}/{module}.py\n"
        f"# Этот stub сохраняет обратную совместимость — все старые импорты продолжают работать.\n"
        f"from core.{folder}.{module} import *  # noqa: F401, F403\n"
    )


errors = []
created = []

for folder, modules in FOLDERS.items():
    folder_path = os.path.join(CORE, folder)
    os.makedirs(folder_path, exist_ok=True)

    for module in modules:
        src = os.path.join(CORE, f"{module}.py")
        dst = os.path.join(folder_path, f"{module}.py")

        if not os.path.exists(src):
            print(f"  SKIP (no src): core/{module}.py")
            continue

        # Проверяем что src — не уже stub
        with open(src, encoding="utf-8") as f:
            content = f.read()
        if "ARCH-54: файл перемещён" in content:
            print(f"  ALREADY stub: core/{module}.py -> core/{folder}/{module}.py")
            # Проверяем что dst существует
            if not os.path.exists(dst):
                errors.append(f"Stub exists but dst missing: core/{folder}/{module}.py")
            continue

        # Копируем файл в папку
        shutil.copy2(src, dst)

        # Заменяем оригинал на stub
        with open(src, "w", encoding="utf-8") as f:
            f.write(make_stub(module, folder))

        created.append(f"core/{folder}/{module}.py")
        print(f"  MOVED: core/{module}.py -> core/{folder}/{module}.py")

    # Создаём __init__.py если нет
    init_path = os.path.join(folder_path, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(make_init(folder_path, modules))
        print(f"  CREATED: core/{folder}/__init__.py")

print(f"\n✅ Создано/перемещено: {len(created)} файлов")
if errors:
    print(f"❌ Ошибки: {errors}")
    sys.exit(1)
