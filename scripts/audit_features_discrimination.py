"""
Анализ дискриминационной силы MTF/SMC полей features_json.
Показывает, какие поля разделяют DEAD (never-profit) и ALIVE сделки.
"""
import sqlite3, json

DB = "subscriptions.db"

FIELDS_NUMERIC = [
    'mtf_senior_matches', 'mtf_aligned_pct', 'htf_wt1_1h', 'htf_wt1_4h',
    'div_count', 'current_retracement', 'smc_active_bull_fvg_count',
    'smc_active_bear_fvg_count', 'smc_active_bull_ob_count', 'smc_active_bear_ob_count',
    'mtf_wt_spread_1h', 'mtf_wt_spread_4h', 'mtf_bias_strength',
]

FIELDS_CATEGORICAL = [
    'mtf_direction_bias', 'mtf_regime', 'smc_trend', 'btc_4h_regime',
    'last_bos_direction', 'weekly_bias', 'narrative',
    'smc_has_bullish_bos', 'smc_has_bearish_bos', 'smc_has_bos', 'smc_has_choch',
    'smc_price_in_ote', 'smc_ote_direction',
]


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Test on wt_signal + pivot_reversal (where data exists)
    signal_filter = "('wt_signal', 'pivot_reversal')"

    print("=" * 75)
    print("DISCRIMINATION POWER: DEAD vs ALIVE (wt_signal + pivot_reversal)")
    print("=" * 75)
    print(f"{'Field':<30s} {'DEAD':>8s} {'ALIVE':>8s} {'Delta':>8s} {'Power':>8s} {'n':>5s}")
    print("-" * 65)

    for field in FIELDS_NUMERIC:
        cur.execute(f"""
            SELECT 
                AVG(CASE WHEN (first_profit_r IS NULL OR first_profit_r=0) 
                    THEN CAST(json_extract(features_json, '$.{field}') AS REAL) END),
                AVG(CASE WHEN first_profit_r>0 
                    THEN CAST(json_extract(features_json, '$.{field}') AS REAL) END),
                COUNT(CASE WHEN json_extract(features_json, '$.{field}') IS NOT NULL THEN 1 END)
            FROM simulated_trades 
            WHERE signal_type IN {signal_filter} AND status != 'OPEN'
        """)
        dead_avg, alive_avg, n = cur.fetchone()
        if n and n >= 20 and dead_avg is not None and alive_avg is not None:
            delta = alive_avg - dead_avg
            if abs(delta) > 0.5:
                power = "STRONG"
            elif abs(delta) > 0.2:
                power = "MEDIUM"
            else:
                power = "weak"
            print(f"{field:<30s} {dead_avg:>+8.3f} {alive_avg:>+8.3f} {delta:>+8.3f} {power:>8s} {n:>5d}")

    print()
    print("--- Categorical fields: dead rate by value ---")
    for field in FIELDS_CATEGORICAL:
        cur.execute(f"""
            SELECT json_extract(features_json, '$.{field}') as val,
                COUNT(*) as n,
                SUM(CASE WHEN first_profit_r IS NULL OR first_profit_r=0 THEN 1 ELSE 0 END) as dead,
                ROUND(100.0*SUM(CASE WHEN first_profit_r IS NULL OR first_profit_r=0 THEN 1 ELSE 0 END)/COUNT(*),1) as dead_pct,
                ROUND(AVG(R_multiple),2) as avgR
            FROM simulated_trades 
            WHERE signal_type IN {signal_filter} AND status != 'OPEN'
                AND json_extract(features_json, '$.{field}') IS NOT NULL
            GROUP BY 1
            HAVING n >= 10
            ORDER BY 1
        """)
        rows = cur.fetchall()
        if rows:
            print(f"  [{field}]:")
            for r in rows:
                val = str(r[0]) if r[0] is not None else 'NULL'
                print(f"    {val:<25s} n={r[1]:>5d} dead={r[2]:>4d} ({r[3]:>5}%) avgR={r[4]:>+7}")

    conn.close()


if __name__ == "__main__":
    main()
