"""Daily Trade Review + Watch List — анализ вчерашних/последних сделок + живые свечи топ символов.

Pipeline (двухфазный):
  Phase 1 (текст):
    1. SELECT trades за N часов из subscriptions.db
    2. Топ-N активных символов за 7 дней → fetch OHLCV (15m/1h/4h) через ccxt.bingx
    3. TA снимок: WT zone, ATR trend, EMA50 по каждому TF
    4. Gemini анализирует сделки + Watch List → топ-3 сетапа
  Phase 2 (vision):
    5. Composite PNG (15m/1h/4h) для каждого топ-3 символа (через chart_builder + PIL)
    6. Gemini Vision — анализ графиков
    7. TG: текст дайджест + composite PNG для каждого топ-3

Output: memory/last_trade_review.md + obsidian/Daily-Review/YYYY-MM-DD.md + TG

Запуск:
  python tools/daily_trade_review.py             # за последние 24ч
  python tools/daily_trade_review.py --hours 12  # за последние 12ч
  python tools/daily_trade_review.py --quiet     # минимум вывода (для hook)
  python tools/daily_trade_review.py --max-age-hours 18  # skip если свежий
  python tools/daily_trade_review.py --no-watchlist      # только сделки, без биржи
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = PROJECT_ROOT / ".env"
DB_PATH = PROJECT_ROOT / "subscriptions.db"

OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "last_trade_review.md"
OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Daily-Review"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 10000

WATCHLIST_N = 10
WATCHLIST_TFS = ["15m", "1h", "4h"]
WATCHLIST_OHLCV_LIMIT = 120  # дефолт для 15m/4h
# 1h нужно 530 свечей для недельных пивотов (_calc_pivot_levels требует 3+ полных недели)
WATCHLIST_TF_LIMITS = {"15m": 120, "1h": 530, "4h": 120}

try:
    from core.indicators.indicators import calculate_wt, calculate_trend
    _CORE_OK = True
except Exception:
    _CORE_OK = False

try:
    import ccxt.async_support as _ccxt_async
    _CCXT_OK = True
except Exception:
    _CCXT_OK = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mplfinance as mpf
    _MPF_OK = True
except Exception:
    _MPF_OK = False


# ─── Prompts ──────────────────────────────────────────────────────────────────

REVIEW_PROMPT = """Ты — TRADER, разбираешь торговый день бота Oko MTF.
Тебе даны статистика по {n_total} закрытым сделкам за последние {hours} часов
и живой TA снимок Watch List ({n_watch} символов).
Сделай ЁМКИЙ разбор для следующей сессии Claude.

ФОРМАТ (markdown, русский, ~300-500 строк МАКСИМУМ):

# Trade Review — {date} (за {hours}ч)

## 🎯 Главный вывод дня (2-3 строки)
- Был день прибыльный или убыточный
- Какая стратегия сегодня лидер / антилидер
- Что главное стоит отметить

## 📊 Сводка
- Total: n=X, avgR=Y, WR=Z%
- Закрытий по статусам: TP / SL / TSL / EXPIRED
- Сумма R за период

## 🏆 По signal_type (отсортировано по totalR)
Таблица: signal_type | n | avgR | WR | totalR

Подсветить особо хороших (avgR > +0.3) и плохих (avgR < -0.5).

## 🔬 По regime
Таблица: regime | n | avgR | WR
Видны ли паттерны? Какой регим прибылен, какой убыточен?

## 🧭 По direction
LONG: n=X, avgR=Y. SHORT: n=X, avgR=Y.
Какое направление работало?

## 🏗️ По strategy_type (SINGLE / DUAL_TP / DUAL_TSL)
Таблица. Какой type сегодня прибылен?

## ⭐ TOP-3 winners (R > +1.0)
Для каждого: id, symbol, signal_type, regime, R, sl_source.

## 💥 TOP-3 losers (R < -1.0)
Для каждого: id, symbol, signal_type, regime, R, sl_source, **в чём вероятно ошибка**
(прочитай features_json что упомянуто — strength, entry_priority, ote, mtf alignment, etc).

## 📡 Watch List — живой TA снимок
Смотри таблицу ниже. Выдели:
- Топ-3 потенциальных входа (LONG/SHORT): символ, TF входа, почему интересны (WT OS/OB, тренд, confluence)
- Символы которых избегать сейчас и почему

