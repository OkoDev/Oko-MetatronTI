"""Схема ручного разбора BCH 14.09: 1D памп и фибо коррекции, 1h счёт снижения от 305.9 с незавершённой пятой/C, уровни (OB/FVG/пивоты), сценарии."""
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

BG, FG, GRID, UP, DN, WAVE, ACC, LINE, VIO, GRN = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#ff8f00", "#9575cd", "#66bb6a"
D1 = pd.read_pickle("coin_BCH_1d.pkl"); H1 = pd.read_pickle("coin_BCH_1h.pkl"); M15 = pd.read_pickle("coin_BCH_15m.pkl")
PX = float(M15.close.iloc[-1])


def candles(ax, w):
    x = np.arange(len(w)); o, h, l, c = (w[k].values for k in ("open", "high", "low", "close"))
    for i in range(len(w)):
        col = UP if c[i] >= o[i] else DN
        ax.vlines(x[i], l[i], h[i], color=col, lw=0.6); ax.add_patch(Rectangle((x[i] - .32, min(o[i], c[i])), .64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, lw=0))


def style(ax, t):
    ax.set_facecolor(BG); [s.set_color(GRID) for s in ax.spines.values()]; ax.tick_params(colors=FG, labelsize=7.5)
    ax.grid(True, color=GRID, lw=.5, alpha=.4); ax.set_title(t, color=FG, fontsize=10, loc="left")


def xi(w, t):
    return int(w.index.get_indexer([pd.Timestamp(t, tz="UTC")], method="nearest")[0])


def seg(ax, x0, x1, y, txt, col, ls="--", lw=.9, side="right"):
    ax.hlines(y, min(x0, x1), max(x0, x1), colors=col, linestyles=ls, lw=lw)
    ax.annotate(f"{txt} {y:.1f}", (max(x0, x1) if side == "right" else min(x0, x1), y), color=col, fontsize=7, va="center",
                ha="left" if side == "right" else "right", xytext=(3 if side == "right" else -3, 0), textcoords="offset points")


def arrow(ax, p0, p1, col, ls, txt=None, off=(5, 0)):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=14, color=col, lw=1.6, linestyle=ls, zorder=7))
    if txt:
        ax.annotate(txt, p1, color=col, fontsize=8, fontweight="bold", xytext=off, textcoords="offset points", va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc=BG, ec="none", alpha=.85))


fig = plt.figure(figsize=(15, 13.5), facecolor=BG)
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.35], width_ratios=[1.4, 1], hspace=.25, wspace=.1)
# 1D: памп 199.4 → 305.9 и фибо коррекции
ax = fig.add_subplot(gs[0, 0]); w = D1.iloc[-110:]; candles(ax, w); style(ax, "1D · памп 14.08→22.08 (199.4 → 305.9) и глубина коррекции")
x0, x1 = xi(w, "2026-08-14"), xi(w, "2026-08-22"); lo, hi = 199.4, 305.85; R = hi - lo
ax.plot([x0, x1], [lo, hi], color=WAVE, lw=1.2, ls="--")
for f, col in ((.382, VIO), (.5, VIO), (.618, ACC), (.705, ACC), (.786, ACC), (.886, VIO), (1.0, FG)):
    seg(ax, x0, x1, hi - f * R, f"{f}", col, ":" if f not in (.786,) else "-", .8, side="left")
ax.add_patch(Rectangle((x0, hi - .886 * R), x1 - x0, .276 * R, color=ACC, alpha=.08, lw=0))
ax.scatter([len(w) - 1], [PX], color=FG, s=20, zorder=6); ax.annotate(f"цена {PX:.1f} ≈ 0.786", (len(w) - 1, PX), color=ACC, fontsize=8, xytext=(-8, -14), textcoords="offset points", ha="right")
ax.set_xlim(-2, len(w) + 10)
# 1h: счёт снижения от 305.9
ax = fig.add_subplot(gs[1, 0]); w = H1[H1.index >= "2026-08-19"]; candles(ax, w); style(ax, "1h · снижение от 305.9: 1(A) · 2(B) · 3(C?) · 4 · пятая/C не завершена · уровни и сценарии")
pts = [("2026-08-22 02:00", 305.85, "0"), ("2026-08-30 23:00", 239.6, "1/A"), ("2026-09-07 16:00", 269.21, "2/B"), ("2026-09-11 12:00", 219.0, "3/C?"), ("2026-09-11 14:00", 237.85, "4")]
xs = [xi(w, t) for t, _, _ in pts]; ys = [p for _, p, _ in pts]
ax.plot(xs + [len(w) - 1], ys + [PX], color=WAVE, lw=1.6); ax.scatter(xs, ys, color=WAVE, s=30, zorder=6)
for (t, p, lb), x in zip(pts, xs):
    ax.annotate(lb, (x, p), color=WAVE, fontsize=10, fontweight="bold", xytext=(-6, 8 if lb in ("0", "2/B", "4") else -16), textcoords="offset points")
n = len(w) - 1; F = 80
# уровни (отрезками от места появления до правого края)
for y0, y1, nm, col, t in ((201.77, 203.77, "4h OB бычий", GRN, "2026-08-16"), (194.05, 201.28, "4h OB бычий", GRN, "2026-08-20"),
                           (226.45, 229.9, "4h FVG медвежий", DN, "2026-09-10 08:00"), (224.2, 225.86, "1h OB медвежий", DN, "2026-09-13 11:00"),
                           (257.57, 261.18, "4h OB медвежий", DN, "2026-09-08 08:00")):
    xa = xi(w, t); ax.add_patch(Rectangle((xa, y0), n + F - xa, y1 - y0, color=col, alpha=.13, lw=0))
    ax.annotate(nm, (n + F, y1), color=col, fontsize=7, ha="right", va="bottom")
