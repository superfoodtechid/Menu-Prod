"""
menu_core/gofood_api.py - Direct REST API Client for GoFood / GoBiz.
Mengambil data menu, modifier, dan promo langsung via endpoint REST Gojek/GoBiz
tanpa perlu meluncurkan browser Chromium Playwright (fast-path ~1 detik).
"""

import os
import re
import json
import glob
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

BASE_DIR = Path(__file__).resolve().parent.parent
GOFOOD_DIR = BASE_DIR / "Gofood"
MAPPING_FILE = GOFOOD_DIR / "outlet_mapping.json"

DEFAULT_HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'id',
    'Authentication-Type': 'go-id',
    'Content-Type': 'application/json',
    'Gojek-Country-Code': 'ID',
    'Origin': 'https://portal.gofoodmerchant.co.id',
    'Referer': 'https://portal.gofoodmerchant.co.id/',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36'
}


def _get_auth_headers(token: str, passkey: Optional[str] = None) -> Dict[str, str]:
    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        auth_val = clean_token
    else:
        auth_val = f"Bearer {clean_token}"

    headers = dict(DEFAULT_HEADERS)
    headers['Authorization'] = auth_val
    if passkey:
        headers['x-passkey'] = passkey
    return headers


def load_outlet_mapping() -> Dict[str, Dict[str, Any]]:
    """Memuat cache pemetaan store_id -> {restaurant_uuid, v2_menus_group_id, city_slug}"""
    if MAPPING_FILE.exists():
        try:
            with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_outlet_mapping(mapping: Dict[str, Dict[str, Any]]) -> None:
    """Menyimpan cache pemetaan store_id -> {restaurant_uuid, v2_menus_group_id, city_slug}"""
    try:
        MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        print(f"   ⚠️ Gagal menyimpan outlet mapping: {e}")


