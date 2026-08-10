"""
_menu_api.py — Shared API helper untuk menu GoFood.

Endpoints (dari curl):
  GET    /v1/restaurants/{rest_uuid}/menus
  PATCH  /v2/menu_groups/{parent_id}/menus/{cat_id}            ← rename / toggle aktif kategori
  DELETE /v2/menu_groups/{parent_id}/menus/{cat_id}            ← hapus kategori
  PATCH  /v2/menu_groups/{group_id}/menus/{menu_id}            ← rename / toggle aktif item
  GET    /v2/menu_groups/{group_id}/variant_categories
  PATCH  /v2/menu_groups/{group_id}/variant_categories/{vid}   ← rename modifier
"""

BASE_V1 = "https://api.gojekapi.com/gofood/merchant/v1"
BASE_V2 = "https://api.gojekapi.com/gofood/merchant/v2"

_HEADERS_TMPL = """(token) => ({
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'id',
    'Authentication-Type': 'go-id',
    'Authorization': token,
    'Content-Type': 'application/json',
    'Gojek-Country-Code': 'ID',
    'Origin': 'https://portal.gofoodmerchant.co.id',
    'Referer': 'https://portal.gofoodmerchant.co.id/',
})"""


def _get_headers(token, passkey=None):
    h = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'id',
        'Authentication-Type': 'go-id',
        'Authorization': token,
        'Content-Type': 'application/json',
        'Gojek-Country-Code': 'ID',
        'x-passkey': passkey or "1729b182-c60e-4568-849d-5eb7d794fd09"
    }
    return h


def _fetch(page, token, url, passkey=None):
    """GET request via page.context.request, kembalikan parsed JSON atau None."""
    try:
        res = page.context.request.get(url, headers=_get_headers(token, passkey))
        if not res.ok:
            print(f"   ⚠️ Fetch gagal [{url}]: HTTP {res.status}")
            return None
        return res.json()
    except Exception as e:
        print(f"   ⚠️ Fetch error [{url}]: {e}")
        return None


def _put(page, token, url, payload, passkey=None):
    """PUT request via page.context.request, kembalikan {ok, status, body}."""
    import json
    try:
        res = page.context.request.put(url, headers=_get_headers(token, passkey), data=json.dumps(payload))
        return { "ok": res.ok, "status": res.status, "body": res.text() }
    except Exception as e:
        return { "ok": False, "error": str(e) }


def _post(page, token, url, payload, passkey=None):
    """POST request via page.context.request, kembalikan {ok, status, body}."""
    import json
    try:
        res = page.context.request.post(url, headers=_get_headers(token, passkey), data=json.dumps(payload))
        return { "ok": res.ok, "status": res.status, "body": res.text() }
    except Exception as e:
        return { "ok": False, "error": str(e) }


def _patch(page, token, url, payload, passkey=None):
    """PATCH request via page.context.request, kembalikan {ok, status, body}."""
    import json
    try:
        res = page.context.request.patch(url, headers=_get_headers(token, passkey), data=json.dumps(payload))
        return { "ok": res.ok, "status": res.status, "body": res.text() }
    except Exception as e:
        return { "ok": False, "error": str(e) }


def _delete(page, token, url, passkey=None):
    """DELETE request via page.context.request, kembalikan {ok, status, body}."""
    try:
        res = page.context.request.delete(url, headers=_get_headers(token, passkey))
        return { "ok": res.ok, "status": res.status, "body": res.text() }
    except Exception as e:
        return { "ok": False, "error": str(e) }


# ── Public helpers ────────────────────────────────────────────

def fetch_menus(page, token, rest_uuid, passkey=None):
    """Ambil semua menu (kategori + item) dari restoran via v1."""
    return _fetch(page, token, f"{BASE_V1}/restaurants/{rest_uuid}/menus", passkey=passkey)