for y, nm, col in ((222.23, "D PP", FG), (218.38, "D S1", GRN), (214.88, "D S2", GRN), (204.0, "W S1", GRN), (196.39, "M S1", GRN), (236.25, "W PP", DN)):
    seg(ax, n - 40, n + F, y, nm, col, "-.", .7)
seg(ax, xi(w, "2026-09-11 14:00"), n + F, 237.85, "отмена сценария вниз: выше 4", DN, "--", 1)
# цели пятой / C
for y, nm in ((211.45, "0.886 пампа"), (206.8, "5=0.618×3"), (202.9, "C=A")):
    seg(ax, n - 60, n + 12, y, nm, ACC, ":", 1, side="left")
ax.add_patch(Rectangle((n + 18, 199.4), 40, 12.1, color=ACC, alpha=.15, lw=0)); ax.annotate("зона завершения\n199–211", (n + 38, 199.6), color=ACC, fontsize=8, ha="center", va="bottom")
arrow(ax, (n, PX), (n + 30, 205.5), ACC, "-.", "A: 5/C вниз → 199–211", (-150, -22))
arrow(ax, (n + 30, 205.5), (n + 72, 230.0), GRN, "--", "затем лонг → 238 / 243+", (6, -12))
arrow(ax, (n, PX), (n + 22, 231.0), UP, "--", "B: низ 219 → 226–238", (-40, 26))
ax.set_xlim(-5, n + F + 30); ax.set_ylim(185, 312)
# текст
at = fig.add_subplot(gs[:, 1]); at.axis("off"); y = .99
import textwrap
T = [("BCH · волновой разбор и уровни", 15, FG, True), (f"14.09.2026 ~09:50 UTC · цена {PX:.1f} · режим терминала: TREND_DOWN", 9, "#9aa3b2", False),
     ("Контекст 1D", 11, ACC, True),
     ("Памп 14→22.08: 199.4 → 305.9 (+53% за 8 дней). С 22.08 — коррекция: нижний максимум 269.2 (07.09), дневной слом вниз 10.09 (239.6). Цена 221.6 — на 0.786 пампа, WT 1D −25 и падает, ATRTrend 1D вниз 18 дней.", 9, FG, False),
     ("Счёт снижения (1h, свинги 50/60)", 11, ACC, True),
     ("0 = 305.9 → 1/A = 239.6 (−66.3) → 2/B = 269.2 (откат 0.45) → 3/C = 219.0 (−50.2, 0.76×первой) → 4 = 237.8 (откат 0.37, без перекрытия с 1) → сейчас 221.6 идём на тест 219. Детектор ядра: пятая ещё не прошла 219 — импульс не достроен, сетапа нет.", 9, FG, False),
     ("Правило: третья короче первой ⇒ пятая обязана быть короче третьей (≤ 50.2) ⇒ минимум пятой не ниже ~187.6. Типичные цели: 0.886 пампа 211.5 · 5 = 0.618×3 → 206.8 · C = A → 202.9. Кластер поддержки 199–204: начало пампа 199.4, 4h бычьи OB 201.8–203.8 и 194–201, W S1 204.0, M S1 196.4.", 9, FG, False),
     ("Индикаторы", 11, ACC, True),
     ("WT 4h −52.6 (перепродан, wt1≈wt2 — на грани кросса вверх) · WT 1h −22.6 растёт, ATRTrend 1h развернулся вверх 6 ч назад · WT 15m −40, на 15m серия BOS вниз (последний 221.3). Сопротивления: 1h OB 224.2–225.9, D PP 222.2, 4h FVG 226.5–229.9, W PP 236.3, «4» 237.8.", 9, FG, False),
     ("Сценарий A (основной) · пятая/C вниз", 11, ACC, True),
     ("Пробой 219 → зона завершения 199–211. Там ждать: WT 4h/1h < −45 на минимуме, CHoCH 3m вверх и откат (механика RECALL), стоп под 0.886 волны A. Цели — коррекция всего снижения от 305.9 (при минимуме ~205): 0.382 ≈ 243, 0.5 ≈ 255, 0.618 ≈ 267; первая промежуточная — «4» 237.8. Отмена: закрытие 1h выше 237.8.", 9, FG, False),
     ("Сценарий B · низ уже стоит на 219", 11, GRN, True),
     ("Двойное дно 219 без обновления, CHoCH 1h вверх выше 225.9 (сверху 1h OB) и удержание 222 → первая цель 226.5–229.9 (FVG), затем 236–238. Отмена: пробой 219.", 9, FG, False),
     ("Шорт сейчас", 11, DN, True),
     ("Поздно: цена у поддержки 219–218 (D S1). Если продавать — только отказ от 224–230 (OB/FVG/PP) со стопом над 231.9, цели 211/204. По нашим замерам шорт-механика после пятёрок статистически НЕ платит — только как ручная идея.", 9, FG, False),
     ("Что говорит статистика программы", 11, VIO, True),
     ("Платящий класс — лонг после ЗАВЕРШЁННОЙ пятёрки с отбором ядра (фрактал+канал) и/или после массового слива рынка. Сейчас у BCH пятёрка не завершена → ждать уровня 199–211 и сигнала, не угадывать дно.", 9, FG, False)]
for txt, fs, col, bold in T:
    for ln in textwrap.wrap(txt, 64 if fs <= 9 else 50):
        at.text(0, y, ln, color=col, fontsize=fs, fontweight="bold" if bold else "normal", va="top"); y -= .0185 * fs / 9
    y -= .008
fig.savefig("BCH_razbor.png", dpi=105, facecolor=BG, bbox_inches="tight"); print("ok")
