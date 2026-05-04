"""
Автономный мониторинг DEV-185: p90 SL overshoot.
Только SELECT + отчёт + TTS. Никаких изменений config.

Overshoot = насколько цена прошла СКВОЗЬ стоп-лосс при реальном исполнении.
- LONG: ov = (stop_loss - exit_price) / entry_price * 100
- SHORT: ov = (exit_price - stop_loss) / entry_price * 100
Положительный overshoot = проскальзывание за стоп.

Запуск: python scripts/dev185_overshoot_monitor.py
Cron: раз в сутки ~08:43 UTC.
"""
import os
import sqlite3
import statistics
from datetime import datetime, timezone

MAIN_DB    = os.path.join(os.path.dirname(__file__), "..", "subscriptions.db")
REPORT_DIR = r"e:\tmp\cron_reports"

P90_TARGET   = 2.0   # %  — цель DEV-185 шаг 1
P90_WARN     = 2.5   # %  — граница «buffer не помогает»
CATAS_PCT    = 5.0   # %  — catastrophic overshoot

SQL = """
    SELECT id, symbol, direction, entry_price, stop_loss, exit_price, R_multiple, sl_source
    FROM simulated_trades
    WHERE status = 'SL'
      AND exchange_order_id IS NOT NULL
      AND exchange_order_id != ''
      AND exchange_order_id != 'SIM'
      AND created_at >= datetime('now', '-24 hours')
"""

BUCKETS = [
    (0.0,   0.5,  "0–0.5%"),
    (0.5,   1.0,  "0.5–1%"),
    (1.0,   2.0,  "1–2%"),
    (2.0,   5.0,  "2–5%"),
    (5.0,  10.0,  "5–10%"),
    (10.0, 999.0, "10%+"),
]


