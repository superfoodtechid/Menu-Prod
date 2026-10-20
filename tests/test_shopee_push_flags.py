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
        self.assertIn("Foto gagal diunggah", results[0]["note"])

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["picture"], "")
        self.assertEqual(kwargs["price"], 15000.0)


if __name__ == "__main__":
    unittest.main()

