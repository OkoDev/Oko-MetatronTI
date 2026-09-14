"""📤 Публикация волновых разборов в TG-канал Oko_Waves (Егор 15.09: «TG канал - Oko_Waves -1003971555028»).

Настройки — data/wave5_shadow/tg.json: {"enabled": true, "chat_id": "...", "post_new": true, "post_closed": true}.
Токен — TELEGRAM_TOKEN из .env (тот же бот, что у проекта; живой бот и его обработчики не трогаются).
Шаблон отправки — как в scripts/wave_chart_send.py (sendPhoto через Bot API)."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "data" / "wave5_shadow" / "tg.json"


def tg_config() -> Dict[str, Any]:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False}


def _token() -> str:
    tok = os.getenv("TELEGRAM_TOKEN", "")
    if not tok:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env"); tok = os.getenv("TELEGRAM_TOKEN", "")
        except Exception:
            pass
    return tok


def caption_from_report(r: Dict[str, Any], side: Optional[str] = None, extra: str = "") -> str:
    """Подпись к схеме (≤1024 символов, HTML): монета · структура · зона · сценарии с целями и отменой."""
    e = html.escape
    txt = r.get("text") or []
    price = r.get("price") or 0
    head = f"🌊 <b>{e(r['sym'])}</b>" + (f" · {e(side)}" if side else "") + (" · ход в процессе" if r.get("mode") == "progress" else "") + f" · цена {price:.6g}"
    lines = [head]
    if txt:
        first = txt[0].split(": ", 1)[-1]
        lines.append("• " + e(first[:230]))
    zone = next((t for t in txt if t.startswith("Зона ")), None)
    if zone:
        lines.append("• " + e(zone[:200]))
    leg = next((t for t in txt if t.startswith("1D:")), None)
    if leg:
        lines.append("• " + e(leg[:160]))
    for sc in (r.get("scenarios") or [])[:2]:
        tg = [f"{v:.6g} ({(v / price - 1) * 100:+.0f}%)" for n, v in sc.get("targets", []) if v is not None and price][:3]
        lines.append(f"\n<b>{e(sc['name'])}</b>" + (": " + " · ".join(tg) if tg else ""))
        lines.append(f"⛔ {e(sc['invalid'][:120])}")
    if extra:
        lines.append(extra)
    lines.append(f"#волны #{e(r['sym'])}")
    cap = "\n".join(lines)
    return cap if len(cap) <= 1024 else cap[:1010] + "…"


def send_photo(png: Path, caption: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    import requests
    cfg = tg_config(); chat = chat_id or cfg.get("chat_id"); tok = _token()
    if not tok or not chat:
        return {"ok": False, "error": "нет TELEGRAM_TOKEN или chat_id"}
    with open(png, "rb") as f:
        rr = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                           files={"photo": f}, timeout=60)
    try:
        return rr.json()
    except Exception:
        return {"ok": False, "error": rr.text[:200]}


def send_text(text: str, chat_id: Optional[str] = None, reply_to: Optional[int] = None) -> Dict[str, Any]:
    import requests
    cfg = tg_config(); chat = chat_id or cfg.get("chat_id"); tok = _token()
    if not tok or not chat:
        return {"ok": False, "error": "нет TELEGRAM_TOKEN или chat_id"}
    data = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_to:
        data.update({"reply_to_message_id": reply_to, "allow_sending_without_reply": True})
    rr = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=30)
    try:
        return rr.json()
    except Exception:
        return {"ok": False, "error": rr.text[:200]}


def publish_report(r: Dict[str, Any], out_dir: Path, side: Optional[str] = None, extra: str = "") -> Dict[str, Any]:
    """Разбор из report_for → фото со схемой в канал (или текст, если схемы нет)."""
    cap = caption_from_report(r, side, extra)
    if r.get("png"):
        return send_photo(Path(out_dir) / r["png"], cap)
    return send_text(cap)
