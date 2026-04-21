import os
import time
import pandas as pd
import yfinance as yf
from datetime import datetime

class DataCollector:
    """
    Rate-limit aware institutional data collector.
    Manifesto: No fakes. Real-time fetcher.
    """
    def __init__(self):
        self.last_fetch_time = 0
        self.rate_limit_delay = 1.0 # 1 second between calls to avoid blacklisting
        
    def _wait_for_rate_limit(self):
        elapsed = time.time() - self.last_fetch_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_fetch_time = time.time()

    def fetch_market_data(self, ticker: str, interval: str = "5m", period: str = "1d"):
        """
        Fetches prices and volumes from Yahoo Finance.
        """
        self._wait_for_rate_limit()
        
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                return None, None
            
            # Extract standard lists for the S3 engine
            prices = df['Close'].tolist()
            volumes = df['Volume'].tolist()
            
            return prices, volumes
        except Exception as e:
            print(f"Data Fetch Failure for {ticker}: {e}")
            return None, None

def get_data_collector():
    return DataCollector()
