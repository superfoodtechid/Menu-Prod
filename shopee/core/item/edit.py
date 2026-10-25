# -*- coding: utf-8 -*-
import logging
import sys
import json
import time
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from shopee.core.client import ShopeeModifyClient
from shopee.core.session_utils import resolve_shopee_session, get_fast_shopee_session, invalidate_shopee_session

logger = logging.getLogger("ShopeeItemEdit")

WORKSPACE_DIR = Path(__file__).resolve().parents[3]
MENU_DIR = WORKSPACE_DIR
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

def _resolve_target_merchant_name(username: str, merchant_name: str, store_metadata: dict) -> str:
    nama_portal = store_metadata.get('nama_portal')
    if nama_portal and str(nama_portal).strip() and str(nama_portal).lower() not in ('nan', '-', 'none'):
        return str(nama_portal).strip()
    if merchant_name and merchant_name.lower() != 'nan' and merchant_name != '-':
        return merchant_name
    return store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''

def _boot_client(store_metadata: dict, headless: bool = True, force_browser: bool = False) -> tuple[ShopeeModifyClient | None, str]:
    store_id = store_metadata["store_id"]
    username = store_metadata.get("username")
    password = store_metadata.get("password")
    
    if not username:
        return None, "Username Shopee tidak ditemukan pada store_metadata outlet"
        
    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)

    # ── Fast-Path Pre-flight: Check cached session before launching browser ──
    if not force_browser:
        fast_session = get_fast_shopee_session(store_metadata, base_dir=MENU_DIR)
        if fast_session and fast_session.get("shopee_tob_token"):
            tob_token = fast_session["shopee_tob_token"]
            real_store_id = str(store_id) if store_id else str(fast_session.get("shopee_tob_entity_id") or "")
            real_merchant_id = str(fast_session.get("merchant_id") or "")
            extra_cookies = fast_session.get("extra_cookies") or {}
            client = ShopeeModifyClient(
                tob_token=tob_token,
                entity_id=real_store_id or str(store_id),
                merchant_id=real_merchant_id,
                username=username,
                extra_cookies=extra_cookies
            )
            return client, ""

    session_file = resolve_shopee_session(store_metadata, base_dir=MENU_DIR)
    browser.set_session_file(session_file)
    active_account = session_file.stem.replace("session_", "") if session_file.stem.startswith("session_") else username
    
    session_data = browser.get_session(
        username=active_account,
        password=password,
        headless=headless,
        close_browser=True,
        target_name=target_name,
        target_store_id=store_id,
        interactive=True
    )
    if not session_data or "shopee_tob_token" not in session_data:
        return None, "Gagal menginisialisasi browser session"
        
    client = ShopeeModifyClient(
        tob_token=session_data["shopee_tob_token"],
        entity_id=store_id,
        extra_cookies=session_data.get("extra_cookies", {})
    )
    return client, ""

def _sync_store_session(driver, store_id: str) -> None:
    """
    Menyinkronkan sesi browser ke target store ID menggunakan CDP cookie injection
    dan memicu halaman Business Hours.
    """
    try:
        store_str = str(store_id)
        existing_cookie = driver.get_cookie("shopee_tob_entity_id")
        if existing_cookie and str(existing_cookie.get("value")) == store_str:
            return

        curr_url = driver.current_url
        if "partner.shopee.co.id" not in curr_url:
            driver.get("https://partner.shopee.co.id/")
            time.sleep(2)

        def set_cdp_cookie(name, val, domain):
            driver.execute_cdp_cmd('Network.setCookie', {
                'name': name,
                'value': val,
                'domain': domain,
                'path': '/'
            })

        for domain in [".shopee.co.id", "partner.shopee.co.id"]:
            set_cdp_cookie("shopee_tob_entity_id", store_str, domain)
        time.sleep(1)

        business_hours_url = "https://partner.shopee.co.id/settings/shopee-food/business-hours-settings"
        driver.get(business_hours_url)
        time.sleep(4)
    except Exception as e:
        logger.warning(f"Gagal menyinkronkan sesi store di browser: {e}")