## 🧪 Гипотезы / наблюдения
3-5 пунктов: что подозрительно, что стоит проверить отдельным бэктестом.

## 🎯 Что предложить TRADER/DEV
Конкретные действия которые могут улучшить ситуацию.

ПРАВИЛА:
- ТОЛЬКО факты из источника. Не выдумывай числа.
- Цитируй id сделок, symbol, signal_type.
- Bullet-points. Не повторяйся.
- Только русский.
- В самом конце добавь строку (для автопарсинга, точный формат, символы из Watch List):
  TOP3: SYMBOL1, SYMBOL2, SYMBOL3

ИСТОЧНИК:

{stats_block}

=== TOP WINNERS (полные записи) ===
{winners_block}

=== TOP LOSERS (полные записи) ===
{losers_block}

=== WATCH LIST — ЖИВОЙ TA СНИМОК ({n_watch} символов, {ts_utc} UTC) ===
{watchlist_block}
"""

VISION_PROMPT = """Ты TRADER. Chart {symbol}: 15m / 1h / 4h (сверху вниз).

Выжимка строго по шаблону. Без объяснений, только факты и числа. Максимум 18 строк.

Шаблон:

📡 {symbol}

📈 15m [↗ UP / ↘ DN / → SWY] · 1h [↗/↘/→] · 4h [↗/↘/→]

〰 WT
  15m [OS/OB/нейтрал] [↑/↓] [крест ↑/↓ если есть]
  1h  [OS/OB/нейтрал] [↑/↓] [крест ↑/↓ если есть]
  4h  [OS/OB/нейтрал] [↑/↓] [дивергенция если есть]

🏛 Пивоты
  W: [PP цена] · [S1/R1 цена] · [S2/R2 цена]  ← цена [выше ↑ / ниже ↓] W:PP
  D: [PP цена] · [S1/R1 цена] · [S2/R2 цена]  ← ближайшая поддержка/сопротивление

🎯 [SHORT / LONG / Ждать: причина одной строкой]
  Вход:  [цена или диапазон]
  SL:    [цена]  ([% от входа]  [за что])
  TP1:   [цена]  ([уровень])
  TP2:   [цена]  ([уровень])
