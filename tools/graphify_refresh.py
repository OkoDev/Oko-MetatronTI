"""Обновление графа знаний graphify (graphify-out/) одной командой — DEV-242.

  python tools/graphify_refresh.py            # код: AST-пересборка + чистка по .graphifyignore (бесплатно)
  python tools/graphify_refresh.py --docs     # + LLM-разбор изменённых доков (Gemini через LLM_PROXY) → код
  python tools/graphify_refresh.py --labels   # имена только сообществам-заглушкам «Community N»
  python tools/graphify_refresh.py --all      # доки → код → имена

Ловушки, найденные 26–28.09 и учтённые здесь:
- после extract ОБЯЗАТЕЛЕН `update --force`: инкрементальная склейка extract теряет узлы кода;
- extract перекластеризует граф → узлам возвращаются прежние номера сообществ до update,
  иначе update сопоставит сохранённые имена с чужими сообществами;
- исключённое в .graphifyignore update из графа не вычищает (семантические узлы живут вечно) →
  чистка узлов, чей source_file исключён в .graphifyignore или удалён;
- Gemini с VPN-выхода отвечает 400 «location» → только через LLM_PROXY; чанки 30k — без минутных 429;
- graphify вызывается отдельным процессом (`python -m graphify`): его __main__ под guard,
  Windows spawn-воркеры AST не плодят копии extract.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "graphify-out"
GRAPH = OUT / "graph.json"
LABELS = OUT / ".graphify_labels.json"
MODEL = "gemini-3.1-flash-lite"   # у бесплатного gemini-3-flash суточная квота кончается за ~10 чанков
MAX_PRUNE_SHARE = 0.10            # чистка >10% узлов = почти наверняка сбой сравнения путей → не трогаем


def _ensure_graphify_python() -> None:
    """graphify стоит в .venv, а тулзы часто запускают системным Python → перезапуск нужным."""
    try:
        import graphify  # noqa: F401
        return
    except ImportError:
        pass
    marker = OUT / ".graphify_python"   # пишется graphify, с BOM
    py = marker.read_text(encoding="utf-8-sig").strip() if marker.exists() else ""
    if not py or Path(py).resolve() == Path(sys.executable).resolve():
        sys.exit("graphify не установлен в этом Python, а graphify-out/.graphify_python не указывает на другой")
    sys.exit(subprocess.call([py, __file__, *sys.argv[1:]]))


def _graphify(*args: str, env: dict | None = None) -> None:
    print("$ graphify " + " ".join(args), flush=True)
    rc = subprocess.call([sys.executable, "-m", "graphify", *args], cwd=ROOT,
                         env=env or dict(os.environ, PYTHONIOENCODING="utf-8"))
    if rc != 0:
        sys.exit(f"graphify {args[0]} завершился с кодом {rc}")


def _gemini_env() -> dict:
    sys.path.insert(0, str(ROOT / "tools"))
    from llm_ask import load_env

    load_env()
    missing = [k for k in ("GEMINI_API_KEY", "LLM_PROXY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"нет в .env: {', '.join(missing)}")
    proxy = os.environ["LLM_PROXY"]
    return dict(os.environ, HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="127.0.0.1,localhost",
                PYTHONIOENCODING="utf-8", GRAPHIFY_MAX_OUTPUT_TOKENS="8000")


def _load() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def _save(g: dict) -> None:
    GRAPH.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")


def _labels() -> dict:
    return json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {}


def _unnamed(name: str | None) -> bool:
    return name is None or name.startswith("Community ")


def _rel(path: str) -> str:
    p = path.replace("\\", "/")
    if os.path.isabs(p):
        p = os.path.relpath(p, ROOT).replace("\\", "/")
    return p.removeprefix("./")


def step_docs(model: str) -> None:
    pre = _load() if GRAPH.exists() else None
    _graphify("extract", ".", "--backend", "gemini", "--model", model,
              "--max-concurrency", "1", "--token-budget", "30000", env=_gemini_env())
    if pre is None:
        return
    # Инкрементальная склейка extract (28–29.09): теряет узлы кода и .md-структуры, выбрасывает
    # гиперрёбра даже непереразобранных доков и перенумеровывает сообщества. Чиним до update --force.
    g = _load()
    before = {n["id"]: n.get("community") for n in pre["nodes"]}
    fresh = max((c for c in before.values() if isinstance(c, int)), default=-1) + 1
    new_ids: dict = {}
    for n in g["nodes"]:   # прежние номера сообществ — иначе сохранённые имена прилипнут к чужим
        if before.get(n["id"]) is not None:
            n["community"] = before[n["id"]]
        else:
            n["community"] = new_ids.setdefault(n.get("community"), fresh + len(new_ids))
    # потерянные AST-узлы — обратно с прежними номерами: update --force их пересоберёт из исходников,
    # но карту «узел → сообщество» возьмёт отсюда
    have = {n["id"] for n in g["nodes"]}
    g["nodes"] += [n for n in pre["nodes"] if n["id"] not in have and n.get("_origin") == "ast"]
    have = {n["id"] for n in g["nodes"]}
    # гиперрёбра доков, которые в этот раз не переразбирались (из их файла нет новых гиперрёбер)
    hyper = g.get("hyperedges") or []
    ids, files = {h["id"] for h in hyper}, {h.get("source_file") for h in hyper}
    back = [h for h in pre.get("hyperedges") or []
            if h["id"] not in ids and h.get("source_file") not in files
            and all(x in have for x in h.get("nodes", []))]
    g["hyperedges"] = hyper + back
    _save(g)
    print(f"после extract: возвращено гиперрёбер {len(back)}, номера сообществ восстановлены", flush=True)


def _prune() -> int:
    """Убрать узлы, чей source_file исключён в .graphifyignore или удалён с диска.

    Только правила самого .graphifyignore, без .gitignore: семантические узлы законно ссылаются
    на существующие файлы вне корпуса (subscriptions.db, *.pine, obsidian/) — их не трогаем.
    """
    from graphify.detect import _is_ignored, _parse_gitignore_line

    ign = ROOT / ".graphifyignore"
    lines = ign.read_text(encoding="utf-8").splitlines() if ign.exists() else []
    patterns = [(ROOT, p) for p in map(_parse_gitignore_line, lines) if p]

    def gone(source_file: str) -> bool:
        path = ROOT / _rel(source_file)
        try:
            return not path.exists() or _is_ignored(path, ROOT, patterns)
        except (OSError, ValueError):   # кривой путь от LLM — не повод удалять
            return False

    g = _load()
    drop = {n["id"] for n in g["nodes"] if n.get("source_file") and gone(n["source_file"])}
    if not drop:
        return 0
    if len(drop) > MAX_PRUNE_SHARE * len(g["nodes"]):
        print(f"⚠️ чистка пропущена: под удаление {len(drop)} из {len(g['nodes'])} узлов — "
              f"похоже на сбой сравнения путей, а не на мусор", flush=True)
        return 0
    g["nodes"] = [n for n in g["nodes"] if n["id"] not in drop]
    key = "links" if "links" in g else "edges"
    g[key] = [e for e in g[key] if e.get("source") not in drop and e.get("target") not in drop]
    hyper = []
    for h in g.get("hyperedges") or []:
        if h.get("source_file") and gone(h["source_file"]):
            continue
        h["nodes"] = [x for x in h.get("nodes", []) if x not in drop]
        if len(h["nodes"]) >= 2:
            hyper.append(h)
    if "hyperedges" in g:
        g["hyperedges"] = hyper
    _save(g)
    print(f"чистка: убрано {len(drop)} узлов (исключены в .graphifyignore или удалены с диска)", flush=True)
    return len(drop)


def _communities() -> dict[int, list[str]]:
    comms: dict[int, list[str]] = {}
    for n in _load()["nodes"]:
        if n.get("community") is not None:
            comms.setdefault(int(n["community"]), []).append(n["id"])
    return comms


def _report_keep_communities() -> None:
    """GRAPH_REPORT.md и graph.json по ТЕКУЩИМ сообществам.

    `graphify cluster-only` всегда кластеризует заново и каждый раз рождает пару новых мелких
    сообществ без имени. Здесь его cluster() подменён на «вернуть то, что уже в graph.json».
    """
    import graphify.cluster as C
    from graphify.__main__ import main as graphify_main

    fixed = _communities()
    C.cluster = lambda G, **_kw: {c: [x for x in m if x in G] for c, m in fixed.items()}
    argv, sys.argv = sys.argv, ["graphify", "cluster-only", ".", "--no-viz"]
    print("$ graphify cluster-only . --no-viz  (без перекластеризации)", flush=True)
    try:
        graphify_main()
    finally:
        sys.argv = argv


def step_code() -> None:
    _graphify("update", ".", "--force")
    if _prune():
        _report_keep_communities()


def step_labels(model: str) -> None:
    os.environ.update(_gemini_env())   # до импорта graphify.llm: httpx берёт прокси из окружения
    import graphify.llm as L
    from networkx.readwrite import json_graph

    data = _load()
    G = json_graph.node_link_graph(data, edges="links" if "links" in data else "edges")
    labels = _labels()
    todo = {c: m for c, m in _communities().items() if _unnamed(labels.get(str(c)))}
    if not todo:
        print("имена: заглушек нет", flush=True)
        return
    print(f"имена: {len(todo)} сообществ-заглушек через {model}", flush=True)
    named = L.label_communities(G, todo, backend="gemini", model=model)
    labels.update({str(c): v for c, v in named.items() if not _unnamed(v)})
    LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _report_keep_communities()


def summary() -> None:
    g, labels = _load(), _labels()
    comms = {n.get("community") for n in g["nodes"]}
    unnamed = sum(1 for c in comms if _unnamed(labels.get(str(c))))
    print(f"граф: {len(g['nodes'])} узлов · {len(g.get('links', g.get('edges', [])))} рёбер · "
          f"{len(g.get('hyperedges') or [])} гиперрёбер · {len(comms)} сообществ (без имени: {unnamed})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Обновить граф знаний graphify-out/ (DEV-242)")
    ap.add_argument("--docs", action="store_true", help="LLM-разбор изменённых доков, затем пересборка кода")
    ap.add_argument("--labels", action="store_true", help="имена только сообществам-заглушкам")
    ap.add_argument("--all", action="store_true", help="доки → код → имена")
    ap.add_argument("--model", default=MODEL, help=f"модель Gemini (по умолчанию {MODEL})")
    a = ap.parse_args()
    _ensure_graphify_python()
    os.chdir(ROOT)   # graphify работает от cwd (graphify-out/ и «.»)

    run_docs = a.docs or a.all
    steps = []
    if run_docs:
        steps.append(("доки", lambda: step_docs(a.model)))
    if run_docs or a.all or not a.labels:
        steps.append(("код", step_code))
    if a.labels or a.all:
        steps.append(("имена", lambda: step_labels(a.model)))

    ours = None
    for name, fn in steps:
        # хук post-commit тоже пишет graph.json: коммит посреди прогона однажды перезаписал результат (28.09)
        if ours is not None and GRAPH.stat().st_mtime != ours:
            print("⚠️ graph.json изменён извне (хук после коммита?) — результат прошлого шага мог быть перезаписан",
                  flush=True)
        print(f"── шаг: {name}", flush=True)
        fn()
        ours = GRAPH.stat().st_mtime
    summary()
    if run_docs and not (a.labels or a.all):
        print("подсказка: новые сообщества без имени → python tools/graphify_refresh.py --labels")


if __name__ == "__main__":
    main()
