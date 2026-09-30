"""TBT/TLT leveraged ETF analysis: decay measurement, regime detection, and scenario math for bond bear positioning. Also includes AMD/NVDA cointegration and meta pre-earnings event study utilities."""

"""
TBT/TLT leveraged ETF analytics for bond bear positioning.
Functions: measure_tbt_decay, tbt_scenario, bond_regime_score
"""
import numpy as np
import pandas as pd
from scipy import stats

def measure_tbt_decay(prices_df, by_year=False):
    """
    Measure TBT actual performance vs theoretical 2x short TLT.
    Returns residual alpha (positive = TBT beats 2x short).
    prices_df must have columns TBT and TLT.
    """
    rets = prices_df[['TBT','TLT']].pct_change().dropna()
    tbt_r = rets['TBT']
    tlt_r = rets['TLT']
    
    slope, intercept, r, p, se = stats.linregress(-tlt_r, tbt_r)
    residual = tbt_r + 2*tlt_r  # positive = TBT beats 2x theory
    
    result = {
        'beta': slope,
        'annual_alpha': intercept * 252,
        'r_squared': r**2,
        'mean_residual_annual': residual.mean() * 252,
    }
    
    if by_year:
        result['by_year'] = {}
        rets['year'] = rets.index.year
        for yr in sorted(rets['year'].unique()):
            mask = rets['year'] == yr
            if mask.sum() < 50:
                continue
            s, ic, _, _, _ = stats.linregress(-tlt_r[mask], tbt_r[mask])
            result['by_year'][yr] = {'beta': s, 'annual_alpha': ic * 252}
    
    return result


def tbt_scenario(rate_move_bps, weeks, tlt_duration=17, tbt_annual_alpha=0.05):
    """
    Scenario math: given rate move in bps and holding period in weeks,
    compute expected TBT and TMV (estimated) net returns.
    
    tlt_duration: modified duration of TLT (typically 17)
    tbt_annual_alpha: empirical TBT alpha vs 2x short TLT (default 5%/yr from recent data)
    """
    tlt_move = tlt_duration * rate_move_bps / 10000  # TLT return for rate move
    
    tbt_gross = 2 * tlt_move  # 2x levered
    tmv_gross = 3 * tlt_move  # 3x levered (estimated)
    
    # Decay: TBT has ~0-5%/yr positive alpha in trending markets
    # In flat markets, 2x leveraged ETF has minimal decay
    tbt_decay = -(tbt_annual_alpha / 52) * weeks  # net positive = benefit
    tmv_decay_cost = (0.12 / 52) * weeks  # ~12%/yr for 3x, always a cost
    
    tbt_net = tbt_gross - tbt_decay
    tmv_net = tmv_gross - tmv_decay_cost
    
    return {
        'rate_move_bps': rate_move_bps,
        'weeks': weeks,
        'tlt_expected': -tlt_move,  # TLT falls when rates rise
        'tbt_gross': tbt_gross,
        'tbt_net': tbt_net,
        'tmv_gross': tmv_gross,
        'tmv_net': tmv_net,
        'tmv_vs_tbt_advantage': tmv_net - tbt_net,
    }


def bond_regime_score(prices_df):
    """
    Compute a 0-5 score for bond bear regime (high score = favor TBT).
    prices_df must have columns: TLT, IEF, TIP, TBT
    Returns pd.Series of daily scores.
    """
    f1 = (prices_df['TLT'].pct_change(63) < -0.01).astype(int)       # TLT 3M negative
    f2 = (prices_df['TLT'] < prices_df['TLT'].rolling(200).mean()).astype(int)  # below 200MA
    f3 = (prices_df['TIP'].pct_change(63) > prices_df['IEF'].pct_change(63)).astype(int)  # TIPS>IEF
    f4 = (prices_df['TBT'].pct_change(21) > 0).astype(int)            # TBT 1M positive
    f5 = (prices_df['TBT'].pct_change(63) > 0).astype(int)            # TBT 3M positive
    
    score = f1 + f2 + f3 + f4 + f5
    score.name = 'bond_bear_score'
    return score