def fetch_menu_groups(page, token, rest_uuid, passkey=None):
    """
    Ambil menu_group_id dari restoran via V2 API.
    Endpoint: GET /v2/restaurants/{rest_uuid}
    """
    res = _fetch(page, token, f"{BASE_V2}/restaurants/{rest_uuid}", passkey=passkey)
    if res and isinstance(res, dict):
        mg_id = res.get('menu_group_id') or res.get('v2_menus_group_id') or res.get('group_id')
        if mg_id:
            return mg_id
        mgs = res.get('menu_groups') or res.get('data') or []
        if mgs and len(mgs) > 0:
            return mgs[0].get('id') or mgs[0].get('common_id')

    # Fallback ke endpoint v2 / v1 legacy menu_groups
    result = _fetch(page, token, f"{BASE_V2}/restaurants/{rest_uuid}/menu_groups", passkey=passkey)
    if result:
        return result
    return _fetch(page, token, f"{BASE_V1}/restaurants/{rest_uuid}/menu_groups", passkey=passkey)


def fetch_menus_v2(page, token, group_id, passkey=None):
    """
    Ambil daftar kategori dari menu_group via v2.
    Endpoint: GET /v2/menu_groups/{group_id}/menus
    Mengembalikan list kategori dengan ID v2 yang kompatibel untuk PATCH/DELETE.
    """
    return _fetch(page, token, f"{BASE_V2}/menu_groups/{group_id}/menus", passkey=passkey)


def parse_menus(data):
    """
    Normalisasi respons API menus → list kategori.
    Respons aktual: {'menus': [{id, name, active, menu_items: [...]}]}
    Mengembalikan list kategori dengan field ternormalisasi.
    """
    if data is None:
        return []
    # Coba berbagai kemungkinan root key
    categories = (data.get('menus')
                  or data.get('menu_categories')
                  or data.get('categories')
                  or [])
    # Normalisasi field 'active' → 'is_active' agar konsisten di UI
    for cat in categories:
        if 'active' in cat and 'is_active' not in cat:
            cat['is_active'] = cat['active']
        for item in (cat.get('menu_items') or []):
            if 'active' in item and 'is_active' not in item:
                item['is_active'] = item['active']
    return categories


def update_category(page, token, group_id, payload, passkey=None):
    """
    Rename/update kategori (menu_group).
    Endpoint: PATCH /v2/menu_groups/{group_id}
    Payload minimal: {"name": "...", "active": true/false}
    """
    return _patch(page, token, f"{BASE_V2}/menu_groups/{group_id}", payload, passkey=passkey)


def create_category(page, token, group_id, payload, passkey=None):
    """
    Buat kategori menu baru via V2 API.
    Endpoint: POST /v2/menu_groups/{group_id}/menus
    Payload: {"name": "Nama Kategori Baru", "active": true}
    """
    return _post(page, token, f"{BASE_V2}/menu_groups/{group_id}/menus", payload, passkey=passkey)


def create_menu_item(page, token, group_id, payload, passkey=None):
    """
    Buat item menu baru via V2 API.
    Endpoint: POST /v2/menu_groups/{group_id}/menu_items
    Payload: {
        "menu_common_id": "<category_id>",
        "name": "Nama Item Baru",
        "price": 15000,
        "description": "...",
        "image_url": "...",
        "active": true
    }
    """
    return _post(page, token, f"{BASE_V2}/menu_groups/{group_id}/menu_items", payload, passkey=passkey)


def update_menu_item(page, token, group_id, menu_id, payload, passkey=None):
    """
    Update/rename item atau kategori di dalam satu menu_group.
    Endpoint: PATCH /v2/menu_groups/{group_id}/menus/{menu_id}
    Payload: {"name": "...", "active": true/false}
    """
    return _patch(page, token, f"{BASE_V2}/menu_groups/{group_id}/menus/{menu_id}", payload, passkey=passkey)


def delete_menu_item(page, token, group_id, menu_id, passkey=None):
    """
    Hapus kategori/item dari menu_group.
    Endpoint: DELETE /v2/menu_groups/{group_id}/menus/{menu_id}
    """
    return _delete(page, token, f"{BASE_V2}/menu_groups/{group_id}/menus/{menu_id}", passkey=passkey)


def update_item(page, token, rest_uuid, item_id, payload, passkey=None):
    """Legacy PUT v1 — dipertahankan untuk kompatibilitas mundur."""
    return _put(page, token, f"{BASE_V1}/restaurants/{rest_uuid}/menu_items/{item_id}", payload, passkey=passkey)


def update_v2_menu_item(page, token, group_id, item_id, payload, passkey=None):
    """
    Update menu item per V2 API.
    Endpoint: PATCH /v2/menu_groups/{group_id}/menu_items/{item_id}
    """
    return _patch(page, token, f"{BASE_V2}/menu_groups/{group_id}/menu_items/{item_id}", payload, passkey=passkey)


