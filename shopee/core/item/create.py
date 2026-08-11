# -*- coding: utf-8 -*-
import sys
import json
import time
from pathlib import Path
from ..client import ShopeeModifyClient

MENU_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = MENU_DIR.parent / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

def _build_dish_payload(
    name: str,
    price: float,
    description: str,
    available: bool,
    catalog_id: int,
    picture: str = "",
    opt_groups: list = None,
    rank: int = 1,
    existing_dish: dict = None
) -> dict:
    price_cents = int(price * 100000)
    time_for_sales = [{"sale_start_time": 0, "sale_end_time": 86399}]
    
    if existing_dish:
        time_for_sales = existing_dish.get("time_for_sales", time_for_sales)
        rank = existing_dish.get("rank", rank)

    payload = {
        "name":           name,
        "price":          str(price_cents),
        "list_price":     str(price_cents),
        "picture":        picture,
        "description":    description,
        "available":      available,
        "listing_status": 1,
        "sale_status":    1,
        "time_for_sales": time_for_sales,
        "rank":           rank,
        "catalog_id":     catalog_id,
        "option_groups":  opt_groups or []
    }
    
    if existing_dish and "id" in existing_dish:
        payload["id"] = existing_dish["id"]
        
    return payload

def create_dish(
    client: ShopeeModifyClient,
    store_id: str,
    catalog_id: int,
    name: str,
    price: float,
    description: str = "",
    available: bool = True,
    picture: str = "",
    opt_groups: list = None
) -> dict | None:
    url = f"https://foody.shopee.co.id/api/seller/store/dish/create"
    payload = _build_dish_payload(
        name=name,
        price=price,
        description=description,
        available=available,
        catalog_id=catalog_id,
        picture=picture,
        opt_groups=opt_groups
    )
    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("dish")
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return None

def create_category(client: ShopeeModifyClient, store_id: str, name: str) -> dict | None:
    url = f"https://foody.shopee.co.id/api/seller/store/catalog/create"
    payload = {"name": name, "rank": 1}
    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("catalog")
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return None

def add_menu_shopee(
    store_metadata: dict,
    category_id: str,
    name: str,
    price_rp: float,
    description: str = "",
    available: bool = True,
    show: bool = True,
    image_path: str = "",
    sales_time_type: int = 0,
    headless: bool = True
) -> tuple[bool, str]:
    from .edit import _boot_client, edit_dish_upload_image
    client, err = _boot_client(store_metadata, headless=headless)
    if not client:
        return False, f"Boot client failed: {err}"
        
    store_id = store_metadata["store_id"]
    catalogs = client.get_store_dishes(store_id)
    target_catalog = next((c for c in catalogs if str(c.get("id")) == str(category_id)), None)
    
    if not target_catalog:
        return False, f"Kategori dengan ID '{category_id}' tidak ditemukan."
        
    dish = create_dish(
        client=client,
        store_id=store_id,
        catalog_id=int(category_id),
        name=name,
        price=price_rp,
        description=description,
        available=available
    )
    if not dish:
        return False, f"Gagal membuat hidangan: {client.last_error}"
        
    dish_id = dish["id"]
    if image_path and Path(image_path).exists():
        print(f"  [*] Mengunggah foto hidangan via Selenium...")
        upload_ok = edit_dish_upload_image(store_metadata, str(dish_id), image_path, headless=headless)
        if not upload_ok:
            return True, f"Hidangan '{name}' berhasil dibuat, tetapi gagal mengunggah gambar."
            
    return True, f"Hidangan '{name}' berhasil dibuat dengan ID {dish_id}."
