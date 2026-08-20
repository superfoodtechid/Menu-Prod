# -*- coding: utf-8 -*-
"""
shopee/core/push.py — Push Update Harga Shopee Partner.
Disesuaikan secara simetris dengan shopee/core/pull.py.
Menggunakan engine browser core yang sama (browser.get_session)
dengan penanganan otomatis sesi tersimpan, switcher merchant, dan OTP.
"""

import sys
import json
import time
from pathlib import Path
from shopee.core.client import ShopeeModifyClient
from shopee.core.edit import update_dish, _resolve_target_merchant_name

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

def _boot_push_client(store_metadata: dict, headless: bool = True) -> tuple[ShopeeModifyClient | None, str]:
    store_id = store_metadata.get("store_id")
    if isinstance(store_id, str):
        store_id = store_id.strip().split('.')[0]
    if not store_id or store_id == '-' or str(store_id).lower() == 'nan':
        store_id = None

    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"
    
    m_name = store_metadata.get('merchant_name', '')
    if not m_name or m_name.lower() == 'nan' or m_name == '-':
        target_name = store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''
    else:
        target_name = m_name
        
    target_name = _resolve_target_merchant_name(username, target_name, store_metadata)
    
    automation_data_dir = AUTOMATION_DIR / "data"
    automation_data_dir.mkdir(parents=True, exist_ok=True)
    session_file = automation_data_dir / f"session_{username}.json"
    browser.set_session_file(session_file)
    
    print(f"[*] [PUSH] Membuka browser (headless={headless}) untuk akun '{username}', merchant: '{target_name}'...")
    session_data = None
    try:
        session_data = browser.get_session(
            username=username,
            password=password,
            headless=headless,
            close_browser=True,
            target_name=target_name,
            interactive=True
        )
    except Exception as e:
        print(f"[WARN] get_session with target_name '{target_name}' failed ({e}). Retrying without target_name filter...")
        try:
            session_data = browser.get_session(
                username=username,
                password=password,
                headless=headless,
                close_browser=True,
                target_name="",
                interactive=True
            )
        except Exception as ex:
            return None, f"Gagal menginisialisasi browser session: {ex}"

    if not session_data or "shopee_tob_token" not in session_data:
        return None, f"Gagal menginisialisasi browser session untuk akun '{username}'"

    tob_token = session_data["shopee_tob_token"]

    # Extract real merchant_id via GetUserInfo API
    import requests
    user_info_url = "https://api.partner.shopee.co.id/nb/mss/web-api/PartnerAccountServer/GetUserInfo"
    user_headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://partner.shopee.co.id",
        "referer": "https://partner.shopee.co.id/",
        "x-merchant-token": tob_token
    }
    real_store_id = str(store_id) if store_id else ""
    real_merchant_id = ""
    try:
        u_resp = requests.post(user_info_url, headers=user_headers, json={}, timeout=10)
        u_data = u_resp.json().get("data", {})
        if not real_store_id and u_data.get("store_id"):
            real_store_id = str(u_data["store_id"])
        if u_data.get("merchantId"):
            real_merchant_id = str(u_data["merchantId"])
    except Exception as e:
        print(f"[WARN] GetUserInfo lookup failed: {e}")

    extra_cookies = session_data.get("extra_cookies", {}).copy()
    extra_cookies["shopee_user_name"] = username
    extra_cookies["shopee_request_from"] = "partner_web"
    if real_merchant_id:
        extra_cookies["shopee_foody_mid"] = real_merchant_id
    if real_store_id:
        extra_cookies["shopee_tob_entity_id"] = real_store_id

    client = ShopeeModifyClient(
        tob_token=tob_token,
        entity_id=real_store_id or str(store_id or ""),
        extra_cookies=extra_cookies,
        merchant_id=real_merchant_id or str(store_id or ""),
        username=username
    )
    return client, ""

def push_price_update_dish(
    store_metadata: dict,
    dish_id: str,
    new_price: float,
    headless: bool = True
) -> tuple[bool, str]:
    """
    Melakukan PUSH perubahan harga item menu ke Shopee Partner API
    dengan autentikasi browser session yang presisi per akun & outlet.
    """
    client, err = _boot_push_client(store_metadata, headless=headless)
    if not client:
        return False, f"Boot client failed: {err}"
        
    store_id = client.entity_id or store_metadata.get("store_id")
    if not store_id:
        return False, "Store ID / Entity ID Shopee tidak ditemukan"

    dish = client.get_dish_detail(dish_id, store_id)
    if not dish:
        catalog_id = 0
        target_name = str(dish_id)
        target_desc = ""
        target_avail = True
        target_pic = ""
        opt_groups = []
        existing_dish = None
    else:
        catalog_id = dish.get("catalog_id", 0)
        target_name = dish.get("name", str(dish_id))
        target_desc = dish.get("description", "")
        target_avail = dish.get("available", True)
        target_pic = dish.get("picture", "")
        opt_groups = dish.get("option_groups", [])
        existing_dish = dish

    ok = update_dish(
        client=client,
        store_id=store_id,
        catalog_id=catalog_id,
        dish_id=int(dish_id),
        name=target_name,
        price=new_price,
        description=target_desc,
        available=target_avail,
        picture=target_pic,
        opt_groups=opt_groups,
        existing_dish=existing_dish
    )
    if not ok:
        return False, f"Gagal mengupdate hidangan via API: {client.last_error}"
        
    return True, f"Hidangan '{target_name}' (ID {dish_id}) berhasil diupdate ke Rp {new_price:,.0f}."


