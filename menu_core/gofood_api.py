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
from typing import Optional, Dict, Any, Tuple, List, Union, Callable

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


def calculate_price_steps(current_price: float, target_price: float, max_step_pct: float = 0.15) -> List[int]:
    """
    Menghitung harga bertahap (intermediate price steps) agar perubahan harga
    tidak melampaui batas maksimal per tahap (default 15%) dari GoFood.
    """
    import math
    curr = float(current_price)
    target = float(target_price)
    if curr <= 0 or curr == target:
        return [int(round(target))]

    steps = []
    if target > curr:
        while curr < target:
            next_p = curr * (1.0 + max_step_pct)
            if next_p >= target:
                steps.append(int(round(target)))
                break
            else:
                next_p_rounded = int(math.floor(next_p / 100.0) * 100)
                if next_p_rounded <= curr:
                    next_p_rounded = int(curr) + 100
                if next_p_rounded >= target:
                    steps.append(int(round(target)))
                    break
                steps.append(next_p_rounded)
                curr = float(next_p_rounded)
    else:  # target < curr
        while curr > target:
            next_p = curr * (1.0 - max_step_pct)
            if next_p <= target:
                steps.append(int(round(target)))
                break
            else:
                next_p_rounded = int(math.ceil(next_p / 100.0) * 100)
                if next_p_rounded >= curr:
                    next_p_rounded = int(curr) - 100
                if next_p_rounded <= target:
                    steps.append(int(round(target)))
                    break
                steps.append(next_p_rounded)
                curr = float(next_p_rounded)
    return steps


def fetch_direct_menu_groups(access_token: str, rest_uuid: str, passkey: Optional[str] = None) -> Optional[str]:
    """Mengambil menu_group_id langsung via REST API tanpa Playwright."""
    headers = _get_auth_headers(access_token, passkey=passkey)
    candidates = [
        f"https://api.gojekapi.com/gofood/merchant/v2/restaurants/{rest_uuid}",
        f"https://api.gojekapi.com/gofood/merchant/v2/restaurants/{rest_uuid}/menu_groups",
        f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{rest_uuid}/menu_groups"
    ]
    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                res = resp.json()
                if isinstance(res, dict):
                    mg_id = res.get('menu_group_id') or res.get('v2_menus_group_id') or res.get('group_id')
                    if mg_id:
                        return mg_id
                    mgs = res.get('menu_groups') or res.get('data') or []
                    if mgs and len(mgs) > 0:
                        return mgs[0].get('id') or mgs[0].get('common_id')
                elif isinstance(res, list) and len(res) > 0:
                    return res[0].get('id') or res[0].get('common_id')
                elif isinstance(res, str) and len(res) > 10:
                    return res
        except Exception:
            continue
    return None


