"""DS-R1-ANALYZER: локальный DeepSeek-R1 с памятью проекта.

Использование:
  python scripts/ds_r1_analyzer.py "почему arch104 на VST +0.48R а confluence -0.71R?"
  python scripts/ds_r1_analyzer.py "разбери последние 10 SL-сделок XLM"
  python scripts/ds_r1_analyzer.py --db "дай сводку по ote_nested за 7 дней"

Архитектура:
  1. Сбор контекста из памяти проекта (DISCUSSION, TASKS, брифы)
  2. Сбор данных из БД (SQL по запросу)
  3. Отправка в DeepSeek-R1:14b через Ollama
  4. R1 думает (CoT) → выдаёт структурированный анализ

DeepSeek-R1 особенности:
  - Рассуждающая модель: ответ содержит  теги с цепочкой мыслей
  - В контекст подаём ТОЛЬКО релевантные данные (14B память ограничена ~8K токенов)
  - Лучше работает с конкретными цифрами, а не абстрактными вопросами
"""
import sys, json, sqlite3, subprocess, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Проектная память (ключевые файлы для контекста) ──────────────────
MEMORY_FILES = [
    ("Сессия",         "memory/session_brief.md"),
    ("Сделки",         "memory/last_trade_review.md"),
    ("Задачи",         "TASKS.md"),
    ("Дискуссия",      "DISCUSSION.md"),
]

# Максимальный размер контекста для R1:14b (~6K токенов = ~24K символов)
MAX_CONTEXT_CHARS = 21000


def _read_file(path: Path, max_lines: int = 200) -> str:
    """Читает первые N строк файла (самое важное — в начале)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
        lines = text.split("\n")[:max_lines]
        return "\n".join(lines)
    except Exception:
        return ""


def _query_db(sql: str) -> list[dict]:
    """Выполняет SQL и возвращает список словарей."""
    db = sqlite3.connect(str(ROOT / "subscriptions.db"))
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql).fetchall()]
    finally:
        db.close()


def build_context(question: str) -> str:
    """Собирает контекст: память проекта + авто-SQL по вопросу."""
    parts = []

    # 1. Ключевая память проекта
    parts.append("=== ПАМЯТЬ ПРОЕКТА (последние обновления) ===")
    for name, rel_path in MEMORY_FILES:
        text = _read_file(ROOT / rel_path, max_lines=100)
        if text:
            # Берём только первые 100 строк — самое свежее
            preview = text[:3000]
            parts.append(f"\n--- {name} ---\n{preview}")

    # 2. Авто-SQL: если вопрос про сделки — добавляем статистику
    lower = question.lower()
    if any(w in lower for w in ["сделка", "сделок", "sl", "tp", "убыток", "avg", "wr", "r_multiple", "ote", "arch104", "pivot", "vst"]):
        parts.append("\n=== БД: СТАТИСТИКА ПО СИГНАЛАМ (VST, 7 дней) ===")
        rows = _query_db("""
            SELECT signal_type,
                   COUNT(*) n, AVG(R_multiple) avgR,
                   SUM(R_multiple) sumR,
                   100.0*COUNT(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) WR
            FROM simulated_trades
            WHERE status IN ('TP','SL','TSL','EXPIRED')
              AND exchange_order_id IS NOT NULL AND exchange_order_id!='SIM' AND exchange_order_id!=''
              AND created_at >= datetime('now','-7 days')
            GROUP BY signal_type
            ORDER BY n DESC
        """)
        parts.append(json.dumps(rows, indent=2, ensure_ascii=False))

    if any(w in lower for w in ["xlm", "lumen", "stellar"]):
        parts.append("\n=== БД: ПОСЛЕДНИЕ 10 СДЕЛОК XLM/USDT ===")
        rows = _query_db("""
            SELECT created_at, signal_type, direction, R_multiple, status,
                   entry_price, exit_price, duration_minutes
            FROM simulated_trades
            WHERE symbol='XLM/USDT' AND status IN ('TP','SL','TSL','EXPIRED')
            ORDER BY created_at DESC LIMIT 10
        """)
        parts.append(json.dumps(rows, indent=2, ensure_ascii=False, default=str))

    if any(w in lower for w in ["открыт", "open", "позици"]):
        parts.append("\n=== БД: ОТКРЫТЫЕ VST ПОЗИЦИИ ===")
        rows = _query_db("""
            SELECT symbol, signal_type, direction, R_multiple,
                   ROUND((julianday('now')-julianday(created_at))*24,1) hours
            FROM simulated_trades
            WHERE status='OPEN' AND exchange_order_id IS NOT NULL
              AND exchange_order_id!='SIM' AND exchange_order_id!=''
            ORDER BY hours DESC LIMIT 15
        """)
        parts.append(json.dumps(rows, indent=2, ensure_ascii=False))

    # 3. Правила анализа (system prompt)
    system = """Ты DeepSeek-R1 — аналитик проекта Oko MTF (крипто-трейдинг бот).
Твоя задача: анализировать данные СТРОГО на основе контекста ниже.
НЕ выдумывай цифры. Если данных недостаточно — скажи.
Отвечай как трейдер: коротко, по делу, на русском.
Формат: 1) Главный вывод 2) Данные 3) Рекомендация."""
    parts.insert(0, system)

    context = "\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n... (контекст обрезан)"
    return context


def call_ollama(prompt: str, model: str = "deepseek-r1:14b") -> str:
    """Вызывает Ollama через CLI (самый надёжный способ для R1)."""
    cmd = ["ollama", "run", model, prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = result.stdout.strip()
        # R1 возвращает  теги — убираем для чистоты вывода
        output = re.sub(r'[ \n]*[\s\S]*?[\n]*', '\n', output)
        # Убираем пустые строки в начале
        output = output.strip()
        return output if output else f"ERROR: {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "TIMEOUT: R1 думала >5 минут. Упрости вопрос или уменьши контекст."
    except Exception as e:
        return f"ERROR: {e}"


def run():
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    if not question:
        question = input("Вопрос к R1: ").strip()
    if not question:
        print("Usage: python scripts/ds_r1_analyzer.py 'вопрос'")
        return

    print(f"\n{'='*60}")
    print(f"  DeepSeek-R1:14b — анализ проекта Oko MTF")
    print(f"{'='*60}")
    print(f"  Вопрос: {question}")
    print(f"  Сбор контекста...")

    context = build_context(question)
    print(f"  Контекст: {len(context)} символов")

    prompt = f"{context}\n\n=== ВОПРОС ===\n{question}\n\nДай развёрнутый анализ на основе КОНТЕКСТА выше."

    print(f"  Отправка в R1...")
    print(f"{'='*60}\n")

    answer = call_ollama(prompt)
    print(answer)
    print(f"\n{'='*60}")


if __name__ == "__main__":
    run()
