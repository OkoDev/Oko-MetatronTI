"""
Журнал вахт `WATCH.md` (19.10.2026) — выселен из TASKS.md.

Тест нужен из-за обрезки: `log_to_tasks` теперь УДАЛЯЕТ хвост старше MAX_ROWS.
Ошибка в разборе таблицы молча съест историю срабатываний — её восстанавливать неоткуда.
"""
import importlib

import pytest

alert = importlib.import_module("scripts._alert")

HEAD = (
    "# 🔭 WATCH — журнал фоновых вахт\n\n"
    "> Пишется автоматически.\n\n"
    "| когда | вахта | состояние | что делать |\n"
    "|---|---|---|---|\n"
)


@pytest.fixture
def watch(tmp_path, monkeypatch):
    f = tmp_path / "WATCH.md"
    monkeypatch.setattr(alert, "WATCH", f)
    return f


def test_новая_строка_встаёт_сверху(watch):
    watch.write_text(HEAD + "| старое | **Вахта** | `OUT` | было |\n", encoding="utf-8")

    assert alert.log_to_tasks("Зона дрейфа", "IN", "зона открылась") is True

    rows = [ln for ln in watch.read_text(encoding="utf-8").split("\n")
            if ln.startswith("|") and not ln.startswith("|---") and "когда |" not in ln]
    assert "Зона дрейфа" in rows[0] and "`IN`" in rows[0]
    assert "старое" in rows[1]


def test_хвост_режется_до_max_rows(watch):
    old = "".join(f"| t{i} | **В** | `OUT` | {i} |\n" for i in range(alert.MAX_ROWS + 10))
    watch.write_text(HEAD + old, encoding="utf-8")

    alert.log_to_tasks("Новая", "IN", "деталь")

    rows = [ln for ln in watch.read_text(encoding="utf-8").split("\n") if ln.startswith("| t")
            or ln.startswith("| 1") or "Новая" in ln]
    assert len(rows) == alert.MAX_ROWS
    assert "Новая" in rows[0]


def test_шапка_и_текст_над_таблицей_целы(watch):
    watch.write_text(HEAD, encoding="utf-8")

    alert.log_to_tasks("Вахта", "OK", "всё отвечает")

    text = watch.read_text(encoding="utf-8")
    assert text.startswith("# 🔭 WATCH")
    assert "> Пишется автоматически." in text
    assert text.index("|---") < text.index("**Вахта**")  # легла ПОД разделитель, не над ним


def test_файла_нет_отказ_не_молчит(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(alert, "WATCH", tmp_path / "нет.md")

    assert alert.log_to_tasks("Вахта", "OK", "деталь") is False
    assert "WATCH.md недоступен" in caplog.text


def test_таблицы_нет_отказ_не_молчит(watch, caplog):
    watch.write_text("# 🔭 WATCH\n\nтаблицу снесли руками\n", encoding="utf-8")

    assert alert.log_to_tasks("Вахта", "OK", "деталь") is False
    assert "нет таблицы" in caplog.text
