# -*- coding: utf-8 -*-
"""
push_browser.py — Standalone browser session khusus PUSH harga Shopee.
Mendukung login dengan username + password, serta verifikasi OTP interaktif
(menunggu kode via file otp_request_{username}.json yang ditulis oleh main.py/API).

Tidak bergantung pada browser.get_session() karena fungsi itu menutup login
saat halaman OTP terdeteksi (interactive=False) atau dapat menggunakan sesi
yang masih aktif dari akun lain.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────────
WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

# ── Selenium ───────────────────────────────────────────────────────────────────
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

log = logging.getLogger(__name__)

PARTNER_DASHBOARD   = "https://partner.shopee.co.id/food/dashboard"
PARTNER_LOGIN_URL   = "https://partner.shopee.co.id/login"
TOKEN_TRIGGER_PAGE  = "https://partner.shopee.co.id/settings/shopee-food/business-hours-settings"

OTP_WAIT_TIMEOUT    = 900  # 15 menit


# ── Driver ─────────────────────────────────────────────────────────────────────

def _init_push_driver(username: str, headless: bool = True) -> webdriver.Chrome:
    """Inisialisasi Chrome dengan profil terisolasi untuk username tertentu."""
    options = Options()
    options.add_argument("--log-level=3")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-component-update")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    # Profil Chrome terisolasi per username — di AUTOMATION_DIR/data/
    automation_data = AUTOMATION_DIR / "data"
    automation_data.mkdir(parents=True, exist_ok=True)
    profile_dir = automation_data / f"chrome_profile_{username}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument(f"--profile-directory=profile_{username}")

    # Hapus SingletonLock jika ada
    singleton_lock = profile_dir / "SingletonLock"
    try:
        if os.path.islink(singleton_lock) or os.path.exists(singleton_lock):
            os.unlink(str(singleton_lock))
            log.info(f"🧹 Removed Chrome SingletonLock at {singleton_lock}")
    except Exception as e:
        log.warning(f"⚠️ Failed to remove SingletonLock: {e}")

    chromium_path = (
        "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium")
        else "/usr/bin/chromium" if os.path.exists("/usr/bin/chromium")
        else None
    )
    chromedriver_path = (
        "/usr/bin/chromedriver" if os.path.exists("/usr/bin/chromedriver")
        else "/usr/lib/chromium/chromedriver" if os.path.exists("/usr/lib/chromium/chromedriver")
        else None
    )

    if chromium_path:
        options.binary_location = chromium_path

    driver = None
    if chromedriver_path:
        try:
            log.info(f"🌐 [PUSH_BROWSER] Initializing with system ChromeDriver: {chromedriver_path}")
            driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
        except Exception as e:
            log.warning(f"⚠️ System ChromeDriver failed: {e}")

    if not driver:
        try:
            log.info("🌐 [PUSH_BROWSER] Falling back to native Selenium Manager...")
            driver = webdriver.Chrome(options=options)
        except Exception as e:
            log.warning(f"⚠️ Native Chrome init failed: {e}. Trying CDP mode fallback...")
            try:
                import socket, subprocess
                s = socket.socket()
                s.bind(('', 0))
                cdp_port = s.getsockname()[1]
                s.close()

                cmd = [
                    chromium_path or "chromium",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f"--remote-debugging-port={cdp_port}",
                    f"--user-data-dir={profile_dir.resolve()}",
                    f"--profile-directory=profile_{username}"
                ]
                if headless:
                    cmd.append("--headless=new")
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2.5)

                # Use clean options instance for CDP attach mode to avoid unrecognized option errors
                cdp_options = Options()
                cdp_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{cdp_port}")
                if chromedriver_path:
                    driver = webdriver.Chrome(service=Service(chromedriver_path), options=cdp_options)
                else:
                    driver = webdriver.Chrome(options=cdp_options)
            except Exception as cdp_err:
                log.error(f"❌ CDP mode fallback failed: {cdp_err}")
                raise cdp_err

    if driver:
        driver.set_page_load_timeout(60)
    return driver


# ── Token Extraction ──────────────────────────────────────────────────────────

def _extract_tokens(driver) -> tuple[str | None, str | None]:
    """Ekstrak shopee_tob_token dan entity_id dari cookies browser."""
    tob_token = None
    entity_id = None

    for c in driver.get_cookies():
        name = c["name"]
        val = c["value"]
        if name == "shopee_tob_token":
            tob_token = val
        elif name.lower() in ["shopee_tob_entity_id", "shopee_foody_mid"]:
            if val and not entity_id:
                entity_id = val

    if not entity_id:
        try:
            entity_id = driver.execute_script("""
                return localStorage.getItem('shopee_tob_entity_id')
                    || localStorage.getItem('shopee_foody_mid')
                    || localStorage.getItem('merchant_id') || null;
            """)
        except:
            pass

    return tob_token, (str(entity_id).strip() if entity_id else None)


def _trigger_tokens(driver) -> tuple[str | None, str | None]:
    """Picu penerbitan token baru dengan mengunjungi halaman pengaturan."""
    try:
        try:
            driver.delete_cookie("shopee_tob_token")
        except:
            pass
        driver.get(TOKEN_TRIGGER_PAGE)
        for _ in range(12):
            tok, eid = _extract_tokens(driver)
            if tok:
                return tok, eid
            time.sleep(1)
    except:
        pass
    return _extract_tokens(driver)


def _get_all_cookies(driver) -> dict:
    return {c["name"]: c["value"] for c in driver.get_cookies()}


# ── OTP Waiting ───────────────────────────────────────────────────────────────

def _write_otp_request(username: str, channel: str = "sms"):
    """Tulis file OTP request ke automation/data/ agar main.py/API mendeteksinya."""
    data_dir = AUTOMATION_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    otp_file = data_dir / f"otp_request_{username}.json"
    otp_file.write_text(json.dumps({
        "status": "WAITING_OTP",
        "username": username,
        "channel": channel,
        "requested_at": datetime.now().isoformat()
    }, indent=2))
    log.info(f"📩 [OTP] Request OTP ditulis ke: {otp_file}")
    return otp_file


def _wait_for_otp_code(username: str, timeout: int = OTP_WAIT_TIMEOUT) -> str | None:
    """Tunggu kode OTP dari file otp_request_{username}.json (ditulis oleh API/main.py)."""
    data_dir = AUTOMATION_DIR / "data"
    otp_file = data_dir / f"otp_request_{username}.json"

    # Buat request file jika belum ada
    if not otp_file.exists():
        _write_otp_request(username)

    log.info(f"⏳ [OTP] Menunggu input OTP untuk akun '{username}' (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            if otp_file.exists():
                data = json.loads(otp_file.read_text())
                if data.get("status") == "CANCELLED":
                    log.info(f"❌ [OTP] User membatalkan OTP untuk '{username}'")
                    otp_file.unlink(missing_ok=True)
                    raise RuntimeError("user membatalkan otp")
                if data.get("status") == "RECEIVED" and data.get("code"):
                    code = str(data["code"]).strip()
                    otp_file.unlink(missing_ok=True)
                    log.info(f"✅ [OTP] Kode OTP diterima: {code}")
                    return code
        except RuntimeError as re:
            raise re
        except Exception as e:
            log.debug(f"  OTP file read error: {e}")
        time.sleep(2)

    log.error(f"❌ [OTP] Timeout menunggu OTP untuk '{username}'")
    otp_file.unlink(missing_ok=True)
    return None


# ── Lanjutkan / SSO Handler ───────────────────────────────────────────────────

def _handle_lanjutkan_screen(driver, target_username: str) -> str:
    """
    Penanganan khusus halaman 'Lanjutkan dengan Shopee' (SSO screen).
    Jika akun yang muncul di layar bukan `target_username` (misal 'allvbadmin'),
    maka hapus cookies & reload agar muncul form username + password baru.
    Jika akun di layar SESUAI `target_username` (atau tidak terdeteksi beda),
    maka klik tombol 'Lanjutkan'.
    
    Returns:
        'CLICKED_CONTINUE' - jika tombol Lanjutkan diklik
        'CLEARED_COOKIES' - jika akun beda & cookies dibersihkan untuk login ulang
        'NONE' - jika bukan halaman Lanjutkan dengan Shopee
    """
    try:
        body_text = (driver.execute_script("return document.body.innerText || ''") or "").lower()
        if "lanjutkan dengan shopee" in body_text or "sedang log in ke akun" in body_text:
            log.info("🔎 [PUSH_BROWSER] Terdeteksi halaman 'Lanjutkan dengan Shopee'...")
            
            # Cek nama akun yang muncul di layar
            account_shown = driver.execute_script("""
                var els = document.querySelectorAll('div, p, span, h1, h2, h3');
                for (var i = 0; i < els.length; i++) {
                    var txt = (els[i].innerText || '').trim();
                    if (!txt) continue;
                    var low = txt.toLowerCase();
                    if (!low.includes('lanjutkan') && !low.includes('shopee') && !low.includes('bantuan') && 
                        !low.includes('sedang log in') && !low.includes('merchant') && txt.length > 2 && txt.length < 40) {
                        return txt;
                    }
                }
                return '';
            """) or ""
            
            log.info(f"  👤 Akun di layar: '{account_shown}' | Target: '{target_username}'")
            
            # Jika akun di layar beda dari target_username (misal 'allvbadmin')
            if account_shown and target_username.lower() not in account_shown.lower():
                log.warning(f"  ⚠️ Akun di layar ({account_shown}) TIDAK SESUAI dengan target ({target_username}). Hapus cookies...")
                try:
                    driver.delete_all_cookies()
                    driver.execute_script("try{localStorage.clear();sessionStorage.clear();}catch(e){}")
                except Exception as c_err:
                    log.warning(f"  Failed clear cookies: {c_err}")
                driver.get(PARTNER_LOGIN_URL)
                time.sleep(3)
                return 'CLEARED_COOKIES'
            
            # Jika akun sesuai ATAU tombol Lanjutkan ada:
            btn = None
            for sel in [
                "//button[contains(., 'Lanjutkan') or contains(., 'Continue')]",
                "//a[contains(., 'Lanjutkan') or contains(., 'Continue')]",
                "//button[@type='submit']"
            ]:
                try:
                    candidates = driver.find_elements(By.XPATH, sel)
                    for c in candidates:
                        if c.is_displayed():
                            btn = c
                            break
                    if btn: break
                except: continue
                
            if btn:
                log.info(f"  👉 Mengklik tombol 'Lanjutkan': '{btn.text.strip()}'")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                return 'CLICKED_CONTINUE'
    except Exception as e:
        log.debug(f"  _handle_lanjutkan_screen error: {e}")
    return 'NONE'


# ── Main Session Function ─────────────────────────────────────────────────────

def get_push_session(
    username: str,
    password: str,
    target_name: str = "",
    headless: bool = True
) -> dict | None:
    """
    Login ke Shopee Partner sebagai {username} menggunakan engine browser teruji.
    """
    from core import browser
    session_file = AUTOMATION_DIR / "data" / f"session_{username}.json"
    browser.set_session_file(session_file)
    return browser.get_session(
        username=username,
        password=password,
        headless=headless,
        close_browser=True,
        target_name=target_name,
        interactive=True
    )
