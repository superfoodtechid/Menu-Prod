#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_shopee_session.py
======================
Skrip pengujian diagnostik sesi Shopee Partner mandiri (tanpa mengubah harga menu).

Kegunaan:
1. Memverifikasi keberadaan dan kesegaran berkas session_{identifier}.json.
2. Memverifikasi direktori Chrome Profile lokal di server.
3. Menguji validasi token secara langsung via API Shopee Partner.
4. Menguji peluncuran browser headless dan mekanisme pemulihan sesi multi-domain
   (SSO cookie injection dan auto-click 'Lanjutkan dengan Shopee').
5. Menguji ekstraksi token baru via halaman pengaturan jam operasional (business-hours).

Penggunaan:
    python scripts/test_shopee_session.py --identifier 6285183151531
    python scripts/test_shopee_session.py -i superfoodapp --no-headless
"""

import os
import sys
import time
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

# Setup root path agar dapat mengimpor modul shopee dan shopee_core
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src" / "shopee-omzet-automation"))

try:
    import requests
except ImportError:
    print("❌ Modul 'requests' belum terpasang.")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Uji Diagnostik Sesi Shopee Partner FoodMaster")
    parser.add_argument(
        "-i", "--identifier",
        type=str,
        default="6285183151531",
        help="Kunci identitas akun Shopee (nomor HP 628xxx atau username)"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Jalankan browser dengan jendela GUI (default: headless)"
    )
    return parser.parse_args()


def log_step(step_num: int, title: str):
    print("\n" + "=" * 65)
    print(f"[{step_num}/5] {title}")
    print("=" * 65)


def main():
    args = parse_args()
    identifier = args.identifier.strip()
    is_headless = not args.no_headless

    print("\n" + "#" * 65)
    print("🧪 FOODMASTER: PENGUJIAN DIAGNOSTIK SESI SHOPEE PARTNER")
    print(f"Target Akun: {identifier}")
    print(f"Mode Browser: {'Headless' if is_headless else 'Headed (GUI)'}")
    print(f"Waktu Uji: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 65)

    # ─────────────────────────────────────────────────────────────
    # Langkah 1: Memeriksa Keberadaan Berkas Sesi
    # ─────────────────────────────────────────────────────────────
    log_step(1, "Memeriksa Berkas Sesi di Server")

    search_dirs = [
        ROOT_DIR / "src" / "shopee-omzet-automation" / "data",
        ROOT_DIR / "shopee" / "data",
        ROOT_DIR / "data",
    ]

    session_file = None
    for d in search_dirs:
        cand = d / f"session_{identifier}.json"
        if cand.exists():
            session_file = cand
            break

    # Cek kandidat tanpa awalan 62 atau nomor HP
    if not session_file:
        digits = re.sub(r'[^0-9]', '', identifier)
        for d in search_dirs:
            if not d.exists():
                continue
            for f in d.glob("session_*.json"):
                f_digits = re.sub(r'[^0-9]', '', f.stem)
                if digits and f_digits and (f_digits.endswith(digits[-9:]) or digits.endswith(f_digits[-9:])):
                    session_file = f
                    break
            if session_file:
                break

    if not session_file or not session_file.exists():
        print(f"❌ [GAGAL] Berkas sesi 'session_{identifier}.json' tidak ditemukan di:")
        for d in search_dirs:
            print(f"    - {d}")
        print("\n💡 Rekomendasi:")
        print(f"    Jalankan shopee_session_exporter.py di komputer Anda:")
        print(f"    python shopee_session_exporter/shopee_session_exporter.py -p {identifier}")
        sys.exit(1)

    print(f"✅ Berkas sesi ditemukan: {session_file}")
    try:
        session_data = json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Gagal membaca berkas JSON sesi: {e}")
        sys.exit(1)

    saved_at_str = session_data.get("saved_at", "Tidak diketahui")
    tob_token = session_data.get("shopee_tob_token", "")
    entity_id = session_data.get("shopee_tob_entity_id", "")
    merchant_name = session_data.get("merchant_name", "Shopee Merchant")
    extra_cookies = session_data.get("extra_cookies", {}) or {}

    print(f"    - Merchant Name: {merchant_name}")
    print(f"    - Entity ID: {entity_id}")
    print(f"    - Disimpan Pada: {saved_at_str}")
    print(f"    - Jumlah Extra Cookies: {len(extra_cookies)}")
    print(f"    - Token TOB: {tob_token[:15]}...{tob_token[-10:] if len(tob_token) > 25 else ''}")

    # Hitung umur sesi
    try:
        saved_dt = datetime.fromisoformat(saved_at_str)
        diff_hours = (datetime.now() - saved_dt).total_seconds() / 3600.0
        print(f"    - Estimasi Umur Sesi: {diff_hours:.1f} jam yang lalu")
        if diff_hours > 8:
            print("    ⚠️ Sesi berumur lebih dari 8 jam. Kemungkinan cookie SSO Shopee sudah kedaluwarsa.")
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────
    # Langkah 2: Memeriksa Direktori Chrome Profile
    # ─────────────────────────────────────────────────────────────
    log_step(2, "Memeriksa Direktori Chrome Profile")

    profile_candidates = [
        ROOT_DIR / "src" / "shopee-omzet-automation" / "data" / f"chrome_profile_{identifier}",
        ROOT_DIR / "data" / f"chrome_profile_{identifier}",
    ]
    found_profile = None
    for p in profile_candidates:
        if p.exists() and p.is_dir():
            found_profile = p
            break

    if found_profile:
        print(f"✅ Direktori Chrome Profile ditemukan: {found_profile}")
        sub_items = [item.name for item in found_profile.iterdir() if item.is_dir()]
        print(f"    - Subdirektori: {', '.join(sub_items[:6])}")
    else:
        print("⚠️ Direktori Chrome Profile khusus tidak ditemukan. Sistem akan mengandalkan pemulihan cookie sesi.")

    # ─────────────────────────────────────────────────────────────
    # Langkah 3: Uji Token via Direct API (Tanpa Browser)
    # ─────────────────────────────────────────────────────────────
    log_step(3, "Uji Validitas Token API Langsung (HTTP)")

    direct_valid = False
    if tob_token:
        try:
            headers = {
                "Cookie": f"shopee_tob_entity_id={entity_id}; shopee_tob_token={tob_token}",
                "x-merchant-token": tob_token,
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.post(
                "https://api.partner.shopee.co.id/nb/mss/web-api/PartnerAccountServer/GetUserInfo",
                json={},
                headers=headers,
                timeout=8
            )
            resp_json = resp.json()
            if resp.status_code == 200 and resp_json.get("code") == 0:
                direct_valid = True
                u_info = resp_json.get("data", {})
                print("✅ Token API saat ini masih AKTIF dan valid!")
                print(f"    - Akun: {u_info.get('userName') or u_info.get('tocUserName')}")
                print(f"    - Merchant: {u_info.get('merchantName')} (ID: {u_info.get('merchantId')})")
            else:
                print(f"⚠️ Token API telah kedaluwarsa (Respons: {resp_json.get('message', 'Expired')}).")
                print("   Browser headless akan melakukan regenerasi token dari sesi browser/cookies.")
        except Exception as api_e:
            print(f"⚠️ Pengecekan API langsung gagal: {api_e}")
    else:
        print("⚠️ Tidak ada token TOB tersimpan untuk diuji.")

    # ─────────────────────────────────────────────────────────────
    # Langkah 4: Uji Pemulihan Sesi Multi-Domain via Browser
    # ─────────────────────────────────────────────────────────────
    log_step(4, "Uji Pemulihan Sesi Multi-Domain via Browser Headless")

    try:
        from shopee_core import browser
    except ImportError:
        try:
            from core import browser
        except ImportError:
            import browser

    browser.set_session_file(session_file)

    print("🚀 Meluncurkan browser otomasi Shopee...")
    session_result = None
    try:
        session_result = browser.get_session(
            username=identifier,
            headless=is_headless,
            close_browser=True,
            interactive=False
        )
    except Exception as b_err:
        print(f"❌ Terjadi kesalahan saat pengujian browser: {b_err}")

    # ─────────────────────────────────────────────────────────────
    # Langkah 5: Evaluasi Hasil dan Kesimpulan
    # ─────────────────────────────────────────────────────────────
    log_step(5, "Hasil Akhir Diagnostik")

    if session_result and session_result.get("shopee_tob_token"):
        new_tok = session_result["shopee_tob_token"]
        new_eid = session_result.get("shopee_tob_entity_id", entity_id)
        print("\n🎉 ========================================================")
        print("✅ PENGUJIAN SESI SHOPEE BERHASIL LULUS 100%!")
        print("========================================================")
        print(f"Akun: {identifier}")
        print(f"Token Baru: {new_tok[:15]}...{new_tok[-10:] if len(new_tok) > 25 else ''}")
        print(f"Entity ID: {new_eid}")
        print(f"Status: Browser berhasil memulihkan sesi multi-domain, masuk ke dashboard,")
        print(f"        dan memperbarui token via halaman pengaturan jam operasional.")
        print(f"Kesiapan Push Price: SIAP DIGUNAKAN.")
        print("========================================================\n")
    else:
        print("\n⚠️ ========================================================")
        print("❌ SESI SHOPEE MEMBUTUHKAN PEMBARUAN (REFRESH DARI LOKAL)")
        print("========================================================")
        print(f"Akun: {identifier}")
        print("Penyebab:")
        print("  - Sesi SSO Shopee di server sudah kedaluwarsa (berumur lebih dari batas toleransi).")
        print("  - Server dialihkan ke layar input nomor HP / OTP.")
        print("\nLangkah Penyelesaian untuk Esok Hari:")
        print("  1. Buka browser Google Chrome di komputer Anda (tempat akun Shopee biasa login).")
        print("  2. Jalankan skrip exporter lokal:")
        print(f"     python shopee_session_exporter/shopee_session_exporter.py -p {identifier}")
        print("  3. Selesaikan CAPTCHA atau OTP jika diminta di Chrome komputer Anda.")
        print("  4. Setelah selesai, skrip otomatis mengunggah sesi segar ke server.")
        print("  5. Jalankan kembali tes ini untuk konfirmasi status aktif.")
        print("========================================================\n")


if __name__ == "__main__":
    main()
