import os
from dotenv import load_dotenv

load_dotenv()

def calculate_s3_score(momentum: float, volatility: float, anomaly: float):
    """
    Final S3 Scoring Machine.
    Strain (volatility/anomalies) accelerates the bias.
    """
    w_v = float(os.getenv("S3_VOLATILITY_WEIGHT", 0.3))
    w_a = float(os.getenv("S3_ANOMALY_WEIGHT", 0.3))
    
    strain = (volatility * w_v) + (anomaly * w_a)
    
    if momentum >= 50:
        # Bullish bias: strain pushes score higher
        score = momentum + strain
    else:
        # Bearish bias: strain pushes score lower
        score = momentum - strain
    
    return int(min(100, max(0, score)))

def get_state(score: int):
    """
    Determines the engine state based on thresholds.
    """
    ignition = int(os.getenv("S3_IGNITION_THRESHOLD", 80))
    exhaustion = int(os.getenv("S3_EXHAUSTION_THRESHOLD", 20))
    
    if score >= ignition:
        return "IGNITION"
    if score <= exhaustion:
        return "EXHAUSTION"
    return "NEUTRAL"
