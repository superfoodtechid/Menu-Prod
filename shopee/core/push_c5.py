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
import tempfile
from pathlib import Path

import requests

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

from shopee.core.client import ShopeeModifyClient
from shopee.core.push import _boot_push_client
from shopee.core.session_utils import resolve_shopee_session
from shopee.core.item.edit import (
    update_dish,
    update_category,
    reorder_categories,
    reorder_dishes,
    edit_dish_upload_image,
    _sync_store_session,
    _resolve_target_merchant_name,
)
from shopee.core.item.create import create_dish, create_category
from menu_core.c5_template_helper import is_c5_reserved_row

logger = logging.getLogger("ShopeeC5Push")


def calculate_price_steps(old_price: float, new_price: float, max_jump_ratio: float = 0.50) -> list[float]:
    """Menghitung tahapan perubahan harga.
    Catatan: Shopee membatasi perubahan harga maksimal 1x per hari sehingga
    step push tidak digunakan agar tidak memicu kuota harian (error 1100036).
    Fungsi ini selalu mengembalikan harga akhir langsung [new_price].
    """
    return [new_price]


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


def is_valid_shopee_image_hash(val: str) -> bool:
    """Memeriksa apakah string adalah hash gambar Shopee yang valid."""
    val = str(val or "").strip()
    if not val:
        return False
    return bool(re.match(r"^[a-z]{2}-[a-zA-Z0-9_-]{10,}$", val) or re.match(r"^[a-fA-F0-9]{32}$", val))


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

    if is_valid_shopee_image_hash(raw_link):
        photo_cache[raw_link] = raw_link
        return raw_link

    if not raw_link.startswith(("http://", "https://")):
        logger.warning(f"Nilai foto '{raw_link}' bukan URL maupun hash Shopee yang valid. Dilewati agar tidak merusak data gambar.")
        raise ValueError(f"Nilai foto '{raw_link}' tidak valid (harus berupa URL atau hash gambar Shopee).")

    img_data, filename, mime_type = download_image_bytes(raw_link)
    uploaded_hash = client.upload_image_bytes(img_data=img_data, filename=filename, content_type=mime_type)
    if not uploaded_hash:
        raise ValueError(f"Upload foto ke Shopee MMS gagal: {client.last_error or 'Gagal tanpa pesan error'}")

    photo_cache[raw_link] = uploaded_hash
    return uploaded_hash