def _query(db_path: str) -> list:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(SQL)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _overshoot(row: dict) -> float | None:
    """Overshoot в % от entry. None если данных нет или нет проскальзывания."""
    try:
        ep  = float(row["entry_price"])
        sl  = float(row["stop_loss"])
        ex  = float(row["exit_price"])
        if ep <= 0:
            return None
        d = row["direction"]
        if d == "LONG":
            ov = (sl - ex) / ep * 100   # LONG: exit ниже SL → положительный overshoot
        elif d == "SHORT":
            ov = (ex - sl) / ep * 100   # SHORT: exit выше SL → положительный overshoot
        else:
            return None
        return round(ov, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    data_s = sorted(data)
    idx = (p / 100) * (len(data_s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(data_s) - 1)
    return round(data_s[lo] + (data_s[hi] - data_s[lo]) * (idx - lo), 4)


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


def main() -> None:
    date_str    = _date_str()
    report_path = os.path.join(REPORT_DIR, f"dev185_overshoot_{date_str}.md")
    os.makedirs(REPORT_DIR, exist_ok=True)

    rows = _query(MAIN_DB)
    lines = [f"# DEV-185 Overshoot Monitor — {_now_str()}\n\n"]

    if not rows:
        lines.append("Нет SL-сделок с реальным исполнением за 24ч.\n")
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[dev185] no data -> {report_path}")
        return

    # ── Вычисляем overshoot ───────────────────────────────────────────────
    overshoots: list[float] = []
    catastrophic: list[dict] = []
    no_data_count = 0

    for r in rows:
        ov = _overshoot(r)
        if ov is None:
            no_data_count += 1
            continue
        overshoots.append(ov)
        if ov >= CATAS_PCT:
            catastrophic.append({**r, "overshoot_pct": ov})

    if not overshoots:
        lines.append(f"Нет данных для расчёта overshoot ({len(rows)} сделок, данные неполные).\n")
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[dev185] no overshoot data -> {report_path}")
        return

    p50 = _percentile(overshoots, 50)
    p90 = _percentile(overshoots, 90)
    p_max = max(overshoots)
    avg_r = round(
        sum(r.get("R_multiple", 0) or 0 for r in rows if _overshoot(r) is not None) / len(overshoots), 3
    )
    positive_ov = [o for o in overshoots if o > 0]
    negative_ov = [o for o in overshoots if o <= 0]  # исполнено ЛУЧШЕ стопа

    lines.append(f"**Сделок:** {len(rows)} SL-live | **С overshoot-данными:** {len(overshoots)}\n\n")

    # ── Ключевые метрики ──────────────────────────────────────────────────
    p90_status = "✅" if p90 <= P90_TARGET else ("⚠️" if p90 <= P90_WARN else "🔴")
    lines.append("## Ключевые метрики\n\n")
    lines.append(f"| Метрика | Значение | Цель |\n|---|---|---|\n")
    lines.append(f"| p50 overshoot | {p50:.3f}% | — |\n")
    lines.append(f"| p90 overshoot | {p90:.3f}% | {p90_status} ≤{P90_TARGET}% |\n")
    lines.append(f"| max overshoot | {p_max:.3f}% | — |\n")
    lines.append(f"| avg R_multiple | {avg_r:.3f} | — |\n")
    lines.append(f"| исполнено лучше SL | {len(negative_ov)} ({len(negative_ov)*100//len(overshoots)}%) | — |\n")
    lines.append(f"| catastrophic (≥{CATAS_PCT}%) | {len(catastrophic)} | 0 |\n\n")

    # ── Бакеты ────────────────────────────────────────────────────────────
    lines.append("## Распределение overshoot\n\n")
    lines.append("| Диапазон | Кол-во | % |\n|---|---|---|\n")
    for lo, hi, label in BUCKETS:
        cnt = sum(1 for o in overshoots if lo <= o < hi)
        pct = cnt * 100 // len(overshoots) if overshoots else 0
        lines.append(f"| {label} | {cnt} | {pct}% |\n")
    lines.append("\n")

    # ── Catastrophic список ───────────────────────────────────────────────
    if catastrophic:
        lines.append(f"## Catastrophic overshoot (≥{CATAS_PCT}%) — {len(catastrophic)} сделок\n\n")
        lines.append("| id | symbol | dir | ov% | R | sl_source |\n|---|---|---|---|---|---|\n")
        for c in sorted(catastrophic, key=lambda x: x["overshoot_pct"], reverse=True):
            lines.append(
                f"| {c['id']} | {c['symbol']} | {c['direction']} "
                f"| {c['overshoot_pct']:.2f}% | {c.get('R_multiple', '—'):.2f} "
                f"| {c.get('sl_source', '—')} |\n"
            )
        lines.append("\n")

    # ── Вердикт DEV-185 ───────────────────────────────────────────────────
    lines.append("## Вердикт DEV-185\n\n")
    if p90 <= P90_TARGET and len(catastrophic) == 0:
        verdict = (
            f"✅ **Можно поднимать buffer 1.0→2.0 (DEV-185 шаг 2).**\n"
            f"p90={p90:.3f}% ≤ цели {P90_TARGET}%, catastrophic=0."
        )
        tts_text = f"D E V 185: p90 {p90:.1f} процент, catastrophic ноль. Можно поднимать buffer."
    elif p90 > P90_WARN or len(catastrophic) > 0:
        reason = []
        if p90 > P90_WARN:
            reason.append(f"p90={p90:.3f}% > {P90_WARN}%")
        if catastrophic:
            worst = max(catastrophic, key=lambda x: x["overshoot_pct"])
            reason.append(f"catastrophic={len(catastrophic)} (worst {worst['symbol']} {worst['overshoot_pct']:.1f}%)")
        verdict = (
            f"🔴 **Buffer не помогает, разбираться.**\n"
            + " | ".join(reason)
        )
        tts_text = (
            f"D E V 185: p90 {p90:.1f} процент, "
            f"catastrophic {len(catastrophic)}. Buffer не помогает, нужно разбираться."
        )
    else:
        verdict = (
            f"⚠️ **Наблюдать ещё день.**\n"
            f"p90={p90:.3f}% (цель {P90_TARGET}%, граница {P90_WARN}%), catastrophic={len(catastrophic)}."
        )
        tts_text = f"D E V 185: p90 {p90:.1f} процент, catastrophic {len(catastrophic)}. Наблюдать ещё день."

    lines.append(verdict + "\n\n")
    lines.append("*Изменение sl_limit_buffer_pct — только пользователь.*\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    _tts(tts_text)
    print(
        f"[dev185] p90={p90:.3f}% | catastrophic={len(catastrophic)} | "
        f"n={len(overshoots)} -> {report_path}"
    )


if __name__ == "__main__":
    main()