def delete_v2_menu_item(page, token, group_id, item_id, passkey=None):
    """
    Hapus menu item per V2 API.
    Endpoint: DELETE /v2/menu_groups/{group_id}/menu_items/{item_id}
    """
    return _delete(page, token, f"{BASE_V2}/menu_groups/{group_id}/menu_items/{item_id}", passkey=passkey)


def fetch_variant_categories(page, token, group_id, passkey=None):
    """Ambil variasi (variant_categories) untuk satu menu group."""
    return _fetch(page, token, f"{BASE_V2}/menu_groups/{group_id}/variant_categories", passkey=passkey)


def update_variant_category(page, token, group_id, variant_id, payload, passkey=None):
    return _patch(page, token, f"{BASE_V2}/menu_groups/{group_id}/variant_categories/{variant_id}", payload, passkey=passkey)

def delete_variant_category(page, token, group_id, variant_id, passkey=None):
    """
    Hapus seluruh variasi (variant_category).
    Endpoint: DELETE /v2/menu_groups/{group_id}/variant_categories/{variant_id}
    """
    return _delete(page, token, f"{BASE_V2}/menu_groups/{group_id}/variant_categories/{variant_id}", passkey=passkey)

def create_variant_category(page, token, group_id, payload, passkey=None):
    """Membuat grup variasi (variant_category) baru."""
    return _post(page, token, f"{BASE_V2}/menu_groups/{group_id}/variant_categories", payload, passkey=passkey)

def create_variant(page, token, group_id, payload, passkey=None):
    """Membuat opsi (variant) baru di dalam suatu variant_category."""
    return _post(page, token, f"{BASE_V2}/menu_groups/{group_id}/variants", payload, passkey=passkey)

def delete_variant(page, token, group_id, variant_id, passkey=None):
    """Menghapus opsi (variant) dari variant_category."""
    return _delete(page, token, f"{BASE_V2}/menu_groups/{group_id}/variants/{variant_id}", passkey=passkey)


def download_bulk_csv(page, api_headers, group_id):
    """
    Download CSV template berisi daftar menu saat ini untuk bulk update.
    Endpoint: GET /v1/bulk_upload/templates?type=menu_group_menu_item_update&menu_group_id={group_id}
    """
    token = api_headers.get('authorization', '')
    url = f"{BASE_V1}/bulk_upload/templates?type=menu_group_menu_item_update&menu_group_id={group_id}"
    return page.evaluate("""async ({token, url}) => {
        try {
            const res = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'id',
                    'Authentication-Type': 'go-id',
                    'Authorization': token,
                    'Gojek-Country-Code': 'ID',
                    'Origin': 'https://portal.gofoodmerchant.co.id',
                    'Referer': 'https://portal.gofoodmerchant.co.id/'
                }
            });
            const text = await res.text();
            if (!res.ok) return { error: `HTTP ${res.status}: ${text.substring(0, 200)}` };
            return { ok: true, csv_data: text };
        } catch(e) { return { error: e.message }; }
    }""", {"token": token, "url": url})

def upload_bulk_csv(page, api_headers, group_id, b64_csv, filename, actor="Menu Updater"):
    """
    Upload file CSV (dalam format base64) untuk bulk update.
    Endpoint: POST /v1/bulk_upload
    """
    token = api_headers.get('authorization', '')
    url = f"{BASE_V1}/bulk_upload"
    import json
    payload = {
        "type": "menu_group_menu_item_update",
        "metadata": {
            "menu_group_id": group_id,
            "actor": actor
        },
        "csv_filename": filename,
        "csv_content": b64_csv
    }
    
    return page.evaluate("""async ({token, url, payload}) => {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'id',
                    'Authentication-Type': 'go-id',
                    'Authorization': token,
                    'Content-Type': 'application/json',
                    'Gojek-Country-Code': 'ID',
                    'Origin': 'https://portal.gofoodmerchant.co.id',
                    'Referer': 'https://portal.gofoodmerchant.co.id/'
                },
                body: payload
            });
            const text = await res.text();
            return { ok: res.ok, status: res.status, body: text };
        } catch(e) { return { error: e.message }; }
    }""", {"token": token, "url": url, "payload": json.dumps(payload)})


