import os
import json
import asyncio
import logging
import re
from pathlib import Path
from playwright.async_api import async_playwright
from grab.core.grab_api_scraper import GrabAPI, perform_login, SESSION_DIR

logger = logging.getLogger("GrabC5Push")

async def _async_push_c5_grab(username: str, password: str, store_id: str, updates: list, progress_cb=None):
    """
    Internal async worker to log into Grab Merchant Portal and push C5 menu updates to Grab API.
    """
    if not username or not password:
        raise Exception("Username dan password Grab tidak boleh kosong.")

    session_path = os.path.join(SESSION_DIR, f"{username}.json")
    storage_state = session_path if os.path.exists(session_path) else None

    results = []
    total = len(updates)

    async with async_playwright() as p:
        proc = None
        use_system_chromium = os.path.exists("/usr/lib/chromium/chromium") or os.path.exists("/usr/bin/chromium")
        if use_system_chromium:
            import socket, subprocess
            def get_free_port():
                s = socket.socket()
                s.bind(('', 0))
                port = s.getsockname()[1]
                s.close()
                return port
            cdp_port = get_free_port()
            chromium_bin = "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else "/usr/bin/chromium"
            proc = subprocess.Popen([
                chromium_bin, "--no-sandbox", "--no-zygote", "--in-process-gpu", "--disable-gpu",
                "--disable-dev-shm-usage", "--disable-gpu-sandbox", "--dbus-stub", f"--remote-debugging-port={cdp_port}", "--headless=new"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.sleep(3.0)
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        else:
            browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            try:
                await page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Grab dashboard navigate warning: {e}")

            api = GrabAPI(page, username, password)
            group_id = await api.get_merchant_group_id()

            if not group_id:
                logger.info("Grab session expired/invalid. Running perform_login...")
                if await perform_login(page, username, password):
                    os.makedirs(SESSION_DIR, exist_ok=True)
                    await context.storage_state(path=session_path)
                    group_id = await api.get_merchant_group_id()

            if not group_id:
                raise Exception("Gagal mendapatkan Merchant Group ID dari Grab. Cek username/password.")

            # Resolve target store / merchant IDs
            target_sid = store_id
            if not target_sid:
                merchants = await api.get_all_merchants_and_stores()
                if merchants and len(merchants) > 0:
                    target_sid = merchants[0].get("id") or merchants[0].get("store_id")

            if not target_sid:
                raise Exception("Store ID Grab tidak valid atau tidak ditemukan.")

            logger.info(f"🔑 Grab C5 Push initialized for Store ID: {target_sid}, Group ID: {group_id}")

            # Fetch current menu structure to map categories and existing items
            current_menu, fetch_err = await api.fetch_menu(group_id, target_sid)
            if fetch_err or not current_menu:
                logger.warning(f"Warning: Fetch current menu return error: {fetch_err}. Proceeding with fallback.")
                current_menu = {}

            categories = current_menu.get("categories") or []
            cat_map = {}  # norm_name -> cat_id
            cat_obj_map = {} # cat_id -> cat_obj
            for c in categories:
                cid = c.get("categoryID") or c.get("id")
                cname = c.get("name", "").strip()
                if cname:
                    cat_map[cname.lower()] = cid
                if cid:
                    cat_obj_map[cid] = c

            # Index existing items to check live campaign / promo status
            existing_items_map = {}
            for c in categories:
                for it in (c.get("items") or c.get("menuItems") or []):
                    iid = str(it.get("itemID") or it.get("id") or "")
                    if iid:
                        existing_items_map[iid] = it
                    iname = (it.get("itemName") or it.get("name") or "").strip().lower()
                    if iname:
                        existing_items_map[iname] = it

            # Process each item update
            for idx, upd in enumerate(updates):
                item_id = str(upd.get("item_id") or "").strip()
                item_name = upd.get("item_name") or ""
                new_name = upd.get("item_name_new") or item_name
                new_price = upd.get("new_fake_price")
                new_cat_name = upd.get("category") or ""
                photo_link = upd.get("photo_link") or ""
                description = upd.get("description") or ""

                if progress_cb:
                    progress_cb(idx, total, upd)

                res_item = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "new_name": new_name,
                    "new_price": new_price,
                    "new_category": new_cat_name,
                    "new_photo": photo_link,
                    "new_desc": description,
                    "status": "SUCCESS",
                    "error": None
                }

                try:
                    # 1. Handle NEW CATEGORY if needed
                    if upd.get("is_new_category") and new_cat_name and new_cat_name.lower() not in cat_map:
                        selling_time_id = ""
                        if categories and isinstance(categories[0], dict):
                            selling_time_id = categories[0].get("sellingTimeID") or ""

                        cat_res, cat_err = await api.create_category(group_id, target_sid, new_cat_name, selling_time_id)
                        if cat_err:
                            logger.warning(f"Gagal buat kategori baru '{new_cat_name}': {cat_err}")
                        elif cat_res:
                            new_cid = cat_res.get("categoryID") or cat_res.get("id")
                            if new_cid:
                                cat_map[new_cat_name.lower()] = new_cid

                    target_cat_id = upd.get("category_id") or cat_map.get((new_cat_name or "").lower()) or (categories[0].get("categoryID") if categories else "")

                    # 2. Handle DELETE ITEM
                    if upd.get("is_deleted_item"):
                        if item_id:
                            ok_del, err_del = await api.delete_item(group_id, target_sid, item_id)
                            if not ok_del:
                                res_item["status"] = "FAILED"
                                res_item["error"] = f"Gagal hapus item: {err_del}"
                        else:
                            res_item["status"] = "FAILED"
                            res_item["error"] = "Item ID tidak ada untuk penghapusan."
                        results.append(res_item)
                        continue

                    # 3. Handle Active Promo Check for Grab C5 Push
                    existing_it = existing_items_map.get(item_id) or existing_items_map.get(item_name.strip().lower())
                    target_price_val = int(float(new_price)) if new_price is not None else 0
                    if existing_it:
                        has_campaign = bool(existing_it.get("itemCampaignInfo"))
                        orig_grab_p = int(existing_it.get("priceInMin") or 0)
                        if has_campaign and target_price_val != orig_grab_p and target_price_val > 0:
                            logger.info(f"🔒 [Grab C5 Push] Item '{new_name or item_name}' sedang dalam promo/campaign aktif. Menahan harga asli dan melanjutkan pembaruan non-harga.")
                            target_price_val = orig_grab_p
                            res_item["note"] = "Harga dipertahankan karena campaign aktif"

                    # 4. Handle UPSERT ITEM (Price, Name, Photo, Description)
                    item_payload = {
                        "name": new_name or item_name,
                        "priceInMin": target_price_val,
                        "description": description,
                        "photoURL": photo_link,
                    }
                    if item_id:
                        item_payload["itemID"] = item_id

                    upsert_res, upsert_err = await api.upsert_item(group_id, target_sid, target_cat_id, item_payload)

                    if upsert_err:
                        res_item["status"] = "FAILED"
                        res_item["error"] = upsert_err
                    else:
                        logger.info(f"✅ [Grab C5 Push] Successfully updated item '{new_name or item_name}' (SID: {target_sid})")

                except Exception as ex_item:
                    logger.error(f"❌ Error processing Grab C5 item '{item_name}': {ex_item}")
                    res_item["status"] = "FAILED"
                    res_item["error"] = str(ex_item)

                results.append(res_item)

        finally:
            try:
                await browser.close()
            except Exception:
                pass
            if proc:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass

        return results

def push_c5_grab_for_merchant(username: str, password: str, store_id: str, updates: list, progress_cb=None):
    """
    Synchronous wrapper to run async Grab C5 push in a clean event loop.
    """
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(_async_push_c5_grab(username, password, store_id, updates, progress_cb))
    finally:
        try:
            new_loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)
