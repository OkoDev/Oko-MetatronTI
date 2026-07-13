# -*- coding: utf-8 -*-
"""ПАСПОРТ МОНЕТЫ (11.07, Егор: «бот = второй глаз на 530 пар, аналитика а не сигналы»).

Пользователь шлёт тикер (BTC / SOL / 1000BONK) → мгновенная сводка ИЗ ГОТОВОГО:
шина Куба (SMC/WT/regime/пивоты, скан обновляет каждые ~2-3 мин) + Elliott
(bot._elliott_snap) + радар-стек (oko_feed/external_data.db: OI/funding/магниты)
+ компас. НИКАКИХ расчётов в хендлере — только чтение (ответ <1с, не 60с как
старый «Комплексный AI анализ»).

Фазы: 1=эта карточка · 2=чарт с уровнями · 3=кнопка 🧠 LLM-мнение (oko-analyst).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_FEED_DB = Path(__file__).resolve().parents[2] / "oko_feed" / "external_data.db"
_TICKER_RE = re.compile(r"^[A-Za-z0-9]{2,15}$")

_ARROW = {"TREND_UP": "📈", "TREND_DOWN": "📉", "RANGE": "↔️", "HIGH_VOL": "⚡"}


def resolve_symbol(bot, text: str) -> str | None:
    """'btc' / 'BONK' / '1000BONK' → 'BTC/USDT:USDT' из вселенной бота (иначе None)."""
    if not text or not _TICKER_RE.match(text.strip()):
        return None
    base = text.strip().upper()
    pairs = getattr(bot.data_collector, "usdt_pairs", None) or []
    def _base(p: str) -> str:
        return p.split("/")[0].upper()
    for p in pairs:                                   # точное совпадение базы
        if _base(p) == base:
            return p
    for pref in ("1000", "10000", "1000000"):         # BONK → 1000BONK
        for p in pairs:
            if _base(p) == pref + base:
                return p
    return None


def _fmt_px(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "?"
    return f"{v:.6g}"


def _nearest_pivots(pivot_snap: dict, price: float) -> list[str]:
    """Ближайший уровень сверху и снизу по каждому ТФ (1D/1W/1M)."""
    out = []
    for tf, label in (("1D", "Дн"), ("1W", "Нед"), ("1M", "Мес")):
        lvls = (pivot_snap or {}).get(tf)
        if not isinstance(lvls, dict):
            continue
        above = [(n, v) for n, v in lvls.items() if isinstance(v, (int, float)) and v > price]
        below = [(n, v) for n, v in lvls.items() if isinstance(v, (int, float)) and v < price]
        parts = []
        if above:
            n, v = min(above, key=lambda x: x[1])
            parts.append(f"↑{n} {_fmt_px(v)} (+{(v / price - 1) * 100:.1f}%)")
        if below:
            n, v = max(below, key=lambda x: x[1])
            parts.append(f"↓{n} {_fmt_px(v)} ({(v / price - 1) * 100:.1f}%)")
        if parts:
            out.append(f"  [{label}] " + " · ".join(parts))
    return out


def _wt_line(wt_snap: dict) -> str:
    parts = []
    for tf in ("15m", "1h", "4h", "1d"):
        d = (wt_snap or {}).get(tf)
        if not isinstance(d, dict):
            continue
        try:
            wt1 = float(d.get("wt1"))
        except (TypeError, ValueError):
            continue
        zone = d.get("zone") or ""
        mark = "🟢" if zone == "OS" else ("🔴" if zone == "OB" else "")
        cross = "⚡" if d.get("cross_in_zone") else ""
        parts.append(f"{tf} {wt1:+.0f}{mark}{cross}")
    return " · ".join(parts)


def _smc_lines(smc: dict, price: float) -> list[str]:
    if not isinstance(smc, dict):
        return []
    out = []
    bos, choch = smc.get("last_bos") or {}, smc.get("last_choch") or {}
    st = []
    if bos.get("direction"):
        st.append(f"BOS {'↑' if bos['direction'] == 'UP' else '↓'}")
    if choch.get("direction"):
        st.append(f"CHoCH {'↑' if choch['direction'] == 'UP' else '↓'}")
    if smc.get("price_in_ote"):
        st.append("в OTE")
    if smc.get("smc_verdict"):
        st.append(str(smc["smc_verdict"]))
    if st:
        out.append("  " + " · ".join(st))
    lv = []
    for key, nm in (("nearest_bull_ob", "OB bull"), ("nearest_bear_ob", "OB bear"),
                    ("eqh_level", "EQH"), ("eql_level", "EQL")):
        v = smc.get(key)
        if isinstance(v, dict):
            v = v.get("mid") or v.get("top") or v.get("price")
        if isinstance(v, (int, float)) and v > 0 and price > 0:
            lv.append(f"{nm} {_fmt_px(v)} ({(v / price - 1) * 100:+.1f}%)")
    if lv:
        out.append("  " + " · ".join(lv[:3]))
    return out


_QUAD_RU = {  # OI×цена квадрант — человеческая расшифровка (ретро n=80, 12.07)
    "PDN+OIUP": "цена↓+OI↑ — шорты грузятся (тренд оплачен) ✅",
    "PDN+OIFL": "цена↓, OI ровно",
    "PDN+OIDN": "цена↓+OI↓ — лонги закрываются (выдох)",
    "PUP+OIUP": "цена↑+OI↑ — поздние лонги? (ретро −0.7%) ⚠️",
    "PUP+OIFL": "цена↑ БЕЗ топлива (ретро WR0%) ⚠️",
    "PUP+OIDN": "цена↑+OI↓ — шорт-сквиз (закрытия, не деньги)",
    "PFL+OIUP": "флэт+OI↑ — ПРУЖИНА 🌀",
    "PFL+OIFL": "тишина",
    "PFL+OIDN": "флэт, OI утекает",
}


def _feed_block(symbol: str, price: float) -> list[str]:
    """Радар-стек из oko_feed/external_data.db (топ-50+hot): OI/funding/квадрант/магниты/компас."""
    out = []
    base = symbol.split("/")[0]
    try:
        c = sqlite3.connect(f"file:{_FEED_DB}?mode=ro", uri=True, timeout=3)
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM radar_state WHERE symbol=?", (base,)).fetchone()
        if r and time.time() - (r["ts"] or 0) < 3600:
            seg = []
            if r["oi_d5"] is not None:
                seg.append(f"OI {float(r['oi_d5']):+.1f}%/5м")
            if r["oi_d1d"] is not None:
                seg.append(f"{float(r['oi_d1d']):+.1f}%/день")
            if r["funding"] is not None:
                seg.append(f"fund {float(r['funding']) * 100:+.3f}%")
            if seg:
                out.append("💹 " + " · ".join(seg))
            try:                              # квадрант OI×цена (12.07, колонки может не быть)
                q = r["quadrant"]
                if q:
                    out.append(f"  🧭 15м: {_QUAD_RU.get(q, q)}")
            except (IndexError, KeyError):
                pass
        m = c.execute("SELECT * FROM magnet_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                      (base,)).fetchone()
        if m and time.time() - (m["ts"] or 0) < 12 * 3600:
            seg = []
            for col, mark in (("above_json", "↑"), ("below_json", "↓")):
                try:
                    arr = json.loads(m[col] or "[]")
                    if arr:
                        a = arr[0]
                        px, usd = float(a[0]), float(a[1])
                        if price > 0:
                            seg.append(f"{mark}🧲 {_fmt_px(px)} ({(px / price - 1) * 100:+.1f}%, ${usd / 1e6:.1f}M)")
                except Exception:
                    pass
            if seg:
                out.append("  " + " · ".join(seg))
        cp = c.execute("SELECT * FROM compass_log ORDER BY ts DESC LIMIT 1").fetchone()
        if cp and time.time() - (cp["ts"] or 0) < 3 * 3600:
            out.append(f"🧭 компас: {str(cp['bias']).upper()} {cp['confidence']}%")
        c.close()
    except Exception as e:
        logger.debug("[COIN-CARD] feed block %s: %s", symbol, e)
    return out


def _open_trades_block(bot, symbol: str) -> list[str]:
    try:
        db = bot.trade_simulator.db_path
        with sqlite3.connect(db, timeout=3) as c:
            rows = c.execute(
                "SELECT direction, signal_type, actual_entry_price, entry_price, stop_loss "
                "FROM simulated_trades WHERE symbol=? AND status='OPEN' "
                "AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' LIMIT 3",
                (symbol,)).fetchall()
        out = []
        for d, sig, ae, e, sl in rows:
            out.append(f"⚔️ позиция: {d} {sig} @ {_fmt_px(ae or e)} · SL {_fmt_px(sl)}")
        return out
    except Exception:
        return []


def build_radar_watch() -> str:
    """«радар» в TG (12.07, Егор «65 монет — где смотреть?!»): кого радар тикает СЕЙЧАС.
    HOT-хвост отдельно (🔥), топ-движения по |OI 15м|, квадранты. Всё из radar_state."""
    try:
        c = sqlite3.connect(f"file:{_FEED_DB}?mode=ro", uri=True, timeout=3)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT symbol, oi_d15, quadrant, is_hot FROM radar_state WHERE ts > ?",
            (int(time.time()) - 300,))]
        c.close()
    except Exception as e:
        return f"радар: нет данных ({e})"
    if not rows:
        return "радар: тишина (state старше 5 мин — радар лежит?)"
    hot = [r for r in rows if r.get("is_hot")]
    core = [r for r in rows if not r.get("is_hot")]
    def _fmt(r):
        d = f"{float(r['oi_d15']):+.1f}%" if r["oi_d15"] is not None else "—"
        q = r.get("quadrant") or ""
        return f"<code>{r['symbol']}</code> OI15м {d} {q}"
    lines = [f"📡 <b>РАДАР live</b>: {len(rows)} монет (ядро {len(core)} + 🔥 hot {len(hot)})"]
    if hot:
        lines.append("\n🔥 <b>HOT (движения дня):</b>")
        lines += ["  " + _fmt(r) for r in sorted(hot, key=lambda x: -abs(x["oi_d15"] or 0))]
    movers = sorted((r for r in core if r["oi_d15"] is not None),
                    key=lambda x: -abs(x["oi_d15"]))[:10]
    if movers:
        lines.append("\n📊 <b>Ядро — топ OI-движения 15м:</b>")
        lines += ["  " + _fmt(r) for r in movers]
    lines.append("\n<i>квадрант: P=цена OI=интерес за 15м · PDN+OIUP=шорты грузятся ✅ · "
                 "PUP+OIFL=рост без топлива ⚠️</i>")
    return "\n".join(lines)


async def send_coin_card(bot, message, symbol: str) -> None:
    """Карточка + чарт (reuse build_signal_chart) одним сообщением. Единая точка отправки
    для: тикер напрямую (handler.py unknown-ветка) и «Комплексный анализ» (analysis_handlers)."""
    card = await build_coin_card(bot, symbol)
    chart = None
    try:
        from core.ui.chart_builder import build_signal_chart
        # wave_overlay (11.07 Егор «BOS/CHoCH не хватает»): ZigZag+OB+FVG+BOS/CHoCH-разметка
        chart = await build_signal_chart(symbol, tf="1h", bot=bot, wave_overlay=True)
    except Exception as e:
        logger.debug("[COIN-CARD] chart %s: %s", symbol, e)
    if chart and len(card) <= 1024:                    # лимит caption Telegram
        from aiogram.types import BufferedInputFile
        await message.answer_photo(
            BufferedInputFile(chart, filename=f"{symbol.split('/')[0]}.png"),
            caption=card, parse_mode="HTML")
    else:
        await message.answer(card, parse_mode="HTML")


async def build_coin_card(bot, symbol: str) -> str:
    """HTML-карточка монеты. Только чтение готового — без расчётов и REST."""
    bus = getattr(bot, "pair_context", None)
    st = bus.get(symbol) if bus is not None else None
    price = float(getattr(st, "tick_price", 0) or 0)
    regime = getattr(st, "regime", None) or ""
    base = symbol.split("/")[0]

    head = f"🔋 <b>{base}</b>"
    if price > 0:
        head += f" · <code>{_fmt_px(price)}</code>"
    if regime:
        head += f" · {_ARROW.get(regime, '')} {regime}"
    lines = [head]

    wt = _wt_line(getattr(st, "wt_snap", None) or {})
    if wt:
        lines.append(f"〰 WT: {wt}")

    smc = _smc_lines(getattr(st, "smc_snap", None) or {}, price)
    if smc:
        lines.append("🧱 SMC:")
        lines.extend(smc)

    ell = (getattr(bot, "_elliott_snap", {}) or {}).get(symbol)
    if ell:
        lines.append(f"🌊 Эллиотт: n_down={ell.get('elliott_n_down')} "
                     f"n_up={ell.get('elliott_n_up')} ({ell.get('htf_tf')})")

    piv = _nearest_pivots(getattr(st, "pivot_snap", None) or {}, price) if price else []
    if piv:
        lines.append("📍 Пивоты:")
        lines.extend(piv)

    lines.extend(_feed_block(symbol, price))
    lines.extend(_open_trades_block(bot, symbol))

    if price <= 0 or not wt:
        lines.append("⏳ шина прогревается по этой паре — скан дойдёт за 2-3 мин, повтори запрос")
    lines.append(f"<i>{time.strftime('%H:%M UTC', time.gmtime())} · из шины Куба</i>")
    return "\n".join(lines)