def verify_gofood_token(access_token: str, timeout: float = 4.0) -> bool:
    """
    Validasi cepat ke API GoBiz apakah access_token masih aktif (<300ms).
    Mengembalikan True jika HTTP 200, False jika 401 atau error lain.
    """
    if not access_token or len(str(access_token).strip()) < 20:
        return False
    try:
        headers = _get_auth_headers(access_token)
        resp = requests.get('https://api.gobiz.co.id/v1/users/me', headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return True
        elif resp.status_code == 401:
            return False
    except Exception:
        pass
    return False


def find_cached_token_for_outlet(store_metadata: dict) -> Optional[str]:
    """
    Mencari token aktif dari sesi yang tersimpan di disk.
    Mengecek berdasarkan email, username, phone, store_id,
    atau file sesi GoFood terbaru yang masih valid.
    """
    email = store_metadata.get('email') or store_metadata.get('username') or ''
    phone = store_metadata.get('phone') or store_metadata.get('phone_raw') or ''
    store_id = store_metadata.get('store_id') or ''

    identifiers_to_check = []
    if email and str(email).strip() not in ('-', '', 'None'):
        identifiers_to_check.append(str(email).strip().lower())
    if phone and str(phone).strip() not in ('-', '', 'None'):
        identifiers_to_check.append(str(phone).strip())
    if store_id and str(store_id).strip() not in ('-', '', 'None'):
        identifiers_to_check.append(str(store_id).strip())

    # 1. Cek sesi spesifik untuk identifier yang cocok
    for ident in identifiers_to_check:
        sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', ident)
        session_file = GOFOOD_DIR / f"session_gofood_{sanitized}.json"
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                tok = data.get('access_token')
                if tok and verify_gofood_token(tok):
                    return tok
            except Exception:
                pass

    # 2. Cek semua sesi di folder Gofood, urutkan berdasarkan yang paling baru dimodifikasi
    all_sessions = glob.glob(str(GOFOOD_DIR / "session_gofood_*.json"))
    all_sessions.sort(key=os.path.getmtime, reverse=True)

    for sf in all_sessions:
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            tok = data.get('access_token')
            if tok and verify_gofood_token(tok):
                return tok
        except Exception:
            continue

    return None


def resolve_restaurant_info(access_token: str, store_id: str) -> Dict[str, Any]:
    """
    Mendapatkan info restoran (restaurant_uuid, v2_menus_group_id, outlet_city, outlet_name)
    berdasarkan store_id (mis. G025124092, M160248, atau UUID).
    Memanfaatkan cache disk `outlet_mapping.json` jika sudah pernah diambil.
    """
    store_id_clean = str(store_id).strip()
    result = {
        'restaurant_uuid': '',
        'v2_menus_group_id': '',
        'outlet_city': '',
        'city_slug': 'indonesia',
        'outlet_name': ''
    }

    # Jika store_id sudah berformat UUID 36 karakter (e.g. 2a55bb44-ab15-4c7e-af94-71096b91e278)
    if len(store_id_clean) == 36 and store_id_clean.count('-') == 4:
        result['restaurant_uuid'] = store_id_clean

    # Cek cache
    mapping = load_outlet_mapping()
    if store_id_clean in mapping:
        cached = mapping[store_id_clean]
        result.update({
            'restaurant_uuid': cached.get('restaurant_uuid') or result['restaurant_uuid'],
            'v2_menus_group_id': cached.get('v2_menus_group_id') or '',
            'outlet_city': cached.get('outlet_city') or '',
            'city_slug': cached.get('city_slug') or 'indonesia',
            'outlet_name': cached.get('outlet_name') or ''
        })
        if result['restaurant_uuid']:
            return result

    headers = _get_auth_headers(access_token)

    # 1. Coba endpoint spesifik merchant /v1/merchants/{store_id}
    try:
        resp = requests.get(f'https://api.gobiz.co.id/v1/merchants/{store_id_clean}', headers=headers, timeout=8)
        if resp.status_code == 200:
            m_data = resp.json()
            city_raw = m_data.get('outlet_city', '')
            if city_raw:
                result['outlet_city'] = city_raw
                city_clean = re.sub(r'^(kota|kabupaten|kab\.)\s+', '', city_raw, flags=re.IGNORECASE)
                city_slug = re.sub(r'[^a-zA-Z0-9\s\-]', '', city_clean)
                result['city_slug'] = re.sub(r'\s+', '-', city_slug.strip()).lower() or 'indonesia'

            result['outlet_name'] = m_data.get('outlet_name') or m_data.get('merchant_name') or ''
            goresto = m_data.get('applications', {}).get('goresto', {})
            if goresto.get('goresto_id'):
                result['restaurant_uuid'] = goresto['goresto_id']
            if goresto.get('v2_menus_group_id'):
                result['v2_menus_group_id'] = goresto['v2_menus_group_id']
            elif m_data.get('menu_group_id'):
                result['v2_menus_group_id'] = m_data['menu_group_id']
    except Exception as e:
        print(f"   ⚠️ Info merchant {store_id_clean} via direct endpoint tidak ditemukan: {e}")

    # 2. Jika belum mendapatkan restaurant_uuid, coba via /v1/merchants/search
    if not result['restaurant_uuid']:
        try:
            search_payload = {
                "from": 0,
                "size": 1000,
                "_source": ["id", "merchant_name", "outlet_name", "outlet_city", "applications"]
            }
            resp_s = requests.post('https://api.gobiz.co.id/v1/merchants/search', headers=headers, json=search_payload, timeout=10)
            if resp_s.status_code == 200:
                hits = resp_s.json().get('hits', [])
                updated_cache = False
                for h in hits:
                    src = h.get('_source', h)
                    hid = str(src.get('id', '')).strip()
                    h_goresto = src.get('applications', {}).get('goresto', {}).get('goresto_id', '')
                    h_v2_gid = src.get('applications', {}).get('goresto', {}).get('v2_menus_group_id', '')
                    h_city = src.get('outlet_city', '')
                    h_name = src.get('outlet_name') or src.get('merchant_name') or ''

                    h_city_clean = re.sub(r'^(kota|kabupaten|kab\.)\s+', '', h_city, flags=re.IGNORECASE) if h_city else ''
                    h_city_slug = re.sub(r'[^a-zA-Z0-9\s\-]', '', h_city_clean) if h_city_clean else 'indonesia'
                    h_city_slug = re.sub(r'\s+', '-', h_city_slug.strip()).lower() if h_city_slug else 'indonesia'

                    if hid and h_goresto:
                        mapping[hid] = {
                            'restaurant_uuid': h_goresto,
                            'v2_menus_group_id': h_v2_gid,
                            'outlet_city': h_city,
                            'city_slug': h_city_slug,
                            'outlet_name': h_name
                        }
                        updated_cache = True

                    if hid == store_id_clean:
                        result['restaurant_uuid'] = h_goresto or result['restaurant_uuid']
                        result['v2_menus_group_id'] = h_v2_gid or result['v2_menus_group_id']
                        result['outlet_city'] = h_city or result['outlet_city']
                        result['city_slug'] = h_city_slug
                        result['outlet_name'] = h_name or result['outlet_name']

                if updated_cache:
                    save_outlet_mapping(mapping)
        except Exception as e:
            print(f"   ⚠️ Search merchant API failed: {e}")

    # Simpan kembali ke cache jika berhasil mendapatkan data
    if result['restaurant_uuid'] and store_id_clean:
        mapping[store_id_clean] = result
        save_outlet_mapping(mapping)

    return result


def fetch_direct_gofood_menus(access_token: str, restaurant_uuid: str, store_id: str = "", group_id: str = "") -> Optional[Dict[str, Any]]:
    """
    Mengambil data menu restoran dari REST API Gojek/GoBiz.
    Mencoba beberapa endpoint secara berurutan:
      1. GET /v1/restaurants/{restaurant_uuid}/menus
      2. GET /v2/menu_groups/{group_id}/menus (jika group_id tersedia)
      3. GET /v1/restaurants/{store_id}/menus (jika store_id berbeda dengan uuid)
    """
    headers = _get_auth_headers(access_token)

    candidates = []
    if restaurant_uuid:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{restaurant_uuid}/menus")
    if group_id:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v2/menu_groups/{group_id}/menus")
    if store_id and store_id != restaurant_uuid:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{store_id}/menus")

    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    menus = data.get('menus') or data.get('categories')
                    if menus and len(menus) > 0:
                        # Normalisasi format jika diperlukan
                        if 'menus' not in data and 'categories' in data:
                            data['menus'] = data['categories']
                        return data
                elif isinstance(data, list) and len(data) > 0:
                    return {'menus': data}
        except Exception:
            continue

    return None


def fetch_direct_gofood_modifiers(access_token: str, restaurant_uuid: str, group_id: str = "", store_id: str = "") -> List[Dict[str, Any]]:
    """
    Mengambil daftar variant categories / modifier restoran secara langsung dari API.
    Endpoint:
      1. GET /v1/restaurants/{restaurant_uuid}/variant_categories
      2. GET /v2/menu_groups/{group_id}/variant_categories
      3. GET /v1/restaurants/{store_id}/variant_categories
    """
    headers = _get_auth_headers(access_token)

    candidates = []
    if restaurant_uuid:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{restaurant_uuid}/variant_categories")
    if group_id:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v2/menu_groups/{group_id}/variant_categories")
    if store_id and store_id != restaurant_uuid:
        candidates.append(f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{store_id}/variant_categories")

    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    cats = data.get('variant_categories') or data.get('data') or []
                    if cats:
                        return cats
                elif isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            continue

    return []


def fetch_gofood_menu_and_modifiers(access_token: str, store_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Fungsi orkestrasi lengkap:
    1. Resolve restaurant UUID & metadata.
    2. Tarik data menus.
    3. Tarik data modifiers.
    Mengembalikan (success, {captured_menu, captured_modifiers, restaurant_uuid, city_slug, access_token}).
    """
    print(f"   ⚡ [Direct API] Menghubungi REST API GoFood untuk Store ID: {store_id}...")
    start_t = time.time()

    info = resolve_restaurant_info(access_token, store_id)
    rest_uuid = info.get('restaurant_uuid') or store_id
    group_id = info.get('v2_menus_group_id') or ''
    city_slug = info.get('city_slug') or 'indonesia'

    # 1. Fetch menu
    menu_data = fetch_direct_gofood_menus(access_token, rest_uuid, store_id=store_id, group_id=group_id)
    if not menu_data:
        print(f"   ⚠️ [Direct API] Menu tidak ditemukan untuk {store_id} / {rest_uuid}")
        return False, {}

    # Update restaurant_uuid jika ada di dalam menu_items
    for cat in menu_data.get('menus', []):
        if cat.get('restaurant_id'):
            rest_uuid = cat.get('restaurant_id')
            break
        for it in cat.get('menu_items', []):
            if it.get('restaurant_id'):
                rest_uuid = it.get('restaurant_id')
                break
        if rest_uuid:
            break

    # 2. Fetch modifiers
    modifiers = fetch_direct_gofood_modifiers(access_token, rest_uuid, group_id=group_id, store_id=store_id)

    elapsed = round(time.time() - start_t, 2)
    categories_cnt = len(menu_data.get('menus', []))
    items_cnt = sum(len(c.get('menu_items', [])) for c in menu_data.get('menus', []))
    print(f"   ✅ [Direct API] Berhasil menarik {categories_cnt} kategori ({items_cnt} item), {len(modifiers)} modifier dalam {elapsed} detik!")

    return True, {
        'captured_menu': menu_data,
        'captured_modifiers': modifiers,
        'restaurant_uuid': rest_uuid,
        'city_slug': city_slug,
        'access_token': access_token
    }