"""


# ─── Env / DB ─────────────────────────────────────────────────────────────────

def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def fetch_trades(hours: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, symbol, signal_type, direction, regime, strategy_type, strategy_name,
               R_multiple, status, profit_pct, captured_R_pct, max_R_possible,
               strength, confidence, tsl_activated, be_activated,
               sl_source, tp_source, source_router,
               first_profit_r, first_drawdown_r, duration_minutes,
               features_json, decision_trace_json,
               entry_price, stop_loss, take_profit, exit_price,
               created_at, closed_at
        FROM simulated_trades
        WHERE status != 'OPEN' AND closed_at IS NOT NULL AND closed_at >= ?
        ORDER BY closed_at DESC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def safe_features_brief(features_json: str | None, keys: list[str]) -> dict:
    if not features_json:
        return {}
    try:
        d = json.loads(features_json)
    except Exception:
        return {}
    return {k: d.get(k) for k in keys if k in d}


def compute_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    rs = [t.get("R_multiple") or 0.0 for t in trades]
    statuses = [t.get("status") for t in trades]
    avg_r = sum(rs) / n if n else 0.0
    wr = 100 * sum(1 for r in rs if r > 0) / n if n else 0.0
    total_r = sum(rs)

    def group(field: str) -> list[dict]:
        bucket: dict[str, list] = defaultdict(list)
        for t in trades:
            bucket[t.get(field) or "<NULL>"].append(t.get("R_multiple") or 0.0)
        rows = []
        for k, vs in bucket.items():
            rows.append({
                "key": k, "n": len(vs),
                "avgR": round(sum(vs) / len(vs), 3),
                "WR": round(100 * sum(1 for r in vs if r > 0) / len(vs), 1),
                "totalR": round(sum(vs), 2),
            })
        rows.sort(key=lambda x: x["totalR"], reverse=True)
        return rows

    return {
        "n": n, "avgR": round(avg_r, 3), "WR": round(wr, 1), "totalR": round(total_r, 2),
        "status_counts": {s: statuses.count(s) for s in set(statuses)},
        "by_signal_type": group("signal_type"),
        "by_regime": group("regime"),
        "by_direction": group("direction"),
        "by_strategy_type": group("strategy_type"),
    }


def fmt_stats_block(stats: dict, hours: int) -> str:
    if stats.get("n", 0) == 0:
        return f"[нет закрытых сделок за последние {hours} часов]"
    lines = [
        f"Total: n={stats['n']}, avgR={stats['avgR']}, WR={stats['WR']}%, totalR={stats['totalR']}",
        f"Status counts: {stats['status_counts']}",
        "",
        "By signal_type (sorted by totalR):",
    ]
    for r in stats["by_signal_type"]:
        lines.append(f"  {r['key']}: n={r['n']} avgR={r['avgR']} WR={r['WR']}% totalR={r['totalR']}")
    lines += ["", "By regime:"]
    for r in stats["by_regime"]:
        lines.append(f"  {r['key']}: n={r['n']} avgR={r['avgR']} WR={r['WR']}%")
    lines += ["", "By direction:"]
    for r in stats["by_direction"]:
        lines.append(f"  {r['key']}: n={r['n']} avgR={r['avgR']} WR={r['WR']}%")
    lines += ["", "By strategy_type:"]
    for r in stats["by_strategy_type"]:
        lines.append(f"  {r['key']}: n={r['n']} avgR={r['avgR']} WR={r['WR']}%")
    return "\n".join(lines)


def fmt_trade(t: dict, with_features: bool = True) -> str:
    feature_keys = [
        "entry_priority", "entry_priority_reason", "atr_trend_1h_bias", "atr_tf",
        "ote_zone", "ote_direction", "price_in_ote", "trigger_source",
        "signal_mode", "confirmations_count", "confirmations_sources",
        "all_signal_types", "n_supporting",
        "pivot_real_touch", "pivot_close_rejection", "pivot_volume_z",
        "wt_b_zone", "wt_b_div_strength",
        "trade_mode", "rr_at_entry",
    ]
    feats = safe_features_brief(t.get("features_json"), feature_keys) if with_features else {}
    return (
        f"id={t['id']} {t.get('symbol')} {t.get('direction')} sig={t.get('signal_type')} "
        f"strat={t.get('strategy_type')} regime={t.get('regime')} R={t.get('R_multiple')} "
        f"status={t.get('status')} dur={t.get('duration_minutes')}min "
        f"first_profit_r={t.get('first_profit_r')} first_drawdown_r={t.get('first_drawdown_r')} "
        f"captured={t.get('captured_R_pct')}% maxR={t.get('max_R_possible')} "
        f"sl_src={t.get('sl_source')} tp_src={t.get('tp_source')} "
        f"strength={t.get('strength')} conf={t.get('confidence')} "
        f"tsl_act={t.get('tsl_activated')} be_act={t.get('be_activated')}\n"
        f"  features: {feats}"
    )


# ─── Gemini text ──────────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    cfg_kwargs: dict = dict(
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        system_instruction=(
            "Ты — TRADER-аналитик. Только русский. Только факты из источника. "
            "ЗАПРЕЩЕНО повторение. Если поймал петлю — закрывай раздел."
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
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg:
            print(f"[trade_review] 503 → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
            resp = client.models.generate_content(
                model=GEMINI_MODEL_FALLBACK, contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return (resp.text or "").strip(), GEMINI_MODEL_FALLBACK
        raise


def _fmt_ta_snapshot_line(ta_snapshot: dict | None) -> str:
    """Форматирует числовой TA снимок для вставки в vision промпт."""
    if not ta_snapshot:
        return ""
    parts = []
    for tf in WATCHLIST_TFS:
        d = (ta_snapshot.get("tfs") or {}).get(tf)
        if d:
            parts.append(f"{tf} wt1={d['wt1']:+.1f} zone={d['zone']} trend={d['trend']}")
    if not parts:
        return ""
    return "TA snapshot: " + " · ".join(parts)


def call_gemini_vision(png_bytes: bytes, symbol: str, ta_snapshot: dict | None = None) -> str:
    """Вызов Gemini с composite PNG для visual analysis."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "[google-genai не установлен]"

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return "[GEMINI_API_KEY не задан]"

    try:
        client = genai.Client(api_key=key)
        snapshot_line = _fmt_ta_snapshot_line(ta_snapshot)
        prompt_text = VISION_PROMPT.format(symbol=symbol)
        if snapshot_line:
            prompt_text = prompt_text.replace(
                "Выжимка строго по шаблону.",
                f"{snapshot_line}\n\nВыжимка строго по шаблону.",
            )
        contents = [
            types.Part.from_text(text=prompt_text),
            types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
        ]
        resp = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=2000,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                system_instruction=(
                    "Только русский. Только факты с графика. "
                    "БЕЗ markdown разметки — никаких **, *, _, #. "
                    "Строго следуй шаблону. Никакой воды, только числа и символы."
                ),
            ),
        )
        # Логируем обрезку
        try:
            reason = resp.candidates[0].finish_reason if resp.candidates else "unknown"
            if str(reason) not in ("FinishReason.STOP", "STOP", "1"):
                print(f"[vision] finish_reason={reason} — возможна обрезка", file=sys.stderr)
        except Exception:
            pass
        return (resp.text or "").strip()
    except Exception as e:
        return f"[vision error: {e}]"


