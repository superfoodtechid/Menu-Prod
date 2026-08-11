#!/usr/bin/env python3
import os
import sys
import re
import time
from datetime import datetime
from pathlib import Path

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from menu_core.sheets import get_outlets_for_applicator
from shopee.core.pull import extract_shopee_menu

def main():
    print("=" * 65)
    print("  🚀 SHOPEEFOOD BATCH EXTRACTOR (FROM MASTER GSHEETS)")
    print("=" * 65)
    
    print("[*] Mengunduh daftar outlet ShopeeFood dari Google Sheets...")
    try:
        outlets = get_outlets_for_applicator("shopee")
        print(f"[+] Berhasil memuat {len(outlets)} outlet ShopeeFood dari Google Sheets.")
    except Exception as e:
        print(f"[-] Gagal memuat daftar outlet: {e}")
        sys.exit(1)
        
    if not outlets:
        print("[!] Tidak ada outlet ShopeeFood berstatus 'Live' yang ditemukan.")
        sys.exit(0)
        
    print("\nOpsi Penarikan:")
    print("  [1] Tarik SEMUA outlet (Overwrite data lama)")
    print("  [2] Tarik HANYA outlet baru yang belum diproses")
    print("  [q] Batal / Keluar")
    
    choice = input("\nPilihan Anda: ").strip()
    if choice.lower() == 'q':
        print("Dibatalkan.")
        sys.exit(0)
        
    only_new = (choice == '2')
    
    print(f"\n[*] Memulai penarikan menu massal...")
    success_count = 0
    fail_count = 0
    skipped_count = 0
    
    for idx, o in enumerate(outlets):
        raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
        raw_brand = o.get('brand') or ''
        
        def clean_filename_part(s):
            return "".join(c for c in s if c.isalnum() or c in (' ', '_', '-')).strip()
            
        clean_outlet = clean_filename_part(raw_outlet)
        clean_brand = clean_filename_part(raw_brand)
        
        if clean_brand and clean_brand.lower() != clean_outlet.lower():
            excel_filename = f"O.C5 {clean_outlet} - {clean_brand}.xlsx"
        else:
            excel_filename = f"O.C5 {clean_outlet}.xlsx"
            
        clean_outlet_folder = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
        clean_outlet_folder = re.sub(r'\s+', ' ', clean_outlet_folder).lower()
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "data", "exports", "shopee", clean_outlet_folder)
        excel_path = os.path.join(output_dir, excel_filename)
        
        # Cek jika file excel sudah ada
        if only_new and os.path.exists(excel_path):
            print(f"[{idx+1}/{len(outlets)}] Skipping: {raw_outlet} (Sudah pernah ditarik)")
            skipped_count += 1
            continue
                
        name_to_show = o.get('brand') or o.get('nama_resto_final') or o.get('nama_outlet')
        print(f"\n[{idx+1}/{len(outlets)}] Memproses: {name_to_show} (ID: {o['store_id']})")
        
        try:
            success, result_data = extract_shopee_menu(o, output_dir)
            if success:
                success_count += 1
                print(f"  ✔ Berhasil! {result_data.get('items_count', 0)} item, {result_data.get('mods_count', 0)} modifier.")
            else:
                fail_count += 1
                print(f"  ✘ Gagal: {result_data}")
        except Exception as e:
            fail_count += 1
            print(f"  ✘ Error / Exception: {e}")
            
        # Jeda 1 menit setiap 10 outlet untuk menghindari rate limit / limit browser session
        if (idx + 1) < len(outlets) and (idx + 1) % 10 == 0:
            print(f"\n[BATCH] Selesai memproses 10 outlet. Jeda 1 menit...")
            for remaining in range(60, 0, -1):
                sys.stdout.write(f"\rMenunggu... {remaining} detik")
                sys.stdout.flush()
                time.sleep(1)
            print("\n[BATCH] Melanjutkan penarikan...\n")
            
    print("\n" + "=" * 65)
    print("🎉 BATCH PENARIKAN SELESAI!")
    print(f"  - Sukses   : {success_count}")
    print(f"  - Gagal    : {fail_count}")
    print(f"  - Dilewati : {skipped_count}")
    print("=" * 65)

if __name__ == "__main__":
    main()
