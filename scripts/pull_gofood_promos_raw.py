# -*- coding: utf-8 -*-
import os
import sys
import json
import base64
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "menu_core"))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

def decode_base64_promo(promo_val):
    """Mencoba mendecode string promo jika berupa Base64."""
    if not promo_val:
        return None
    if isinstance(promo_val, dict):
        return promo_val
    if isinstance(promo_val, str):
        try:
            decoded = base64.b64decode(promo_val).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            try:
                return json.loads(promo_val)
            except Exception:
                return promo_val
    return promo_val

def get_auth_headers(token):
    clean_token = token.replace("Bearer ", "").strip()
    return {
        'Accept': 'application/json, text/plain, */*',
        'Authentication-Type': 'go-id',
        'Authorization': f'Bearer {clean_token}',
        'Origin': 'https://portal.gofoodmerchant.co.id',
        'Referer': 'https://portal.gofoodmerchant.co.id/',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'accept-language': 'id',
        'accept-version': '2026-08-21',
        'gojek-country-code': 'ID'
    }

def fetch_mpp_promotions_full(access_token, restaurant_uuid=""):
    """
    Menarik seluruh data promo dari GoBiz MPP API (Sumber 2) dengan pagination:
    1. Melakukan perulangan halaman (page 1, 2, 3...) hingga seluruh records terambil
    2. Mengambil detail masing-masing promo beserta menu_items dan diskonnya secara concurrent
    """
    headers = get_auth_headers(access_token)
    session = requests.Session()
    session.headers.update(headers)

    all_records = []
    page = 1
    limit = 50
    total_count = None

    log(f"Mengakses GoBiz MPP Promotions API dengan pagination otomatis...")
    while True:
        list_url = f'https://api.gojekapi.com/mpp/merchant/promotions?page={page}&limit={limit}&source=gobiz_webapp'
        log(f"-> Mengambil halaman {page}: {list_url}")
        try:
            r = session.get(list_url, timeout=15)
            if r.status_code != 200:
                log(f"Gagal mengambil daftar MPP promo halaman {page} (HTTP {r.status_code}): {r.text[:200]}")
                break

            list_data = r.json()
            data_obj = list_data.get('data', {})
            records = data_obj.get('records', [])
            total_count = data_obj.get('total_count', total_count)

            if not records:
                log(f"   Halaman {page} kosong, proses pagination selesai.")
                break

            all_records.extend(records)
            log(f"   Halaman {page} berhasil: +{len(records)} records (Total: {len(all_records)} / {total_count or '?'})")

            # Cek jika sudah mencapai total_count dari server
            if total_count is not None and len(all_records) >= total_count:
                log(f"   Seluruh records ({len(all_records)}) telah lengkap terambil!")
                break

            # Jika jumlah item lebih sedikit dari limit, ini halaman terakhir
            if len(records) < limit:
                break

            page += 1
            if page > 30:  # Batas pengaman
                log("   Mencapai batas pengaman maksimum (30 halaman).")
                break
        except Exception as e:
            log(f"Exception saat fetch MPP promotions halaman {page}: {e}")
            break

    log(f"Total program promosi di GoBiz MPP yang terkumpul: {len(all_records)} records.")

    # Ambil detail masing-masing promo secara concurrent (5 workers)
    log(f"Mengambil detail program promo untuk seluruh {len(all_records)} records...")

    def fetch_one_detail(rec):
        pid = rec.get('id')
        detail_obj = None
        if pid:
            try:
                d_url = f'https://api.gojekapi.com/mpp/merchant/promotions/{pid}?source=gobiz_webapp'
                dr = session.get(d_url, timeout=12)
                if dr.status_code == 200:
                    detail_obj = dr.json().get('data', {})
            except Exception:
                pass
        return {
            "summary": rec,
            "detail": detail_obj
        }

    with ThreadPoolExecutor(max_workers=5) as executor:
        full_records = list(executor.map(fetch_one_detail, all_records))

    details_success = sum(1 for r in full_records if r.get('detail') is not None)
    log(f"Berhasil mengunduh detail untuk {details_success} dari {len(full_records)} program promosi.")

    return {
        "fetched_at": datetime.utcnow().isoformat(),
        "restaurant_uuid": restaurant_uuid,
        "total_records": len(all_records),
        "total_count": total_count,
        "pages_fetched": page,
        "raw_list_response": {
            "data": {
                "limit": limit,
                "total_count": total_count,
                "records": all_records
            }
        },
        "promotions_with_details": full_records
    }

