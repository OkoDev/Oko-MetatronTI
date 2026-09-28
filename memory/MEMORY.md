> 🔴 **ЭТО НЕ ИНДЕКС ПАМЯТИ.** Горячий индекс (законы измерения, что в бою, состояние поиска
> эджа) живёт в auto-memory: `~/.claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory/MEMORY.md`
> — он подгружается в контекст сам. Здесь, в repo-слое (git, читает DS), только SHARED-правила
> ролей. Архитектура памяти описана в шапке `memory/current_state.md`. Помечено 29.09.2026,
> когда выяснилось, что CLAUDE.md п.4 отправлял читать при старте сессии именно этот файл.

## 🧊 ЗАМОРОЖЕНО (планы от 30.06.2026, к исполнению НЕ принимать без решения Егора)
Оба пункта — планы, а не факты; в индексе auto-memory направления GAMMA / LIQUIDATION / PAIRS
стоят как **заморожены**. Оставлено как история намерения.

- **THE GRAPH MCP** → [план](the_graph_onchain_plan.md): 6-й канал (whale tracking, DEX liquidity
  surge, contract stress, funding+whale divergence, new pools). Заявленный WR 55-70% — ОЦЕНКА из
  плана, не наш замер.
- **5 EDGE-СТРАТЕГИЙ от роя** → [вердикт team-ask](new_edge_strategies_team_verdict.md): Gamma
  Scalping, Liquidation Cascades, Pairs Trading, Delta Footprint, Epsilon Arb.

## 🔴 MACRO-REVIEW — правило DS (16.06.2026)

1. Каждые 14 дней (понедельник) — плановый макро-обзор рынка.
2. При значимых новостях (FOMC, MiCA-дедлайны, ETF-рекорды, BTC>8%/день) — внеочередной.
3. Процедура:
   - `python scripts/macro_review.py --dry-run` → проверить расписание
   - `python scripts/macro_review.py` → создать шаблон в `obsidian/Macro-Analysis/`
   - WebSearch (ФРС, MiCA, ETF, CryptoQuant) + vault-recall obsidian
   - Заполнить шаблон экспертным анализом
   - Записать в DISCUSSION → DS (краткий дайджест команде)
4. Интеграция в Куб: Сфера 5 (Cross-Market Node) — макро-контекст для всех позиций.
   Сейчас Сфера 5 только «BTC 4h режим». Цель: полный макро-слой (ставки, ликвидность, регуляция).
   Связано: BACKLOG #19 (Capital Allocator), #11 (Risk Monitor).
5. Файлы: `obsidian/Macro-Analysis/` (обзоры) + MOC + `.macro_config.json` (расписание).

## DS SELF-CHECK (13.06)

1. ПЕРЕД утверждением «стратегия X убыточна» — проверить последние N дней.
   Провал: atr_change назвал убыточной, а она уже +0.10 avgR.

2. ПЕРЕД «нужно сделать Y» — grep код: возможно уже сделано.
   Провал: OTE-конверсию назвал «нужно», а DEV-209 уже в коде.

3. ПЕРЕД «SL не работает» — проверить tsl_activated колонку.
   TSL спасает ×2.4 для ote_nested, игнорировал в ранних выводах.

4. Данные за ALL TIME ≠ данные за последние 3 дня.
   Система меняется быстро. Всегда брать свежий срез.

