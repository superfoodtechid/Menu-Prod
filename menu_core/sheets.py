import os
import io
import time
import requests
import pandas as pd

GSHEETS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ3tLKBNXDqRgBw0mNhKZFxgvKx-JoiTDzm_s5Ix1cm7O6HCv4IvExOLR2HSRVaXSsx82V348mcr9X4/pub?output=csv&gid=0&single=true"
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
            cache_buster = f"&t={int(time.time())}" if "?" in GSHEETS_URL else f"?t={int(time.time())}"
            resp = requests.get(GSHEETS_URL + cache_buster, timeout=30)
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
    
    # Filter by applicator
    app_lower = applicator_choice.lower()
    if app_lower == 'shopee':
        mask = df['Aplikasi'].str.strip().str.lower().str.contains('shopee', na=False)
    elif app_lower == 'grab':
        mask = df['Aplikasi'].str.strip().str.lower().str.contains('grab', na=False)
    elif app_lower == 'gofood':
        mask = df['Aplikasi'].str.strip().str.lower().str.contains('go', na=False)
    else:
        raise ValueError(f"Aplikator tidak didukung: {applicator_choice}")
        
    # Filter Live status
    live_mask = df['Status'].str.strip().str.lower() == 'live'
    filtered_df = df[mask & live_mask].copy()
    
    # Find columns dynamically for gofood
    col_email1 = None
    col_email2 = None
    col_phone = None
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl == 'email login go 1':
            col_email1 = col
        elif cl == 'email login go 2':
            col_email2 = col
            
    phone_cols = [col for col in df.columns if 'nomor hp' in str(col).lower()]
    if len(phone_cols) > 1:
        col_phone = phone_cols[1]
    elif len(phone_cols) == 1:
        col_phone = phone_cols[0]

    outlets = []
    for _, row in filtered_df.iterrows():
        store_id = str(row.get('Store ID', '')).strip().split('.')[0]
        if not store_id or store_id == '-' or store_id.lower() == 'nan':
            # Fallback to Merchant ID if Store ID is empty (e.g., for GoFood)
            store_id = str(row.get('Merchant ID', '')).strip().split('.')[0]
            
        if (not store_id or store_id == '-' or store_id.lower() == 'nan') and app_lower != 'shopee':
            continue
            
        email1 = str(row.get(col_email1, '')) if col_email1 else ''
        email2 = str(row.get(col_email2, '')) if col_email2 else ''
        phone = str(row.get(col_phone, '')) if col_phone else ''
        
        emails = []
        if email1 and email1 != '-' and email1 != 'nan':
            emails.append(email1.strip())
        if email2 and email2 != '-' and email2 != 'nan' and email2.strip() != email1.strip():
            emails.append(email2.strip())
            
        if app_lower == 'gofood' and not emails:
            continue
            
        def get_valid(c1, c2):
            v = str(row.get(c1, '')).strip()
            if v and v != '-' and v != 'nan':
                return v
            v = str(row.get(c2, '')).strip()
            if v and v != '-' and v != 'nan':
                return v
            return ''
            
        if app_lower == 'shopee':
            username = ''
            password = ''
        elif app_lower == 'grab':
            username = get_valid('Nama Pengguna.1', 'Nama Pengguna')
            password = get_valid('Kata Sandi.1', 'Kata Sandi')
        else:
            username = get_valid('Nama Pengguna', 'Nama Pengguna.1')
            password = get_valid('Kata Sandi', 'Kata Sandi.1')
            
        outlets.append({
            'store_id': store_id,
            'owner': str(row.get('Owner', '')).strip(),
            'nama_resto_final': str(row.get('Nama Resto Final', '')).strip(),
            'nama_pendek': str(row.get('Nama Pendek Outlet (Shopee) Final', '')).strip(),
            'nama_outlet': str(row.get('Nama Outlet', '')).strip(),
            'aplikasi': str(row.get('Aplikasi', '')).strip(),
            'merchant_name': str(row.get('Merchant Name', '')).strip(),
            'brand': str(row.get('Brand', '')).strip(),
            'email': emails[0] if emails else '',
            'emails': emails,
            'phone': phone.strip() if phone and phone != 'nan' else '',
            'username': username,
            'password': password
        })
        
    outlets = sorted(outlets, key=lambda x: x['nama_resto_final'] or x['nama_outlet'])
    return outlets
