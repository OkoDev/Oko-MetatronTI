import numpy as np
import pandas as pd
from wave_lib import load, atr14, detect_impulses, simulate, pnl_pct, CORE

def gen_trades_for_symbol(symbol, tf, K, M, regime_df, rng, n_control=3, max_hold_c=96):
    df = load(symbol, tf)
    n = len(df)
    if n < 300:
        return []
    high = df['high'].values; low = df['low'].values; close = df['close'].values
    years = df['year'].values
    atr = atr14(df)
    imps = detect_impulses(df, atr, K, M)
    W = 4 * M
    # regime lookup via merge_asof
    reg = pd.merge_asof(df[['dt']].reset_index(), regime_df.sort_values('dt'), on='dt', direction='backward')
    regime_arr = reg['regime'].values

    trades = []

    def record(mech, side, entry_idx, entry_price, stop, target, max_hold):
        exitp, reason, exit_idx = simulate(high, low, entry_idx, side, entry_price, stop, target, max_hold)
        if exitp is None:
            exitp = close[exit_idx]  # expired -> mark-to-close
        pnl = pnl_pct(side, entry_price, exitp)
        trades.append(dict(symbol=symbol, tf=tf, mech=mech, side=('long' if side==1 else 'short'),
                            entry_idx=entry_idx, year=int(years[entry_idx]),
                            regime=('up' if regime_arr[entry_idx]==1 else 'down'),
                            entry=entry_price, stop=stop, target=target, exitp=exitp,
                            reason=reason, pnl_pct=pnl))
        # controls (matched geometry, same side, same year, random bar)
        stop_pct = abs(entry_price - stop) / entry_price
        target_pct = abs(target - entry_price) / entry_price
        yr_idx = np.where(years == years[entry_idx])[0]
        yr_idx = yr_idx[(yr_idx > 5) & (yr_idx < n - max_hold - 1)]
        if len(yr_idx) == 0:
            return
        for _ in range(n_control):
            ridx = int(rng.choice(yr_idx))
            rprice = close[ridx]
            if side == 1:
                rstop = rprice * (1 - stop_pct); rtarget = rprice * (1 + target_pct)
            else:
                rstop = rprice * (1 + stop_pct); rtarget = rprice * (1 - target_pct)
            rexit, rreason, rexit_idx = simulate(high, low, ridx, side, rprice, rstop, rtarget, max_hold)
            if rexit is None:
                rexit = close[rexit_idx]
            rpnl = pnl_pct(side, rprice, rexit)
            trades.append(dict(symbol=symbol, tf=tf, mech='D_' + mech, side=('long' if side==1 else 'short'),
                                entry_idx=ridx, year=int(years[ridx]),
                                regime=('up' if regime_arr[ridx]==1 else 'down'),
                                entry=rprice, stop=rstop, target=rtarget, exitp=rexit,
                                reason=rreason, pnl_pct=rpnl))

    for imp in imps:
        d = imp['dir']; S = imp['start_price']; E = imp['extreme_price']; c = imp['confirm_idx']
        La = abs(E - S)
        if La <= 0 or c >= n - 2:
            continue

        # --- Mechanic A: continuation ---
        zone_a = E - d * 0.382 * La
        zone_b = E - d * 0.618 * La
        zone_lo, zone_hi = (zone_a, zone_b) if zone_a < zone_b else (zone_b, zone_a)
        invalid_level = S
        end_scan = min(c + W, n - 1)
        entry_idx = None
        for t in range(c, end_scan + 1):
            lo_t, hi_t = low[t], high[t]
            if d == 1 and lo_t <= invalid_level:
                break
            if d == -1 and hi_t >= invalid_level:
                break
            if lo_t <= zone_hi and hi_t >= zone_lo:
                entry_idx = t
                break
        if entry_idx is not None and entry_idx < n - 2:
            entry_price = close[entry_idx]
            stop = S
            target = entry_price + d * La
            if (d == 1 and stop < entry_price and target > entry_price) or \
               (d == -1 and stop > entry_price and target < entry_price):
                record('A', d, entry_idx, entry_price, stop, target, W)

        # --- Mechanic B: fade ---
        entry_idx_b = c
        entry_price_b = close[c]
        side_b = -d
        stop_b = E
        target_b = E - d * 0.5 * La
        valid_b = (side_b == 1 and stop_b < entry_price_b and target_b > entry_price_b) or \
                  (side_b == -1 and stop_b > entry_price_b and target_b < entry_price_b)
        if valid_b and entry_idx_b < n - 2:
            record('B', side_b, entry_idx_b, entry_price_b, stop_b, target_b, W)

        # --- Mechanic C: bounce after down-impulse (also mirrored: fade after up-impulse) ---
        entry_idx_c = c
        entry_price_c = close[c]
        side_c = -d  # after down impulse (d=-1) -> long bounce; after up impulse (d=1) -> short fade
        atr_c = atr[c]
        if atr_c and atr_c > 0 and entry_idx_c < n - 2:
            stop_c = entry_price_c - side_c * 1.0 * atr_c
            for tp_pct in (0.01, 0.02, 0.03):
                target_c = entry_price_c * (1 + side_c * tp_pct)
                valid_c = (side_c == 1 and stop_c < entry_price_c) or (side_c == -1 and stop_c > entry_price_c)
                if valid_c:
                    record(f'C_{int(tp_pct*100)}', side_c, entry_idx_c, entry_price_c, stop_c, target_c, max_hold_c)

    return trades
