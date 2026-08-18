#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import csv
import requests
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
from dotenv import load_dotenv, set_key
from playwright.sync_api import sync_playwright

# Muat file .env dari folder menu
MENU_DIR = Path(__file__).resolve().parent
ENV_PATH = MENU_DIR / ".env"
load_dotenv(ENV_PATH)

# Master credential Google Sheet
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ3tLKBNXDqRgBw0mNhKZFxgvKx-JoiTDzm_s5Ix1cm7O6HCv4IvExOLR2HSRVaXSsx82V348mcr9X4/pub?gid=0&single=true&output=csv"


def normalisasi_nomor_hp(nomor_hp):
    if not nomor_hp:
        return ""
    nomor_hp = str(nomor_hp).strip()
    if "@" in nomor_hp:
        return nomor_hp
    nomor_hp = re.sub(r'\D', '', nomor_hp)
    if nomor_hp.startswith("62"):
        return nomor_hp[2:]
    if nomor_hp.startswith("0"):
        return nomor_hp[1:]
def safe_goto_with_retry(
    page,
    url,
    wait_until="domcontentloaded",
    timeout=30000,
    max_attempts=3,
    ready_selector=None,
    ready_timeout=15000,
):
    """
    Mekanisme navigasi aman dengan reload 2x (total 3 attempt) jika terjadi Timeout Error
    saat mengakses halaman portal GoFood.
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        navigated = False
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            navigated = True
        except Exception as e:
            last_err = e
            print(f"   ⚠️ [Timeout/Error] Navigasi ke {url} gagal pada percobaan {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                print(f"   🔄 [Reload Mekanisme 2x] Melakukan reload / re-try navigasi ke {url} (Coba {attempt}/{max_attempts - 1})...")
                time.sleep(2.0)
                try:
                    if page.url and page.url != "about:blank":
                        page.reload(wait_until=wait_until, timeout=timeout)
                        navigated = True
                        print(f"   ✅ Reload berhasil untuk {url}")
                except Exception as reload_err:
                    print(f"   ⚠️ Reload gagal ({reload_err}), mencoba page.goto ulang...")
                    last_err = reload_err
        if not navigated:
            continue
        if ready_selector:
            try:
                page.wait_for_selector(ready_selector, timeout=ready_timeout, state="visible")
            except Exception as ready_err:
                last_err = ready_err
                print(f"   ⚠️ Halaman termuat tetapi elemen target belum siap pada percobaan {attempt}/{max_attempts}: {ready_err}")
                if attempt < max_attempts:
                    time.sleep(2.0)
                    continue
                raise ready_err
        return True
    if last_err:
        raise last_err
    return False


def fetch_gofood_outlets():
    """
    Mengambil semua outlet GoFood Live dari master Google Sheet.
    Mendeteksi kolom Email Login Go 1, Email Login Go 2, dan Nomor HP secara dinamis.
    """
    try:
        cache_buster_url = MASTER_SHEET_URL + f"&t={int(time.time())}"
        resp = requests.get(cache_buster_url, timeout=30)
        resp.raise_for_status()
        reader_rows = list(csv.reader(resp.text.splitlines()))
    except Exception as e:
        print(f"❌ Gagal mengambil Google Sheet master: {e}")
        return []

    if not reader_rows:
        return []

    header = [str(h).strip().lower() for h in reader_rows[0]]

    def col_idx(names):
        for n in names:
            for i, h in enumerate(header):
                if n in h:
                    return i
        return None

    idx_aplikasi = col_idx(['aplikasi'])
    idx_status   = col_idx(['status'])
    idx_outlet   = col_idx(['nama outlet'])
    idx_cabang   = col_idx(['cabang'])
    idx_store    = col_idx(['store id', 'store_id', 'merchant id'])
    
    # Cari kolom email secara dinamis
    idx_email1 = col_idx(['email login go 1'])
    if idx_email1 is None:
        idx_email1 = 24  # Fallback Kolom Y (0-indexed)
        
    idx_email2 = col_idx(['email login go 2'])
    if idx_email2 is None:
        idx_email2 = 25  # Fallback Kolom Z (0-indexed)

    # Cari nomor hp untuk Superfood secara dinamis (Nomor HP setelah akses superfood/login go 1)
    idx_phone = 27  # Default fallback ke index 27 (Kolom AB)
    idx_superfood = None
    for i, h in enumerate(header):
        if 'akses superfood' in h or 'login go 1' in h:
            idx_superfood = i
            break
    if idx_superfood is not None:
        for i in range(idx_superfood, len(header)):
            if 'nomor hp' in header[i]:
                idx_phone = i
                break

    outlets = []
    for row in reader_rows[1:]:
        if len(row) <= idx_phone:
            continue

        aplikasi = str(row[idx_aplikasi]).strip().lower() if idx_aplikasi is not None and len(row) > idx_aplikasi else ''
        status   = str(row[idx_status]).strip().lower()   if idx_status is not None and len(row) > idx_status else ''

        if 'gofood' not in aplikasi:
            continue
        if 'live' not in status:
            continue

        email1 = str(row[idx_email1]).strip() if len(row) > idx_email1 else ''
        email2 = str(row[idx_email2]).strip() if len(row) > idx_email2 else ''
        
        emails = []
        if email1 and email1 != "-":
            emails.append(email1)
        if email2 and email2 != "-" and email2 != email1:
            emails.append(email2)
            
        primary_email = emails[0] if emails else ""
        phone    = str(row[idx_phone]).strip() if len(row) > idx_phone else ''
        nama     = str(row[idx_outlet]).strip() if idx_outlet is not None and len(row) > idx_outlet else ''
        cabang   = str(row[idx_cabang]).strip() if idx_cabang is not None and len(row) > idx_cabang else ''
        store_id = str(row[idx_store]).strip()  if idx_store is not None  and len(row) > idx_store  else ''

        outlets.append({
            'nama_outlet': nama,
            'cabang'     : cabang,
            'email'      : primary_email,
            'emails'     : emails,
            'phone'      : phone,
            'store_id'   : store_id,
        })

    return outlets


def ambil_otp_dari_endpoint(url_dasar, action="getOtp", label_email=None):
    if not url_dasar:
        raise ValueError("URL endpoint OTP kosong.")

    if "docs.google.com/spreadsheets" in url_dasar:
        try:
            with urlopen(url_dasar, timeout=30) as response:
                content = response.read().decode("utf-8").strip()
                lines = content.splitlines()
                if not lines or len(lines) < 2:
                    return ""
                reader = csv.reader(lines)
                rows = list(reader)
                headers = [h.strip().lower() for h in rows[0]]
                
                otp_idx = -1
                for idx, h in enumerate(headers):
                    if "otp" in h:
                        otp_idx = idx
                        break
                
                if otp_idx == -1:
                    otp_idx = 1 if len(rows[0]) > 1 else 0
                    
                last_row = rows[-1]
                if len(last_row) > otp_idx:
                    return last_row[otp_idx].strip()
                return ""
        except Exception as e:
            print(f"⚠️ Gagal membaca OTP dari Sheets: {e}")
            return ""

    parsed = urlparse(url_dasar)
    query_params = dict(parse_qsl(parsed.query))
    query_params["action"] = action
    if label_email:
        query_params["label"] = label_email
    url_final = urlunparse(parsed._replace(query=urlencode(query_params)))

    with urlopen(url_final, timeout=30) as response:
        return response.read().decode("utf-8").strip()


def tunggu_otp_terbaru(url_dasar, action="getOtp", label_email=None, interval_detik=3, otp_awal_override=None, timeout_detik=15):
    """
    Menunggu OTP terbaru yang berbeda dari nilai awal agar tidak memakai OTP sebelumnya.
    otp_awal_override: Jika diisi, gunakan nilai ini sebagai baseline (snapshot sebelum OTP dikirim).
    """
    if otp_awal_override is not None:
        otp_awal = otp_awal_override
    else:
        try:
            otp_awal = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
        except Exception:
            otp_awal = ""
    
    batas_waktu = time.time() + timeout_detik
    print(f"   🤖 Menunggu OTP baru masuk ke inbox (maksimal {timeout_detik} detik)...")

    while time.time() < batas_waktu:
        time.sleep(interval_detik)
        try:
            otp_baru = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
            if otp_baru and otp_baru != otp_awal:
                return otp_baru
        except Exception:
            pass

    return otp_awal


def tutup_semua_popup(page):
    """
    Dismisses common popups, cookie consent banners, and onboarding overlays
    to prevent intercepting clicks on target elements.
    """
    print("   🤖 Mencoba mendeteksi dan menutup pop-up/cookie banner...")
    
    # 1. Cookie consent
    cookie_selectors = [
        'button:has-text("Terima Semua Cookie")',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Terima")',
        'button:has-text("Accept")'
    ]
    for sel in cookie_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                print(f"   ✅ Cookie banner ditutup ({sel})")
                time.sleep(0.5)
        except Exception:
            pass

    # 2. Tutorial / Lewati / Onboarding
    dismiss_selectors = [
        'button:has-text("Lewati")',
        'button:has-text("Lewati Tutorial")',
        'button:has-text("Selesai")',
        'button:has-text("Tutup")',
        'button:has-text("Nanti Saja")',
        '[aria-label="close"]',
        '[aria-label="Close"]',
        'button.close',
        '.dismiss-button',
        'button[class*="close"]',
        'button:has-text("×")',
        'button:has-text("✕")'
    ]
    for sel in dismiss_selectors:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                candidate = loc.nth(i)
                if candidate.is_visible():
                    candidate.click(timeout=1500)
                    print(f"   ✅ Pop-up/Tutorial ditutup ({sel})")
                    time.sleep(0.5)
        except Exception:
            pass


SESSION_FILE = MENU_DIR / "Gofood" / "gofood_sessions.json"

def load_gofood_session(identifier):
    if not identifier:
        return None
    ident_str = str(identifier).strip().lower()
    if ident_str in ("", "-", "nan", "none", "null"):
        return None
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', ident_str)
    json_file = MENU_DIR / "Gofood" / f"session_gofood_{sanitized}.json"
    if not json_file.exists():
        phone_norm = normalisasi_nomor_hp(identifier)
        if phone_norm:
            json_file_old = MENU_DIR / f"session_{phone_norm}.json"
            if json_file_old.exists():
                json_file = json_file_old
    if not json_file.exists():
        return None
    try:
        with open(json_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def save_gofood_session(identifier, session_data):
    if not identifier:
        return
    ident_str = str(identifier).strip().lower()
    if ident_str in ("", "-", "nan", "none", "null"):
        return
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', ident_str)
    json_file = MENU_DIR / "Gofood" / f"session_gofood_{sanitized}.json"
    try:
        os.makedirs(os.path.dirname(json_file), exist_ok=True)
        with open(json_file, 'w') as f:
            json.dump(session_data, f, indent=4)
        phone_norm = normalisasi_nomor_hp(identifier)
        if phone_norm and phone_norm != sanitized:
            json_file_old = MENU_DIR / f"session_{phone_norm}.json"
            with open(json_file_old, 'w') as f:
                json.dump(session_data, f, indent=4)
    except Exception as e:
        print(f"   ⚠️ Gagal menyimpan berkas sesi untuk {identifier}: {e}")


def login_outlet(outlet_info, proxy_config=None):
    """
    Membuka browser Chromium untuk login otomatis 1 outlet.
    Menangkap token, menyimpannya di .env, dan mengembalikannya.
    """
    store_id = outlet_info.get('store_id')
    nama = outlet_info.get('nama_outlet') or outlet_info.get('merchant_name') or ''
    cabang = outlet_info.get('cabang', '')
    
    emails_to_try = outlet_info.get('emails', [])
    phone = outlet_info.get('phone_raw', '') or outlet_info.get('phone', '')
    
    # Try to enrich the info from Google Sheet
    try:
        sheet_outlets = fetch_gofood_outlets()
        matched_outlet = None
        if store_id:
            matched_outlet = next((o for o in sheet_outlets if str(o.get('store_id')) == str(store_id)), None)
        if not matched_outlet and nama:
            matched_outlet = next((o for o in sheet_outlets if o.get('nama_outlet') == nama and o.get('cabang') == cabang), None)
            
        if matched_outlet:
            if not emails_to_try:
                emails_to_try = matched_outlet.get('emails', [])
            if not phone:
                phone = matched_outlet.get('phone', '')
    except Exception as e:
        print(f"   ⚠️ Gagal memperkaya data outlet dari Google Sheet: {e}")
        
    if not emails_to_try:
        single_email = outlet_info.get('email', '') or outlet_info.get('username', '')
        if single_email:
            emails_to_try = [single_email]

    label = f"{nama} - {cabang}" if cabang and cabang != 'Tanpa Cabang' else nama

    print(f"\n🔄 Membuka browser untuk login otomatis ke: {label}")
    if emails_to_try:
        print(f"   📧 Emails: {', '.join(emails_to_try)}")
    if phone:
        print(f"   📱 Phone: {phone}")

    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")
    if proxy_config is None and use_proxy and proxy_server:
        parsed = urlparse(proxy_server)
        if parsed.username and parsed.password:
            server_url = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server_url += f":{parsed.port}"
            proxy_config = {"server": server_url, "username": parsed.username, "password": parsed.password}
        else:
            proxy_config = {"server": proxy_server}

    headless_mode = True
    try:
        env_headless = os.getenv("HEADLESS") or os.getenv("HEADLESS_GOFOOD")
        if env_headless is not None:
            headless_mode = env_headless.lower() in ("true", "1", "yes")
    except Exception:
        pass

    if not os.getenv("DISPLAY"):
        headless_mode = True

    result = None

    chrome_process = None
    chrome_log = None
    try:
        import socket
        import subprocess
        import time
        use_system_chromium = os.path.exists("/usr/lib/chromium/chromium") or os.path.exists("/usr/bin/chromium")

        if use_system_chromium:
            def get_free_port():
                s = socket.socket()
                s.bind(('', 0))
                port = s.getsockname()[1]
                s.close()
                return port

            cdp_port = get_free_port()
            chromium_bin = "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else "/usr/bin/chromium"
            chrome_args = [
                chromium_bin,
                "--no-sandbox",
                "--no-zygote",
                "--in-process-gpu",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-gpu-sandbox",
                "--dbus-stub",
                f"--remote-debugging-port={cdp_port}",
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--window-size=1366,768'
            ]
            if use_proxy and proxy_server:
                chrome_args.append(f"--proxy-server={proxy_server}")

            if headless_mode:
                chrome_args.append("--headless=new")

            os.makedirs("logs", exist_ok=True)
            chrome_log = open("logs/chrome_err.log", "a")
            chrome_process = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=chrome_log
            )
            time.sleep(4.0)
            poll = chrome_process.poll()
            if poll is not None:
                print(f"ERROR: Chromium process exited immediately with code {poll}!")

            p = sync_playwright().start()
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        else:
            p = sync_playwright().start()
            browser = p.chromium.launch(
                headless=headless_mode,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--no-sandbox',
                    '--disable-gpu',
                    '--disable-dev-shm-usage'
                ]
            )

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768},
            proxy=proxy_config
        )

        import random

        def normalize_token(raw_token):
            token = str(raw_token or "").strip()
            if not token:
                return ""
            if token.lower().startswith("bearer "):
                return token.split(" ", 1)[1].strip()
            return token
        
        access_token = None
        session_loaded_successfully = False
        logged_in_email = None

        # Check if we have a cached session for one of the emails or phone
        cached_identifier = None
        cached_data = None
        for email in emails_to_try:
            cached_data = load_gofood_session(email)
            if cached_data:
                cached_identifier = email
                break
        if not cached_data and phone:
            cached_data = load_gofood_session(phone)
            if cached_data:
                cached_identifier = phone

        if cached_data and cached_data.get('cookies'):
            try:
                print(f"   🔑 Ditemukan sesi aktif untuk {cached_identifier}. Mencoba memuat sesi...")
                context.add_cookies(cached_data['cookies'])
                
                page = context.new_page()
                safe_goto_with_retry(page, "https://portal.gofoodmerchant.co.id/dashboard", wait_until="domcontentloaded")
                time.sleep(2.0)

                # Check if we are logged in (i.e. URL does not contain /auth or /login)
                current_url = page.url
                if "/auth" not in current_url and "login" not in current_url:
                    token_candidate = normalize_token(cached_data.get('access_token'))
                    if not token_candidate:
                        try:
                            for c in context.cookies():
                                if c.get('name') in ('access_token', 'token', 'gobiz_token'):
                                    token_candidate = normalize_token(c.get('value'))
                                    if token_candidate:
                                        break
                        except Exception:
                            pass
                    if not token_candidate:
                        try:
                            token_eval = page.evaluate("""() => {
                                const keys = ['token', 'access_token', 'accessToken', 'auth_token', 'authorization', 'gobiz-token', 'go-id-token'];
                                const fromStorage = (storage) => {
                                    for (const k of keys) {
                                        try {
                                            const v = storage.getItem(k);
                                            if (v) return v;
                                        } catch (_) {}
                                    }
                                    for (let i = 0; i < storage.length; i++) {
                                        try {
                                            const key = storage.key(i);
                                            const val = storage.getItem(key);
                                            if (val && /bearer|eyj[a-z0-9_-]{10,}/i.test(val)) return val;
                                        } catch (_) {}
                                    }
                                    return '';
                                };
                                return fromStorage(localStorage) || fromStorage(sessionStorage) || '';
                            }""")
                            token_candidate = normalize_token(token_eval)
                        except Exception:
                            pass

                    if token_candidate:
                        # Sesi terdeteksi, uji apakah navigasi ke menu-items tetap valid
                        if store_id:
                            store_id_cached = str(store_id).strip()
                            safe_goto_with_retry(
                                page,
                                f"https://portal.gofoodmerchant.co.id/gofood/{store_id_cached}/menu-items",
                                wait_until="domcontentloaded",
                                timeout=45000,
                            )
                            time.sleep(2.0)
                        
                        # Verifikasi apakah URL di-redirect kembali ke auth/login
                        if "/auth" in page.url or "login" in page.url:
                            print(f"   ⚠️ Sesi kedaluwarsa saat membuka halaman menu ({page.url}). Memaksa fresh login ulang...")
                            context.clear_cookies()
                            try:
                                page.close()
                            except Exception:
                                pass
                            sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', str(cached_identifier).strip().lower())
                            old_session = MENU_DIR / "Gofood" / f"session_gofood_{sanitized_id}.json"
                            if old_session.exists():
                                try: os.remove(old_session)
                                except Exception: pass
                        else:
                            print(f"   ✅ Sesi berhasil dimuat! Melewati login OTP untuk {cached_identifier}.")
                            access_token = token_candidate
                            session_loaded_successfully = True
                            logged_in_email = cached_identifier if "@" in str(cached_identifier) else None
                    else:
                        print(f"   ⚠️ Sesi terlihat login tetapi token tidak ditemukan untuk {cached_identifier}. Memaksa login ulang...")
                        context.clear_cookies()
                        page.close()
                        sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', str(cached_identifier).strip().lower())
                        old_session = MENU_DIR / "Gofood" / f"session_gofood_{sanitized_id}.json"
                        if old_session.exists():
                            try: os.remove(old_session)
                            except Exception: pass
                else:
                    print(f"   ⚠️ Sesi kedaluwarsa untuk {cached_identifier} (URL: {current_url}). Melakukan login ulang...")
                    context.clear_cookies()
                    page.close()
                    sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', str(cached_identifier).strip().lower())
                    old_session = MENU_DIR / "Gofood" / f"session_gofood_{sanitized_id}.json"
                    if old_session.exists():
                        try: os.remove(old_session)
                        except Exception: pass
            except Exception as e:
                print(f"   ⚠️ Gagal memuat sesi: {e}. Melakukan login ulang...")
                try:
                    context.clear_cookies()
                    page.close()
                except Exception:
                    pass

        if session_loaded_successfully:
            emails_to_try = []

        for email_idx, current_email in enumerate(emails_to_try):
            if access_token:
                break
                
            max_login_attempts = 2
            attempts_made = 0
            email_input_selector = 'input[type="email"]:visible, input[name="email"]:visible, input[placeholder*="email" i]:visible, input[type="text"]:visible'
            
            while attempts_made < max_login_attempts:
                attempt = attempts_made
                attempts_made += 1

                if access_token:
                    break
                    
                page = context.new_page()
                if current_email:
                    print(f"\n   ➡️ [Email: {current_email}] Membuka halaman login email langsung... (Percobaan {attempt + 1}/{max_login_attempts})")
                    try:
                        safe_goto_with_retry(
                            page,
                            "https://portal.gofoodmerchant.co.id/auth/login/email",
                            wait_until="domcontentloaded",
                            timeout=45000,
                            ready_selector=email_input_selector,
                            ready_timeout=25000,
                        )
                    except Exception as email_nav_err:
                        print(f"   ⚠️ Halaman /auth/login/email gagal ({email_nav_err}). Mencoba buka /auth/login lalu pindah ke login Email...")
                        safe_goto_with_retry(
                            page,
                            "https://portal.gofoodmerchant.co.id/auth/login",
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        switched_to_email = False
                        for sel in [
                            'a[href*="/auth/login/email"]',
                            'button:has-text("Email")',
                            'a:has-text("Email")',
                            'button:has-text("Masuk dengan Email")',
                            'a:has-text("Masuk dengan Email")',
                        ]:
                            try:
                                loc = page.locator(sel).first
                                if loc.count() > 0 and loc.is_visible():
                                    loc.click()
                                    switched_to_email = True
                                    break
                            except Exception:
                                pass
                        if not switched_to_email:
                            try:
                                safe_goto_with_retry(
                                    page,
                                    "https://portal.gofoodmerchant.co.id/auth/login/email",
                                    wait_until="domcontentloaded",
                                    timeout=45000,
                                )
                            except Exception:
                                pass
                        page.wait_for_selector(email_input_selector, timeout=25000, state="visible")
                else:
                    print(f"\n   ➡️ Membuka halaman login... (Percobaan {attempt + 1}/{max_login_attempts})")
                    safe_goto_with_retry(
                        page,
                        "https://portal.gofoodmerchant.co.id/auth/login",
                        wait_until="domcontentloaded",
                        timeout=45000,
                        ready_selector=email_input_selector,
                        ready_timeout=25000,
                    )

                time.sleep(1.0)
                
                otp_failed_timeout = False
                is_banned = False

                otp_endpoint = os.getenv("OTP_ENDPOINT_URL")
                label_email_cfg = os.getenv("GMAIL_OTP_LABEL", "OTP-GO")
                action_type = "getOtpEmail" if current_email else "getOtp"
                otp_snapshot_awal = ""

                # --- STEP 4: Ketik email secara human-like ---
                if current_email:
                    try:
                        email_input = page.wait_for_selector(
                            email_input_selector,
                            timeout=15000
                        )
                        if email_input:
                            email_input.click()
                            time.sleep(0.3)
                            email_input.focus()
                            time.sleep(0.3)
                            for char in current_email:
                                email_input.type(char, delay=0)
                                time.sleep(random.uniform(0.05, 0.15))
                            time.sleep(0.5)

                            submit_btn = page.locator('button:has-text("Lanjut"), button:has-text("Submit"), button:has-text("Masuk"), button[type="submit"]')
                            if submit_btn.count() > 0:
                                submit_btn.first.click()
                            else:
                                email_input.press("Enter")
                            time.sleep(3)

                            # --- Pre-snapshot OTP sebelum tombol OTP diklik ---
                            if otp_endpoint:
                                try:
                                    otp_snapshot_awal = ambil_otp_dari_endpoint(otp_endpoint, action=action_type, label_email=label_email_cfg)
                                    print(f"   📸 Snapshot OTP awal: '{otp_snapshot_awal or '(kosong)'}' (sebelum OTP dikirim)")
                                except Exception:
                                    otp_snapshot_awal = ""

                            # Jika ada halaman pilihan login (password/OTP)
                            try:
                                btn_otp = page.locator('button:has-text("Masuk dengan OTP"), a:has-text("Masuk dengan OTP")').first
                                if btn_otp.count() > 0 and btn_otp.is_visible():
                                    btn_otp.click()
                                    print("   ✅ Tombol 'Masuk dengan OTP' diklik. OTP sedang dikirim...")
                                    time.sleep(2)
                            except Exception:
                                pass

                            # --- STEP 5: Automated OTP Polling & Fill ---
                            if otp_endpoint:
                                try:
                                    print("   🤖 Menunggu field OTP muncul...")
                                    otp_input_selector = 'input[autocomplete="one-time-code"], input[aria-label*="digit" i], div[class*="otp" i] input:not([type="checkbox"]):not([type="radio"]), input[name*="otp" i]:not([type="checkbox"]):not([type="radio"]), input[maxlength="1"]:not([type="checkbox"]):not([type="radio"])'
                                    
                                    otp_appeared = False
                                    start_wait_otp = time.time()
                                    while time.time() - start_wait_otp < 15:
                                        if page.locator(otp_input_selector).count() > 0 and page.locator(otp_input_selector).first.is_visible():
                                            otp_appeared = True
                                            break
                                        
                                        # Fast-fail deteksi Limit/Banned
                                        try:
                                            ban_msg1 = page.locator('text=/terlalu banyak/i')
                                            ban_msg2 = page.locator('text=/coba lagi/i')
                                            ban_msg3 = page.locator('text=/15 menit/i')
                                            if (ban_msg1.count() > 0 and ban_msg1.first.is_visible()) or \
                                               (ban_msg2.count() > 0 and ban_msg2.first.is_visible()) or \
                                               (ban_msg3.count() > 0 and ban_msg3.first.is_visible()):
                                                print("   ⚠️ Terdeteksi teks peringatan Limit/Banned. Membatalkan tunggu OTP...")
                                                break
                                        except Exception:
                                            pass
                                            
                                        time.sleep(1.0)
                                        
                                    if not otp_appeared:
                                        raise Exception("OTP Field timeout atau akun terindikasi banned")
                                        
                                    time.sleep(1)
                                except Exception as e:
                                    print(f"   ⚠️ {e}: Field OTP tidak muncul. Indikasi limit/banned 15 menit untuk email {current_email}. Menghentikan percobaan dan rotasi akun.")
                                    is_banned = True
                                    try:
                                        page.close()
                                    except Exception:
                                        pass
                                    break  # Keluar dari loop attempt, langsung rotasi ke email berikutnya

                                # 2. Lakukan polling dan input OTP
                                if not is_banned:
                                    try:
                                        print("   🤖 Polling OTP dari Gmail (snapshot awal sudah diambil sebelumnya)...")
                                        
                                        otp_code = tunggu_otp_terbaru(otp_endpoint, action=action_type, label_email=label_email_cfg, interval_detik=3, otp_awal_override=otp_snapshot_awal, timeout_detik=15)
                                        
                                        if otp_code and not (otp_code.isdigit() and len(otp_code) in (4, 6)):
                                            print(f"   ⚠️ OTP dari endpoint bukan format angka valid: {otp_code[:50]}...")
                                            otp_code = None
                                            
                                        if otp_code:
                                            print(f"   🤖 OTP didapat: {otp_code}. Memasukkan OTP...")
                                            otp_fields = page.locator(otp_input_selector).all()
                                            if len(otp_fields) > 0:
                                                otp_fields[0].focus()
                                                time.sleep(0.5)
                                                otp_fields[0].type(otp_code, delay=300)
                                                print("   ✅ OTP berhasil diisi otomatis.")
                                                
                                                time.sleep(1)
                                                submit_otp_btn = page.locator('button:has-text("Masuk"), button:has-text("Konfirmasi"), button:has-text("Verifikasi"), button:has-text("Lanjut"), button[type="submit"]')
                                                clicked = False
                                                for i in range(submit_otp_btn.count()):
                                                    btn = submit_otp_btn.nth(i)
                                                    if btn.is_visible() and btn.is_enabled():
                                                        print(f"   🤖 Mengklik tombol OTP: '{btn.text_content().strip()}'")
                                                        btn.click()
                                                        clicked = True
                                                        break
                                                if not clicked:
                                                    print("   🤖 Mengirim Enter sebagai fallback...")
                                                    page.keyboard.press("Enter")
                                                time.sleep(2)
                                        else:
                                            print("   ⚠️ Gagal mendapatkan OTP dalam 15 detik (atau format tidak valid).")
                                            otp_failed_timeout = True
                                    except Exception as e:
                                        print(f"   ⚠️ Gagal melakukan automasi OTP: {e}.")
                                        otp_failed_timeout = True
                            else:
                                print("   👉 Silakan isi kode OTP secara MANUAL di browser.")
                    except Exception as e:
                        print(f"   ⚠️ Gagal ketik email: {e}")

                if is_banned:
                    continue

                if otp_failed_timeout:
                    if attempt < max_login_attempts - 1:
                        print("   ⚠️ Menutup halaman dan menunggu 15 detik sebelum mengulang login (attempt ke-2)...")
                        try:
                            page.close()
                        except Exception:
                            pass
                        time.sleep(15)
                        continue
                    else:
                        print(f"   ⚠️ Melewati batas percobaan login untuk {current_email}. Rotasi ke email berikutnya/gagal.")
                        try:
                            page.close()
                        except Exception:
                            pass
                        continue

                # --- Tunggu access_token muncul di cookies (max 15 detik) ---
                attempt_token = None
                start_time = time.time()
                try:
                    while True:
                        if page.is_closed():
                            print("⚠️ Browser ditutup sebelum login selesai.")
                            break

                        try:
                            cookies = context.cookies()
                        except Exception as cookie_err:
                            print(f"   ⚠️ Context browser tertutup saat membaca cookies: {cookie_err}")
                            break
                        for cookie in cookies:
                            if cookie['name'] == 'access_token':
                                attempt_token = cookie['value']
                                break

                        if attempt_token:
                            access_token = attempt_token
                            logged_in_email = current_email
                            break

                        # Deteksi akun baru yang butuh verifikasi email
                        try:
                            error_msg1 = page.locator('text=/Email belum diverifikasi/i')
                            error_msg2 = page.locator('text=/silahkan login ulang/i')
                            if (error_msg1.count() > 0 and error_msg1.first.is_visible()) or \
                               (error_msg2.count() > 0 and error_msg2.first.is_visible()):
                                print("   ⚠️ Terdeteksi akun baru: 'Email belum diverifikasi'. Mempercepat percobaan ulang...")
                                max_login_attempts = 3
                                time.sleep(2.0)
                                break
                        except Exception:
                            pass

                        # Deteksi OTP Salah / Kadaluarsa
                        try:
                            otp_err1 = page.locator('text=/kode salah/i')
                            otp_err2 = page.locator('text=/tidak valid/i')
                            otp_err3 = page.locator('text=/kadaluarsa/i')
                            if (otp_err1.count() > 0 and otp_err1.first.is_visible()) or \
                               (otp_err2.count() > 0 and otp_err2.first.is_visible()) or \
                               (otp_err3.count() > 0 and otp_err3.first.is_visible()):
                                print("   ⚠️ Terdeteksi pesan 'OTP Salah/Tidak Valid'. Mempercepat percobaan ulang...")
                                break
                        except Exception:
                            pass

                        # Deteksi Ban 15 Menit setelah submit OTP
                        try:
                            ban_err1 = page.locator('text=/terlalu banyak/i')
                            ban_err2 = page.locator('text=/coba lagi/i')
                            ban_err3 = page.locator('text=/15 menit/i')
                            if (ban_err1.count() > 0 and ban_err1.first.is_visible()) or \
                               (ban_err2.count() > 0 and ban_err2.first.is_visible()) or \
                               (ban_err3.count() > 0 and ban_err3.first.is_visible()):
                                print("   ⚠️ Terdeteksi teks Limit/Banned. Membatalkan tunggu token...")
                                is_banned = True
                                break
                        except Exception:
                            pass

                        time.sleep(1.0)

                        if time.time() - start_time > 5:
                            try:
                                if "/auth/login" in page.url:
                                    print("   ⚠️ (Fallback) Timeout 5 detik: URL masih stuck di halaman login. Mempercepat percobaan ulang...")
                                    max_login_attempts = 3
                                    break
                            except Exception:
                                pass

                        if time.time() - start_time > 15:
                            print("⚠️ Timeout 15 detik menunggu access_token.")
                            break

                except KeyboardInterrupt:
                    print("\n⚠️ Dibatalkan oleh pengguna.")
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")

                if not access_token:
                    try:
                        page.close()
                    except Exception:
                        pass

                    if is_banned:
                        print(f"   ⚠️ Akun {current_email} terindikasi Limit/Banned. Langsung rotasi ke email berikutnya.")
                        break

                    if attempt < max_login_attempts - 1:
                        print(f"   ⚠️ Token tidak ditemukan. Kembali ke login page dengan email yang sama ({current_email})...")
                        continue
                    else:
                        print(f"   ⚠️ Token tidak ditemukan setelah {max_login_attempts} percobaan untuk {current_email}. Rotasi ke email berikutnya...")

        if access_token:
            print(f"🎉 LOGIN SUKSES untuk {label}!")

            # --- HANDLE CHOOSE OUTLET / BRAND PAGE (IF APPLICABLE) ---
            print("   🤖 Memeriksa apakah berada di halaman pemilihan outlet/merchant...")
            try:
                # Tunggu URL berubah ke salah satu halaman utama (dashboard, analytics, choose, outlet)
                page.wait_for_url(re.compile(r".*(dashboard|analytics|choose|outlet).*"), timeout=15000)
            except Exception:
                pass

            current_url = page.url
            print(f"   🤖 URL saat ini setelah login: {current_url}")
            
            if "/auth" in current_url or "login" in current_url:
                print(f"   ⚠️ URL saat ini masih di {current_url}. Sesi kedaluwarsa/invalid.")
                access_token = None
                session_loaded_successfully = False
                context.clear_cookies()
                if cached_identifier:
                    sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', str(cached_identifier).strip().lower())
                    old_session = MENU_DIR / "Gofood" / f"session_gofood_{sanitized_id}.json"
                    if old_session.exists():
                        try: os.remove(old_session)
                        except Exception: pass
                raise RuntimeError(f"Halaman masih terdampar di {current_url} (unauthenticated). Sesi tidak valid, perlu fresh login.")

            # Jika URL mengandung 'choose' atau 'choose-outlet', kita perlu memilih merchant
            elif "choose" in current_url or "outlet" in current_url:
                tutup_semua_popup(page)
                search_name = outlet_info.get('nama_resto_final') or outlet_info.get('nama_outlet') or ''
                brand_name = outlet_info.get('brand') or ''
                
                print(f"   🤖 Halaman pemilihan terdeteksi. Mencari cabang: {search_name or brand_name}...")
                
                chosen = False
                # Coba beberapa nama pencarian
                candidates = [search_name, brand_name]
                if search_name:
                    candidates.append(search_name.replace(',', ''))
                    words = [w.strip() for w in search_name.replace(',', ' ').split() if len(w.strip()) > 2]
                    common_words = {'rm', 'depot', 'warung', 'sate', 'resto', 'restaurant', 'kuliner', 'kedai'}
                    filtered_words = [w for w in words if w.lower() not in common_words]
                    if filtered_words:
                        candidates.append(" ".join(filtered_words[:2]))
                
                for candidate in candidates:
                    if not candidate or candidate.lower() == 'nan':
                        continue
                    try:
                        print(f"   🤖 Mencoba mencari element dengan teks: '{candidate}'")
                        outlet_element = page.locator(f"text={candidate}").first
                        if outlet_element.count() > 0 and outlet_element.is_visible():
                            outlet_element.click(force=True)
                            print(f"   ✅ Berhasil memilih cabang dengan teks '{candidate}'")
                            chosen = True
                            break
                    except Exception:
                        continue
                
                if not chosen:
                    print("   ⚠️ Cabang target tidak ditemukan di halaman pemilihan, mencoba mengklik element pertama yang tersedia...")
                    try:
                        first_card = page.locator('[class*="card" i], [class*="item" i], a, button').filter(has_text=re.compile(r".+")).first
                        if first_card.count() > 0:
                            first_card.click(force=True)
                            print("   ✅ Mengklik element/kartu pertama sebagai fallback.")
                    except Exception as e:
                        print(f"   ⚠️ Gagal melakukan fallback pemilihan cabang: {e}")
            
            # Tunggu hingga halaman beralih ke dashboard/analytics
            try:
                page.wait_for_url(re.compile(r".*(dashboard|analytics|gofood).*"), timeout=20000)
                print(f"   🤖 Masuk ke halaman utama: {page.url}")
            except Exception:
                print("   ⚠️ Timeout menunggu pengalihan ke dashboard/halaman utama.")

            # --- REDIRECT TO MENUS PAGE AND INTERCEPT API ---
            store_id = outlet_info.get('store_id', '')
            captured_menu = None
            captured_restaurant_id = None
            captured_modifiers = []
            captured_v2_group_id = None
            captured_x_passkey = None
            if store_id:
                store_id_clean = str(store_id).strip()
                print(f"   🤖 Target Store ID: {store_id_clean}")
                try:
                    # Capture x-passkey dari request headers
                    def handle_request_passkey(req):
                        nonlocal captured_x_passkey
                        if 'gojekapi.com' in req.url and req.headers.get('x-passkey'):
                            captured_x_passkey = req.headers['x-passkey']

                    # Register response listener to capture API response asynchronously
                    def handle_response(response):
                        nonlocal captured_menu, captured_restaurant_id, captured_v2_group_id
                        url_lower = response.url.lower()

                        if "/restaurants/" in url_lower or "/outlets/" in url_lower or "/gofood/" in url_lower:
                            parts = response.url.split("/")
                            for idx, part in enumerate(parts):
                                if part.lower() in ("restaurants", "outlets", "gofood") and idx + 1 < len(parts):
                                    cand = parts[idx + 1].split("?")[0]
                                    if cand and cand not in ("menu-items", "menu", "menus", ""):
                                        captured_restaurant_id = cand
                                        break

                        # Capture v2_menus_group_id dari endpoint /v2/menu_groups/{gid}/menus
                        if "/v2/menu_groups/" in response.url and "/menus" in response.url and "variant" not in response.url:
                            try:
                                if response.status == 200:
                                    parts = response.url.split("/")
                                    for idx, part in enumerate(parts):
                                        if part == "menu_groups" and idx + 1 < len(parts):
                                            gid = parts[idx + 1].split("?")[0]
                                            if len(gid) >= 10:
                                                captured_v2_group_id = gid
                                                print(f"   ✅ [Listener] Berhasil menangkap V2 Menu Group ID: {gid}")
                                                break
                            except Exception:
                                pass

                        if ("/menus" in url_lower or "menu_groups" in url_lower or "menu-items" in url_lower) and response.status == 200:
                            try:
                                data = response.json()
                                if isinstance(data, dict) and ("menus" in data or "categories" in data or "data" in data):
                                    captured_menu = data
                                    print(f"   ✅ [Listener] Berhasil menangkap response API Menu! Total kategori: {len(data.get('menus', data.get('categories', [])))}")
                            except Exception as e:
                                pass

                        if "variant_categories" in response.url:
                            try:
                                if response.status == 200:
                                    data = response.json()
                                    cats = data.get("variant_categories", [])
                                    if cats:
                                        captured_modifiers.extend(cats)
                                        print(f"   ✅ [Listener] Berhasil menangkap {len(cats)} modifier category dari API!")
                            except Exception as e:
                                pass
                    
                    page.on("request", handle_request_passkey)
                    page.on("response", handle_response)
                    
                    # 1. Coba klik Menu tab di sidebar dengan selector href yang presisi
                    print("   🤖 Mengklik tab Menu di sidebar...")
                    tutup_semua_popup(page)
                    menu_clicked = False
                    sidebar_locators = [
                        'a[href="/gofood"]',
                        'a[href*="/gofood"]',
                        "aside a:has-text('Menu')",
                        "nav a:has-text('Menu')",
                        "a:has-text('Menu')",
                        "text=Menu"
                    ]
                    for sel in sidebar_locators:
                        try:
                            loc = page.locator(sel)
                            for i in range(loc.count()):
                                candidate = loc.nth(i)
                                if candidate.is_visible():
                                    candidate.click(force=True)
                                    menu_clicked = True
                                    break
                            if menu_clicked:
                                break
                        except Exception:
                            continue
                            
                    if menu_clicked:
                        print("   ✅ Berhasil mengklik tab Menu di sidebar.")
                        tutup_semua_popup(page)
                        page.wait_for_timeout(1000)
                        
                        # Cek apakah ada tutorial/popup lagi
                        tutup_semua_popup(page)
                    else:
                        print("   ⚠️ Tab Menu di sidebar tidak ditemukan, mencoba langsung ke URL /gofood...")
                        safe_goto_with_retry(page, "https://portal.gofoodmerchant.co.id/gofood", wait_until="domcontentloaded")
                    
                    # Cek apakah sudah otomatis ter-redirect ke halaman menu items (untuk single-branch)
                    current_url = page.url
                    if "/menu-items" in current_url:
                        print("   🤖 Halaman otomatis beralih ke Menu Items (Single Branch). Menunggu capture...")
                    else:
                        print(f"   🤖 Langsung navigasi ke halaman menu outlet {store_id_clean}...")
                        safe_goto_with_retry(page, f"https://portal.gofoodmerchant.co.id/gofood/{store_id_clean}/", wait_until="domcontentloaded")
                            
                    # Ultra-reliable Menu Capture Flow (2x max retries)
                    max_menu_retries = 2
                    for menu_attempt in range(1, max_menu_retries + 1):
                        if captured_menu is not None:
                            break

                        print(f"   🤖 [Retry Mechanism {menu_attempt}/{max_menu_retries}] Menunggu response API Menu ditangkap listener (maksimal 8 detik)...")
                        start_wait = time.time()
                        while captured_menu is None and (time.time() - start_wait) < 8:
                            page.wait_for_timeout(500)

                        if captured_menu is not None:
                            break

                        # Jika listener belum menangkap menu setelah 8 detik, eksekusi Direct Fetch API & V2 API
                        if captured_menu is None and access_token:
                            print(f"   🤖 [Direct Fetch Fallback {menu_attempt}/{max_menu_retries}] Memulai fetch langsung via API Gojek...")
                            token_for_fetch = access_token if str(access_token).lower().startswith("bearer ") else f"Bearer {access_token}"
                            
                            target_ids = []
                            for cand in [store_id_clean, captured_restaurant_id]:
                                if cand and str(cand).strip() not in ("-", "", "None") and str(cand).strip() not in target_ids:
                                    target_ids.append(str(cand).strip())
                                    
                            try:
                                storage_ids = page.evaluate("""() => {
                                    const found = [];
                                    const add = (v) => {
                                        if (v && typeof v === 'string') {
                                            const s = v.trim();
                                            if (s.length >= 6 && s.length <= 40 && !s.includes('{') && !s.includes('[') && !found.includes(s)) {
                                                found.push(s);
                                            }
                                        }
                                    };
                                    const href = window.location.href || '';
                                    href.split('/').forEach(add);
                                    const uuidM = href.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|G[0-9]{8,12}|M[0-9]{5,10}/gi);
                                    if (uuidM) uuidM.forEach(add);

                                    [localStorage, sessionStorage].forEach(store => {
                                        try {
                                            for (let i = 0; i < store.length; i++) {
                                                const k = (store.key(i) || '').toLowerCase();
                                                const v = store.getItem(store.key(i)) || '';
                                                if (k.includes('restaurant') || k.includes('outlet') || k.includes('store') || k.includes('merchant') || k.includes('id')) {
                                                    add(v);
                                                }
                                                const m = v.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|G[0-9]{8,12}|M[0-9]{5,10}/gi);
                                                if (m) m.forEach(add);
                                            }
                                        } catch(e) {}
                                    });
                                    return found;
                                }""")
                                if storage_ids:
                                    for sid in storage_ids:
                                        if sid not in target_ids:
                                            target_ids.append(sid)
                            except Exception:
                                pass

                            try:
                                direct_menu = page.evaluate("""async ({token, targetIds, passkey}) => {
                                    for (const restId of targetIds) {
                                        const endpoints = [
                                            `https://api.gojekapi.com/gofood/merchant/v1/restaurants/${restId}/menus`,
                                            `https://api.gobiz.co.id/gofood/merchant/v1/restaurants/${restId}/menus`,
                                            `https://api.gojekapi.com/gofood/merchant/v2/restaurants/${restId}/menus`,
                                            `https://api.gojekapi.com/gofood/merchant/v1/outlets/${restId}/menus`,
                                            `https://api.gojekapi.com/gofood/merchant/v2/menu_groups/${restId}/menus`,
                                            `https://portal.gofoodmerchant.co.id/api/gofood/v1/restaurants/${restId}/menus`,
                                            `https://portal.gofoodmerchant.co.id/api/gofood/v2/restaurants/${restId}/menus`
                                        ];
                                        for (const ep of endpoints) {
                                            try {
                                                const headers = {
                                                    "Authorization": "Bearer " + token.replace(/^Bearer /i, ''),
                                                    "Authentication-Type": "go-id",
                                                    "Gojek-Country-Code": "ID",
                                                    "Accept": "application/json"
                                                };
                                                if (passkey) headers["X-Passkey"] = passkey;
                                                const res = await fetch(ep, { headers });
                                                if (res.ok) {
                                                    const d = await res.json();
                                                    if (d && (d.menus || d.categories || d.data)) return d;
                                                }
                                            } catch (e) {}
                                        }
                                    }
                                    return null;
                                }""", {"token": access_token, "targetIds": target_ids, "passkey": captured_x_passkey})

                                if direct_menu:
                                    captured_menu = direct_menu
                                    print(f"   ✅ [Direct Fetch Fallback {menu_attempt}/{max_menu_retries}] Berhasil mengambil menu GoFood langsung dari API! Total kategori: {len(direct_menu.get('menus', direct_menu.get('categories', [])))}")
                            except Exception as err:
                                print(f"   ⚠️ [Direct Fetch Fallback {menu_attempt}/{max_menu_retries}] Error: {err}")

                        if captured_menu is None and captured_v2_group_id:
                            try:
                                from Gofood.GO.actions import _menu_api as go_api
                                token_for_fetch = access_token if str(access_token).lower().startswith("bearer ") else f"Bearer {access_token}"
                                v2_menu = go_api.fetch_menus_v2(page, token_for_fetch, captured_v2_group_id, passkey=captured_x_passkey)
                                if v2_menu:
                                    captured_menu = {"menus": v2_menu} if isinstance(v2_menu, list) else v2_menu
                                    print(f"   ✅ [Direct Fetch Fallback {menu_attempt}/{max_menu_retries}] Berhasil mengambil menu via endpoint V2 menu_groups.")
                            except Exception as v2_err:
                                print(f"   ⚠️ [Direct Fetch Fallback {menu_attempt}/{max_menu_retries}] V2 menu_groups gagal: {v2_err}")

                        if captured_menu is None and menu_attempt < max_menu_retries:
                            print(f"   🔄 [Retry Mechanism {menu_attempt}/{max_menu_retries}] Re-navigasi presisi ke halaman menu items...")
                            try:
                                safe_goto_with_retry(page, f"https://portal.gofoodmerchant.co.id/gofood/{store_id_clean}/menu-items", wait_until="domcontentloaded")
                                tutup_semua_popup(page)
                            except Exception as reload_err:
                                print(f"   ⚠️ Re-navigasi warning: {reload_err}")
                        
                    # Beri waktu tambahan 5 detik untuk menangkap pemanggilan API variant_categories
                    if captured_menu is not None:
                        print("   🤖 Menu ditangkap, menunggu 5 detik tambahan untuk mengintersepsi semua modifier...")
                        page.wait_for_timeout(5000)
                        
                        # Dapatkan restaurant_id dari captured_menu untuk fetch langsung v1 variant categories
                        restaurant_id = None
                        menus_list = captured_menu.get("menus", [])
                        for menu_cat in menus_list:
                            items_list = menu_cat.get("menu_items", [])
                            for m_item in items_list:
                                if m_item.get("restaurant_id"):
                                    restaurant_id = m_item.get("restaurant_id")
                                    break
                            if restaurant_id:
                                break
                        
                        if restaurant_id and access_token:
                            print(f"   🤖 [Direct Fetch] Mencoba fetch langsung v1 variant categories untuk restaurant: {restaurant_id}...")
                            try:
                                direct_cats = page.evaluate("""async ({token, rest_id}) => {
                                    try {
                                        const res = await fetch(`https://api.gojekapi.com/gofood/merchant/v1/restaurants/${rest_id}/variant_categories`, {
                                            headers: {
                                                "Authorization": "Bearer " + token,
                                                "Authentication-Type": "go-id",
                                                "Gojek-Country-Code": "ID",
                                                "Accept": "application/json"
                                            }
                                        });
                                        const data = await res.json();
                                        return data.variant_categories || [];
                                    } catch (e) {
                                        return [];
                                    }
                                }""", {"token": access_token, "rest_id": restaurant_id})
                                
                                if direct_cats:
                                    captured_modifiers.extend(direct_cats)
                                    print(f"   ✅ [Direct Fetch] Berhasil mendapatkan {len(direct_cats)} variant categories langsung dari API v1!")
                            except Exception as e:
                                print(f"   ⚠️ [Direct Fetch] Gagal fetch langsung variant categories: {e}")
                        
                    # Hapus listener agar tidak berpotensi memory leak
                    try:
                        page.remove_listener("response", handle_response)
                    except Exception:
                        pass
                        
                except Exception as e:
                    print(f"   ⚠️ Gagal menangkap response API Menu: {e}")

            # Fetch user profile
            user_data = None
            try:
                user_data = page.evaluate("""async (token) => {
                    try {
                        const res = await fetch("https://api.gobiz.co.id/v1/users/me", {
                            headers: {
                                "Authorization": "Bearer " + token,
                                "Authentication-Type": "go-id"
                            }
                        });
                        return await res.json();
                    } catch (e) { return null; }
                }""", access_token)
            except Exception:
                pass

            try:
                all_cookies = context.cookies()
            except Exception as cookie_err:
                print(f"   ⚠️ Gagal membaca cookies dari context: {cookie_err}")
                all_cookies = []
            local_storage = {}
            session_storage = {}
            try:
                local_storage = page.evaluate("() => ({...localStorage})")
                session_storage = page.evaluate("() => ({...sessionStorage})")
            except Exception:
                pass

            # Deduplicate captured modifiers (prioritize those with 'id' or 'master_variant_category_id')
            deduped_modifiers = []
            seen_ids = set()
            
            def get_priority(m):
                return 0 if (m.get("id") or m.get("master_variant_category_id")) else 1
                
            sorted_modifiers = sorted(captured_modifiers, key=get_priority)
            
            for m in sorted_modifiers:
                cid = m.get("common_id") or m.get("master_variant_category_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    deduped_modifiers.append(m)

            result = {
                'access_token': access_token,
                'user_data': user_data,
                'cookies': all_cookies,
                'localStorage': local_storage,
                'sessionStorage': session_storage,
                'captured_menu': captured_menu,
                'captured_modifiers': deduped_modifiers,
                'v2_menus_group_id': captured_v2_group_id,
                'restaurant_uuid': captured_restaurant_id,
                'x_passkey': captured_x_passkey,
            }

            # Save session for future runs
            if not session_loaded_successfully:
                session_data = {
                    'timestamp': time.time(),
                    'access_token': access_token,
                    'cookies': all_cookies,
                    'localStorage': local_storage,
                    'sessionStorage': session_storage,
                }
                if logged_in_email:
                    save_gofood_session(logged_in_email, session_data)
                elif emails_to_try:
                    for email in emails_to_try:
                        save_gofood_session(email, session_data)
                if phone:
                    save_gofood_session(phone, session_data)
        else:
            print(f"❌ Gagal mendapatkan token untuk {label}.")

        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass
    finally:
        if chrome_process:
            from src.core.browser_factory import kill_process_tree
            kill_process_tree(chrome_process)
        if chrome_log:
            try:
                chrome_log.close()
            except Exception:
                pass

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GoFood Multi-Outlet Manual Login (Menu Extractor Version)")
    parser.add_argument("--no-proxy", action="store_true", help="Nonaktifkan proxy/WARP")
    args_cli = parser.parse_args()

    print("=" * 60)
    print("  🔑 GOFOOD LOGIN UTILITY (NEW COLUMNS GID=0)  ")
    print("=" * 60)

    # Proxy config
    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")

    if args_cli.no_proxy:
        use_proxy = False
        print("🚫 Proxy dinonaktifkan.")

    proxy_config = None
    if use_proxy and proxy_server:
        print(f"🔄 Menggunakan proxy: {proxy_server}")
        parsed = urlparse(proxy_server)
        if parsed.username and parsed.password:
            server_url = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server_url += f":{parsed.port}"
            proxy_config = {"server": server_url, "username": parsed.username, "password": parsed.password}
        else:
            proxy_config = {"server": proxy_server}

    # Ambil daftar outlet dari Google Sheet
    print("\n📋 Mengambil daftar outlet GoFood dari Google Sheet...")
    outlets = fetch_gofood_outlets()

    # Filter hanya yang punya email (Email Login Go 1 atau Email Login Go 2 tidak kosong)
    outlets_with_email = [o for o in outlets if o.get('emails') and any('@' in em for em in o['emails'])]

    if not outlets_with_email:
        print("❌ Tidak ada outlet GoFood dengan email kredensial yang tersedia.")
        return

    # Cek token yang sudah ada di .env
    existing_tokens = {}
    for key, value in os.environ.items():
        if key.startswith('BEARER_TOKEN_') and value:
            suffix = key[len('BEARER_TOKEN_'):]
            phone_part = suffix.split('_')[0]
            phone_norm = normalisation_nomor_hp(phone_part)
            if phone_norm:
                existing_tokens[phone_norm] = True

    # Tampilkan daftar
    print(f"\n📋 Ditemukan {len(outlets_with_email)} outlet GoFood Live dengan email:\n")
    for i, o in enumerate(outlets_with_email, 1):
        phone_norm = normalisation_nomor_hp(o['phone'])
        has_token = "✅ Sudah Login" if phone_norm in existing_tokens else "❌ Belum Login"
        cabang_str = f" - {o['cabang']}" if o['cabang'] else ""
        store_str = f" (Store: {o['store_id']})" if o['store_id'] else ""
        print(f"  [{i:2d}] {o['nama_outlet']}{cabang_str}{store_str}")
        emails_str = ", ".join(o.get('emails', [])) if o.get('emails') else o['email']
        print(f"       📧 {emails_str}  |  {has_token}")

    print(f"\n  Pilih outlet untuk login (contoh: 1,3,5 atau 'all' or 'new'):")
    pilihan = input("  Masukkan pilihan: ").strip().lower()

    selected = []
    if pilihan == 'all':
        selected = list(range(len(outlets_with_email)))
    elif pilihan == 'new':
        for idx, o in enumerate(outlets_with_email):
            phone_norm = normalisation_nomor_hp(o['phone'])
            if phone_norm not in existing_tokens:
                selected.append(idx)
    else:
        # Parsir comma separated indices
        parts = pilihan.split(',')
        for p in parts:
            p = p.strip()
            if '-' in p:
                start_s, end_s = p.split('-')
                start = int(start_s.strip()) - 1
                end = int(end_s.strip()) - 1
                selected.extend(range(start, end + 1))
            elif p.isdigit():
                idx = int(p) - 1
                if 0 <= idx < len(outlets_with_email):
                    selected.append(idx)

    # Filter unique & sorted
    selected = sorted(list(set(selected)))

    if not selected:
        print("❌ Tidak ada outlet terpilih yang valid.")
        return

    print(f"\n🚀 Memulai login manual untuk {len(selected)} outlet...")

    success_count = 0
    for seq, idx in enumerate(selected, 1):
        outlet = outlets_with_email[idx]
        print(f"\n[{seq}/{len(selected)}] ", end="")

        result = login_outlet(outlet, proxy_config)

        if result and result.get('access_token'):
            token = result['access_token']
            phone_norm = normalisation_nomor_hp(outlet['phone'])
            sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', outlet['nama_outlet'])
            suffix = f"_{phone_norm}_{sanitized_name}"

            # Simpan ke .env di core folder
            try:
                set_key(str(ENV_PATH), "BEARER_TOKEN", token)
                set_key(str(ENV_PATH), f"BEARER_TOKEN{suffix}", token)
                set_key(str(ENV_PATH), "ACTIVE_NOMOR_HP", phone_norm)
                set_key(str(ENV_PATH), f"NAMA_OUTLET{suffix}", outlet['nama_outlet'])
                if outlet['cabang']:
                    set_key(str(ENV_PATH), f"CABANG{suffix}", outlet['cabang'])
                if outlet['store_id']:
                    set_key(str(ENV_PATH), f"STORE_ID{suffix}", outlet['store_id'])

                print(f"   ✅ Token disimpan: BEARER_TOKEN{suffix}")
                success_count += 1
            except Exception as e:
                print(f"   ❌ Gagal simpan ke .env: {e}")
                print(f"   Token: {token[:50]}...")

            # Dump session JSON ke menu folder
            try:
                dump = {
                    'timestamp': time.time(),
                    'outlet': outlet,
                    'user': result.get('user_data'),
                    'cookies': result.get('cookies', []),
                    'localStorage': result.get('localStorage', {}),
                    'sessionStorage': result.get('sessionStorage', {}),
                }
                json_file = MENU_DIR / f"session_{phone_norm}.json"
                with open(json_file, 'w') as f:
                    json.dump(dump, f, indent=4)
                print(f"   💾 Session dump: session_{phone_norm}.json")
            except Exception as e:
                print(f"   ❌ Gagal menyimpan berkas sesi: {e}")

            # Simpan captured menu response jika ada
            if result.get('captured_menu'):
                try:
                    api_dir = MENU_DIR / "Gofood" / "API"
                    api_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Simpan file spesifik store id
                    store_id = outlet.get('store_id', '')
                    if store_id:
                        menu_file_specific = api_dir / f"menu-response-{store_id}.json"
                        with open(menu_file_specific, 'w', encoding='utf-8') as f:
                            json.dump(result['captured_menu'], f, indent=4)
                        print(f"   💾 Menu response spesifik disimpan ke: menu/Gofood/API/menu-response-{store_id}.json")
                    
                    # Simpan ke default menu-response.json
                    menu_file = api_dir / "menu-response.json"
                    with open(menu_file, 'w', encoding='utf-8') as f:
                        json.dump(result['captured_menu'], f, indent=4)
                    print(f"   💾 Menu response default disimpan ke: menu/Gofood/API/menu-response.json")
                    
                    # Simpan captured modifier response jika ada
                    if result.get('captured_modifiers'):
                        mod_file_specific = api_dir / f"modifier-response-{store_id}.json"
                        with open(mod_file_specific, 'w', encoding='utf-8') as f:
                            json.dump({"variant_categories": result['captured_modifiers']}, f, indent=4)
                        print(f"   💾 Modifier response spesifik disimpan ke: menu/Gofood/API/modifier-response-{store_id}.json")
                        
                        # Simpan ke default modifier-response.json
                        mod_file = api_dir / "modifier-response.json"
                        with open(mod_file, 'w', encoding='utf-8') as f:
                            json.dump({"variant_categories": result['captured_modifiers']}, f, indent=4)
                        print(f"   💾 Modifier response default disimpan ke: menu/Gofood/API/modifier-response.json")
                except Exception as e:
                    print(f"   ❌ Gagal menyimpan menu-response.json / modifier-response.json: {e}")

        if seq < len(selected):
            print(f"\n   ⏳ Lanjut ke outlet berikutnya dalam 2 detik...")
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"  ✅ SELESAI: {success_count}/{len(selected)} outlet berhasil login.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
