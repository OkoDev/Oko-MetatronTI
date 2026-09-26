"""
Аудит чистоты данных в simulated_trades + features_json.

Что проверяет (все искажения D1):
  B2: status='SL' где реально был TSL exit (для VST скрытые TSL под маской SL)
  B3: stop_loss НЕ обновлялся в БД при движении TSL (для SIM)
  B4: be_activated пишется некорректно (особенно для SINGLE)
  B5: wt1_value на 15m, а wt_b детектор работает на 1h
  B6: distance_to_pivot_pct = TP distance, не entry-trigger pivot

Read-only. Бот может писать одновременно (retry).

Использование:
    python scripts/audit_data_integrity.py                    # post-fix (>=2026-04-15)
    python scripts/audit_data_integrity.py --since "2026-01-01"  # вся история
"""
import sqlite3
import sys
import json
import time
from pathlib import Path
from collections import defaultdict

DEFAULT_SINCE = "2026-04-15"
DB = Path(__file__).parent.parent / "subscriptions.db"


def open_db_with_retry(db_path, retries=10, delay=3):
    last_err = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(str(db_path), timeout=15)
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("SELECT 1").fetchone()
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if attempt < retries - 1:
                print(f"  [retry {attempt+1}/{retries}] DB busy: {e}, wait {delay}s...")
                time.sleep(delay)
    raise RuntimeError(f"DB open failed: {last_err}")


def parse_args():
    since = DEFAULT_SINCE
    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since = sys.argv[i + 1]
    return since


def section(title):
    print()
    print("=" * 75)
    print(title)
    print("=" * 75)


