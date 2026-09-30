UNIVERSE = ["SPY", "XLK", "XLP", "XLV"]

def signal(prices):
    """
    Low-Vol Growth Rotation: Long XLK vs Short XLV/XLP in low-vol regimes.
    
    Mechanism: When SPY 21-day realized vol is below its trailing 252-day 
    mean by > 0.5 standard deviations, rotate into tech (XLK) vs defensives.
    Position: +0.5 XLK, -0.25 XLV, -0.25 XLP (gross exposure = 1.0)
    """
    import numpy as np
    import pandas as pd
    
    spy = prices['SPY']
    
    # 21-day realized vol of SPY (annualized)
    spy_rets = spy.pct_change()
    vol_21d = spy_rets.rolling(21).std() * np.sqrt(252)
    
    # Z-score of vol using trailing 252-day window
    vol_mean = vol_21d.rolling(252).mean()
    vol_std  = vol_21d.rolling(252).std()
    vol_z    = (vol_21d - vol_mean) / vol_std
    
    # Signal: active in low-vol regime (z < -0.5), using prior day to avoid lookahead
    active = vol_z.shift(1) < -0.5
    
    # Build weight DataFrame
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights.loc[active, 'XLK'] =  0.5
    weights.loc[active, 'XLV'] = -0.25
    weights.loc[active, 'XLP'] = -0.25
    # SPY weight stays 0 (used only for vol calculation)
    
    return weights
