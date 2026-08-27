"""
strategy_preflight.py — ПРЕДПОЛЁТНАЯ ПРОВЕРКА СТРАТЕГИИ.

Гонит синтетический сигнал источника через ВСЕ гейты и печатает, кто его убил.
Ловит МОЛЧАЛИВЫЕ отказы ДО боя, а не через сутки простоя.

Повод (21.08.2026): чтобы завести impulse_fib, пришлось тронуть 11 мест в config.yaml
и 8 файлов кода. 15 дефектов, 9 молчаливых. Каждый обнаруживался ТОЛЬКО через отказ
в бою. Корень — к свойствам стратегии ходят по ЧЕТЫРЁМ РАЗНЫМ КЛЮЧАМ:

    место                        ключ поиска                       дефолт
    gates/min_sl_dist.py:31      ctx.source                        0.5
    gates/rr_filter.py:45        ctx.source                        2.0
    trade_simulator.py:453       trade_mode                        2.0
    trade_simulator.py:483       trade_mode                        0.5
    trade_simulator.py:795       signal_type_override              [ote_nested, impulse_fib]
    trade_simulator.py:890       signal_type_override              [ote_nested, impulse_fib]
    trade_simulator.py:1976      trade["signal_type"] (из БД)      trading.tsl_activation_r
    order_manager.py:490         параметр source                   0.1  ← ДРУГОЙ дефолт!

У impulse_fib все ключи совпали СЛУЧАЙНО. У следующей стратегии не совпадут.

Запуск:
    python scripts/strategy_preflight.py                 # все источники, кратко
    python scripts/strategy_preflight.py impulse_fib     # полный разбор одного
    python scripts/strategy_preflight.py --gates rangefade   # + прогон через гейты
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 🔴 ТОЛЬКО боевой загрузчик: он мержит sl_tp_engine → trading (config_loader.py:31-44).
# Сырой yaml.safe_load даёт ЛОЖНЫЕ выводы — проверено 21.08 на tsl_activation_r_per_strategy.
from core.infra.config_loader import config  # noqa: E402
from core.trading.source_policies import SourcePolicy  # noqa: E402

G, R, Y, B, D = "\033[92m", "\033[91m", "\033[93m", "\033[94m", "\033[0m"


def _loop_overrides() -> dict[str, str]:
    """
    Что ставит в signal_type_override КАЖДЫЙ луп — грепом по коду, а не по памяти.
    Литерал берётся как есть; переменная (SRC/src) резолвится по константе модуля,
    иначе остаётся <...> = «вычисляется в рантайме, статически не определить».
    """
    out: dict[str, str] = {}
    pat = re.compile(r'"signal_type_override"\s*:\s*(.+?)[,\n]')
    for f in sorted((ROOT / "bot" / "loops").glob("*.py")):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for m in pat.finditer(txt):
            raw = m.group(1).strip().rstrip(",").strip()
            if raw.startswith('"'):
                val = raw.strip('"')
            else:
                const = re.search(rf'^{re.escape(raw)}\s*=\s*"([^"]+)"', txt, re.M)
                val = const.group(1) if const else f"<{raw}>"
            out[f.stem.replace("_loop", "")] = val
    return out


def resolve_keys(src: str, loop_ovr: dict[str, str]) -> dict:
    """Четыре ключа, по которым код ищет свойства этого источника."""
    pol = SourcePolicy.from_config(config, src)
    ovr = next((v for k, v in loop_ovr.items() if k == src or v == src), None)
    return {
        "source": src,
        "trade_mode": pol.trade_mode or "(пусто)",
        "override": ovr or "(луп не найден)",
        "policy": pol,
    }


def thresholds(keys: dict) -> list[tuple]:
    """(параметр, место, ключ, значение, найден_ли_per_strategy)."""
    src, tm, ovr = keys["source"], keys["trade_mode"], keys["override"]
    g_sl = float(config.get("trading.min_sl_dist_pct", 0.5))
    g_rr = float(config.get("trading.min_rr_ratio", 2.0))
    p_sl = config.get("trading.min_sl_dist_per_strategy", {}) or {}
    p_rr = config.get("trading.min_rr_per_strategy", {}) or {}
    p_tsl = config.get("trading.tsl_activation_r_per_strategy", {}) or {}
    ex_rr = config.get("trading.sl_management.rr_cap_exempt") or ["ote_nested", "impulse_fib"]
    single = config.get("trading.single_tp_sources") or ["ote_nested", "impulse_fib"]

    def pick(tbl, key, glob):
        return (float(tbl[key]), True) if key in tbl else (glob, False)

    rows = []
    for place, key, dflt in (
        ("router/min_sl_dist:31", src, 0.5),
        ("trade_simulator:483", tm, 0.5),
        ("order_manager:490", src, 0.1),
    ):
        v, hit = pick(p_sl, key, g_sl)
        rows.append(("min_sl_dist_pct", place, key, v, hit, dflt))
    for place, key in (("router/rr_filter:45", src), ("trade_simulator:453", tm)):
        v, hit = pick(p_rr, key, g_rr)
        rows.append(("min_rr", place, key, v, hit, 2.0))
    v, hit = pick(p_tsl, ovr, float(config.get("trading.tsl_activation_r", 1.0)))
    rows.append(("tsl_activation_r", "trade_simulator:1976", ovr, v, hit, 1.0))
    rows.append(("rr_cap_exempt", "trade_simulator:795", ovr, ovr in ex_rr, ovr in ex_rr, False))
    rows.append(("single_tp", "trade_simulator:890", ovr, ovr in single, ovr in single, False))
    return rows


def report(src: str, loop_ovr: dict[str, str]) -> list[str]:
    """Полный разбор одного источника. Возвращает список 🔴-проблем."""
    keys = resolve_keys(src, loop_ovr)
    pol = keys["policy"]
    problems: list[str] = []

    print(f"\n{B}{'═' * 100}{D}\n{B}  ИСТОЧНИК: {src}{D}\n{B}{'═' * 100}{D}")

    # ── A. ключи ──
    print(f"\n{Y}A. ЧЕТЫРЕ КЛЮЧА (по ним код ищет свойства){D}")
    uniq = {keys["source"], keys["trade_mode"], keys["override"]} - {"(пусто)", "(луп не найден)"}
    for label, val in (("source", keys["source"]), ("policy.trade_mode", keys["trade_mode"]),
                       ("signal_type_override", keys["override"])):
        mark = "" if val in (src, "(пусто)") else f"  {R}← расходится с source{D}"
        print(f"   {label:<24} = {val}{mark}")
    if len(uniq) > 1:
        problems.append(f"ключи расходятся: {uniq} — пороги будут искаться по РАЗНЫМ именам")
        print(f"   {R}🔴 КЛЮЧИ РАСХОДЯТСЯ → часть порогов не найдётся{D}")
    else:
        print(f"   {G}✓ все ключи совпадают{D}")

    # ── B. пороги ──
    print(f"\n{Y}B. ПОРОГИ ПО МЕСТАМ (расхождение = молчаливый отказ){D}")
    print(f"   {'параметр':<18}{'место':<24}{'ключ':<20}{'значение':>10}  источник")
    rows = thresholds(keys)
    by_param: dict[str, set] = {}
    for param, place, key, val, hit, dflt in rows:
        by_param.setdefault(param, set()).add(str(val))
        origin = f"{G}per-strategy{D}" if hit else f"{Y}глобальный/дефолт {dflt}{D}"
        print(f"   {param:<18}{place:<24}{str(key):<20}{str(val):>10}  {origin}")
    for param, vals in by_param.items():
        if len(vals) > 1:
            problems.append(f"{param}: РАЗНЫЕ значения в разных местах {vals}")
            print(f"   {R}🔴 {param}: места видят РАЗНОЕ → {vals}{D}")

    # ── C. конфиг стратегии + policy ──
    print(f"\n{Y}C. ПОЛИТИКА ИСПОЛНЕНИЯ И СЕКЦИЯ СТРАТЕГИИ{D}")
    print(f"   min_strength={pol.min_strength}  exchange={pol.exchange_enabled}  "
          f"order={pol.entry_order_type}  lev={pol.leverage}  risk%={pol.risk_pct}  "
          f"set_to_max={pol.lev_set_to_max}")
    sec = config.get(f"trading.{src}", None)
    if isinstance(sec, dict):
        keep = {k: sec[k] for k in ("enabled", "shadow", "sides", "max_open",
                                    "min_stop_pct", "max_stop_pct", "require_gates") if k in sec}
        print(f"   trading.{src}: {keep}")
        if sec.get("enabled") is False:
            problems.append("trading.%s.enabled = false — стратегия ВЫКЛЮЧЕНА" % src)
            print(f"   {R}🔴 enabled=false — не торгует{D}")
        if sec.get("shadow") is True:
            print(f"   {Y}⚠ shadow=true — пишет в журнал, но НЕ в бой{D}")
        lo, hi = sec.get("min_stop_pct"), sec.get("max_stop_pct")
        sl_router = next(r[3] for r in rows if r[0] == "min_sl_dist_pct" and "router" in r[1])
        if lo is not None and float(lo) < float(sl_router):
            problems.append(f"min_stop_pct={lo}% НИЖЕ гейта min_sl_dist={sl_router}% — "
                            f"часть сигналов зарежется молча")
            print(f"   {R}🔴 min_stop_pct={lo}% < min_sl_dist={sl_router}% → отказы{D}")
    else:
        print(f"   trading.{src}: {Y}секции нет{D} (механика берёт дефолты кода)")
    if not pol.exchange_enabled:
        print(f"   {Y}⚠ exchange_enabled=false — только симуляция{D}")
    return problems


# ── D. прогон синтетического сигнала через HARD-гейты ────────────────────────
class _Rec:
    """Duck-typed TradingRecommendation — только поля, которые читают гейты."""
    def __init__(self, symbol, direction, entry, sl, tp, signal_type, strength):
        self.symbol, self.direction = symbol, direction
        self.entry_price, self.stop_loss, self.take_profit = entry, sl, tp
        self.signal_type, self.strength = signal_type, strength
        self.supporting_signals: list = []


class _Bot:
    def __init__(self):
        self.config = config
        self.db_path = str(ROOT / "subscriptions.db")
        self.pivot_calculator = None
        self.data_collector = None


async def run_gates(src: str, loop_ovr: dict[str, str], stop_pct: float, rr: float) -> None:
    from core.trading.gates.base import GateContext
    from core.trading.trade_router import TradeRouter

    keys = resolve_keys(src, loop_ovr)
    entry = 100.0
    sl = entry * (1 - stop_pct / 100.0)
    tp = entry + (entry - sl) * rr
    rec = _Rec("BTC/USDT:USDT", "LONG", entry, sl, tp, src, 70)
    bot = _Bot()
    ctx = GateContext(
        rec=rec, symbol=rec.symbol, direction="LONG", signal_type=src, strength=70,
        source=src, extra_features={"signal_type_override": keys["override"],
                                    "trade_mode": keys["trade_mode"]},
        policy=keys["policy"], regime="TREND", open_trades=[], bot=bot,
    )
    print(f"\n{Y}D. ПРОГОН СИНТЕТИЧЕСКОГО СИГНАЛА{D}")
    print(f"   LONG BTC entry={entry} sl={sl:.2f} (стоп {stop_pct}%) tp={tp:.2f} (RR {rr}) strength=70")
    router = TradeRouter.__new__(TradeRouter)
    TradeRouter.__init__(router, bot)  # type: ignore[misc]
    killed = False
    for gate in router._hard_gates:  # noqa: SLF001
        try:
            res = await gate.check(ctx)
        except Exception as e:  # noqa: BLE001
            print(f"   {Y}?{D} {gate.name:<22} не проверен: {type(e).__name__}: {str(e)[:60]}")
            continue
        if res.passed:
            print(f"   {G}✓{D} {gate.name:<22} пропустил")
        else:
            killed = True
            print(f"   {R}✗ {gate.name:<22} УБИЛ: {res.reason}{D}")
    print(f"\n   {R}🔴 сигнал НЕ дойдёт до биржи{D}" if killed
          else f"\n   {G}✓ сигнал проходит все HARD-гейты{D}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Предполётная проверка стратегии")
    ap.add_argument("source", nargs="?", help="источник; без аргумента — сводка по всем")
    ap.add_argument("--gates", action="store_true", help="прогнать синтетический сигнал")
    ap.add_argument("--stop", type=float, default=2.0, help="стоп %% для прогона (по умолч. 2.0)")
    ap.add_argument("--rr", type=float, default=2.0, help="RR для прогона (по умолч. 2.0)")
    a = ap.parse_args()

    loop_ovr = _loop_overrides()
    sr = (config.get("signal_router.source_policies", {}) or {})

    if not a.source:
        print(f"\n{B}СВОДКА ПО ВСЕМ ИСТОЧНИКАМ{D}  (🔴 = найдены расхождения)")
        print(f"{'источник':<20}{'trade_mode':<18}{'override':<24}{'проблем':>8}")
        total = 0
        for s in sorted(sr.keys()):
            k = resolve_keys(s, loop_ovr)
            n = len(report_quiet(s, loop_ovr))
            total += 1 if n else 0
            mark = f"{R}{n}{D}" if n else f"{G}0{D}"
            print(f"{s:<20}{k['trade_mode']:<18}{k['override']:<24}{mark:>17}")
        print(f"\nисточников с расхождениями: {R}{total}{D} из {len(sr)}")
        print(f"\nПодробно: {B}python scripts/strategy_preflight.py <источник> --gates{D}")
        return 0

    problems = report(a.source, loop_ovr)
    if a.gates:
        asyncio.run(run_gates(a.source, loop_ovr, a.stop, a.rr))

    print(f"\n{B}{'─' * 100}{D}")
    if problems:
        print(f"{R}🔴 ПРОБЛЕМ: {len(problems)}{D}")
        for p in problems:
            print(f"   • {p}")
        return 1
    print(f"{G}✓ расхождений не найдено{D}")
    return 0


def report_quiet(src: str, loop_ovr: dict[str, str]) -> list[str]:
    """Тот же анализ без печати — для сводки."""
    import contextlib, io  # noqa: PLC0415
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return report(src, loop_ovr)


if __name__ == "__main__":
    sys.exit(main())
