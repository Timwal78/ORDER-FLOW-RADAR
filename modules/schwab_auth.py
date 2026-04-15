"""
Order Flow Radar™ — Schwab Institutional Auth Orchestrator
ScriptMasterLabs™

CLI implementation of the Schwab OAuth2 code-to-token exchange.
Following Institutional Integrity Law 6: No manual copy-pasting of tokens to .env.
"""
import asyncio
import sys
import os
import logging
from typing import Optional

# Ensure we can import from the root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from modules.schwab_api import SchwabAPI

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("schwab_auth")

async def run_exchange(auth_code: str):
    """Perform the exchange and update .env."""
    if not config.SCHWAB_APP_KEY or not config.SCHWAB_APP_SECRET:
        logger.error("SCHWAB_APP_KEY/SECRET missing from .env. Configure them first.")
        return

    logger.info(f"Initiating exchange for code: {auth_code[:10]}...")
    
    # Initialize client
    client = SchwabAPI(
        app_key=config.SCHWAB_APP_KEY,
        app_secret=config.SCHWAB_APP_SECRET,
        refresh_token="", # Not needed for initial exchange
        redirect_uri=config.SCHWAB_REDIRECT_URI
    )

    try:
        tokens = await client.exchange_code(auth_code)
        if tokens:
            refresh_token = tokens.get("refresh_token")
            access_token = tokens.get("access_token")
            
            logger.info("Handshake successful. Updating .env...")
            
            env_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), '.env')
            update_env(env_path, {
                "SCHWAB_REFRESH_TOKEN": refresh_token,
                "SCHWAB_ACCESS_TOKEN": access_token
            })
            
            logger.info("Institutional state reached. System is ready.")
            print("\n" + "="*50)
            print("  SUCCESS: SCHWAB AUTHENTICATION COMPLETE")
            print("="*50)
            print(f"  - Refresh Token: Persisted to .env")
            print(f"  - Access Token:  Ready for immediate use")
            print("="*50 + "\n")
        else:
            logger.error("Handshake failed. Check your App Key, Secret, and Redirect URI alignment.")
    finally:
        await client.close()

def update_env(env_path: str, updates: dict):
    """Directly update .env file while preserving comments."""
    if not os.path.exists(env_path):
        logger.error(f".env not found at {env_path}")
        return

    with open(env_path, 'r') as f:
        lines = f.readlines()

    new_lines = []
    updated_keys = set()
    
    for line in lines:
        matched = False
        for key, value in updates.items():
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                updated_keys.add(key)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    # Add any keys that weren't found in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(env_path, 'w') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    if "--link" in sys.argv:
        auth_url = (
            f"https://api.schwabapi.com/v1/oauth/authorize?"
            f"client_id={config.SCHWAB_APP_KEY}&"
            f"redirect_uri={config.SCHWAB_REDIRECT_URI}"
        )
        print("\n" + "="*50)
        print("  SCHWAB AUTHORIZATION LINK")
        print("="*50)
        print(f"  1. Click the link below and log in:")
        print(f"     {auth_url}")
        print("\n  2. After approving, copy the FULL URL you land on.")
        print('  3. Run: python modules/schwab_auth.py "<FULL_URL>"')
        print("="*50 + "\n")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python modules/schwab_auth.py <AUTHORIZATION_CODE_OR_URL>")
        print("       python modules/schwab_auth.py --link")
        sys.exit(1)
    
    input_str = sys.argv[1]
    
    # Extract code if a full URL was pasted
    if "?code=" in input_str:
        import urllib.parse
        parsed = urllib.parse.urlparse(input_str)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code:
            logger.error("Could not find 'code' parameter in the URL.")
            sys.exit(1)
    else:
        code = input_str

    asyncio.run(run_exchange(code))
