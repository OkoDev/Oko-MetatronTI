"""📤 Публикация волновых разборов в TG-канал Oko_Waves (Егор 15.09: «TG канал - Oko_Waves -1003971555028»).

Настройки — data/wave5_shadow/tg.json: {"enabled": true, "chat_id": "...", "post_new": true, "post_trades": true, "since": "..."}.
Токен — TELEGRAM_TOKEN из .env (тот же бот, что у проекта; живой бот и его обработчики не трогаются).
Шаблон отправки — как в scripts/wave_chart_send.py (sendPhoto через Bot API).
Обновления разбора, вход и выход — ОТВЕТОМ на предыдущее сообщение сетапа (Егор 15.09: «так динамику можно отслеживать»;
тот же приём reply_to, что в oko_feed/alerts.py для radar/oi-каналов)."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def caption_from_report(r: Dict[str, Any], side: Optional[str] = None, extra: str = "", note: str = "") -> str:
    """Подпись к схеме (≤1024 символов, HTML): монета · [что изменилось] · структура · зона · сценарии с целями и отменой."""
    e = html.escape
    txt = r.get("text") or []
    price = r.get("price") or 0
    head = (("🔄 " if note else "🌊 ") + f"<b>{e(r['sym'])}</b>" + (f" · {e(side)}" if side else "")
            + (" · ход в процессе" if r.get("mode") == "progress" else "") + f" · цена {price:.6g}")
    lines = [head]
    if note:
        lines.append(f"<b>Обновление:</b> {e(note)}")
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


def state_diff(old: Optional[Dict[str, Any]], new: Optional[Dict[str, Any]], price: float) -> List[str]:
    """Что значимо изменилось в разборе (отпечаток report_for()['state']). Пусто — постить обновление не нужно.
    Уровни сравниваются с допуском 1.5% цены: дневные пивоты сдвигают зону каждый день на копейки."""
    if not old or not new:
        return []
    tol = abs(price) * 0.015 if price else 0.0

    def moved(a, b):
        return (a is None) != (b is None) or (a is not None and abs(a - b) > tol)

    def f(v):
        return f"{v:.6g}"
    out: List[str] = []
    switched = old.get("mode") != new.get("mode")
    if switched:
        out.append("пятёрка завершена — разворотный разбор" if new.get("mode") == "reversal" else "завершённой пятёрки больше нет — ход в процессе")
    if old.get("zone_1d") != new.get("zone_1d") and new.get("zone_1d"):
        out.append(f"зона в дневной ноге: {old.get('zone_1d')} → {new['zone_1d']}")
    if old.get("p5") is not None and new.get("p5") is not None and moved(old.get("p5"), new.get("p5")):
        out.append(f"экстремум пятой обновлён: {f(new['p5'])}")
    if old.get("choch") is None and new.get("choch") is not None:
        out.append(f"слом младшего ТФ против хода на {f(new['choch'])} — волна A пошла")
    if old.get("choch_sw") is None and new.get("choch_sw") is not None:
        out.append(f"старший слом младшего ТФ на {f(new['choch_sw'])}")
    if not old.get("a_done") and new.get("a_done"):
        out.append("волна A закончена (встречный слом) — ждём откат в зону 0.5–0.705")
    if not old.get("zone_touch") and new.get("zone_touch"):
        out.append("цена дошла до зоны отката волны A")
    if switched:                                      # поля другого режима сравнивать бессмысленно
        return out
    if old.get("count_k") != new.get("count_k") and new.get("count_k") is not None:
        out.append(f"счёт: 0–{old.get('count_k')} → 0–{new['count_k']}")
    elif any(moved(a, b) for a, b in zip(old.get("count_px") or [], new.get("count_px") or [])):
        out.append("точки счёта сдвинулись")
    if moved(old.get("zone_lo"), new.get("zone_lo")) or moved(old.get("zone_hi"), new.get("zone_hi")):
        out.append(f"зона: {f(new['zone_lo'])}–{f(new['zone_hi'])}" if new.get("zone_lo") is not None else "зона схождения уровней пропала")
    if old.get("tri") != new.get("tri"):
        out.append(f"треугольник: {new['tri']}" if new.get("tri") else "треугольник больше не виден")
    if old.get("scen") != new.get("scen") and not out:
        out.append("сценарии пересобраны")
    return out


def _post(method: str, data: Dict[str, Any], files=None, timeout: int = 30) -> Dict[str, Any]:
    import requests
    cfg = tg_config(); tok = _token()
    data = {k: v for k, v in data.items() if v is not None}
    data.setdefault("chat_id", cfg.get("chat_id")); data["parse_mode"] = "HTML"
    if not tok or not data.get("chat_id"):
        return {"ok": False, "error": "нет TELEGRAM_TOKEN или chat_id"}
    if data.get("reply_to_message_id"):
        data["allow_sending_without_reply"] = True
    rr = requests.post(f"https://api.telegram.org/bot{tok}/{method}", data=data, files=files, timeout=timeout)
    try:
        return rr.json()
    except Exception:
        return {"ok": False, "error": rr.text[:200]}


def send_photo(png: Path, caption: str, chat_id: Optional[str] = None, reply_to: Optional[int] = None) -> Dict[str, Any]:
    with open(png, "rb") as fh:
        return _post("sendPhoto", {"chat_id": chat_id, "caption": caption, "reply_to_message_id": reply_to}, files={"photo": fh}, timeout=60)


def send_text(text: str, chat_id: Optional[str] = None, reply_to: Optional[int] = None) -> Dict[str, Any]:
    return _post("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "reply_to_message_id": reply_to})


def publish_report(r: Dict[str, Any], out_dir: Path, side: Optional[str] = None, extra: str = "", note: str = "",
                   reply_to: Optional[int] = None) -> Dict[str, Any]:
    """Разбор из report_for → фото со схемой в канал (или текст, если схемы нет); note — что изменилось (для обновления)."""
    cap = caption_from_report(r, side, extra, note)
    if r.get("png"):
        return send_photo(Path(out_dir) / r["png"], cap, reply_to=reply_to)
    return send_text(cap, reply_to=reply_to)


def message_id(res: Dict[str, Any]) -> Optional[int]:
    return (res.get("result") or {}).get("message_id") if res.get("ok") else None
