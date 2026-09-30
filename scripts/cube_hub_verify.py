"""
cube_hub_verify.py — критерий шага 1 ADR-003: доска хаба = доска бота.

Состояние пары меняется непрерывно, поэтому «расхождение» = поле, которое у бота НЕ менялось между двумя
чтениями с интервалом дольше полного круга досыла (35 с), а в хабе после этого всё ещё другое.
Сравниваются ключи бота (`/api/cube/context/{sym}` = get_full_state); хаб хранит надмножество.
Печатает также сводку хаба: разрывы seq, задержка p50/p95.

    python scripts/cube_hub_verify.py [--sample 150] [--wait 35]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from collections import Counter

BOT = "http://127.0.0.1:8000/api/cube"
HUB = "http://127.0.0.1:8020"


def _get(url: str):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def _norm(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=150)
    ap.add_argument("--wait", type=float, default=35.0)
    a = ap.parse_args()

    hub_syms = list(_get(f"{HUB}/state")["coins"].keys())
    bot_syms = list(_get(f"{BOT}/snapshot_all")["coins"].keys())
    missing = sorted(set(bot_syms) - set(hub_syms))
    print(f"пар: бот {len(bot_syms)} · хаб {len(hub_syms)} · нет в хабе {len(missing)} {missing[:5]}")
    syms = random.Random(1).sample(sorted(set(bot_syms) & set(hub_syms)),
                                   min(a.sample, len(set(bot_syms) & set(hub_syms))))

    def bot_state(s):
        return _get(f"{BOT}/context/{s.replace('/', '_').replace(':USDT', '')}")

    b1 = {s: bot_state(s) for s in syms}
    time.sleep(a.wait)
    # по каждой паре подряд: бот → хаб → бот. Последовательное чтение «все у бота, потом все у хаба»
    # давало гонку: скан успевал обновить пару между чтениями, и хаб оказывался НОВЕЕ (30.09, 300 пар).
    b2, h2, b3 = {}, {}, {}
    for s in syms:
        b2[s] = bot_state(s)
        h2[s] = _get(f"{HUB}/state/{s.replace('/', '_').replace(':USDT', '')}")
        b3[s] = bot_state(s)

    bad = Counter(); stable = 0; examples = []
    for s in syms:
        for k, v2 in b2[s].items():
            if _norm(b1[s].get(k)) != _norm(v2) or _norm(b3[s].get(k)) != _norm(v2):
                continue                                  # поле у бота менялось — сравнивать нечестно
            stable += 1
            if _norm(h2[s].get(k)) != _norm(v2):
                bad[k] += 1
                if len(examples) < 5:
                    examples.append((s, k, str(v2)[:60], str(h2[s].get(k))[:60]))
    print(f"стабильных полей сверено: {stable} на {len(syms)} парах · расхождений: {sum(bad.values())}")
    for k, n in bad.most_common(10):
        print(f"   {k}: {n}")
    for e in examples:
        print("   пример:", e)
    st = _get(f"{HUB}/stats")
    p = st["producers"].get("oko-bot", {})
    print(f"хаб: состояний {st['states']} · возраст p50 {st['state_age_p50']} с, макс {st['state_age_max']} с · "
          f"фактов {st['facts']}")
    print(f"   задержка состояние p50/p95 {st['latency_state_p50']}/{st['latency_state_p95']} с · "
          f"факт p50/p95 {st['latency_fact_p50']}/{st['latency_fact_p95']} с")
    print(f"   oko-bot: элементов {p.get('items')} · разрывов seq {p.get('gaps')} · потеряно {p.get('lost')} · "
          f"рестартов {p.get('restarts')} · битых {st['bad_items']}")


if __name__ == "__main__":
    main()
