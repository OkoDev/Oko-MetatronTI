---
name: cutover_blocker_ws_closefill
description: "CUTOVER не флипать — «?» застрял 75%, корень=WS close-fill o.rp ловится лишь 25%. Эпик A = починить захват. B (P&L-fallback) отклонён"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0b9885d0-84da-4125-92df-2c24b01a41a7
---

# CUTOVER-блокер: WS close-fill capture ~25% (21.06.2026)

**Решение юзера 21.06: ПАУЗА, путь A на будущее. B (флип с P&L-fallback) отклонён.**

## Замер «?»-rate (post BE/TSL-фикс)
WOULD CLOSE «?» **застрял ~75%** по часам (20:00→76%, 00:00→76% МСК). Гипотеза «BE-фикс→чистые SL-fill→«?» вниз» ОПРОВЕРГНУТА — не падает.

## Корень (подтверждён)
`sphere.py on_event` (99-118): pa=0 → `take_exit` (застешенный WS close-fill o.rp) → если None → `_resolve_exit_via_rest` (REST). «?» = ОБА не дали. rp приходит ТОЛЬКО из WS closing-fill ExitInfo, застешивается **~25%**. Резолв (SOPH/INX/THETA/MANA SL с rp) = fill пойман; «?» = гонка fill↔pa=0 + one-click закрытия (hedge 101205 [[hedge_close_multiacct_root]]) чей fill не мапится по positionId. pid_resolver МООТ (backfill ставит pid; не он горло).

## Почему B (P&L-fallback) отклонён
Флип СЕЙЧАС без fallback = `db_writer.intent_to_close_args` возвращает None на «?» → сделка НЕ закрывается → **75% орфанов** (старый путь 2b под CUTOVER выключен, exec_ws:181). С P&L-fallback (reuse position_sync:636) флипабельно, НО: 25% получают честный o.rp, 75% = тот же P&L что старый path (паритет) → **немедленный приз только 25%** за цену живого close-path флипа (риск орфанов) + copy-DB тест. Не стоит ради 25%.

## Путь A (истинный unlock, на будущее)
Починить **WS close-fill capture** чтобы o.rp ловился ~100% (не 25%):
- Гонка fill↔pa=0: закрывающий ORDER_TRADE_UPDATE приходит ПОСЛЕ pa=0 → ExitInfo не застешен. Нужно: буфер/ретрай стеша, или дождаться fill перед close-триггером.
- one-click закрытия (101205): bot закрывает reduceOnly в hedge → fail → one-click, чей fill не несёт positionId → не мапится. Корень one-click = routing/mode ([[hedge_close_multiacct_root]]). Починить close чтобы НЕ падал в one-click → fill мапится.
Когда o.rp% растёт → CUTOVER (даже с тем же flag) автоматически честнее. ТОГДА флип осмыслен.

## 🟢 ОБНОВЛЕНИЕ 22.06: захват вырос 25%→65% (прогресс пути A)
Свежий замер shadow-логов (334 WOULD CLOSE): **o.rp захвачен 65% (218), «?» 35% (116)** — все остаток `reason=ws_pa0`. Было 25% (21.06) → 65% (22.06): больше fill ловится (+ `_resolve_exit_via_rest` есть в sphere). Флип сейчас = 35% орфанов (лучше 75%, но много).
**Остаток 35% = pa=0 БЕЗ застешённого fill И REST-резолв не дал** (after positionID-ужесточение [[bug_phantom_exit_resolve]] — _resolve_exit_via_rest требует pid → меньше ложных, но больше «?»).
**🔑 ПУТЬ разблокировки (инфра ЕСТЬ, reuse):** `get_income(start_ms,end_ms)` (bingx_client:533, order_manager:303) = income-ledger $-истина.

## ✅ РЕАЛИЗОВАНО 22.06 — income-fallback (3-й уровень close-resolve)
`sphere.on_event`: take_exit None → `_resolve_exit_via_rest`(pid) None → **`_resolve_exit_via_income`** (НОВЫЙ, sphere.py): `adapter.get_income(symbol,account,now-5min,now)` → realized из income-ledger (REALIZED_PNL+INSURANCE_CLEAR), exit_price восстановлен из realized+entry+qty. Файлы: `adapter.py` (abstract get_income), `bingx_adapter.py` (reuse cli.get_income, норм symbol), `sphere.py` (_resolve_exit_via_income). Тест `test_income_fallback_when_fill_and_rest_empty` ✅ **26/26 passed**. order_type='INCOME_FALLBACK'.
**Ожидание:** после РЕСТАРТА в shadow-логах `WOULD CLOSE rp=?` (35%) упадёт → захват ~65%→~100% (income всегда есть). Когда зелёная shadow-сверка → флип `sphere_cutover:true` (+copy-DB тест). Income не даёт exit-цену → восстановлена из realized (для R; realized=факт-истина).

## Пока CUTOVER в shadow — метрики не слепые
Старый position_sync реклассифицирует EXPIRED→P&L (стр.636); $-истина = income-ledger `o.rp`/`/user/income` ([[income_ledger_db_overstates_realized]]). Связь: [[exec_ws_vst_userdata_proven]] [[exec_sim_split_epic]] [[bug_phantom_exit_resolve]]
