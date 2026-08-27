#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Хуки жизненного цикла сессии (12.08.2026).

Автоматизируют два РУЧНЫХ правила из .claude/CLAUDE.md, которые забывались:
  precompact  — «до компакта записать промежуточный статус в current_state.md»
  sessionend  — чеклист завершения сессии (current_state / MEMORY / whats-next / START)

Читает JSON хука со stdin (не обязателен), пишет JSON в stdout для Claude Code.

Запуск:  python tools/session_hooks.py precompact|sessionend
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_STATE = ROOT / "memory" / "current_state.md"
# Файлы, которые правило CLAUDE.md требует обновлять при завершении сессии
SESSION_FILES = {
    "memory/current_state.md": ROOT / "memory" / "current_state.md",
    "whats-next.md": ROOT / "whats-next.md",
    "START.md": ROOT / "START.md",
}
FRESH_HOURS = 6.0


def _out(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _read_stdin() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def precompact() -> int:
    """Вставляет маркер в current_state.md, чтобы после компакта было с чего продолжить."""
    if not CURRENT_STATE.exists():
        _out({"systemMessage": f"PreCompact: {CURRENT_STATE} не найден — статус не записан"})
        return 0
    ts = datetime.now(timezone.utc).strftime("%d.%m %H:%M UTC")
    marker = (
        f"\n## ⏸️ [{ts}] КОМПАКТ КОНТЕКСТА — заполнить после\n"
        f"- 🔄 В процессе: _чем занимался до компакта_\n"
        f"- ⚠️ На чём остановился: _следующий шаг_\n"
        f"- 📌 Что НЕ потерять: _открытые гипотезы, незаписанные числа_\n"
    )
    text = CURRENT_STATE.read_text(encoding="utf-8")
    # вставляем сразу после шапки (первый разделитель), чтобы было видно сверху
    anchor = "\n---\n"
    idx = text.find(anchor)
    if idx == -1:
        text += marker
    else:
        cut = idx + len(anchor)
        text = text[:cut] + marker + text[cut:]
    CURRENT_STATE.write_text(text, encoding="utf-8")
    _out({
        "systemMessage": f"⏸️ PreCompact: маркер записан в memory/current_state.md ({ts}) — заполни его.",
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": (
                "ПЕРЕД КОМПАКТОМ: в memory/current_state.md добавлен блок "
                f"'⏸️ [{ts}] КОМПАКТ КОНТЕКСТА'. Заполни его тем, чем занимался: "
                "что в процессе, на чём остановился, какие числа/гипотезы нельзя потерять."
            ),
        },
    })
    return 0


def sessionend() -> int:
    """Проверяет, обновлены ли файлы завершения сессии; называет забытые."""
    now = time.time()
    stale, missing = [], []
    for label, path in SESSION_FILES.items():
        if not path.exists():
            missing.append(label)
            continue
        age_h = (now - path.stat().st_mtime) / 3600.0
        if age_h > FRESH_HOURS:
            stale.append(f"{label} ({age_h:.0f}ч назад)")
    if not stale and not missing:
        _out({"systemMessage": "✅ SessionEnd: current_state / whats-next / START обновлены."})
        return 0
    parts = []
    if stale:
        parts.append("НЕ обновлены: " + " · ".join(stale))
    if missing:
        parts.append("отсутствуют: " + " · ".join(missing))
    _out({"systemMessage": "⚠️ SessionEnd — " + "; ".join(parts)})
    return 0


def postwrite(payload: dict) -> int:
    """PostToolUse на Write/Edit: по ПУТИ решает, какую проверку запустить.

    Фильтрация пути сделана здесь, а не через `jq` в команде хука: jq на этой машине
    НЕ УСТАНОВЛЕН, и стандартный паттерн `jq -r '.tool_input.file_path' | …` молча
    не сработал бы (проверено pipe-тестом 12.08).
    """
    import subprocess

    ti = payload.get("tool_input") or {}
    tr = payload.get("tool_response") or {}
    path = str(ti.get("file_path") or tr.get("filePath") or "").replace("\\", "/").lower()
    if not path:
        return 0

    checks = []
    if "/memory/" in path and path.endswith(".md"):
        checks.append(("memory_lint", ROOT / "tools" / "memory_lint.py"))
    if "/obsidian/" in path and path.endswith(".md"):
        checks.append(("obsidian_vault", ROOT / "scripts" / "validate_obsidian_vault.py"))
    # 13.08.2026: аудит конфига после КАЖДОЙ правки config.yaml. Повод — два класса,
    # которые тихо стоили денег: ключ-призрак (min_rr_ratio жил хардкодом 2.0 и резал
    # 18 464 сигнала) и sed-инцидент 16.07 (одна правка выключила 5 чужих `enabled`).
    # Обе находки — из ручного прогона; хук делает проверку неизбежной.
    if path.endswith("config.yaml"):
        checks.append(("config_audit", ROOT / "tools" / "config_audit.py"))
    if not checks:
        return 0

    msgs = []
    for name, script in checks:
        if not script.exists():
            continue
        try:
            r = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
            )
            out = (r.stdout or "") + (r.stderr or "")
            # вытаскиваем только строки-предупреждения, чтобы не засорять вывод
            bad = [ln.strip() for ln in out.splitlines()
                   if ln.strip().startswith(("⚠️", "🔴")) and "Statistics" not in ln]
            # config_audit печатает заголовки «## СИРОТЫ: N …» / «## ПРИЗРАКИ: N …»,
            # они не начинаются с эмодзи — ловим отдельно, иначе хук молчит впустую.
            if name == "config_audit":
                bad = [ln.strip().lstrip("# ") for ln in out.splitlines()
                       if ln.strip().startswith("##") and not ln.strip().endswith(": 0")]
            if bad:
                msgs.append(f"{name}: " + " | ".join(bad[:3]))
        except Exception as e:
            msgs.append(f"{name}: не запустился ({type(e).__name__})")
    if msgs:
        _out({"systemMessage": "🔎 " + " ;; ".join(msgs)})
    return 0


def main() -> int:
    payload = _read_stdin()          # PostToolUse передаёт tool_input со stdin
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "precompact":
        return precompact()
    if cmd == "sessionend":
        return sessionend()
    if cmd == "postwrite":
        return postwrite(payload)
    _out({"systemMessage": "session_hooks: ожидается precompact|sessionend|postwrite"})
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