def push_gofood_item_price_single(
    session: requests.Session,
    token: str,
    group_id: str,
    rest_uuid: str,
    item_id: str,
    orig_item: Dict[str, Any],
    cat_common_id: str,
    new_price: Union[int, float],
    passkey: str = "1729b182-c60e-4568-849d-5eb7d794fd09",
    mpp_promos_map: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Memperbarui harga 1 menu item GoFood secara langsung via REST API.
    Mendukung:
    - Kunci proteksi promo nominal tetap (mencegah kerugian margin merchant).
    - Stepping bertahap 15% jika lonjakan harga signifikan.
    - V2 PATCH endpoint (primary) dengan auto-retry saat rate limit (HTTP 429/503).
    - Fallback variant_category_common_ids jika payload standar ditolak.
    - Fallback V1 PUT jika V2 tidak tersedia.
    """
    # 1. Cek proteksi promo nominal
    item_name = (orig_item.get("name") or "").strip().lower()
    mpp_promos = mpp_promos_map or {}
    mpp_info = mpp_promos.get(str(item_id).strip()) or mpp_promos.get(item_name)
    promo_info = orig_item.get("promo_info") or orig_item.get("discount") or orig_item.get("campaign") or mpp_info
    original_p = float(orig_item.get("original_price") or orig_item.get("list_price") or 0)
    cur_p = float(orig_item.get("price") or 0)
    is_go_promo = bool(promo_info) or (original_p > cur_p > 0)

    is_nominal_promo = False
    promo_desc = ""
    if is_go_promo:
        if isinstance(promo_info, dict):
            pct = promo_info.get("discount_percentage") or promo_info.get("percentage")
            val = promo_info.get("discount_value") or promo_info.get("value") or promo_info.get("amount")
            if pct and float(pct) > 0:
                is_nominal_promo = False
                promo_desc = f"Persentase ({int(float(pct))}%)"
            elif val and float(val) > 0:
                is_nominal_promo = True
                promo_desc = f"Nominal (Rp {int(float(val)):,})"
        elif original_p > cur_p > 0:
            diff = original_p - cur_p
            is_nominal_promo = True
            promo_desc = f"Nominal (Rp {int(diff):,})"

    # Kunci jika promo berjenis NOMINAL TETAP
    if is_go_promo and is_nominal_promo:
        item_label = orig_item.get("name", item_id)
        err_promo = f"Item '{item_label}' sedang dalam promo nominal tetap GoFood ({promo_desc}). Perubahan harga dasar dikunci untuk mencegah kerugian margin."
        return {
            "success": False,
            "status": "SKIPPED_ACTIVE_PROMO",
            "old_price": cur_p,
            "new_price": float(new_price),
            "error": err_promo
        }

    # 2. Hitung intermediate price steps
    old_price = int(float(orig_item.get('price') or 0))
    target_price = float(new_price)
    steps = calculate_price_steps(old_price, target_price, max_step_pct=0.15)

    headers_direct = _get_auth_headers(token, passkey=passkey)
    patch_group_id = group_id or orig_item.get('menu_common_id') or cat_common_id
    v2_url = f"https://api.gojekapi.com/gofood/merchant/v2/menu_groups/{patch_group_id}/menu_items/{item_id}"

    def _send_patch_request(payload_data: dict, max_retries: int = 2) -> dict:
        for attempt in range(max_retries + 1):
            try:
                resp = session.patch(v2_url, headers=headers_direct, json=payload_data, timeout=15)
                code = resp.status_code
                if code in (429, 403, 503, 504) and attempt < max_retries:
                    backoff_sec = 6.0 * (attempt + 1)
                    time.sleep(backoff_sec)
                    continue
                return {'ok': 200 <= code < 300, 'status': code, 'body': resp.text}
            except Exception as ex:
                if attempt < max_retries:
                    time.sleep(2.0)
                    continue
                return {'ok': False, 'status': 0, 'error': str(ex)}
        return {'ok': False, 'status': 0, 'error': 'Max retries exceeded'}

    res = None
    for step_idx, step_p in enumerate(steps):
        v2_payload = {
            "menu_common_id": orig_item.get('menu_common_id') or cat_common_id,
            "image_url": orig_item.get('image_url', orig_item.get('image', '')),
            "name": orig_item.get('name'),
            "description": orig_item.get('description', ''),
            "price": int(step_p),
            "active": orig_item.get('is_active', orig_item.get('active', True)),
            "signature": orig_item.get('signature', False)
        }

        res = _send_patch_request(v2_payload)

        # Jika terkena 429, jeda tambahan
        if res and res.get('status') == 429:
            time.sleep(8.0)

        # Fallback 1: variant_category_common_ids
        if (not res or not res.get('ok')) and res.get('status') != 429:
            time.sleep(0.4)
            vars_ids = orig_item.get('variant_category_common_ids') or orig_item.get('variant_category_ids')
            if vars_ids and isinstance(vars_ids, list) and len(vars_ids) > 0:
                v2_with_vars = dict(v2_payload)
                v2_with_vars["variant_category_common_ids"] = vars_ids
                res_var = _send_patch_request(v2_with_vars, max_retries=1)
                if res_var and res_var.get('ok'):
                    res = res_var

        # Fallback 2: V1 PUT jika V2 gagal
        if (not res or not res.get('ok')) and res.get('status') != 429:
            time.sleep(0.4)
            v1_item_id = orig_item.get('id') or orig_item.get('common_id') or item_id
            if v1_item_id and rest_uuid:
                v1_url = f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{rest_uuid}/menu_items/{v1_item_id}"
                v1_payload = {
                    "name": orig_item.get('name'),
                    "price": int(step_p),
                    "active": orig_item.get('active', True),
                    "description": orig_item.get('description', ''),
                    "image": orig_item.get('image_url', orig_item.get('image', ''))
                }
                try:
                    v1_resp = session.put(v1_url, headers=headers_direct, json=v1_payload, timeout=15)
                    res = {'ok': 200 <= v1_resp.status_code < 300, 'status': v1_resp.status_code, 'body': v1_resp.text}
                except Exception as e:
                    res = {'ok': False, 'status': 0, 'error': str(e)}

        if not (res and res.get('ok')):
            err_msg = res.get('body') or res.get('error') or "GoFood API error" if res else "Unknown error"
            return {
                "success": False,
                "status": "FAILED",
                "old_price": old_price,
                "new_price": target_price,
                "error": err_msg
            }

        if step_idx < len(steps) - 1:
            time.sleep(1.0)

    return {
        "success": True,
        "status": "SUCCESS",
        "old_price": old_price,
        "new_price": target_price,
        "error": None
    }


def push_gofood_price_batch(
    access_token: str,
    store_id: str,
    updates_list: List[Dict[str, Any]],
    restaurant_uuid: Optional[str] = None,
    group_id: Optional[str] = None,
    passkey: Optional[str] = None,
    progress_callback: Optional[Any] = None,
    item_result_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Eksekusi batch update harga GoFood 100% Direct REST API tanpa browser Chromium.
    Menghilangkan overhead RAM 800MB+ dan memangkas waktu inisialisasi dari 45s ke <1s.
    """
    total_updates = len(updates_list)
    success_count = 0
    fail_count = 0
    skipped_count = 0
    results = []

    session = requests.Session()
    pk = passkey or "1729b182-c60e-4568-849d-5eb7d794fd09"

    # 1. Resolve restaurant UUID & group_id
    info = resolve_restaurant_info(access_token, store_id)
    rest_uuid = restaurant_uuid or info.get('restaurant_uuid') or store_id
    grp_id = group_id or info.get('v2_menus_group_id') or ''

    if not grp_id and rest_uuid and len(rest_uuid) == 36:
        grp_id = fetch_direct_menu_groups(access_token, rest_uuid, passkey=pk) or ''

    # 2. Ambil data menu untuk mencocokkan item & kategori
    def _find_gofood_cache_file(m_id: str) -> Optional[Path]:
        cands = [m_id, m_id.replace("GM", "M"), m_id.lstrip("G"), m_id.strip()]
        for cid in cands:
            cp = GOFOOD_DIR / "API" / f"menu-response-{cid}.json"
            if cp.exists():
                return cp
        return None

    menu_data = None
    cache_file = _find_gofood_cache_file(store_id)
    if cache_file and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                menu_data = json.load(f)
        except Exception:
            pass

    if not menu_data:
        menu_data = fetch_direct_gofood_menus(access_token, rest_uuid, store_id=store_id, group_id=grp_id)

    if not menu_data:
        raise Exception(f"Gagal menarik menu GoFood untuk store {store_id} ({rest_uuid}).")

    # 3. Indeks item GoFood
    categories = menu_data.get('menus') or menu_data.get('categories') or []
    go_items_by_id = {}
    for cat in categories:
        cat_group = cat.get("menu_common_id") or cat.get("common_id") or cat.get("id")
        for it in (cat.get("menu_items") or []):
            iid = it.get("common_id") or it.get("id")
            go_items_by_id[str(iid)] = {
                "item": it,
                "category_id": cat.get("id"),
                "category_common_id": cat.get("common_id") or cat_group
            }

    # 4. Ambil active MPP promo map
    mpp_promos_map = {}
    try:
        from menu_core.gofood import fetch_gofood_mpp_promotions
        clean_tok = access_token.replace("Bearer ", "").strip()
        mpp_promos_map = fetch_gofood_mpp_promotions(clean_tok, rest_uuid)
    except Exception as mpp_err:
        print(f"   ⚠️ Gagal fetch MPP promo map: {mpp_err}")

    # 5. Iterasi push tiap item
    for idx, update in enumerate(updates_list):
        item_id = str(update["item_id"])
        new_price = update["new_price"]

        item_info = go_items_by_id.get(item_id)
        if not item_info:
            fail_count += 1
            item_res = {
                "item_id": item_id,
                "item_name": item_id,
                "old_price": None,
                "new_price": str(new_price),
                "status": "FAILED",
                "error_message": "Item ID tidak ditemukan di menu GoFood."
            }
            results.append(item_res)
            if item_result_callback:
                item_result_callback(item_res)
        else:
            orig_item = item_info["item"]
            cat_common_id = item_info["category_common_id"] or item_info["category_id"]

            res = push_gofood_item_price_single(
                session=session,
                token=access_token,
                group_id=grp_id,
                rest_uuid=rest_uuid,
                item_id=item_id,
                orig_item=orig_item,
                cat_common_id=cat_common_id,
                new_price=new_price,
                passkey=pk,
                mpp_promos_map=mpp_promos_map
            )

            st = res["status"]
            if st == "SUCCESS":
                success_count += 1
            elif st == "SKIPPED_ACTIVE_PROMO":
                skipped_count += 1
            else:
                fail_count += 1

            item_res = {
                "item_id": item_id,
                "item_name": orig_item.get("name", item_id),
                "old_price": str(res.get("old_price", orig_item.get("price", 0))),
                "new_price": str(new_price),
                "status": st,
                "error_message": res.get("error")
            }
            results.append(item_res)

            if item_result_callback:
                item_result_callback(item_res)

            # Pacing delay jitter (0.6s - 1.2s)
            import random
            time.sleep(random.uniform(0.6, 1.2))

        # Batch breather setiap 20 item
        if (idx + 1) % 20 == 0 and (idx + 1) < total_updates:
            time.sleep(3.0)

        # Progress callback
        if progress_callback and ((idx + 1) % 5 == 0 or (idx + 1) == total_updates):
            pct = int(40 + ((idx + 1) / total_updates) * 55)
            msg = f"Memproses update harga GoFood Direct API ({idx + 1}/{total_updates})..."
            progress_callback(pct, msg)

    return {
        "total": total_updates,
        "success_count": success_count,
        "fail_count": fail_count,
        "skipped_count": skipped_count,
        "results": results
    }