def _dismiss_popups(driver) -> None:
    """
    Mencari dan mengklik tombol penutup pop-up (seperti 'Got it', 'Mengerti', dll)
    agar tidak menghalangi interaksi UI.
    """
    try:
        # Cari tombol penutup pop-up yang umum (Case-Insensitive friendly)
        buttons = driver.find_elements(By.XPATH, (
            "//button["
            "contains(text(), 'Got it') or contains(., 'Got it') or "
            "contains(text(), 'Got It') or contains(., 'Got It') or "
            "contains(text(), 'Mengerti') or contains(., 'Mengerti') or "
            "contains(text(), 'Tutup') or contains(., 'Tutup') or "
            "contains(text(), 'Ok') or contains(., 'Ok') or "
            "contains(text(), 'OK') or contains(., 'OK')]"
        ))
        for btn in buttons:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.5)
                break
                
        # Cek ikon close (X)
        close_icons = driver.find_elements(By.CSS_SELECTOR, (
            ".ant-tour-close, .ant-modal-close, .shopee-modal__close, "
            ".ant-modal-close-x, .ant-tour-close-x"
        ))
        for icon in close_icons:
            if icon.is_displayed():
                driver.execute_script("arguments[0].click();", icon)
                time.sleep(1.5)
                break
    except Exception as e:
        pass

