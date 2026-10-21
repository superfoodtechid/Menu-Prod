import os
import re
import io
import openpyxl
import pandas as pd
from menu_core.c5_template_helper import (
    get_c5_template_path,
    prepare_c5_sheet,
    get_c5_headers,
    DATA_START_ROW,
    is_c5_reserved_row,
)

FILE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = str(get_c5_template_path())
OFFLINE_PRICE_COLUMNS = ('Offline Price (Rp)', 'Offline Adjustment (Rp)')


def _identity_value(value):
    if value is None or pd.isna(value):
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_item_name(value):
    """Normalize item names for conservative offline-price fallback matching."""
    if value is None or pd.isna(value):
        return ''
    normalized = str(value).strip().casefold()
    normalized = re.sub(r'[^\w\s]', ' ', normalized, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', normalized).strip()


def _read_offline_prices(previous_workbook):
    if not previous_workbook:
        return {}
    try:
        if isinstance(previous_workbook, (bytes, bytearray)):
            workbook = openpyxl.load_workbook(io.BytesIO(previous_workbook), data_only=True, read_only=True)
        else:
            workbook = openpyxl.load_workbook(previous_workbook, data_only=True, read_only=True)
        if 'Item' not in workbook.sheetnames:
            workbook.close()
            return {}

        sheet = workbook['Item']
        headers = {str(cell.value).strip(): cell.column for cell in sheet[1] if cell.value is not None}
        sid_col = headers.get('SID')
        item_id_col = headers.get('Item ID')
        item_name_col = headers.get('Item', headers.get('Item Name'))
        offline_cols = {name: headers[name] for name in OFFLINE_PRICE_COLUMNS if name in headers}
        if not sid_col or not offline_cols or (not item_id_col and not item_name_col):
            workbook.close()
            return {}

        saved_by_id = {}
        saved_by_name_candidates = {}
        name_row_counts = {}
        for row in sheet.iter_rows(min_row=DATA_START_ROW, values_only=True):
            if is_c5_reserved_row(row):
                continue
            sid = _identity_value(row[sid_col - 1] if sid_col - 1 < len(row) else None)
            if not sid:
                continue
            item_id = _identity_value(row[item_id_col - 1] if item_id_col and item_id_col - 1 < len(row) else None)
            item_name = _normalize_item_name(row[item_name_col - 1] if item_name_col and item_name_col - 1 < len(row) else None)
            if item_name:
                name_row_counts[(sid, item_name)] = name_row_counts.get((sid, item_name), 0) + 1
            values = {}
            for name, column in offline_cols.items():
                value = row[column - 1] if column - 1 < len(row) else None
                if value is not None and str(value).strip() not in ('', 'nan', 'None'):
                    values[name] = value
            if not values:
                continue
            if item_id:
                saved_by_id[(sid, item_id)] = values
            if item_name:
                saved_by_name_candidates[(sid, item_name)] = values
        workbook.close()
        # Names are a fallback only. Never guess if duplicate item names exist
        # within the same Store ID, since that could attach a price to the wrong item.
        saved_by_name = {
            key: values for key, values in saved_by_name_candidates.items()
            if name_row_counts.get(key) == 1
        }
        return {'by_id': saved_by_id, 'by_name': saved_by_name}
    except Exception as exc:
        print(f"[C5 Combiner] Gagal membaca harga offline dari C5 sebelumnya: {exc}")
        return {}


def _restore_offline_prices(output_path, previous_workbook=None, db=None):
    from menu_core.database import SessionLocal, get_offline_prices_by_store, bulk_upsert_offline_prices

    close_db_when_done = False
    if db is None:
        try:
            db = SessionLocal()
            close_db_when_done = True
        except Exception:
            db = None

    try:
        workbook = openpyxl.load_workbook(output_path)
        if 'Item' not in workbook.sheetnames:
            workbook.close()
            return 0
        sheet = workbook['Item']
        headers = {str(cell.value).strip(): cell.column for cell in sheet[1] if cell.value is not None}
        sid_col = headers.get('SID')
        item_id_col = headers.get('Item ID')
        item_name_col = headers.get('Item', headers.get('Item Name'))
        offline_cols = {name: headers[name] for name in OFFLINE_PRICE_COLUMNS if name in headers}
        if not sid_col or not offline_cols or (not item_id_col and not item_name_col):
            workbook.close()
            return 0

        # Collect all unique SIDs from this sheet
        sheet_sids = set()
        target_name_counts = {}
        for row_idx in range(DATA_START_ROW, sheet.max_row + 1):
            if is_c5_reserved_row([sheet.cell(row=row_idx, column=c).value for c in range(1, 6)]):
                continue
            sid = _identity_value(sheet.cell(row=row_idx, column=sid_col).value)
            if sid:
                sheet_sids.add(sid)
            if item_name_col:
                item_name = _normalize_item_name(sheet.cell(row=row_idx, column=item_name_col).value)
                if sid and item_name:
                    key = (sid, item_name)
                    target_name_counts[key] = target_name_counts.get(key, 0) + 1

        # 1. Query database for known offline prices
        db_values = {'by_id': {}, 'by_name': {}}
        if db and sheet_sids:
            try:
                raw_db = get_offline_prices_by_store(db, list(sheet_sids))
                for k, v in raw_db.get('by_id', {}).items():
                    entry = {}
                    if v.get('offline_price') is not None:
                        entry['Offline Price (Rp)'] = v['offline_price']
                    if v.get('offline_adjustment') is not None:
                        entry['Offline Adjustment (Rp)'] = v['offline_adjustment']
                    if entry:
                        db_values['by_id'][k] = entry
                for k, v in raw_db.get('by_name', {}).items():
                    entry = {}
                    if v.get('offline_price') is not None:
                        entry['Offline Price (Rp)'] = v['offline_price']
                    if v.get('offline_adjustment') is not None:
                        entry['Offline Adjustment (Rp)'] = v['offline_adjustment']
                    if entry:
                        db_values['by_name'][k] = entry
            except Exception as e_db:
                print(f"[C5 Combiner] Warning reading offline prices from DB: {e_db}")

        # 2. Read previous workbook (Drive / local file backup)
        saved_from_file = _read_offline_prices(previous_workbook) if previous_workbook else {}

        # 3. Combine: DB takes priority, file fills any missing items
        combined_by_id = dict(saved_from_file.get('by_id', {}))
        combined_by_id.update(db_values.get('by_id', {}))
        combined_by_name = dict(saved_from_file.get('by_name', {}))
        combined_by_name.update(db_values.get('by_name', {}))

        # 4. Auto-seed: If file had values not in DB, save them to DB for next time
        if db and saved_from_file:
            records_to_seed = []
            for (s, iid), vals in saved_from_file.get('by_id', {}).items():
                if (s, iid) not in db_values.get('by_id', {}):
                    records_to_seed.append({
                        'store_id': s,
                        'item_id': iid,
                        'item_name': '',
                        'offline_price': vals.get('Offline Price (Rp)'),
                        'offline_adjustment': vals.get('Offline Adjustment (Rp)'),
                        'source': 'drive_backup'
                    })
            for (s, norm_name), vals in saved_from_file.get('by_name', {}).items():
                if (s, norm_name) not in db_values.get('by_name', {}):
                    records_to_seed.append({
                        'store_id': s,
                        'item_id': None,
                        'item_name': norm_name,
                        'offline_price': vals.get('Offline Price (Rp)'),
                        'offline_adjustment': vals.get('Offline Adjustment (Rp)'),
                        'source': 'drive_backup'
                    })
            if records_to_seed:
                try:
                    seeded = bulk_upsert_offline_prices(db, records_to_seed)
                    if seeded > 0:
                        print(f"[C5 Combiner] Auto-seeded {seeded} offline prices from backup workbook to database.")
                except Exception as e_seed:
                    print(f"[C5 Combiner] Failed auto-seeding offline prices to DB: {e_seed}")

        if not combined_by_id and not combined_by_name:
            workbook.close()
            return 0

        restored = 0
        for row_idx in range(DATA_START_ROW, sheet.max_row + 1):
            if is_c5_reserved_row([sheet.cell(row=row_idx, column=c).value for c in range(1, 6)]):
                continue
            sid = _identity_value(sheet.cell(row=row_idx, column=sid_col).value)
            item_id = _identity_value(sheet.cell(row=row_idx, column=item_id_col).value) if item_id_col else ''
            values = combined_by_id.get((sid, item_id)) if item_id else None
            if not values and item_name_col:
                item_name = _normalize_item_name(sheet.cell(row=row_idx, column=item_name_col).value)
                name_key = (sid, item_name)
                if item_name and target_name_counts.get(name_key) == 1:
                    values = combined_by_name.get(name_key)
            if not values:
                continue
            for name, value in values.items():
                column = offline_cols.get(name)
                if column and sheet.cell(row=row_idx, column=column).value != value:
                    sheet.cell(row=row_idx, column=column, value=value)
                    restored += 1
        workbook.save(output_path)
        workbook.close()
        matched_item_count = len(combined_by_id) + len(combined_by_name)
        print(f"[C5 Combiner] Memulihkan {restored} nilai harga offline untuk hingga {matched_item_count} item (Database diprioritaskan, cadangan Drive).")
        return restored
    except Exception as exc:
        print(f"[C5 Combiner] Gagal memulihkan harga offline: {exc}")
        return 0
    finally:
        if close_db_when_done and db:
            try:
                db.close()
            except Exception:
                pass

def _get_ofd_sort_order(ofd_val):
    v = str(ofd_val or '').strip().lower()
    if 'go' in v:
        return 1
    if 'grab' in v:
        return 2
    if 'shopee' in v or 'shope' in v:
        return 3
    return 4


def combine_c5(excel_paths, output_path, previous_workbook=None, return_restore_count=False, db=None):
    """
    Combines multiple C5 Excel files (Item & Modifier sheets) into a single C5 Excel file.
    """
    all_items = []
    all_mods = []
    for f in excel_paths:
        if f and os.path.exists(f):
            try:
                df_item = pd.read_excel(f, sheet_name='Item')
                df_mod = pd.read_excel(f, sheet_name='Modifier')
                # Filter out row 2 "Don't touch row 2" if present in input
                if not df_item.empty:
                    df_item = df_item[~df_item.iloc[:, 0].astype(str).str.lower().str.contains("don't touch")]
                    if 'Listing Name' in df_item.columns and 'Outlet Name' not in df_item.columns:
                        df_item['Outlet Name'] = df_item['Listing Name']
                    elif 'Outlet Name' in df_item.columns and 'Listing Name' not in df_item.columns:
                        df_item['Listing Name'] = df_item['Outlet Name']
                if not df_mod.empty:
                    df_mod = df_mod[~df_mod.iloc[:, 0].astype(str).str.lower().str.contains("don't touch")]
                    if 'Listing Name' in df_mod.columns and 'Outlet Name' not in df_mod.columns:
                        df_mod['Outlet Name'] = df_mod['Listing Name']
                    elif 'Outlet Name' in df_mod.columns and 'Listing Name' not in df_mod.columns:
                        df_mod['Listing Name'] = df_mod['Outlet Name']
                all_items.append(df_item)
                all_mods.append(df_mod)
            except Exception as e:
                print(f"[C5 Combiner] Error reading {f}: {e}")
                
    if not all_items:
        return False
        
    df_combined_items = pd.concat(all_items, ignore_index=True)
    df_combined_mods = pd.concat(all_mods, ignore_index=True)

    # Sort deterministically by platform (OFD): GoFood (1) -> GrabFood (2) -> ShopeeFood (3)
    # Uses stable sort on _ofd_sort ONLY to guarantee exact original menu item sequence per SID is preserved
    if 'OFD' in df_combined_items.columns:
        df_combined_items['_ofd_sort'] = df_combined_items['OFD'].map(_get_ofd_sort_order)
        df_combined_items = df_combined_items.sort_values(by=['_ofd_sort'], kind='stable').drop(columns=['_ofd_sort']).reset_index(drop=True)

    if 'OFD' in df_combined_mods.columns:
        df_combined_mods['_ofd_sort'] = df_combined_mods['OFD'].map(_get_ofd_sort_order)
        df_combined_mods = df_combined_mods.sort_values(by=['_ofd_sort'], kind='stable').drop(columns=['_ofd_sort']).reset_index(drop=True)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    template_path = str(get_c5_template_path())
    if os.path.exists(template_path):
        try:
            wb = openpyxl.load_workbook(template_path)
            sheet_item = wb['Item']
            prepare_c5_sheet(sheet_item)
            headers_item = get_c5_headers(sheet_item)
                    
            for r_idx, row in df_combined_items.iterrows():
                for col_name, val in row.items():
                    if col_name in headers_item:
                        if pd.isna(val):
                            val = ""
                        elif col_name in ['SID', 'Category ID', 'Item ID']:
                            if isinstance(val, float):
                                val = str(int(val)) if val.is_integer() else str(val)
                            else:
                                val = str(val)
                        sheet_item.cell(row=DATA_START_ROW + r_idx, column=headers_item[col_name], value=val)
                        
            # Apply percentage formatting to columns with '(%)' in the header
            for cell in sheet_item[1]:
                val_str = cell.value.text if hasattr(cell.value, 'text') else str(cell.value or "")
                if '(%)' in val_str:
                    for r in range(DATA_START_ROW, sheet_item.max_row + 1):
                        sheet_item.cell(row=r, column=cell.column).number_format = '0%'
                        
            sheet_mod = wb['Modifier']
            prepare_c5_sheet(sheet_mod)
            headers_mod = get_c5_headers(sheet_mod)
                    
            for r_idx, row in df_combined_mods.iterrows():
                for col_name, val in row.items():
                    if col_name in headers_mod:
                        if pd.isna(val):
                            val = ""
                        elif col_name in ['SID', 'Modifier Group ID', 'Modifier ID', 'Item']:
                            if isinstance(val, float):
                                val = str(int(val)) if val.is_integer() else str(val)
                            else:
                                val = str(val)
                        sheet_mod.cell(row=DATA_START_ROW + r_idx, column=headers_mod[col_name], value=val)
                        
            for cell in sheet_mod[1]:
                val_str = cell.value.text if hasattr(cell.value, 'text') else str(cell.value or "")
                if '(%)' in val_str:
                    for r in range(DATA_START_ROW, sheet_mod.max_row + 1):
                        sheet_mod.cell(row=r, column=cell.column).number_format = '0%'
                        
            wb.save(output_path)
            restored_count = _restore_offline_prices(output_path, previous_workbook, db=db)
            return {"success": True, "offline_fields_restored": restored_count} if return_restore_count else True
        except Exception as e:
            print(f"[C5 Combiner] Failed writing to template, fallback to raw pandas export: {e}")
            
    try:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_combined_items.to_excel(writer, sheet_name='Item', index=False)
            df_combined_mods.to_excel(writer, sheet_name='Modifier', index=False)
        restored_count = _restore_offline_prices(output_path, previous_workbook, db=db)
        return {"success": True, "offline_fields_restored": restored_count} if return_restore_count else True
    except Exception as ex:
        print(f"[C5 Combiner] Export error: {ex}")
        return False
