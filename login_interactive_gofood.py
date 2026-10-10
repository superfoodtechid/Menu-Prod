#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv, set_key
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=True)


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    p = str(phone).strip()
    if "@" in p:
        return p
    digits = re.sub(r"\D", "", p)
    if digits.startswith("62"):
        return digits[2:]
    if digits.startswith("0"):
        return digits[1:]
    return digits


def normalize_token(raw_token: str) -> str:
    token = str(raw_token or "").strip()
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token.split(" ", 1)[1].strip()
    return token


def save_session_files(identifier: str, session_data: dict):
    if not identifier:
        return
    ident_str = str(identifier).strip().lower()
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", ident_str)

    gofood_dir = BASE_DIR / "Gofood"
    gofood_dir.mkdir(parents=True, exist_ok=True)

    target_gofood = gofood_dir / f"session_gofood_{sanitized}.json"
    with open(target_gofood, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=4)
    print(f"[+] Sesi tersimpan: {target_gofood}")

    phone_norm = normalize_phone(identifier)
    if phone_norm:
        target_root = BASE_DIR / f"session_{phone_norm}.json"
        with open(target_root, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=4)
        print(f"[+] Sesi dump tersimpan: {target_root}")


def extract_token_from_page(page, context) -> str:
    token_candidate = ""

    try:
        cookies = context.cookies()
        for c in cookies:
            if c.get("name") in ("access_token", "token", "gobiz_token", "go-id-token"):
                val = normalize_token(c.get("value"))
                if val and len(val) > 20:
                    token_candidate = val
                    break
    except Exception:
        pass

    if not token_candidate:
        try:
            token_eval = page.evaluate("""() => {
                const keys = [
                    'token', 'access_token', 'accessToken', 'auth_token',
                    'authorization', 'gobiz-token', 'go-id-token'
                ];
                const fromStorage = (storage) => {
                    for (const k of keys) {
                        try {
                            let v = storage.getItem(k);
                            if (v) {
                                if (v.startsWith('{')) {
                                    try {
                                        const p = JSON.parse(v);
                                        v = p.token || p.access_token || p.accessToken || v;
                                    } catch (_) {}
                                }
                                if (v && v.length > 20) return v;
                            }
                        } catch (_) {}
                    }
                    const tokenRegex = /[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+\\.?[A-Za-z0-9-_.+/=]*/;
                    for (let i = 0; i < storage.length; i++) {
                        try {
                            const key = storage.key(i);
                            const val = storage.getItem(key);
                            if (val && val.length > 20) {
                                if (val.includes('eyJ')) {
                                    const m = val.match(/eyJ[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+\\.?[A-Za-z0-9-_.+/=]*/);
                                    if (m) return m[0];
                                }
                                const match = val.match(tokenRegex);
                                if (match) return match[0];
                            }
                        } catch (_) {}
                    }
                    return '';
                };
                return fromStorage(localStorage) || fromStorage(sessionStorage) || '';
            }""")
            token_candidate = normalize_token(token_eval)
        except Exception:
            pass

    return token_candidate