def edit_dish_upload_image(
    store_metadata: dict,
    dish_id: str,
    image_path: str,
    headless: bool = True,
    driver=None,
    sync_session: bool = True,
    store_id: str = None
) -> bool:
    target_store_id = str(store_id or store_metadata.get("store_id") or "")
    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"

    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)
    
    session_file = resolve_shopee_session(store_metadata, base_dir=WORKSPACE_DIR)
    browser.set_session_file(session_file)
    active_account = session_file.stem.replace("session_", "") if session_file.stem.startswith("session_") else username
    
    own_driver = False
    if driver is None:
        session_data = browser.get_session(
            username=active_account,
            password=password,
            headless=headless,
            close_browser=False,
            target_name=target_name,
            target_store_id=target_store_id,
            interactive=False,
            load_images=True,
        )
        if not session_data or "driver" not in session_data:
            logger.error(f"Gagal menginisialisasi browser session untuk upload gambar item {dish_id}")
            return False
        driver = session_data["driver"]
        own_driver = True

    try:
        if sync_session and target_store_id:
            _sync_store_session(driver, str(target_store_id))

        edit_url = f"https://partner.shopee.co.id/shopee-pos/menu-management/dish/edit?id={dish_id}&storeId={target_store_id}&defaultTab=sf"
        driver.get(edit_url)
        time.sleep(5)
        _dismiss_popups(driver)
        
        wait = WebDriverWait(driver, 25)
        file_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
        driver.execute_script("arguments[0].style.display='block'; arguments[0].style.opacity='1';", file_input)
        file_input.send_keys(str(Path(image_path).resolve()))
        time.sleep(1)

        # Shopee opens a separate crop dialog after file selection. Scope all
        # crop actions to that visible dialog; a global "Simpan" selector can
        # otherwise click the page's Save button behind a still-loading dialog.
        crop_dialog = None
        dialog_selectors = (
            "[role='dialog'], .shopee-pos-modal-wrap, .shopee-modal, "
            "[class*='crop_modal'], [class*='cropper'], [class*='modal-wrap']"
        )
        for _ in range(20):
            for dialog in driver.find_elements(By.CSS_SELECTOR, dialog_selectors):
                try:
                    if dialog.is_displayed() and "potong gambar" in dialog.text.lower():
                        crop_dialog = dialog
                        break
                except Exception:
                    continue
            if crop_dialog:
                break
            time.sleep(0.5)

        if crop_dialog:
            # Wait for the image itself to render (not just an enabled button)
            # and scope the crop action to this dialog. Never save the dish form
            # while the crop preview is blank or still loading.
            crop_btn = None
            preview_ready = False
            crop_button_xpath = (
                ".//button[contains(., 'Konfirmasi') or contains(., 'Confirm') "
                "or contains(., 'Simpan') or contains(., 'Save') "
                "or contains(., 'Apply') or contains(., 'Selesai') or contains(., 'OK')]"
            )
            for _ in range(40):
                try:
                    preview_ready = bool(driver.execute_script(
                        """
                        const root = arguments[0];
                        const imgs = Array.from(root.querySelectorAll('img'));
                        const imageReady = imgs.some(img => img.complete && img.naturalWidth > 0 && img.getClientRects().length);
                        const canvasReady = Array.from(root.querySelectorAll('canvas')).some(
                            canvas => canvas.width > 0 && canvas.height > 0 && canvas.getClientRects().length
                        );
                        return imageReady || canvasReady;
                        """,
                        crop_dialog,
                    ))
                    buttons = crop_dialog.find_elements(By.XPATH, crop_button_xpath)
                    candidate_btn = next((b for b in buttons if b.is_displayed() and b.is_enabled()), None)
                    if preview_ready and candidate_btn:
                        crop_btn = candidate_btn
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            if not crop_btn:
                raise RuntimeError(
                    "Dialog Potong Gambar tetap kosong/loading; pratinjau foto atau tombol konfirmasi crop tidak siap."
                )

            driver.execute_script("arguments[0].click();", crop_btn)
            try:
                WebDriverWait(driver, 25).until(
                    lambda d: not any(
                        dialog.is_displayed() and "potong gambar" in dialog.text.lower()
                        for dialog in d.find_elements(By.CSS_SELECTOR, dialog_selectors)
                    )
                )
            except Exception:
                raise RuntimeError("Dialog Potong Gambar tidak tertutup setelah konfirmasi; proses simpan form dibatalkan.")

        # Click only the dish form's primary Save button. Avoid matching a
        # hidden/overlay button or a crop-modal action left in the DOM.
        save_btn_xpath = (
            "//button[contains(@class, 'shopee-pos-btn-primary') and "
            "(contains(., 'Save') or contains(., 'Simpan') or contains(., 'Ubah'))]"
        )
        save_btn = wait.until(EC.element_to_be_clickable((By.XPATH, save_btn_xpath)))
        driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.5)
        # Confirm the button belongs to the page, not any remaining dialog.
        driver.execute_script(
            "if (arguments[0].closest('[role=dialog], .shopee-pos-modal-wrap, .shopee-modal')) "
            "{ throw new Error('Save button belongs to a modal'); }",
            save_btn,
        )
        save_btn.click()

        # Some Shopee portal versions ask for a second confirmation after the
        # dish form's Save button (e.g. "Apakah Anda yakin ... perubahan menu").
        # Handle both browser-native confirm() and an in-page confirmation
        # modal, but only click affirmative controls inside that modal.
        try:
            alert = driver.switch_to.alert
            alert_text = (alert.text or "").strip()
            if alert_text:
                alert.accept()
                logger.info("Shopee confirmation alert accepted after saving dish %s: %s", dish_id, alert_text[:200])
        except Exception:
            pass

        confirmation_selectors = (
            "[role='dialog'], .shopee-pos-modal-wrap, .shopee-modal, "
            ".ant-modal, [class*='modal-wrap'], [class*='confirm']"
        )
        confirmation_deadline = time.time() + 5
        while time.time() < confirmation_deadline:
            confirmation_handled = False
            for dialog in driver.find_elements(By.CSS_SELECTOR, confirmation_selectors):
                try:
                    if not dialog.is_displayed():
                        continue
                    dialog_text = (dialog.text or "").strip()
                    normalized_text = dialog_text.lower()
                    asks_confirmation = (
                        ("yakin" in normalized_text or "sure" in normalized_text or "confirm" in normalized_text)
                        and any(word in normalized_text for word in ("menu", "perubahan", "change", "save", "simpan"))
                    )
                    if not asks_confirmation:
                        continue

                    affirmative_xpath = (
                        ".//button[contains(@class, 'primary') or contains(@class, 'confirm') "
                        "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ya') "
                        "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'yakin') "
                        "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm') "
                        "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'simpan') "
                        "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'save')]"
                    )
                    candidates = [b for b in dialog.find_elements(By.XPATH, affirmative_xpath) if b.is_displayed() and b.is_enabled()]
                    # Prefer a clearly affirmative button; do not select a
                    # generic primary button if it is the cancel action.
                    confirm_btn = next((b for b in candidates if any(
                        word in (b.text or "").lower() for word in ("ya", "yakin", "confirm", "simpan", "save")
                    )), None)
                    if not confirm_btn:
                        confirm_btn = next((b for b in candidates if "primary" in (b.get_attribute("class") or "").lower()), None)
                    if not confirm_btn:
                        raise RuntimeError(f"Konfirmasi perubahan menu muncul tetapi tombol persetujuan tidak ditemukan: {dialog_text[:250]}")
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    logger.info("Shopee menu-change confirmation accepted for dish %s.", dish_id)
                    confirmation_handled = True
                    break
                except RuntimeError:
                    raise
                except Exception:
                    continue
            if confirmation_handled:
                break
            time.sleep(0.25)

        # Shopee may take several seconds to process the image and can display
        # validation errors in toast/alert components. Wait for the request UI
        # to settle and surface explicit portal errors to the caller.
        settled = False
        for _ in range(50):
            state = driver.execute_script(
                """
                const visible = el => !!(el && el.getClientRects().length &&
                    getComputedStyle(el).visibility !== 'hidden');
                const notices = Array.from(document.querySelectorAll(
                    '[role=alert], [class*="toast"], [class*="Toast"], [class*="message"], [class*="Message"], [class*="notification"], [class*="Notification"]'
                )).filter(visible).map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean);
                const button = Array.from(document.querySelectorAll('button')).find(el =>
                    el.className && String(el.className).includes('shopee-pos-btn-primary') &&
                    /save|simpan|ubah/i.test(el.innerText || el.textContent || '') && visible(el));
                const busy = !!(button.disabled || button.getAttribute('aria-busy') === 'true' ||
                    button.querySelector('[class*="loading"], [class*="spin"], [class*="Spin"]'));
                return {notices, busy};
                """,
            )
            notices = state.get("notices", []) if isinstance(state, dict) else []
            joined_notices = " ".join(notices)
            if any(word in joined_notices.lower() for word in ("gagal", "error", "failed", "tidak berhasil")):
                raise RuntimeError(f"Shopee menolak penyimpanan foto: {joined_notices[:400]}")
            if any(word in joined_notices.lower() for word in ("berhasil", "success", "saved", "tersimpan")):
                settled = True
                break
            if not (state or {}).get("busy", False):
                # A short quiet period avoids returning while the portal is
                # still updating the form after the button spinner disappears.
                time.sleep(2)
                settled = True
                break
            time.sleep(0.4)
        if not settled:
            raise RuntimeError("Portal masih memproses penyimpanan foto setelah 20 detik.")
        return True
    except Exception as e:
        logger.error(f"Gagal mengunggah gambar ke dish ID {dish_id} via portal: {e}")
        return False
    finally:
        if own_driver and driver:
            try:
                driver.quit()
            except Exception:
                pass


