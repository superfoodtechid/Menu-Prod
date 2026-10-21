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
    name: str = None,
    price: float = None,
    description: str = "",
    available: bool = True,
    catalog_id: int | str = None,
    picture: str = "",
    opt_groups: list = None,
    rank: int = None,
    existing_dish: dict = None,
    list_price: float = None,
    include_price_mutation: bool = True
) -> dict:
    time_for_sales = [{"sale_start_time": 0, "sale_end_time": 86399}]
    
    if existing_dish:
        # Jika tidak ada perubahan harga (hanya ubah nama/kategori/deskripsi/foto),
        # kirim payload bersih persis seperti cURL web portal Shopee Partner (tanpa list_price & promo)
        # agar tidak memicu sistem validasi kuota batas perubahan harga harian.
        if not include_price_mutation:
            dish_payload = {
                "name": name if (name is not None and str(name).strip() != "") else existing_dish.get("name", ""),
                "available": available if available is not None else existing_dish.get("available", True),
                "catalog_id": str(catalog_id or existing_dish.get("catalog_id", "")),
                "description": description if description is not None else existing_dish.get("description", ""),
                "price": str(existing_dish.get("price", "0")),
                "picture": picture if (picture is not None and str(picture).strip() != "") else existing_dish.get("picture", ""),
                "time_for_sales": existing_dish.get("time_for_sales") or time_for_sales,
                "listing_status": existing_dish.get("listing_status", 1),
                "sale_status": existing_dish.get("sale_status", 1),
                "sale_week_bit": existing_dish.get("sale_week_bit", 127),
                "stock_type": existing_dish.get("stock_type", 0),
                "id": str(existing_dish.get("id"))
            }
            if rank is not None:
                dish_payload["rank"] = rank
            elif "rank" in existing_dish:
                dish_payload["rank"] = existing_dish["rank"]
            return dish_payload

        price_cents = int(price * 100000) if price is not None else int(existing_dish.get("price", 0))
        list_price_cents = int(list_price * 100000) if list_price is not None else price_cents

        dish_copy = existing_dish.copy()
        dish_copy["price"] = str(price_cents)
        dish_copy["list_price"] = list_price_cents
        dish_copy["available"] = available
        if rank is not None:
            dish_copy["rank"] = rank
        elif "rank" not in dish_copy:
            dish_copy["rank"] = 1
        if name:
            dish_copy["name"] = name
        if description is not None:
            dish_copy["description"] = description
        if picture is not None and str(picture).strip() != "":
            dish_copy["picture"] = picture
        if catalog_id:
            dish_copy["catalog_id"] = str(catalog_id)
        if "id" in dish_copy:
            dish_copy["id"] = str(dish_copy["id"])
        if "store_id" in dish_copy:
            dish_copy["store_id"] = str(dish_copy["store_id"])
        if "item_discount" in dish_copy and isinstance(dish_copy["item_discount"], dict):
            it_disc = dish_copy["item_discount"].copy()
            if price_cents < list_price_cents:
                it_disc["discount_price"] = str(price_cents)
            dish_copy["item_discount"] = it_disc
        return dish_copy

    price_cents = int(price * 100000) if price is not None else 0
    list_price_cents = int(list_price * 100000) if list_price is not None else price_cents

    if rank is None:
        rank = 1

    payload = {
        "name":           name,
        "price":          str(price_cents),
        "list_price":     list_price_cents,
        "picture":        picture,
        "description":    description,
        "available":      available,
        "listing_status": 1,
        "sale_status":    1,
        "sale_week_bit":  127,
        "time_for_sales": time_for_sales,
        "rank":           rank,
        "catalog_id":     str(catalog_id),
        "option_groups":  opt_groups or []
    }
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
    opt_groups: list = None,
    rank: int = None
) -> dict | None:
    url = f"https://foody.shopee.co.id/api/seller/store/dish/create"
    payload = _build_dish_payload(
        name=name,
        price=price,
        description=description,
        available=available,
        catalog_id=catalog_id,
        picture=picture,
        opt_groups=opt_groups,
        rank=rank
    )
    dish_payload = payload if (isinstance(payload, dict) and "dish" in payload) else {"dish": payload}
    try:
        resp = client.session.post(url, json=dish_payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
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
