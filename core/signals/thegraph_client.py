"""The Graph on-chain клиент (Сфера 6.5, P1+P2 shadow — 03.07.2026).

Урок 03.07: WR-оценкам роя не верим — с ПЕРВОГО дня только SHADOW-ЛОГГЕР событий (копим СВОЮ
историю для честной валидации через 4-6 недель; исторических on-chain данных для walk-forward нет).

Ключ: env THEGRAPH_API_KEY или config the_graph.api_key. Free tier 100k q/мес (Subgraph Studio).
Gateway: https://gateway.thegraph.com/api/{key}/subgraphs/id/{subgraph_id}

Первые два сигнала (Uniswap V3 mainnet):
  whale_swap — свопы > $250k (направление к/от стейблов = risk-off/on поток)
  liq_event  — mint/burn ликвидности > $500k (маркет-мейкеры готовят движение)
События → таблица onchain_events (ohlcv_cache.db). Поллер: scripts/thegraph_shadow_poller.py
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("ohlcv_cache.db")
UNISWAP_V3_ID = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"   # Uniswap V3 mainnet
SWAP_MIN_USD = 250_000
LIQ_MIN_USD = 500_000
STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD"}


def _api_key() -> str | None:
    key = os.environ.get("THEGRAPH_API_KEY")
    if key:
        return key.strip()
    try:
        import yaml
        cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
        return ((cfg.get("the_graph") or {}).get("api_key") or "").strip() or None
    except Exception:
        return None


def _gql(subgraph_id: str, query: str) -> dict | None:
    key = _api_key()
    if not key:
        logger.debug("[GRAPH] нет THEGRAPH_API_KEY")
        return None
    url = f"https://gateway.thegraph.com/api/{key}/subgraphs/id/{subgraph_id}"
    try:
        req = urllib.request.Request(url, json.dumps({"query": query}).encode(),
                                     {"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=25))
        if "errors" in r:
            logger.debug("[GRAPH] errors: %s", str(r["errors"])[:200])
            return None
        return r.get("data")
    except Exception as e:  # noqa: BLE001
        logger.debug("[GRAPH] query error: %s", e)
        return None


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS onchain_events (
        ts INTEGER NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
        symbol TEXT, amount_usd REAL, direction TEXT, raw TEXT,
        PRIMARY KEY (ts, kind, symbol, amount_usd))""")
    conn.commit()


def poll_uniswap_events(since_ts: int | None = None) -> dict:
    """Одна итерация: крупные свопы + ликвидность за окно. Пишет в onchain_events.
    Возвращает {'swaps': n, 'liq': n} или {'error': ...}."""
    since = since_ts or int(time.time()) - 900
    data_sw = _gql(UNISWAP_V3_ID, f"""{{
      swaps(first: 100, orderBy: timestamp, orderDirection: desc,
            where: {{amountUSD_gt: "{SWAP_MIN_USD}", timestamp_gt: {since}}}) {{
        timestamp amountUSD amount0 amount1
        token0 {{ symbol }} token1 {{ symbol }}
      }} }}""")
    data_liq = _gql(UNISWAP_V3_ID, f"""{{
      mints(first: 50, orderBy: timestamp, orderDirection: desc,
            where: {{amountUSD_gt: "{LIQ_MIN_USD}", timestamp_gt: {since}}}) {{
        timestamp amountUSD token0 {{ symbol }} token1 {{ symbol }}
      }}
      burns(first: 50, orderBy: timestamp, orderDirection: desc,
            where: {{amountUSD_gt: "{LIQ_MIN_USD}", timestamp_gt: {since}}}) {{
        timestamp amountUSD token0 {{ symbol }} token1 {{ symbol }}
      }} }}""")
    if data_sw is None and data_liq is None:
        return {"error": "no api key or query failed"}
    conn = sqlite3.connect(_DB)
    _ensure_schema(conn)
    n_sw = n_liq = 0
    try:
        for s in (data_sw or {}).get("swaps", []):
            t0, t1 = s["token0"]["symbol"], s["token1"]["symbol"]
            pair = f"{t0}/{t1}"
            # направление risk-потока: продажа токена ЗА стейбл (amount стейбла < 0 у пула = выход
            # стейбла к трейдеру = трейдер ПРОДАЛ токен) → risk_off; покупка токена → risk_on
            direction = None
            try:
                if t1 in STABLES:
                    direction = "risk_off" if float(s["amount1"]) < 0 else "risk_on"
                elif t0 in STABLES:
                    direction = "risk_off" if float(s["amount0"]) < 0 else "risk_on"
            except Exception:
                pass
            conn.execute("INSERT OR IGNORE INTO onchain_events VALUES (?,?,?,?,?,?,?)",
                         (int(s["timestamp"]), "whale_swap", "uniswap_v3", pair,
                          float(s["amountUSD"]), direction, json.dumps(s)[:500]))
            n_sw += 1
        for kind, arr in (("liq_mint", (data_liq or {}).get("mints", [])),
                          ("liq_burn", (data_liq or {}).get("burns", []))):
            for s in arr:
                pair = f"{s['token0']['symbol']}/{s['token1']['symbol']}"
                conn.execute("INSERT OR IGNORE INTO onchain_events VALUES (?,?,?,?,?,?,?)",
                             (int(s["timestamp"]), kind, "uniswap_v3", pair,
                              float(s["amountUSD"]), None, json.dumps(s)[:500]))
                n_liq += 1
        conn.commit()
    finally:
        conn.close()
    return {"swaps": n_sw, "liq": n_liq}