def edit_dish_update_name(
    store_metadata: dict,
    dish_id: str,
    new_name: str,
    headless: bool = True,
    store_id: str = None,
) -> bool:
    """Rename an existing dish through the merchant portal, without price API fields."""
    target_store_id = str(store_id or store_metadata.get("store_id") or "")
    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"
    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)
    session_file = resolve_shopee_session(store_metadata, base_dir=WORKSPACE_DIR)
    browser.set_session_file(session_file)
    active_account = session_file.stem.replace("session_", "") if session_file.stem.startswith("session_") else username
    session_data = browser.get_session(
        username=active_account, password=password, headless=headless,
        close_browser=True, target_name=target_name, target_store_id=target_store_id,
        interactive=False, allow_login=False, load_images=False,
    )
    if not session_data or "driver" not in session_data:
        logger.error("Gagal menginisialisasi sesi portal untuk rename dish %s", dish_id)
        return False

    driver = session_data["driver"]
    try:
        edit_url = f"https://partner.shopee.co.id/shopee-pos/menu-management/dish/edit?id={dish_id}&storeId={target_store_id}&defaultTab=sf"
        driver.get(edit_url)
        wait = WebDriverWait(driver, 25)
        _dismiss_popups(driver)
        name_input = None
        name_xpath = (
            "//label[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nama menu')]/following::input[1]"
            " | //input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nama menu')]"
        )
        try:
            name_input = wait.until(EC.visibility_of_element_located((By.XPATH, name_xpath)))
        except Exception:
            # Portal markup sometimes uses a non-label wrapper; find the text
            # field inside the nearest visible section titled "Nama Menu".
            for candidate in driver.find_elements(By.XPATH, "//input[not(@type='file') and (@type='text' or not(@type))]"):
                try:
                    context = candidate.find_element(By.XPATH, "./ancestor::*[self::div or self::section][.//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nama menu')]][1]")
                    if context.is_displayed():
                        name_input = candidate
                        break
                except Exception:
                    continue
        if not name_input:
            raise RuntimeError("Field Nama Menu tidak ditemukan pada halaman edit.")

        name_input.clear()
        name_input.send_keys(new_name)
        save_xpath = "//button[contains(@class, 'shopee-pos-btn-primary') and (contains(., 'Simpan') or contains(., 'Save') or contains(., 'Ubah'))]"
        save_btn = wait.until(EC.element_to_be_clickable((By.XPATH, save_xpath)))
        save_btn.click()

        # Accept portal/native confirmation dialogs without touching unrelated dialogs.
        try:
            alert = driver.switch_to.alert
            if alert.text:
                alert.accept()
        except Exception:
            pass
        deadline = time.time() + 5
        while time.time() < deadline:
            handled = False
            for dialog in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], .shopee-pos-modal-wrap, .shopee-modal, .ant-modal, [class*='modal-wrap'], [class*='confirm']"):
                try:
                    text = (dialog.text or "").strip()
                    lowered = text.lower()
                    if not dialog.is_displayed() or not ("yakin" in lowered or "sure" in lowered or "confirm" in lowered):
                        continue
                    if not any(word in lowered for word in ("menu", "perubahan", "change", "simpan", "save")):
                        continue
                    buttons = dialog.find_elements(By.XPATH, ".//button")
                    affirmative = next((b for b in buttons if b.is_displayed() and b.is_enabled() and any(w in (b.text or "").lower() for w in ("ya", "yakin", "confirm", "simpan", "save"))), None)
                    if affirmative:
                        driver.execute_script("arguments[0].click();", affirmative)
                        handled = True
                    else:
                        raise RuntimeError(f"Dialog konfirmasi rename tidak memiliki tombol persetujuan: {text[:200]}")
                    break
                except RuntimeError:
                    raise
                except Exception:
                    continue
            if handled:
                break
            time.sleep(0.25)
        time.sleep(2)
        return True
    except Exception as exc:
        logger.error("Gagal mengubah nama dish %s melalui portal: %s", dish_id, exc)
        return False
    finally:
        try:
            driver.quit()
        except Exception:
            pass

