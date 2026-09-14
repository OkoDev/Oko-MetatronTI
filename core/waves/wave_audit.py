"""🧪 Автосверка разметки сетапа тени по правилам методички (строка «ИИ» на :8010/waves, Егор 14.09).

Вердикт — один из тех, что ставит Егор: верно · степень не та · четвёртая не там · удлинение · не импульс · начало не там.
Правила детерминированы (воспроизводимо, без внешних моделей); оценка Егора — контроль, счётчик согласия показывает,
насколько правилам можно верить. Порядок старшинства: не импульс > начало не там > удлинение > четвёртая не там >
степень не та > верно. Предупреждения (не меняют вердикт) пишутся в заметку."""
from __future__ import annotations

from typing import Any, Dict, Optional

VERDICTS = ["верно", "степень не та", "четвёртая не там", "удлинение", "не импульс", "начало не там"]


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def audit_setup(rec: Dict[str, Any], analyst: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """rec — запись state.json тени; analyst — json разбора (структура с уточнённой точкой 0), если есть."""
    why, warn = [], []
    depth5, w2, w4, w3x = _f(rec.get("depth5")), _f(rec.get("w2_retr")), _f(rec.get("w4_retr")), _f(rec.get("w3_ext"))
    p0, p5 = _f(rec.get("p0")), _f(rec.get("p5"))
    verdict = None
    # 1. не импульс: пятая не дошла до базовой линии канала 2-4 (плато / 1-2-3 и консолидация)
    if depth5 is not None and depth5 < 0:
        verdict = "не импульс"; why.append(f"канал {depth5:.2f} < 0 — пятая не дошла даже до линии 2-4")
    # 2. начало не там: точка 0 уточнилась до экстремума ноги больше чем на 5% хода
    st = (analyst or {}).get("structure") or {}
    p0x = _f(st.get("p0"))
    if verdict is None and p0 and p5 and p0x and abs(p0 - p5) > 0:
        shift = abs(p0x - p0) / abs(p0 - p5)
        if shift > 0.05:
            verdict = "начало не там"; why.append(f"точка 0 детектора {p0:.6g}, экстремум ноги {p0x:.6g} (сдвиг {shift:.0%} хода)")
    # 3. удлинение: пятая далеко за параллелью канала (выброс) — вероятно, удлинённая пятая или подволны
    if verdict is None and depth5 is not None and depth5 > 1.5:
        verdict = "удлинение"; why.append(f"канал {depth5:.2f} > 1.5 — пятая вылетела за параллель через 3")
    # 4. четвёртая не там: откат четвёртой вне канона или нет чередования со второй
    if verdict is None and w4 is not None and not (0.146 <= w4 <= 0.618):
        verdict = "четвёртая не там"; why.append(f"откат 4 = {w4:.2f} вне 0.146–0.618")
    if verdict is None and rec.get("altern") is False and w2 is not None and w4 is not None and abs(w2 - w4) < 0.1:
        verdict = "четвёртая не там"; why.append(f"нет чередования: откаты 2 и 4 почти равны ({w2:.2f} / {w4:.2f})")
    # 5. степень не та: сдвинутый на два свинга счёт каноничнее нашего
    if verdict is None and rec.get("count_ok") is False:
        verdict = "степень не та"; why.append("сдвинутый счёт даёт более каноничную третью — наши волны, похоже, подволны")
    if verdict is None:
        verdict = "верно"; why.append("правила формы, канал, четвёртая, счёт — в норме")
    # предупреждения
    if rec.get("fractal") is False:
        warn.append("фрактал ✗ (в 1 или 3 нет младших сломов — первая могла быть из пары свечей)")
    if depth5 is not None and 0 <= depth5 < 0.5:
        warn.append(f"канал {depth5:.2f} < 0.5 — пятая усечена/не дотянула")
    if w2 is not None and w2 > 0.886:
        warn.append(f"вторая очень глубокая ({w2:.2f})")
    if w3x is not None and w3x < 1.0:
        warn.append(f"третья короче первой ({w3x:.2f}) ⇒ пятая должна быть короче третьей")
    note = "; ".join(why) + (" · ⚠ " + "; ".join(warn) if warn else "")
    return {"ai": verdict, "ai_note": note}


def agreement(reviews: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Согласие правил с Егором по сетапам, где есть обе оценки."""
    both = [(r.get("egor"), r.get("ai")) for r in reviews.values() if r.get("egor") and r.get("ai")]
    hit = sum(1 for e, a in both if e == a)
    by = {}
    for e, a in both:
        d = by.setdefault(e, [0, 0]); d[1] += 1; d[0] += int(e == a)
    return {"n": len(both), "hit": hit, "by_egor": {k: f"{v[0]}/{v[1]}" for k, v in by.items()}}
