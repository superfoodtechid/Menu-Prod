"""
ShopeeFood Platform Adapter
Wraps existing ShopeeModifyClient logic for the unified dashboard.
"""

import io
import pandas as pd

from base_adapter import PlatformAdapter
from shopee.core.item.edit import _boot_client
from shopee.core.client import ShopeeModifyClient


class ShopeeAdapter(PlatformAdapter):
    platform_name = "shopee"

    @property
    def supports_write(self) -> bool:
        return True

    def pull_stores(self, username: str, password: str) -> list[dict]:
        """Pull daftar outlet dari Shopee Partner API."""
        store_metadata = {
            "store_id": "21941677",  # bootstrap store id
            "username": username,
            "password": password,
            "merchant_name": "Bootstrap",
        }
        client, _ = _boot_client(store_metadata, headless=None)
        if not client:
            print("Failed to boot Shopee client for listing stores")
            return []

        stores = client.get_stores()
        if not stores:
            print("No stores returned from Shopee API")
            return []

        result = []
        for store in stores:
            result.append({
                "store_id": str(store.get("id")),
                "merchant_name": store.get("name", ""),
            })
        return result

    def pull_dishes(self, outlet) -> list[dict]:
        """Pull menu data dari Shopee dan normalize ke format standar."""
        store_metadata = {
            "store_id": outlet.store_id,
            "username": outlet.username,
            "password": outlet.password,
            "merchant_name": outlet.merchant_name,
            "nama_resto_final": outlet.merchant_name,
            "nama_outlet": outlet.merchant_name,
            "nama_pendek": outlet.merchant_name,
            "brand": "",
        }

        client, _ = _boot_client(store_metadata, headless=None)
        if not client:
            raise Exception("Failed to boot Shopee client")

        catalogs = client.get_store_dishes()
        if not catalogs:
            raise Exception("No categories returned from Shopee")

        # Normalize ke format standar
        result = []
        for cat in catalogs:
            normalized_cat = {
                "id": str(cat.get("id")),
                "name": cat.get("name", ""),
                "sequence": cat.get("sequence", 0),
                "items": [],
            }
            for dish in cat.get("dishes", []):
                normalized_cat["items"].append({
                    "id": str(dish.get("id")),
                    "name": dish.get("name", ""),
                    "price_rp": float(dish.get("price", 0)) / 100000.0,
                    "description": dish.get("description", ""),
                    "available": bool(dish.get("available")),
                    "show": bool(dish.get("show", True)),
                    "image_url": dish.get("picture", ""),
                    "stock_type": int(dish.get("stock_type", 0)),
                    "stock_limit_current": int(dish.get("stock_limit_current", 0)),
                })
            result.append(normalized_cat)
        return result

    def export_menu(self, outlet) -> tuple:
        """Export menu Shopee sebagai (df_items, df_mods) DataFrames."""
        store_metadata = {
            "store_id": outlet.store_id,
            "username": outlet.username,
            "password": outlet.password,
            "merchant_name": outlet.merchant_name,
            "nama_resto_final": outlet.merchant_name,
            "nama_outlet": outlet.merchant_name,
            "nama_pendek": outlet.merchant_name,
            "brand": "",
        }

        client, _ = _boot_client(store_metadata, headless=None)
        if not client:
            raise Exception("Failed to boot Shopee client")

        catalogs = client.get_store_dishes()
        if not catalogs:
            raise Exception("No categories returned from Shopee")

        all_dishes = []
        dish_ids_with_modifiers = []

        for cat in catalogs:
            cat_name = cat.get("name", "Menu Lainnya")
            for dish in cat.get("dishes", []):
                dish_id = str(dish.get("id"))
                price_raw = dish.get("price", "0")
                list_price_raw = dish.get("list_price", "0")
                price = float(price_raw) / 100000.0
                list_price = float(list_price_raw) / 100000.0 if (list_price_raw and float(list_price_raw) > 0) else price
                discount_pct = dish.get("discount_percentage", 0)

                promo_val = ""
                if discount_pct > 0:
                    promo_val = f"{int(discount_pct / 100)}%"
                elif list_price > price:
                    promo_val = f"{int(round((list_price - price) / list_price * 100))}%"

                dish_info = {
                    "link_outlet": f"https://shopee.co.id/now-food/shop/{outlet.store_id}",
                    "nama_panjang": outlet.merchant_name,
                    "store_id": outlet.store_id,
                    "nama_kategori": cat_name,
                    "nama_item": dish.get("name", ""),
                    "jumlah_terjual": dish.get("sales_volume", 0),
                    "deskripsi_item": dish.get("description", ""),
                    "harga_sebelum_promo": list_price,
                    "harga_setelah_promo": price,
                    "promo": promo_val,
                    "ketersediaan": "Tersedia" if dish.get("available") else "Habis",
                    "link_foto": f"https://down-id.img.susercontent.com/file/{dish.get('picture', '')}" if dish.get("picture") else "",
                    "dish_id": dish_id,
                    "jumlah_modifier_group": 0,
                    "jumlah_modifier": 0,
                }
                all_dishes.append(dish_info)
                if dish.get("option_group_count", 0) > 0:
                    dish_ids_with_modifiers.append(dish_id)

        # Process modifiers
        modifier_rows = []
        for dish_id in dish_ids_with_modifiers:
            dish_obj = next((d for d in all_dishes if d["dish_id"] == dish_id), None)
            if not dish_obj:
                continue

            opt_groups = client.get_store_option_groups(outlet.store_id, dish_ids=[dish_id])
            dish_obj["jumlah_modifier_group"] = len(opt_groups)
            total_modifiers_count = 0

            for group in opt_groups:
                opt_group_info = group.get("option_group", {})
                group_name = opt_group_info.get("name", "").strip()
                select_min = opt_group_info.get("select_min", 0)
                select_max = opt_group_info.get("select_max", 0)
                options = group.get("options", [])
                total_modifiers_count += len(options)
                tipe_modifier = "Pilihan Tunggal" if select_max == 1 else "Pilihan Ganda"

                for opt in options:
                    modifier_rows.append({
                        "link_outlet": dish_obj["link_outlet"],
                        "nama_panjang": outlet.merchant_name,
                        "store_id": outlet.store_id,
                        "nama_item": dish_obj["nama_item"],
                        "nama_modifier_group": group_name,
                        "nama_modifier": opt.get("name", ""),
                        "tipe_modifier": tipe_modifier,
                        "minimal": select_min,
                        "maksimal": select_max,
                        "harga_modifier": float(opt.get("price", "0")) / 100000.0,
                        "ketersediaan_modifier": "Tersedia" if opt.get("available", True) else "Habis",
                    })
            dish_obj["jumlah_modifier"] = total_modifiers_count

        # Build DataFrames
        item_cols = [
            "Link outlet", "Nama panjang", "Store ID",
            "Nama kategori", "Nama item", "Jumlah terjual",
            "Jumlah modifier group", "Jumlah modifier", "Deskripsi item",
            "Harga item sebelum promo", "Harga item setelah promo",
            "Promo", "Ketersediaan item", "Link foto",
        ]
        item_data = []
        for d in all_dishes:
            item_data.append([
                d["link_outlet"], d["nama_panjang"], d["store_id"],
                d["nama_kategori"], d["nama_item"], d["jumlah_terjual"],
                d["jumlah_modifier_group"], d["jumlah_modifier"], d["deskripsi_item"],
                d["harga_sebelum_promo"], d["harga_setelah_promo"],
                d["promo"], d["ketersediaan"], d["link_foto"],
            ])
        df_items = pd.DataFrame(item_data, columns=item_cols)

        mod_cols = [
            "Link outlet", "Nama panjang", "Store ID",
            "Nama item", "Nama modifier group", "Nama modifier",
            "Tipe modifier", "Minimal", "Maksimal",
            "Harga modifier", "Ketersediaan modifier",
        ]
        mod_data = []
        for m in modifier_rows:
            mod_data.append([
                m["link_outlet"], m["nama_panjang"], m["store_id"],
                m["nama_item"], m["nama_modifier_group"], m["nama_modifier"],
                m["tipe_modifier"], m["minimal"], m["maksimal"],
                m["harga_modifier"], m["ketersediaan_modifier"],
            ])
        df_mods = pd.DataFrame(mod_data, columns=mod_cols)
        return df_items, df_mods

    def ping_session(self, outlet) -> dict:
        """Cek apakah session Shopee masih aktif."""
        store_metadata = {
            "store_id": outlet.store_id,
            "username": outlet.username,
            "password": outlet.password,
            "merchant_name": outlet.merchant_name,
            "nama_resto_final": outlet.merchant_name,
            "nama_outlet": outlet.merchant_name,
            "nama_pendek": outlet.merchant_name,
            "brand": "",
        }
        try:
            client, _ = _boot_client(store_metadata, headless=None)
            if not client:
                return {"active": False, "msg": "Client boot failed"}

            url = "https://foody.shopee.co.id/api/seller/store/dishes"
            resp = client.session.get(
                url,
                headers=client._seller_headers(override_entity_id=outlet.store_id),
                timeout=5,
            )
            data = resp.json()
            if data.get("code") == 0:
                return {"active": True, "msg": "Active"}
            else:
                return {"active": False, "msg": data.get("msg", "Session expired")}
        except Exception as e:
            return {"active": False, "msg": str(e)}

    def sync_changes(self, db, outlet, pending_categories, pending_dishes) -> list[str]:
        """Push perubahan lokal ke Shopee via API."""
        from shopee.core.item.create import create_category, create_dish
        from shopee.core.item.edit import update_category, update_dish

        store_metadata = {
            "store_id": outlet.store_id,
            "username": outlet.username,
            "password": outlet.password,
            "merchant_name": outlet.merchant_name,
            "nama_resto_final": outlet.merchant_name,
            "nama_outlet": outlet.merchant_name,
            "nama_pendek": outlet.merchant_name,
            "brand": "",
        }

        client, _ = _boot_client(store_metadata, headless=None)
        if not client:
            return [f"Gagal login/koneksi API Shopee"]

        errors = []

        # Sync categories
        from sqlalchemy import text
        for cat in pending_categories:
            if cat.sync_status == "pending_create":
                new_cat_data = create_category(client, outlet.store_id, cat.name)
                if new_cat_data and "id" in new_cat_data:
                    real_id = str(new_cat_data["id"])
                    old_id = cat.id
                    db.execute(
                        text("UPDATE categories SET id = :new_id, sync_status = 'synced' WHERE id = :old_id"),
                        {"new_id": real_id, "old_id": old_id}
                    )
                    db.execute(
                        text("UPDATE dishes SET category_id = :new_id WHERE category_id = :old_id"),
                        {"new_id": real_id, "old_id": old_id}
                    )
                    db.commit()
                    print(f"  [Sync] Category '{cat.name}' created on Shopee. ID changed from {old_id} to {real_id}")
                else:
                    err = f"Gagal membuat kategori '{cat.name}': {client.last_error}"
                    cat.sync_status = "failed"
                    errors.append(err)
                    db.commit()
            elif cat.sync_status == "pending_update":
                ok = update_category(client, outlet.store_id, cat.id, cat.name)
                if ok:
                    cat.sync_status = "synced"
                else:
                    err = f"Gagal memperbarui kategori '{cat.name}': {client.last_error}"
                    cat.sync_status = "failed"
                    errors.append(err)
                db.commit()

        # Sync category ordering if there were any category changes
        if pending_categories:
            from shopee.core.item.edit import reorder_categories
            all_cats = db.query(Category).filter(Category.store_id == outlet.store_id).order_by(Category.sequence).all()
            ranks_payload = []
            for idx, cat in enumerate(all_cats):
                if not cat.id.startswith("temp_") and cat.sync_status == "synced":
                    ranks_payload.append({
                        "id": cat.id,
                        "rank": idx + 1
                    })
            if ranks_payload:
                print(f"  [Sync] Reordering categories on Shopee: {ranks_payload}")
                ok = reorder_categories(client, outlet.store_id, ranks_payload)
                if not ok:
                    errors.append(f"Gagal mengatur urutan kategori di Shopee: {client.last_error}")

        # Sync dishes
        for dish in pending_dishes:
            if dish.sync_status == "pending_create":
                res = create_dish(
                    client=client,
                    store_id=outlet.store_id,
                    catalog_id=int(dish.category_id),
                    name=dish.name,
                    price=dish.price_rp,
                    description=dish.description or "",
                    available=dish.available,
                )
                if res:
                    real_id = str(res.get("id", ""))
                    if real_id:
                        old_id = dish.id
                        db.execute(
                            text("UPDATE dishes SET id = :new_id, sync_status = 'synced' WHERE id = :old_id"),
                            {"new_id": real_id, "old_id": old_id}
                        )
                        db.commit()
                        print(f"  [Sync] Dish '{dish.name}' created on Shopee. ID changed from {old_id} to {real_id}")
                    else:
                        dish.sync_status = "failed"
                        errors.append(f"Gagal memproses ID menu baru '{dish.name}'")
                        db.commit()
                else:
                    dish.sync_status = "failed"
                    errors.append(f"Gagal membuat menu '{dish.name}': {client.last_error}")
                    db.commit()
            elif dish.sync_status == "pending_metadata":
                ok = update_dish(
                    client=client,
                    store_id=outlet.store_id,
                    catalog_id=int(dish.category_id),
                    dish_id=int(dish.id),
                    name=dish.name,
                    price=dish.price_rp,
                    description=dish.description or "",
                    available=dish.available,
                )
                if ok:
                    dish.sync_status = "synced"
                else:
                    dish.sync_status = "failed"
                    errors.append(f"Gagal memperbarui menu '{dish.name}': {client.last_error}")
                db.commit()

        return errors