def main():
    since = parse_args()
    print(f"AUDIT DATA INTEGRITY — since {since}")

    conn = open_db_with_retry(DB)
    cur = conn.cursor()

    # -- Базовый счёт --
    cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE created_at >= ?", (since,))
    total = cur.fetchone()[0]
    cur.execute("""
        SELECT
          SUM(CASE WHEN exchange_order_id IS NOT NULL AND exchange_order_id != '' THEN 1 ELSE 0 END) vst,
          SUM(CASE WHEN exchange_order_id IS NULL OR exchange_order_id = '' THEN 1 ELSE 0 END) sim
        FROM simulated_trades WHERE created_at >= ?
    """, (since,))
    vst, sim = cur.fetchone()
    print(f"\nTotal: {total}  (VST: {vst}, SIM: {sim})")

    # ============================================================
    section("B2 — status='SL' где реально был TSL exit (VST)")
    # ============================================================
    print("Гипотеза: VST с tsl_activated=1 + status='SL' + R>0.1 = скрытый TSL exit")
    print()
    cur.execute("""
      WITH cls AS (
        SELECT id, R_multiple, status,
          CASE
            WHEN status='OPEN' THEN 'OPEN'
            WHEN status='TP' THEN 'TP'
            WHEN status='TSL' THEN 'TSL_native'
            WHEN status='SL' AND R_multiple > 0.1 THEN 'TSL_hidden_win'
            WHEN status='SL' AND R_multiple BETWEEN -0.2 AND 0.1 THEN 'BE_area'
            WHEN status='SL' AND R_multiple < -1.05 THEN 'SL_slipped'
            WHEN status='SL' THEN 'SL_clean'
            ELSE status
          END eff
        FROM simulated_trades
        WHERE tsl_activated=1
          AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
          AND created_at >= ?
      )
      SELECT eff, COUNT(*), ROUND(AVG(R_multiple),3) FROM cls GROUP BY eff ORDER BY 2 DESC
    """, (since,))
    print("  {:18s} {:>5s} {:>8s}".format('eff_status', 'n', 'avgR'))
    rows = cur.fetchall()
    closed = wins = hidden = 0
    for r in rows:
        print("  {:18s} {:>5d} {:>8}".format(r[0], r[1], r[2] if r[2] is not None else 0))
        if r[0] != 'OPEN':
            closed += r[1]
            if r[0] in ('TP','TSL_native','TSL_hidden_win'): wins += r[1]
            if r[0] == 'TSL_hidden_win': hidden = r[1]

    if closed > 0:
        print(f"\n  Чистота status: {hidden}/{closed} ({hidden/closed*100:.1f}%) сделок имеют 'SL' но фактически были TSL exit")
        if hidden / max(closed, 1) > 0.05:
            print(f"  ⚠️  ИСКАЖЕНИЕ: статистика 'WR' и 'avgR_SL' завышает потери")
            print(f"  🔧 РЕШЕНИЕ: DEV-190 effective_status helper в performance_engine + dashboard")

    # ============================================================
    section("B3 — stop_loss НЕ обновлялся в БД при TSL движении (SIM)")
    # ============================================================
    print("Гипотеза: для SIM (без exchange_order_id) UPDATE stop_loss блокируется")
    print()
    cur.execute("""
      SELECT
        SUM(CASE WHEN original_sl IS NULL THEN 1 ELSE 0 END) no_orig,
        SUM(CASE WHEN original_sl IS NOT NULL AND ABS(stop_loss - original_sl) < 1e-8 THEN 1 ELSE 0 END) not_moved,
        SUM(CASE WHEN original_sl IS NOT NULL AND ABS(stop_loss - original_sl) >= 1e-8 THEN 1 ELSE 0 END) moved,
        COUNT(*) total
      FROM simulated_trades
      WHERE tsl_activated=1
        AND (exchange_order_id IS NULL OR exchange_order_id = '')
        AND created_at >= ?
    """, (since,))
    r = cur.fetchone()
    print(f"  SIM tsl_activated=1: total={r[3]}")
    print(f"    no original_sl (старые): {r[0]}")
    print(f"    SL не двинулся в БД:     {r[1]}")
    print(f"    SL двинулся:             {r[2]}")

    measurable = (r[1] or 0) + (r[2] or 0)
    if measurable > 0:
        not_moved_pct = (r[1] or 0) / measurable * 100
        print(f"\n  Чистота stop_loss: {r[1]}/{measurable} ({not_moved_pct:.1f}%) SIM сделок не апдейтят БД")
        if not_moved_pct > 30:
            print(f"  ⚠️  ИСКАЖЕНИЕ: дашборд для SIM показывает прежний (не двинутый) SL")
            print(f"  🔧 РЕШЕНИЕ: DEV-189 фикс _is_real_move в trade_simulator.py:1980")

    # Симметрично для VST для контраста
    cur.execute("""
      SELECT
        SUM(CASE WHEN original_sl IS NOT NULL AND ABS(stop_loss - original_sl) < 1e-8 THEN 1 ELSE 0 END) not_moved,
        SUM(CASE WHEN original_sl IS NOT NULL AND ABS(stop_loss - original_sl) >= 1e-8 THEN 1 ELSE 0 END) moved
      FROM simulated_trades
      WHERE tsl_activated=1
        AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
        AND created_at >= ?
    """, (since,))
    rv = cur.fetchone()
    print(f"\n  Контроль (VST): not_moved={rv[0]}, moved={rv[1]} (для VST механика работает)")

    # ============================================================
    section("B4 — be_activated по strategy_type")
    # ============================================================
    print("Гипотеза: SINGLE strategy_type не имеет tp1 → use_be_after_tp1 не срабатывает")
    print()
    cur.execute("""
      SELECT COALESCE(strategy_type,'NULL') st,
             COUNT(*) total,
             SUM(CASE WHEN tsl_activated=1 THEN 1 ELSE 0 END) tsl_act,
             SUM(CASE WHEN be_activated=1 THEN 1 ELSE 0 END) be_act,
             SUM(CASE WHEN tp1_hit_at IS NOT NULL THEN 1 ELSE 0 END) tp1_hit
      FROM simulated_trades WHERE created_at >= ? GROUP BY st ORDER BY total DESC
    """, (since,))
    print("  {:12s} {:>5s} {:>7s} {:>5s} {:>7s}".format('strat', 'n', 'tsl_act', 'be', 'tp1'))
    for r in cur.fetchall():
        print("  {:12s} {:>5d} {:>7d} {:>5d} {:>7d}".format(*r))
    print()
    print("  Если strat=SINGLE, tsl_act>0, be=0 → BE невозможен по дизайну (B4)")
    print("  🔧 RE-AUDIT показал: SINGLE даёт лучший avgR — BE не нужен")

    # ============================================================
    section("B5 — wt1_value vs wt_snap['1h']['wt1'] для wt_b_signal")
    # ============================================================
    print("Гипотеза: wt1_value записывается из 15m, а детектор wt_b на 1h")
    print()
    cur.execute("""
      SELECT id, signal_type, features_json
      FROM simulated_trades
      WHERE signal_type='wt_b_signal' AND features_json IS NOT NULL
        AND created_at >= ?
      ORDER BY id DESC LIMIT 100
    """, (since,))
    rows = cur.fetchall()
    same_as_15m = 0
    same_as_1h = 0
    no_match = 0
    for r in rows:
        try:
            f = json.loads(r[2])
            wt1_val = f.get("wt1_value")
            wt_snap = f.get("wt_snap", {})
            wt1_15m = (wt_snap.get("15m") or {}).get("wt1")
            wt1_1h = (wt_snap.get("1h") or {}).get("wt1")
            if wt1_val is None: continue
            if wt1_15m is not None and abs(wt1_val - wt1_15m) < 0.5:
                same_as_15m += 1
            elif wt1_1h is not None and abs(wt1_val - wt1_1h) < 0.5:
                same_as_1h += 1
            else:
                no_match += 1
        except Exception: pass

    n_checked = same_as_15m + same_as_1h + no_match
    print(f"  Проверено wt_b сделок: {n_checked}")
    print(f"    wt1_value совпадает с wt_snap['15m']['wt1']: {same_as_15m}")
    print(f"    wt1_value совпадает с wt_snap['1h']['wt1']:  {same_as_1h}")
    print(f"    Не совпадает ни с тем ни с другим:           {no_match}")
    if n_checked > 0:
        wrong_pct = same_as_15m / n_checked * 100
        if wrong_pct > 50:
            print(f"\n  ⚠️  ИСКАЖЕНИЕ: {wrong_pct:.0f}% wt_b сделок имеют wt1_value на 15m (должно быть 1h)")
            print(f"  🔧 РЕШЕНИЕ: DEV-191 wt1_at_trigger_tf в features_json")
            print(f"  📝 ВРЕМЕННО: для аудита/ML wt_b использовать features_json['wt_snap']['1h']['wt1']")

    # ============================================================
    section("B6 — distance_to_pivot_pct vs entry-pivot proximity")
    # ============================================================
    print("Гипотеза: d2p в БД это TP distance (коррелирует с rr_at_entry)")
    print()
    cur.execute("""
      SELECT id, R_multiple, features_json
      FROM simulated_trades
      WHERE signal_type='pivot_reversal' AND features_json LIKE '%distance_to_pivot_pct%'
        AND created_at >= ?
      ORDER BY id DESC LIMIT 100
    """, (since,))
    rows = cur.fetchall()
    pairs = []
    for r in rows:
        try:
            f = json.loads(r[2])
            d2p = f.get("distance_to_pivot_pct")
            rr = f.get("rr_at_entry")
            if d2p is not None and rr is not None:
                pairs.append((d2p, rr))
        except Exception: pass

    if len(pairs) >= 10:
        # Pearson correlation
        n = len(pairs)
        sum_x = sum(p[0] for p in pairs)
        sum_y = sum(p[1] for p in pairs)
        sum_xy = sum(p[0]*p[1] for p in pairs)
        sum_xx = sum(p[0]*p[0] for p in pairs)
        sum_yy = sum(p[1]*p[1] for p in pairs)
        try:
            denom = ((n*sum_xx - sum_x**2) * (n*sum_yy - sum_y**2)) ** 0.5
            corr = (n*sum_xy - sum_x*sum_y) / denom if denom else 0
        except Exception:
            corr = 0
        d2p_med = sorted(p[0] for p in pairs)[len(pairs)//2]
        d2p_min = min(p[0] for p in pairs)
        print(f"  Sample n={len(pairs)}")
        print(f"  d2p median = {d2p_med:.2f}%, min = {d2p_min:.2f}%")
        print(f"  Pearson corr(d2p, rr_at_entry) = {corr:.3f}")
        if corr > 0.5:
            print(f"\n  ⚠️  ПОДТВЕРЖДЕНО: d2p сильно коррелирует с rr → это TP distance")
            print(f"  🔧 РЕШЕНИЕ: DEV-192 entry_to_trigger_distance_pct в features_json")
            print(f"  📝 ВРЕМЕННО: проверить trigger pivot невозможно по текущим данным")

    # ============================================================
    section("R_multiple вычисление — есть ли аномалии?")
    # ============================================================
    print("Проверка: R_multiple должен соответствовать profit_pct / sl_dist")
    print()
    cur.execute("""
      SELECT id, R_multiple, profit_pct, entry_price, stop_loss, exit_price, original_sl, status
      FROM simulated_trades
      WHERE status IN ('SL','TP','TSL') AND R_multiple IS NOT NULL
        AND created_at >= ?
      LIMIT 500
    """, (since,))
    rows = cur.fetchall()
    anomalies = 0
    for r in rows:
        try:
            tid, rmul, ppct, entry, sl, exit_p, orig_sl, status = r
            if not (entry and sl and exit_p): continue
            sl_dist = abs(entry - sl)
            if orig_sl and orig_sl != sl:
                # SL двинулся → R считается от ОРИГИНАЛЬНОГО SL
                sl_dist_orig = abs(entry - orig_sl)
                expected_r = (exit_p - entry) / sl_dist_orig if entry < exit_p else -(entry - exit_p) / sl_dist_orig
            else:
                expected_r = (exit_p - entry) / sl_dist if (exit_p > entry) else -(entry - exit_p) / sl_dist
            # допуск 5%
            if abs(rmul - expected_r) > 0.5 and abs(rmul - expected_r) / max(abs(expected_r), 0.1) > 0.2:
                anomalies += 1
        except Exception: pass

    print(f"  Проверено: {len(rows)} закрытых сделок")
    print(f"  R_multiple аномалий (отклонение >0.5 от expected): {anomalies}")
    if anomalies > len(rows) * 0.05:
        print(f"  ⚠️  R_multiple вычисляется некорректно в {anomalies/len(rows)*100:.1f}% сделок")
        print(f"  🔧 ИССЛЕДОВАТЬ: возможно после DEV-185 (overshoot fill) формула не учитывает реальный exit")

    # ============================================================
    section("features_json — coverage ключевых полей")
    # ============================================================
    cur.execute("""
      SELECT features_json FROM simulated_trades
      WHERE created_at >= ? AND features_json IS NOT NULL
    """, (since,))
    rows = cur.fetchall()
    n_feat = len(rows)
    keys_count = defaultdict(int)
    for r in rows:
        try:
            f = json.loads(r[0])
            for k in f.keys():
                keys_count[k] += 1
        except Exception: pass

    print(f"  features_json есть в {n_feat}/{total} сделках ({n_feat/total*100:.1f}%)")
    print()
    important = [
        "data_era", "wt1_value", "wt_snap", "smc_snap", "atr_trend_1h_bias",
        "mtf_direction_bias", "mtf_senior_matches", "mtf_aligned_pct",
        "regime", "session", "entry_priority", "rr_at_entry",
        "distance_to_pivot_pct", "distance_to_sl_pct", "narrative",
        "btc_4h_regime", "weekly_bias",
    ]
    print(f"  Coverage ключевых полей (n={n_feat}):")
    print("  {:30s} {:>6s} {:>6s}".format('field', 'n', '%'))
    for k in important:
        c = keys_count.get(k, 0)
        pct = c / n_feat * 100 if n_feat else 0
        marker = "✓" if pct >= 90 else ("~" if pct >= 50 else "✗")
        print(f"  {marker} {k:28s} {c:>6d} {pct:>5.1f}%")
    # Прочие частые поля
    other = [(k, c) for k, c in keys_count.items() if k not in important and c >= n_feat * 0.5]
    if other:
        print(f"\n  Другие частые (≥50%):")
        for k, c in sorted(other, key=lambda x: -x[1])[:20]:
            print(f"    {k:30s} {c:>6d} ({c/n_feat*100:>5.1f}%)")

    # ============================================================
    section("ИТОГ + рекомендации")
    # ============================================================
    print("Что делать с этими данными:\n")
    print("  1. Для аналитики/дашборда — внедрить effective_status helper (DEV-190)")
    print("     — устранит искажение B2 (скрытые TSL под маской SL)")
    print()
    print("  2. Для ML обучения — фильтровать по data_era='post_fix'")
    print("     — но дополнительно использовать features_json['wt_snap']['{tf}']['wt1']")
    print("     — НЕ wt1_value (может быть с не того TF)")
    print()
    print("  3. Для SIM сделок (B3) — stop_loss не трогать как ground truth")
    print("     — использовать original_sl + R_multiple для оценки")
    print()
    print("  4. distance_to_pivot_pct — НЕ использовать как entry-pivot proximity")
    print("     — это TP distance. Альтернативы нет в БД, только новые фичи (DEV-192)")
    print()
    print("  5. Backfill effective_status в новой колонке (опц.):")
    print("     ALTER TABLE simulated_trades ADD COLUMN effective_status TEXT;")
    print("     UPDATE ... SET effective_status = CASE ... END")
    print("     → но это write-операция, требует остановки бота")

    conn.close()


if __name__ == "__main__":
    main()