def _process_photo_fallback_queue(
    store_metadata: dict,
    queue: list[dict],
    headless: bool = True,
    item_result_cb=None,
    store_id: str = None,
    client: ShopeeModifyClient = None,
) -> None:
    """Mengunggah foto yang gagal via API langsung menggunakan otomasi browser Selenium."""
    if not queue:
        return

    meta_sid = store_metadata.get("store_id")
    target_store_id = str(store_id or meta_sid or "")
    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"
    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)

    session_file = resolve_shopee_session(store_metadata, base_dir=WORKSPACE_DIR)
    browser.set_session_file(session_file)
    active_account = session_file.stem.replace("session_", "") if session_file.stem.startswith("session_") else username

    driver = None
    try:
        session_data = browser.get_session(
            username=active_account,
            password=password,
            headless=headless,
            close_browser=False,
            target_name=target_name,
            interactive=False,
            target_store_id=target_store_id,
            allow_login=False,
            load_images=True,
        )
        if not session_data or "driver" not in session_data:
            logger.warning("Gagal menginisialisasi browser untuk fallback upload foto.")
            for entry in queue:
                entry["res_item"]["status"] = "FAILED"
                entry["res_item"]["error"] = "Gagal menginisialisasi browser untuk fallback upload foto."
                entry["res_item"]["note"] = (entry["res_item"].get("note", "") + " Gagal init browser fallback foto.").strip()
                upd = entry.get("update_payload")
                if item_result_cb and upd:
                    try:
                        item_result_cb(upd, "FAILED", entry["res_item"]["error"], applied=entry["res_item"])
                    except Exception:
                        pass
            return

        driver = session_data["driver"]
        # get_session() above already selects and validates target_store_id.
        # Calling _sync_store_session() here can navigate through dashboard
        # and business-hours pages before every photo batch, causing visible
        # white flashes and risking loss of the selected merchant context.

        for entry in queue:
            dish_id = entry["dish_id"]
            photo_link = entry["photo_link"]
            res_item = entry["res_item"]
            tname = entry.get("target_name", dish_id)
            upd = entry.get("update_payload")

            temp_path = None
            try:
                img_data, filename, _ = download_image_bytes(photo_link)
                ext = Path(filename).suffix or ".jpg"
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                    tf.write(img_data)
                    temp_path = tf.name

                upload_ok = False
                verified_picture = ""
                previous_picture = str(entry.get("previous_picture") or "").strip()
                for attempt in range(1, 3):
                    upload_ok = edit_dish_upload_image(
                        store_metadata=store_metadata,
                        dish_id=str(dish_id),
                        image_path=temp_path,
                        headless=headless,
                        driver=driver,
                        sync_session=False,
                        store_id=target_store_id
                    )
                    if not upload_ok:
                        logger.warning(
                            "Portal upload attempt %d/2 did not complete for dish %s.",
                            attempt, dish_id
                        )
                        continue

                    if client:
                        # Clicking Save is not proof that Shopee persisted the
                        # picture. Confirm the live dish hash changed before
                        # returning a successful result to the job/audit trail.
                        for verify_attempt in range(4):
                            try:
                                live_dish = client.get_dish_detail(str(dish_id), target_store_id)
                                live_picture = str((live_dish or {}).get("picture") or "").strip()
                                if live_picture and live_picture != previous_picture:
                                    verified_picture = live_picture
                                    break
                            except Exception as verify_error:
                                logger.debug(
                                    "Photo verification attempt %d/4 failed for dish %s: %s",
                                    verify_attempt + 1, dish_id, verify_error
                                )
                            if verify_attempt < 3:
                                time.sleep(1.5)
                        if verified_picture:
                            break
                        logger.warning(
                            "Portal Save was clicked, but Shopee still reports the previous picture for dish %s (attempt %d/2).",
                            dish_id, attempt
                        )
                        upload_ok = False
                    else:
                        # Preserve the legacy helper behavior for standalone
                        # callers that do not provide an API client.
                        verified_picture = "Uploaded via portal"
                        break

                    if attempt < 2:
                        time.sleep(1)
                if upload_ok:
                    res_item["status"] = "SUCCESS"
                    res_item["error"] = None
                    res_item["new_photo"] = verified_picture
                    prev_note = res_item.get("note", "")
                    if "Foto gagal diunggah:" in prev_note or "fallback" in prev_note:
                        res_item["note"] = "Foto berhasil diunggah via portal"
                    else:
                        res_item["note"] = (prev_note + " Foto berhasil diunggah via portal.").strip()
                    logger.info(f"✅ Foto untuk item '{tname}' (ID {dish_id}) berhasil diunggah via portal.")
                    if item_result_cb and upd:
                        try:
                            item_result_cb(upd, "SUCCESS", None, applied=res_item)
                        except Exception:
                            pass
                else:
                    logger.warning(f"❌ Foto untuk item '{tname}' (ID {dish_id}) gagal diunggah via portal.")
                    res_item["status"] = "FAILED"
                    res_item["error"] = res_item.get("error") or "Foto belum terkonfirmasi tersimpan di Shopee setelah fallback portal."
                    res_item["note"] = (res_item.get("note", "") + " Foto gagal diunggah via portal.").strip()
                    if item_result_cb and upd:
                        try:
                            item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                        except Exception:
                            pass
            except Exception as ex:
                logger.warning(f"Error memproses fallback upload foto item '{tname}': {ex}")
                res_item["status"] = "FAILED"
                res_item["error"] = f"Error fallback upload foto: {ex}"
                res_item["note"] = (res_item.get("note", "") + f" Error fallback foto: {ex}").strip()
                if item_result_cb and upd:
                    try:
                        item_result_cb(upd, "FAILED", res_item["error"], applied=res_item)
                    except Exception:
                        pass
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"Kesalahan fatal pada worker fallback foto: {e}")
        for entry in queue:
            upd = entry.get("update_payload")
            entry["res_item"]["status"] = "FAILED"
            entry["res_item"]["error"] = f"Fatal fallback error: {e}"
            if item_result_cb and upd:
                try:
                    item_result_cb(upd, "FAILED", entry["res_item"]["error"], applied=entry["res_item"])
                except Exception:
                    pass
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


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
    photo_fallback_queue = []

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

    meta_sid = store_metadata.get("store_id")
    if meta_sid and str(meta_sid).strip() and str(meta_sid).strip().lower() not in ("-", "nan", "none"):
        store_id = str(meta_sid).strip()
    else:
        store_id = str(client.entity_id or "")

    if client and store_id:
        client.entity_id = store_id

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

        if is_c5_reserved_row([item_name, new_name, new_cat_name, item_id]):
            continue
        photo_link = upd.get("photo_link") or ""
        description = upd.get("description") or ""

        raw_changes = upd.get("changes") if upd.get("changes") is not None else upd.get("change_types")
        if isinstance(raw_changes, dict):
            change_set = {k for k, v in raw_changes.items() if v}
            is_dict_changes = True
            has_change_metadata = True
        elif isinstance(raw_changes, (list, set, tuple)):
            change_set = set(raw_changes)
            is_dict_changes = False
            has_change_metadata = True
        else:
            change_set = set()
            is_dict_changes = False
            has_change_metadata = False

        is_new_item = (not item_id) or item_id in ("NEW_ITEM", "TAMBAH_ITEM", "-") or ("NEW_ITEM" in change_set)
        allow_fallback = is_new_item or not has_change_metadata

        want_name = is_new_item or ("NAME_CHANGE" in change_set) or (is_dict_changes and upd.get("changes", {}).get("name_changed")) or (allow_fallback and bool(new_name))
        want_category = is_new_item or ("CATEGORY_CHANGE" in change_set) or (is_dict_changes and upd.get("changes", {}).get("category_changed")) or (allow_fallback and bool(new_cat_name))
        want_photo = is_new_item or ("PHOTO_CHANGE" in change_set) or (is_dict_changes and upd.get("changes", {}).get("photo_changed")) or (allow_fallback and bool(photo_link))
        want_desc = is_new_item or ("DESCRIPTION_CHANGE" in change_set) or (is_dict_changes and upd.get("changes", {}).get("description_changed")) or (allow_fallback and bool(description))
        want_price = is_new_item or ("PRICE_CHANGE" in change_set) or (is_dict_changes and upd.get("changes", {}).get("price_changed")) or (allow_fallback and raw_price is not None)

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
            new_item_photo_fallback = False
            if photo_link and want_photo:
                try:
                    target_pic = resolve_shopee_photo(client, photo_link, photo_cache) or ""
                    res_item["new_photo"] = target_pic
                except Exception as ex_photo:
                    logger.warning(f"Gagal memproses foto item baru '{new_name or item_name}': {ex_photo}")
                    if photo_link.startswith(("http://", "https://")):
                        res_item["note"] = f"Foto ditandai untuk fallback portal: {ex_photo}"
                        new_item_photo_fallback = True
                    else:
                        res_item["note"] = f"Foto dilewati: {ex_photo}"

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
                    if new_item_photo_fallback and photo_link and new_did != "NEW_ITEM":
                        logger.info(f"📌 [PHOTO FALLBACK] Mendaftarkan item baru '{new_name or item_name}' (ID: {new_did}) ke antrean upload portal.")
                        photo_fallback_queue.append({
                            "dish_id": new_did,
                            "photo_link": photo_link,
                            "res_item": res_item,
                            "target_name": new_name or item_name,
                            "update_payload": upd,
                            "previous_picture": str((created_dish or {}).get("picture") or ""),
                        })
                else:
                    logger.error(f"❌ [PUSH_C5] create_dish gagal untuk '{new_name or item_name}': {client.last_error}")
                    res_item["status"] = "FAILED"
                    res_item["error"] = f"Gagal membuat item di Shopee: {client.last_error}"
            except Exception as ex_create:
                res_item["status"] = "FAILED"
                res_item["error"] = str(ex_create)

            results.append(res_item)
            queued_for_portal = bool(new_item_photo_fallback and photo_link and res_item.get("item_id") not in (None, "", "NEW_ITEM"))
            if not queued_for_portal and item_result_cb:
                try:
                    err_cb = res_item.get("error") if res_item.get("status") == "FAILED" else None
                    item_result_cb(upd, res_item.get("status", "FAILED"), err_cb, applied=res_item)
                except Exception:
                    pass
            continue

        has_item_mutation = (
            want_name
            or want_category
            or want_photo
            or want_desc
            or want_price
        )
        if not has_item_mutation:
            res_item["status"] = "SUCCESS"
            res_item["note"] = "Tidak ada perubahan atribut yang dipilih (dilewati)"
            results.append(res_item)
            if item_result_cb:
                try:
                    item_result_cb(upd, "SUCCESS", None, applied=res_item)
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

        # For a photo-only push, update the image through the merchant portal
        # directly. The seller dish-update API requires a full dish object and
        # can still trigger Shopee's daily price-change guard even when we send
        # the existing price unchanged. Avoid both the MMS/API update path and
        # any price-bearing payload in this case.
        photo_only_push = want_photo and not (want_name or want_category or want_desc or want_price)
        if photo_only_push and photo_link:
            logger.info(
                "📌 [PHOTO ONLY] Mengirim foto '%s' (ID: %s) lewat portal; API update dish dilewati.",
                item_name, item_id,
            )
            photo_fallback_queue.append({
                "dish_id": str(item_id),
                "photo_link": photo_link,
                "res_item": res_item,
                "target_name": item_name or new_name or item_id,
                "update_payload": upd,
                "previous_picture": str(existing_dish.get("picture") or ""),
            })
            res_item["note"] = "Push foto saja melalui portal; payload harga tidak dikirim."
            results.append(res_item)
            continue

        orig_catalog_id = int(existing_dish.get("catalog_id") or 0)
        catalog_id = orig_catalog_id
        if want_category and new_cat_name:
            norm_cname = new_cat_name.lower()
            if norm_cname in cat_map:
                catalog_id = int(cat_map[norm_cname])
            else:
                new_cat = create_category(client, store_id, new_cat_name)
                if new_cat and new_cat.get("id"):
                    catalog_id = int(new_cat["id"])
                    cat_map[norm_cname] = str(catalog_id)
                    cat_obj_map[str(catalog_id)] = new_cat

        target_name = new_name if (want_name and new_name) else existing_dish.get("name", item_name)
        target_desc = description if (want_desc and description) else existing_dish.get("description", "")
        target_avail = existing_dish.get("available", True)
        opt_groups = existing_dish.get("option_groups", [])

        target_pic = existing_dish.get("picture", "")
        photo_fallback_needed = False
        if want_photo and photo_link and photo_link != target_pic:
            try:
                resolved_pic = resolve_shopee_photo(client, photo_link, photo_cache)
                if resolved_pic:
                    target_pic = resolved_pic
                    res_item["new_photo"] = target_pic
            except Exception as ex_photo:
                logger.warning(f"Gagal memproses foto untuk '{target_name}': {ex_photo}")
                if photo_link.startswith(("http://", "https://")):
                    res_item["note"] = f"Foto ditandai untuk fallback portal: {ex_photo}"
                    photo_fallback_needed = True
                else:
                    res_item["note"] = f"Foto dilewati: {ex_photo}"

        orig_price = float(existing_dish.get("price", 0)) / 100000.0 if existing_dish.get("price") else 0.0
        list_price = float(existing_dish.get("list_price", 0)) / 100000.0 if existing_dish.get("list_price") else orig_price
        disc_pct = float(existing_dish.get("discount_percentage", 0))
        is_promo = (list_price > orig_price > 0) or (disc_pct > 0) or (existing_dish.get("discount_status") == 1)

        target_dish_id = int(item_id) if str(item_id).isdigit() else item_id

        if want_price and raw_price is not None:
            target_list_price = float(raw_price)
            new_real_price = upd.get("new_real_price")

            if is_promo:
                if new_real_price is not None and float(new_real_price) > 0:
                    target_selling_price = float(new_real_price)
                elif list_price > orig_price > 0:
                    disc_ratio = (list_price - orig_price) / list_price
                    target_selling_price = round(target_list_price * (1.0 - disc_ratio))
                elif disc_pct > 0:
                    disc_ratio = (disc_pct / 10000.0) if disc_pct > 100 else (disc_pct / 100.0)
                    target_selling_price = round(target_list_price * (1.0 - disc_ratio))
                else:
                    target_selling_price = target_list_price

                if target_selling_price > target_list_price:
                    target_selling_price = target_list_price

                logger.info(
                    f"Item '{target_name}' (ID: {item_id}) sedang promo. "
                    f"Mengubah harga sebelum coret (list_price) dari Rp{list_price:,.0f} ke Rp{target_list_price:,.0f} "
                    f"(harga promo disesuaikan ke Rp{target_selling_price:,.0f})."
                )
                final_price = target_selling_price
                final_list_price = target_list_price
                promo_note = f" (Promo aktif: list_price Rp{target_list_price:,.0f}, promo Rp{target_selling_price:,.0f})"
            else:
                final_price = float(raw_price)
                final_list_price = final_price
                promo_note = ""

            # Kirim perubahan harga langsung dalam 1 kali request tanpa step push
            # agar tidak menghabiskan kuota harian Shopee (maksimal 1x per hari).
            ok = update_dish(
                client=client, store_id=store_id, catalog_id=catalog_id,
                dish_id=target_dish_id, name=target_name, price=final_price,
                description=target_desc, available=target_avail,
                picture=target_pic, opt_groups=opt_groups, existing_dish=existing_dish,
                list_price=final_list_price, include_price_mutation=True
            )
            if ok:
                update_success, last_err = True, ""
            else:
                update_success = False
                raw_err = client.last_error or "Update dish API returned error."
                if "1100036" in raw_err or "limit times" in raw_err.lower() or "exceed the limit times" in raw_err.lower():
                    last_err = "Batas perubahan harga Shopee tercapai (maksimal 1x per hari). Mohon jangan lakukan push harga lagi untuk item ini hari ini."
                else:
                    last_err = raw_err
                logger.error(f"❌ [PUSH_C5] update_dish via API gagal untuk '{target_name}' (ID: {item_id}): {last_err}")
        else:
            # Metadata-only update (nama, kategori, deskripsi, foto tanpa ubah harga).
            # Kirim payload bersih persis seperti web portal agar tidak memicu batas kuota perubahan harga harian.
            final_price = orig_price
            final_list_price = list_price
            promo_note = ""
            ok = update_dish(
                client=client, store_id=store_id, catalog_id=catalog_id,
                dish_id=target_dish_id, name=target_name, price=final_price,
                description=target_desc, available=target_avail,
                picture=target_pic, opt_groups=opt_groups, existing_dish=existing_dish,
                list_price=final_list_price, include_price_mutation=False
            )
            if ok:
                update_success, last_err = True, ""
            else:
                update_success = False
                raw_err = client.last_error or "Update dish API returned error."
                if "1100036" in raw_err or "limit times" in raw_err.lower() or "exceed the limit times" in raw_err.lower():
                    last_err = "Batas perubahan harga Shopee tercapai (maksimal 1x per hari). Mohon jangan lakukan push harga lagi untuk item ini hari ini."
                else:
                    last_err = raw_err
                logger.error(f"❌ [PUSH_C5] update_dish metadata via API gagal untuk '{target_name}' (ID: {item_id}): {last_err}")

        if update_success:
            res_item["status"] = "SUCCESS"
            res_item["new_price"] = final_list_price
            if promo_note:
                res_item["note"] = promo_note.strip()
            if item_id in dish_map:
                dish_map[item_id].update({
                    "name": target_name,
                    "description": target_desc,
                    "picture": target_pic,
                    "catalog_id": catalog_id,
                    "price": str(int(final_price * 100000)),
                    "list_price": int(final_list_price * 100000)
                })
        else:
            res_item["status"] = "FAILED"
            res_item["error"] = last_err

        queued_for_portal = bool(photo_fallback_needed and photo_link)
        if queued_for_portal:
            logger.info(f"📌 [PHOTO FALLBACK] Mendaftarkan item '{target_name}' (ID: {item_id}) ke antrean upload portal.")
            photo_fallback_queue.append({
                "dish_id": str(item_id),
                "photo_link": photo_link,
                "res_item": res_item,
                "target_name": target_name,
                "update_payload": upd,
                "previous_picture": str(existing_dish.get("picture") or ""),
            })

        results.append(res_item)
        if not queued_for_portal and item_result_cb:
            try:
                err_cb = res_item.get("error") if res_item.get("status") == "FAILED" else None
                item_result_cb(upd, res_item.get("status", "FAILED"), err_cb, applied=res_item)
            except Exception:
                pass

    if photo_fallback_queue:
        logger.info(f"📸 [PHOTO FALLBACK] Memproses upload foto untuk {len(photo_fallback_queue)} item via portal Selenium...")
        _process_photo_fallback_queue(
            store_metadata,
            photo_fallback_queue,
            headless=headless,
            item_result_cb=item_result_cb,
            store_id=store_id,
            client=client,
        )

    has_any_cat_changes = any(
        ("CATEGORY_CHANGE" in (u.get("changes") or u.get("change_types") or []))
        or ("CATEGORY_ORDER_CHANGE" in (u.get("changes") or u.get("change_types") or []))
        or ("NEW_CATEGORY" in (u.get("changes") or u.get("change_types") or []))
        or (not (u.get("changes") or u.get("change_types")))
        for u in updates
    )
    has_any_item_order_changes = any(
        ("ITEM_ORDER_CHANGE" in (u.get("changes") or u.get("change_types") or []))
        or ("NEW_ITEM" in (u.get("changes") or u.get("change_types") or []))
        or ("CATEGORY_CHANGE" in (u.get("changes") or u.get("change_types") or []))
        or (not (u.get("changes") or u.get("change_types")))
        for u in updates
    )
    if not has_any_cat_changes and not has_any_item_order_changes:
        return results

    valid_cat_ids = {str(cid) for cid in cat_obj_map.keys()}
    c5_name_to_cid = {}
    for upd in updates:
        c_name = (upd.get("category") or "").strip().lower()
        c_id = str(upd.get("category_id") or "").strip()
        if c_name and c_id and c_id in valid_cat_ids and c_name not in c5_name_to_cid:
            c5_name_to_cid[c_name] = c_id

    if has_any_cat_changes:
        try:
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

    # ── Mengatur urutan item di setiap kategori berdasarkan susunan C5 ──
    if has_any_item_order_changes:
        try:
            cat_updates_map = {}
            for upd in updates:
                c_name = (upd.get("category") or "").strip()
                cid = None
                if c_name:
                    c_key = c_name.lower()
                    cid = c5_name_to_cid.get(c_key) or cat_map.get(c_key)
                if not cid:
                    item_id = str(upd.get("item_id") or "")
                    if item_id in dish_map:
                        cid = str(dish_map[item_id].get("catalog_id") or "")
                if cid:
                    cid_str = str(cid)
                    if cid_str not in cat_updates_map:
                        cat_updates_map[cid_str] = []
                    item_id = str(upd.get("item_id") or "")
                    if item_id and item_id not in cat_updates_map[cid_str]:
                        cat_updates_map[cid_str].append(item_id)

            for cat in catalogs:
                cid_str = str(cat.get("id") or "")
                existing_dishes = cat.get("dishes") or []
                if not existing_dishes:
                    continue

                current_dishes = sorted(existing_dishes, key=lambda d: int(d.get("rank") or 0))
                current_dish_ids = [str(d.get("id")) for d in current_dishes if d.get("id")]

                c5_item_ids = cat_updates_map.get(cid_str, [])
                if not c5_item_ids:
                    continue

                target_dish_ids = []
                seen_dish_ids = set()
                for did in c5_item_ids:
                    if did in current_dish_ids and did not in seen_dish_ids:
                        target_dish_ids.append(did)
                        seen_dish_ids.add(did)

                for did in current_dish_ids:
                    if did not in seen_dish_ids:
                        target_dish_ids.append(did)
                        seen_dish_ids.add(did)

                if target_dish_ids and len(target_dish_ids) > 1 and target_dish_ids != current_dish_ids:
                    logger.info(f"Mengatur urutan item kategori {cid_str} di Shopee: {target_dish_ids}")
                    dish_ranks = [
                        {"id": str(did), "rank": idx + 1}
                        for idx, did in enumerate(target_dish_ids)
                    ]
                    ok_dish_reorder = reorder_dishes(client, store_id, dish_ranks)
                    if ok_dish_reorder:
                        logger.info(f"Urutan item kategori {cid_str} Shopee berhasil diperbarui")
                    else:
                        logger.warning(f"Gagal mengatur urutan item kategori {cid_str}: {client.last_error}")
        except Exception as ex_dish_sort:
            logger.warning(f"Pengecualian saat mengatur urutan item Shopee: {ex_dish_sort}")

    return results
