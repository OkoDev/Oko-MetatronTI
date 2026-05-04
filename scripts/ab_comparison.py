"""
Автономный A/B отчёт: Main (с gates) vs Strip (без gates).
Только SELECT + запись отчёта + TTS. Никаких действий.

Запуск: python scripts/ab_comparison.py
Используется как cron-задача (раз в сутки, ~09:00 UTC).
"""
import os
import sqlite3
from datetime import datetime, timezone

MAIN_DB  = os.path.join(os.path.dirname(__file__), "..", "subscriptions.db")
STRIP_DB = r"e:\MTF BOT\CURSOR\crypto_volume_bot_strip\subscriptions.db"
REPORT_DIR = r"e:\tmp\cron_reports"

MIN_TRADES_TOTAL  = 30   # минимум сделок в одной БД для вывода
MIN_TRADES_TYPE   = 10   # минимум по signal_type для сравнения
DELTA_THRESHOLD   = 0.15  # Δ avgR = «gates помогают / режут»

SQL_STATS = """
    SELECT signal_type,
           COUNT(*) n,
           ROUND(AVG(R_multiple), 3) avgR,
           ROUND(SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) WR,
           ROUND(SUM(R_multiple), 1) sumR
    FROM simulated_trades
    WHERE status != 'OPEN'
      AND created_at >= datetime('now', '-24 hours')
    GROUP BY signal_type
    ORDER BY n DESC
"""


def _query_db(db_path: str) -> dict:
    """Возвращает {signal_type: {n, avgR, WR, sumR}} или None если БД недоступна."""
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(SQL_STATS)
        rows = {r["signal_type"]: dict(r) for r in cur.fetchall()}
        conn.close()
        return rows
    except Exception as e:
        print(f"[ab_comparison] DB error {db_path}: {e}")
        return None


def _tts(text: str) -> None:
    try:
        import subprocess
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.SelectVoice('Microsoft Irina Desktop'); "
            f"$s.Speak('{text}')"
        )
        subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps],
            timeout=15,
            capture_output=True,
        )
    except Exception:
        pass


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _fmt(val, fmt=".3f") -> str:
    if val is None:
        return "—"
    try:
        return format(float(val), fmt)
    except Exception:
        return str(val)


def main() -> None:
    date_str = _date_str()
    report_path = os.path.join(REPORT_DIR, f"ab_main_vs_strip_{date_str}.md")
    os.makedirs(REPORT_DIR, exist_ok=True)
    now = _now_str()

    main_data  = _query_db(MAIN_DB)
    strip_data = _query_db(STRIP_DB)

    lines = [f"# A/B Main vs Strip — {now}\n\n"]

    # ── Статус БД ──────────────────────────────────────────────────────────
    main_total  = sum(r["n"] for r in main_data.values())  if main_data  else 0
    strip_total = sum(r["n"] for r in strip_data.values()) if strip_data else 0

    if strip_data is None or strip_total == 0:
        lines.append("**Strip:** пустой/недоступен — A/B сравнение пропущено.\n\n")
        lines.append(f"**Main:** {main_total} сделок за 24ч.\n")
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        _tts("Отчёт A B: strip недоступен, данных нет")
        print(f"[ab_comparison] strip empty/unavailable -> {report_path}")
        return

    if main_total < MIN_TRADES_TOTAL or strip_total < MIN_TRADES_TOTAL:
        lines.append(
            f"**Недостаточно данных**: main={main_total}, strip={strip_total} "
            f"(порог {MIN_TRADES_TOTAL}).\n"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        _tts(f"Отчёт A B: недостаточно данных, main {main_total}, strip {strip_total}")
        print(f"[ab_comparison] not enough data (main={main_total}, strip={strip_total}) -> {report_path}")
        return

    # ── Сводная таблица ────────────────────────────────────────────────────
    lines.append(
        f"**Main:** {main_total} сделок | **Strip:** {strip_total} сделок\n\n"
    )
    lines.append(
        "| signal_type | main n | main avgR | main WR% | main sumR "
        "| strip n | strip avgR | strip WR% | strip sumR | Δ avgR |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")

    all_types = sorted(
        set(list(main_data.keys()) + list(strip_data.keys())),
        key=lambda t: (main_data.get(t, {}).get("n", 0) + strip_data.get(t, {}).get("n", 0)),
        reverse=True,
    )

    comparable: list[tuple[str, float]] = []  # (signal_type, delta_avgR) для вывода

    for st in all_types:
        m = main_data.get(st, {})
        s = strip_data.get(st, {})
        mn, mavgR = m.get("n", 0), m.get("avgR")
        sn, savgR = s.get("n", 0), s.get("avgR")

        delta = ""
        if mn >= MIN_TRADES_TYPE and sn >= MIN_TRADES_TYPE and mavgR is not None and savgR is not None:
            d = float(mavgR) - float(savgR)
            delta = f"{d:+.3f}"
            comparable.append((st, d))

        lines.append(
            f"| {st} "
            f"| {mn or '—'} | {_fmt(mavgR)} | {_fmt(m.get('WR'), '.1f')} | {_fmt(m.get('sumR'), '.1f')} "
            f"| {sn or '—'} | {_fmt(savgR)} | {_fmt(s.get('WR'), '.1f')} | {_fmt(s.get('sumR'), '.1f')} "
            f"| {delta} |\n"
        )

    lines.append("\n")

    # ── Вывод ──────────────────────────────────────────────────────────────
    if not comparable:
        verdict = "Недостаточно сравниваемых пар (n<10 в одном из ботов)."
        tts_text = "Отчёт A B: сравниваемых пар недостаточно"
    else:
        avg_delta = sum(d for _, d in comparable) / len(comparable)
        if avg_delta >= DELTA_THRESHOLD:
            verdict = (
                f"**Gates ПОМОГАЮТ**: средний Δ avgR = {avg_delta:+.3f}R "
                f"(main лучше strip на {len(comparable)} типах)."
            )
            tts_text = f"Gates помогают. Среднее улучшение {avg_delta:.2f} R"
        elif avg_delta <= -DELTA_THRESHOLD:
            verdict = (
                f"**Gates РЕЖУТ хорошие сделки**: средний Δ avgR = {avg_delta:+.3f}R "
                f"(strip лучше main на {len(comparable)} типах)."
            )
            tts_text = f"Внимание! Gates режут сделки. Разница {abs(avg_delta):.2f} R в пользу strip"
        else:
            verdict = (
                f"**Нейтрально**: средний Δ avgR = {avg_delta:+.3f}R "
                f"(меньше порога {DELTA_THRESHOLD}R)."
            )
            tts_text = f"A B нейтрально. Разница {avg_delta:.2f} R"

    lines.append(f"## Вывод\n\n{verdict}\n\n")
    lines.append("*Решения по gates — пользователю.*\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    _tts(tts_text)
    print(f"[ab_comparison] report -> {report_path} | verdict: {verdict[:60]}")


if __name__ == "__main__":
    main()
