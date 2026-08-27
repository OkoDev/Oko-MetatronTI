# -*- coding: utf-8 -*-
"""РЕГРЕССИЯ ФАЗЫ 3: общий раннер обязан вести себя как два прежних лупа БИТ В БИТ.

Схлопывание клонов безопасно ровно настолько, насколько доказана эквивалентность.
Проверяем три вещи:

  A. КОНСТАНТЫ ИНСТАНСОВ — окна, ТФ, таблица, источник, путь к дрейф-гейту.
     Именно здесь 22.08 нашёлся дефект (окна в барах под 1h), поэтому сверка жёсткая.
  B. РЕЗОЛВЕР — старый `_resolve` из бэкапа против нового на ОДНИХ И ТЕХ ЖЕ данных
     и одинаковых входных записях: статусы, время резолва и result_pct должны совпасть.
  C. ТОЧКИ ВХОДА — имена, которые импортируют `bot/core/bot.py` и verify-скрипт, на месте.

Запуск: python scripts/verify_impulse_runner.py [N_SYM]
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from bot.loops import impulse_fib_15m_loop as new15  # noqa: E402
from bot.loops import impulse_fib_loop as new1h      # noqa: E402

N_SYM = int(sys.argv[1]) if len(sys.argv) > 1 else 6
CACHE = str(ROOT / "ohlcv_cache.db")


def _load_backup(path: Path, name: str):
    """Импортирует прежний луп из .bak, не трогая пакет.

    Расширение не .py, поэтому загрузчик задаётся явно — иначе spec приходит None.
    """
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


old1h = _load_backup(ROOT / "bot/loops/impulse_fib_loop.py.bak.phase3", "_old_1h")
old15 = _load_backup(ROOT / "bot/loops/impulse_fib_15m_loop.py.bak.phase3", "_old_15m")

fails = 0

# ── A. КОНСТАНТЫ ───────────────────────────────────────────────────────────────
print("=" * 96)
print("A. КОНСТАНТЫ ИНСТАНСОВ (окна — тот самый дефект, что чинили 22.08)")
print("=" * 96)
EXPECT = [
    ("1h ", new1h.INSTANCE, "impulse_fib", "1h", 12, 96, "impulse_shadow",
     getattr(old1h, "WAIT_BARS", None), getattr(old1h, "HOLD_BARS", None)),
    ("15m", new15.INSTANCE, "impulse_fib_15m", "15m", 48, 384, "impulse_shadow_15m",
     getattr(old15, "WAIT_BARS_TF", None), getattr(old15, "HOLD_BARS_TF", None)),
]
for tag, inst, src, tf, wb, hb, table, old_wb, old_hb in EXPECT:
    ok = (inst.src == src and inst.tf == tf and inst.wait_bars == wb
          and inst.hold_bars == hb and inst.table == table)
    same_as_old = (old_wb == wb and old_hb == hb)
    mark = "✅" if (ok and same_as_old) else "🔴"
    if not (ok and same_as_old):
        fails += 1
    print(f"  {mark} {tag}: src={inst.src} tf={inst.tf} окна {inst.wait_bars}/{inst.hold_bars} "
          f"таблица={inst.table} · в прежнем лупе было {old_wb}/{old_hb} · "
          f"gate={inst.cfg_key}.drift_gate")

# ── B. РЕЗОЛВЕР: старый против нового на одних данных ──────────────────────────
print("\n" + "=" * 96)
print("B. РЕЗОЛВЕР: прежний код против общего раннера (одни данные, одни записи)")
print("=" * 96)


def _universe(tf: str, n: int) -> list[str]:
    with sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True) as c:
        rows = c.execute("SELECT symbol,COUNT(*) k FROM ohlcv_cache WHERE timeframe=? "
                         "GROUP BY symbol ORDER BY k DESC LIMIT ?", (tf, n)).fetchall()
    return [s for s, _ in rows]


def _load(sym: str, tf: str, limit: int = 3000) -> pd.DataFrame:
    with sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True) as c:
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",
                        c, params=(sym, tf, limit))
    d = d.iloc[::-1]
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def _seed(conn, table: str, sym: str, df: pd.DataFrame, every: int = 40) -> None:
    """Кладёт синтетические записи-сетапы, которые резолверу предстоит догнать."""
    conn.execute(f"DELETE FROM {table} WHERE symbol=?", (sym,))
    d = df.iloc[:-1]
    for k in range(200, len(d) - 5, every):
        px = float(d.close.values[k])
        side = "long" if k % 2 == 0 else "short"
        entry = px * (0.995 if side == "long" else 1.005)
        sl = entry * (0.97 if side == "long" else 1.03)
        tp = entry * (1.08 if side == "long" else 0.92)
        conn.execute(
            f"INSERT OR IGNORE INTO {table} (symbol,impulse_ts,origin_ts,side,entry,"
            "stop_loss,take_profit,stop_pct) VALUES (?,?,?,?,?,?,?,?)",
            (sym, str(d.index[k]), str(d.index[k]) + f"#{k}", side, entry, sl, tp, 3.0))
    conn.commit()


def compare(tag: str, tf: str, table: str, old_resolve, new_resolve) -> int:
    """Прогоняет оба резолвера на одинаковом старте и сверяет результат по записям."""
    bad = 0
    for sym in _universe(tf, N_SYM):
        df = _load(sym, tf)
        if len(df) < 800:
            continue
        res = {}
        for name, fn in (("old", old_resolve), ("new", new_resolve)):
            conn = sqlite3.connect(":memory:")
            conn.execute(new1h._TABLE if table == "impulse_shadow" else new15._TABLE)
            _seed(conn, table, sym, df)
            fn(conn, sym, df)
            res[name] = conn.execute(
                f"SELECT origin_ts,status,COALESCE(resolved_at,''),"
                f"COALESCE(ROUND(result_pct,8),-999),COALESCE(bars_to_fill,-1) "
                f"FROM {table} WHERE symbol=? ORDER BY origin_ts", (sym,)).fetchall()
            conn.close()
        if res["old"] != res["new"]:
            bad += 1
            diff = [(a, b) for a, b in zip(res["old"], res["new"]) if a != b][:2]
            print(f"  🔴 {sym}: РАСХОЖДЕНИЕ, примеры: {diff}")
        else:
            st = {}
            for r in res["new"]:
                st[r[1]] = st.get(r[1], 0) + 1
            print(f"  ✅ {sym}: {len(res['new'])} записей совпали 1:1 · {st}")
    return bad


print(f"\n▸ 1h (таблица impulse_shadow)")
fails += compare("1h", "1h", "impulse_shadow", old1h._resolve, new1h._resolve)
print(f"\n▸ 15m (таблица impulse_shadow_15m)")
fails += compare("15m", "15m", "impulse_shadow_15m", old15._resolve, new15._resolve)

# ── C. ТОЧКИ ВХОДА ─────────────────────────────────────────────────────────────
print("\n" + "=" * 96)
print("C. ТОЧКИ ВХОДА (их импортируют bot.py и verify_impulse_fib_loop.py)")
print("=" * 96)
for mod, names in ((new1h, ("impulse_fib_loop", "_TABLE", "_resolve", "INSTANCE")),
                   (new15, ("impulse_fib_15m_loop", "_TABLE", "_resolve", "INSTANCE"))):
    for nm in names:
        ok = hasattr(mod, nm)
        if not ok:
            fails += 1
        print(f"  {'✅' if ok else '🔴'} {mod.__name__}.{nm}")

print("\n" + "=" * 96)
print(f"{'✅ ЭКВИВАЛЕНТНОСТЬ ДОКАЗАНА' if fails == 0 else f'🔴 РАСХОЖДЕНИЙ: {fails}'}")
print("=" * 96)
sys.exit(1 if fails else 0)
