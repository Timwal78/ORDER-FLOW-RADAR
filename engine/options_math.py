import os
from datetime import datetime, timedelta
import numpy as np

def calculate_strike(current_price: float, bias: str, prices: list):
    """
    Calculates strike price based on ATR-like multiplier.
    Manifesto: Formula-driven, no magic defaults.
    """
    multiplier = float(os.getenv("STRIKE_ATR_MULTIPLIER", 1.5))
    
    # Calculate simple ATR (as standard deviation scaled)
    if len(prices) < 2:
        std = current_price * 0.01 # Fallback 1%
    else:
        std = np.std(prices)
    
    offset = std * multiplier
    
    if bias == "LONG":
        strike = current_price + offset
    elif bias == "SHORT":
        strike = current_price - offset
    else:
        strike = current_price
        
    # Round to nearest $0.50 or $1.00 for institutional realism
    return round(strike * 2) / 2

def calculate_expiry(ticker: str, price: float):
    """
    Calculates expiry date.
    - 0DTE for IWM and tickers < $5.
    - 14DTE for standard swing setups.
    """
    odte_tickers = os.getenv("ODTE_TICKERS", "IWM").split(",")
    today = datetime.now()
    
    if ticker.upper() in [t.strip().upper() for t in odte_tickers] or price < 5.0:
        # 0DTE: Today
        return today.strftime("%Y-%m-%d")
        
    # Standard Swing: Default 14 days
    days_to_expiry = int(os.getenv("DAYS_TO_EXPIRY", 14))
    target = today + timedelta(days=days_to_expiry)
    
    # Target standard Friday
    days_to_friday = (4 - target.weekday()) % 7
    expiry_date = target + timedelta(days=days_to_friday)
    
    return expiry_date.strftime("%Y-%m-%d")