# ─── Watch List: fetch OHLCV ──────────────────────────────────────────────────

def fetch_watchlist_symbols(n: int = WATCHLIST_N) -> list[str]:
    """Топ-N символов: активные из сделок (7 дней) + пропущенные из signal_drops (4ч)."""
    conn = sqlite3.connect(str(DB_PATH))

    rows = conn.execute(
        """
        SELECT symbol, COUNT(*) as cnt
        FROM simulated_trades
        WHERE created_at > datetime('now', '-7 days')
        GROUP BY symbol ORDER BY cnt DESC LIMIT ?
        """,
        (n,),
    ).fetchall()
    trade_syms = [r[0] for r in rows]

    drop_syms: list[str] = []
    try:
        rows2 = conn.execute(
            """
            SELECT symbol, COUNT(*) as cnt
            FROM signal_drops
            WHERE dropped_at > datetime('now', '-4 hours')
              AND symbol IS NOT NULL AND symbol != ''
            GROUP BY symbol ORDER BY cnt DESC LIMIT ?
            """,
            (n,),
        ).fetchall()
        drop_syms = [r[0] for r in rows2]
    except Exception:
        pass  # таблица signal_drops может отсутствовать на старых инсталляциях

    conn.close()

    # Объединяем: сначала из сделок, потом уникальные из signal_drops
    seen: set[str] = set(trade_syms)
    result = list(trade_syms)
    added_from_drops = 0
    for s in drop_syms:
        if s not in seen:
            seen.add(s)
            result.append(s)
            added_from_drops += 1
    if added_from_drops:
        print(f"[watch] +{added_from_drops} символов из signal_drops", file=sys.stderr)

    return result[:n]


async def _fetch_all_ohlcv(symbols: list[str], tfs: list[str], limit: int) -> dict[str, dict[str, pd.DataFrame | None]]:
    """Параллельный fetch OHLCV: один shared exchange + load_markets один раз + Semaphore(5)."""
    exch = _ccxt_async.bingx({"enableRateLimit": True})
    sem = asyncio.Semaphore(5)

    async def _fetch(sym: str, tf: str) -> pd.DataFrame | None:
        tf_limit = WATCHLIST_TF_LIMITS.get(tf, limit)
        async with sem:
            try:
                raw = await asyncio.wait_for(exch.fetch_ohlcv(sym, tf, limit=tf_limit), timeout=20.0)
                if not raw:
                    return None
                df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
                df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
                return df.set_index("time").astype(float)
            except Exception as _e:
                print(f"[ohlcv] {sym} {tf}: {type(_e).__name__}: {_e}", file=sys.stderr)
                return None

    try:
        await exch.load_markets()
        keys = [(sym, tf) for sym in symbols for tf in tfs]
        results = await asyncio.gather(*[_fetch(sym, tf) for sym, tf in keys])
    finally:
        await exch.close()

    out: dict[str, dict[str, pd.DataFrame | None]] = {}
    for (sym, tf), res in zip(keys, results):
        out.setdefault(sym, {})[tf] = res if isinstance(res, pd.DataFrame) else None
    return out


