"""
Run Registry — журнал каждого запуска pattern mining скриптов.

Цели:
1. Воспроизводимость — любой запуск можно повторить
2. Audit trail — что когда запускалось с какими параметрами
3. Lineage tracking — какой CSV произведён каким скриптом из каких данных

Использование:
  from _run_registry import register_run

  with register_run("combinator_v3_nested", params={"ltf": "5m"}) as run:
      # ... твой код ...
      run.add_output("data/research/.../nested_v3_5m.csv")

Journal: `data/research/_run_registry.jsonl` (append-only)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JOURNAL_PATH = PROJECT_ROOT / "data" / "research" / "_run_registry.jsonl"


def _hash_file(path: Path, max_bytes: int = 1024 * 1024) -> str:
    """SHA256 первого MB файла (быстро для больших файлов)."""
    if not path.exists():
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(max_bytes))
    return h.hexdigest()[:16]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class RunHandle:
    def __init__(self, script_name: str, params: dict[str, Any]):
        self.script_name = script_name
        self.params = params
        self.start_ts = time.time()
        self.start_iso = datetime.now(timezone.utc).isoformat()
        self.outputs: list[dict[str, Any]] = []
        self.inputs: list[dict[str, Any]] = []
        self.errors: list[str] = []

        # Hash скрипта (для tracking изменений в коде)
        script_path = PROJECT_ROOT / "tools" / "pattern_mining" / f"{script_name}.py"
        self.script_hash = _hash_file(script_path)

    def add_input(self, path: str | Path):
        p = Path(path)
        self.inputs.append({
            "path": str(p.relative_to(PROJECT_ROOT) if p.is_absolute() else p),
            "hash": _hash_file(p),
            "size_kb": p.stat().st_size / 1024 if p.exists() else 0,
        })

    def add_output(self, path: str | Path):
        p = Path(path)
        self.outputs.append({
            "path": str(p.relative_to(PROJECT_ROOT) if p.is_absolute() else p),
            "hash": _hash_file(p),
            "size_kb": p.stat().st_size / 1024 if p.exists() else 0,
        })

    def add_error(self, msg: str):
        self.errors.append(msg)


@contextmanager
def register_run(script_name: str, params: dict[str, Any] | None = None):
    """Context manager — пишет entry в journal при выходе."""
    handle = RunHandle(script_name, params or {})
    try:
        yield handle
    except Exception as e:
        handle.add_error(f"{type(e).__name__}: {e}")
        raise
    finally:
        duration = time.time() - handle.start_ts
        entry = {
            "script": handle.script_name,
            "start_iso": handle.start_iso,
            "duration_sec": round(duration, 2),
            "params": handle.params,
            "script_hash": handle.script_hash,
            "inputs": handle.inputs,
            "outputs": handle.outputs,
            "errors": handle.errors,
        }
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[registry] {script_name} | {duration:.1f}s | outputs={len(handle.outputs)} | hash={handle.script_hash}")


def verify_baseline() -> bool:
    """Проверка immutability baseline snapshot."""
    baseline_dir = PROJECT_ROOT / "data" / "research" / "_baseline_2026-05-19"
    if not baseline_dir.exists():
        print(f"❌ Baseline directory missing: {baseline_dir}")
        return False
    hash_file = baseline_dir / ".hashes.json"
    if not hash_file.exists():
        print(f"❌ Hash file missing: {hash_file}")
        return False
    with open(hash_file) as f:
        hashes = json.load(f)
    mismatches = []
    for filename, expected_hash in hashes.items():
        fpath = baseline_dir / filename
        actual_hash = _hash_file(fpath)
        if actual_hash != expected_hash:
            mismatches.append((filename, expected_hash, actual_hash))
    if mismatches:
        print(f"❌ {len(mismatches)} files mismatch:")
        for name, exp, act in mismatches:
            print(f"  {name}: expected {exp}, got {act}")
        return False
    print(f"✅ Baseline verified — {len(hashes)} files immutable")
    return True


def list_runs(limit: int = 20):
    """Список последних N запусков."""
    if not JOURNAL_PATH.exists():
        print("Журнал пуст")
        return
    with open(JOURNAL_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    recent = lines[-limit:]
    for line in recent:
        e = json.loads(line)
        status = "❌" if e.get("errors") else "✅"
        print(f"{status} {e['start_iso'][:19]} | {e['script']:<35} | {e['duration_sec']:>7.1f}s | "
              f"out={len(e['outputs'])} | hash={e['script_hash']}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--verify-baseline", action="store_true", help="Проверить immutability baseline")
    p.add_argument("--list", type=int, default=0, help="Показать последние N запусков")
    args = p.parse_args()

    if args.verify_baseline:
        ok = verify_baseline()
        sys.exit(0 if ok else 1)
    elif args.list:
        list_runs(args.list)
    else:
        p.print_help()
