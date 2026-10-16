# -*- coding: utf-8 -*-
"""Снапшот повестки для публичного /moment (Фаза 1, 15.10.2026).

Берёт живую повестку с приватного терминала :8010 (/api/agenda), переводит жаргон →
человеческий через docs/product/glossary.json и пишет компактный agenda.json рядом с
/moment. Публичного бэкенда нет: файл деплоится статикой на Cloudflare Pages, /moment
читает его через fetch('./agenda.json'). Запуск по расписанию (cron/pm2) + деплой.

    python scripts/moment_snapshot.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "docs" / "product" / "glossary.json"
OUT = ROOT / "docs" / "product" / "deploy" / "public" / "moment" / "agenda.json"
AGENDA_URL = "http://127.0.0.1:8010/api/agenda"

_G = json.loads(GLOSSARY.read_text(encoding="utf-8"))


def _fetch() -> dict:
    # Прямое соединение в обход системного прокси/VPN (localhost не должен идти через happ).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(AGENDA_URL, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _translate(text: str) -> str:
    """Мягкая замена жаргонных слов на человеческие (по вхождению, без учёта регистра)."""
    if not text:
        return text
    for frm, to in _G["phrases"]:
        low = text.lower()
        i = low.find(frm.lower())
        while i >= 0:
            text = text[:i] + to + text[i + len(frm):]
            low = text.lower()
            i = low.find(frm.lower(), i + len(to))
    return text


def _coins(n) -> str:
    """Русское склонение: '1 монета', '3 монеты', '5 монет'."""
    n = int(n or 0)
    t = abs(n) % 100
    if 11 <= t <= 14:
        w = "монет"
    else:
        d = t % 10
        w = "монета" if d == 1 else "монеты" if 2 <= d <= 4 else "монет"
    return f"{n} {w}"


def _fmt_price(x) -> str:
    """Цена с разумным числом значащих цифр, без хвостовых нулей."""
    if x is None:
        return "—"
    x = float(x)
    if x >= 100:
        s = f"{x:.2f}"
    elif x >= 1:
        s = f"{x:.4f}"
    else:
        s = f"{x:.6f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _verdict(d: dict) -> dict:
    light = d.get("light") or "yellow"
    return {"light": light,
            "title": _G["verdict"].get(light, "Сегодня — выборочно"),
            "sub": _translate(d.get("reason") or "")}


def _pulse(d: dict) -> dict:
    p = d.get("pulse") or {}
    win = p.get("win") or {}
    labels = {"15m": "15 мин", "2h": "2 часа", "6h": "6 часов"}
    move = [{"tf": labels[k], "dn": win[k]["dn"], "up": win[k]["up"]}
            for k in ("15m", "2h", "6h") if k in win]
    state = _G["pulse_state"].get(p.get("state") or "", (p.get("state") or "").lower())
    return {"state": state, "liq": p.get("liq") or "", "move": move,
            "stale": bool(p.get("stale"))}


def _gauges(d: dict) -> dict:
    brd = d.get("breadth") or {}
    drf = d.get("drift") or {}
    share = brd.get("share_pct") or 0
    hi = brd.get("share_hi_pct") or 15
    wide = bool(brd.get("wide"))
    breadth = {
        "label": "Падают разом", "meta": f"обвал — от {hi}%",
        "val": f"{share}%", "pct": min(100, round(share / hi * 100)) if hi else 0,
        "color": "green" if wide else "red",
        "cap": (f"{_coins(brd.get('day') or brd.get('now'))} из {brd.get('universe')} · "
                + ("обвал идёт" if wide else "обвала нет"))}

    d30 = drf.get("d30")
    if d30 is None:
        drift = {"label": "Рынок за 30 дней", "meta": "нет данных", "val": "—",
                 "pct": 0, "color": "s1", "cap": "дрейф вселенной неизвестен"}
    else:
        if drf.get("short_ok"):
            cap, color = "растёт — шорт в режиме", "green"
        elif d30 <= -30:
            cap, color = "рынок упал — шортить поздно", "amber"
        elif d30 > 0:
            cap, color = "растёт — для шорта рано", "amber"
        else:
            cap, color = "около нуля", "s1"
        drift = {"label": "Рынок за 30 дней", "meta": _coins(drf.get("coins")),
                 "val": f"{d30:+.1f}%", "pct": min(100, round(abs(d30) / 10 * 100)),
                 "color": color, "cap": cap}

    phase = {"label": "Фаза рынка", "meta": "справочно", "val": "пока неясно",
             "pct": 0, "color": "s1", "cap": "точным прибором не измеряли", "dim": True}
    return {"breadth": breadth, "drift": drift, "phase": phase}


def _measured(d: dict):
    """Измеренная строка — ТОЛЬКО когда сторона подтверждена прибором. Иначе не выдумываем."""
    if bool((d.get("breadth") or {}).get("wide")):
        return "Широкое падение 4 года из 4 давало отскок сильнее обычного часа — поэтому смотрим лонг."
    if bool((d.get("drift") or {}).get("short_ok")):
        return "Шорт в начале роста 4 года из 4 оказывался лучше обычного часа — поэтому шорт в режиме."
    return None


def _warn(raw: str):
    if not raw:
        return None
    low = raw.lower()
    if "вниз" in low:
        return _G["warn"]["down_against"]
    if "вверх" in low:
        return _G["warn"]["up_against"]
    return _translate(raw)


def _ideas(d: dict) -> dict:
    items = []
    pool = (d.get("long") or []) + (d.get("short") or [])
    for it in pool:
        p = it.get("plan") or {}
        if not p:
            continue
        long_ = it.get("side") == "long"
        items.append({
            "sym": it.get("sym"),
            "side": "ЛОНГ" if long_ else "ШОРТ", "side_cls": "long" if long_ else "short",
            "entry": _fmt_price(p.get("entry")),
            "stop": _fmt_price(p.get("sl")), "stop_pct": f"-{p.get('risk_pct')}%",
            "target": _fmt_price(p.get("tp")), "target_pct": f"+{p.get('rew_pct')}%",
            "lev": p.get("max_lev"), "rr": f"{p.get('rr')}",
            "warn": _warn(it.get("warn") or "")})
    n_pass = len(items)
    n_total = n_pass + len(d.get("skipped") or [])
    return {"title": "Если всё-таки смотришь",
            "note": f"{n_pass} из {n_total} прошли проверку — совпадения, издержки, оборот",
            "items": items}


def _dropped(d: dict) -> str:
    skipped = d.get("skipped") or []
    if not skipped:
        return ""
    buckets: dict[str, int] = {}
    for it in skipped:
        drop = (it.get("drop") or "").lower()
        label = "прочее"
        for key, human in _G["drop_labels"]:
            if key.lower() in drop:
                label = human
                break
        buckets[label] = buckets.get(label, 0) + 1
    parts = " · ".join(f"{k} — {v}" for k, v in sorted(buckets.items(), key=lambda x: -x[1]))
    return f"отсеяно {len(skipped)}: {parts}"


def build(d: dict) -> dict:
    now = int(time.time())
    utc = datetime.now(timezone.utc).strftime("%d.%m · %H:%M UTC")
    out = {
        "generated": now, "generated_utc": utc, "data_ts": d.get("ts_data") or d.get("ts"),
        "verdict": _verdict(d),
        "pulse": _pulse(d),
        "gauges": _gauges(d),
        "ideas": _ideas(d),
        "dropped": _dropped(d),
        "bot_demo": True,
    }
    m = _measured(d)
    if m:
        out["measured"] = m
    return out


def main() -> int:
    try:
        raw = _fetch()
    except Exception as e:
        print(f"[moment_snapshot] терминал :8010 недоступен: {e}", file=sys.stderr)
        return 1
    out = build(raw)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    v = out["verdict"]
    print(f"[moment_snapshot] {OUT.name}: {v['light']} · идей {len(out['ideas']['items'])} · {out['generated_utc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
