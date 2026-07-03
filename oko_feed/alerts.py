"""FEED-ALERTS → Telegram (03.07.2026, запрос Егора после GRT-сквиза).

Пороговые события oko_feed → сообщение в TG (напрямую Bot API, без aiogram — standalone).
Антиспам: cooldown per (тип, символ) в таблице alert_log (external_data.db).

Алерты v1:
  🌀 oi_spike unwind_squeeze — СКВИЗ на монете ядра (тот механизм, что выбил GRT 03.07)
  📈 oi_spike build ≥1%/10м — резкая загрузка
  🐋 whale_swap ≥ $1M (Uniswap)
  ₿ BTC-флоу 3ч |net| ≥ 150 BTC — товар подвозят/увозят
  🔄 смена USDT.D-режима (risk_on ↔ risk_off)

Ключи: .env TELEGRAM_TOKEN + ADMIN_CHAT_ID.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from .store import conn

COOLDOWN_SEC = {"oi_squeeze": 1800, "oi_build": 1800, "whale": 3600,
                "btc_flow": 3600, "usdtd_regime": 600}


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip()
    try:                                             # .env вручную (standalone без dotenv)
        for ln in open(".env", encoding="utf-8"):
            if ln.startswith(name + "="):
                return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def send_tg(text: str) -> bool:
    token, chat = _env("TELEGRAM_TOKEN"), _env("ADMIN_CHAT_ID") or _env("CHAT_ID")
    if not token or not chat:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                       "parse_mode": "HTML", "disable_web_page_preview": "1"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data),
            timeout=15)
        return True
    except Exception:  # noqa: BLE001
        return False


def _cooldown_ok(c, key: str) -> bool:
    c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
    row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
    kind = key.split(":")[0]
    if row and time.time() - row[0] < COOLDOWN_SEC.get(kind, 1800):
        return False
    c.execute("INSERT OR REPLACE INTO alert_log VALUES (?, ?)", (key, int(time.time())))
    c.commit()
    return True


_last_regime: bool | None = None


def check_and_alert() -> list[str]:
    """Одна итерация проверок (зовётся из поллера каждые 10 мин). Возвращает отправленное."""
    global _last_regime
    sent = []
    c = conn()
    now = int(time.time())
    try:
        # 1-2) OI-спайки за последние 12 мин (радар их уже записал)
        for ts, sym, usd, d in c.execute(
                "SELECT ts,symbol,amount_usd,direction FROM onchain_events "
                "WHERE kind='oi_spike' AND ts>?", (now - 720,)).fetchall():
            coin = sym.split(" ")[0]
            if d == "unwind_squeeze" and _cooldown_ok(c, f"oi_squeeze:{coin}"):
                msg = (f"🌀 <b>СКВИЗ-сигнал: {coin}</b>\nOI {sym.split(' ',1)[1]} — закрытия позиций "
                       f"двигают цену (стопы = топливо).\nOI ${usd/1e6:.0f}M · механизм GRT-03.07")
                if send_tg(msg): sent.append(f"squeeze {coin}")
            elif d == "build" and _cooldown_ok(c, f"oi_build:{coin}"):
                msg = f"📈 <b>OI BUILD: {coin}</b>\n{sym.split(' ',1)[1]} за 10м — грузятся. OI ${usd/1e6:.0f}M"
                if send_tg(msg): sent.append(f"build {coin}")
        # 3) киты Uniswap ≥$1M за 12 мин
        for ts, sym, usd, d in c.execute(
                "SELECT ts,symbol,amount_usd,direction FROM onchain_events "
                "WHERE kind='whale_swap' AND amount_usd>=1000000 AND ts>?", (now - 720,)).fetchall():
            if _cooldown_ok(c, f"whale:{sym}"):
                arrow = "→ в стейблы (risk-off)" if d == "risk_off" else "← из стейблов (risk-on)" if d == "risk_on" else ""
                if send_tg(f"🐋 <b>КИТ ${usd/1e6:.2f}M</b> {sym} {arrow} (Uniswap)"):
                    sent.append(f"whale {sym}")
        # 4) BTC-флоу кумулятив 3ч
        inf = c.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                        "WHERE kind='btc_inflow' AND ts>?", (now - 10800,)).fetchone()[0]
        outf = c.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                         "WHERE kind='btc_outflow' AND ts>?", (now - 10800,)).fetchone()[0]
        net = outf - inf
        if abs(net) >= 150 and _cooldown_ok(c, "btc_flow:btc"):
            what = "⬆️ ВЫВОДЯТ в холд (бычье)" if net > 0 else "⬇️ ЗАВОДЯТ на биржи (медвежье)"
            if send_tg(f"₿ <b>BTC-флоу 3ч: {net:+.0f} BTC</b>\n{what} · in {inf:.0f} / out {outf:.0f}"):
                sent.append("btc_flow")
        # 5) смена USDT.D-режима
        try:
            import sys
            sys.path.insert(0, ".")
            from core.signals.usdtd_regime import get_usdtd_risk_off
            ro = get_usdtd_risk_off()
            if ro is not None and _last_regime is not None and ro != _last_regime:
                if _cooldown_ok(c, "usdtd_regime:flip"):
                    txt = "🔄 <b>USDT.D режим: RISK-OFF</b> — среда SHORT-эджа ВКЛ" if ro \
                        else "🔄 <b>USDT.D режим: RISK-ON</b> — шорты спят"
                    if send_tg(txt): sent.append("regime")
            if ro is not None:
                _last_regime = ro
        except Exception:  # noqa: BLE001
            pass
    finally:
        c.close()
    return sent
