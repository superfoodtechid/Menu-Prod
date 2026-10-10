import os
import re
import io
import openpyxl
import pandas as pd

FILE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(FILE_DIR, "O. C5 Template.xlsx")
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
        for row in sheet.iter_rows(min_row=2, values_only=True):
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


def _restore_offline_prices(output_path, previous_workbook):
    saved_values = _read_offline_prices(previous_workbook)
    if not saved_values or not (saved_values.get('by_id') or saved_values.get('by_name')):
        return 0
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

        target_name_counts = {}
        if item_name_col:
            for row_idx in range(2, sheet.max_row + 1):
                sid = _identity_value(sheet.cell(row=row_idx, column=sid_col).value)
                item_name = _normalize_item_name(sheet.cell(row=row_idx, column=item_name_col).value)
                if sid and item_name:
                    key = (sid, item_name)
                    target_name_counts[key] = target_name_counts.get(key, 0) + 1

        restored = 0
        for row_idx in range(2, sheet.max_row + 1):
            sid = _identity_value(sheet.cell(row=row_idx, column=sid_col).value)
            item_id = _identity_value(sheet.cell(row=row_idx, column=item_id_col).value) if item_id_col else ''
            values = saved_values['by_id'].get((sid, item_id)) if item_id else None
            if not values and item_name_col:
                item_name = _normalize_item_name(sheet.cell(row=row_idx, column=item_name_col).value)
                name_key = (sid, item_name)
                if item_name and target_name_counts.get(name_key) == 1:
                    values = saved_values['by_name'].get(name_key)
            if not values:
                continue
            for name, value in values.items():
                column = offline_cols.get(name)
                if column and sheet.cell(row=row_idx, column=column).value != value:
                    sheet.cell(row=row_idx, column=column, value=value)
                    restored += 1
        workbook.save(output_path)
        workbook.close()
        matched_item_count = len(saved_values['by_id']) + len(saved_values['by_name'])
        print(f"[C5 Combiner] Memulihkan {restored} nilai harga offline untuk hingga {matched_item_count} item (Item ID diprioritaskan, nama unik sebagai cadangan).")
        return restored
    except Exception as exc:
        print(f"[C5 Combiner] Gagal memulihkan harga offline: {exc}")
        return 0

def _get_ofd_sort_order(ofd_val):
    v = str(ofd_val or '').strip().lower()
    if 'go' in v:
        return 1
    if 'grab' in v:
        return 2
    if 'shopee' in v or 'shope' in v:
        return 3
    return 4


def combine_c5(excel_paths, output_path, previous_workbook=None, return_restore_count=False):
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
    
    if os.path.exists(TEMPLATE_PATH):
        try:
            wb = openpyxl.load_workbook(TEMPLATE_PATH)
            sheet_item = wb['Item']
            if sheet_item.max_row > 1:
                sheet_item.delete_rows(2, sheet_item.max_row - 1)
                
            headers_item = {}
            for cell in sheet_item[1]:
                if isinstance(cell.value, str):
                    headers_item[cell.value] = cell.column
                    
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
                        cell = sheet_item.cell(row=r_idx + 2, column=headers_item[col_name], value=val)
                        
            # Apply percentage formatting to columns with '(%)' in the header
            for cell in sheet_item[1]:
                val_str = cell.value.text if hasattr(cell.value, 'text') else str(cell.value or "")
                if '(%)' in val_str:
                    for r in range(2, sheet_item.max_row + 1):
                        sheet_item.cell(row=r, column=cell.column).number_format = '0%'
                        
            sheet_mod = wb['Modifier']
            if sheet_mod.max_row > 1:
                sheet_mod.delete_rows(2, sheet_mod.max_row - 1)
                
            headers_mod = {}
            for cell in sheet_mod[1]:
                if isinstance(cell.value, str):
                    headers_mod[cell.value] = cell.column
                    
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
                        sheet_mod.cell(row=r_idx + 2, column=headers_mod[col_name], value=val)
                        
            for cell in sheet_mod[1]:
                val_str = cell.value.text if hasattr(cell.value, 'text') else str(cell.value or "")
                if '(%)' in val_str:
                    for r in range(2, sheet_mod.max_row + 1):
                        sheet_mod.cell(row=r, column=cell.column).number_format = '0%'
                        
            wb.save(output_path)
            restored_count = _restore_offline_prices(output_path, previous_workbook)
            return {"success": True, "offline_fields_restored": restored_count} if return_restore_count else True
        except Exception as e:
            print(f"[C5 Combiner] Failed writing to template, fallback to raw pandas export: {e}")
            
    try:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_combined_items.to_excel(writer, sheet_name='Item', index=False)
            df_combined_mods.to_excel(writer, sheet_name='Modifier', index=False)
        restored_count = _restore_offline_prices(output_path, previous_workbook)
        return {"success": True, "offline_fields_restored": restored_count} if return_restore_count else True
    except Exception as ex:
        print(f"[C5 Combiner] Export error: {ex}")
        return False
