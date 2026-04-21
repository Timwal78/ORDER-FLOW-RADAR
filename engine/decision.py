import os
import numpy as np
from .scoring import calculate_s3_score, get_state

def evaluate_signal(ticker: str, prices: list, volumes: list, confidence_base: float = 75.0, use_ai: bool = True):
    """
    Final decision layer.
    Maps engine state to specific actionable recommendations.
    """
    from .features import calculate_momentum, calculate_volatility, calculate_anomaly, calculate_sharpe_momentum
    from .options_math import calculate_strike, calculate_expiry
    from .intelligence import generate_executive_summary
    
    # Lethal Momentum logic
    m_raw = calculate_momentum(prices)
    m_sharpe = calculate_sharpe_momentum(prices)
    
    # Weight sharpe momentum highly for "Lethal" accuracy
    w_s = float(os.getenv("SHARPE_MOMENTUM_WEIGHT", 0.6))
    m = (m_sharpe * w_s) + (m_raw * (1 - w_s))
    
    v = calculate_volatility(prices)
    a = calculate_anomaly(prices, volumes)
    
    score = calculate_s3_score(m, v, a)
    state = get_state(score)
    
    # Logic for action bias
    bias = "NEUTRAL"
    action = "WAIT"
    confidence = confidence_base
    
    if state == "IGNITION":
        bias = "LONG"
        action = "BUY CALLS"
        confidence += (score - 80) # Bonus confidence for high scores
    elif state == "EXHAUSTION":
        bias = "SHORT"
        action = "BUY PUTS"
        confidence += (20 - score)
        
    # Options logic
    current_price = prices[-1]
    
    # Price Gate
    price_cap = float(os.getenv("PRICE_CAP", 50))
    if current_price > price_cap and ticker.upper() != "IWM":
        action = "EXCLUDED (PRICE > $50)"
        state = "NEUTRAL"
        
    strike = calculate_strike(current_price, bias, prices)
    expiry = calculate_expiry(ticker, current_price)
    
    # Risk Management: SL/TP logic (Lethal Suite)
    std = np.std(prices) if len(prices) > 1 else current_price * 0.01
    sl_mult = float(os.getenv("ATR_SL_MULTIPLIER", 2.0))
    tp_mult = float(os.getenv("ATR_TP_MULTIPLIER", 6.0))
    
    if bias == "LONG":
        sl = current_price - (std * sl_mult)
        tp = current_price + (std * tp_mult)
    elif bias == "SHORT":
        sl = current_price + (std * sl_mult)
        tp = max(0.01, current_price - (std * tp_mult))
    else:
        sl = current_price
        tp = current_price
        
    # Dynamic Sizing based on S3 Score
    # BULL: Higher score = higher conviction. BEAR: Lower score = higher conviction.
    max_size = float(os.getenv("MAX_POSITION_SIZE", 10.0))
    if state == "IGNITION":
        conviction = score / 100  # 100 = max bull conviction
        position_size = min(max_size, conviction * max_size)
    elif state == "EXHAUSTION":
        conviction = (100 - score) / 100  # 0 = max bear conviction
        position_size = min(max_size, conviction * max_size)
    else:
        position_size = 0
        
    signal = {
        "ticker": ticker,
        "s3_score": score,
        "state": state,
        "bias": bias,
        "confidence": int(min(100, confidence)),
        "suggested_action": action,
        "strike": strike,
        "expiry": expiry,
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "risk_reward": float(os.getenv("RR_RATIO", 3.0)),
        "invalidation": f"Break of SL @ {round(sl, 2)}",
        "position_size_pct": round(position_size, 1)
    }
    
    # Intelligence logic
    if use_ai and state != "NEUTRAL":
        signal["reasoning"] = generate_executive_summary(signal)
    else:
        signal["reasoning"] = "System neutral. No active reasoning generated."
        
    return signal
