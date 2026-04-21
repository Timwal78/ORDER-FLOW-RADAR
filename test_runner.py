import json
from engine.decision import evaluate_signal

def run_test_suite():
    print("=== S3 FORENSIC AUDIT ===")
    
    # Test 1: High Momentum, High Volatility (Bullish Ignition)
    bullish_data = {
        "ticker": "BULL",
        "prices": [30, 32, 35, 40, 48],
        "volumes": [1000, 1100, 1200, 1500, 2000]
    }
    
    # Test 2: Low Momentum, High Volatility (Bearish Exhaustion)
    bearish_data = {
        "ticker": "BEAR",
        "prices": [40, 38, 35, 30, 22],
        "volumes": [1000, 1100, 1200, 1500, 2000]
    }
    
    # Test 3: Sideways, Volume Spike (Anomaly Detection)
    anomaly_data = {
        "ticker": "ANOM",
        "prices": [10.1, 10.2, 10.1, 10.2, 10.1],
        "volumes": [1000, 1000, 1000, 1000, 5000]
    }
    
    # Test 4: IWM Special Case (Should be 0DTE)
    iwm_data = {
        "ticker": "IWM",
        "prices": [200, 202, 205, 210, 215],
        "volumes": [5000, 5200, 5500, 6000, 8000]
    }
    
    # Test 5: High Price Case (Should be Excluded)
    high_price_data = {
        "ticker": "NVDA",
        "prices": [800, 802, 805, 810, 815],
        "volumes": [1000, 1100, 1200, 1500, 2000]
    }
    
    # Test 6: Bearish Scaling (Partial Conviction)
    partial_bear_data = {
        "ticker": "PBEAR",
        "prices": [30, 29, 28, 27, 26], # Steady drop (EXHAUSTION)
        "volumes": [1000, 1000, 1000, 1000, 1000]
    }

    # Test 7: Penny Stock 0DTE Logic
    penny_data = {
        "ticker": "PENN",
        "prices": [2.5, 2.6, 2.7, 2.4, 2.5],
        "volumes": [10000, 11000, 12000, 13000, 15000]
    }

    tests = [bullish_data, bearish_data, anomaly_data, iwm_data, high_price_data, partial_bear_data, penny_data]
    
    for test in tests:
        print(f"\nAnalyzing {test['ticker']}...")
        result = evaluate_signal(test['ticker'], test['prices'], test['volumes'], use_ai=False)
        
        # Display Lethal Stats
        print(f"  Score: {result['s3_score']}")
        print(f"  Action: {result['suggested_action']}")
        print(f"  Sizing: {result['position_size_pct']}%")
        print(f"  SL: ${result['stop_loss']} | TP: ${result['take_profit']} (R/R: {result['risk_reward']})")
        print(f"  Expiry: {result['expiry']}")
        
        # Validation rules
        if test['ticker'] == "BULL":
            assert result['state'] == "IGNITION", f"BULL failed ignition (score: {result['s3_score']})"
            assert result['position_size_pct'] > 5, "BULL failed sizing scale"
        elif test['ticker'] == "BEAR":
            assert result['state'] == "EXHAUSTION", f"BEAR failed exhaustion (score: {result['s3_score']})"
            assert result['stop_loss'] > test['prices'][-1], "BEAR SL logic reversed"
        elif test['ticker'] == "PBEAR":
            # Score should be low but not 0
            assert result['state'] == "EXHAUSTION"
            # Conviction = (100 - score) / 100. If score is 20, conviction is 0.8. Sizing = 8%.
            expected_sizing = round(((100 - result['s3_score']) / 100) * 10.0, 1)
            assert result['position_size_pct'] == expected_sizing, f"PBEAR sizing mismatch: {result['position_size_pct']} vs {expected_sizing}"
        elif test['ticker'] in ["IWM", "PENN"]:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            assert result['expiry'] == today, f"{test['ticker']} failed 0DTE check"
        elif test['ticker'] == "NVDA":
            assert "EXCLUDED" in result['suggested_action'], "NVDA failed price gate"

    print("\n[SUCCESS] S3 Logic Audit Passed.")

if __name__ == "__main__":
    run_test_suite()
