#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shopee_diagnostic.py
====================
Shopee Food Automation Diagnostic & Troubleshooting Tool.
Runs Chrome browser with `headless=False` (GUI mode) to visually inspect
login status, token validity, DOM rendering, and API connectivity.

Usage:
    python3 shopee_diagnostic.py
    python3 shopee_diagnostic.py --cli-check
"""

import os
import sys
import json
import time
from pathlib import Path

# Color styling for CLI output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

BASE_DIR = Path(__file__).resolve().parent
AUTOMATION_DIR = BASE_DIR / "src" / "shopee-omzet-automation"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

# Try loading .env if dotenv available or manually
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

from core import browser
from shopee.core.client import ShopeeModifyClient


def print_banner():
    print(f"{CYAN}{BOLD}{'=' * 70}{RESET}")
    print(f"{CYAN}{BOLD}  🔍 SHOPEE AUTOMATION DIAGNOSTIC & TROUBLESHOOTING TOOL{RESET}")
    print(f"{CYAN}{BOLD}  Mode: Headless = FALSE (Browser GUI Diagnostic){RESET}")
    print(f"{CYAN}{BOLD}{'=' * 70}{RESET}\n")


def check_environment():
    print(f"{BOLD}[1/4] Checking Environment & Settings...{RESET}")
    headless_shopee = os.getenv("HEADLESS_SHOPEE", "not set")
    general_headless = os.getenv("HEADLESS", "not set")
    otp_method = os.getenv("SHOPEE_OTP_METHOD", "auto")

    resolved_headless = browser.resolve_shopee_headless()

    print(f"  • Environment HEADLESS_SHOPEE: {YELLOW}{headless_shopee}{RESET}")
    print(f"  • Environment HEADLESS       : {YELLOW}{general_headless}{RESET}")
    print(f"  • Environment SHOPEE_OTP_METHOD: {GREEN}{otp_method.upper()}{RESET} (Flexible: SMS & WhatsApp)")
    print(f"  • Effective Shopee Headless  : {GREEN}{resolved_headless}{RESET} ({'HEADLESS (No GUI)' if resolved_headless else 'HEADFUL (GUI Window Visible)'})")
    print(f"  • OTP Channel Handler        : {GREEN}FLEXIBLE (SMS or WhatsApp options enabled){RESET}")

    display = os.getenv("DISPLAY")
    print(f"  • DISPLAY Environment        : {GREEN if display else YELLOW}{display or 'None (Warning: Non-headless needs X11/GUI display)'}{RESET}")

    # Check Chrome & Selenium
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        print(f"  • Selenium package           : {GREEN}AVAILABLE{RESET}")
    except ImportError as e:
        print(f"  • Selenium package           : {RED}FAILED ({e}){RESET}")
        return False

    return True


def scan_sessions():
    print(f"\n{BOLD}[2/4] Scanning Saved Shopee Sessions...{RESET}")
    session_dirs = [
        BASE_DIR / "shopee" / "data",
        AUTOMATION_DIR / "data",
        BASE_DIR
    ]

    session_files = []
    for d in session_dirs:
        if d.exists():
            session_files.extend(list(d.glob("session_*.json")))

    if not session_files:
        print(f"  {YELLOW}⚠️ No session_*.json files found.{RESET}")
        return []

    valid_sessions = []
    for s_file in session_files:
        try:
            with open(s_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            token = data.get("shopee_tob_token") or data.get("tob_token")
            entity_id = data.get("shopee_tob_entity_id") or data.get("entity_id") or data.get("store_id")
            
            token_snippet = f"{token[:20]}..." if token else "MISSING"
            status = f"{GREEN}VALID{RESET}" if token else f"{RED}NO TOKEN{RESET}"
            
            print(f"  • File: {CYAN}{s_file.relative_to(BASE_DIR)}{RESET}")
            print(f"    - Token    : {token_snippet} ({status})")
            print(f"    - Entity ID: {entity_id or 'Not set'}")
            if token:
                valid_sessions.append((s_file, data))
        except Exception as e:
            print(f"  • File: {CYAN}{s_file.relative_to(BASE_DIR)}{RESET} -> {RED}Error reading file: {e}{RESET}")

    return valid_sessions


def test_browser_launch(interactive=True):
    print(f"\n{BOLD}[3/4] Testing GUI Browser Launch (headless=False)...{RESET}")
    resolved_headless = browser.resolve_shopee_headless(headless_override=False)

    print(f"  🚀 Launching Chrome browser with headless={GREEN}{resolved_headless}{RESET}...")
    try:
        driver = browser._init_driver(headless=resolved_headless)
    except Exception as e:
        print(f"  {RED}❌ Failed to launch Chrome driver: {e}{RESET}")
        return False

    try:
        print(f"  🌐 Navigating to Shopee Partner Portal (https://partner.shopee.co.id/)...")
        driver.get("https://partner.shopee.co.id/login")
        time.sleep(3)

        title = driver.title
        curr_url = driver.current_url
        print(f"  • Page Title      : {GREEN}{title}{RESET}")
        print(f"  • Current URL     : {GREEN}{curr_url}{RESET}")

        cookies = driver.get_cookies()
        print(f"  • Active Cookies  : {GREEN}{len(cookies)} cookies loaded{RESET}")

        if interactive:
            print(f"\n{YELLOW}{BOLD}  [GUI INTERACTIVE DIAGNOSTIC MODE]{RESET}")
            print(f"  Window is open on screen. Verify the page layout, login, or popups.")
            print(f"  Press ENTER in this terminal to close the diagnostic browser window...")
            input()

        driver.quit()
        print(f"  {GREEN}✅ Chrome browser diagnostic launch SUCCESS.{RESET}")
        return True
    except Exception as e:
        print(f"  {RED}❌ Error during browser diagnostic navigation: {e}{RESET}")
        try: driver.quit()
        except: pass
        return False


def test_api_connectivity(sessions):
    print(f"\n{BOLD}[4/4] Testing Shopee API Connectivity...{RESET}")
    if not sessions:
        print(f"  {YELLOW}⚠️ Skipped API connectivity test: No valid sessions available.{RESET}")
        return

    s_file, data = sessions[0]
    token = data.get("shopee_tob_token")
    entity_id = data.get("shopee_tob_entity_id") or "21941677"
    extra_cookies = data.get("extra_cookies", {})

    print(f"  • Testing API using session file: {CYAN}{s_file.name}{RESET}")
    client = ShopeeModifyClient(
        tob_token=token,
        entity_id=str(entity_id),
        extra_cookies=extra_cookies
    )

    try:
        stores = client.get_stores()
        if stores:
            print(f"  {GREEN}✅ Shopee API Connected successfully! Stores count: {len(stores)}{RESET}")
            for store in stores[:3]:
                print(f"    - Store ID: {store.get('id')} | Name: {store.get('name')}")
        else:
            print(f"  {YELLOW}⚠️ API response received but store list is empty or token requires refresh.{RESET}")
    except Exception as e:
        print(f"  {RED}❌ API Connection error: {e}{RESET}")


def main():
    print_banner()

    cli_only = "--cli-check" in sys.argv

    ok = check_environment()
    if not ok:
        sys.exit(1)

    sessions = scan_sessions()

    if not cli_only:
        test_browser_launch(interactive=True)
    else:
        test_browser_launch(interactive=False)

    test_api_connectivity(sessions)

    print(f"\n{CYAN}{BOLD}{'=' * 70}{RESET}")
    print(f"{GREEN}{BOLD}  🎉 SHOPEE DIAGNOSTIC COMPLETE!{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
