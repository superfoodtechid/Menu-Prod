# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch

from shopee.core.push_c5 import push_c5_shopee_for_merchant


class TestShopeePushFlags(unittest.TestCase):
    def setUp(self):
        self.mock_dish = {
            "id": 1001,
            "catalog_id": 50,
            "name": "Nasi Goreng Spesial",
            "price": "2000000000",      # Rp 20,000
            "list_price": "2000000000",  # Rp 20,000
            "picture": "id-11134505-nasi-goreng-hash",
            "description": "Nasi goreng lezat",
            "discount_percentage": 0,
            "discount_status": 0,
            "available": True,
        }
        self.catalogs = [
            {
                "id": 50,
                "name": "Makanan Utama",
                "rank": 1,
                "dishes": [self.mock_dish]
            },
            {
                "id": 60,
                "name": "Kategori Baru",
                "rank": 2,
                "dishes": []
            }
        ]

    @patch("shopee.core.push_c5.reorder_categories")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_only_name_change(self, mock_boot, mock_update, mock_reorder):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True

        updates = [
            {
                "item_id": "1001",
                "item_name": "Nasi Goreng Spesial",
                "item_name_new": "Nasi Goreng Jumbo",
                "new_fake_price": 25000,
                "category": "Kategori Baru",
                "photo_link": "https://img.test/new_pic.jpg",
                "description": "Deskripsi Baru",
                "changes": ["NAME_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")

        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        # Name should be updated
        self.assertEqual(kwargs["name"], "Nasi Goreng Jumbo")
        # Category, photo, description, and price must stay at baseline
        self.assertEqual(kwargs["catalog_id"], 50)
        self.assertEqual(kwargs["picture"], "id-11134505-nasi-goreng-hash")
        self.assertEqual(kwargs["description"], "Nasi goreng lezat")
        self.assertEqual(kwargs["price"], 20000.0)
        self.assertEqual(kwargs["list_price"], 20000.0)
        self.assertEqual(kwargs["include_price_mutation"], False)
        # Category reordering should be skipped because only NAME_CHANGE was present
        mock_reorder.assert_not_called()

    @patch("shopee.core.push_c5.reorder_categories")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_only_category_change(self, mock_boot, mock_update, mock_reorder):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True
        mock_reorder.return_value = True

        updates = [
            {
                "item_id": "1001",
                "item_name": "Nasi Goreng Spesial",
                "item_name_new": "Nasi Goreng Beda",
                "new_fake_price": 99000,
                "category": "Kategori Baru",
                "changes": ["CATEGORY_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")

        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        # Category should change to 60
        self.assertEqual(kwargs["catalog_id"], 60)
        # Name and price must stay preserved
        self.assertEqual(kwargs["name"], "Nasi Goreng Spesial")
        self.assertEqual(kwargs["price"], 20000.0)
        self.assertEqual(kwargs["list_price"], 20000.0)
        self.assertEqual(kwargs["include_price_mutation"], False)

    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_no_mutation_skips_api_call(self, mock_boot, mock_update):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_boot.return_value = (mock_client, None)

        updates = [
            {
                "item_id": "1001",
                "item_name": "Nasi Goreng Spesial",
                "changes": []
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertIn("dilewati", results[0]["note"].lower())
        mock_update.assert_not_called()

    @patch("shopee.core.push_c5._process_photo_fallback_queue")
    @patch("shopee.core.push_c5.create_dish")
    @patch("shopee.core.push_c5.resolve_shopee_photo")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_new_item_photo_failure_still_creates_dish(self, mock_boot, mock_resolve_photo, mock_create, mock_fallback_queue):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_boot.return_value = (mock_client, None)

        # Photo upload raises exception (e.g. MMS Extra data error)
        mock_resolve_photo.side_effect = ValueError("Upload foto ke Shopee MMS gagal: Extra data: line 1 column 5")
        mock_create.return_value = {"id": 9999, "name": "Menu Baru"}

        updates = [
            {
                "item_id": "NEW_ITEM",
                "item_name": "Menu Baru",
                "new_fake_price": 15000,
                "category": "Makanan Utama",
                "photo_link": "https://img.test/fail.jpg",
                "changes": ["NEW_ITEM", "PHOTO_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["item_id"], "9999")
        self.assertIn("fallback portal", results[0]["note"])

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["picture"], "")
        self.assertEqual(kwargs["price"], 15000.0)

    def test_clean_dish_payload_omits_pricing_and_promo_keys(self):
        from shopee.core.item.create import _build_dish_payload
        existing = {
            "id": "3148482929458688",
            "name": "Es Jeruk",
            "price": "1800000000",
            "list_price": "1800000000",
            "description": "Segar manis",
            "catalog_id": "3148480950140416",
            "picture": "Es Jeruk",
            "item_discount": {"discount_price": "1500000000"},
            "discount_type": 1,
            "discount_amount": "300000000",
            "flash_sale_dish_discount": {},
            "store_id": "22459819",
            "available": True,
            "rank": 2,
        }

        payload = _build_dish_payload(
            name="Es Jeruk Jumbo",
            existing_dish=existing,
            include_price_mutation=False
        )

        self.assertEqual(payload["name"], "Es Jeruk Jumbo")
        self.assertEqual(payload["id"], "3148482929458688")
        self.assertEqual(payload["price"], "1800000000")
        self.assertEqual(payload["rank"], 2)
        # Verify pricing and promo mutation keys are omitted
        self.assertNotIn("list_price", payload)
        self.assertNotIn("item_discount", payload)
        self.assertNotIn("discount_type", payload)
        self.assertNotIn("discount_amount", payload)
        self.assertNotIn("flash_sale_dish_discount", payload)
        self.assertNotIn("store_id", payload)

    def test_delete_category_api(self):
        from shopee.core.item.delete import delete_category
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "msg": "success"}
        mock_client.session.delete.return_value = mock_resp
        mock_client._seller_headers.return_value = {"Header": "Test"}

        ok = delete_category(mock_client, "STORE_123", "3312666246514176")
        self.assertTrue(ok)
        mock_client.session.delete.assert_called_once_with(
            "https://foody.shopee.co.id/api/seller/store/catalogs/3312666246514176",
            headers={"Header": "Test"},
            timeout=15
        )

    def test_reorder_dishes_api(self):
        from shopee.core.item.edit import reorder_dishes
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "msg": "success"}
        mock_client.session.post.return_value = mock_resp
        mock_client._seller_headers.return_value = {"Header": "Test"}

        ranks = [
            {"id": "3148484252139008", "rank": 1},
            {"id": "3148483850695168", "rank": 2},
            {"id": "3148484649480704", "rank": 3}
        ]
        ok = reorder_dishes(mock_client, "STORE_123", ranks)
        self.assertTrue(ok)
        mock_client.session.post.assert_called_once_with(
            "https://foody.shopee.co.id/api/seller/store/dishes/-/rank",
            json={"ranks": ranks},
            headers={"Header": "Test"},
            timeout=15
        )

    @patch("shopee.core.push_c5.reorder_dishes")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_item_reordering_within_category(self, mock_boot, mock_update, mock_reorder_dishes):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        # Catalog with 3 dishes initially in rank 1, 2, 3
        cat_dishes = [
            {"id": "DISH_1", "catalog_id": 50, "rank": 1, "name": "Item 1", "price": "1000000000", "available": True},
            {"id": "DISH_2", "catalog_id": 50, "rank": 2, "name": "Item 2", "price": "1000000000", "available": True},
            {"id": "DISH_3", "catalog_id": 50, "rank": 3, "name": "Item 3", "price": "1000000000", "available": True},
        ]
        mock_client.get_store_dishes.return_value = [
            {"id": 50, "name": "Makanan Utama", "rank": 1, "dishes": cat_dishes}
        ]
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True
        mock_reorder_dishes.return_value = True

        # C5 specifies updates in new order: DISH_3 first, then DISH_1
        updates = [
            {"item_id": "DISH_3", "item_name": "Item 3", "category": "Makanan Utama", "changes": ["ITEM_ORDER_CHANGE"]},
            {"item_id": "DISH_1", "item_name": "Item 1", "category": "Makanan Utama", "changes": ["ITEM_ORDER_CHANGE"]},
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 2)
        mock_reorder_dishes.assert_called_once()
        _, call_args, call_kwargs = mock_reorder_dishes.mock_calls[0]
        # Target rank should be DISH_3 (rank 1), DISH_1 (rank 2), DISH_2 (rank 3)
        expected_ranks = [
            {"id": "DISH_3", "rank": 1},
            {"id": "DISH_1", "rank": 2},
            {"id": "DISH_2", "rank": 3},
        ]
        self.assertEqual(call_args[2], expected_ranks)

    @patch("shopee.core.push_c5.reorder_categories")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_price_change_direct_push_no_step_push(self, mock_boot, mock_update, mock_reorder):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True

        # Kenaikan harga 1000% dari Rp20.000 ke Rp200.000
        updates = [
            {
                "item_id": "1001",
                "item_name": "Nasi Goreng Spesial",
                "new_fake_price": 200000,
                "changes": ["PRICE_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        # Memastikan update_dish hanya dipanggil 1 kali langsung dengan harga akhir (tanpa step push)
        self.assertEqual(mock_update.call_count, 1)
        _, _, update_kwargs = mock_update.mock_calls[0]
        self.assertEqual(update_kwargs["price"], 200000.0)
        self.assertEqual(update_kwargs["list_price"], 200000.0)
        self.assertTrue(update_kwargs["include_price_mutation"])

    @patch("shopee.core.push_c5.reorder_categories")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_shopee_daily_price_limit_error_translation(self, mock_boot, mock_update, mock_reorder):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_FLAG"
        mock_client.get_store_dishes.return_value = self.catalogs
        mock_client.last_error = "Dish error 1100036: edit times exceed the limit times."
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = False

        updates = [
            {
                "item_id": "1001",
                "item_name": "Nasi Goreng Spesial",
                "new_fake_price": 25000,
                "changes": ["PRICE_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_FLAG", "username": "user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "FAILED")
        self.assertIn("Batas perubahan harga Shopee tercapai", results[0]["error"])
        self.assertIn("maksimal 1x per hari", results[0]["error"])

    def test_calculate_price_steps_returns_single_price(self):
        from shopee.core.push_c5 import calculate_price_steps
        # Shopee tidak menggunakan step push, selalu langsung harga akhir
        self.assertEqual(calculate_price_steps(10000, 50000), [50000])
        self.assertEqual(calculate_price_steps(20000, 15000), [15000])


if __name__ == "__main__":
    unittest.main()

