import os
import json
import asyncio
import logging
import re
import base64
import requests
from pathlib import Path
from playwright.async_api import async_playwright
from grab.core.grab_api_scraper import GrabAPI, perform_login, SESSION_DIR
from menu_core.c5_template_helper import is_c5_reserved_row

logger = logging.getLogger("GrabC5Push")


def download_and_encode_image(photo_link: str) -> tuple[str, str]:
    """Download image from HTTP URL or Google Drive link, returning base64 data and image type."""
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
        img_type = "jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        img_type = "png"
    elif content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        img_type = "webp"
    else:
        ctype = resp.headers.get("content-type", "").lower()
        if "png" in ctype:
            img_type = "png"
        elif "webp" in ctype:
            img_type = "webp"
        else:
            img_type = "jpeg"

    b64_data = base64.b64encode(content).decode("utf-8")
    return b64_data, img_type


def calculate_price_steps(current_price: float, target_price: float, max_step_pct: float = 0.15) -> list[int]:
    """Calculates intermediate prices to reach target_price without any single step exceeding max_step_pct change."""
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
    else:
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

async def _async_push_c5_grab(username: str, password: str, store_id: str, updates: list, progress_cb=None, item_result_cb=None, price_guard_cb=None, store_name=None, step_cb=None):
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
        # Determine headless mode: on Linux servers or in Docker without $DISPLAY, headless MUST be True.
        # Can be overridden via HEADLESS_GRAB environment variable (defaults to True).
        headless_mode = os.environ.get("HEADLESS_GRAB", "true").lower() in ("true", "1", "yes")
        if not os.environ.get("DISPLAY"):
            headless_mode = True

        use_system_chromium = os.path.exists("/usr/lib/chromium/chromium") or os.path.exists("/usr/bin/chromium")
        if use_system_chromium:
            chromium_bin = "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else "/usr/bin/chromium"
            browser = await p.chromium.launch(
                executable_path=chromium_bin,
                headless=headless_mode,
                args=["--no-sandbox", "--no-zygote", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--disable-gpu"],
            )
        else:
            browser = await p.chromium.launch(
                headless=headless_mode,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--disable-gpu"]
            )

        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); window.chrome = { runtime: {} };")
        page = await context.new_page()

        try:
            try:
                await page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Grab dashboard navigate warning: {e}")

            api = GrabAPI(page, username, password)

            # Check if navigation was redirected to login / SSO screen
            cur_url = str(getattr(page, "url", "") or "").lower()
            is_on_login = any(dom in cur_url for dom in ("login.grab.com", "weblogin.grab.com", "saved-accounts"))

            group_id = None
            if not is_on_login:
                try:
                    group_id = await api.get_merchant_group_id()
                except Exception as e_grp:
                    logger.info("Initial merchant group check skipped (%s); checking login.", e_grp)
                    group_id = None

            async def wait_for_merchant_group_id(timeout_seconds=45):
                """Wait for the SSO handoff to expose the merchant selector."""
                deadline = asyncio.get_running_loop().time() + timeout_seconds
                while True:
                    resolved_group_id = None
                    try:
                        resolved_group_id = await api.get_merchant_group_id()
                    except Exception:
                        pass
                    if resolved_group_id:
                        return resolved_group_id
                    if asyncio.get_running_loop().time() >= deadline:
                        return None
                    await asyncio.sleep(2)

            if not group_id:
                logger.info("Grab session expired/invalid or on login page. Running perform_login...")
                login_ok = False
                try:
                    login_ok = await perform_login(page, username, password)
                except Exception as login_error:
                    logger.warning("Grab login with configured password failed: %s", login_error)

                if not login_ok and password != "Master@123":
                    logger.info("Configured Grab login did not complete; trying the existing Master@123 fallback.")
                    api = GrabAPI(page, username, "Master@123")
                    try:
                        login_ok = await perform_login(page, username, "Master@123")
                    except Exception as login_error:
                        logger.warning("Grab fallback login failed: %s", login_error)

                if login_ok:
                    logger.info("Grab login continued; waiting for merchant selector to finish SSO...")
                    group_id = await wait_for_merchant_group_id()
                    if group_id:
                        os.makedirs(SESSION_DIR, exist_ok=True)
                        await context.storage_state(path=session_path)

            if not group_id:
                raise Exception(
                    "Login Grab belum selesai: Merchant Group ID tidak tersedia setelah menunggu SSO. "
                    "Selesaikan verifikasi yang muncul di browser dan pastikan akun memiliki akses ke outlet."
                )

            # Resolve target store / merchant IDs
            target_sid = store_id
            if not target_sid:
                try:
                    merchants = await api.get_all_merchants_and_stores()
                except Exception:
                    merchants = []
                if merchants and len(merchants) > 0:
                    target_sid = merchants[0].get("id") or merchants[0].get("store_id")

            if not target_sid:
                raise Exception("Store ID Grab tidak valid atau tidak ditemukan.")

            async def resolve_target_group_id(fallback_group_id):
                # Pull resolves the group from the selected outlet page's real
                # API request. Reuse that mapping for C5 writes instead of
                # assuming merchant-selector's first group belongs to SID.
                intercepted = await api.get_merchant_ids_from_page_requests(target_store_id=target_sid)
                
                # Check if navigating to SID redirected to login/SSO screen
                cur_url = str(getattr(page, "url", "") or "").lower()
                if any(dom in cur_url for dom in ("login.grab.com", "weblogin.grab.com", "saved-accounts")):
                    logger.warning("Grab redirected to login during SID inspection; performing re-login...")
                    ok_rel = await perform_login(page, username, password)
                    if not ok_rel and password != "Master@123":
                        ok_rel = await perform_login(page, username, "Master@123")
                    if ok_rel:
                        await wait_for_merchant_group_id()
                        await context.storage_state(path=session_path)
                        intercepted = await api.get_merchant_ids_from_page_requests(target_store_id=target_sid)

                sid_key = str(target_sid).strip().casefold()
                for entry in intercepted:
                    if str(entry.get("store_id") or "").strip().casefold() == sid_key:
                        resolved = entry.get("group_id")
                        if resolved:
                            logger.info("Resolved Grab group from outlet page request for SID %s.", target_sid)
                            return resolved

                try:
                    selector_stores = await api.get_all_merchants_and_stores()
                except Exception as e_sel:
                    logger.warning("Failed to get all merchants and stores: %s", e_sel)
                    selector_stores = []
                exact_matches = [
                    entry for entry in selector_stores
                    if str(entry.get("store_id") or "").strip().casefold() == sid_key
                ]
                matching_group_ids = {
                    str(entry.get("group_id") or "").strip()
                    for entry in exact_matches
                    if entry.get("group_id")
                }
                if len(matching_group_ids) == 1:
                    resolved = matching_group_ids.pop()
                    logger.info("Resolved Grab group from merchant selector for SID %s.", target_sid)
                    return resolved

                # A lone account group is a safe fallback when Grab's page
                # does not emit the menu request during navigation.
                all_group_ids = {
                    str(entry.get("group_id") or "").strip()
                    for entry in selector_stores
                    if entry.get("group_id")
                }
                if not selector_stores or all_group_ids == {str(fallback_group_id)}:
                    logger.warning(
                        "Grab outlet request did not expose SID %s; using the only available account group.",
                        target_sid,
                    )
                    return fallback_group_id
                return None

            resolved_group_id = await resolve_target_group_id(group_id)
            if not resolved_group_id:
                raise Exception(
                    f"Tidak dapat mencocokkan SID Grab {target_sid} dengan Merchant Group yang benar. "
                    "Push dihentikan sebelum ada perubahan dikirim."
                )
            group_id = resolved_group_id

            logger.info(f"🔑 Grab C5 Push initialized for Store ID: {target_sid}, Group ID: {group_id}")
            await api.get_csrf_token()

            # A stale session can still return a merchant selector but be
            # rejected by mutation endpoints. Refresh once, and retry only
            # explicit authentication failures so ordinary errors never cause
            # duplicate menu mutations.
            auth_recovery_attempted = False

            def is_auth_error(error):
                text = str(error or "").casefold()
                return (
                    bool(re.search(r"\b(?:401|403)\b", text))
                    or "unauthorized" in text
                    or "token invalid" in text
                    or "session expired" in text
                    or "session invalid" in text
                )

            async def call_with_auth_recovery(action, action_name):
                nonlocal auth_recovery_attempted, group_id
                response = await action()
                error = response[1] if isinstance(response, tuple) and len(response) > 1 else None
                if not error or not is_auth_error(error) or auth_recovery_attempted:
                    return response

                auth_recovery_attempted = True
                logger.warning("🔄 Grab rejected the %s request due to authentication; refreshing the session once.", action_name)
                try:
                    # A portal selector response alone is not proof that the
                    # refreshed session can access this store. Start from the
                    # login flow, then verify the exact target menu before
                    # allowing the failed mutation to be retried.
                    login_ok = await perform_login(page, username, password)
                    if not login_ok:
                        return (response[0], "Sesi Grab kedaluwarsa dan login ulang otomatis gagal. Login kembali ke portal Grab, lalu ulangi push.")
                    refreshed_group_id = await wait_for_merchant_group_id()
                    if not refreshed_group_id:
                        return (response[0], "Login Grab berhasil tetapi sesi merchant belum pulih. Login kembali ke portal Grab, lalu ulangi push.")
                    refreshed_group_id = await resolve_target_group_id(refreshed_group_id)
                    if not refreshed_group_id:
                        return (
                            response[0],
                            f"Login berhasil, tetapi konteks merchant untuk SID {target_sid} tidak ditemukan. "
                            "Push dihentikan demi keamanan outlet.",
                        )
                    try:
                        await page.goto(
                            f"https://merchant.grab.com/food/menu/{target_sid}",
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        await page.wait_for_timeout(1500)
                    except Exception as nav_error:
                        logger.warning("Grab menu context navigation after login failed: %s", nav_error)

                    verified_menu, verify_error = await api.fetch_menu(
                        refreshed_group_id,
                        target_sid,
                        store_name=store_name,
                        require_menu_group_match=True,
                    )
                    if verify_error or not verified_menu:
                        logger.warning(
                            "Grab login completed but target menu verification failed after %s: %s",
                            action_name,
                            verify_error or "empty menu response",
                        )
                        return (
                            response[0],
                            "Login Grab terdeteksi, tetapi akses ke menu outlet belum terverifikasi. "
                            "Pastikan akun memiliki akses ke outlet yang dipilih dan login ulang di portal Grab.",
                        )

                    group_id = refreshed_group_id
                    os.makedirs(SESSION_DIR, exist_ok=True)
                    await context.storage_state(path=session_path)
                    api.csrf_token = None
                    await api.get_csrf_token()
                    logger.info("✅ Grab session refreshed; retrying %s once.", action_name)
                    return await action()
                except Exception as refresh_error:
                    logger.warning("Grab session refresh failed: %s", refresh_error)
                    return (response[0], "Sesi Grab kedaluwarsa dan tidak berhasil diperbarui otomatis. Login kembali ke portal Grab, lalu ulangi push.")

            # Validate that the session can read the target menu before any
            # mutation. If auth expired, refresh once and retry this read; if
            # the menu still cannot be verified, fail the job closed.
            current_menu, fetch_err = await call_with_auth_recovery(
                lambda: api.fetch_menu(
                    group_id,
                    target_sid,
                    store_name=store_name,
                    require_menu_group_match=True,
                ),
                "validate menu session",
            )
            if fetch_err or not current_menu:
                detail = fetch_err or "respons menu Grab kosong"
                raise Exception(
                    "Sesi atau menu Grab belum dapat diverifikasi. Tidak ada perubahan yang dikirim. "
                    f"Detail: {detail}"
                )

            # Match the successful single-price edit flow: determine the
            # Menu Group context from the fetched catalog and pass it
            # explicitly to every item upsert. Do not rely on an incidental
            # menuGroupID field surviving C5 payload shaping.
            is_menu_group = bool(current_menu.get("is_menu_group"))
            menu_group_id = current_menu.get("menuGroupID")
            if not is_menu_group:
                for category in current_menu.get("categories") or []:
                    if category.get("menuGroupID"):
                        is_menu_group = True
                        menu_group_id = category.get("menuGroupID")
                        break
                    for menu_item in category.get("items") or category.get("menuItems") or []:
                        if menu_item.get("menuGroupID"):
                            is_menu_group = True
                            menu_group_id = menu_item.get("menuGroupID")
                            break
                    if is_menu_group:
                        break
            logger.info(
                "Grab C5 mutation context: SID=%s, menu_group=%s, menu_group_id=%s",
                target_sid,
                is_menu_group,
                menu_group_id or "(store-level)",
            )

            categories = current_menu.get("categories") or []
            cat_map = {}  # norm_name -> cat_id
            cat_obj_map = {} # cat_id -> cat_obj
            category_creation_errors = {}
            category_rename_errors = {}
            renamed_category_ids = set()
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
                category_id = c.get("categoryID") or c.get("id")
                for it in (c.get("items") or c.get("menuItems") or []):
                    it.setdefault("_c5CategoryID", category_id)
                    iid = str(it.get("itemID") or it.get("id") or "")
                    if iid:
                        existing_items_map[iid] = it
                    iname = (it.get("itemName") or it.get("name") or "").strip().lower()
                    if iname:
                        existing_items_map[iname] = it

            # Pre-fetch active campaign promos mapping to detect items in promotion
            active_camp_promos = {}
            try:
                active_camp_promos = await api.fetch_grab_campaign_promotions(target_store_id=target_sid)
                if active_camp_promos:
                    logger.info(f"🔍 [Grab C5 Push] Memuat {len(active_camp_promos)} promo aktif di outlet {target_sid}")
            except Exception as e_promos:
                logger.warning(f"⚠️ [Grab C5 Push] Gagal memeriksa promo aktif sebelum push: {e_promos}")

            uploaded_photo_cache = {}

            # Process each item update
            for idx, upd in enumerate(updates):
                if is_c5_reserved_row([upd.get("item_name"), upd.get("item_name_new"), upd.get("category"), upd.get("item_id")]):
                    continue
                item_id = str(upd.get("item_id") or "").strip()
                item_name = upd.get("item_name") or ""
                new_name = upd.get("item_name_new") or item_name
                new_price = upd.get("new_fake_price")
                new_cat_name = upd.get("category") or ""
                photo_link = upd.get("photo_link") or ""
                description = upd.get("description") or ""
                changes = set(upd.get("changes") or [])
                is_new_item = "NEW_ITEM" in changes or not item_id
                is_new_category = "NEW_CATEGORY" in changes or bool(upd.get("is_new_category"))
                is_deleted_item = "DELETE_ITEM" in changes or bool(upd.get("is_deleted_item"))
                has_price_change = "PRICE_CHANGE" in changes or (not changes and new_price is not None)

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
                    # 1. Handle DELETE ITEM from the same change_types list sent by the UI.
                    if is_deleted_item:
                        if item_id:
                            # 1a. Handle Active Promo Check & Detachment before Delete
                            existing_it = existing_items_map.get(item_id) or existing_items_map.get(item_name.strip().lower())
                            has_campaign = bool((existing_it or {}).get("itemCampaignInfo"))
                            c_info = None
                            if active_camp_promos:
                                it_check_id = str((existing_it or {}).get("itemID") or item_id).strip()
                                it_check_name = item_name.strip().lower()
                                c_info = active_camp_promos.get(it_check_id) or active_camp_promos.get(it_check_name)
                                if c_info:
                                    has_campaign = True

                            if has_campaign:
                                logger.info(f"🔍 [Grab C5 Push] Item '{item_name}' (ID: {item_id}) yang akan dihapus terdeteksi dalam promo aktif. Mencopot promo sebelum menghapus...")
                                try:
                                    camp_id_direct = (c_info or {}).get("campaign_id")
                                    if camp_id_direct:
                                        del_res, del_err = await api.delete_campaign(camp_id_direct)
                                        if not del_err:
                                            logger.info(f"🔓 [Grab C5 Push] Berhasil mencopot promo '{camp_id_direct}' untuk item '{item_name}'")
                                            res_item["note"] = f"Promo aktif dicopot ({camp_id_direct})"
                                            await asyncio.sleep(2.0)
                                        else:
                                            logger.warning(f"⚠️ [Grab C5 Push] Gagal mencopot promo langsung: {del_err}. Mencoba cancel_promos_for_item...")
                                            c_camps, _ = await api.cancel_promos_for_item(store_id=target_sid, item_id=item_id, item_name=item_name)
                                            if c_camps:
                                                res_item["note"] = f"Promo aktif dicopot ({', '.join(c_camps)})"
                                                await asyncio.sleep(2.0)
                                    else:
                                        c_camps, _ = await api.cancel_promos_for_item(store_id=target_sid, item_id=item_id, item_name=item_name)
                                        if c_camps:
                                            res_item["note"] = f"Promo aktif dicopot ({', '.join(c_camps)})"
                                            await asyncio.sleep(2.0)
                                except Exception as e_del_promo:
                                    logger.warning(f"⚠️ [Grab C5 Push] Error saat mencopot promo sebelum hapus item: {e_del_promo}")

                            ok_del, err_del = await call_with_auth_recovery(
                                lambda: api.delete_item(group_id, target_sid, item_id),
                                "delete item",
                            )
                            if not ok_del and "promo" in str(err_del).lower():
                                # Fallback retry jika masih gagal karena promo
                                try:
                                    logger.info(f"🔄 [Grab C5 Push] Mencoba kembali mencopot promo untuk item '{item_name}'...")
                                    c_camps, _ = await api.cancel_promos_for_item(store_id=target_sid, item_id=str(item_id), item_name=item_name)
                                    if c_camps:
                                        await asyncio.sleep(2.0)
                                        ok_del, err_del = await call_with_auth_recovery(
                                            lambda: api.delete_item(group_id, target_sid, item_id),
                                            "delete item retry",
                                        )
                                except Exception as e_retry:
                                    logger.warning(f"⚠️ [Grab C5 Push] Retry promo cancellation failed: {e_retry}")

                            if not ok_del:
                                res_item["status"] = "FAILED"
                                res_item["error"] = f"Gagal hapus item: {err_del}"
                            else:
                                logger.info(f"🗑️ [Grab C5 Push] Berhasil menghapus item '{item_name}' (ID: {item_id})")
                        else:
                            res_item["status"] = "FAILED"
                            res_item["error"] = "Item ID tidak ada untuk penghapusan."
                        results.append(res_item)
                        if item_result_cb:
                            item_result_cb(upd, res_item["status"], res_item.get("error"), applied=res_item)
                        continue

                    # Validate character length limits (Name <= 60, Category <= 80, Description <= 250)
                    target_name_check = (new_name or item_name or "").strip()
                    if len(target_name_check) > 60:
                        raise ValueError(f"Nama item melebihi batas 60 karakter ({len(target_name_check)} karakter): '{target_name_check[:30]}...'")
                    target_cat_check = (new_cat_name or "").strip()
                    if len(target_cat_check) > 80:
                        raise ValueError(f"Nama kategori melebihi batas 80 karakter ({len(target_cat_check)} karakter): '{target_cat_check[:30]}...'")
                    target_desc_check = (description or "").strip()
                    if len(target_desc_check) > 250:
                        raise ValueError(f"Deskripsi item melebihi batas 250 karakter ({len(target_desc_check)} karakter).")

                    # Validate existing item and price before any category API
                    # mutation so a blocked price cannot leave partial changes.
                    # 3. Validate price mutations before sending them to Grab.
                    if is_new_item:
                        existing_it = existing_items_map.get(item_id) if item_id else None
                    else:
                        existing_it = existing_items_map.get(item_id) or existing_items_map.get(item_name.strip().lower())
                    if not is_new_item and not existing_it:
                        raise ValueError(f"Item '{item_name}' tidak ditemukan pada menu Grab yang baru ditarik. Pull ulang sebelum push.")
                    if existing_it and not is_new_item:
                        res_item["item_id"] = str(existing_it.get("itemID") or existing_it.get("id") or item_id)
                    if is_new_item and (new_price is None or float(new_price) <= 0):
                        raise ValueError("Harga item baru harus lebih dari Rp0.")
                    old_price_minor = int(float((existing_it or {}).get("priceInMin") or 0))
                    old_price = old_price_minor / 100.0
                    price_steps = [float(new_price)] if new_price is not None else []
                    if has_price_change and not is_new_item:
                        if new_price is None or old_price <= 0:
                            raise ValueError("Harga saat ini atau harga baru tidak tersedia; perubahan harga dihentikan agar batas Grab tidak terlewati.")
                        increase_pct = ((float(new_price) - old_price) / old_price) * 100.0
                        if increase_pct > 15.0 or increase_pct < -15.0:
                            price_steps = calculate_price_steps(old_price, float(new_price), max_step_pct=0.15)
                            if len(price_steps) > 10:
                                raise ValueError(f"Perubahan harga {increase_pct:+.1f}% memerlukan {len(price_steps)} tahapan bertahap, melebihi kuota maksimal Grab 10 perubahan per 24 jam.")
                            logger.info(f"📊 [Grab C5 Push] Push Bertahap (>15%) untuk '{item_name}': Rp {old_price:,.0f} -> Rp {float(new_price):,.0f} via {len(price_steps)} tahapan: {price_steps}")
                        else:
                            price_steps = [float(new_price)]
                        if price_guard_cb:
                            guard_error = price_guard_cb(upd, str((existing_it or {}).get("itemID") or item_id), old_price, float(new_price), len(price_steps))
                            if guard_error:
                                raise ValueError(guard_error)

                    # priceInMin uses minor units (Rp × 100) in Grab's menu API.
                    if has_price_change or is_new_item:
                        target_price_val = int(round(float(new_price) * 100)) if new_price is not None else 0
                    else:
                        target_price_val = old_price_minor

                    # 2. Create a new category once per SID/name. Never fall back
                    # to the first existing category when category creation fails.
                    category_key = (new_cat_name or "").strip().casefold()
                    if is_new_category and category_key and category_key not in cat_map:
                        if category_key in category_creation_errors:
                            raise ValueError(category_creation_errors[category_key])
                        selling_time_id = (categories[0].get("sellingTimeID") or "") if categories else ""
                        if not selling_time_id:
                            raise ValueError(f"Jadwal penjualan Grab tidak tersedia; kategori '{new_cat_name}' tidak dibuat agar tidak meninggalkan kategori yang tidak dapat dipakai.")
                        cat_res, cat_err = await call_with_auth_recovery(
                            lambda: api.create_category(group_id, target_sid, new_cat_name, selling_time_id),
                            "create category",
                        )
                        new_cid = (cat_res or {}).get("categoryID") or (cat_res or {}).get("id")
                        if cat_err or not new_cid:
                            error_text = f"Kategori Grab '{new_cat_name}' gagal dibuat; item terkait tidak dikirim. {cat_err or 'ID kategori tidak diberikan oleh Grab.'}"
                            category_creation_errors[category_key] = error_text
                            raise ValueError(error_text)
                        cat_map[category_key] = new_cid
                        created_category = dict(cat_res)
                        created_category.setdefault("sellingTimeID", selling_time_id)
                        cat_obj_map[new_cid] = created_category

                    target_cat_id = (
                        upd.get("category_id")
                        or cat_map.get(category_key)
                        or (existing_items_map.get(item_id) or {}).get("_c5CategoryID")
                    )
                    if not target_cat_id:
                        raise ValueError(f"Kategori target '{new_cat_name or '(kosong)'}' tidak ditemukan. Item tidak dikirim agar tidak masuk ke kategori yang salah.")

                    # Rename the existing category once when C5 keeps the same
                    # category ID and changes its name. A category move only
                    # changes the item's target category below.
                    existing_for_category = existing_items_map.get(item_id) or existing_items_map.get(item_name.strip().lower())
                    old_category_id = (existing_for_category or {}).get("_c5CategoryID")
                    if (
                        "CATEGORY_CHANGE" in changes
                        and not is_new_category
                        and old_category_id
                        and str(target_cat_id) == str(old_category_id)
                        and str(old_category_id) not in renamed_category_ids
                    ):
                        if str(old_category_id) in category_rename_errors:
                            raise ValueError(category_rename_errors[str(old_category_id)])
                        category_obj = cat_obj_map.get(old_category_id) or {}
                        _, cat_err = await call_with_auth_recovery(
                            lambda: api.edit_category(
                                group_id,
                                target_sid,
                                old_category_id,
                                new_cat_name,
                                category_obj.get("sellingTimeID") or "",
                            ),
                            "edit category",
                        )
                        if cat_err:
                            error_text = f"Kategori Grab '{new_cat_name}' gagal diubah: {cat_err}"
                            category_rename_errors[str(old_category_id)] = error_text
                            raise ValueError(error_text)
                        renamed_category_ids.add(str(old_category_id))
                        cat_map[category_key] = old_category_id

                    # 4. Handle Active Promo Check & Detachment for Grab C5 Push
                    if existing_it:
                        has_campaign = bool(existing_it.get("itemCampaignInfo"))
                        c_info = None
                        if active_camp_promos:
                            it_check_id = str((existing_it or {}).get("itemID") or item_id).strip()
                            it_check_name = (new_name or item_name).strip().lower()
                            it_cat_id = str((existing_it or {}).get("_c5CategoryID") or target_cat_id or "").strip()
                            it_cat_name = (new_cat_name or "").strip().lower()
                            c_info = (
                                active_camp_promos.get(it_check_id)
                                or active_camp_promos.get(it_check_name)
                                or (active_camp_promos.get(f"category:{it_cat_id}") if it_cat_id else None)
                                or (active_camp_promos.get(f"category:{it_cat_name}") if it_cat_name else None)
                                or active_camp_promos.get("store:all")
                            )
                            if c_info:
                                has_campaign = True

                        has_item_mutation = (
                            (has_price_change and target_price_val != old_price_minor and target_price_val > 0)
                            or bool(changes.intersection({"NAME_CHANGE", "DESCRIPTION_CHANGE", "PHOTO_CHANGE", "CATEGORY_CHANGE"}))
                        )

                        if has_campaign and has_item_mutation:
                            logger.info(f"🔍 [Grab C5 Push] Item '{new_name or item_name}' terdeteksi dalam promo/campaign aktif. Mencoba mencopot promo sebelum mutasi...")
                            try:
                                camp_id_direct = (c_info or {}).get("campaign_id")
                                if camp_id_direct:
                                    del_res, del_err = await api.delete_campaign(camp_id_direct)
                                    if not del_err:
                                        logger.info(f"🔓 [Grab C5 Push] Berhasil mencopot promo '{camp_id_direct}' untuk item '{new_name or item_name}'")
                                        res_item["note"] = f"Promo aktif dicopot ({camp_id_direct})"
                                        await asyncio.sleep(2.0)
                                    else:
                                        logger.warning(f"⚠️ [Grab C5 Push] Gagal mencopot promo langsung: {del_err}. Mencoba cancel_promos_for_item...")
                                        canceled_camps, camp_err = await api.cancel_promos_for_item(
                                            store_id=target_sid,
                                            item_id=str((existing_it or {}).get("itemID") or item_id),
                                            item_name=(new_name or item_name)
                                        )
                                        if canceled_camps:
                                            res_item["note"] = f"Promo aktif dicopot ({', '.join(canceled_camps)})"
                                            await asyncio.sleep(2.0)
                                else:
                                    canceled_camps, camp_err = await api.cancel_promos_for_item(
                                        store_id=target_sid,
                                        item_id=str((existing_it or {}).get("itemID") or item_id),
                                        item_name=(new_name or item_name)
                                    )
                                    if canceled_camps:
                                        logger.info(f"🔓 [Grab C5 Push] Berhasil mencopot {len(canceled_camps)} promo aktif untuk '{new_name or item_name}': {canceled_camps}")
                                        res_item["note"] = f"Promo aktif dicopot ({', '.join(canceled_camps)})"
                                    elif camp_err:
                                        logger.warning(f"⚠️ [Grab C5 Push] Peringatan saat mencopot promo otomatis ({camp_err}). Melanjutkan push harga...")
                                    else:
                                        logger.info(f"ℹ️ [Grab C5 Push] Tidak ditemukan kampanye aktif yang cocok untuk '{new_name or item_name}'. Melanjutkan push perubahan.")
                            except Exception as e_camp:
                                logger.warning(f"⚠️ [Grab C5 Push] Error saat mencopot promo: {e_camp}. Melanjutkan push harga...")

                    # If multiple price steps are needed, push intermediate price steps first
                    if has_price_change and not is_new_item and len(price_steps) > 1:
                        prev_step_price = old_price
                        for s_idx, s_price in enumerate(price_steps[:-1]):
                            step_target_minor = int(round(s_price * 100))
                            step_payload = dict(existing_it or {})
                            step_payload.update({
                                "itemName": ((existing_it or {}).get("itemName") or (existing_it or {}).get("name") or item_name),
                                "priceInMin": step_target_minor,
                                "description": (existing_it or {}).get("description") or "",
                            })
                            step_payload.pop("name", None)
                            step_payload.pop("photoURL", None)
                            step_payload.pop("_c5CategoryID", None)
                            if item_id:
                                step_payload["itemID"] = item_id

                            upsert_res, upsert_err = await call_with_auth_recovery(
                                lambda: api.upsert_item(
                                    group_id,
                                    target_sid,
                                    target_cat_id,
                                    step_payload,
                                    is_menu_group=is_menu_group,
                                    menu_group_id=menu_group_id,
                                ),
                                f"upsert item intermediate step {s_idx + 1}/{len(price_steps)}",
                            )
                            if upsert_err:
                                raise ValueError(f"Tahap {s_idx + 1}/{len(price_steps)} (Rp {s_price:,.0f}) gagal: {upsert_err}")

                            logger.info(f"   [Grab C5 Push Tahap {s_idx + 1}/{len(price_steps)}] Berhasil PUSH harga intermediate: Rp {s_price:,.0f} untuk '{item_name}'")
                            if step_cb:
                                try:
                                    step_cb(upd, s_idx + 1, len(price_steps), prev_step_price, s_price)
                                except Exception as e_cb:
                                    logger.warning(f"Error in step_cb: {e_cb}")
                            prev_step_price = s_price
                            await asyncio.sleep(1.5)

                    # Preserve fields absent from this C5 change. Sending blank
                    # photo/description on a price-only edit can erase merchant data.
                    item_payload = dict(existing_it or {})
                    item_payload.update({
                        "itemName": (new_name or item_name) if (is_new_item or "NAME_CHANGE" in changes) else ((existing_it or {}).get("itemName") or (existing_it or {}).get("name") or item_name),
                        "priceInMin": target_price_val,
                        "description": description if (is_new_item or "DESCRIPTION_CHANGE" in changes) else ((existing_it or {}).get("description") or ""),
                    })
                    if is_new_item or "PHOTO_CHANGE" in changes:
                        final_photo_url = ""
                        if photo_link:
                            if photo_link.startswith("https://food-cms.grab.com/"):
                                final_photo_url = photo_link
                            elif photo_link in uploaded_photo_cache:
                                final_photo_url = uploaded_photo_cache[photo_link]
                            else:
                                logger.info(f"Mengunggah foto untuk '{new_name or item_name}' ke Grab food-cms...")
                                try:
                                    b64_data, p_type = download_and_encode_image(photo_link)
                                    upload_res, upload_err = await call_with_auth_recovery(
                                        lambda: api.upload_item_photo(
                                            group_id,
                                            target_sid,
                                            b64_data,
                                            photo_type=p_type,
                                            is_menu_group=is_menu_group,
                                            menu_group_id=menu_group_id,
                                        ),
                                        "upload item photo",
                                    )
                                    if upload_err or not upload_res:
                                        raise ValueError(f"Gagal mengunggah foto ke Grab: {upload_err}")
                                    final_photo_url = upload_res
                                    uploaded_photo_cache[photo_link] = final_photo_url
                                    logger.info(f"Berhasil mengunggah foto Grab: {final_photo_url}")
                                except Exception as e_up:
                                    logger.warning(f"Gagal memproses foto untuk '{new_name or item_name}': {e_up}")
                                    raise ValueError(f"Gagal upload foto item '{new_name or item_name}': {e_up}")

                        item_payload["imageURL"] = final_photo_url
                        item_payload["imageURLs"] = [final_photo_url] if final_photo_url else []
                        res_item["new_photo"] = final_photo_url
                    else:
                        item_payload["imageURL"] = (
                            (existing_it or {}).get("imageURL")
                            or next(iter((existing_it or {}).get("imageURLs") or []), "")
                        )
                        item_payload["imageURLs"] = (
                            (existing_it or {}).get("imageURLs")
                            or ([item_payload["imageURL"]] if item_payload["imageURL"] else [])
                        )
                    item_payload.pop("name", None)
                    item_payload.pop("photoURL", None)
                    if is_new_item:
                        target_category = cat_obj_map.get(target_cat_id) or {}
                        selling_time_id = target_category.get("sellingTimeID") or ""
                        if not selling_time_id:
                            raise ValueError(f"Jadwal penjualan untuk kategori '{new_cat_name}' tidak tersedia; item baru tidak dikirim.")
                        item_payload["sellingTimeID"] = selling_time_id
                        item_payload["categoryName"] = new_cat_name
                    item_payload.pop("_c5CategoryID", None)
                    if item_id:
                        item_payload["itemID"] = item_id

                    item_weight = upd.get("item_weight")
                    if item_weight is not None:
                        try:
                            item_payload["sortOrder"] = int(item_weight)
                        except (ValueError, TypeError):
                            pass

                    upsert_res, upsert_err = await call_with_auth_recovery(
                        lambda: api.upsert_item(
                            group_id,
                            target_sid,
                            target_cat_id,
                            item_payload,
                            is_menu_group=is_menu_group,
                            menu_group_id=menu_group_id,
                        ),
                        "upsert item",
                    )

                    if upsert_err:
                        res_item["status"] = "FAILED"
                        res_item["error"] = upsert_err
                    else:
                        new_item_id = (upsert_res or {}).get("itemID")
                        if new_item_id:
                            res_item["item_id"] = str(new_item_id)
                            item_info_obj = {"itemID": str(new_item_id), "itemName": new_name or item_name, "_c5CategoryID": target_cat_id}
                            existing_items_map[str(new_item_id)] = item_info_obj
                            existing_items_map[(new_name or item_name).strip().lower()] = item_info_obj
                        if len(price_steps) > 1:
                            logger.info(f"✅ [Grab C5 Push] Successfully updated item '{new_name or item_name}' (SID: {target_sid}) via {len(price_steps)} price steps")
                        else:
                            logger.info(f"✅ [Grab C5 Push] Successfully updated item '{new_name or item_name}' (SID: {target_sid})")

                except Exception as ex_item:
                    logger.error(f"❌ Error processing Grab C5 item '{item_name}': {ex_item}")
                    res_item["status"] = "FAILED"
                    res_item["error"] = str(ex_item)

                results.append(res_item)
                if item_result_cb:
                    try:
                        err_cb = res_item.get("error") if res_item.get("status") == "FAILED" else None
                        item_result_cb(upd, res_item.get("status", "FAILED"), err_cb, applied=res_item)
                    except Exception:
                        pass

            # ── 1. Reorder Categories via PUT /food/merchant/categories-sort ──
            try:
                # Build lookup helpers for resolving category IDs:
                # 1. Direct valid Grab category ID
                # 2. C5 category ID specified in updates
                # 3. Normalized category name mapping (cat_map)
                valid_grab_cat_ids = {str(c.get("categoryID") or c.get("id")) for c in categories if (c.get("categoryID") or c.get("id"))}
                for cid in cat_obj_map.keys():
                    valid_grab_cat_ids.add(str(cid))

                c5_name_to_cid = {}
                for upd in updates:
                    c_name = (upd.get("category") or "").strip().casefold()
                    c_id = str(upd.get("category_id") or "").strip()
                    if c_name and c_id and c_id in valid_grab_cat_ids and c_name not in c5_name_to_cid:
                        c5_name_to_cid[c_name] = c_id

                ordered_c5_cat_names = []
                category_weights = {}
                for upd in updates:
                    for c_name in (upd.get("c5_categories") or []):
                        if c_name and c_name not in ordered_c5_cat_names:
                            ordered_c5_cat_names.append(c_name)
                    c_name_upd = (upd.get("category") or "").strip()
                    cw = upd.get("category_weight")
                    if c_name_upd and cw is not None and c_name_upd.casefold() not in category_weights:
                        try:
                            category_weights[c_name_upd.casefold()] = int(cw)
                        except (ValueError, TypeError):
                            pass

                if not ordered_c5_cat_names and category_weights:
                    sorted_c = sorted(category_weights.items(), key=lambda x: x[1])
                    ordered_c5_cat_names = [x[0] for x in sorted_c]

                if not ordered_c5_cat_names:
                    for upd in updates:
                        if "DELETE_ITEM" in (upd.get("changes") or upd.get("change_types") or []):
                            continue
                        c_name = (upd.get("category") or "").strip()
                        if c_name and c_name not in ordered_c5_cat_names:
                            ordered_c5_cat_names.append(c_name)

                if ordered_c5_cat_names or category_weights:
                    target_cat_ids = []
                    seen_cat_ids = set()
                    for c_name in ordered_c5_cat_names:
                        c_key = (c_name or "").strip().casefold()
                        cid = c5_name_to_cid.get(c_key) or cat_map.get(c_key)
                        if not cid and c_name in valid_grab_cat_ids:
                            cid = c_name
                        if cid and str(cid) not in seen_cat_ids:
                            target_cat_ids.append(str(cid))
                            seen_cat_ids.add(str(cid))

                    # Append any remaining existing categories from Grab not mentioned in C5.
                    # In Grab, higher sortOrder is at the top, so descending order reflects current top-to-bottom.
                    existing_sorted_cats = sorted(categories, key=lambda c: int(c.get("sortOrder") or 0), reverse=True)
                    current_cat_ids = []
                    for c in existing_sorted_cats:
                        cid = str(c.get("categoryID") or c.get("id") or "")
                        if cid:
                            current_cat_ids.append(cid)
                            if cid not in seen_cat_ids:
                                target_cat_ids.append(cid)
                                seen_cat_ids.add(cid)

                    if target_cat_ids and target_cat_ids != current_cat_ids:
                        logger.info(f"📐 [Grab C5 Push] Updating Category Order via PUT /food/merchant/categories-sort...")
                        logger.info(f"   Urutan target kategori: {target_cat_ids}")
                        total_cats = len(target_cat_ids)
                        # Grab displays categories with higher sortOrder at the top, down to 1 at the bottom.
                        sort_payload = [
                            {"resourceID": cid, "sortOrder": total_cats - idx}
                            for idx, cid in enumerate(target_cat_ids)
                        ]
                        ok_sort, err_sort = await call_with_auth_recovery(
                            lambda: api.sort_categories(group_id, target_sid, sort_payload),
                            "sort categories",
                        )
                        if ok_sort:
                            logger.info(f"✅ [Grab C5 Push] Category order successfully updated: {target_cat_ids}")
                        else:
                            logger.warning(f"⚠️ [Grab C5 Push] Failed to sort categories: {err_sort}")
            except Exception as cat_sort_ex:
                logger.warning(f"⚠️ [Grab C5 Push] Exception while sorting categories: {cat_sort_ex}")

            # ── 2. Reorder Items within each Category via PUT /food/merchant/items-sort ──
            try:
                target_cat_keys = set()
                for upd in updates:
                    c_name = (upd.get("category") or "").strip()
                    if c_name:
                        target_cat_keys.add(c_name.casefold())

                for cat_key in target_cat_keys:
                    cat_id = c5_name_to_cid.get(cat_key) or cat_map.get(cat_key)
                    if not cat_id:
                        continue

                    c5_items_in_cat = [
                        upd for upd in updates
                        if (upd.get("category") or "").strip().casefold() == cat_key
                        and not ("DELETE_ITEM" in (upd.get("changes") or upd.get("change_types") or []))
                        and not (isinstance(upd.get("changes"), dict) and upd["changes"].get("is_deleted_item"))
                    ]
                    c5_items_in_cat.sort(key=lambda u: u.get("item_weight") or 9999)

                    target_item_ids = []
                    seen_item_ids = set()
                    for upd in c5_items_in_cat:
                        it_id = str(upd.get("item_id") or "").strip()
                        it_name = upd.get("item_name_new") or upd.get("item_name") or ""
                        matched_id = None
                        if it_id and it_id in existing_items_map:
                            matched_id = it_id
                        elif it_name and it_name.strip().lower() in existing_items_map:
                            matched_id = str(existing_items_map[it_name.strip().lower()].get("itemID") or "")

                        final_iid = matched_id or it_id
                        if final_iid and final_iid not in seen_item_ids:
                            target_item_ids.append(final_iid)
                            seen_item_ids.add(final_iid)

                    # Append existing items in this category not in C5.
                    # In Grab, higher sortOrder is at the top, so descending order reflects current top-to-bottom.
                    cat_obj = cat_obj_map.get(cat_id) or {}
                    existing_cat_items = sorted(
                        cat_obj.get("items") or cat_obj.get("menuItems") or [],
                        key=lambda it: int(it.get("sortOrder") or 0),
                        reverse=True
                    )
                    current_item_ids = []
                    for it in existing_cat_items:
                        iid = str(it.get("itemID") or it.get("id") or "")
                        if iid:
                            current_item_ids.append(iid)
                            if iid not in seen_item_ids:
                                target_item_ids.append(iid)
                                seen_item_ids.add(iid)

                    if target_item_ids and len(target_item_ids) > 1 and target_item_ids != current_item_ids:
                        logger.info(f"📐 [Grab C5 Push] Updating Item Order for category '{cat_key}' ({cat_id}) via PUT /food/merchant/items-sort...")
                        logger.info(f"   Urutan target item: {target_item_ids}")
                        total_items = len(target_item_ids)
                        # Grab displays items with higher sortOrder at the top, down to 1 at the bottom.
                        item_sort_payload = [
                            {"resourceID": iid, "sortOrder": total_items - idx}
                            for idx, iid in enumerate(target_item_ids)
                        ]
                        ok_isort, err_isort = await call_with_auth_recovery(
                            lambda cid=cat_id, payload=item_sort_payload: api.sort_items(
                                group_id, target_sid, cid, payload, menu_group_id=menu_group_id or ""
                            ),
                            f"sort items ({cat_key})",
                        )
                        if ok_isort:
                            logger.info(f"✅ [Grab C5 Push] Items successfully reordered for category '{cat_key}'")
                        else:
                            logger.warning(f"⚠️ [Grab C5 Push] Failed to reorder items for category '{cat_key}': {err_isort}")
            except Exception as item_sort_ex:
                logger.warning(f"⚠️ [Grab C5 Push] Exception while sorting items: {item_sort_ex}")


        finally:
            proc_killed = False
            try:
                if proc:
                    from src.core.browser_factory import kill_process_tree
                    kill_process_tree(proc)
                    proc_killed = True
            except Exception:
                pass
            if not proc_killed and proc:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
            try:
                await browser.close()
            except Exception:
                pass

        return results

def push_c5_grab_for_merchant(username: str, password: str, store_id: str, updates: list, progress_cb=None, item_result_cb=None, price_guard_cb=None, store_name=None, step_cb=None):
    """
    Synchronous wrapper to run async Grab C5 push in a clean event loop.
    """
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(_async_push_c5_grab(username, password, store_id, updates, progress_cb, item_result_cb, price_guard_cb, store_name, step_cb=step_cb))
    finally:
        try:
            new_loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)