def update_dish(
    client: ShopeeModifyClient,
    store_id: str,
    catalog_id: int | str,
    dish_id: int | str,
    name: str = None,
    price: float = None,
    description: str = "",
    available: bool = True,
    picture: str = "",
    opt_groups: list = None,
    existing_dish: dict = None,
    rank: int = None,
    list_price: float = None,
    include_price_mutation: bool = True
) -> bool:
    from .create import _build_dish_payload
    dish_str_id = str(dish_id)
    url = f"https://foody.shopee.co.id/api/seller/store/dishes/{dish_str_id}"
    payload_raw = _build_dish_payload(
        name=name,
        price=price,
        description=description,
        available=available,
        catalog_id=catalog_id,
        picture=picture,
        opt_groups=opt_groups,
        rank=rank,
        existing_dish=existing_dish,
        list_price=list_price,
        include_price_mutation=include_price_mutation
    )
    if isinstance(payload_raw, dict) and "dish" in payload_raw:
        payload = payload_raw
    else:
        payload = {"dish": payload_raw, "option_group_bindings": []}

    if "option_group_bindings" not in payload:
        payload["option_group_bindings"] = []

    dish_data = payload.get("dish") or {}
    dish_data["id"] = dish_str_id
    if catalog_id:
        dish_data["catalog_id"] = str(catalog_id)
    if include_price_mutation and store_id:
        dish_data["store_id"] = str(store_id)

    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False

