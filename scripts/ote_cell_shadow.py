# -*- coding: utf-8 -*-
"""SHADOW КЛЕТКИ OTE: собранный импульс × фаза × СТОРОНА (11.08.2026, решение Егора).

Зачем. Дуга OTE дважды закрывалась мной по УСРЕДНЁННОМУ числу и дважды Егор это ловил.
Разрез по фазе и стороне вскрыл первую клетку, прошедшую тест хрупкости
([[ote_short_impulsive_first_robust_cell]]): импульсный режим + SHORT + собранный импульс
(n_bos≥1) → n=271, WR 70%, медиана +3.536%, PF 2.10, безтоп10% **+266%**, 87/125 монет.
Лонг на истории мёртв (PF 0.70) — НО мерилось на трёх годах падающих альтов. Егор:
«шорт и лонг в клетку» — пишем ОБЕ стороны, чтобы при смене режима у нас были данные,
а не сожаления.

Почему shadow, а не VST: 2026 минусовой (−0.62), клетка найдена ТРОЙНЫМ условием
(фаза × сторона × сборка) на выборке n=271 — риск отбора реален. Форвард рассудит.

Геометрия 1:1 с бэктестом (иначе меряли бы не то, что торгуем):
  импульс с 4h по CHoCH+BOS (`core.smc.impulse_assembly`) · вход при заходе ЗАКРЫТОГО
  1h-бара в OTE 0.618-0.786 · SL за origin импульса · цели: TP1R и экстремум импульса.
ПРИЧИННО: последний (формирующийся) бар отбрасывается на обоих ТФ.

Пишем ВСЕ фазы с меткой — режем потом. Гейт только структурный (n_bos≥1), он измерен
полезным для обеих сторон. Исходы закрывает `scripts/shadow_resolve.py`.

pm2: --name ote-cell · тест одной монеты: python scripts/ote_cell_shadow.py --test SOL
"""
import json
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import pandas as pd

from oko_feed.store import conn
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.context.market_regime import ac_regime, ac_label
from oi_fast_poller import CORE  # noqa: E402  — та же ликвидная вселенная, что у радара

SCAN_SEC = 900
HTF, LTF = "4h", "1h"
HTF_LIMIT, LTF_LIMIT = 400, 5
MIN_BOS = 1                  # структурный гейт: свинг годен под OTE только ПОСЛЕ BOS
COOLDOWN_SEC = 12 * 3600     # одна запись на (монета, сторона) раз в 12ч
MIN_STOP_PCT, MAX_STOP_PCT = 0.5, 25.0


def _klines(sym: str, interval: str, limit: int):
    """Binance fapi (та же биржа, что в кэше бэктеста). Последний бар — формирующийся."""
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
           f"&interval={interval}&limit={limit}")
    try:
        arr = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "oko-shadow"}), timeout=10))
    except Exception:
        return None
    if not arr or len(arr) < 3:
        return None
    df = pd.DataFrame(arr, columns=["ot", "open", "high", "low", "close", "volume",
                                    "ct", "qv", "n", "tb", "tq", "ig"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["ot", "open", "high", "low", "close", "volume"]].iloc[:-1].reset_index(drop=True)


def _cooldown_ok(key: str, sec: int) -> bool:
    c = conn()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
        row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < sec:
            return False
        c.execute("INSERT OR REPLACE INTO alert_log VALUES (?,?)", (key, int(time.time())))
        c.commit()
        return True
    finally:
        c.close()


def _log(row: dict) -> None:
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS ote_cell_shadow (
            ts INTEGER, symbol TEXT, direction TEXT, entry REAL, sl REAL,
            tp1r REAL, tp_ext REAL, origin REAL, extreme REAL, n_bos INTEGER,
            stop_pct REAL, ac_value REAL, ac_label TEXT, core_cell INTEGER,
            cluster_size INTEGER, retr REAL,
            resolved INTEGER DEFAULT 0, outcome TEXT, exit_price REAL,
            pct_1r REAL, pct_ext REAL, resolved_ts INTEGER)""")
        _cols = [x[1] for x in c.execute("PRAGMA table_info(ote_cell_shadow)")]
        for _c, _t in (("cluster_size", "INTEGER"), ("retr", "REAL")):
            if _c not in _cols:
                c.execute(f"ALTER TABLE ote_cell_shadow ADD COLUMN {_c} {_t}")
        c.execute("""INSERT INTO ote_cell_shadow
            (ts,symbol,direction,entry,sl,tp1r,tp_ext,origin,extreme,n_bos,stop_pct,
             ac_value,ac_label,core_cell,cluster_size,retr)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (int(time.time()), row["symbol"], row["direction"], row["entry"], row["sl"],
                   row["tp1r"], row["tp_ext"], row["origin"], row["extreme"], row["n_bos"],
                   row["stop_pct"], row["ac_value"], row["ac_label"], row["core_cell"],
                   row.get("cluster_size"), row.get("retr")))
        c.commit()
    finally:
        c.close()


