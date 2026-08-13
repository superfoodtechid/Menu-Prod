# -*- coding: utf-8 -*-
import sys
import json
import time
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .client import ShopeeModifyClient

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

def _resolve_target_merchant_name(username: str, merchant_name: str, store_metadata: dict) -> str:
    if merchant_name and merchant_name.lower() != 'nan' and merchant_name != '-':
        return merchant_name
    return store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''

def _boot_client(store_metadata: dict, headless: bool = True) -> tuple[ShopeeModifyClient | None, str]:
    store_id = store_metadata["store_id"]
    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"
        
    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)
    
    session_file = WORKSPACE_DIR / "shopee" / "data" / f"session_{username}.json"
    browser.set_session_file(session_file)
    
    session_data = browser.get_session(
        username=username,
        password=password,
        headless=headless,
        close_browser=True,
        target_name=target_name,
        interactive=False
    )
    if not session_data or "shopee_tob_token" not in session_data:
        return None, "Gagal menginisialisasi browser session"
        
    extra_cookies = session_data.get("extra_cookies", {}).copy()
    if store_id:
        extra_cookies["shopee_tob_entity_id"] = str(store_id)

    client = ShopeeModifyClient(
        tob_token=session_data["shopee_tob_token"],
        entity_id=str(store_id),
        extra_cookies=extra_cookies
    )
    return client, ""

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

def edit_dish_upload_image(store_metadata: dict, dish_id: str, image_path: str, headless: bool = True) -> bool:
    store_id = store_metadata["store_id"]
    username = store_metadata.get("username") or "superfoodapp"
    password = store_metadata.get("password") or "Master@00@"

    target_name = _resolve_target_merchant_name(username, store_metadata.get("merchant_name", ""), store_metadata)
    
    session_file = WORKSPACE_DIR / "shopee" / "data" / f"session_{username}.json"
    browser.set_session_file(session_file)
    
    session_data = browser.get_session(
        username=username,
        password=password,
        headless=headless,
        close_browser=False,
        target_name=target_name,
        interactive=False
    )
    if not session_data or "driver" not in session_data:
        return False
        
    driver = session_data["driver"]
    try:
        _sync_store_session(driver, store_id)
        edit_url = f"https://partner.shopee.co.id/shopee-pos/menu-management/dish/edit?id={dish_id}&storeId={store_id}&defaultTab=sf"
        driver.get(edit_url)
        time.sleep(6)
        _dismiss_popups(driver)
        
        wait = WebDriverWait(driver, 15)
        file_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
        driver.execute_script("arguments[0].style.display='block'; arguments[0].style.opacity='1';", file_input)
        file_input.send_keys(str(Path(image_path).resolve()))
        time.sleep(5)
        
        save_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[span[contains(text(), 'Save') or contains(text(), 'Simpan')]]")))
        save_btn.click()
        time.sleep(5)
        driver.quit()
        return True
    except Exception as e:
        try:
            driver.quit()
        except:
            pass
        return False

def update_dish(
    client: ShopeeModifyClient,
    store_id: str,
    catalog_id: int | str,
    dish_id: int | str,
    name: str,
    price: float,
    description: str = "",
    available: bool = True,
    picture: str = "",
    opt_groups: list = None,
    existing_dish: dict = None
) -> bool:
    from .create import _build_dish_payload
    dish_str_id = str(dish_id)
    url = f"https://foody.shopee.co.id/api/seller/store/dishes/{dish_str_id}"
    payload = _build_dish_payload(
        name=name,
        price=price,
        description=description,
        available=available,
        catalog_id=catalog_id,
        picture=picture,
        opt_groups=opt_groups,
        existing_dish=existing_dish
    )
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

def reorder_categories(client: ShopeeModifyClient, store_id: str, ranks: list) -> bool:
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
