"""Trade Post-Mortem — мини-разбор плохих сделок (R < threshold).

Для каждой сделки с R < -2.0 (по умолчанию) генерирует досье:
- Контекст входа (regime, strategy, signal_type, mtf_alignment)
- Что предсказывалось (max_R_possible, captured_R_pct)
- Что сломалось (first_drawdown_r, sl_source, статус)
- Что в features_json (decision_trace, confirmations, mtf_bias и т.д.)
- Урок на будущее (что детектор должен был увидеть, но не увидел)

Запуск:
  python tools/trade_postmortem.py                    # все R<-2 за 24ч без досье
  python tools/trade_postmortem.py --trade-id 12285   # одна конкретная сделка
  python tools/trade_postmortem.py --hours 48         # шире окно
  python tools/trade_postmortem.py --threshold -1.5   # планка
  python tools/trade_postmortem.py --force            # перезаписать существующие

Output:
  obsidian/Trades/<trade_id>-<symbol>.md
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DB_PATH = PROJECT_ROOT / "subscriptions.db"

OUTPUT_DIR = PROJECT_ROOT / "obsidian" / "Trades"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 4000


POSTMORTEM_PROMPT = """Ты — TRADER-аналитик, разбираешь УБЫТОЧНУЮ сделку торгового бота.
Цель — выявить ЧТО пошло не так и какой урок извлечь.

ФОРМАТ (markdown, русский, 100-200 строк):

# Trade #{trade_id} — {symbol} {direction} R={r}

## 📌 Краткая суть
1-2 строки: что произошло. SL? TSL? Сколько R потеряли.

## 🎯 Контекст входа
- Сигнал: signal_type, strategy_name, regime
- Время: created_at, длительность
- Параметры: strength, confidence, entry_priority
- MTF контекст: atr_trend_1h_bias, mtf alignment если упоминается

## 🛠️ Что планировалось
- SL: where (sl_source), distance %
- TP: where (tp_source), distance %, RR
- Стратегия: strategy_type (SINGLE / DUAL_TP / DUAL_TSL)

## 💥 Что случилось
- Статус закрытия: SL/TSL/EXPIRED
- first_profit_r vs first_drawdown_r — что было первым
- TSL activated? BE activated?
- max_R_possible vs achieved — был ли шанс выйти раньше

## 🔍 Что в decision_trace / confirmations
Если в `features_json` есть `confirmations` / `decision_trace` / `signal_mode`:
- какие подтверждения сработали
- что могло быть «фейк-сетапом»
- entry_priority и почему

## 🚨 Главный диагноз
ОДНА главная причина почему сделка убыточна. Используй данные:
- Pattern fail (структура SMC сломалась, ложный BOS)?
- Wrong regime (контр-тренд в TREND_DOWN)?
- Bad SL (слишком близко, шум выбил)?
- Late entry (вход после движения)?
- mtf disagree (15m даёт LONG, 1h — TREND_DOWN)?
- News / black swan?

Будь конкретен. Цитируй конкретные числа.

## 🧠 Урок
Что должен был увидеть бот, чтобы НЕ открывать эту сделку?
Какой gate / фильтр / confirmation выявил бы это?

## 🔗 Связано
- Стратегия: `[[Strategies/<signal_type>]]`
- Похожие проблемы: ссылки на DEV-XXX задачи если можно вычислить
- Дата: `[[Daily-Review/{date}-review]]`

ПРАВИЛА:
- Только факты из source. Не выдумывай.
- Будь критичен. Это разбор УБЫТКА.
- Если в source мало данных — пиши "недостаточно данных для X".
- Bullet-points. Только русский.

ИСТОЧНИК (полный record сделки):

