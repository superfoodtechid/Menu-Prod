# -*- coding: utf-8 -*-
"""
shopee/core/push_c5.py — Worker PUSH C5 ke Shopee Food Merchant API.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

from shopee.core.client import ShopeeModifyClient
from shopee.core.push import _boot_push_client
from shopee.core.item.edit import update_dish, update_category
from shopee.core.item.create import create_dish, create_category

logger = logging.getLogger("ShopeeC5Push")

def calculate_price_steps(old_price: float, new_price: float, max_jump_ratio: float = 0.50) -> list[float]:
    """Jika kenaikan harga > max_jump_ratio (50%), pecah jadi beberapa tahapan."""
    if old_price <= 0 or new_price <= old_price:
        return [new_price]
    ratio = (new_price - old_price) / old_price
    if ratio <= max_jump_ratio:
        return [new_price]
    
    steps = []
    curr = old_price
    while True:
        curr = round(curr * (1 + max_jump_ratio) / 100) * 100
        if curr >= new_price:
            steps.append(new_price)
            break
        steps.append(curr)
    return steps

def push_c5_shopee_for_merchant(
    store_metadata: dict,
    updates: list,
    progress_cb=None,
    headless: bool = True,
    item_result_cb=None
) -> list[dict]:
    """Eksekusi push item menu C5 untuk outlet Shopee Food."""
    results = []
    total = len(updates)

    client, err = _boot_push_client(store_metadata, headless=headless)
    if not client:
        logger.error(f"❌ Boot client Shopee gagal: {err}")
        for upd in updates:
            results.append({
                "item_id": upd.get("item_id"),
                "item_name": upd.get("item_name"),
                "new_name": upd.get("item_name_new"),
                "new_price": upd.get("new_fake_price"),
                "status": "FAILED",
                "error": f"Boot client failed: {err}"
            })
        return results

    store_id = str(client.entity_id or store_metadata.get("store_id") or "")
    if not store_id:
        for upd in updates:
            results.append({
                "item_id": upd.get("item_id"),
                "item_name": upd.get("item_name"),
                "new_name": upd.get("item_name_new"),
                "new_price": upd.get("new_fake_price"),
                "status": "FAILED",
                "error": "Store ID / Entity ID Shopee tidak ditemukan"
            })
        return results

    catalogs = client.get_store_dishes(store_id) or []
    cat_map, cat_obj_map, dish_map = {}, {}, {}

    for cat in catalogs:
        cid = str(cat.get("id") or "")
        cname = (cat.get("name") or "").strip().lower()
    for idx, upd in enumerate(updates):
        item_id = str(upd.get("item_id") or "").strip()
        item_name = upd.get("item_name") or ""
        new_name = upd.get("item_name_new") or item_name
        raw_price = upd.get("new_fake_price") if upd.get("new_fake_price") is not None else upd.get("current_fake_price")
        new_cat_name = (upd.get("category") or "").strip()
        photo_link = upd.get("photo_link") or ""
        description = upd.get("description") or ""

        if progress_cb:
            try:
                progress_cb(idx, total, upd)
            except Exception:
                pass

        res_item = {
            "item_id": item_id, "item_name": item_name,
            "new_name": new_name, "new_price": raw_price,
            "new_category": new_cat_name, "new_photo": photo_link,
            "new_desc": description, "status": "PENDING", "error": None
        }
        if idx > 0:
            time.sleep(0.3)

        # ── KASUS 1: ITEM BARU ──
        if not item_id or item_id in ("NEW_ITEM", "TAMBAH_ITEM", "-"):
            target_catalog_id = None
            if new_cat_name:
                norm_cname = new_cat_name.lower()
                if norm_cname in cat_map:
                    target_catalog_id = cat_map[norm_cname]
                else:
                    new_cat = create_category(client, store_id, new_cat_name)
                    if new_cat and new_cat.get("id"):
                        target_catalog_id = str(new_cat["id"])
                        cat_map[norm_cname] = target_catalog_id
            if not target_catalog_id and catalogs:
                target_catalog_id = str(catalogs[0].get("id") or "0")

            if not target_catalog_id:
                res_item["status"] = "FAILED"
                res_item["error"] = f"Kategori '{new_cat_name}' tidak ditemukan dan gagal dibuat."
                results.append(res_item)
                continue

            try:
                final_price = float(raw_price or 0)
                created_dish = create_dish(
                    client=client, store_id=store_id, catalog_id=int(target_catalog_id),
                    name=new_name or item_name, price=final_price,
                    description=description, available=True, picture=""
                )
                if created_dish:
                    res_item["item_id"] = str(created_dish.get("id") or "NEW_ITEM")
                    res_item["status"] = "SUCCESS"
                else:
                    res_item["status"] = "FAILED"
                    res_item["error"] = f"Gagal membuat item di Shopee: {client.last_error}"
            except Exception as ex_create:
                res_item["status"] = "FAILED"
                res_item["error"] = str(ex_create)

            results.append(res_item)
        # ── KASUS 2: UPDATE ITEM EKSIS ──
        existing_dish = dish_map.get(item_id) or client.get_dish_detail(item_id, store_id)
        if not existing_dish:
            res_item["status"] = "FAILED"
            res_item["error"] = f"Dish ID '{item_id}' tidak ditemukan di Shopee."
            results.append(res_item)
            continue

        catalog_id = int(existing_dish.get("catalog_id") or 0)
        target_name = new_name if new_name else existing_dish.get("name", item_name)
        target_desc = description if description else existing_dish.get("description", "")
        target_avail = existing_dish.get("available", True)
        target_pic = existing_dish.get("picture", "")
        opt_groups = existing_dish.get("option_groups", [])

        orig_price = float(existing_dish.get("price", 0)) / 100000.0 if existing_dish.get("price") else 0.0
        list_price = float(existing_dish.get("list_price", 0)) / 100000.0 if existing_dish.get("list_price") else orig_price
        disc_pct = float(existing_dish.get("discount_percentage", 0))
        is_promo = (list_price > orig_price > 0) or (disc_pct > 0) or (existing_dish.get("discount_status") == 1)

        # ── Partial C5 Push for Active Promo Items ──
        if is_promo and raw_price is not None and float(raw_price) != orig_price:
            logger.info(f"🔒 [Shopee C5 Push] Item '{target_name}' (ID: {item_id}) sedang promo. Mempertahankan harga asli Rp{orig_price:,.0f} dan tetap mengupdate atribut non-harga.")
            final_price = orig_price
            price_steps = [orig_price]
            promo_note = " (Harga tidak diubah karena promo aktif)"
        else:
            final_price = float(raw_price) if raw_price is not None else orig_price
            price_steps = calculate_price_steps(orig_price, final_price) if orig_price > 0 else [final_price]
            promo_note = ""

        update_success, last_err = True, ""

        for step_price in price_steps:
            ok = update_dish(
                client=client, store_id=store_id, catalog_id=catalog_id,
                dish_id=int(item_id), name=target_name, price=step_price,
                description=target_desc, available=target_avail,
                picture=target_pic, opt_groups=opt_groups, existing_dish=existing_dish
            )
            if not ok:
                update_success = False
                last_err = client.last_error or "Update dish API returned error."
                break
            time.sleep(0.2)

        if update_success:
            res_item["status"] = "SUCCESS"
            if promo_note:
                res_item["note"] = promo_note.strip()
        else:
            res_item["status"] = "FAILED"
            res_item["error"] = last_err

        results.append(res_item)
        if item_result_cb:
            try:
                err_cb = res_item.get("error") if res_item.get("status") == "FAILED" else None
                item_result_cb(upd, res_item.get("status", "FAILED"), err_cb, applied=res_item)
            except Exception:
                pass

    return results
