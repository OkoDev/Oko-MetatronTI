---
name: principle_log_signal_components
description: ПРИНЦИП (юзер 18.06) — каждая составная стратегия ДОЛЖНА логировать сработавшие компоненты в features → обучающий контур. Иначе слепое пятно
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 01a80823-46cc-4251-9bdf-bf45da105c68
---

🧬 **ПРИНЦИП: составная стратегия логирует свои компоненты в features.**

**Why:** без лога «какие подтверждения/компоненты реально сработали» нельзя из БД измерить, что несёт edge, а что шум → слепое пятно (ote не логировал confirmations → 0 способов проверить «лучше ли ote с div»). Юзер 18.06: «и так должно быть для ВСЕХ составных стратегий».

**How to apply:** при register_trade в `extra_features` класть сработавшие компоненты строкой (SQL-friendly, как `ote_trigger="FVG+OB+SC"`) + счётчик.

**Состояние (18.06):**
- ote_nested: ✅ добавлено `ote_confirmations` (div/fvg_held/vol/liq_sweep/wt_cross/atr) + `ote_conf_score` (ote_observer_loop ~282, из `OTESignal.confirmations`). НЕ закоммичено.
- atr_change: ✅ уже было — `confirmations` + `strength_breakdown` + волна `elliott_n_down/up` (scan_loop ~1036). ЭТАЛОН.
- arch104: ✅ `arch104_matched_patterns` (компоненты), ❌ НЕ видит волну → дать `elliott_n_down/up` ([[signal_health_map_18jun]] TODO).

**✅ ТЕХДОЛГ ЗАКРЫТ (18.06):** унифицированы имена волны → `elliott_n_down/up` везде (коммит `bdf36f8`: ote phase_nd/nu→elliott_*; phase_gate_* остались=ote-гейт). arch104 дана волна (`de92b88`, из `bot._elliott_snap`). Теперь все составные стратегии говорят на одном языке волны. ⚠️ разрыв истории: старые ote-сделки несут phase_* → анализы `COALESCE(elliott_n_down, phase_nd_4h)`.

Связь: [[ote_tight_sl_validated]], [[bug_phantom_exit_resolve]], [[signal_health_map_18jun]].
