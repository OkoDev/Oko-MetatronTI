---
name: perf_loop_drift_b_done
description: PERF-LOOP-DRIFT эпик B завершён (торговый loop изолирован) + XMP=корень BSOD + 531 пара даёт баны direct IP
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**PERF-LOOP-DRIFT — эпик B ЗАВЕРШЁН (13.06.2026).** Изоляция торгового пути в отдельный event loop (отдельный поток) → торговый rtt не зависит от scan-нагрузки.

**Коммиты:** 4248df1 (шаг0 GlobalRateLimiter→threading loop-agnostic) → 4d403ef (шаг1 trading_loop за флагом) → 9f71839 (шаг2 HTTP-routing BingXClient, БЕЗ очереди — DB-write остаётся в main) → c69572f (активация dedicated_loop=true + health-ping через торговый loop). План: `docs/PLAN_PERF_LOOP_DRIFT_B.md`.

**Результат (доказано на 199→278→531 паре):** торговый rtt median 255-394ms (было 9-16с пики), timestamp invalid 90/час→0, cross-loop ошибок 0, SL/bracket ставятся. B держит rtt при любом масштабе (даже total=1850 задач на loop). Флаг `trading.dedicated_loop=true`. Откат: false.

**🔑 XMP = КОРЕНЬ BSOD (не бот, не CPU/тепло).** При стресс-тесте 531 пара комп дважды упал в BSOD (DPC_WATCHDOG_VIOLATION + REFERENCE_BY_POINTER). Корень — **нестабильный XMP** (разгон памяти Patriot 3200 на старом BIOS ASUS TUF X299 MARK 2 0802/2017) под I/O-нагрузкой бота. REFERENCE_BY_POINTER 0x18 = классика memory corruption. Юзер выключил XMP + выдернул 2-ю GPU → бот держит 531 пару 42 мин без падений. **Оставить XMP OFF** (стабильность > скорость). Вернуть разгон — только после обновления BIOS.

**Железо юзера:** i7-7820X (8/16, X299, BIOS 0802/2017 ОЧЕНЬ старый), 32GB DDR4 Patriot 3200, GTX 1080, NVMe Samsung 960 EVO. Windows 11 22H2, Hyper-V+HVCI активны. **WireGuard FULL TUNNEL** (0.0.0.0/0) — весь трафик (Claude+бот) через VPN (РФ→Claude только через VPN). Субоптимально (бот тысячи соединений через túннель), но работает; split tunnel — на досуге.

**531 пара (гейт min_volume_usd=0) даёт ~16 банов 100410/час** (предел direct IP, не железа) — GlobalRateLimiter (threading, шаг0) гасит 5с-паузами cross-loop. Оптимум по банам ~200-278 пар (0 банов). Текущий гейт=0 (юзер выбрал полный масштаб).

**Осталось (backlog):** шаг4 EXEC-WS (orders=0/account=0 — приходят только SNAPSHOT, listenKey вне IP-бюджета; доработка для real-time sync). health-ping теперь через торговый loop (мерит реальную доступность), но под repair-нагрузкой торгового loop даёт 2-3с (DEGRADED-шум). [[exec_ws_vst_userdata_proven]]
