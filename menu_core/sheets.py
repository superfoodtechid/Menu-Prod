import os
import io
import time
import requests
import pandas as pd

# Force urllib3 to use IPv4 only because IPv6 is broken/blocked on some hosts and causes 2.5m connection hangs
try:
    import urllib3.util.connection
    import socket
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

DEFAULT_DBR_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSsAq8JmDfGI8KY7aSCRpzC2EaQARkK1OvhWrll7g3qlxFMIcwtDpAF-Wxf4aQnGET4eCmncjdEgre5/pub?output=csv"
GSHEETS_URL = os.getenv("DBR_CSV_URL") or os.getenv("GSHEETS_URL") or os.getenv("NOMOR_HP_CSV_URL") or DEFAULT_DBR_URL
GSHEETS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "master_merchants_cache.csv")

def get_master_df(force_download=False):
    """Downloads or loads cached GSheets master merchant list."""
    df = None
    if not force_download and os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < 180:  # Near real-time cache TTL: 3 minutes (180 seconds)
            try:
                df = pd.read_csv(CACHE_PATH)
            except Exception:
                pass
    
    if df is None:
        try:
            resp = requests.get(GSHEETS_URL, headers=GSHEETS_HEADERS, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.to_csv(CACHE_PATH, index=False)
        except Exception as e:
            if os.path.exists(CACHE_PATH):
                print(f"[Sheets Helper] Warning: GSheets download failed ({e}). Using stale cache.")
                df = pd.read_csv(CACHE_PATH)
            else:
                raise RuntimeError(f"Gagal mengunduh daftar merchant: {e}")
    if df is not None:
        df = df.fillna('')
    return df

def get_outlets_for_applicator(applicator_choice: str):
    df = get_master_df()
    
    # Deteksi kolom Aplikator (DBR) atau Aplikasi (Legacy)
    col_app = None
    for c in ["Aplikator", "Aplikasi"]:
        if c in df.columns:
            col_app = c
            break
    if not col_app:
        raise ValueError("Kolom Aplikator/Aplikasi tidak ditemukan dalam spreadsheet.")

    # Deteksi kolom Status (DBR: Status Internal, Legacy: Status)
    col_status = None
    for c in ["Status Internal", "Status"]:
        if c in df.columns:
            col_status = c
            break
    if not col_status:
        raise ValueError("Kolom Status Internal/Status tidak ditemukan dalam spreadsheet.")

    # Filter by applicator
    app_lower = applicator_choice.lower()
    if app_lower == 'shopee':
        mask = df[col_app].astype(str).str.strip().str.lower().str.contains('shopee', na=False)
    elif app_lower == 'grab':
        mask = df[col_app].astype(str).str.strip().str.lower().str.contains('grab', na=False)
    elif app_lower == 'gofood':
        mask = df[col_app].astype(str).str.strip().str.lower().str.contains('go', na=False)
    else:
        raise ValueError(f"Aplikator tidak didukung: {applicator_choice}")
        
    # Filter Tipe: Agency dan Status Internal: Live atau Progress
    col_type = None
    for c in ["Tipe", "tipe"]:
        if c in df.columns:
            col_type = c
            break

    type_mask = df[col_type].astype(str).str.strip().str.lower().str.contains('agency', na=False) if col_type else True
    live_mask = df[col_status].astype(str).str.strip().str.lower().str.contains('live|progress', na=False)
    filtered_df = df[mask & type_mask & live_mask].copy()
    
    # Deteksi kolom email GoFood (DBR: Email FoodMaster1/2; Legacy: Email Login Go 1/2)
    col_email1 = None
    col_email2 = None
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ('email foodmaster1', 'email foodmaster 1', 'email login go 1'):
            col_email1 = col
        elif cl in ('email foodmaster2', 'email foodmaster 2', 'email login go 2'):
            col_email2 = col
            
    # Deteksi kolom nomor HP
    col_phone_owner = None
    col_phone_shopee = None
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl == 's nomor hp akses pemilik':
            col_phone_shopee = col
        elif cl == 'nomor hp':
            col_phone_owner = col

    outlets = []
    for _, row in filtered_df.iterrows():
        store_id = str(row.get('Store ID', '')).strip().split('.')[0]
        if not store_id or store_id == '-' or store_id.lower() == 'nan':
            # Fallback to Group ID / Merchant ID
            store_id = str(row.get('Group ID', '') or row.get('Merchant ID', '')).strip().split('.')[0]
            
        if (not store_id or store_id == '-' or store_id.lower() == 'nan') and app_lower != 'shopee':
            continue
            
        email1 = str(row.get(col_email1, '')) if col_email1 else ''
        email2 = str(row.get(col_email2, '')) if col_email2 else ''
        
        # Phone: untuk Shopee prioritaskan S Nomor HP Akses Pemilik jika ada
        phone = ''
        if app_lower == 'shopee' and col_phone_shopee:
            phone = str(row.get(col_phone_shopee, '')).strip()
        if not phone or phone in ('-', 'nan'):
            phone = str(row.get(col_phone_owner, '')).strip() if col_phone_owner else ''
        if '.' in phone:
            phone = phone.split('.')[0]
        
        emails = []
        if email1 and email1 not in ('-', 'nan', ''):
            emails.append(email1.strip())
        if email2 and email2 not in ('-', 'nan', '') and email2.strip() != email1.strip():
            emails.append(email2.strip())
            
        if app_lower == 'gofood' and not emails:
            continue
            
        def get_valid(*col_names):
            for cn in col_names:
                v = str(row.get(cn, '')).strip()
                if v and v not in ('-', 'nan', 'None'):
                    return v
            return ''
            
        if app_lower == 'shopee':
            username = get_valid('S Username Akses Pemilik', 'Nama Pengguna', 'S Allvbadmin Username Akses Staff')
            password = get_valid('S Kata Sandi Akses Pemilik', 'Kata Sandi', 'S Allvbadmin Kata Sandi Akses Staff')
        elif app_lower == 'grab':
            username = get_valid('Nama Pengguna', 'Nama Pengguna.1')
            password = get_valid('Kata Sandi', 'Kata Sandi.1') or 'Master@123'
        else:
            username = emails[0] if emails else get_valid('Nama Pengguna', 'Nama Pengguna.1')
            password = get_valid('Kata Sandi', 'Kata Sandi.1')

        # Nama resto dan brand
        owner = get_valid('Nama Pemilik', 'Owner')
        brand = get_valid('Nama Brand', 'Brand')
        nama_listing = get_valid('Nama Listing', 'Nama Resto Final', 'Nama Tarikan', 'Outlet', 'Nama Outlet')
        outlet_name = get_valid('Outlet', 'Nama Outlet', 'Nama Listing')
        merchant_name = get_valid('Outlet', 'Merchant Name', 'Nama Brand')
            
        outlets.append({
            'store_id': store_id,
            'owner': owner,
            'nama_resto_final': nama_listing,
            'nama_listing': nama_listing,
            'nama_pendek': str(row.get('Nama Pendek Outlet (Shopee) Final', '')).strip(),
            'nama_outlet': nama_listing or outlet_name,
            'outlet': outlet_name,
            'aplikasi': str(row.get(col_app, '')).strip(),
            'merchant_name': merchant_name,
            'brand': brand,
            'email': emails[0] if emails else '',
            'emails': emails,
            'phone': phone.strip() if phone and phone != 'nan' else '',
            'username': username,
            'password': password
        })
        
    outlets = sorted(outlets, key=lambda x: x['nama_resto_final'] or x['nama_outlet'])
    return outlets
