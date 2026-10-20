# -*- coding: utf-8 -*-
"""
Worker PUSH C5 ke Shopee Food Merchant API.
"""

import os
import sys
import re
import json
import time
import logging
from pathlib import Path

import requests

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

from shopee.core.client import ShopeeModifyClient
from shopee.core.push import _boot_push_client
from shopee.core.item.edit import update_dish, update_category, reorder_categories
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


def download_image_bytes(photo_link: str) -> tuple[bytes, str, str]:
    """Unduh gambar dari URL web atau Google Drive, mengembalikan raw bytes, nama file, dan mime type."""
    target_url = str(photo_link or "").strip()
    if not target_url.startswith(("http://", "https://")):
        raise ValueError(f"URL gambar tidak valid: '{photo_link}'")

    if "drive.google.com" in target_url.casefold():
        m = re.search(r"/d/([a-zA-Z0-9_-]+)|[?&]id=([a-zA-Z0-9_-]+)", target_url)
        if m:
            file_id = m.group(1) or m.group(2)
            target_url = f"https://lh3.googleusercontent.com/d/{file_id}=s0"

    resp = requests.get(target_url, timeout=30)
    if not resp.ok or not resp.content:
        raise ValueError(f"Gagal mengunduh gambar (HTTP {resp.status_code}): '{photo_link}'")

    content = resp.content
    if content.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
        ext = ".jpg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
        ext = ".png"
    elif content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        mime = "image/webp"
        ext = ".webp"
    else:
        ctype = resp.headers.get("content-type", "").lower()
        if "png" in ctype:
            mime = "image/png"
            ext = ".png"
        elif "webp" in ctype:
            mime = "image/webp"
            ext = ".webp"
        else:
            mime = "image/jpeg"
            ext = ".jpg"

    return content, f"dish{ext}", mime