def update_category(client: ShopeeModifyClient, store_id: str, catalog_id: str, name: str) -> bool:
    url = f"https://foody.shopee.co.id/api/seller/store/catalog/update"
    payload = {"id": int(catalog_id), "name": name}
    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False

def reorder_categories(client: ShopeeModifyClient, store_id: str, ranks: list[dict]) -> bool:
    """
    Mengatur urutan kategori (catalogs) di toko.
    ranks format: [{"id": "3142001330862080", "rank": 1}, ...]
    """
    url = "https://foody.shopee.co.id/api/seller/store/catalogs/-/rank"
    formatted_ranks = []
    for item in ranks:
        formatted_ranks.append({
            "id": str(item["id"]),
            "rank": int(item["rank"])
        })
    payload = {"ranks": formatted_ranks}
    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False

def reorder_dishes(client: ShopeeModifyClient, store_id: str, ranks: list[dict]) -> bool:
    """
    Mengatur urutan item (dishes) dalam kategori / toko.
    ranks format: [{"id": "3148484252139008", "rank": 1}, {"id": "3148483850695168", "rank": 2}, ...]
    Endpoint: POST https://foody.shopee.co.id/api/seller/store/dishes/-/rank
    """
    url = "https://foody.shopee.co.id/api/seller/store/dishes/-/rank"
    formatted_ranks = []
    for item in ranks:
        formatted_ranks.append({
            "id": str(item["id"]),
            "rank": int(item["rank"])
        })
    payload = {"ranks": formatted_ranks}
    try:
        resp = client.session.post(url, json=payload, headers=client._seller_headers(override_entity_id=store_id), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False


def edit_dish_via_portal(
    store_metadata: dict,
    dish_id: str,
    name: str = None,
    price: float = None,
    description: str = None,
    available: bool = None,
    image_path: str = None,
    headless: bool = True
) -> tuple[bool, str]:
    client, err = _boot_client(store_metadata, headless=headless)
    if not client:
        return False, f"Boot client failed: {err}"
        
    store_id = store_metadata["store_id"]
    dish = client.get_dish_detail(dish_id, store_id)
    if not dish:
        return False, f"Detail hidangan dengan ID {dish_id} tidak ditemukan: {client.last_error}"
        
    catalog_id = dish.get("catalog_id")
    target_name = name if name is not None else dish.get("name")
    target_price = price if price is not None else (float(dish.get("price", 0)) / 100000.0)
    target_desc = description if description is not None else dish.get("description", "")
    target_avail = available if available is not None else dish.get("available", True)
    
    target_pic = dish.get("picture", "")
    if image_path and Path(image_path).exists():
        print(f"  [*] Mengunggah foto baru ke Shopee CDN...")
        uploaded_hash = client.upload_image(image_path)
        if uploaded_hash:
            target_pic = uploaded_hash
            
    ok = update_dish(
        client=client,
        store_id=store_id,
        catalog_id=catalog_id,
        dish_id=int(dish_id),
        name=target_name,
        price=target_price,
        description=target_desc,
        available=target_avail,
        picture=target_pic,
        opt_groups=dish.get("option_groups", []),
        existing_dish=dish
    )
    if not ok:
        return False, f"Gagal mengupdate hidangan via API: {client.last_error}"
        
    return True, f"Hidangan '{target_name}' (ID {dish_id}) berhasil diupdate."

def edit_menu_shopee(
    store_metadata: dict,
    dish_id: str,
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
    return edit_dish_via_portal(
        store_metadata=store_metadata,
        dish_id=str(dish_id),
        name=name,
        price=price_rp,
        description=description,
        available=available,
        image_path=image_path,
        headless=headless
    )