# ─── Watch List: TA snapshot ──────────────────────────────────────────────────

def _wt_zone(wt1: float) -> str:
    if wt1 < -45:
        return "OS"
    if wt1 > 45:
        return "OB"
    return "~"


def _trend_dir(df: pd.DataFrame) -> str:
    """UP/DN/~ из calculate_trend колонок trendup/trenddown."""
    if "trendup" in df.columns and "trenddown" in df.columns:
        last = df.iloc[-1]
        if not pd.isna(last.get("trendup", float("nan"))):
            return "UP"
        if not pd.isna(last.get("trenddown", float("nan"))):
            return "DN"
    return "~"


def _compute_wt_inline(df: pd.DataFrame) -> pd.DataFrame:
    """Минимальный inline WaveTrend (fallback если core не доступен)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan)).fillna(0)
    df = df.copy()
    df["wt1"] = ci.ewm(span=21, adjust=False).mean()
    df["wt2"] = df["wt1"].rolling(4).mean()
    return df


def compute_ta_snapshot(symbol: str, dfs: dict[str, pd.DataFrame | None]) -> dict:
    """TA снимок по 3 TF для символа. Возвращает dict с зонами, трендами, сетапом."""
    snap: dict = {"symbol": symbol, "tfs": {}}

    for tf in WATCHLIST_TFS:
        df = dfs.get(tf)
        if df is None or df.empty or len(df) < 25:
            snap["tfs"][tf] = None
            continue
        try:
            if _CORE_OK:
                df_wt = calculate_wt(df.copy())
                df_tr = calculate_trend(df_wt.copy(), atr_period=43, factor=1.0)
                trend = _trend_dir(df_tr)
            else:
                df_wt = _compute_wt_inline(df)
                trend = "~"

            last = df_wt.iloc[-1]
            wt1 = round(float(last.get("wt1", 0)), 1)
            wt2 = round(float(last.get("wt2", 0)), 1)
            close = float(last["close"])
            ema50 = float(df_wt["close"].ewm(span=50, adjust=False).mean().iloc[-1])

            snap["tfs"][tf] = {
                "wt1": wt1,
                "wt2": wt2,
                "zone": _wt_zone(wt1),
                "trend": trend,
                "close": round(close, 6),
                "above_ema50": close > ema50,
            }
        except Exception:
            snap["tfs"][tf] = None

    # Общий сетап на основе зон и трендов
    valid = {tf: snap["tfs"][tf] for tf in WATCHLIST_TFS if snap["tfs"].get(tf)}
    zones = [d["zone"] for d in valid.values()]
    trends = [d["trend"] for d in valid.values()]

    if zones.count("OS") >= 2 and "DN" not in trends:
        snap["setup"] = "LONG"
    elif zones.count("OB") >= 2 and "UP" not in trends:
        snap["setup"] = "SHORT"
    elif any(z == "OS" for z in zones) and trends.count("UP") >= 2:
        snap["setup"] = "LONG↑"
    elif any(z == "OB" for z in zones) and trends.count("DN") >= 2:
        snap["setup"] = "SHORT↓"
    else:
        snap["setup"] = "—"

    return snap


def fmt_watchlist_block(snapshots: list[dict]) -> str:
    header = f"{'Symbol':<22} {'15m':<12} {'1h':<12} {'4h':<12} {'Setup'}"
    sep = "─" * 72
    lines = [header, sep]
    for snap in snapshots:
        sym = snap["symbol"]

        def _fmt_tf(tf: str) -> str:
            d = snap["tfs"].get(tf)
            if not d:
                return "?"
            return f"{d['zone']} wt{d['wt1']:+.0f} {d['trend']}"

        lines.append(
            f"{sym:<22} {_fmt_tf('15m'):<12} {_fmt_tf('1h'):<12} {_fmt_tf('4h'):<12} {snap['setup']}"
        )
    return "\n".join(lines)


# ─── Composite PNG ─────────────────────────────────────────────────────────────

async def build_composite_png(symbol: str, dfs: dict[str, pd.DataFrame | None]) -> bytes | None:
    """Composite 3-panel PNG (15m/1h/4h) для символа. Склеивает через PIL или возвращает 1h."""
    if not _MPF_OK:
        return None
    try:
        from core.ui.chart_builder import _calculate_wt, _render, _calc_pivot_levels
    except Exception:
        return None

    pngs: list[bytes] = []
    df_1h = dfs.get("1h")

    for tf in WATCHLIST_TFS:
        df = dfs.get(tf)
        if df is None or df.empty or len(df) < 20:
            continue
        try:
            # Нормализуем индекс
            if not isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                df.index = pd.to_datetime(df.index, utc=True)

            df_wt = _calculate_wt(df.copy())
            display_df = df_wt.iloc[-100:].copy()

            # Пивоты из 1h
            if df_1h is not None and not df_1h.empty:
                df_1h_norm = df_1h.copy()
                if not isinstance(df_1h_norm.index, pd.DatetimeIndex):
                    df_1h_norm.index = pd.to_datetime(df_1h_norm.index, utc=True)
                daily_piv, weekly_piv = _calc_pivot_levels(df_1h_norm)
            else:
                daily_piv, weekly_piv = {}, {}

            png = _render(display_df, f"{symbol} {tf}", tf,
                          daily_pivots=daily_piv, weekly_pivots=weekly_piv)
            if png:
                pngs.append(png)
        except Exception as _e:
            print(f"[composite_png] {symbol} {tf}: {_e}", file=sys.stderr)

    if not pngs:
        return None
    if len(pngs) == 1:
        return pngs[0]

    # Склейка через Pillow
    try:
        from PIL import Image
        import io as _io
        images = [Image.open(_io.BytesIO(p)) for p in pngs]
        total_h = sum(img.height for img in images)
        max_w = max(img.width for img in images)
        composite = Image.new("RGB", (max_w, total_h), color=(19, 23, 34))
        y = 0
        for img in images:
            composite.paste(img, (0, y))
            y += img.height
        buf = _io.BytesIO()
        composite.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.read()
    except ImportError:
        # Pillow нет — отдаём 1h (индекс 1 в списке TF)
        idx = min(1, len(pngs) - 1)
        return pngs[idx]


# ─── Telegram ─────────────────────────────────────────────────────────────────

def _tg_token() -> tuple[str, str]:
    return os.environ.get("TELEGRAM_TOKEN", ""), os.environ.get("ADMIN_CHAT_ID", "")


def send_tg_text(text: str, parse_mode: str | None = "Markdown") -> bool:
    token, chat_id = _tg_token()
    if not token or not chat_id:
        return False
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_tg_photo(photo_bytes: bytes, caption: str = "") -> bool:
    token, chat_id = _tg_token()
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "Markdown"},
            files={"photo": ("chart.png", photo_bytes, "image/png")},
            timeout=30,
        )
        return r.status_code == 200
    except Exception:
        return False


# ─── Parse top-3 from Gemini response ─────────────────────────────────────────

def parse_top3(text: str, known_symbols: list[str]) -> list[str]:
    """Извлекает TOP3: строку из ответа Gemini, сверяет с known_symbols."""
    m = re.search(r"TOP3:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return []
    raw = [s.strip() for s in re.split(r",\s*", m.group(1).strip())]
    # Фильтруем только те что есть в watch list
    known_set = set(known_symbols)
    result = [s for s in raw if s in known_set]
    # Если Gemini написал без :USDT суффикса — пробуем матч по префиксу
    if not result:
        for s in raw:
            for k in known_symbols:
                if k.startswith(s) or s.startswith(k.split("/")[0]):
                    result.append(k)
                    break
    return result[:3]


# ─── Output ───────────────────────────────────────────────────────────────────

def write_outputs(text: str, hours: int, stats: dict, used_model: str) -> tuple[Path, Path]:
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    obsidian_file = OUTPUT_OBSIDIAN_DIR / f"{today}-review.md"

    memory_header = (
        f"# Trade Review (last {hours}h)\n\n"
        f"> Автогенерация: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} • "
        f"n={stats.get('n', 0)} • модель: `{used_model}` • "
        f"скрипт: `tools/daily_trade_review.py`\n\n---\n\n"
    )
    OUTPUT_MEMORY.write_text(memory_header + text, encoding="utf-8")

    obsidian_header = (
        "---\n"
        "tags: [daily-review, trade, auto]\n"
        "type: daily-review\n"
        f"date: {today}\n"
        f"hours: {hours}\n"
        f"n_trades: {stats.get('n', 0)}\n"
        f"avgR: {stats.get('avgR', 0)}\n"
        f"WR: {stats.get('WR', 0)}\n"
        'parent: "[[Project-MOC]]"\n'
        f'month: "[[Months/{today[:7]}]]"\n'
        f"model: {used_model}\n"
        "---\n\n"
        f"# Daily Trade Review {today} (last {hours}h)\n\n"
        "> Автогенерация Gemini.\n\n---\n\n"
    )
    obsidian_file.write_text(obsidian_header + text, encoding="utf-8")
    return OUTPUT_MEMORY, obsidian_file


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Daily trade review + Watch List via Gemini")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--max-age-hours", type=float, default=0)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-watchlist", action="store_true",
                        help="Пропустить Watch List (без обращения к BingX)")
    args = parser.parse_args()

    if args.max_age_hours > 0 and OUTPUT_MEMORY.exists():
        age = datetime.now(timezone.utc).timestamp() - OUTPUT_MEMORY.stat().st_mtime
        if age < args.max_age_hours * 3600:
            print(f"[trade_review] SKIP: review свежий ({int(age/60)} мин < {args.max_age_hours}ч)",
                  file=sys.stderr)
            return 0

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not DB_PATH.exists():
        print(f"[trade_review] ERROR: {DB_PATH} не найден", file=sys.stderr)
        return 1

    # ── Phase 0: сделки из БД ────────────────────────────────────────────────
    trades = fetch_trades(args.hours)
    stats = compute_stats(trades)

    if stats.get("n", 0) == 0:
        print(f"[trade_review] SKIP: нет закрытых сделок за {args.hours}ч", file=sys.stderr)
        return 0

    winners = sorted([t for t in trades if (t.get("R_multiple") or 0) >= 1.0],
                     key=lambda t: t.get("R_multiple") or 0, reverse=True)[:5]
    losers = sorted([t for t in trades if (t.get("R_multiple") or 0) <= -1.0],
                    key=lambda t: t.get("R_multiple") or 0)[:5]

    stats_block = fmt_stats_block(stats, args.hours)
    winners_block = "\n".join(fmt_trade(t) for t in winners) or "[нет сделок с R>1.0]"
    losers_block = "\n".join(fmt_trade(t) for t in losers) or "[нет сделок с R<-1.0]"

    # ── Phase 1a: Watch List OHLCV + TA снимок ───────────────────────────────
    watchlist_symbols: list[str] = []
    watchlist_block = "[Watch List пропущен]"
    snapshots: list[dict] = []
    dfs_by_sym: dict[str, dict] = {}

    use_watchlist = not args.no_watchlist and _CCXT_OK and _CORE_OK
    if not use_watchlist and not args.no_watchlist:
        missing = []
        if not _CCXT_OK:
            missing.append("ccxt")
        if not _CORE_OK:
            missing.append("core.indicators")
        print(f"[watch] SKIP: недоступны {missing}", file=sys.stderr)

    if use_watchlist:
        watchlist_symbols = fetch_watchlist_symbols(n=WATCHLIST_N)
        print(f"[watch] Символы ({len(watchlist_symbols)}): {watchlist_symbols}", file=sys.stderr)

        try:
            dfs_by_sym = asyncio.run(
                _fetch_all_ohlcv(watchlist_symbols, WATCHLIST_TFS, WATCHLIST_OHLCV_LIMIT)
            )
            snapshots = [compute_ta_snapshot(s, dfs_by_sym.get(s, {})) for s in watchlist_symbols]
            watchlist_block = fmt_watchlist_block(snapshots)
            print(f"[watch] TA снимок готов: {len(snapshots)} символов", file=sys.stderr)
        except Exception as e:
            print(f"[watch] ERROR fetch/compute: {e}", file=sys.stderr)
            watchlist_block = f"[ошибка загрузки Watch List: {e}]"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ts_utc = datetime.now(timezone.utc).strftime("%H:%M")

    # ── Phase 1b: Gemini text (сделки + watch list) ──────────────────────────
    prompt = REVIEW_PROMPT.format(
        date=today, hours=args.hours,
        n_total=stats["n"],
        n_watch=len(snapshots),
        ts_utc=ts_utc,
        stats_block=stats_block,
        winners_block=winners_block,
        losers_block=losers_block,
        watchlist_block=watchlist_block,
    )
    in_tokens = int(len(prompt) / 3.5)
    print(f"[trade_review] n={stats['n']} avgR={stats['avgR']} WR={stats['WR']}% "
          f"watch={len(snapshots)} → Gemini (~{in_tokens} tokens)", file=sys.stderr)

    try:
        text, used_model = call_gemini(prompt)
    except Exception as e:
        print(f"[trade_review] ERROR Gemini: {e}", file=sys.stderr)
        return 1

    # ── Phase 2: Vision (composite PNG для топ-3) ────────────────────────────
    top3_symbols = parse_top3(text, watchlist_symbols) if watchlist_symbols else []
    vision_results: list[dict] = []  # [{symbol, png, analysis}]

    if top3_symbols and dfs_by_sym and _MPF_OK:
        print(f"[vision] Топ-3 символа: {top3_symbols}", file=sys.stderr)

        async def _build_composites() -> list[bytes | None]:
            return await asyncio.gather(
                *[build_composite_png(sym, dfs_by_sym.get(sym, {})) for sym in top3_symbols],
                return_exceptions=True,
            )

        png_list = asyncio.run(_build_composites())
        for sym, png in zip(top3_symbols, png_list):
            if isinstance(png, bytes) and png:
                print(f"[vision] {sym}: {len(png)//1024}KB → Gemini Vision", file=sys.stderr)
                sym_snapshot = next((s for s in snapshots if s["symbol"] == sym), None)
                analysis = call_gemini_vision(png, sym, ta_snapshot=sym_snapshot)
                vision_results.append({"symbol": sym, "png": png, "analysis": analysis})
            else:
                print(f"[vision] {sym}: PNG не сгенерирован, пропускаем", file=sys.stderr)

    # Дополняем текст vision-анализом
    vision_appendix = ""
    if vision_results:
        vision_appendix = "\n\n---\n\n## 🔭 Vision Analysis (топ-3 сетапа)\n"
        for item in vision_results:
            vision_appendix += f"\n### {item['symbol']}\n{item['analysis']}\n"

    # ── Сохранение файлов ────────────────────────────────────────────────────
    memory_path, obsidian_path = write_outputs(text + vision_appendix, args.hours, stats, used_model)
    out_tokens = int(len(text) / 3.5)

    # ── TG: текст + фото ──────────────────────────────────────────────────────
    if not args.quiet:
        top3_str = ", ".join(top3_symbols) if top3_symbols else "—"
        tg_header = (
            f"📊 *Trade Review {today}* (за {args.hours}ч)\n"
            f"n={stats['n']} avgR={stats['avgR']} WR={stats['WR']}% totalR={stats['totalR']}\n\n"
            f"📡 *Watch List топ-3:* {top3_str}"
        )
        ok = send_tg_text(tg_header)
        if ok:
            print("[tg] Текстовый дайджест отправлен", file=sys.stderr)

        for item in vision_results:
            # Фото с коротким caption (TG limit 1024), анализ отдельным сообщением
            ok = send_tg_photo(item["png"], f"📡 *{item['symbol']}* — 15m / 1h / 4h")
            if ok:
                print(f"[tg] {item['symbol']} PNG отправлен", file=sys.stderr)
            send_tg_text(f"📡 {item['symbol']}\n\n{item['analysis']}", parse_mode=None)

    if args.quiet:
        print(f"[trade_review] OK n={stats['n']} vision={len(vision_results)} "
              f"~in={in_tokens} ~out={out_tokens}", file=sys.stderr)
    else:
        print(f"[trade_review] OK model={used_model}")
        print(f"  n={stats['n']} avgR={stats['avgR']} WR={stats['WR']}% totalR={stats['totalR']}")
        print(f"  watch={len(snapshots)} top3={top3_symbols} vision={len(vision_results)}")
        print(f"  in: ~{in_tokens} tokens  out: ~{out_tokens} tokens")
        print(f"  -> {memory_path}")
        print(f"  -> {obsidian_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
