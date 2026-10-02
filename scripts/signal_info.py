"""
signal_info.py — СТЕНД СЛОЯ СИГНАЛА (L1). Единая точка входа для вопроса
«несёт ли сигнал информацию о движении цены» — для ЛЮБОГО источника.

Зачем. 02.10 я выдал вердикт «радар выключить» по замеру ГЕОМЕТРИИ СДЕЛКИ, не проверив сам сигнал.
Возражение Егора («радар использует динамические данные OI/объём, а не строгую геометрию») оказалось
верным: сигнал `pump` живой (медиана форварда +1.5%/24ч против контроля, 3/3 месяца), а убыток давали
геометрия и микс потока. Причина ошибки — инструмента для L1 не существовало, был только ad hoc скрипт.
Закон и порядок слоёв: скилл `research-verdict` §0, память `law_measure_judges_layer_not_mechanic`.

Что считает. Геометрии нет вообще: от момента сигнала — чистое форвардное движение цены В СТОРОНУ
сигнала на горизонтах 15м/1ч/4ч/24ч, против ДВУХ контролей (случайный момент и момент той же
волатильности ±25%, та же монета и сторона). Метрики — медиана и доля>0 с бутстрап-интервалом:
средние забиты хвостами мемкоинов (±30%).

Печатает ВСЕГДА, не по опции (§0.1, §0.5, §2A, §2B протокола):
  инвентаризация и покрытие цен · состав потока по подтипам · форвард против обоих контролей
  с интервалами · оси (подтип × сторона, месяц) · охват монет.

    python scripts/signal_info.py --source radar:pump
    python scripts/signal_info.py --source drops:radar          # отказы гейтов (с 03.10 несут цену)
    python scripts/signal_info.py --source shadow:impulse_shadow_15m
    python scripts/signal_info.py --source trades:choch_wavec
    python scripts/signal_info.py --source hub:signal_detected  # журнал фактов хаба Куба
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.infra import market_store as ms          # noqa: E402

TF, STEP_MIN = "15m", 15
HORIZONS = {"15м": 1, "1ч": 4, "4ч": 16, "24ч": 96}
PRE_BARS, TOL, CTRL_N, CTRL_DAYS = 12, 0.25, 3, 30
HUB_URL = "http://127.0.0.1:8020"
_bars_cache: dict = {}


# ── источники сигналов: каждый отдаёт (ts, symbol, side, cells{ось: значение}) ──

def src_radar(arg: str) -> list[tuple]:
    """radar[:тип] — журнал радара `oko_feed/external_data.db::radar_orders` (~46 тыс.)."""
    q = "SELECT ts, symbol, side, sig_type, grade, wave_leg, status FROM radar_orders"
    args: list = []
    if arg:
        q += " WHERE sig_type=?"; args.append(arg)
    db = sqlite3.connect(f"file:{ROOT / 'oko_feed' / 'external_data.db'}?mode=ro", uri=True, timeout=20)
    out = []
    for ts, sym, side, stype, grade, wl, status in db.execute(q + " ORDER BY ts", args):
        out.append((pd.Timestamp(int(ts), unit="s"), sym, (side or "").upper(),
                    {"подтип": stype, "grade": str(grade), "статус": status,
                     "wave_leg": "нет" if wl is None else ("leg≥3" if wl >= 3 else f"leg={wl}")}))
    return out


def src_drops(arg: str) -> list[tuple]:
    """drops[:источник] — отказы гейтов `signal_drops`. 🔴 Цена и ATR% пишутся только с 03.10."""
    q = ("SELECT dropped_at, symbol, direction, signal_type, gate_name, source FROM signal_drops "
         "WHERE price IS NOT NULL")
    args: list = []
    if arg:
        q += " AND (source=? OR signal_type=?)"; args += [arg, arg]
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    return [(pd.Timestamp(str(ts).replace("T", " ")[:19]), sym, (side or "").upper(),
             {"подтип": stype, "гейт": gate, "источник": src})
            for ts, sym, side, stype, gate, src in db.execute(q + " ORDER BY dropped_at", args)]


def src_shadow(arg: str) -> list[tuple]:
    """shadow:<таблица> — теневой журнал (impulse_shadow, impulse_shadow_15m, choch_shadow…)."""
    tbl = arg or "impulse_shadow"
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    cols = [r[1] for r in db.execute(f"pragma table_info({tbl})")]
    side_col = "side" if "side" in cols else None
    side_expr = side_col if side_col else "'SHORT'"
    sel = f"SELECT created_at, symbol, {side_expr}, status FROM {tbl} ORDER BY created_at"
    return [(pd.Timestamp(str(ts).replace("T", " ")[:19]), sym, (side or "").upper(), {"статус": st})
            for ts, sym, side, st in db.execute(sel)]


def src_trades(arg: str) -> list[tuple]:
    """trades[:источник] — зарегистрированные сделки `simulated_trades` (момент сигнала = created_at)."""
    q = ("SELECT created_at, symbol, direction, signal_type, source_router, execution_mode "
         "FROM simulated_trades WHERE entry_price > 0")
    args: list = []
    if arg:
        q += " AND (source_router=? OR signal_type=?)"; args += [arg, arg]
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    return [(pd.Timestamp(str(ts).replace("T", " ")[:19]), sym, (side or "").upper(),
             {"подтип": stype, "источник": src, "режим": mode})
            for ts, sym, side, stype, src, mode in db.execute(q + " ORDER BY created_at", args)]


def src_hub(arg: str) -> list[tuple]:
    """hub[:тип события] — журнал фактов хаба Куба (`GET /facts`), 30 дней."""
    ev = arg or "signal_detected"
    with urllib.request.urlopen(f"{HUB_URL}/facts?types={ev}&limit=5000", timeout=20) as r:
        facts = json.loads(r.read()).get("facts", [])
    out = []
    for f in facts:
        d = f.get("data") or {}
        out.append((pd.Timestamp(f["ts"], unit="s"), f["symbol"],
                    (d.get("direction") or "").upper(), {"подтип": d.get("signal_type")}))
    return out


SOURCES = {"radar": src_radar, "drops": src_drops, "shadow": src_shadow,
           "trades": src_trades, "hub": src_hub}


# ── ядро ──

def bars(base: str):
    if base not in _bars_cache:
        d = ms.read_bars(base, TF)
        if len(d):
            d = d.copy(); d.index = d.index.tz_localize(None)
        _bars_cache[base] = d if len(d) else None
    return _bars_cache[base]


def at(d, t):
    """(индекс бара <= t, ATR% до него). Волатильность нужна для сопоставимого контроля (§2A)."""
    if d is None:
        return None, None
    pos = d.index.searchsorted(t, side="right") - 1
    if pos < PRE_BARS or pos >= len(d) - 1:
        return None, None
    pre = d.iloc[pos - PRE_BARS + 1:pos + 1]
    px = float(d.close.values[pos])
    return pos, (float((pre.high - pre.low).mean() / px * 100) if px else None)


def forward(d, pos, long_: bool) -> dict:
    px = float(d.close.values[pos])
    out = {}
    for name, n in HORIZONS.items():
        j = pos + n
        ret = ((float(d.close.values[j]) - px) / px * 100) if j < len(d) else None
        out[name] = (ret if long_ else -ret) if ret is not None else None
    return out


def summary(xs: list[float]) -> str:
    if not xs:
        return "—"
    s = sorted(xs)
    return (f"n={len(xs):6d} мед={s[len(s) // 2]:+6.3f}% доля>0={sum(x > 0 for x in xs) / len(xs) * 100:4.1f}% "
            f"ср={sum(xs) / len(xs):+6.3f}%")


def boot(a: list[float], b: list[float], rnd, stat="median", n=1500):
    """Разница устойчивой статистики с 95% интервалом (§2B: средние при хвостах не годятся)."""
    def f(xs):
        if stat == "median":
            s = sorted(xs); return s[len(s) // 2]
        return sum(x > 0 for x in xs) / len(xs) * 100
    if not a or not b:
        return 0.0, 0.0, 0.0
    ka, kb = min(len(a), 1500), min(len(b), 1500)
    d = sorted(f([rnd.choice(a) for _ in range(ka)]) - f([rnd.choice(b) for _ in range(kb)])
               for _ in range(n))
    return f(a) - f(b), d[int(0.025 * n)], d[int(0.975 * n)]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="radar[:тип] · drops[:ист] · shadow:<табл> · trades[:ист] · hub[:событие]")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    kind, _, arg = a.source.partition(":")
    if kind not in SOURCES:
        print(f"неизвестный источник {kind!r}; доступны: {', '.join(SOURCES)}"); return
    rnd = random.Random(23)
    raw = SOURCES[kind](arg)
    if a.limit:
        raw = raw[-a.limit:]

    print(f"■ СТЕНД СЛОЯ СИГНАЛА (L1) · источник {a.source} · сигналов {len(raw)}")
    if not raw:
        print("  пусто — нечего мерить"); return
    print(f"  окно: {min(r[0] for r in raw).date()} → {max(r[0] for r in raw).date()} · "
          f"монет {len({r[1] for r in raw})} · цены {TF} BingX (хранилище Сферы 1)")
    print("  🔑 объект замера = L1 (сигнал). Геометрия, управление, исполнение и портфель НЕ представлены:")
    print("     вывод этого стенда НЕ является вердиктом о механике (скилл research-verdict §0).")

    sig, ctl, ctl_v = defaultdict(list), defaultdict(list), defaultdict(list)
    kept = skipped = 0
    flow = Counter()
    for t, symbol, side, cells in raw:
        d = bars(symbol)
        pos, atr = at(d, t)
        if pos is None or not atr:
            skipped += 1
            continue
        kept += 1
        long_ = side == "LONG"
        f = forward(d, pos, long_)
        flow[(cells.get("подтип"), side)] += 1
        axes = [("всё", "все сигналы"), ("месяц", t.strftime("%Y-%m"))]
        for k, v in cells.items():
            if v is not None:
                axes.append((k, f"{v} {side}" if k == "подтип" else str(v)))
        for h, val in f.items():
            if val is None:
                continue
            for ax, cell in axes:
                sig[(ax, cell, h)].append(val)
        # два контроля (§2A): случайный момент и момент той же волатильности
        for store, match in ((ctl, False), (ctl_v, True)):
            got = 0
            for _ in range(40):
                if got >= CTRL_N:
                    break
                tr = t + pd.Timedelta(days=rnd.uniform(-CTRL_DAYS, CTRL_DAYS))
                p2, a2 = at(d, tr)
                if p2 is None or not a2:
                    continue
                if match and not (atr * (1 - TOL) <= a2 <= atr * (1 + TOL)):
                    continue
                got += 1
                for h, val in forward(d, p2, long_).items():
                    if val is not None:
                        store[("всё", "все сигналы", h)].append(val)
                        for ax, cell in axes[1:]:
                            store[(ax, cell, h)].append(val)
    cov = kept / (kept + skipped) * 100 if (kept + skipped) else 0
    print(f"  покрытие ценами: {kept} из {kept + skipped} ({cov:.0f}%)"
          f"{'  ⚠️ ниже 80% — стенд мерит подвыборку' if cov < 80 else ''}")
    print("\n  состав потока (§0.5 — агрегат по механике мерит МИКС, а не механику):")
    tot = sum(flow.values())
    for (st, sd), n in flow.most_common(10):
        print(f"    {str(st):18} {sd:5} {n:6d} ({n / tot * 100:4.1f}%)")

    print("\n=== ФОРВАРД СИГНАЛА против двух контролей (медиана, §2B) ===")
    for h in HORIZONS:
        s_ = sig[("всё", "все сигналы", h)]
        print(f"  {h:>4}: сигнал   {summary(s_)}")
        for nm, store in (("случайный момент", ctl), ("та же волатильность", ctl_v)):
            c_ = store[("всё", "все сигналы", h)]
            dm, lo, hi = boot(s_, c_, rnd)
            dp, plo, phi = boot(s_, c_, rnd, "share")
            mark = "  ←ЗНАЧИМО" if (lo > 0 and plo > 0) or (hi < 0 and phi < 0) else ""
            print(f"        контроль [{nm:19}] {summary(c_)}")
            print(f"        Δ медиана {dm:+6.3f} [{lo:+6.3f}; {hi:+6.3f}] · "
                  f"доля>0 {dp:+5.1f}% [{plo:+5.1f}; {phi:+5.1f}]{mark}")

    for ax in sorted({a_ for (a_, c, h) in sig} - {"всё"}):
        print(f"\n— {ax} (горизонты 4ч / 24ч, против контроля той же волатильности):")
        cells = sorted({c for (a_, c, h) in sig if a_ == ax}, key=lambda c: -len(sig[(ax, c, "4ч")]))
        for c in cells[:12]:
            s4 = sig[(ax, c, "4ч")]
            if len(s4) < 100:
                continue
            parts = []
            for h in ("4ч", "24ч"):
                s_ = sig[(ax, c, h)]
                c_ = ctl_v[(ax, c, h)] or ctl_v[("всё", "все сигналы", h)]
                dm, lo, hi = boot(s_, c_, rnd)
                dp, plo, phi = boot(s_, c_, rnd, "share")
                mark = "←" if (lo > 0 and plo > 0) or (hi < 0 and phi < 0) else " "
                parts.append(f"{h} Δмед={dm:+6.3f} [{lo:+6.3f};{hi:+6.3f}] доля{dp:+5.1f}%{mark}")
            print(f"    {str(c):22} n={len(s4):5d} · " + " · ".join(parts))

    by_coin = defaultdict(list)
    for t, symbol, side, cells in raw:
        d = bars(symbol); pos, atr = at(d, t)
        if pos is not None and atr:
            v = forward(d, pos, side == "LONG")["24ч"]
            if v is not None:
                by_coin[symbol].append(v)
    if by_coin:
        pos_n = sum(1 for v in by_coin.values() if sorted(v)[len(v) // 2] > 0)
        print(f"\n— охват монет: {len(by_coin)} · с положительной медианой 24ч: {pos_n} "
              f"({pos_n / len(by_coin) * 100:.0f}%)")
    print("\n  Вердикт по этому стенду формулировать как «слой L1 ...» (§0.2). Для решения об отключении "
          "нужны ещё L2–L5 и пререгистрированный критерий в паспорте механики.")


if __name__ == "__main__":
    main()