def resolve_shopee_photo(client: ShopeeModifyClient, photo_link: str, photo_cache: dict) -> str | None:
    """Mengubah photo_link menjadi hash gambar Shopee, mengunggah ke MMS jika diperlukan."""
    raw_link = str(photo_link or "").strip()
    if not raw_link:
        return ""

    if raw_link in photo_cache:
        return photo_cache[raw_link]

    if ("susercontent.com/file/" in raw_link) or ("shopee.co.id/file/" in raw_link):
        pic_hash = raw_link.rstrip("/").split("/")[-1].split("?")[0]
        if pic_hash:
            photo_cache[raw_link] = pic_hash
            return pic_hash

    if not raw_link.startswith(("http://", "https://")):
        photo_cache[raw_link] = raw_link
        return raw_link

    img_data, filename, mime_type = download_image_bytes(raw_link)
    uploaded_hash = client.upload_image_bytes(img_data=img_data, filename=filename, content_type=mime_type)
    if not uploaded_hash:
        raise ValueError(f"Upload foto ke Shopee MMS gagal: {client.last_error or 'Gagal tanpa pesan error'}")

    photo_cache[raw_link] = uploaded_hash
    return uploaded_hash


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
    photo_cache = {}

    client, err = _boot_push_client(store_metadata, headless=headless)
    if not client:
        logger.error(f"Boot client Shopee gagal: {err}")
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
        if cid:
            cat_obj_map[cid] = cat
        if cname:
            cat_map[cname] = cid
        for dish in cat.get("dishes", []) or []:
            did = str(dish.get("id") or "")
            if did:
                dish_map[did] = dish

    for idx, upd in enumerate(updates):
        item_id = str(upd.get("item_id") or "").strip()
        item_name = upd.get("item_name") or ""
        new_name = upd.get("item_name_new") or item_name
        raw_price = upd.get("new_fake_price") if upd.get("new_fake_price") is not None else upd.get("current_fake_price")
        new_cat_name = (upd.get("category") or "").strip()
        photo_link = upd.get("photo_link") or ""
        description = upd.get("description") or ""

        changes = upd.get("changes") or upd.get("change_types") or []
        if isinstance(changes, dict):
            changes = [k for k, v in changes.items() if v]

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

        is_new_item = (not item_id) or item_id in ("NEW_ITEM", "TAMBAH_ITEM", "-") or ("NEW_ITEM" in changes)

        if is_new_item:
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
                        cat_obj_map[target_catalog_id] = new_cat
            if not target_catalog_id and catalogs:
                target_catalog_id = str(catalogs[0].get("id") or "0")

            if not target_catalog_id:
                res_item["status"] = "FAILED"
                res_item["error"] = f"Kategori '{new_cat_name}' tidak ditemukan dan gagal dibuat."
                results.append(res_item)
                if item_result_cb:
                    try:
                        item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                    except Exception:
                        pass
                continue

            target_pic = ""
            if photo_link:
                try:
                    target_pic = resolve_shopee_photo(client, photo_link, photo_cache) or ""
                    res_item["new_photo"] = target_pic
                except Exception as ex_photo:
                    logger.warning(f"Gagal memproses foto item baru '{new_name or item_name}': {ex_photo}")
                    res_item["status"] = "FAILED"
                    res_item["error"] = f"Gagal upload foto: {ex_photo}"
                    results.append(res_item)
                    if item_result_cb:
                        try:
                            item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                        except Exception:
                            pass
                    continue

            try:
                final_price = float(raw_price or 0)
                created_dish = create_dish(
                    client=client, store_id=store_id, catalog_id=int(target_catalog_id),
                    name=new_name or item_name, price=final_price,
                    description=description, available=True, picture=target_pic
                )
                if created_dish:
                    new_did = str(created_dish.get("id") or "NEW_ITEM")
                    res_item["item_id"] = new_did
                    res_item["status"] = "SUCCESS"
                    dish_map[new_did] = created_dish
                else:
                    res_item["status"] = "FAILED"
                    res_item["error"] = f"Gagal membuat item di Shopee: {client.last_error}"
            except Exception as ex_create:
                res_item["status"] = "FAILED"
                res_item["error"] = str(ex_create)

            results.append(res_item)
            if item_result_cb:
                try:
                    err_cb = res_item.get("error") if res_item.get("status") == "FAILED" else None
                    item_result_cb(upd, res_item.get("status", "FAILED"), err_cb, applied=res_item)
                except Exception:
                    pass
            continue

        existing_dish = dish_map.get(item_id) or client.get_dish_detail(item_id, store_id)
        if not existing_dish:
            res_item["status"] = "FAILED"
            res_item["error"] = f"Dish ID '{item_id}' tidak ditemukan di Shopee."
            results.append(res_item)
            if item_result_cb:
                try:
                    item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                except Exception:
                    pass
            continue

        catalog_id = int(existing_dish.get("catalog_id") or 0)
        if new_cat_name:
            norm_cname = new_cat_name.lower()
            if norm_cname in cat_map:
                catalog_id = int(cat_map[norm_cname])
            else:
                new_cat = create_category(client, store_id, new_cat_name)
                if new_cat and new_cat.get("id"):
                    catalog_id = int(new_cat["id"])
                    cat_map[norm_cname] = str(catalog_id)
                    cat_obj_map[str(catalog_id)] = new_cat

        target_name = new_name if new_name else existing_dish.get("name", item_name)
        target_desc = description if description else existing_dish.get("description", "")
        target_avail = existing_dish.get("available", True)
        opt_groups = existing_dish.get("option_groups", [])

        target_pic = existing_dish.get("picture", "")
        has_photo_change = ("PHOTO_CHANGE" in changes) or (photo_link and photo_link != target_pic)
        if has_photo_change and photo_link:
            try:
                resolved_pic = resolve_shopee_photo(client, photo_link, photo_cache)
                if resolved_pic:
                    target_pic = resolved_pic
                    res_item["new_photo"] = target_pic
            except Exception as ex_photo:
                logger.warning(f"Gagal memproses foto untuk '{target_name}': {ex_photo}")
                res_item["status"] = "FAILED"
                res_item["error"] = f"Gagal upload foto: {ex_photo}"
                results.append(res_item)
                if item_result_cb:
                    try:
                        item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                    except Exception:
                        pass
                continue

        orig_price = float(existing_dish.get("price", 0)) / 100000.0 if existing_dish.get("price") else 0.0
        list_price = float(existing_dish.get("list_price", 0)) / 100000.0 if existing_dish.get("list_price") else orig_price
        disc_pct = float(existing_dish.get("discount_percentage", 0))
        is_promo = (list_price > orig_price > 0) or (disc_pct > 0) or (existing_dish.get("discount_status") == 1)

        if is_promo and raw_price is not None and float(raw_price) != orig_price:
            logger.info(f"Item '{target_name}' (ID: {item_id}) sedang promo. Mempertahankan harga asli Rp{orig_price:,.0f} dan tetap mengupdate atribut non-harga.")
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
            if item_id in dish_map:
                dish_map[item_id].update({
                    "name": target_name,
                    "description": target_desc,
                    "picture": target_pic,
                    "catalog_id": catalog_id,
                    "price": int(final_price * 100000)
                })
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

    try:
        valid_cat_ids = {str(cid) for cid in cat_obj_map.keys()}
        c5_name_to_cid = {}
        for upd in updates:
            c_name = (upd.get("category") or "").strip().lower()
            c_id = str(upd.get("category_id") or "").strip()
            if c_name and c_id and c_id in valid_cat_ids and c_name not in c5_name_to_cid:
                c5_name_to_cid[c_name] = c_id

        ordered_c5_cat_names = []
        category_weights = {}
        for upd in updates:
            for c_name in (upd.get("c5_categories") or []):
                if c_name and c_name not in ordered_c5_cat_names:
                    ordered_c5_cat_names.append(c_name)
            c_name_upd = (upd.get("category") or "").strip()
            cw = upd.get("category_weight")
            if c_name_upd and cw is not None and c_name_upd.lower() not in category_weights:
                try:
                    category_weights[c_name_upd.lower()] = int(cw)
                except (ValueError, TypeError):
                    pass

        if not ordered_c5_cat_names and category_weights:
            sorted_c = sorted(category_weights.items(), key=lambda x: x[1])
            ordered_c5_cat_names = [x[0] for x in sorted_c]

        if not ordered_c5_cat_names:
            for upd in updates:
                c_name = (upd.get("category") or "").strip()
                if c_name and c_name not in ordered_c5_cat_names:
                    ordered_c5_cat_names.append(c_name)

        if ordered_c5_cat_names or category_weights:
            target_cat_ids = []
            seen_cat_ids = set()
            for c_name in ordered_c5_cat_names:
                c_key = (c_name or "").strip().lower()
                cid = c5_name_to_cid.get(c_key) or cat_map.get(c_key)
                if not cid and c_name in valid_cat_ids:
                    cid = c_name
                if cid and str(cid) not in seen_cat_ids:
                    target_cat_ids.append(str(cid))
                    seen_cat_ids.add(str(cid))

            current_sorted_cats = sorted(catalogs, key=lambda c: int(c.get("rank") or 0))
            current_cat_ids = []
            for c in current_sorted_cats:
                cid = str(c.get("id") or "")
                if cid:
                    current_cat_ids.append(cid)
                    if cid not in seen_cat_ids:
                        target_cat_ids.append(cid)
                        seen_cat_ids.add(cid)

            if target_cat_ids and target_cat_ids != current_cat_ids:
                logger.info(f"Mengatur urutan kategori Shopee: {target_cat_ids}")
                ranks_payload = [
                    {"id": str(cid), "rank": idx + 1}
                    for idx, cid in enumerate(target_cat_ids)
                ]
                ok_reorder = reorder_categories(client, store_id, ranks_payload)
                if ok_reorder:
                    logger.info("Urutan kategori Shopee berhasil diperbarui")
                else:
                    logger.warning(f"Gagal mengatur urutan kategori Shopee: {client.last_error}")
    except Exception as ex_cat_sort:
        logger.warning(f"Pengecualian saat mengatur urutan kategori Shopee: {ex_cat_sort}")

    return results
