# -*- coding: utf-8 -*-
"""Мост радар → Куб (Егор 03.07: добро на шаг 1 интеграции SFERA-14).

Бот при регистрации сделки зовёт get_radar_context(symbol) → плоский dict радар-фичей
для features_json. SHADOW: на решения не влияет, кормит DS-MINING-FEATURES фичами
orderflow, которых нет ни в одном датасете проекта (OI-дельты, funding, магниты).

Источники (порт №2 радара — external_data.db, радар о Кубе не знает):
  radar_state       — live-контекст каждого тика oi-fast (60с): oi_d5/oi_d15/funding
  magnet_snapshots  — дневная карта магнитов (magnet-snap, 08:15 UTC)

Все ошибки глотаются → {} (радар лежит — сделки регистрируются как раньше).
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "external_data.db"
STATE_MAX_AGE_SEC = 300          # radar_state старше 5 мин = радар лежит, фичи протухли


def _norm(symbol: str) -> str:
    """'MANA/USDT:USDT' | 'MANAUSDT' | 'MANA' → 'MANA' (ключ радара)."""
    s = symbol.split("/")[0].split(":")[0].upper()
    return s[:-4] if s.endswith("USDT") else s


def get_radar_context(symbol: str) -> dict:
    """Радар-фичи для features_json. Пустой dict если данных нет/протухли."""
    sym = _norm(symbol)
    out: dict = {}
    try:
        c = sqlite3.connect(DB_PATH, timeout=2)
        try:
            try:      # quadrant добавлен 12.07 (OI×цена 15м) — старые БД без колонки
                row = c.execute("SELECT ts, px, oi_d5, oi_d15, funding, quadrant "
                                "FROM radar_state WHERE symbol=?", (sym,)).fetchone()
            except sqlite3.OperationalError:
                row = c.execute("SELECT ts, px, oi_d5, oi_d15, funding, NULL "
                                "FROM radar_state WHERE symbol=?", (sym,)).fetchone()
            if row and time.time() - row[0] <= STATE_MAX_AGE_SEC:
                out["radar_oi_d5"] = row[2]
                out["radar_oi_d15"] = row[3]
                out["radar_funding"] = row[4]
                if row[5]:
                    # квадрант OI×цена (12.07, ретро n=80: PDN+OIUP +0.88% vs PUP+OIUP −0.69%)
                    out["radar_oi_px_quadrant"] = row[5]
            m = c.execute("SELECT px, above_json, below_json FROM magnet_snapshots "
                          "WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
            if m:
                px_ref = row[1] if (row and row[1]) else m[0]   # свежая цена радара > цены снапшота
                above = json.loads(m[1] or "[]")
                below = json.loads(m[2] or "[]")
                if px_ref:
                    # цена могла уйти за снапшотный уровень (магнит потрачен) —
                    # берём ближайший строго СО СВОЕЙ стороны от ТЕКУЩЕЙ цены
                    up = [l for l, _ in above if l > px_ref]
                    dn = [l for l, _ in below if l < px_ref]
                    if up:
                        out["radar_magnet_above_pct"] = round((min(up) / px_ref - 1) * 100, 3)
                    if dn:
                        out["radar_magnet_below_pct"] = round((max(dn) / px_ref - 1) * 100, 3)
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        return {}
    return out
