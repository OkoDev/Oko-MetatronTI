"""
Автономный watchdog: stuck OPEN + catastrophic slippage.
ARCH-95 / LIVE-GUARD.

Только SELECT + алерт. Никаких действий.

Запуск: python scripts/watchdog_autonomous.py
Используется как cron-задача (каждый час).
"""
import os
import sqlite3
from datetime import datetime, timezone

MAIN_DB   = os.path.join(os.path.dirname(__file__), "..", "subscriptions.db")
STRIP_DB  = r"e:\MTF BOT\CURSOR\crypto_volume_bot_strip\subscriptions.db"
ALERT_DIR = r"e:\tmp\cron_reports"

STUCK_ALERT_FILE  = os.path.join(ALERT_DIR, "ALERT_stuck_open.md")
CATAS_ALERT_FILE  = os.path.join(ALERT_DIR, "ALERT_catastrophic.md")

STUCK_THRESHOLD_H = 24   # часов
STUCK_ALERT_N     = 3    # минимум записей для алерта
CATAS_R           = -3.0  # R < этого = catastrophic


# ── SQL ──────────────────────────────────────────────────────────────────────

SQL_STUCK = """
    SELECT id, symbol, signal_type, direction, regime,
           ROUND((julianday('now')-julianday(created_at))*24, 1) age_h,
           exchange_order_id
    FROM simulated_trades WHERE status='OPEN'
      AND (julianday('now')-julianday(created_at))*24 > :threshold_h
    ORDER BY age_h DESC LIMIT 10
"""

SQL_CATAS = """
    SELECT id, symbol, direction, R_multiple, sl_source, exit_price, stop_loss, entry_price
    FROM simulated_trades WHERE status='SL'
      AND R_multiple < :r_threshold
      AND created_at >= datetime('now','-1 hour')
      AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM'
    ORDER BY R_multiple ASC
"""


def _query(db_path: str, sql: str, params: dict) -> list:
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[watchdog] DB error {db_path}: {e}")
        return []


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


def _append_alert(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Проверки ─────────────────────────────────────────────────────────────────

def check_stuck_open() -> None:
    rows = _query(MAIN_DB, SQL_STUCK, {"threshold_h": STUCK_THRESHOLD_H})
    if len(rows) < STUCK_ALERT_N:
        return

    lines = [
        f"\n## [{_now_str()}] STUCK OPEN — {len(rows)} сделок > {STUCK_THRESHOLD_H}ч\n",
        "| id | symbol | type | dir | regime | age_h | exch_id |\n",
        "|---|---|---|---|---|---|---|\n",
    ]
    for r in rows:
        exch = (r["exchange_order_id"] or "—")[:30]
        lines.append(
            f"| {r['id']} | {r['symbol']} | {r['signal_type']} "
            f"| {r['direction']} | {r['regime']} | {r['age_h']} | {exch} |\n"
        )
    lines.append("\n")
    _append_alert(STUCK_ALERT_FILE, "".join(lines))

    tts_text = f"Внимание, {len(rows)} сделок висят больше 24 часов"
    _tts(tts_text)
    print(f"[watchdog] ALERT stuck_open: {len(rows)} sdelok -> {STUCK_ALERT_FILE}")


def check_catastrophic(db_path: str, label: str) -> None:
    rows = _query(db_path, SQL_CATAS, {"r_threshold": CATAS_R})
    if not rows:
        return

    lines = [
        f"\n## [{_now_str()}] CATASTROPHIC SLIPPAGE ({label}) — {len(rows)} сделок\n",
        "| id | symbol | dir | R | sl_source | exit | stop_loss | entry |\n",
        "|---|---|---|---|---|---|---|---|\n",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['symbol']} | {r['direction']} "
            f"| {r['R_multiple']:.2f} | {r['sl_source']} "
            f"| {r['exit_price']} | {r['stop_loss']} | {r['entry_price']} |\n"
        )
    lines.append("\n")
    _append_alert(CATAS_ALERT_FILE, "".join(lines))

    worst = rows[0]
    tts_text = (
        f"Катастрофический slippage {label}: "
        f"{worst['symbol'].replace('/USDT:USDT','').replace('/USDT','')} "
        f"R {worst['R_multiple']:.1f}"
    )
    _tts(tts_text)
    print(
        f"[watchdog] ALERT catastrophic ({label}): {len(rows)} sdelok, "
        f"worst={worst['symbol']} R={worst['R_multiple']:.2f} -> {CATAS_ALERT_FILE}"
    )


# ── Точка входа ───────────────────────────────────────────────────────────────

def main() -> None:
    check_stuck_open()
    check_catastrophic(MAIN_DB,  "MAIN")
    check_catastrophic(STRIP_DB, "STRIP")


if __name__ == "__main__":
    main()
