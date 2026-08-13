import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WEEKLY_DIR = BASE_DIR / "src" / "shopee-omzet-automation"
sys.path.insert(0, str(WEEKLY_DIR))

from core import browser

def main():
    session_file = WEEKLY_DIR / "data" / "session.json"
    print(f"[*] Setting session file: {session_file}")
    browser.set_session_file(session_file)
    
    # Load credentials from weekly/credentials.json if exists
    username = "superfoodapp"
    password = "Master@00@"
    
    import json
    creds_file = WEEKLY_DIR / "credentials.json"
    if creds_file.exists():
        try:
            creds = json.loads(creds_file.read_text())
            username = creds.get("shopee_username", username)
            password = creds.get("shopee_password", password)
        except Exception as e:
            print(f"[!] Warning reading credentials.json: {e}")
            
    print(f"[*] Refreshing session for {username} using browser.get_session(headless=True)...")
    res = browser.get_session(
        username=username,
        password=password,
        headless=True,
        close_browser=True,
        interactive=False
    )
    if res:
        print("[+] Session refreshed and saved successfully!")
        print(f"    shopee_tob_token: {res.get('shopee_tob_token')[:30]}...")
        print(f"    shopee_tob_entity_id: {res.get('shopee_tob_entity_id')}")
    else:
        print("[-] Failed to refresh session.")

if __name__ == "__main__":
    main()
