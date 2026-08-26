import os
import json
import csv
from dotenv import load_dotenv, set_key
from playwright.sync_api import sync_playwright
import re
import time
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

load_dotenv()

DEFAULT_OTP_ENDPOINT_URL = os.getenv("OTP_ENDPOINT_URL")
DEFAULT_NOMOR_HP_CSV_URL = os.getenv("NOMOR_HP_CSV_URL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRYSUnKOqk29LCktTxdb0wPLbWMbRaWRP3eC_UA4AwYod1FW6zDMhtLMC5ghIvot2B8upCDfBsn-TCP/pub?gid=0&single=true&output=csv")


def is_email(s):
    return "@" in (s or "")


def check_headless_mode():
    """
    Mengecek mode headless dari berkas config.json atau variabel lingkungan .env
    """
    # 1. Cek dari .env terlebih dahulu
    env_headless = os.getenv("HEADLESS") or os.getenv("HEADLESS_GOFOOD")
    if env_headless is not None:
        return env_headless.lower() in ("true", "1", "yes")

    # 2. Cek dari config.json di parent directory (src/config.json)
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                data = json.load(f)
                return bool(data.get("headless_gofood", False))
    except Exception:
        pass
    return False


def ambil_otp_dari_endpoint(url_dasar, action="getOtp", label_email=None):
    """
    Mengambil OTP terbaru dari endpoint Google Apps Script atau langsung dari Google Sheets CSV.
    """
    if not url_dasar:
        raise ValueError("URL endpoint OTP kosong.")

    # Jika URL mengarah langsung ke Google Sheets CSV, kita download CSV dan ambil OTP terbaru
    if "docs.google.com/spreadsheets" in url_dasar:
        try:
            import time
            cache_buster = f"&t={int(time.time())}" if "?" in url_dasar else f"?t={int(time.time())}"
            with urlopen(url_dasar + cache_buster, timeout=30) as response:
                content = response.read().decode("utf-8").strip()
                lines = content.splitlines()
                if not lines or len(lines) < 2:
                    return ""
                reader = csv.reader(lines)
                rows = list(reader)
                headers = [h.strip().lower() for h in rows[0]]
                
                # Cari kolom "otp"
                otp_idx = -1
                for idx, h in enumerate(headers):
                    if "otp" in h:
                        otp_idx = idx
                        break
                
                if otp_idx == -1:
                    # Fallback ke kolom kedua jika header tidak ditemukan
                    otp_idx = 1 if len(rows[0]) > 1 else 0
                    
                # Ambil nilai dari baris terakhir
                last_row = rows[-1]
                if len(last_row) > otp_idx:
                    return last_row[otp_idx].strip()
                return ""
        except Exception as e:
            print(f"⚠️ Gagal mengunduh/membaca OTP dari CSV Google Sheets: {e}")
            return ""

    parsed = urlparse(url_dasar)
    query_params = dict(parse_qsl(parsed.query))
    query_params["action"] = action
    if label_email:
        query_params["label"] = label_email
    url_final = urlunparse(parsed._replace(query=urlencode(query_params)))

    with urlopen(url_final, timeout=30) as response:
        return response.read().decode("utf-8").strip()


