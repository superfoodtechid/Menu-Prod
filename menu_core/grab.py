import os
import json
import asyncio
import re
import pandas as pd
from pathlib import Path
import openpyxl
from menu_core.c5_template_helper import (
    get_c5_template_path,
    prepare_c5_sheet,
    get_c5_headers,
    DATA_START_ROW,
    is_c5_reserved_row,
    upsert_folder_link_sheet,
    FOLDER_LINK_SHEET_NAME,
    FOLDER_LINK_LABEL_HEADER,
    FOLDER_LINK_URL_HEADER,
)

def run_async(coro):
    """Safely run async coroutines inside a synchronous worker thread context."""
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(coro)
    finally:
        try:
            new_loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)

def clean_name_str(s):
    """Helper to clean string for comparison (remove spaces, symbols, lowercase)."""
    return "".join(c for c in str(s).lower() if c.isalnum())

def extract_grab_menu(store_metadata: dict, output_dir: str):
    """
    Extracts GrabFood menu for a specific store.
    Downloads the entire menu under the account and filters for the target store_id.
    """
    username = store_metadata.get('username', '').strip()
    password = store_metadata.get('password', '').strip() or "Master@123"
    store_id = store_metadata.get('store_id', '').strip()
    nama_resto = store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''
    brand = store_metadata.get('brand') or ''

    print(f"\n[GrabFood Menu Extractor]")
    print(f"[-] Target Outlet: {nama_resto} ({store_id})")

    if not username:
        print("[!] Error: Username is empty.")
        return False, "Username kosong."

    # 1. Import Grab API Scraper
    try:
        import sys
        from pathlib import Path
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        elif sys.path[0] != project_root:
            sys.path.remove(project_root)
            sys.path.insert(0, project_root)
        from grab.core.grab_api_scraper import run_api_download_for_portal
    except ImportError as e:
        print(f"[!] Error importing Grab Scraper: {e}")
        return False, f"Gagal mengimpor Grab Scraper: {e}"

    # 2. Run Playwright Grab download flow
    job_id = store_metadata.get('job_id')
    try:
        from menu_core.job_control import is_job_cancelled
        if is_job_cancelled(job_id):
            print(f"[!] Grab job {job_id} telah dibatalkan oleh pengguna.")
            return False, "Dibatalkan oleh pengguna"
    except Exception:
        pass

    print(f"[*] Meluncurkan browser untuk menarik menu dari portal Grab Merchant...")
    try:
        json_path, error_msg = run_async(run_api_download_for_portal(username, password, target_store_id=store_id, job_id=job_id))
        if error_msg or not json_path or not os.path.exists(json_path):
            print(f"[!] Gagal menarik menu GrabFood: {error_msg}")
            return False, f"Gagal menarik menu GrabFood: {error_msg}"
    except Exception as e:
        print(f"[!] Terjadi pengecualian saat menjalankan scraper: {e}")
        return False, f"Terjadi kesalahan saat menjalankan scraper: {e}"

    print(f"   💾 Download JSON berhasil: {json_path}")

    # 3. Load downloaded JSON data
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            scraped_data = json.load(f)
    except Exception as e:
        print(f"[!] Gagal membaca data JSON menu GrabFood: {e}")
        return False, f"Gagal membaca data JSON menu Grab: {e}"

    # 4. Save structured Grab snapshot to grab/API/menu-response-<store_id>.json for Baseline comparison & Clean up temp file
    grab_api_dir = os.path.join(project_root, "grab", "API")
    os.makedirs(grab_api_dir, exist_ok=True)
    if store_id:
        try:
            snapshot_path = os.path.join(grab_api_dir, f"menu-response-{store_id}.json")
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(scraped_data, f, indent=2)
            print(f"   💾 Snapshot menu Grab berhasil disimpan ke: {snapshot_path}")
        except Exception as e:
            print(f"   ⚠️ Gagal menyimpan snapshot menu Grab ke {grab_api_dir}: {e}")

    try:
        os.unlink(json_path)
    except Exception as e:
        print(f"   ⚠️ Gagal menghapus file unduhan sementara {json_path}: {e}")

    items = scraped_data.get('items', [])
    modifiers = scraped_data.get('modifiers', [])

    # 5. Filter items & modifiers for the target store_id (or fallback matching)
    matched_items = []
    for item in items:
        item_sid = str(item.get("Store ID", "")).strip()
        target_sid = str(store_id).strip()
        if target_sid and item_sid.lower() == target_sid.lower():
            matched_items.append(item)
        elif not target_sid and clean_name_str(item.get("Nama panjang", "")) == clean_name_str(nama_resto):
            matched_items.append(item)

    matched_mods = []
    for mod in modifiers:
        mod_sid = str(mod.get("Store ID", "")).strip()
        target_sid = str(store_id).strip()
        if target_sid and mod_sid.lower() == target_sid.lower():
            matched_mods.append(mod)
        elif not target_sid and clean_name_str(mod.get("Nama panjang", "")) == clean_name_str(nama_resto):
            matched_mods.append(mod)

    print(f"   📊 Berhasil menyaring menu:")
    print(f"      - Item Terkait: {len(matched_items)} dari {len(items)}")
    print(f"      - Modifier Terkait: {len(matched_mods)} dari {len(modifiers)}")

    if not matched_items:
        print(f"[!] Warning: Tidak ada item menu yang cocok untuk Store ID '{store_id}' / Nama '{nama_resto}'.")
        # Kita tetap buat file kosong tapi laporkan warning
        # return False, f"Tidak ada menu yang cocok dengan Store ID {store_id}"

    # 6. Build file name conforming to "O.C5 {nama_outlet} - {brand}.xlsx"
    def clean_filename_part(s):
        return "".join(c for c in s if c.isalnum() or c in (' ', '_', '-')).strip()

    raw_resto_final = store_metadata.get('nama_resto_final') or '' if isinstance(store_metadata, dict) else ''
    clean_outlet = clean_filename_part(nama_resto)
    clean_brand = clean_filename_part(brand)
    clean_resto = clean_filename_part(raw_resto_final)

    if clean_resto and clean_resto.lower() not in (clean_outlet.lower(), clean_brand.lower()):
        excel_filename = f"O.C5 {clean_resto} - {clean_brand}.xlsx"
    elif clean_brand and clean_brand.lower() != clean_outlet.lower():
        excel_filename = f"O.C5 {clean_outlet} - {clean_brand}.xlsx"
    else:
        excel_filename = f"O.C5 {clean_outlet}.xlsx"

    os.makedirs(output_dir, exist_ok=True)
    excel_path = os.path.join(output_dir, excel_filename)

    # 7. Write to O. C5 Template Excel
    BASE_DIR = Path(__file__).resolve().parents[1]
    template_path = get_c5_template_path(BASE_DIR)

    # ── Kolom yang bisa diisi user secara manual (akan di-preserve saat re-pull) ──
    USER_EDITABLE_COLS = [
        'Keyword',                   # Kol L
        'Item Name Improvement',     # Kol M
        'Design Improvement',        # Kol N
        'Offline Price (Rp)',        # Kol W
        'Offline Adjustment (Rp)',   # Kol X
        'Current Adjustment (Rp)',   # Kol AC
        'New Markup (%)',            # Kol AI
        'New Adjustment (Rp)',       # Kol AK
        'New Slash Price (%)',       # Kol AM
        'Notes',                     # Kol AP
    ]

    # ── Load data user dari C5 lama (jika ada) ──
    prev_user_data = {}  # { item_id: { col_name: value } }
    if os.path.exists(excel_path):
        try:
            wb_prev = openpyxl.load_workbook(excel_path, data_only=True)
            if 'Item' in wb_prev.sheetnames:
                sheet_prev = wb_prev['Item']
                prev_headers = {}
                for cell in sheet_prev[1]:
                    if cell.value:
                        prev_headers[str(cell.value).strip()] = cell.column - 1  # 0-indexed
                item_id_idx = prev_headers.get('Item ID')
                edit_col_indices = {col: prev_headers[col] for col in USER_EDITABLE_COLS if col in prev_headers}
                if item_id_idx is not None:
                    for row_cells in sheet_prev.iter_rows(min_row=DATA_START_ROW, values_only=True):
                        if is_c5_reserved_row(row_cells):
                            continue
                        raw_iid = row_cells[item_id_idx] if item_id_idx < len(row_cells) else None
                        if raw_iid is None or str(raw_iid).strip() in ('', 'None', 'nan'):
                            continue
                        iid = str(raw_iid).strip()
                        row_data = {}
                        for col_name, col_idx in edit_col_indices.items():
                            if col_idx < len(row_cells):
                                val = row_cells[col_idx]
                                if val is not None and str(val).strip() not in ('', 'None', 'nan'):
                                    row_data[col_name] = val
                        if row_data:
                            prev_user_data[iid] = row_data
            wb_prev.close()
            if prev_user_data:
                print(f"   🔄 Ditemukan C5 sebelumnya - memuat {len(prev_user_data)} baris data user untuk di-preserve.")
        except Exception as prev_err:
            print(f"   ⚠️ Gagal membaca C5 sebelumnya untuk merge: {prev_err}")

    # ── Load offline price dari database jika ada ──
    db_offline = {}
    if store_id:
        try:
            from menu_core.database import SessionLocal, get_offline_prices_by_store
            with SessionLocal() as db_session:
                db_offline = get_offline_prices_by_store(db_session, [store_id])
        except Exception as e_db:
            print(f"   ⚠️ Gagal memuat harga offline dari DB: {e_db}")

    from menu_core.gdrive_service import format_photo_folder_label, prepare_photo_folder
    from menu_core.database import normalize_offline_item_name
    owner_name = store_metadata.get("owner") or "Default Owner"
    listing_name = nama_resto or "GrabFood Outlet"
    sid = str(store_id or "").strip()
    folder_label = format_photo_folder_label("GrabFood", listing_name, sid)
    photo_sync_meta = None

    try:
        wb = openpyxl.load_workbook(template_path)
        
        # 1. Fill Item Sheet
        sheet_item = wb['Item']
        prepare_c5_sheet(sheet_item)
            
        headers_item = get_c5_headers(sheet_item)
        
        new_row_idx = DATA_START_ROW
        for item in matched_items:
            avail_str = str(item.get('Ketersediaan item', '')).lower()
            availability = "Available" if avail_str in ("available", "active", "1", "true") else "Unavailable"
            
            fake_price = item.get('Harga item sebelum promo (harga coret)', 0.0)
            real_price = item.get('Harga item setelah promo (harga coret)', 0.0)
            slash_rp = item.get('Nominal atau persentase promo (harga coret)', 0.0)
            slash_pct_custom = item.get('Persentase promo')
            
            if fake_price > real_price and fake_price > 0:
                if slash_pct_custom:
                    slash_pct = str(slash_pct_custom).strip()
                else:
                    pct = round(((fake_price - real_price) / fake_price) * 100.0, 2)
                    slash_pct = f"{int(pct)}%" if pct.is_integer() else f"{pct}%"
            else:
                slash_pct = "0%"
                slash_rp = 0

            # Lookup data user lama berdasarkan Item ID
            item_id_str = str(item.get('Item ID', '')).strip()
            prev_row = prev_user_data.get(item_id_str, {})
                
            photo_link_val = item.get('Link foto', '')

            mapping = {
                'OFD': 'GrabFood',
                'Listing Name': item.get('Nama panjang', nama_resto),
                'Outlet Name': item.get('Nama panjang', nama_resto),
                'Outlet Short Name': brand or item.get('Nama panjang', nama_resto),
                'Outlet Link': item.get('Link outlet', f"https://food.grab.com/id/en/restaurant/{store_id}"),
                'SID': item.get('Store ID', store_id),
                'Category ID': item.get('Category ID', ''),
                'Category': item.get('Nama kategori', ''),
                'Item ID': item.get('Item ID', ''),
                'Item': item.get('Nama item', ''),
                'Photo Link': photo_link_val,
                'Description': item.get('Deskripsi item', ''),
                'Keyword': '',
                'Total Sold': item.get('Jumlah terjual', 0),
                'Total Modifier Group': item.get('Jumlah modifier group', 0),
                'Total Modifier': item.get('Jumlah modifier', 0),
                'Availability': availability,
                'Visibility': 'Show',
                'Current Fake Price (Rp)': fake_price,
                'Current Real Price (Rp)': real_price,
                'Current Slash Price (%)': slash_pct,
                'Current Slash Price (Rp)': slash_rp
            }

            # Tambahkan kolom user-editable dari C5 lama jika ada
            for col_name in USER_EDITABLE_COLS:
                if col_name not in mapping and col_name in prev_row:
                    mapping[col_name] = prev_row[col_name]

            # Fallback ke harga offline dari database jika belum terisi dari C5 lama
            if db_offline:
                off_val = None
                if item_id_str and (store_id, item_id_str) in db_offline.get('by_id', {}):
                    off_val = db_offline['by_id'][(store_id, item_id_str)]
                elif item.get('Nama item'):
                    norm_n = normalize_offline_item_name(item.get('Nama item'))
                    if (store_id, norm_n) in db_offline.get('by_name', {}):
                        off_val = db_offline['by_name'][(store_id, norm_n)]
                if off_val:
                    if 'Offline Price (Rp)' not in mapping or mapping['Offline Price (Rp)'] in ('', None):
                        if off_val.get('offline_price') is not None:
                            mapping['Offline Price (Rp)'] = off_val['offline_price']
                    if 'Offline Adjustment (Rp)' not in mapping or mapping['Offline Adjustment (Rp)'] in ('', None):
                        if off_val.get('offline_adjustment') is not None:
                            mapping['Offline Adjustment (Rp)'] = off_val['offline_adjustment']
            
            for key, val in mapping.items():
                if key in headers_item:
                    col_idx = headers_item[key]
                    if pd.isna(val):
                        val = ""
                    elif key in ['SID', 'Category ID', 'Item ID']:
                        if isinstance(val, float):
                            val = str(int(val)) if val.is_integer() else str(val)
                        else:
                            val = str(val)
                    # Jika kolom ini bisa diisi user & nilai baru kosong, restore nilai lama
                    if key in USER_EDITABLE_COLS and (val == "" or val is None):
                        val = prev_row.get(key, val)
                    sheet_item.cell(row=new_row_idx, column=col_idx, value=val)
            new_row_idx += 1
                    
        # 2. Fill Modifier Sheet
        sheet_mod = wb['Modifier']
        prepare_c5_sheet(sheet_mod)
            
        headers_mod = get_c5_headers(sheet_mod)
        
        new_row_idx = DATA_START_ROW
        for mod in matched_mods:
            mod_avail_str = str(mod.get('Ketersediaan modifier', '')).lower()
            mod_availability = "Available" if mod_avail_str in ("available", "active", "1", "true") else "Unavailable"
            
            mapping_mod = {
                'OFD': 'GrabFood',
                'Listing Name': mod.get('Nama panjang', nama_resto),
                'Outlet Name': mod.get('Nama panjang', nama_resto),
                'Outlet Short Name': brand or mod.get('Nama panjang', nama_resto),
                'Outlet Link': mod.get('Link outlet', f"https://food.grab.com/id/en/restaurant/{store_id}"),
                'SID': mod.get('Store ID', store_id),
                'Item': mod.get('Nama item', ''),
                'Modifier Group ID': mod.get('Modifier Group ID', ''),
                'Modifier Group': mod.get('Nama modifier group', ''),
                'Modifier ID': mod.get('Modifier ID', ''),
                'Modifier': mod.get('Nama modifier', ''),
                'Min': mod.get('Minimal', 0),
                'Max': mod.get('Maksimal', 1),
                'Availability': mod_availability,
                'Visibility': 'Show',
                'Current Price (Rp)': mod.get('Harga modifier', 0.0)
            }
            
            for key, val in mapping_mod.items():
                if key in headers_mod:
                    col_idx = headers_mod[key]
                    if pd.isna(val):
                        val = ""
                    elif key in ['SID', 'Modifier Group ID', 'Modifier ID', 'Item']:
                        if isinstance(val, float):
                            val = str(int(val)) if val.is_integer() else str(val)
                        else:
                            val = str(val)
                    sheet_mod.cell(row=new_row_idx, column=col_idx, value=val)
            new_row_idx += 1

        try:
            folder_url, photo_sync_meta = prepare_photo_folder(
                owner_name=owner_name,
                platform="GrabFood",
                listing_name=listing_name,
                sid=sid,
                dishes=[{"item_name": it.get("Nama item"), "photo_url": it.get("Link foto"), "item_id": it.get("Item ID")} for it in matched_items],
                excel_path=excel_path,
                job_id=store_metadata.get("job_id"),
                workbook=wb,
                defer_photo_upload=True,
            )
        except Exception as e_drive:
            print(f"   ⚠️ Gagal menyiapkan folder foto GrabFood: {e_drive}")
            folder_entries = [(folder_label, "")]
            upsert_folder_link_sheet(wb, folder_entries)

        wb.save(excel_path)
        wb.close()
        if prev_user_data:
            print(f"   ✅ Berhasil menyimpan file catalog dengan data user yang di-preserve ke: {excel_path}")
        else:
            print(f"   ✅ Berhasil menyimpan file catalog menggunakan template O.C5 ke: {excel_path}")
    except Exception as ex_err:
        print(f"   [-] Gagal menulis ke template O.C5: {ex_err}. Fallback ke Excel biasa.")
        # Fallback to standard excel writer if template fails
        if photo_sync_meta is None:
            try:
                _, photo_sync_meta = prepare_photo_folder(
                    owner_name=owner_name,
                    platform="GrabFood",
                    listing_name=listing_name,
                    sid=sid,
                    dishes=[{"item_name": it.get("Nama item"), "photo_url": it.get("Link foto"), "item_id": it.get("Item ID")} for it in matched_items],
                    excel_path=excel_path,
                    job_id=store_metadata.get("job_id"),
                    skip_excel_update=True,
                    defer_photo_upload=True,
                )
            except Exception as e_drive:
                print(f"   ⚠️ Gagal menyiapkan folder foto GrabFood fallback: {e_drive}")
        df_items_fallback = pd.DataFrame(matched_items)
        df_mods_fallback = pd.DataFrame(matched_mods)
        resolved_folder_url = (photo_sync_meta or {}).get("drive_folder_url") or ""
        df_folder_links = pd.DataFrame(
            [[folder_label, resolved_folder_url]],
            columns=[FOLDER_LINK_LABEL_HEADER, FOLDER_LINK_URL_HEADER],
        )
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df_items_fallback.to_excel(writer, sheet_name='Item', index=False)
            df_mods_fallback.to_excel(writer, sheet_name='Modifier', index=False)
            df_folder_links.to_excel(writer, sheet_name=FOLDER_LINK_SHEET_NAME, index=False)

    return True, {
        'items_csv': None,
        'mods_csv': None,
        'excel': excel_path,
        'items_count': len(matched_items),
        'mods_count': len(matched_mods),
        'photo_sync': photo_sync_meta,
    }
