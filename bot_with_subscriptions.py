"""DEPRECATED: точка входа переименована в `oko_mtf.py` (15.05.2026).

Этот файл — backward-compat shim. Старые скрипты, ярлыки, hooks продолжат работать,
но рекомендуется использовать `python oko_mtf.py`.

Поведение идентично прямому запуску oko_mtf.py — просто импортируем и выполняем main-блок.
"""
import runpy
import sys
import warnings

warnings.warn(
    "bot_with_subscriptions.py переименован в oko_mtf.py. "
    "Обнови команду запуска: python oko_mtf.py",
    DeprecationWarning, stacklevel=2,
)

# Запускаем oko_mtf.py как __main__ (выполнит весь if __name__ == "__main__" блок)
if __name__ == "__main__":
    runpy.run_path("oko_mtf.py", run_name="__main__")
else:
    # Если кто-то импортирует — пробрасываем модуль (некритично, но на всякий случай)
    sys.modules[__name__] = runpy.run_path("oko_mtf.py")  # type: ignore[assignment]