def ambil_data_outlet_dari_csv(csv_url):
    """
    Mengambil data outlet GoFood langsung dari file CSV Google Sheets.
    """
    if not csv_url:
        raise ValueError("URL CSV kosong.")

    import time
    cache_buster = f"&t={int(time.time())}" if "?" in csv_url else f"?t={int(time.time())}"
    with urlopen(csv_url + cache_buster, timeout=30) as response:
        lines = response.read().decode("utf-8").splitlines()
        
    reader = csv.reader(lines)
    rows = list(reader)
    
    if not rows:
        return []
        
    # Mencari index kolom Status secara dinamis dari baris pertama (header)
    headers_lower = [str(h).strip().lower() for h in rows[0]]
    status_col_index = -1
    nama_resto_final_col_index = -1
    for idx, header_name in enumerate(headers_lower):
        if "status" in header_name:
            status_col_index = idx
        if "nama resto final" in header_name:
            nama_resto_final_col_index = idx

    results = []
    for i in range(1, len(rows)): # Lewati baris pertama (header)
        row = rows[i]
        if len(row) > 26: # Pastikan baris memiliki data hingga kolom AA (index 26)
            app_value = str(row[3]).strip().lower()
            status_value = str(row[status_col_index]).strip().lower() if status_col_index != -1 and len(row) > status_col_index else ""
            
            if app_value == "gofood" and status_value == "live":
                nama_resto_final = str(row[nama_resto_final_col_index]).strip() if nama_resto_final_col_index != -1 and len(row) > nama_resto_final_col_index else ""
                
                # Mendapatkan email dari kolom Y (index 24) dan nomor HP dari kolom AA (index 26)
                email_val = str(row[24]).strip() if len(row) > 24 else ""
                phone_val = str(row[26]).strip() if len(row) > 26 else ""
                
                # Jika kolom Y berisi email valid, gunakan email tersebut sebagai kredensial
                kredensial = email_val if "@" in email_val else phone_val
                
                results.append({
                    "nama_outlet": str(row[1]).strip(),
                    "cabang": str(row[2]).strip(),
                    "phone": kredensial,
                    "nama_resto_final": nama_resto_final
                })
    return results


def normalisasi_nomor_hp(nomor_hp):
    """
    Menghapus awalan 62 agar nomor menjadi format lokal tanpa kode negara.
    Contoh: 628123456789 -> 8123456789.
    Jika nomor_hp adalah email, kembalikan string apa adanya.
    """
    if is_email(nomor_hp):
        return nomor_hp.strip()
    nomor_bersih = re.sub(r"\D", "", nomor_hp or "")
    if nomor_bersih.startswith("62"):
        return nomor_bersih[2:]
    return nomor_bersih


def tunggu_otp_terbaru(url_dasar, action="getOtp", label_email=None, timeout_detik=90, interval_detik=3):
    """
    Menunggu OTP terbaru yang berbeda dari nilai awal agar tidak memakai OTP sebelumnya.
    """
    otp_awal = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
    batas_waktu = time.time() + timeout_detik

    while time.time() < batas_waktu:
        time.sleep(interval_detik)
        otp_baru = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
        if otp_baru and otp_baru != otp_awal:
            return otp_baru

    return otp_awal


