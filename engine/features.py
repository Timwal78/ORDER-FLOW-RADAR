import os
import numpy as np

def calculate_volatility(prices: list):
    """
    Calculates normalized volatility using a simple deviation approach.
    Zero-Fake compliant: Returns 0 for static data, 100 for extreme swings.
    """
    if len(prices) < 2:
        return 0
    std_dev = np.std(prices)
    mean = np.mean(prices)
    if mean == 0:
        return 0
    volatility = (std_dev / mean) * 1000  # Scale for visibility
    return min(100, max(0, volatility))

def calculate_momentum(prices: list):
    """
    Rate of Change (ROC) over the momentum period.
    """
    period = int(os.getenv("MOMENTUM_PERIOD", 10))
    if len(prices) < 2:
        return 50
    
    calc_period = min(len(prices), period)
    current = prices[-1]
    past = prices[-calc_period]
    
    if past == 0:
        return 50
        
    roc = ((current - past) / past) * 100
    # Normalize ROC: 50 is neutral, >50 is bullish, <50 is bearish
    # A 5% move over the period should be significant
    normalized_roc = 50 + (roc * 10) 
    return min(100, max(0, normalized_roc))

def calculate_sharpe_momentum(prices: list):
    """
    Volatility-adjusted momentum (Sharpe Momentum).
    Prioritizes strong, stable moves over chaotic spikes.
    """
    if len(prices) < 5:
        return 50
        
    returns = np.diff(prices) / prices[:-1]
    sharpe = np.mean(returns) / (np.std(returns) + 1e-9)
    
    # Scale sharpe to 0-100 range (50 is neutral)
    normalized = 50 + (sharpe * 10)
    return min(100, max(0, normalized))

def calculate_anomaly(prices: list, volumes: list):
    """
    Volume/Price divergence detector.
    If volume spikes while price is flat or falling, it's an anomaly.
    """
    if len(prices) < 2 or len(volumes) < 2:
        return 0
        
    vol_mean = np.mean(volumes[:-1])
    current_vol = volumes[-1]
    
    sensitivity = float(os.getenv("ANOMALY_SENSITIVITY", 1.5))
    
    if vol_mean == 0:
        return 0
        
    vol_spike = current_vol / vol_mean
    
    if vol_spike > sensitivity:
        # Check for price action
        price_change = abs((prices[-1] - prices[-2]) / prices[-2])
        if price_change < 0.001:  # Hidden accumulation/distribution
            return 100
        return 50 # Normal spike
    
    return 0