def push_price_update_batch(
    store_metadata: dict,
    updates: list[dict],
    headless: bool = True,
    on_item_progress = None,
    item_delay_ms: int = 300,
    batch_size: int = 10,
    batch_pause_sec: float = 1.5
) -> list[dict]:
    """
    Melakukan PUSH perubahan harga batch (banyak item sekaligus)
    menggunakan 1 KALI boot browser session Shopee Partner dengan jeda batching:
    - Jeda per item: item_delay_ms (default: 300 ms)
    - Jeda per batch: batch_pause_sec (default: 1.5 detik per batch_size 10 item)
    """
    client, err = _boot_push_client(store_metadata, headless=headless)
    results = []
    total = len(updates)

    for idx, update in enumerate(updates):
        # ── Rate Limit Safeguard / Batching Delays ──
        if idx > 0:
            if batch_size > 0 and idx % batch_size == 0:
                print(f"[PUSH_BATCH] ⏸️ Jeda batching ({idx}/{total} item terproses). Istirahat {batch_pause_sec} detik untuk mencegah rate limit Shopee...")
                time.sleep(batch_pause_sec)
            elif item_delay_ms > 0:
                time.sleep(item_delay_ms / 1000.0)

        dish_id = str(update["item_id"])
        new_price = float(update["new_price"])
        item_name = update.get("item_name") or dish_id

        if on_item_progress:
            try:
                on_item_progress(idx, total, item_name, new_price)
            except Exception:
                pass

        if not client:
            print(f"[PUSH_BATCH] Retrying _boot_push_client for item {item_name}...")
            client, err = _boot_push_client(store_metadata, headless=headless)

        if not client:
            results.append({
                "item_id": dish_id,
                "item_name": item_name,
                "new_price": new_price,
                "success": False,
                "error_message": f"Boot client failed: {err}"
            })
            continue

        store_id = client.entity_id or store_metadata.get("store_id")
        if not store_id:
            results.append({
                "item_id": dish_id,
                "item_name": item_name,
                "new_price": new_price,
                "success": False,
                "error_message": "Store ID / Entity ID Shopee tidak ditemukan"
            })
            continue

        try:
            dish = client.get_dish_detail(dish_id, store_id)
            if not dish:
                catalog_id = 0
                target_name = item_name
                target_desc = ""
                target_avail = True
                target_pic = ""
                opt_groups = []
                existing_dish = None
            else:
                catalog_id = dish.get("catalog_id", 0)
                target_name = dish.get("name", item_name)
                target_desc = dish.get("description", "")
                target_avail = dish.get("available", True)
                target_pic = dish.get("picture", "")
                opt_groups = dish.get("option_groups", [])
                existing_dish = dish

            ok = update_dish(
                client=client,
                store_id=store_id,
                catalog_id=catalog_id,
                dish_id=int(dish_id),
                name=target_name,
                price=new_price,
                description=target_desc,
                available=target_avail,
                picture=target_pic,
                opt_groups=opt_groups,
                existing_dish=existing_dish
            )

            # If token expired or API failed due to auth, clear client once to force re-boot on next item if needed
            if not ok and client.last_error and ("token" in str(client.last_error).lower() or "auth" in str(client.last_error).lower()):
                client = None

            if ok:
                results.append({
                    "item_id": dish_id,
                    "item_name": target_name,
                    "new_price": new_price,
                    "success": True,
                    "error_message": None
                })
            else:
                results.append({
                    "item_id": dish_id,
                    "item_name": target_name,
                    "new_price": new_price,
                    "success": False,
                    "error_message": f"Gagal mengupdate hidangan via API: {client.last_error if client else 'Session error'}"
                })
        except Exception as ex:
            results.append({
                "item_id": dish_id,
                "item_name": item_name,
                "new_price": new_price,
                "success": False,
                "error_message": str(ex)
            })

    return results
