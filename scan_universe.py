"""
Popular stock and crypto universes for scanning.
Categorized lists of tickers to monitor.
"""

# S&P 500 top 50 by market cap (as of 2024)
SP500_TOP_50 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BERKB", "V", "JNJ",
    "WMT", "XOM", "JPM", "MA", "BA", "SAMSUNG", "KO", "NFLX", "INTC", "ABBV",
    "PG", "CVX", "GE", "MRK", "COST", "ORCL", "AMD", "HON", "CSCO", "AVGO",
    "QCOM", "IBM", "ACPI", "INTU", "SBUX", "EMC", "MCD", "PYPL", "SNAP", "UBER",
    "ABNB", "DASH", "SE", "MRNA", "ZM", "RBLX", "ROKU", "COIN", "MSTR", "GOOG"
]

# Popular day trading stocks
POPULAR_DAYTRADE = [
    "TSLA", "AMD", "NVDA", "AAPL", "GOOGL", "MSFT", "META", "AMZN",
    "PLTR", "UPST", "DKNG", "RIOT", "MARA", "HOOD", "WISH", "CLOV",
    "LCID", "RIVN", "PTON", "RBLX", "U", "SNAP", "COIN", "MSTR",
    "GME", "AMC", "F", "X", "GLD", "SLV", "EEM", "IWM"
]

# Popular crypto pairs
CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
    "DOGE/USD", "AVAX/USD", "LINK/USD", "MATIC/USD", "UNI/USD",
    "LTC/USD", "BCH/USD", "ETC/USD", "XLM/USD", "ATOM/USD"
]

# Meme stocks / High volatility
MEME_STOCKS = [
    "GME", "AMC", "BBIG", "CLOV", "WISH", "SENS", "PAID",
    "NVAX", "RIOT", "MARA", "MSTR", "DKNG", "LCID"
]

# Popular ETFs
ETFS = [
    "SPY", "QQQ", "IWM", "EEM", "TLT", "GLD", "USO", "EFA",
    "XLE", "XLF", "XLV", "XLK", "XLI", "XLRE", "XLY", "XLP"
]

# Sector leaders
SECTOR_LEADERS = {
    "tech": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "INTC", "AMD", "PYPL", "CRM", "ADBE"],
    "energy": ["XOM", "CVX", "COP", "EOG", "MPC", "PSX", "VLO", "PXD", "OKE", "WMB"],
    "finance": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "BK", "AXP", "COF", "DFS"],
    "healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV", "TMO", "AMGN", "GILD", "VRTX", "REGN"],
    "consumer": ["WMT", "KO", "MCD", "NKE", "MO", "PM", "PEP", "CL", "GIS", "K"],
    "industrial": ["BA", "GE", "HON", "LMT", "RTX", "NOC", "GD", "HII", "UTX", "WM"],
}

# Penny stocks and low-float candidates
PENNY_STOCKS = [
    "DPLS", "OWLT", "NVRI", "LHVH", "PSWW", "TRCH", "CTRM", "SNDL",
    "PROG", "PROG", "DWAC", "PHUN", "IDEX", "ZOM", "GNUS", "EXPR"
]

def get_equity_universe():
    """Get complete equity universe for scanning."""
    universe = list(set(
        SP500_TOP_50 +
        POPULAR_DAYTRADE +
        MEME_STOCKS +
        ETFS +
        PENNY_STOCKS
    ))
    return sorted(universe)

def get_crypto_universe():
    """Get crypto universe for scanning."""
    return CRYPTO_PAIRS.copy()

def get_full_universe():
    """Get all symbols (equities + crypto)."""
    equities = get_equity_universe()
    crypto = get_crypto_universe()
    return {
        "equities": equities,
        "crypto": crypto,
        "all": equities + crypto
    }

def is_crypto_symbol(symbol: str) -> bool:
    """Check if symbol is a crypto pair (contains '/')."""
    return "/" in symbol

def get_sector(symbol: str) -> str:
    """Get sector for a given equity symbol."""
    for sector, symbols in SECTOR_LEADERS.items():
        if symbol in symbols:
            return sector
    return "other"

if __name__ == "__main__":
    print("Equity Universe:", len(get_equity_universe()), "symbols")
    print("Crypto Universe:", len(get_crypto_universe()), "symbols")
    universes = get_full_universe()
    print("Total Universe:", len(universes["all"]), "symbols")