def main():
    parser = argparse.ArgumentParser(description="GoFood Interactive Manual Login via Phone Number")
    parser.add_argument("--phone", "-p", help="Nomor HP merchant GoFood (contoh: 08123456789)")
    parser.add_argument("--no-proxy", action="store_true", help="Nonaktifkan proxy/WARP")
    args = parser.parse_args()

    phone_input = args.phone
    if not phone_input:
        phone_input = input("Masukkan Nomor HP GoFood: ").strip()

    if not phone_input:
        print("[-] Nomor HP tidak boleh kosong.")
        sys.exit(1)

    phone_norm = normalize_phone(phone_input)
    print(f"[*] Target nomor HP: {phone_input} (Normalisasi: {phone_norm})")

    # Setup Proxy
    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")
    if args.no_proxy:
        use_proxy = False

    proxy_config = None
    if use_proxy and proxy_server:
        parsed = urlparse(proxy_server)
        if parsed.username and parsed.password:
            server_url = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server_url += f":{parsed.port}"
            proxy_config = {"server": server_url, "username": parsed.username, "password": parsed.password}
        else:
            proxy_config = {"server": proxy_server}
        print(f"[*] Proxy aktif: {proxy_server}")

    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        print("[!] PERINGATAN: Variabel $DISPLAY tidak terdeteksi.")
        print("[!] Mode non-headless membutuhkan GUI / X11 display.")
        print("[!] Jika di VPS remote, jalankan via SSH X11 forwarding (-X atau -Y) atau jalankan di komputer lokal.")

    print("[*] Membuka browser Chromium non-headless...")
    p = sync_playwright().start()

    chromium_bin = "/usr/bin/chromium" if os.path.exists("/usr/bin/chromium") else (
        "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else None
    )

    launch_kwargs = {
        "headless": False,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ]
    }
    if chromium_bin:
        launch_kwargs["executable_path"] = chromium_bin

    try:
        browser = p.chromium.launch(**launch_kwargs)
    except Exception as e:
        print(f"[-] Gagal meluncurkan browser: {e}")
        p.stop()
        sys.exit(1)

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        proxy=proxy_config
    )

    page = context.new_page()

    login_url = "https://portal.gofoodmerchant.co.id/auth/login"
    print(f"[*] Navigasi ke {login_url}...")
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print(f"[!] Warning navigasi: {e}")

    print("\n" + "=" * 65)
    print("  🟢 INTERACTIVE MODE AKTIF")
    print("  1. Masukkan nomor HP di halaman login browser.")
    print("  2. Klik Lanjut / Kirim OTP (via SMS atau WhatsApp ke HP Anda).")
    print("  3. Masukkan kode OTP di browser.")
    print("  4. Jika ada pemilihan cabang/outlet, pilih outlet terkait.")
    print("  5. Setelah masuk dashboard, kembali ke terminal ini.")
    print("=" * 65 + "\n")

    input("👉 Tekan [ENTER] setelah berhasil masuk dashboard GoFood...")

    print("\n[*] Mengekstrak sesi login...")
    access_token = extract_token_from_page(page, context)

    if not access_token:
        print("[-] Token belum terdeteksi. Mencoba tunggu 3 detik dan periksa ulang...")
        page.wait_for_timeout(3000)
        access_token = extract_token_from_page(page, context)

    if not access_token:
        print("[-] GAGAL: access_token tidak ditemukan.")
        print("    Pastikan Anda sudah benar-benar login dan berada di dalam dashboard portal.")
        try:
            browser.close()
            p.stop()
        except Exception:
            pass
        sys.exit(1)

    print(f"[+] Token berhasil didapatkan! (Prefix: {access_token[:25]}...)")

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
    except Exception:
        all_cookies = []

    local_storage = {}
    session_storage = {}
    try:
        local_storage = page.evaluate("() => ({...localStorage})")
        session_storage = page.evaluate("() => ({...sessionStorage})")
    except Exception:
        pass

    session_data = {
        "timestamp": time.time(),
        "phone": phone_norm,
        "phone_raw": phone_input,
        "access_token": access_token,
        "user_data": user_data,
        "cookies": all_cookies,
        "localStorage": local_storage,
        "sessionStorage": session_storage,
    }

    # Simpan berkas sesi
    save_session_files(phone_norm, session_data)
    if phone_input != phone_norm:
        save_session_files(phone_input, session_data)

    # Sinkronisasi ke .env
    try:
        set_key(str(ENV_PATH), "BEARER_TOKEN", access_token)
        set_key(str(ENV_PATH), "ACTIVE_NOMOR_HP", phone_norm)
        set_key(str(ENV_PATH), f"BEARER_TOKEN_{phone_norm}", access_token)

        # Coba cocokkan dengan outlet sheet jika ada
        try:
            from login_gofood import fetch_gofood_outlets
            outlets = fetch_gofood_outlets()
            matched = next((o for o in outlets if normalize_phone(o.get("phone", "")) == phone_norm), None)
            if matched:
                sanitized_name = re.sub(r"[^a-zA-Z0-9]", "", matched.get("nama_outlet", ""))
                suffix = f"_{phone_norm}_{sanitized_name}"
                set_key(str(ENV_PATH), f"BEARER_TOKEN{suffix}", access_token)
                set_key(str(ENV_PATH), f"NAMA_OUTLET{suffix}", matched.get("nama_outlet", ""))
                if matched.get("cabang"):
                    set_key(str(ENV_PATH), f"CABANG{suffix}", matched.get("cabang", ""))
                if matched.get("store_id"):
                    set_key(str(ENV_PATH), f"STORE_ID{suffix}", matched.get("store_id", ""))
                print(f"[+] Data outlet sheet dicocokkan: {matched.get('nama_outlet')} (Suffix: {suffix})")
        except Exception as sheet_err:
            print(f"[!] Info pencocokan sheet dilewati: {sheet_err}")

        print("[+] File .env berhasil diperbarui!")
    except Exception as env_err:
        print(f"[-] Gagal memperbarui file .env: {env_err}")

    try:
        browser.close()
        p.stop()
    except Exception:
        pass

    print("\n" + "=" * 65)
    print("🎉 LOGIN INTERAKTIF GOFOOD SUKSES")
    print(f"   Nomor HP     : {phone_norm}")
    print(f"   Token Prefix : {access_token[:30]}...")
    print(f"   Status       : Sesi tersimpan & .env terupdate")
    print("=" * 65)


if __name__ == "__main__":
    main()

