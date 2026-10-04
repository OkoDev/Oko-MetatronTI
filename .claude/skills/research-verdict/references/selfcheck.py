# -*- coding: utf-8 -*-
"""Ассерты контракта данных для замеров (§0A протокола вердикта).

Зачем файл: проверки из §0A должны стоить ОДНУ СТРОКУ, иначе их не будет в скрипте.
Каждая функция падает громко и печатает, что именно разошлось, — чтобы ошибка ловилась
в момент прогона, а не в вердикте.

    import sys; sys.path.insert(0, r"E:\\MTF BOT\\CURSOR\\crypto_volume_bot\\.claude\\skills\\research-verdict\\references")
    from selfcheck import golden, no_merge_loss, single_side, parts_sum, raw, signed

Разбор ошибок, из которых это выросло (30.09–04.10): инвертированная метка «разворот/по
импульсу», `abs()` на знаковом slip, `stop_loss` вместо исходного риска, чужая сторона в
односторонней находке, «наполняемость 222%» из-за ключа merge без символа.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence


def golden(fn: Callable, cases: Sequence[tuple[tuple, Any]], name: str = "") -> None:
    """Прогон функции на примерах с ответом, посчитанным ВРУЧНУЮ (§0A.2).

        golden(rel_label, [(("LONG", "LONG"), "разворот"),
                           (("SHORT", "LONG"), "по импульсу")], "метка контекста")

    Любая метка и любой знак обязаны иметь golden-case: именно их отсутствие дало
    зеркальные выводы 02.10.
    """
    for args, want in cases:
        got = fn(*args)
        if got != want:
            raise AssertionError(
                f"GOLDEN{' ' + name if name else ''}: {fn.__name__}{args} = {got!r}, "
                f"а вручную посчитано {want!r} — смысл поля или метки понят неверно")
    print(f"  ✓ golden {name or fn.__name__}: {len(cases)} случаев")


def signed(values: Iterable[float], plus_means: str, name: str = "") -> None:
    """Печатает баланс знаков и ЗАПРЕЩАЕТ молча брать модуль (§0A.3).

    `plus_means` — словами, что означает ПЛЮС. 04.10 я взял `abs(slip)` и доложил
    «кост съедает 72% риска», тогда как знак означал «исполнились ЛУЧШЕ сигнала».
    """
    v = [x for x in values if x == x]
    if not v:
        print(f"  ⚠ {name or 'поле'}: пустая выборка")
        return
    pos = sum(1 for x in v if x > 0)
    neg = sum(1 for x in v if x < 0)
    zero = len(v) - pos - neg
    print(f"  ✓ знак {name or 'поля'}: плюс = «{plus_means}» · "
          f"плюсов {pos} ({100*pos/len(v):.0f}%) · минусов {neg} · нулей {zero}")
    if zero and zero / len(v) > 0.5:
        print(f"    🔴 ВНИМАНИЕ: нулей больше половины — проверь, не значит ли 0 «НЕ ИЗМЕРЕНО» "
              f"(ровно это было с live_orders.slip_pct)")


def no_merge_loss(before, after, keys: Sequence[str] | None = None) -> None:
    """После merge строк столько же (§0A.3). Рост = неполный ключ, падение = потеря данных."""
    nb, na = len(before), len(after)
    if nb != na:
        raise AssertionError(
            f"MERGE: было {nb} строк, стало {na} ({100*(na-nb)/max(nb,1):+.0f}%) — "
            f"ключ {list(keys) if keys else '?'} неполный (классика: забыт символ) "
            f"или справочник содержит дубли")
    print(f"  ✓ merge без потерь: {na} строк, ключ {list(keys) if keys else '—'}")


def single_side(df, side: str, col: str = "side") -> None:
    """Односторонняя находка мерится на СВОЕЙ стороне (§0A.3).

    04.10: «два минуса в коридоре» на форварде оказались ШОРТАМИ, а коридор измерен на лонгах.
    """
    got = set(map(str, df[col].dropna().unique()))
    if got != {side}:
        raise AssertionError(
            f"СТОРОНА: в выборке {sorted(got)}, а находка односторонняя ({side}) — "
            f"срез по стороне не применён")
    print(f"  ✓ сторона: только {side}, n={len(df)}")


def parts_sum(parts: Iterable[int], total: int, name: str = "") -> None:
    """Сумма групп равна целому — иначе часть выборки потерялась в нарезке (§0A.3)."""
    s = sum(parts)
    if s != total:
        raise AssertionError(f"НАРЕЗКА{' ' + name if name else ''}: сумма групп {s} != всего {total} "
                             f"(разница {total - s}) — где-то потерянные или двойные строки")
    print(f"  ✓ нарезка {name or ''}: {s} = {total}")


def raw(df, cols: Sequence[str], n: int = 5, title: str = "сырые строки") -> None:
    """Печать сырых строк под агрегатом (§0A.5). Клетки n<10 печатать целиком."""
    k = len(df) if len(df) < 10 else n
    print(f"  {title} ({k} из {len(df)}):")
    have = [c for c in cols if c in df.columns]
    for _, r in df.head(k).iterrows():
        print("    " + " · ".join(f"{c}={r[c]}" for c in have))


def calibration(got: dict[str, float], want: dict[str, float], tol: float = 0.05) -> None:
    """Воспроизведение прошлого замера ДО нового (§0A.4).

        calibration({"impulse_fib_1h": 5.38}, {"impulse_fib_1h": 5.38})

    Не сошлось → искать баг У СЕБЯ, а не докладывать новость.
    """
    bad = {k: (got.get(k), v) for k, v in want.items()
           if got.get(k) is None or abs(got[k] - v) > tol * max(abs(v), 1e-9)}
    if bad:
        raise AssertionError(
            "КАЛИБРОВКА не сошлась с прошлым замером: "
            + " · ".join(f"{k}: сейчас {g}, раньше {w}" for k, (g, w) in bad.items())
            + " — сначала подозревай свой пайплайн, а не рынок")
    print(f"  ✓ калибровка: {len(want)} известных чисел воспроизведены")