def fetch_menu_rest_api(access_token, restaurant_uuid):
    """
    Mengambil data menu GoFood secara langsung via REST API jika restaurant_uuid diketahui.
    """
    headers = get_auth_headers(access_token)
    menu_url = f"https://api.gojekapi.com/gofood/merchant/v1/restaurants/{restaurant_uuid}/menus"
    log(f"Mengakses GoFood Menu API: {menu_url}")
    try:
        r = requests.get(menu_url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        log(f"Gagal ambil menu via menus API (HTTP {r.status_code}): {r.text[:200]}")
    except Exception as e:
        log(f"Exception saat ambil menu API: {e}")
    return None

def main():
    parser = argparse.ArgumentParser(description="Tarik data JSON mentah dari 2 sumber promo GoFood.")
    parser.add_argument("--email", default="cinta2@byfoodmaster.com", help="Email login GoFood")
    parser.add_argument("--store-id", default="G988436960", help="Store ID target (misal G988436960)")
    parser.add_argument("--nama-outlet", default="Ayam Geprek Cinta, Lawang", help="Nama outlet target")
    parser.add_argument("--output-dir", default=str(BASE_DIR / "data" / "exports"), help="Direktori output JSON")
    args = parser.parse_args()

    email_target = args.email.strip()
    store_id = args.store_id.strip()
    nama_outlet = args.nama_outlet.strip()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log("=" * 70)
    log(f"MEMULAI PENARIKAN RAW PROMO JSON GOFOOD")
    log(f"Target Email : {email_target}")
    log(f"Store ID     : {store_id}")
    log(f"Nama Outlet  : {nama_outlet}")
    log(f"Output Dir   : {out_dir}")
    log("=" * 70)

    # 1. Cek atau muat sesi GoFood
    from login_gofood import load_gofood_session, login_outlet
    from menu_core.gofood_api import resolve_restaurant_info, fetch_gofood_menu_and_modifiers

    cached_session = load_gofood_session(email_target)
    access_token = None
    restaurant_uuid = None
    captured_menu = None

    if cached_session and cached_session.get("cookies"):
        for c in cached_session.get("cookies", []):
            if c.get("name") == "access_token":
                access_token = c.get("value")
                break
        restaurant_uuid = cached_session.get("restaurant_uuid")

    # Uji validitas token jika ada
    token_valid = False
    if access_token:
        log(f"Ditemukan sesi tersimpan untuk {email_target}. Menguji validitas token...")
        try:
            test_h = get_auth_headers(access_token)
            test_r = requests.get(
                "https://api.gojekapi.com/mpp/merchant/promotions?page=1&limit=1&source=gobiz_webapp",
                headers=test_h,
                timeout=8
            )
            if test_r.status_code == 200:
                log("Token tersimpan VALID!")
                token_valid = True
            else:
                log(f"Token tersimpan kedaluwarsa (HTTP {test_r.status_code}). Perlu login ulang.")
        except Exception as te:
            log(f"Gagal menguji token: {te}")

    # Jika token tidak ada atau tidak valid, jalankan login_outlet
    if not token_valid:
        log(f"Meluncurkan browser login untuk akun: {email_target}...")
        store_meta = {
            "nama_outlet": nama_outlet,
            "store_id": store_id,
            "cabang": "Lawang",
            "email": email_target,
            "emails": [email_target, "cinta1@byfoodmaster.com"],
            "phone": "6281232166512"
        }
        login_res = login_outlet(store_meta)
        if not login_res or not login_res.get("access_token"):
            log("❌ Gagal login atau tidak menerima access_token.")
            sys.exit(1)
        
        access_token = login_res.get("access_token")
        restaurant_uuid = login_res.get("restaurant_uuid")
        captured_menu = login_res.get("captured_menu")
        log("✅ Login berhasil! Token dan sesi baru telah didapatkan.")

    # Pastikan restaurant_uuid terisi
    if access_token and not restaurant_uuid:
        try:
            r_info = resolve_restaurant_info(access_token, store_id)
            restaurant_uuid = r_info.get("restaurant_uuid")
            if restaurant_uuid:
                log(f"Identitas restaurant_uuid terdeteksi: {restaurant_uuid}")
        except Exception as re_err:
            log(f"Info: Gagal auto-resolve restaurant_uuid: {re_err}")

    # 2. Ambil Sumber 1: Menu JSON
    log("\n--- [SUMBER 1] Mengambil Data Menu GoFood (Menu API / Intercept) ---")
    menu_data = None
    
    # 2a. Jalur Direct REST API (cepat ~0.8 detik)
    try:
        api_ok, api_res = fetch_gofood_menu_and_modifiers(access_token, store_id)
        if api_ok and api_res.get('captured_menu'):
            menu_data = api_res['captured_menu']
            if not restaurant_uuid:
                restaurant_uuid = api_res.get('restaurant_uuid')
            log("✅ Menu berhasil diambil via GoFood Direct REST API!")
    except Exception as api_err:
        log(f"Info: Jalur direct REST API gagal ({api_err}), mencoba opsi cadangan...")

    # 2b. Jalur endpoint menus langsung jika restaurant_uuid ada
    if not menu_data and restaurant_uuid:
        menu_data = fetch_menu_rest_api(access_token, restaurant_uuid)

    # 2c. Cek file hasil intercept di Gofood/API/
    if not menu_data:
        gofood_api_file = BASE_DIR / "Gofood" / "API" / f"menu-response-{store_id}.json"
        if gofood_api_file.exists():
            try:
                with open(gofood_api_file, "r", encoding="utf-8") as f:
                    menu_data = json.load(f)
                log(f"Memuat menu dari cache intercept: {gofood_api_file}")
            except Exception as fe:
                log(f"Peringatan: Gagal baca cache intercept: {fe}")

    # 2d. Fallback captured_menu dari browser
    if not menu_data and captured_menu:
        menu_data = captured_menu

    # 2e. Fallback jika file raw_gofood_menu_{store_id}.json sudah ada sebelumnya
    if not menu_data:
        src1_path = out_dir / f"raw_gofood_menu_{store_id}.json"
        if src1_path.exists():
            try:
                with open(src1_path, "r", encoding="utf-8") as f:
                    cached_menu = json.load(f)
                    if cached_menu and cached_menu.get("menus"):
                        menu_data = cached_menu
                        log(f"Memuat menu dari file ekspor sebelumnya: {src1_path}")
            except Exception:
                pass

    # Decode field Base64 promotion di dalam setiap item menu agar mudah dibaca manusia
    decoded_items_promo_count = 0
    if menu_data and isinstance(menu_data, dict):
        menus = menu_data.get("menus", [])
        for cat in menus:
            for item in cat.get("menu_items", []):
                raw_promo = item.get("promotion")
                if raw_promo:
                    item["_decoded_promotion"] = decode_base64_promo(raw_promo)
                    decoded_items_promo_count += 1
                orig_p = float(item.get("original_price") or item.get("list_price") or 0)
                cur_p = float(item.get("price") or 0)
                if orig_p > cur_p > 0:
                    item["_price_diff_detected"] = {
                        "original_price": orig_p,
                        "current_price": cur_p,
                        "diff": orig_p - cur_p
                    }

    # Simpan Sumber 1 ke file JSON
    src1_path = out_dir / f"raw_gofood_menu_{store_id}.json"
    with open(src1_path, "w", encoding="utf-8") as f:
        json.dump(menu_data or {}, f, indent=2, ensure_ascii=False)
    log(f"✅ [SUMBER 1] Berhasil disimpan ke: {src1_path}")
    log(f"   Total item dengan field promotion/base64: {decoded_items_promo_count}")

    # 3. Ambil Sumber 2: GoBiz MPP Promotions API
    log("\n--- [SUMBER 2] Mengambil Data Promosi GoBiz MPP (MPP Promotions API) ---")
    mpp_data = fetch_mpp_promotions_full(access_token, restaurant_uuid=restaurant_uuid or "")
    
    src2_path = out_dir / f"raw_gofood_mpp_promotions_{store_id}.json"
    with open(src2_path, "w", encoding="utf-8") as f:
        json.dump(mpp_data, f, indent=2, ensure_ascii=False)
    log(f"✅ [SUMBER 2] Berhasil disimpan ke: {src2_path}")
    log(f"   Total program promosi MPP ditemukan: {mpp_data.get('total_records', 0)}")

    # 4. Bangun Komparasi dan Analisis Promo
    log("\n--- [ANALISIS] Membangun Ringkasan Pemetaan Promo ---")
    # Buat lookup map dari MPP (prioritaskan program promosi berstatus aktif)
    ACTIVE_PROMO_STATUSES = {'activated', 'active', 'live', 'ongoing'}
    mpp_lookup = {}
    for p_entry in mpp_data.get("promotions_with_details", []):
        summary = p_entry.get("summary", {})
        detail = p_entry.get("detail", {})
        details_inner = detail.get("details", {}) if isinstance(detail, dict) else {}
        menu_items = details_inner.get("menu_items", [])
        pct_disc = details_inner.get("percentage_discount")
        p_type = details_inner.get("promo_type") or summary.get("promo_type")
        p_name = summary.get("name")
        p_status = summary.get("status")
        is_active = p_status in ACTIVE_PROMO_STATUSES

        for mi in menu_items:
            iid = str(mi.get("id") or "").strip()
            iname = str(mi.get("name") or "").strip().lower()
            info = {
                "promo_id": summary.get("id"),
                "promo_name": p_name,
                "promo_status": p_status,
                "promo_type": p_type,
                "percentage_discount": pct_disc,
                "mpp_original_price": mi.get("price"),
                "mpp_discounted_price": mi.get("discounted_price")
            }
            if iid:
                if iid not in mpp_lookup or (is_active and mpp_lookup[iid].get("promo_status") not in ACTIVE_PROMO_STATUSES):
                    mpp_lookup[iid] = info
            if iname:
                if iname not in mpp_lookup or (is_active and mpp_lookup[iname].get("promo_status") not in ACTIVE_PROMO_STATUSES):
                    mpp_lookup[iname] = info

    # Analisis per item di menu
    comparison_results = []
    if menu_data and isinstance(menu_data, dict):
        for cat in menu_data.get("menus", []):
            cat_name = cat.get("name") or cat.get("category_name")
            for item in cat.get("menu_items", []):
                iid = str(item.get("id") or "").strip()
                iname = str(item.get("name") or "").strip()
                price = float(item.get("price") or 0)
                orig_price = float(item.get("original_price") or item.get("list_price") or 0)
                
                # Cek Sumber 1
                s1_promo = item.get("_decoded_promotion")
                s1_has_promo = bool(s1_promo) or (orig_price > price > 0)

                # Cek Sumber 2 (hanya promo yang aktif)
                s2_promo = mpp_lookup.get(iid) or mpp_lookup.get(iname.lower())
                s2_has_active_promo = bool(s2_promo and s2_promo.get("promo_status") in ACTIVE_PROMO_STATUSES)

                if s1_has_promo or s2_has_active_promo:
                    # Tentukan tipe promo
                    promo_type = "UNKNOWN"
                    discount_display = ""

                    if s2_promo and s2_promo.get("percentage_discount"):
                        promo_type = "PERCENTAGE"
                        discount_display = f"{s2_promo['percentage_discount']}%"
                    elif isinstance(s1_promo, dict) and s1_promo.get("discount_percentage"):
                        promo_type = "PERCENTAGE"
                        discount_display = f"{s1_promo['discount_percentage']}%"
                    elif isinstance(s1_promo, dict) and s1_promo.get("discount_value"):
                        promo_type = "NOMINAL"
                        discount_display = f"Rp {int(float(s1_promo['discount_value'])):,}"
                    elif orig_price > price > 0:
                        diff = orig_price - price
                        pct_calc = (diff / orig_price) * 100
                        if abs(pct_calc - round(pct_calc)) < 0.01 and int(round(pct_calc)) % 5 == 0:
                            promo_type = "PERCENTAGE"
                            discount_display = f"{int(round(pct_calc))}%"
                        else:
                            promo_type = "NOMINAL"
                            discount_display = f"Rp {int(diff):,}"

                    comparison_results.append({
                        "category": cat_name,
                        "item_id": iid,
                        "item_name": iname,
                        "current_price": price,
                        "original_price": orig_price if orig_price > 0 else (s2_promo.get("mpp_original_price") if s2_promo else price),
                        "detected_promo_type": promo_type,
                        "discount_value": discount_display,
                        "source_1_menu_promo": s1_promo,
                        "source_2_mpp_promo": s2_promo
                    })

    # Simpan file perbandingan
    cmp_path = out_dir / f"gofood_promo_comparison_{store_id}.json"
    with open(cmp_path, "w", encoding="utf-8") as f:
        json.dump({
            "target_email": email_target,
            "store_id": store_id,
            "analyzed_at": datetime.utcnow().isoformat(),
            "total_promo_items": len(comparison_results),
            "promo_items": comparison_results
        }, f, indent=2, ensure_ascii=False)
    log(f"✅ [KOMPARASI] File perbandingan disimpan ke: {cmp_path}")
    log(f"   Ditemukan {len(comparison_results)} item yang sedang promo aktif.")

    # Cetak sampel ke konsol
    print("\n" + "=" * 80)
    print(f"RINGKASAN ITEM PROMO DITEMUKAN ({len(comparison_results)} item):")
    print("=" * 80)
    for idx, itm in enumerate(comparison_results[:15]):
        print(f"{idx+1}. [{itm['category']}] {itm['item_name']} (ID: {itm['item_id']})")
        print(f"   Harga Normal : Rp {itm['original_price']:,.0f}")
        print(f"   Harga Jual   : Rp {itm['current_price']:,.0f}")
        print(f"   Tipe Promo   : {itm['detected_promo_type']} ({itm['discount_value']})")
        s1_tag = "Ada" if itm['source_1_menu_promo'] else "Tidak"
        s2_tag = "Ada (" + itm['source_2_mpp_promo']['promo_name'] + ")" if itm['source_2_mpp_promo'] else "Tidak"
        print(f"   Sumber 1 (Menu API) : {s1_tag}")
        print(f"   Sumber 2 (MPP API)  : {s2_tag}")
        print("-" * 50)
    if len(comparison_results) > 15:
        print(f"... dan {len(comparison_results) - 15} item lainnya tercatat di file JSON komparasi.")
    print("=" * 80)

if __name__ == "__main__":
    main()
