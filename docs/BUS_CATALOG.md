# 📖 BUS-CATALOG — меню данных шины (PairContextBus)

> Авто-генерация из `core/context/bus_catalog.py`. Поля — из dataclass (не дрейфнут).
> Пришёл → выбрал «провод» (подписка/чтение) → подключился. Не ищи по коду.

## 🔔 СОБЫТИЯ (PUSH — реакция). `bus.subscribe_async(SphereEvent.X, handler)`

| Событие | Payload | Источник | Описание |
|---|---|---|---|
| `OHLCV_UPDATED` | `{tf,rows,close}` | scan_loop (Сфера 1) | обновление свечей + текущая цена |
| `TICK_PRICE` | `{price,volume_24h}` | WsFeed (Сфера 2) | тик цены (если WsFeed on) |
| `VOLUME_SPIKE` | `{ratio,tf}` | scan_loop (Сфера 2) | всплеск объёма |
| `WT_VERDICT` | `{label,confidence,features}` | scan_loop (Сфера 3) | вердикт WT |
| `WT_SNAP_UPDATED` | `{tf:{wt1,wt2,zone,cross,atr_trend}}` | scan_loop (Сфера 3) | снимок WT |
| `SMC_VERDICT` | `{label,confidence}` | sub_cube (Сфера 4) | вердикт SMC |
| `SMC_SNAP_UPDATED` | `{tf:{ob,fvg,choch,bos,..}}` | sub_cube (Сфера 4) | снимок SMC (магниты TP, NOTIF) |
| `CROSS_MARKET` | `{btc_regime,btc_move_pct,direction}` | scan_loop (Сфера 5) | контекст BTC |
| `REGIME_UPDATED` | `{regime,mode}` | scan_loop (Сфера 6) | режим рынка |
| `SIGNAL_DETECTED` | `{signal_type,direction,strength,tf}` | scan_loop (Сфера 7) | сигнал детектора |
| `ANOMALY_DETECTED` | `{volume_ratio,tf}` | scan_loop (Сфера 7) | аномалия |
| `DIVERGENCE_FOUND` | `{type,direction,tf,strength}` | scan_loop (Сфера 7) | дивергенция |
| `PIVOT_TOUCH` | `{level,source,distance_pct}` | scan_loop (Сфера 7) | касание пивота |
| `PIVOT_SNAP_UPDATED` | `{1W:{..},1D:{..}}` | scan_loop (Сфера 8) | снимок пивотов |
| `NARRATIVE_BUILT` | `{text,action,p_win,key_factors}` | trading_intelligence (Сфера 9) | нарратив решения |
| `POSITION_OPENED` | `{side,source,trade_id,final_strength,regime}` | trade_router (Сфера 9) | сделка открыта |
| `POSITION_DROPPED` | `{side,source,hard_drops,strength,regime}` | trade_router (Сфера 9) | сделка отклонена гейтом |
| `TSL_MOVED` | `{trade_id,old_sl,new_sl,tf}` | trade_simulator (Сфера 10) | TSL сдвинут |
| `TP1_HIT` | `{trade_id,r_at_tp1}` | trade_simulator (Сфера 10) | TP1 достигнут |
| `POSITION_CLOSED` | `{trade_id,status,r_multiple}` | trade_simulator (Сфера 10) | позиция закрыта |
| `TRADE_CLOSED` | `{status,r_multiple,direction,signal_type}` | trade_simulator (Сфера 11) | сделка закрыта (учёт) |
| `CASCADE_UPDATED` | `{cascade_count,avg_r,direction}` | trade_simulator (Сфера 11) | обновление каскада |
| `OTE_ZONE_SET` | `{ote_top,ote_bot,direction,ttl_hours}` | ote_observer (Сфера 11) | OTE-зона установлена |
| `SPHERE_HEALTH` | `{sphere_id,status,last_update}` | sphere_registry (Сфера 12) | здоровье сферы |

## 🅛1 PAIR STATE (PULL — состояние пары). `bus.get(sym).<поле>`