{trade_record}
"""


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def fetch_one_trade(trade_id: int) -> dict | None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM simulated_trades WHERE id = ?",
        (trade_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_bad_trades(hours: int, threshold: float) -> list[dict]:
    """R < threshold за последние N часов."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM simulated_trades
        WHERE status != 'OPEN' AND closed_at IS NOT NULL AND closed_at >= ?
          AND R_multiple < ?
        ORDER BY R_multiple ASC
        """,
        (cutoff, threshold),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def format_trade_record(t: dict) -> str:
    """Полный record + развёрнутый features_json + decision_trace."""
    lines = [f"=== TRADE #{t['id']} ==="]
    # ключевые поля
    keys = ["symbol", "timeframe", "signal_type", "strategy_type", "strategy_name",
            "direction", "regime", "strength", "confidence", "sl_source", "tp_source",
            "entry_price", "stop_loss", "take_profit", "exit_price",
            "R_multiple", "status", "profit_pct",
            "max_R_possible", "captured_R_pct",
            "tsl_activated", "be_activated",
            "first_profit_r", "first_drawdown_r", "duration_minutes",
            "tp1_price", "tp1_hit_at", "tp2_price", "tp2_hit_at",
            "created_at", "closed_at", "source_router"]
    for k in keys:
        if k in t and t[k] is not None:
            lines.append(f"{k}: {t[k]}")

    # features_json — отдельно, развёрнуто
    fj = t.get("features_json")
    if fj:
        try:
            parsed = json.loads(fj)
            lines.append("\n=== features_json ===")
            lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            lines.append(f"\nfeatures_json (raw, не JSON): {fj[:2000]}")

    # decision_trace — отдельно
    dt = t.get("decision_trace_json")
    if dt:
        try:
            parsed = json.loads(dt)
            lines.append("\n=== decision_trace ===")
            lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            lines.append(f"\ndecision_trace (raw): {dt[:2000]}")

    return "\n".join(lines)


def slug(s: str) -> str:
    # CRO/USDT:USDT → CRO-USDT
    return s.replace("/USDT:USDT", "").replace("/", "-").replace(":", "-")


def call_gemini(prompt: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    cfg_kwargs = dict(
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        system_instruction=(
            "Ты — критичный TRADER-аналитик. Только русский. "
            "Только факты из source. Не повторяйся. Будь конкретен."
        ),
    )
    try:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY, contents=prompt,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        return (resp.text or "").strip(), GEMINI_MODEL_PRIMARY
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            print(f"[postmortem] 503 → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
            resp = client.models.generate_content(
                model=GEMINI_MODEL_FALLBACK, contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return (resp.text or "").strip(), GEMINI_MODEL_FALLBACK
        raise


def process_one(t: dict, force: bool) -> tuple[bool, Path | None, str]:
    """Возвращает (ok, file_path, reason)."""
    sym = slug(t["symbol"])
    out_path = OUTPUT_DIR / f"{t['id']}-{sym}.md"
    if out_path.exists() and not force:
        return (True, out_path, "exists, skip")

    record = format_trade_record(t)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = POSTMORTEM_PROMPT.format(
        trade_id=t["id"], symbol=t["symbol"], direction=t["direction"],
        r=t.get("R_multiple"), date=today, trade_record=record,
    )

    try:
        text, used = call_gemini(prompt)
    except Exception as e:
        return (False, None, f"gemini error: {e}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        "---\n"
        f"id: trade-{t['id']}\n"
        "tags: [postmortem, trade, auto]\n"
        "type: trade-postmortem\n"
        f"trade_id: {t['id']}\n"
        f"symbol: {t['symbol']}\n"
        f"signal_type: {t.get('signal_type')}\n"
        f"direction: {t.get('direction')}\n"
        f"R: {t.get('R_multiple')}\n"
        f"status: {t.get('status')}\n"
        f"regime: {t.get('regime')}\n"
        f"created_at: {t.get('created_at')}\n"
        f"closed_at: {t.get('closed_at')}\n"
        'parent: "[[Project-MOC]]"\n'
        f"model: {used}\n"
        "---\n\n"
        f"> Автогенерация Gemini (`tools/trade_postmortem.py --trade-id {t['id']}`).\n\n---\n\n"
    )
    out_path.write_text(header + text, encoding="utf-8")
    return (True, out_path, used)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade post-mortem via Gemini")
    parser.add_argument("--trade-id", type=int, help="Конкретная сделка")
    parser.add_argument("--hours", type=int, default=24, help="Окно поиска R<threshold")
    parser.add_argument("--threshold", type=float, default=-2.0, help="Граница R")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие")
    parser.add_argument("--limit", type=int, default=10, help="Лимит сделок за запуск")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not DB_PATH.exists():
        print(f"[postmortem] ERROR: {DB_PATH} не найден", file=sys.stderr)
        return 1

    if args.trade_id:
        t = fetch_one_trade(args.trade_id)
        if not t:
            print(f"[postmortem] ERROR: trade #{args.trade_id} не найден", file=sys.stderr)
            return 1
        trades = [t]
    else:
        trades = fetch_bad_trades(args.hours, args.threshold)
        if not trades:
            print(f"[postmortem] нет R<{args.threshold} за {args.hours}ч", file=sys.stderr)
            return 0
        trades = trades[: args.limit]

    print(f"[postmortem] обрабатываю {len(trades)} сделок...", file=sys.stderr)
    done, skipped, errors = 0, 0, 0
    for t in trades:
        ok, path, reason = process_one(t, args.force)
        if ok and reason == "exists, skip":
            skipped += 1
            print(f"[postmortem] #{t['id']} {t['symbol']}: skip (exists)", file=sys.stderr)
        elif ok:
            done += 1
            print(f"[postmortem] #{t['id']} {t['symbol']} R={t.get('R_multiple'):.2f} → {path.name}",
                  file=sys.stderr)
        else:
            errors += 1
            print(f"[postmortem] #{t['id']} ERROR: {reason}", file=sys.stderr)

    if args.quiet:
        print(f"[postmortem] OK done={done} skipped={skipped} errors={errors}", file=sys.stderr)
    else:
        print(f"\n[postmortem] Итого: done={done} skipped={skipped} errors={errors}")
        print(f"  -> {OUTPUT_DIR}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