def login_dan_ambil_sesi(nomor_hp, nama_resto_final="", mode_otp="manual", otp_endpoint_url=None):
    """
    Membuka browser secara headless untuk login ke GoBiz.
    """
    headless_mode = check_headless_mode()
    print(f"Membuka browser (headless={headless_mode}) untuk login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless_mode,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox'
            ]
        )
        use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
        proxy_server = os.getenv("PROXY_SERVER")
        
        proxy_config = None
        if use_proxy and proxy_server:
            print(f"Menggunakan proxy untuk browser: {proxy_server}")
            from urllib.parse import urlparse
            parsed = urlparse(proxy_server)
            if parsed.username and parsed.password:
                server_url = f"{parsed.scheme}://{parsed.hostname}"
                if parsed.port:
                    server_url += f":{parsed.port}"
                proxy_config = {
                    "server": server_url,
                    "username": parsed.username,
                    "password": parsed.password
                }
            else:
                proxy_config = {
                    "server": proxy_server
                }

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768},
            proxy=proxy_config
        )
        
        # Suntikkan skrip stealth untuk menyembunyikan ciri-ciri automation
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'id']
            });
        """)
        
        page = context.new_page()
        
        try:
            is_email_login = is_email(nomor_hp)
            nomor_hp = normalisasi_nomor_hp(nomor_hp)

            if is_email_login:
                print("Membuka halaman login email langsung...")
                page.goto("https://portal.gofoodmerchant.co.id/auth/login/email")
                time.sleep(2.0) # Jeda setelah memuat halaman

                already_on_otp = False
                try:
                    if page.locator('text=/Kode OTP/i, text=/Kami telah mengirim/i, input[placeholder*="●"]').count() > 0:
                        already_on_otp = True
                        print("ℹ️ Terdeteksi halaman sudah berada di layar OTP. Melewati pengisian email...")
                except Exception:
                    pass

                if not already_on_otp:
                    print(f"Mencoba memasukkan email {nomor_hp}...")
                    input_email = page.locator('input[type="email"], input[placeholder*="email" i], input[name*="email" i], input[data-testid*="email" i], input[type="text"]:not([placeholder*="●"]):not([placeholder*="otp" i])').first
                    input_email.wait_for(state="visible", timeout=15000)
                    time.sleep(1.0)
                    input_email.focus()
                    time.sleep(0.5)
                    # Ketik secara bertahap seperti manusia
                    input_email.type(nomor_hp, delay=80)
                    time.sleep(1.0)
                    input_email.press("Enter")
                    print("Email berhasil dimasukkan.")
                    time.sleep(2.5)

                    # Klik "Masuk dengan OTP" pada halaman berikutnya
                    print("Menunggu halaman pilihan login (password/OTP)...")
                    try:
                        # Cari tombol "Masuk dengan OTP"
                        btn_otp = page.locator('button:has-text("Masuk dengan OTP"), a:has-text("Masuk dengan OTP")').first
                        btn_otp.wait_for(state="visible", timeout=15000)
                        time.sleep(1.5)
                        btn_otp.click()
                        print("Tombol 'Masuk dengan OTP' berhasil diklik. OTP telah dikirim.")
                        time.sleep(2.0)
                    except Exception as e:
                        print(f"⚠️ Gagal mengklik tombol 'Masuk dengan OTP' secara otomatis: {e}")
                        print("👉 Silakan klik tombol 'Masuk dengan OTP' secara manual pada browser.")
            else:
                page.goto("https://portal.gofoodmerchant.co.id/")
                time.sleep(2.5)
                print(f"Mencoba memasukkan nomor {nomor_hp}...")
                input_nomor = page.locator('input[type="tel"], input[name*="phone" i], input[type="text"]:not([placeholder*="●"]):not([placeholder*="otp" i])').first
                input_nomor.wait_for(state="visible", timeout=15000)
                time.sleep(1.0)
                input_nomor.focus()
                time.sleep(0.5)
                input_nomor.type(nomor_hp, delay=80)
                time.sleep(1.0)
                input_nomor.press("Enter")
                print("Nomor berhasil dimasukkan.")
                time.sleep(2.5)

            try:
                # Tunggu hingga field OTP muncul dan minta input dari terminal
                print("Menunggu halaman OTP...")
                otp_input_selector = 'input[autocomplete="one-time-code"], input[placeholder*="●" i], input[placeholder*="otp" i], input[aria-label*="digit" i], div[class*="otp" i] input, input[name*="otp" i], input[maxlength="1"]'
                page.locator(otp_input_selector).first.wait_for(state="visible", timeout=15000)
                time.sleep(1.5)

                otp_code = None
                if mode_otp == "auto":
                    try:
                        print("Menunggu OTP terbaru masuk...")
                        label_email = os.getenv("GMAIL_OTP_LABEL", "OTP-GO")
                        action_type = "getOtpEmail" if is_email_login else "getOtp"
                        otp_code = tunggu_otp_terbaru(otp_endpoint_url, action=action_type, label_email=label_email, timeout_detik=90, interval_detik=3)
                        if otp_code and not (otp_code.isdigit() and len(otp_code) in (4, 6)):
                            print(f"⚠️ OTP dari endpoint bukan format angka valid: {otp_code[:50]}...")
                            otp_code = None
                        else:
                            print(f"OTP berhasil diambil otomatis dari endpoint: {otp_code}")
                    except (URLError, HTTPError, ValueError, TimeoutError, Exception) as e:
                        print(f"⚠️ Gagal mengambil OTP otomatis: {e}")
                        print("👉 Beralih ke input OTP manual.")

                if not otp_code:
                    otp_code = input("Masukkan kode OTP yang Anda terima: ")
                
                otp_fields = page.locator(otp_input_selector).all()
                if len(otp_fields) > 0:
                    print("Memasukkan OTP secara sekuensial (mensimulasikan ketikan manusia)...")
                    try:
                        otp_fields[0].focus()
                        time.sleep(1.0)
                        # Ketik OTP ke field pertama dengan jeda manusiawi 300ms per tombol
                        try:
                            otp_fields[0].type(otp_code, delay=300)
                        except Exception:
                            # fallback ke keyboard typing jika .type gagal
                            page.keyboard.type(otp_code, delay=300)
                        print("OTP berhasil dimasukkan.")
                        time.sleep(1.5)

                        # [DITANGGUHKAN SEMENTARA UNTUK VALIDASI OTP]
                        # Setelah OTP diketik, coba klik tombol submit/login yang umum.
                        # submit_selectors = [
                        #     'button[type="submit"]',
                        #     'button:has-text("Masuk")',
                        #     'button:has-text("Login")',
                        #     'button:has-text("Sign in")',
                        #     'button[aria-label*="login" i]',
                        #     'input[type="submit"]'
                        # ]
                        # 
                        # submitted = False
                        # for sel in submit_selectors:
                        #     try:
                        #         btn = page.locator(sel).first
                        #         if btn and btn.is_visible():
                        #             btn.click()
                        #             print(f"Mencoba klik tombol submit: {sel}")
                        #             submitted = True
                        #             break
                        #     except Exception:
                        #         continue
                        # 
                        # if not submitted:
                        #     # fallback: tekan Enter dari keyboard (sering bekerja jika fokus ada di field OTP)
                        #     try:
                        #         page.keyboard.press("Enter")
                        #         print("Tidak menemukan tombol submit; menekan Enter sebagai fallback.")
                        #         submitted = True
                        #     except Exception:
                        #         print("⚠️ Tidak dapat menekan Enter sebagai fallback untuk submit.")

                    except Exception as e:
                        print(f"⚠️ Gagal memasukkan OTP otomatis: {e}")
            except Exception:
                print("⚠️ Script tidak dapat menemukan field OTP secara otomatis.")
                print("👉 Silakan lanjutkan proses (misal: klik Lanjut / masukkan OTP) secara MANUAL di jendela browser yang terbuka.")

            # Tunggu sampai URL berubah ke halaman yang menandakan sudah login
            print("Menunggu verifikasi dan login...")
            try:
                page.wait_for_url(re.compile(r".*(dashboard|analytics|choose|outlet).*"), timeout=60000)
            except Exception:
                pass
                
            if nama_resto_final:
                print(f"Mencari dan memilih cabang: {nama_resto_final}...")
                try:
                    # Use a more robust selector that finds a clickable parent
                    outlet_element = page.get_by_text(nama_resto_final, exact=True).first
                    outlet_element.wait_for(state="visible", timeout=15000)
                    outlet_element.click()
                    print(f"✅ Berhasil memilih cabang: {nama_resto_final}")
                    # Wait for navigation to dashboard after click
                    page.wait_for_url(re.compile(r".*(dashboard|analytics).*"), timeout=30000)
                except Exception as e:
                    print(f"⚠️ Gagal memilih cabang '{nama_resto_final}'. Mungkin sudah di cabang yang benar atau cabang tidak ditemukan.")
                    # Still try to continue, maybe it's already on the right page
                    page.wait_for_url(re.compile(r".*(dashboard|analytics).*"), timeout=10000)

            print("Login terdeteksi! Mengambil token sesi...")
            time.sleep(3)
            
            access_token = None
            for cookie in context.cookies():
                if cookie['name'] == 'access_token':
                    access_token = cookie['value']
                    break
            
            if access_token:
                print("✅ Token berhasil ditemukan!")
                print("\n" + "="*70)
                print("🎉 BERHASIL MASUK KE DASHBOARD!")
                print("Waktu tunggu 10 menit diaktifkan agar Anda dapat mengeksplorasi.")
                print("Browser akan ditutup secara otomatis setelah 10 menit.")
                print("="*70 + "\n")
                
                # Tunggu selama 10 menit (600 detik)
                for i in range(600, 0, -1):
                    if i % 60 == 0:
                        print(f"⏳ Waktu sisa eksplorasi: {i // 60} menit...")
                    elif i <= 10:
                        print(f"⏳ Browser akan ditutup dalam {i} detik...")
                    time.sleep(1)
                
                return access_token
            else:
                print("❌ Gagal menemukan access_token pada cookie browser.")
                return None
        except Exception as e:
            print(f"❌ Proses login gagal: {e}")
            return None
        finally:
            browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GoFood Login Utility")
    parser.add_argument("--outlet", type=str, default=None, help="Filter specific outlet name for login")
    parser.add_argument("--mode", type=str, default=None, help="Bypassed mode parameter")
    parser.add_argument("--no-proxy", action="store_true", help="Nonaktifkan proxy/WARP untuk sesi ini")
    args_cli = parser.parse_args()

    if args_cli.no_proxy:
        os.environ["USE_PROXY"] = "false"
        print("🚫 Proxy/WARP dinonaktifkan untuk sesi ini.")


    print("=== LOGIN MULTI-AKUN GOFOOD ===")
    
    # Target email yang dipaksa langsung
    target_email = "gofood2@agencysuperfood.anonaddy.com"
    pilihan_mode = "auto"
    endpoint_otp = DEFAULT_OTP_ENDPOINT_URL

    # Membersihkan file .env untuk kredensial lama
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    try:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
            keys_to_remove = ["BEARER_TOKEN", "ACTIVE_NOMOR_HP", "NAMA_OUTLET", "CABANG"]
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    new_lines.append(line)
                    continue
                key = stripped.split("=")[0].strip()
                if not any(k in key for k in keys_to_remove):
                    new_lines.append(line)
            with open(env_path, 'w') as f:
                f.writelines(new_lines)
            print("✅ Sesi login lama di file .env berhasil dibersihkan.")
        else:
            open(env_path, 'w').close()
            print("✅ File .env berhasil dibuat baru.")
    except Exception as e:
        print(f"⚠️ Gagal membersihkan sesi lama di .env: {e}")

    # Set daftar outlet target langsung
    nama_outlet_target = args_cli.outlet or "GoFood Outlet 1"
    daftar_outlet = [{
        "phone": target_email,
        "nama_outlet": nama_outlet_target,
        "cabang": "Tanpa Cabang",
        "nama_resto_final": nama_outlet_target
    }]

    # Jalankan loop login tunggal
    total_nomor = len(daftar_outlet)
    for idx, outlet in enumerate(daftar_outlet, 1):
        nomor = outlet.get("phone", "")
        nama = outlet.get("nama_outlet", "")
        cabang = outlet.get("cabang", "")
        nama_resto_final = outlet.get("nama_resto_final", "")
        
        print(f"\n{'='*60}")
        print(f"Proses login {idx}/{total_nomor}: {nama} ({nomor})")
        print(f"{'='*60}")
        
        token = login_dan_ambil_sesi(nomor, nama_resto_final=nama_resto_final, mode_otp=pilihan_mode, otp_endpoint_url=endpoint_otp)
            
        if token:
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            sanitized_resto_name = re.sub(r'[^a-zA-Z0-9]', '', nama_resto_final or nama)
            suffix = f"_{nomor}_{sanitized_resto_name}"
            set_key(env_path, "BEARER_TOKEN", token)
            set_key(env_path, f"BEARER_TOKEN{suffix}", token)
            set_key(env_path, "ACTIVE_NOMOR_HP", nomor)
            if nama: set_key(env_path, f"NAMA_OUTLET{suffix}", str(nama))
            if cabang: set_key(env_path, f"CABANG{suffix}", str(cabang))
            print(f"✅ Login sukses untuk {nama}. BEARER_TOKEN disimpan di .env.")
        else:
            print(f"\n⚠️ Login gagal untuk {nama} ({nomor}).")

    print("\n✅ Proses login selesai.")