| Поле | Тип | Источник | Описание |
|---|---|---|---|
| `last_ohlcv_time` | Optional[datetime] | scan_loop (Сфера 1) | когда обновлялись свечи |
| `ohlcv_tfs_loaded` | List[str] | scan_loop (Сфера 1) | какие TF загружены |
| `tick_price` | Optional[float] | WsFeed / scan_loop (OHLCV close) | текущая цена пары |
| `tick_time` | Optional[datetime] | WsFeed / scan_loop | время последнего тика |
| `wt_verdict` | Optional[str] | scan_loop (Сфера 3) | TREND_CONTINUATION/REVERSAL_SETUP/EXHAUSTION |
| `wt_confidence` | float | scan_loop (Сфера 3) | уверенность WT-вердикта 0..1 |
| `wt_snap` | Optional[Dict[str, Any]] | scan_loop (Сфера 3) | {tf: {wt1,wt2,zone,cross,atr_trend}} |
| `smc_verdict` | Optional[str] | sub_cube (Сфера 4) | STRONG_BULL_ZONE/WEAK_ZONE/STRONG_BEAR_ZONE |
| `smc_confidence` | float | sub_cube (Сфера 4) | уверенность SMC 0..1 |
| `smc_snap` | Optional[Dict[str, Any]] | sub_cube (Сфера 4) | {tf: {ob_bull,fvg_open,choch,bos,...}} — магниты TP |
| `btc_regime` | Optional[str] | scan_loop (Сфера 5) | режим BTC TREND_UP/DOWN/RANGE/HIGH_VOL |
| `btc_move_pct` | float | scan_loop (Сфера 5) | движение BTC % |
| `cross_market_time` | Optional[datetime] | scan_loop (Сфера 5) | время cross-market снимка |
| `regime` | Optional[str] | scan_loop (Сфера 6) | режим пары TREND_UP/DOWN/RANGE/HIGH_VOL |
| `reversal_mode` | Optional[str] | scan_loop (Сфера 6) | TREND/REVERSAL/UNCLEAR |
| `sideways_bars` | int | scan_loop (Сфера 6) | счётчик RANGE-циклов подряд |
| `sideways_mode_active` | bool | scan_loop (Сфера 6) | sideways_bars >= порог |
| `last_signal_type` | Optional[str] | scan_loop (Сфера 7) | тип последнего сигнала |
| `last_signal_direction` | Optional[str] | scan_loop (Сфера 7) | LONG/SHORT |
| `last_signal_strength` | float | scan_loop (Сфера 7) | сила сигнала |
| `last_signal_time` | Optional[datetime] | scan_loop (Сфера 7) | время сигнала |
| `active_divergence` | Optional[Dict] | scan_loop (Сфера 7) | активная дивергенция {type,direction,tf,strength} |
| `anomaly_active` | bool | scan_loop (Сфера 7) | аномалия объёма активна |
| `ote_ltf_status` | Optional[str] | ote_observer | ARMED/FIRE/None — статус 5m OTE-сетапа |
| `ote_ltf_score` | int | ote_observer | набрано подтверждений |
| `ote_ltf_min` | int | ote_observer | порог подтверждений для FIRE |
| `ote_ltf_direction` | Optional[str] | ote_observer | long/short |
| `ote_ltf_trigger` | Optional[str] | ote_observer | FVG/OB/EQL/SC |
| `ote_ltf_entry` | Optional[float] | ote_observer | цена входа |
| `ote_ltf_sl` | Optional[float] | ote_observer | стоп-лосс |
| `ote_ltf_tp1` | Optional[float] | ote_observer | частичный +1R |
| `ote_ltf_tp` | Optional[float] | ote_observer | финальная цель (runner) |
| `ote_ltf_setup` | Optional[str] | ote_observer | setup_id из шкафа |
| `ote_ltf_time` | Optional[datetime] | ote_observer | время OTE-снимка |
| `watchlist` | Dict[str, Dict[str, Any]] | bus.set_watchlist() из любой стратегии | {стратегия: {entry, potential_pct, ...}} — заявки стратегий на пару |
| `pivot_snap` | Optional[Dict[str, Any]] | scan_loop (Сфера 8) | {1W:{PP,S1,R1,..},1D:{..}} |
| `near_pivot` | Optional[Dict] | scan_loop (Сфера 8) | {level,source,distance_pct} |
| `last_narrative` | Optional[str] | trading_intelligence (Сфера 9) | текст нарратива |
| `last_narrative_time` | Optional[datetime] | trading_intelligence (Сфера 9) | время нарратива |
| `last_p_win` | float | trading_intelligence (Сфера 9) | P(win) ML 0..1 |
| `open_trade_id` | Optional[int] | trade_simulator (Сфера 10) | id открытой сделки |
| `tsl_active` | bool | trade_simulator (Сфера 10) | TSL активен |
| `tp1_hit` | bool | trade_simulator (Сфера 10) | TP1 достигнут |
| `cascade_count` | int | trade_simulator (Сфера 11) | длина каскада |
| `last_direction` | Optional[str] | trade_simulator (Сфера 11) | направление последней сделки |
| `last_close_status` | Optional[str] | trade_simulator (Сфера 11) | TP/SL/TSL/EXPIRED |
| `last_close_time` | Optional[datetime] | trade_simulator (Сфера 11) | время закрытия |
| `avg_r_cascade` | float | trade_simulator (Сфера 11) | средний R каскада |
| `post_tsl_data` | Optional[dict] | trade_simulator (Сфера 11) | данные post-TSL |
| `sl_streak_count` | int | gates (ARCH-88) | серия SL подряд |
| `last_n_outcomes` | Deque[str] | gates (ARCH-88) | последние 10 исходов (deque) |
| `pair_avg_r_last_20` | float | gates (ARCH-88) | avg R последних 20 сделок пары |
| `last_sl_at` | Optional[datetime] | gates (ARCH-88) | время последнего SL |
| `pair_cooldown_until` | Optional[datetime] | gates (ARCH-88) | пара заблокирована до |
| `last_narrative_outcome` | Optional[dict] | trade_simulator (ARCH-91) | {status,R,lost_reason,closed_at} |
| `spheres_ok` | int | sphere_registry (Сфера 12) | сколько сфер живы за час |
| `last_diagnostic_time` | Optional[datetime] | sphere_registry (Сфера 12) | время диагностики |

## 🅛2 ACCOUNT STATE (PULL — портфель). `bus.get_account(id).<поле>`

| Поле | Тип | Источник | Доступ | Описание |
|---|---|---|---|---|
| `account_id` | int | — | `bus.get_account(id).account_id` | id аккаунта (1/2) |
| `equity` | float | EXEC-WS ACCOUNT_UPDATE (wb) | `bus.get_account(id).equity` | баланс счёта (живой push). total → bus.total_equity() |
| `available` | Optional[float] | position_sync / REST | `bus.get_account(id).available` | доступная маржа |
| `used_margin` | Optional[float] | position_sync / REST | `bus.get_account(id).used_margin` | занятая маржа |
| `positions` | Dict[str, dict] | EXEC-WS + position_sync | `bus.all_positions()` | {sym: {qty,side,entry,upnl,leverage,mark}} → bus.all_positions() |
| `updated_at` | Optional[datetime] | EXEC-WS / position_sync | `bus.get_account(id).updated_at` | время обновления счёта |

---
**Покрытие:** события 24 · L1 57 · L2 6.
✅ Каталог в синхроне с dataclass.