import asyncio
from modules.schwab_api import SchwabAPI
from modules.polygon_api import PolygonAPI
from modules.alpaca_api import AlpacaAPI
import config
from modules.universe_scanner import UniverseScanner
import logging
logging.basicConfig(level=logging.INFO)

async def main():
    u = UniverseScanner(
        SchwabAPI(config.SCHWAB_APP_KEY,config.SCHWAB_APP_SECRET,config.SCHWAB_REFRESH_TOKEN,config.SCHWAB_REDIRECT_URI),
        PolygonAPI(config.POLYGON_API_KEY),
        AlpacaAPI(config.ALPACA_API_KEY, config.ALPACA_API_SECRET)
    )
    res = await u.build_universe()
    print('Total:', len(res))
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
