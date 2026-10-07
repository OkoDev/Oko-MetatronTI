# -*- coding: utf-8 -*-
"""КАРТОЧКА ВЕРДИКТА — одна проверка кандидата для всех исследований (Егор 07.10: «стандартизацию
или унификацию сделать! как усовершенствовать процесс проверок?»).

Зачем. До 07.10 проверки писались руками в каждом скрипте: хрупкость — в 144 из 426, кост 0.35 —
в 64, своя перестановка — в 15; `report`/`blind_select` харнесса звали 4 скрипта. Что не написал —
то не проверил, и это не видно в выводе. Здесь все проверки яруса 1 считаются ОДНИМ вызовом, а то,
что посчитать нельзя (нет колонки), попадает в «НЕ проверено» само.

Контракт данных (`normalize`): одна строка = одна сделка, колонки
    sym · side · ts (вход, UTC) · pnl (% ЗА ВЫЧЕТОМ коста)
необязательные — включают свои проверки:
    ctrl (доход случайного входа той же геометрии) · geo-колонки (stop_pct, imp_pct…) ·
    liq (оборот) · exit_ts (выход — для перекрытия) · entry_type (market/limit)

Ярусы (дешёвое → дорогое):
  1. `card()` — на каждого кандидата, секунды: деньги · база+нулевая модель · контроль · прирост сверх
     геометрии · годы · охват монет · ликвидность · перекрытие · размер выборки; срезы сторона/кластер/тип входа.
  2. `search_null()` — на финалистов: тот же ПОИСК на перемешанных исходах — сколько «победителей»
     он находит на мусоре. Для перебора сочетаний это главная проверка.
  3. НЕ здесь, печатается как «НЕ проверено»: суррогат IAAFT · свежий форвард · паритет с боем
     (формирующийся бар, длина окна) · тень.

Нулевая модель — ЦИКЛИЧЕСКИЙ СДВИГ ИСХОДОВ ВО ВРЕМЕНИ ВНУТРИ ГОДА: признаки остаются на своих сделках,
исходы уезжают блоком. Сохраняет скученность (капитуляция = много монет в один день) и уровень года,
рвёт связь «признак → исход». Урок 07.10: 87 сделок на 26 днях дали P 0.09 по сделкам и 0.81 по дням.

Журнал гипотез (`JOURNAL`): каждая карточка пишется с отпечатком набора данных → число проверенных
гипотез N считается само, в том числе между сессиями; повторное открытие отложенного куска помечается.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = dict(
    alpha=0.05,        # порог P нулевой модели (односторонний: кандидат ЛУЧШЕ остальных)
    n_null=1000,       # сдвигов на кандидата
    min_days=20,       # эффективная выборка — ДНИ, а не сделки
    min_coins=10,
    year_share=0.75,   # доля лет, где кандидат лучше остальных
    cov_share=0.50,    # доля монет кандидата в плюсе
    min_slice=10,      # меньше — срез не считается
    top_days_share=0.10,  # «без лучших дней»: убрать max(3, 10% дней кандидата)
    seed=0,
)
JOURNAL = Path("G:/oko_lab/out/hypothesis_journal.jsonl")
TIER3 = ("суррогат IAAFT", "свежий форвард (после конца кэша)",
         "паритет с боем (формирующийся бар, длина окна)", "тень на живом журнале шины")


# ─────────────────────────────── данные ───────────────────────────────

def normalize(R: pd.DataFrame, *, pnl: str = "pnl", ts: str = "ts", sym: str = "sym",
              side: str = "side", **rename) -> pd.DataFrame:
    """Приводит таблицу сделок к контракту. `rename`: ctrl=…, exit_ts=…, liq=…, entry_type=…"""
    D = R.copy()
    mapping = {pnl: "pnl", ts: "ts", sym: "sym", side: "side", **{v: k for k, v in rename.items()}}
    # 🔴 07.10: чужая колонка с именем цели (например `ts` из merge метрик) давала два `ts`
    D = D.drop(columns=[t for s, t in mapping.items() if s != t and t in D.columns])
    D = D.rename(columns=mapping)
    for c in ("ts", "exit_ts"):
        if c in D.columns:
            t = pd.to_datetime(D[c], utc=True, errors="coerce")
            D[c] = t.dt.tz_convert(None)
    D = D[D.pnl.notna() & D.ts.notna()].reset_index(drop=True)
    D["pnl"] = D.pnl.astype(float)
    D["year"] = D.ts.dt.year
    D["day"] = D.ts.dt.floor("D")
    return D


def fingerprint(D: pd.DataFrame) -> str:
    key = "\n".join(sorted(D.sym.astype(str) + "|" + D.ts.astype(str)))
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _stat(p: np.ndarray, syms: np.ndarray | None = None) -> dict:
    n = len(p)
    if n == 0:
        return dict(n=0)
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    s = np.sort(p)
    out = dict(n=n, wr=(p > 0).mean() * 100, pf=pos / neg if neg > 0 else 9.99, mean=p.mean(),
               med=float(np.median(p)), frail=float(s[:max(1, int(n * 0.9))].mean()))
    if syms is not None:
        per = pd.Series(p).groupby(syms).sum()
        out.update(coins=len(per), cov=(per > 0).mean() * 100)
    return out


def _fmt(st: dict) -> str:
    if not st.get("n"):
        return "n=0"
    cov = f" · монет+ {st['cov']:.0f}% из {st['coins']}" if "cov" in st else ""
    return (f"n={st['n']:<5} WR {st['wr']:4.0f}% · PF {st['pf']:5.2f} · средн {st['mean']:+6.2f}% · "
            f"медиана {st['med']:+6.2f}% · безтоп10% {st['frail']:+6.2f}%{cov}")


# ─────────────────────────────── нулевая модель ───────────────────────────────

def _year_groups(D: pd.DataFrame) -> list[np.ndarray]:
    order = np.argsort(D.ts.values, kind="stable")
    y = D.year.values[order]
    return [order[y == v] for v in np.unique(y)]


def _shifted(pnl: np.ndarray, groups: list[np.ndarray], rng) -> np.ndarray:
    """Исходы, циклически сдвинутые во времени внутри каждого года (сдвиг 10–90% длины)."""
    out = pnl.copy()
    for g in groups:
        L = len(g)
        if L < 3:
            continue
        k = int(rng.integers(max(1, L // 10), max(2, L - L // 10)))
        out[g] = pnl[np.roll(g, k)]
    return out


def _delta(p: np.ndarray, m: np.ndarray) -> float:
    return p[m].mean() - p[~m].mean()


def _strat_delta(p: np.ndarray, m: np.ndarray, strata: np.ndarray, min_n: int) -> float:
    """Δ «кандидат − остальные» внутри корзин, взвешенная числом сделок кандидата."""
    num = den = 0.0
    for s in np.unique(strata[strata >= 0]):
        a, b = (strata == s) & m, (strata == s) & ~m
        if a.sum() >= min_n and b.sum() >= min_n:
            num += (p[a].mean() - p[b].mean()) * a.sum()
            den += a.sum()
    return num / den if den else np.nan


# ─────────────────────────────── журнал ───────────────────────────────

def _journal_read() -> list[dict]:
    if not JOURNAL.exists():
        return []
    out = []
    for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except Exception:                                # noqa: BLE001
            pass
    return out


def _journal_write(rec: dict) -> None:
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:                               # noqa: BLE001
        print(f"🔴 журнал гипотез не записан: {e}")


# ─────────────────────────────── ярус 1 ───────────────────────────────

def card(D: pd.DataFrame, cand, *, name: str, study: str, geo: tuple = (),
         regimes: dict | None = None, holdout: bool = False, spec: dict | None = None,
         journal: bool = True, quiet: bool = False) -> dict:
    """Карточка вердикта. `D` — популяция в контракте `normalize`, `cand` — булева маска кандидата
    (кандидат ЗАЯВЛЕН лучше остальных популяции). `geo` — известные факторы, сверх которых кандидат
    обязан давать прирост (размер стопа, импульс…); колонку, которой кандидат ОПРЕДЕЛЁН, сюда не класть."""
    S = {**SPEC, **(spec or {})}
    m = np.asarray(cand, bool)
    p = D.pnl.values
    rng = np.random.default_rng(S["seed"])
    gates, missing, L = {}, [], []
    fp = fingerprint(D)
    say = L.append

    say("=" * 100)
    say(f"КАРТОЧКА · {study} · {name}")
    say(f"набор {fp}: {len(D)} сделок · {D.sym.nunique()} монет · {D.ts.min():%Y-%m-%d} → {D.ts.max():%Y-%m-%d}")
    say("=" * 100)
    sc, sr, sa = (_stat(p[m], D.sym.values[m]), _stat(p[~m], D.sym.values[~m]), _stat(p, D.sym.values))
    say(f"  кандидат   {_fmt(sc)}")
    say(f"  остальные  {_fmt(sr)}")
    say(f"  вся база   {_fmt(sa)}")
    if sc["n"] < S["min_slice"] or sr["n"] < S["min_slice"]:
        say("🔴 кандидат или остальные меньше минимума — карточка не строится")
        out = dict(name=name, study=study, passed=False, gates={}, text="\n".join(L))
        if not quiet:
            print(out["text"])
        return out

    # 1. деньги
    gates["деньги"] = sc["mean"] > 0 and sc["frail"] > 0
    say(f"\n[{'✅' if gates['деньги'] else '❌'}] ДЕНЬГИ: средн {sc['mean']:+.2f}% > 0 и без лучших 10% "
        f"{sc['frail']:+.2f}% > 0")

    # 2. лучше остальных + нулевая модель (сдвиг исходов во времени внутри года)
    groups = _year_groups(D)
    obs = _delta(p, m)
    geo_cols = [g for g in geo if g in D.columns]
    strata = {}
    for g in geo_cols:
        q = pd.qcut(D[g].rank(method="first"), 3, labels=False)
        strata[g] = q.fillna(-1).astype(int).values
    obs_s = {g: _strat_delta(p, m, strata[g], S["min_slice"]) for g in geo_cols}
    nul, nul_s = [], {g: [] for g in geo_cols}
    for _ in range(S["n_null"]):
        ps = _shifted(p, groups, rng)
        nul.append(_delta(ps, m))
        for g in geo_cols:
            nul_s[g].append(_strat_delta(ps, m, strata[g], S["min_slice"]))
    nul = np.asarray(nul)
    pv = (np.sum(nul >= obs) + 1) / (len(nul) + 1)
    gates["лучше остальных (нулевая модель)"] = obs > 0 and pv < S["alpha"]
    say(f"[{'✅' if gates['лучше остальных (нулевая модель)'] else '❌'}] ЛУЧШЕ ОСТАЛЬНЫХ: Δ {obs:+.2f} п.п. · "
        f"P {pv:.3f} (сдвиг исходов во времени внутри года, {S['n_null']}) · к базе {sc['mean'] - sa['mean']:+.2f}")

    # 3. контроль той же геометрии
    if "ctrl" in D.columns and D.ctrl.notna().any():
        dc = (D.pnl - D.ctrl).values
        ok = np.isfinite(dc)
        c_c, c_r = dc[m & ok].mean(), dc[~m & ok].mean()
        gates["лучше случайного входа той же геометрии"] = c_c > 0
        say(f"[{'✅' if c_c > 0 else '❌'}] КОНТРОЛЬ: кандидат − случайный вход {c_c:+.2f} п.п. "
            f"(у остальных {c_r:+.2f})")
    else:
        missing.append("контроль той же геометрии (нет колонки ctrl)")

    # 4. прирост сверх известных факторов
    for g in geo_cols:
        ns = np.asarray([x for x in nul_s[g] if np.isfinite(x)])
        o = obs_s[g]
        ps_ = (np.sum(ns >= o) + 1) / (len(ns) + 1) if len(ns) and np.isfinite(o) else np.nan
        ok = bool(np.isfinite(o) and o > 0 and ps_ < S["alpha"])
        gates[f"сверх {g}"] = ok
        say(f"[{'✅' if ok else '❌'}] СВЕРХ {g}: Δ внутри терцилей {o:+.2f} п.п. (сырая {obs:+.2f}) · P {ps_:.3f}")
    if not geo_cols:
        missing.append("прирост сверх геометрии (geo не задан)")

    # 5. годы
    rows, pos, cnt = [], 0, 0
    for y, g in D.groupby("year"):
        a, b = g.pnl[m[g.index]], g.pnl[~m[g.index]]
        tag = f" {regimes.get(y, '')}" if regimes else ""
        if len(a) >= S["min_slice"] and len(b) >= S["min_slice"]:
            cnt += 1
            pos += a.mean() > b.mean()
            rows.append(f"      {y}{tag}: кандидат {a.mean():+6.2f}% (n={len(a)}) · остальные {b.mean():+6.2f}% (n={len(b)})")
        else:
            rows.append(f"      {y}{tag}: мало (кандидат {len(a)}, остальные {len(b)})")
    ok = cnt >= 2 and pos / cnt >= S["year_share"]
    gates["годы"] = ok
    say(f"[{'✅' if ok else '❌'}] ГОДЫ: кандидат лучше в {pos} из {cnt} (нужно ≥{S['year_share']:.0%}, лет ≥2)")
    L.extend(rows)
    if not regimes:
        missing.append("подпись режима года (regimes не передан)")

    # 6. охват монет и размер выборки
    ok = sc.get("cov", 0) >= S["cov_share"] * 100
    gates["охват монет"] = ok
    days, coins = D.day[m].nunique(), D.sym[m].nunique()
    ok2 = days >= S["min_days"] and coins >= S["min_coins"]
    gates["выборка (дни, монеты)"] = ok2
    say(f"[{'✅' if ok else '❌'}] ОХВАТ: монет кандидата в плюсе {sc.get('cov', 0):.0f}% (нужно ≥{S['cov_share']:.0%})")
    say(f"[{'✅' if ok2 else '❌'}] ВЫБОРКА: {sc['n']} сделок на {days} днях, {coins} монет "
        f"(нужно ≥{S['min_days']} дней, ≥{S['min_coins']} монет)")

    # «без лучших дней» — хрупкость по ДНЯМ, как «без лучших 10%» по сделкам. Урок 07.10: дневная
    # перепроданность WT дала Δ +2.80 по сделкам и +0.66 при равном весе дней — эффект держали
    # несколько дней капитуляции. Убираем ВСЕ сделки k лучших дней кандидата и смотрим, что осталось.
    k = max(3, int(np.ceil(days * S["top_days_share"])))
    top = D[m].groupby("day").pnl.sum().nlargest(k).index
    keep = ~D.day.isin(top).values
    a, b = p[m & keep], p[~m & keep]
    ok = len(a) >= S["min_slice"] and a.mean() > 0 and a.mean() > b.mean()
    gates["без лучших дней"] = ok
    dm = D.assign(c=m).groupby(["day", "c"]).pnl.mean().unstack()
    dw = dm[True].mean() - dm[False].mean() if True in dm and False in dm else np.nan
    say(f"[{'✅' if ok else '❌'}] БЕЗ {k} ЛУЧШИХ ДНЕЙ: кандидат {a.mean() if len(a) else np.nan:+.2f}% (n={len(a)}) · "
        f"остальные {b.mean() if len(b) else np.nan:+.2f}% · справочно Δ при равном весе дней {dw:+.2f}")

    # 7. ликвидность
    if "liq" in D.columns and D.liq.notna().any():
        hi = (D.liq >= D.liq.median()).values
        res = []
        for nm, h in (("ликвидная ½", hi), ("неликвидная ½", ~hi)):
            a, b = p[h & m], p[h & ~m]
            if len(a) >= S["min_slice"] and len(b) >= S["min_slice"]:
                res.append(a.mean() > b.mean())
                L.append(f"      {nm}: кандидат {a.mean():+6.2f}% (n={len(a)}) · остальные {b.mean():+6.2f}% (n={len(b)})")
        ok = bool(res) and all(res)
        gates["обе половины ликвидности"] = ok
        L.insert(len(L) - len(res), f"[{'✅' if ok else '❌'}] ЛИКВИДНОСТЬ: кандидат лучше в обеих половинах")
    else:
        missing.append("ликвидность (нет колонки liq)")

    # 8. перекрытие повторных входов
    if "exit_ts" in D.columns and D.exit_ts.notna().any():
        keep = np.zeros(len(D), bool)
        C = D[m].sort_values(["sym", "ts"])
        last = {}
        for i, s, t, e in zip(C.index, C.sym, C.ts, C.exit_ts):
            if s not in last or t >= last[s]:
                keep[i] = True
                last[s] = e if pd.notna(e) else t
        a = p[keep]
        ok = len(a) >= S["min_slice"] and a.mean() > 0 and a.mean() > sr["mean"]
        gates["без перекрытия"] = ok
        say(f"[{'✅' if ok else '❌'}] БЕЗ ПЕРЕКРЫТИЯ: одна позиция на монету — {len(a)} из {sc['n']} · "
            f"средн {a.mean():+.2f}%")
    else:
        missing.append("перекрытие повторных входов (нет exit_ts)")

    # срезы без гейта
    say("\n  срезы (без гейта):")
    if D.side.nunique() > 1:
        for s_, g in D.groupby("side"):
            a, b = g.pnl[m[g.index]], g.pnl[~m[g.index]]
            if len(a):
                warn = "  ⚠️ сторона в минусе" if len(a) >= 30 and a.mean() < 0 else ""
                say(f"      {s_}: кандидат {a.mean():+6.2f}% (n={len(a)}) · остальные "
                    f"{b.mean() if len(b) else np.nan:+6.2f}% (n={len(b)}){warn}")
    per_day = D[m].groupby("day").pnl.transform("size")
    single = per_day.values == 1
    pc = p[m]
    say(f"      одиночка (1 сделка кандидата в день) {pc[single].mean() if single.any() else np.nan:+6.2f}% "
        f"(n={single.sum()}) · кластер ≥2 {pc[~single].mean() if (~single).any() else np.nan:+6.2f}% (n={(~single).sum()})")
    if "entry_type" in D.columns:
        for t_, g in D[m].groupby("entry_type"):
            say(f"      вход {t_}: {g.pnl.mean():+6.2f}% (n={len(g)})")
    else:
        missing.append("тип входа market/limit (нет entry_type)")

    # журнал, N, отложенный кусок
    prev = _journal_read()
    same = {(r.get("study"), r.get("name")) for r in prev if r.get("fp") == fp}
    same.add((study, name))
    if holdout and any(r.get("fp") == fp and r.get("name") == name and r.get("holdout") for r in prev):
        say("🔴 ОТЛОЖЕННЫЙ КУСОК С ЭТОЙ ГИПОТЕЗОЙ УЖЕ ОТКРЫВАЛСЯ — результат не независим")
        gates["отложенный кусок открыт впервые"] = False
    say(f"\n  гипотез на этом наборе за всё время: {len(same)} → случайных «прошло» ожидается "
        f"~{len(same) * S['alpha']:.1f} (по P одного гейта)")

    passed = all(gates.values())
    failed = [k for k, v in gates.items() if not v]
    say(f"\n  ИТОГ ЯРУСА 1: {'✅ ПРОШЁЛ' if passed else '❌ НЕ ПРОШЁЛ — ' + ', '.join(failed)}")
    say("  НЕ проверено: " + "; ".join(missing + ["ярус 2: нулевая модель всего поиска"] + list(TIER3)))
    out = dict(name=name, study=study, fp=fp, passed=passed, gates=gates, failed=failed,
               missing=missing, n=sc["n"], mean=sc["mean"], delta=obs, p=pv, text="\n".join(L))
    if journal:
        _journal_write(dict(ts=datetime.now(timezone.utc).isoformat(), tier=1, study=study, name=name,
                            fp=fp, n=sc["n"], mean=round(sc["mean"], 4), delta=round(obs, 4),
                            p=round(pv, 4), passed=passed, failed=failed, holdout=holdout))
    if not quiet:
        print(out["text"])
    return out


# ─────────────────────────────── ярус 2 ───────────────────────────────

def search_null(D: pd.DataFrame, search, *, name: str, study: str, n: int = 200,
                spec: dict | None = None, journal: bool = True) -> dict:
    """Нулевая модель ВСЕГО поиска. `search(pnl: np.ndarray) -> (метка, счёт)` перебирает свои
    гипотезы на исходах `pnl` (порядок строк D) и возвращает лучшую. Прогоняем на настоящих исходах
    и на n сдвинутых во времени: лучший настоящий обязан быть выше 95-го перцентиля лучших «мусорных»."""
    S = {**SPEC, **(spec or {})}
    rng = np.random.default_rng(S["seed"] + 1)
    groups = _year_groups(D)
    p = D.pnl.values
    lab, real = search(p)
    best = np.asarray([search(_shifted(p, groups, rng))[1] for _ in range(n)])
    pv = (np.sum(best >= real) + 1) / (n + 1)
    ok = pv < S["alpha"]
    txt = (f"ЯРУС 2 · {study} · {name}: лучший настоящий «{lab}» счёт {real:+.3f} · лучшие на мусоре: "
           f"медиана {np.median(best):+.3f}, 95-й {np.percentile(best, 95):+.3f}, макс {best.max():+.3f} · "
           f"P {pv:.3f} → {'✅ поиск нашёл больше, чем находит на мусоре' if ok else '❌ такое поиск находит и на мусоре'}")
    print(txt)
    if journal:
        _journal_write(dict(ts=datetime.now(timezone.utc).isoformat(), tier=2, study=study, name=name,
                            fp=fingerprint(D), best=lab, score=round(float(real), 4), p=round(pv, 4), passed=ok))
    return dict(name=name, best=lab, score=real, p=pv, passed=ok, null=best, text=txt)


def save_md(cards: list[dict], path: str | Path, title: str, description: str) -> None:
    """Карточки → файл obsidian/Research (сырые данные вердикта)."""
    today = datetime.now().strftime("%Y-%m-%d")
    body = [f"---\ntitle: \"{title}\"\ndescription: \"{description}\"\n"
            f"tags: ['type/research', '#area/strategy', '#role/dev']\ntype: research\n"
            f"parent: \"[[Project-MOC]]\"\nmonth: \"[[Months/{today[:7]}]]\"\ncreated: {today}\n---\n",
            f"# {title}\n", "Сгенерировано `scripts/research_verify.py`.\n"]
    for c in cards:
        body.append("```\n" + c["text"] + "\n```\n")
    Path(path).write_text("\n".join(body), encoding="utf-8")
