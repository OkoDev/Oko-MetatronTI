"""
DEV-235: Ретробэктест паттернов ARCH-104 на ИСПРАВЛЕННОМ combinator_v2.

Контекст: дивергенции (DEV-233 RSI/WT) и wt_cross (DEV-234) переписаны.
Метрики паттернов в config/arch104_patterns.yaml (test_avgR/WR/n) считались на
СТАРОМ сломанном combinator → невалидны. Этот скрипт пересчитывает их на новом
коде и сравнивает.

ЭТАП 1 (этот файл): HTF-паттерны (anchor только 1h/4h/1d) — combinator_v2 умеет
нативно (process_symbol строит флаги 1h/4h/1d, simulate на 1h-сетке).
5m/15m-паттерны (с LTF-якорями) помечаются SKIP_LTF — для них нужен LTF-движок
(этап 2, отдельно — combinator_v3_nested / fractal_nested).

Запуск:
  python tools/pattern_mining/retrobacktest_dev235.py
Вывод: tmp_charts/dev235_retrobacktest.csv + сводка в stdout.
"""
import sys
from pathlib import Path
import yaml
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pattern_mining"))
import combinator_v2 as cb   # combinator_v2 сам ставит utf-8 stdout wrapper

cb.MIN_N = 10   # снижаем порог — паттерны узкие, хотим увидеть даже малые n

PATTERNS_YAML = ROOT / "config" / "arch104_patterns.yaml"
OUT_CSV = ROOT / "tmp_charts" / "dev235_retrobacktest.csv"


def load_patterns():
    d = yaml.safe_load(open(PATTERNS_YAML, encoding="utf-8"))
    return d.get("patterns", {})


def is_htf_only(anchors):
    """True если ВСЕ anchor-флаги вычислимы на 1h/4h/1d сетке (нет _5m/_15m)."""
    for a in anchors:
        if a.endswith("_5m") or a.endswith("_15m"):
            return False
    return True


def main():
    print("=" * 70)
    print("DEV-235 РЕТРОБЭКТЕСТ — HTF-паттерны на исправленном combinator_v2")
    print("=" * 70)

    pats = load_patterns()
    print(f"Всего паттернов в конфиге: {len(pats)}")

    # 1. Загружаем флаги всех пар (НОВЫЙ combinator с фиксами DEV-233/234)
    files = sorted(cb.HISTORY_DIR.glob("*.parquet"))
    print(f"\n[1] Загрузка {len(files)} пар (1h+4h+1d флаги, исправленный код)...")
    flags_dict = {}
    for i, p in enumerate(files):
        res = cb.process_symbol(p)
        if res is not None:
            flags_dict[p.stem] = res
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(files)} ({len(flags_dict)} валидных)")
    print(f"    Загружено пар: {len(flags_dict)}")
    if not flags_dict:
        print("НЕТ данных — проверь data/history/1h/*.parquet")
        return

    # 2. Для каждого паттерна — evaluate на новом коде
    print(f"\n[2] Пересчёт метрик паттернов...")
    rows = []
    skipped_ltf = 0
    for name, cfg in pats.items():
        if not isinstance(cfg, dict):
            continue
        anchors = cfg.get("anchor_factors", [])
        direction = cfg.get("direction", "LONG")
        old_n = cfg.get("test_n", 0)
        old_avgR = cfg.get("test_avgR", 0.0)
        old_WR = cfg.get("test_WR", 0.0)
        det_tf = cfg.get("detection_tf", "1h")

        if not is_htf_only(anchors):
            skipped_ltf += 1
            rows.append({
                "pattern": name, "tf": det_tf, "dir": direction,
                "status": "SKIP_LTF", "old_n": old_n, "old_avgR": old_avgR,
                "old_WR": old_WR, "new_n": None, "new_avgR": None, "new_WR": None,
                "delta_avgR": None, "anchors": ";".join(anchors),
            })
            continue

        stats = cb.evaluate(flags_dict, tuple(anchors), direction)
        if stats is None:
            rows.append({
                "pattern": name, "tf": det_tf, "dir": direction,
                "status": "NO_MATCH", "old_n": old_n, "old_avgR": old_avgR,
                "old_WR": old_WR, "new_n": 0, "new_avgR": None, "new_WR": None,
                "delta_avgR": None, "anchors": ";".join(anchors),
            })
        else:
            rows.append({
                "pattern": name, "tf": det_tf, "dir": direction,
                "status": "OK", "old_n": old_n, "old_avgR": round(old_avgR, 3),
                "old_WR": round(old_WR, 1),
                "new_n": stats["n"], "new_avgR": round(stats["avgR"], 3),
                "new_WR": round(stats["WR"], 1),
                "delta_avgR": round(stats["avgR"] - old_avgR, 3),
                "anchors": ";".join(anchors),
            })

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")

    # 3. Сводка
    ok = df[df["status"] == "OK"].copy()
    print(f"\n{'='*70}")
    print(f"РЕЗУЛЬТАТ: всего {len(df)} | HTF пересчитано {len(ok)} | "
          f"SKIP_LTF {skipped_ltf} | NO_MATCH {(df['status']=='NO_MATCH').sum()}")
    print(f"{'='*70}")

    if len(ok):
        # Деградировавшие: было avgR>0, стало <=0 или сильно упало
        ok_sorted = ok.sort_values("delta_avgR")
        print(f"\n🔻 ТОП-15 ДЕГРАДАЦИЙ (new avgR ≪ old):")
        print(f"{'pattern':<22}{'tf':<5}{'old_avgR':>9}{'new_avgR':>9}{'Δ':>8}{'old_n':>7}{'new_n':>7}")
        for _, r in ok_sorted.head(15).iterrows():
            print(f"{r['pattern']:<22}{r['tf']:<5}{r['old_avgR']:>9}{r['new_avgR']:>9}"
                  f"{r['delta_avgR']:>8}{r['old_n']:>7}{r['new_n']:>7}")

        print(f"\n🔺 ТОП-10 УЛУЧШИЛИСЬ (new avgR > old):")
        for _, r in ok_sorted.tail(10)[::-1].iterrows():
            print(f"{r['pattern']:<22}{r['tf']:<5}{r['old_avgR']:>9}{r['new_avgR']:>9}"
                  f"{r['delta_avgR']:>8}{r['old_n']:>7}{r['new_n']:>7}")

        # Сколько паттернов "перевернулись" из + в -
        flipped = ok[(ok["old_avgR"] > 0) & (ok["new_avgR"] <= 0)]
        print(f"\n⚠️ Паттернов перевернулось из avgR>0 в avgR<=0: {len(flipped)}")
        if len(flipped):
            print("   ", ", ".join(flipped["pattern"].tolist()[:15]))
        still_good = ok[(ok["new_avgR"] > 0.5) & (ok["new_n"] >= 20)]
        print(f"✅ Остались сильными (new avgR>0.5, n≥20): {len(still_good)}")
        if len(still_good):
            print("   ", ", ".join(still_good["pattern"].tolist()[:15]))

    print(f"\nCSV: {OUT_CSV}")


if __name__ == "__main__":
    main()