def scan_one(sym: str, ac_v, ac_l, test: bool = False):
    d4 = _klines(sym, HTF, HTF_LIMIT)
    if d4 is None or len(d4) < 120:
        return None
    try:
        st = run_structure(d4, swing_len=50, internal_len=5)
    except Exception:
        return None
    imp = assemble_impulse(st, d4["high"], d4["low"], internal=True)
    if not imp:
        return "нет собранного импульса" if test else None
    if imp["n_bos"] < MIN_BOS:
        return f"n_bos={imp['n_bos']} < {MIN_BOS} (свинг без BOS)" if test else None
    is_long = imp["is_long"]
    # 11.08 РАЗВЁРТКА ЗОН: каноническая 0.618-0.786 оказалась ХУДШЕЙ из проверенных
    # (PF 1.22 против 1.76 у 0.55-0.85 и даже 1.60 у «зоны фактически нет» 0.45-0.95).
    # Работает не УРОВЕНЬ, а сам факт глубокого отката. Пишем по ШИРОКОЙ зоне и сохраняем
    # фактический уровень отката — любую узкую зону нарежем постфактум, не потеряв данные.
    z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], is_long, 0.45, 0.95)
    d1 = _klines(sym, LTF, LTF_LIMIT)
    if d1 is None or d1.empty:
        return None
    px = float(d1["close"].iloc[-1])           # ЗАКРЫТЫЙ 1h-бар
    if not (z_lo <= px <= z_hi):
        return (f"вне зоны: цена {px:.6g}, OTE {z_lo:.6g}-{z_hi:.6g} "
                f"({'LONG' if is_long else 'SHORT'}, n_bos={imp['n_bos']})") if test else None
    sl = imp["origin"] * (0.997 if is_long else 1.003)
    if (is_long and sl >= px) or ((not is_long) and sl <= px):
        return None
    stop_pct = abs(px - sl) / px * 100
    if not (MIN_STOP_PCT < stop_pct < MAX_STOP_PCT):
        return f"стоп {stop_pct:.1f}% вне {MIN_STOP_PCT}-{MAX_STOP_PCT}%" if test else None
    side = 1 if is_long else -1
    direction = "LONG" if is_long else "SHORT"
    rng = abs(imp["extreme"] - imp["origin"])
    retr = ((imp["extreme"] - px) / rng) if is_long else ((px - imp["extreme"]) / rng)
    # ЯДРО измеренной клетки: импульсный режим + SHORT. Остальное пишем для сравнения.
    core = 1 if (ac_l == "импульсный" and not is_long) else 0
    row = {"symbol": sym, "direction": direction, "entry": px, "sl": sl,
           "tp1r": px + side * abs(px - sl), "tp_ext": imp["extreme"],
           "origin": imp["origin"], "extreme": imp["extreme"], "n_bos": imp["n_bos"],
           "stop_pct": round(stop_pct, 3), "ac_value": ac_v, "ac_label": ac_l,
           "core_cell": core, "retr": round(float(retr), 4)}
    return json.dumps(row, ensure_ascii=False, indent=1) if test else row


def main():
    if "--test" in sys.argv:
        sym = sys.argv[sys.argv.index("--test") + 1].upper()
        v = ac_regime()
        print(f"фаза: AC={v} → {ac_label(v)}")
        print(scan_one(sym, v, ac_label(v), test=True) or "нет данных")
        return
    print(f"[OTE-CELL] shadow клетки: {len(CORE)} монет, скан {SCAN_SEC}с · "
          f"импульс CHoCH+BOS с 4h, вход в OTE на закрытом 1h, ОБЕ стороны, БЕЗ капитала")
    while True:
        try:
            v = ac_regime()
            lab = ac_label(v)
            # ПРОХОД 1: собираем кандидатов цикла (кластер = сколько монет в зоне ОДНОВРЕМЕННО)
            cands = []
            for sym in CORE:
                r = scan_one(sym, v, lab)
                if r:
                    cands.append(r)
                time.sleep(0.15)
            # ПРОХОД 2: кластер-гейт — решающий фильтр (одиночка PF 1.02 безтоп10% −225%,
            # кластер ≥2 PF 1.83 +230%). Считаем ПО СТОРОНЕ: шорты и лонги — разные движения.
            by_side = {}
            for c_ in cands:
                by_side.setdefault(c_["direction"], []).append(c_)
            hits = []
            for direction, group in by_side.items():
                for c_ in group:
                    c_["cluster_size"] = len(group)
                    if not _cooldown_ok(f"otecell:{c_['symbol']}:{direction}", COOLDOWN_SEC):
                        continue
                    _log(c_)
                    hits.append(f"{c_['symbol']} {direction} n_bos={c_['n_bos']} "
                                f"стоп{c_['stop_pct']:.1f}% кластер={len(group)}"
                                f"{' ЯДРО' if c_['core_cell'] else ''}")
            print(f"[OTE-CELL] {time.strftime('%H:%M:%S')} фаза={lab} кандидатов={len(cands)} "
                  f"записей={len(hits)}" + (f": {hits}" if hits else ""))
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[OTE-CELL] err: {e}")
        time.sleep(SCAN_SEC)


if __name__ == "__main__":
    main()
