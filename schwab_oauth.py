"""
Schwab OAuth2 Helper — Get your refresh token.

Usage:
  python schwab_oauth.py

1. Opens browser to Schwab authorization page
2. You log in and authorize the app
3. Schwab redirects to https://127.0.0.1:8183/ with a code
4. Copy the FULL redirect URL from your browser address bar
5. Paste it here
6. Script exchanges code for refresh_token
7. Copy the refresh_token into your .env file

After that, the system auto-refreshes access tokens using the refresh token.
"""

import base64
import os
import sys
import urllib.parse
import webbrowser

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests")
    import requests

# Load from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

APP_KEY = os.getenv("SCHWAB_APP_KEY", "")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET", "")
REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1:8183/")
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"


def main():
    if not APP_KEY or not APP_SECRET:
        print("ERROR: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in .env")
        print("Get them from https://developer.schwab.com/")
        sys.exit(1)

    print("=" * 60)
    print("  SCHWAB OAuth2 — Get Refresh Token")
    print("=" * 60)

    # Step 1: Build authorization URL
    params = {
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print(f"\nOpening browser to Schwab authorization page...")
    print(f"\nIf browser doesn't open, go to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Step 2: User pastes redirect URL
    print("After authorizing, Schwab will redirect to a URL like:")
    print(f"  {REDIRECT_URI}?code=XXXX&session=YYYY")
    print("\nThe page will show an error (that's normal — we just need the URL).")
    print()
    redirect_url = input("Paste the FULL redirect URL from your browser: ").strip()

    if not redirect_url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    # Step 3: Extract authorization code
    parsed = urllib.parse.urlparse(redirect_url)
    query_params = urllib.parse.parse_qs(parsed.query)
    auth_code = query_params.get("code", [None])[0]

    if not auth_code:
        print("ERROR: Could not find 'code' parameter in the URL.")
        print(f"Parsed URL: {redirect_url}")
        sys.exit(1)

    # URL-decode the code (Schwab double-encodes it sometimes)
    auth_code = urllib.parse.unquote(auth_code)
    print(f"\nAuthorization code: {auth_code[:20]}...")

    # Step 4: Exchange code for tokens
    credentials = f"{APP_KEY}:{APP_SECRET}"
    encoded_creds = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
    }

    print("\nExchanging code for tokens...")
    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)

    if resp.status_code == 200:
        tokens = resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 1800)

        print("\n" + "=" * 60)
        print("  SUCCESS!")
        print("=" * 60)
        print(f"\nAccess Token (expires in {expires_in}s):")
        print(f"  {access_token[:40]}...")
        print(f"\nRefresh Token (use this in .env):")
        print(f"  {refresh_token}")
        print(f"\n{'=' * 60}")
        print(f"Add this to your .env file:")
        print(f"  SCHWAB_REFRESH_TOKEN={refresh_token}")
        print(f"{'=' * 60}")

        # Offer to auto-update .env
        update = input("\nAuto-update .env file? (y/n): ").strip().lower()
        if update == "y":
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    content = f.read()
                if "SCHWAB_REFRESH_TOKEN=" in content:
                    # Replace existing
                    lines = content.split("\n")
                    new_lines = []
                    for line in lines:
                        if line.startswith("SCHWAB_REFRESH_TOKEN="):
                            new_lines.append(f"SCHWAB_REFRESH_TOKEN={refresh_token}")
                        else:
                            new_lines.append(line)
                    with open(env_path, "w") as f:
                        f.write("\n".join(new_lines))
                else:
                    with open(env_path, "a") as f:
                        f.write(f"\nSCHWAB_REFRESH_TOKEN={refresh_token}\n")
                print(f"\n.env updated! Don't forget to also update Railway env vars:")
                print(f"  railway variables set SCHWAB_REFRESH_TOKEN={refresh_token}")
            else:
                print(f".env not found at {env_path}")
    else:
        print(f"\nERROR: Token exchange failed with status {resp.status_code}")
        print(f"Response: {resp.text}")
        print("\nCommon issues:")
        print("  - Code expired (you have ~30 seconds after redirect)")
        print("  - Wrong SCHWAB_APP_KEY or SCHWAB_APP_SECRET")
        print("  - Redirect URI doesn't match what's registered in Schwab developer portal")


if __name__ == "__main__":
    main()
