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

OTP_WAIT_TIMEOUT    = 600  # 10 menit


# ── Driver ─────────────────────────────────────────────────────────────────────

def _init_push_driver(username: str, headless: bool = False) -> webdriver.Chrome:
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
                if data.get("status") == "RECEIVED" and data.get("code"):
                    code = str(data["code"]).strip()
                    otp_file.unlink(missing_ok=True)
                    log.info(f"✅ [OTP] Kode OTP diterima: {code}")
                    return code
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
    Login ke Shopee Partner sebagai {username} dengan profil Chrome terisolasi.
    Mendukung OTP interaktif: jika Shopee meminta verifikasi, tunggu kode OTP
    dari file otp_request_{username}.json (ditulis oleh endpoint API /api/shopee/submit-otp).

    Returns:
        dict dengan kunci: shopee_tob_token, shopee_tob_entity_id, extra_cookies
        None jika gagal
    """
    log.info(f"🚀 [PUSH_BROWSER] Memulai sesi PUSH untuk '{username}' (headless={headless})")
    
    # Cleanup any stale OTP request files from previous runs
    for d in [AUTOMATION_DIR / "data", WORKSPACE_DIR / "shopee" / "data"]:
        if d.exists():
            (d / f"otp_request_{username}.json").unlink(missing_ok=True)

    driver = None
    try:
        driver = _init_push_driver(username=username, headless=headless)
        wait = WebDriverWait(driver, 30)

        # ── Step 1: Periksa apakah sudah login ──────────────────────────────
        log.info(f"🌐 [PUSH_BROWSER] Membuka {PARTNER_DASHBOARD}...")
        driver.get(PARTNER_DASHBOARD)
        time.sleep(4)
        
        # Cek halaman Lanjutkan jika ada
        _handle_lanjutkan_screen(driver, username)
        
        current_url = driver.current_url.lower()
        is_logged_in = any(kw in current_url for kw in ["dashboard", "merchant-selector", "onboarding"])

        if is_logged_in:
            log.info("✅ [PUSH_BROWSER] Sudah login (sesi tersimpan di profil Chrome).")
        else:
            # Try restoring session from saved token file before initiating fresh login
            session_file = AUTOMATION_DIR / "data" / f"session_{username}.json"
            if not session_file.exists():
                session_file = AUTOMATION_DIR / "data" / "session.json"

            if session_file.exists():
                try:
                    saved = json.loads(session_file.read_text())
                    if saved.get("shopee_tob_token"):
                        log.info(f"🔍 [PUSH_BROWSER] Restoring session from {session_file.name}...")
                        driver.add_cookie({"name": "shopee_tob_token", "value": saved["shopee_tob_token"]})
                        if saved.get("shopee_tob_entity_id"):
                            driver.add_cookie({"name": "shopee_tob_entity_id", "value": saved["shopee_tob_entity_id"]})
                        for n, v in saved.get("extra_cookies", {}).items():
                            try: driver.add_cookie({"name": n, "value": v})
                            except: pass

                        driver.get(PARTNER_DASHBOARD)
                        time.sleep(4)
                        current_url = driver.current_url.lower()
                        is_logged_in = any(kw in current_url for kw in ["dashboard", "merchant-selector", "onboarding"])
                        if is_logged_in:
                            log.info("✅ [PUSH_BROWSER] Restored session successfully from file.")
                except Exception as sf_err:
                    log.warning(f"⚠️ [PUSH_BROWSER] Failed to restore session from file: {sf_err}")

        if not is_logged_in:
            # ── Step 2: Login dengan username + password ─────────────────────
            log.info(f"🔐 [PUSH_BROWSER] Belum login, membuka halaman login...")
            driver.get(PARTNER_LOGIN_URL)
            time.sleep(2)

            # Cek halaman Lanjutkan dulu
            lanjut_res = _handle_lanjutkan_screen(driver, username)
            current_url = driver.current_url.lower()
            if any(kw in current_url for kw in ["dashboard", "merchant-selector", "onboarding"]):
                is_logged_in = True

            if not is_logged_in:
                # Tunggu sampai redirect ke halaman authenticate selesai dan form siap
                log.info("  ⏳ Menunggu halaman login Shopee Partner termuat...")
                for _ in range(15):
                    time.sleep(1)
                    cur = driver.current_url.lower()
                    try:
                        inputs = driver.find_elements(By.TAG_NAME, "input")
                        visible_inputs = [i for i in inputs if i.is_displayed()]
                        if visible_inputs and ("accounts.shopee" in cur or "partner.shopee" in cur):
                            break
                    except:
                        pass

            log.info(f"  📄 URL saat ini: {driver.current_url}")

            # Log semua input untuk debugging
            try:
                all_inputs = driver.find_elements(By.TAG_NAME, "input")
                for i, inp in enumerate(all_inputs):
                    log.info(f"  INPUT[{i}] type={inp.get_attribute('type')} "
                             f"name={inp.get_attribute('name')} "
                             f"placeholder={inp.get_attribute('placeholder')} "
                             f"visible={inp.is_displayed()}")
            except Exception as dbg_err:
                log.warning(f"  Debug input scan error: {dbg_err}")

            # ── Isi username ─────────────────────────────────────────────────
            log.info(f"  ✏️  Mengisi username: {username}")
            user_input = None
            # Coba berbagai strategi selector
            strategies_user = [
                (By.CSS_SELECTOR, "input[placeholder*='handphone' i]"),
                (By.CSS_SELECTOR, "input[placeholder*='Username' i]"),
                (By.CSS_SELECTOR, "input[placeholder*='email' i]"),
                (By.CSS_SELECTOR, "input[name='userName']"),
                (By.CSS_SELECTOR, "input[name='username']"),
                (By.XPATH, "//input[not(@type='password') and not(@type='hidden') and not(@type='checkbox')]"),
            ]
            for by, sel in strategies_user:
                try:
                    candidates = driver.find_elements(by, sel)
                    for el in candidates:
                        if el.is_displayed() and el.is_enabled():
                            user_input = el
                            break
                    if user_input:
                        break
                except:
                    continue

            if not user_input:
                log.error("❌ [PUSH_BROWSER] Tidak menemukan field username.")
                return None

            user_input.click()
            time.sleep(0.3)
            user_input.send_keys(Keys.CONTROL + "a")
            user_input.send_keys(Keys.DELETE)
            user_input.send_keys(username)
            log.info(f"  ✅ Username diisi.")
            time.sleep(0.5)

            # ── Isi password ─────────────────────────────────────────────────
            log.info("  ✏️  Mengisi password...")
            pass_input = None
            for by, sel in [
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[placeholder*='assword' i]"),
            ]:
                try:
                    candidates = driver.find_elements(by, sel)
                    for el in candidates:
                        if el.is_displayed() and el.is_enabled():
                            pass_input = el
                            break
                    if pass_input:
                        break
                except:
                    continue

            if not pass_input:
                log.error("❌ [PUSH_BROWSER] Tidak menemukan field password.")
                return None

            pass_input.click()
            time.sleep(0.3)
            pass_input.send_keys(Keys.CONTROL + "a")
            pass_input.send_keys(Keys.DELETE)
            pass_input.send_keys(password)
            log.info("  ✅ Password diisi.")
            time.sleep(0.8)

            # ── Klik tombol Masuk ─────────────────────────────────────────────
            log.info("  👆 Mengklik tombol Masuk...")
            login_btn = None

            # Strategi 1: Selenium XPATH
            for btn_xpath in [
                "//button[normalize-space(text())='Masuk']",
                "//button[contains(., 'Masuk')]",
                "//button[contains(., 'Log In')]",
                "//button[@type='submit']",
            ]:
                try:
                    btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, btn_xpath))
                    )
                    if btn.is_displayed():
                        login_btn = btn
                        break
                except:
                    continue

            if login_btn:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", login_btn)
                time.sleep(0.3)
                try:
                    login_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", login_btn)
                log.info(f"  ✅ Tombol Masuk diklik: '{login_btn.text.strip()}'")
            else:
                # Fallback: Enter di field password
                log.warning("  ⚠️ Tombol Masuk tidak ditemukan, mengirim Enter...")
                pass_input.send_keys(Keys.RETURN)

            # ── Step 3: Tunggu redirect / OTP ────────────────────────────────
            time.sleep(3)
            start_wait = time.time()
            otp_requested = False

            while time.time() - start_wait < 90:
                current_url = driver.current_url.lower()

                # Cek jika ada layar 'Lanjutkan dengan Shopee'
                _handle_lanjutkan_screen(driver, username)
                current_url = driver.current_url.lower()

                if any(kw in current_url for kw in ["dashboard", "merchant-selector", "onboarding"]):
                    log.info("✅ [PUSH_BROWSER] Login berhasil, diarahkan ke dashboard.")
                    is_logged_in = True
                    break

                # Deteksi halaman OTP / verifikasi
                try:
                    otp_input = None
                    for sel in ["input.shopee-otp-input__input", ".shopee-otp-input input", "input[maxlength='6']"]:
                        els = driver.find_elements(By.CSS_SELECTOR, sel)
                        for el in els:
                            if el.is_displayed():
                                otp_input = el
                                break
                        if otp_input:
                            break

                    is_verification_page = driver.execute_script("""
                        var texts = ["pilih cara verifikasi", "select verification method",
                            "pilih metode verifikasi", "verify to log in", "verifikasi untuk masuk",
                            "masukkan kode", "enter code", "kode verifikasi", "verification code"];
                        var body = (document.body.innerText || "").toLowerCase();
                        return texts.some(function(t) { return body.includes(t); });
                    """)

                    if otp_input or is_verification_page:
                        try:
                            from core.browser import _handle_verification_method_selection
                            _handle_verification_method_selection(driver)
                        except Exception as method_err:
                            log.debug(f"Verification method selection warning: {method_err}")

                        if not otp_requested:
                            log.info(f"🔑 [PUSH_BROWSER] Halaman OTP terdeteksi untuk '{username}'. Menulis OTP request...")
                            _write_otp_request(username)
                            otp_requested = True
                            whatsapp_triggered = False

                        # Cek apakah pengguna memilih saluran WhatsApp atau kode OTP sudah tersedia
                        data_dir = AUTOMATION_DIR / "data"
                        otp_file = data_dir / f"otp_request_{username}.json"
                        try:
                            if otp_file.exists():
                                data = json.loads(otp_file.read_text())
                                
                                # Cek jika pengguna memilih saluran WhatsApp via Web UI
                                req_channel = (data.get("requested_channel") or "").lower()
                                if req_channel == "whatsapp" and not whatsapp_triggered:
                                    log.info(f"📲 [PUSH_BROWSER] Pengguna memilih WhatsApp di Web UI! Menjalankan 'metode verifikasi lainnya'...")
                                    try:
                                        from core.browser import _handle_verification_method_selection
                                        success = _handle_verification_method_selection(driver, target_method="whatsapp")
                                        if success:
                                            whatsapp_triggered = True
                                            log.info("✅ [PUSH_BROWSER] Pemicuan WhatsApp OTP sukses!")
                                    except Exception as ch_err:
                                        log.error(f"Gagal memproses pemicuan WhatsApp OTP: {ch_err}")

                                if data.get("status") == "RECEIVED" and data.get("code"):
                                    otp_code = str(data["code"]).strip()
                                    otp_file.unlink(missing_ok=True)
                                    log.info(f"✅ [PUSH_BROWSER] Mengisi OTP ({data.get('channel', 'sms')}): {otp_code}")

                                    # Isi kode OTP ke form
                                    otp_fields = []
                                    for otp_sel in [
                                        "input.shopee-otp-input__input",
                                        ".shopee-otp-input input",
                                        "input[maxlength='1']",
                                        "input[maxlength='6']",
                                        "input[autocomplete='one-time-code']",
                                    ]:
                                        els = driver.find_elements(By.CSS_SELECTOR, otp_sel)
                                        visible = [e for e in els if e.is_displayed()]
                                        if visible:
                                            otp_fields = visible
                                            break

                                    log.info(f"  🔢 OTP fields ditemukan: {len(otp_fields)}")
                                    if len(otp_fields) >= 6:
                                        # 6 field terpisah (per digit)
                                        for idx, digit in enumerate(otp_code[:6]):
                                            otp_fields[idx].click()
                                            time.sleep(0.1)
                                            otp_fields[idx].send_keys(digit)
                                            time.sleep(0.15)
                                    elif len(otp_fields) == 1:
                                        # 1 field gabungan
                                        otp_fields[0].click()
                                        otp_fields[0].send_keys(Keys.CONTROL + "a")
                                        otp_fields[0].send_keys(otp_code)
                                    else:
                                        # Fallback: coba isi semua field yang ada
                                        for fld in otp_fields:
                                            fld.send_keys(otp_code)

                                    # Klik tombol Verifikasi / Konfirmasi jika ada
                                    time.sleep(1)
                                    try:
                                        verify_btn = driver.find_element(By.XPATH,
                                            "//button[contains(.,'Verifikasi') or contains(.,'Verify') "
                                            "or contains(.,'Konfirmasi') or contains(.,'Confirm') "
                                            "or contains(.,'Kirim') or contains(.,'Submit') "
                                            "or contains(.,'Selanjutnya') or contains(.,'Next')]"
                                        )
                                        if verify_btn.is_displayed():
                                            driver.execute_script("arguments[0].click();", verify_btn)
                                            log.info(f"  👆 Tombol verifikasi diklik: '{verify_btn.text.strip()}'")
                                    except:
                                        log.info("  ℹ️  Tidak ada tombol verifikasi (auto-submit).")
                                     # ── Tunggu redirect setelah OTP hingga 30 detik ──────
                                    log.info(f"  ⏳ Menunggu redirect setelah OTP...")
                                    for wait_tick in range(30):
                                        time.sleep(1)
                                        _handle_lanjutkan_screen(driver, username)
                                        cur = driver.current_url.lower()
                                        log.info(f"  [{wait_tick+1}/30] URL: {cur}")
                                        # Partner Shopee redirect ke berbagai halaman setelah login
                                        if any(kw in cur for kw in [
                                            "dashboard", "merchant-selector", "onboarding",
                                            "food", "settings", "analytics", "partner.shopee.co.id/",
                                            "seller.shopee", "manage"
                                        ]) and "login" not in cur and "authenticate" not in cur:
                                            log.info("✅ [PUSH_BROWSER] Verifikasi OTP berhasil! Redirect terdeteksi.")
                                            is_logged_in = True
                                            break
                                    if is_logged_in:
                                        break
                                    # OTP diisi tapi tidak redirect — mungkin ada langkah selanjutnya
                                    log.warning(f"  ⚠️ Setelah OTP, masih di: {driver.current_url}")
                                    # Coba klik tombol Konfirmasi/Lanjutkan jika ada
                                    try:
                                        confirm_btn = driver.find_element(By.XPATH,
                                            "//button[contains(.,'Konfirmasi') or contains(.,'Lanjutkan') or contains(.,'Confirm') or contains(.,'Continue') or contains(.,'Verify')]"
                                        )
                                        if confirm_btn.is_displayed():
                                            confirm_btn.click()
                                            log.info("  👆 Tombol konfirmasi diklik.")
                                            time.sleep(3)
                                    except:
                                        pass
                        except Exception as otp_err:
                            log.warning(f"  OTP check error: {otp_err}")
                except Exception as detect_err:
                    log.debug(f"  OTP detect error: {detect_err}")

                time.sleep(2)

        if not is_logged_in:
            log.error(f"❌ [PUSH_BROWSER] Gagal login sebagai '{username}'.")
            return None

        # ── Step 4: Pilih merchant target jika perlu ─────────────────────────
        if target_name:
            current_url = driver.current_url.lower()
            if "merchant-selector" in current_url:
                log.info(f"🏪 [PUSH_BROWSER] Halaman selector merchant. Mencari '{target_name}'...")
                try:
                    # Cari merchant dengan nama target
                    items = driver.find_elements(By.CSS_SELECTOR, ".listItem, .merchant-item, li")
                    for item in items:
                        text = (item.text or "").strip()
                        if target_name.lower() in text.lower() and item.is_displayed():
                            driver.execute_script("arguments[0].click();", item)
                            time.sleep(3)
                            break
                except Exception as e:
                    log.warning(f"  ⚠️ Tidak bisa pilih merchant: {e}")

        # ── Step 5: Ekstrak token ─────────────────────────────────────────────
        log.info("🔑 [PUSH_BROWSER] Mengekstrak token dari browser...")
        tob_token, entity_id = _trigger_tokens(driver)
        if not tob_token:
            log.error("❌ [PUSH_BROWSER] Gagal mengekstrak shopee_tob_token.")
            return None

        all_cookies = _get_all_cookies(driver)

        # Simpan session ke file untuk referensi berikutnya
        automation_data = AUTOMATION_DIR / "data"
        automation_data.mkdir(parents=True, exist_ok=True)
        session_file = automation_data / f"session_{username}.json"
        session_file.write_text(json.dumps({
            "username": username,
            "shopee_tob_token": tob_token,
            "shopee_tob_entity_id": entity_id or "",
            "saved_at": datetime.now().isoformat(),
            "extra_cookies": all_cookies
        }, indent=2))
        log.info(f"💾 [PUSH_BROWSER] Session disimpan ke {session_file}")

        return {
            "shopee_tob_token": tob_token,
            "shopee_tob_entity_id": entity_id or "",
            "extra_cookies": all_cookies
        }

    except Exception as e:
        log.error(f"❌ [PUSH_BROWSER] Exception: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
