# -*- coding: utf-8 -*-
import unittest
import hashlib
from unittest.mock import MagicMock, patch

from shopee.core.client import ShopeeModifyClient
from shopee.core.item.create import _build_dish_payload
from shopee.core.push_c5 import (
    download_image_bytes,
    resolve_shopee_photo,
    push_c5_shopee_for_merchant,
)


class TestShopeePhotoUpload(unittest.TestCase):
    def test_download_image_bytes_invalid_url(self):
        with self.assertRaises(ValueError):
            download_image_bytes("not_a_valid_url")

    @patch("requests.get")
    def test_download_image_bytes_google_drive(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_get.return_value = mock_resp

        drive_url = "https://drive.google.com/file/d/1shopeePhotoDriveID123/view?usp=sharing"
        content, filename, mime = download_image_bytes(drive_url)

        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(filename, "dish.jpg")
        self.assertEqual(content, mock_resp.content)
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        self.assertIn("https://lh3.googleusercontent.com/d/1shopeePhotoDriveID123=s0", called_url)

    @patch("requests.get")
    def test_download_image_bytes_png(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        mock_resp.headers = {"content-type": "image/png"}
        mock_get.return_value = mock_resp

        url = "https://images.example.com/item.png"
        content, filename, mime = download_image_bytes(url)

        self.assertEqual(mime, "image/png")
        self.assertEqual(filename, "dish.png")
        self.assertEqual(content, mock_resp.content)

    def test_upload_image_bytes_success(self):
        client = ShopeeModifyClient(tob_token="test_token", entity_id="222", username="test_user", merchant_id="111")
        client._preupload_image = MagicMock(return_value={
            "token": "test_token_abc",
            "img_id": "id-11134505-test-pic-hash",
            "upload_domain": "https://up-ws-id.img.susercontent.com"
        })

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        client.session.post = MagicMock(return_value=mock_post_resp)

        img_data = b"fake_image_bytes_data"
        pic_id = client.upload_image_bytes(img_data=img_data, filename="dish.jpg", content_type="image/jpeg")

        self.assertEqual(pic_id, "id-11134505-test-pic-hash")
        client.session.post.assert_called_once()
        call_args = client.session.post.call_args
        self.assertEqual(call_args[0][0], "https://up-ws-id.img.susercontent.com/file/upload")
        self.assertEqual(call_args[1]["params"]["token"], "test_token_abc")
        self.assertEqual(call_args[1]["params"]["img_id"], "id-11134505-test-pic-hash")
        self.assertEqual(call_args[1]["params"]["md5"], hashlib.md5(img_data).hexdigest())

    def test_upload_image_bytes_preupload_failure(self):
        client = ShopeeModifyClient(tob_token="test_token", entity_id="222", username="test_user", merchant_id="111")
        client._preupload_image = MagicMock(return_value=None)
        client.last_error = "Preupload rejected"

        pic_id = client.upload_image_bytes(b"test_bytes")
        self.assertIsNone(pic_id)

    def test_resolve_shopee_photo_cache_and_cdn(self):
        client = MagicMock()
        cache = {"https://example.com/cached.jpg": "id-cached-hash-1"}

        res_cached = resolve_shopee_photo(client, "https://example.com/cached.jpg", cache)
        self.assertEqual(res_cached, "id-cached-hash-1")
        client.upload_image_bytes.assert_not_called()

        cdn_url = "https://down-id.img.susercontent.com/file/id-11134505-822wp-mpyl3mwg1vyk4f"
        res_cdn = resolve_shopee_photo(client, cdn_url, cache)
        self.assertEqual(res_cdn, "id-11134505-822wp-mpyl3mwg1vyk4f")
        self.assertEqual(cache[cdn_url], "id-11134505-822wp-mpyl3mwg1vyk4f")
        client.upload_image_bytes.assert_not_called()

        raw_hash = "id-11134505-822wm-direct-hash"
        res_raw = resolve_shopee_photo(client, raw_hash, cache)
        self.assertEqual(res_raw, raw_hash)
        client.upload_image_bytes.assert_not_called()

    @patch("shopee.core.push_c5.download_image_bytes")
    def test_resolve_shopee_photo_remote_upload(self, mock_download):
        client = MagicMock()
        client.upload_image_bytes.return_value = "id-new-uploaded-hash"
        mock_download.return_value = (b"binary_image_data", "dish.jpg", "image/jpeg")

        cache = {}
        remote_url = "https://my-server.com/photo.jpg"
        res = resolve_shopee_photo(client, remote_url, cache)

        self.assertEqual(res, "id-new-uploaded-hash")
        self.assertEqual(cache[remote_url], "id-new-uploaded-hash")
        mock_download.assert_called_once_with(remote_url)
        client.upload_image_bytes.assert_called_once_with(
            img_data=b"binary_image_data",
            filename="dish.jpg",
            content_type="image/jpeg"
        )

    def test_build_dish_payload_rank_preservation(self):
        existing = {"id": 12345, "rank": 9, "time_for_sales": []}

        payload_explicit_rank = _build_dish_payload(
            name="Nasi Goreng", price=25000, description="", available=True,
            catalog_id=10, rank=3, existing_dish=existing
        )
        self.assertEqual(payload_explicit_rank["rank"], 3)

        payload_default_rank = _build_dish_payload(
            name="Nasi Goreng", price=25000, description="", available=True,
            catalog_id=10, rank=None, existing_dish=existing
        )
        self.assertEqual(payload_default_rank["rank"], 9)

        payload_new_dish = _build_dish_payload(
            name="Es Teh", price=5000, description="", available=True,
            catalog_id=10, rank=None, existing_dish=None
        )
        self.assertEqual(payload_new_dish["rank"], 1)

    @patch("shopee.core.push_c5._boot_push_client")
    @patch("shopee.core.push_c5.resolve_shopee_photo")
    @patch("shopee.core.push_c5.create_dish")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5.reorder_categories")
    def test_push_c5_shopee_photo_and_category_flow(
        self, mock_reorder, mock_update, mock_create, mock_resolve_photo, mock_boot
    ):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_999"
        mock_client.get_store_dishes.return_value = [
            {
                "id": 101,
                "name": "Makanan",
                "rank": 1,
                "dishes": [
                    {
                        "id": 501,
                        "name": "Mie Ayam",
                        "price": 2000000000,
                        "list_price": 2000000000,
                        "picture": "id-old-mie-ayam",
                        "catalog_id": 101,
                        "available": True,
                        "discount_percentage": 0,
                    }
                ]
            },
            {
                "id": 102,
                "name": "Minuman",
                "rank": 2,
                "dishes": []
            }
        ]
        mock_boot.return_value = (mock_client, None)
        mock_resolve_photo.side_effect = lambda c, link, cache: f"hash_of_{link.split('/')[-1]}"
        mock_create.return_value = {"id": 502, "name": "Es Jeruk"}
        mock_update.return_value = True
        mock_reorder.return_value = True

        updates = [
            {
                "item_id": "NEW_ITEM",
                "item_name": "Es Jeruk",
                "new_fake_price": 8000,
                "category": "Minuman",
                "photo_link": "https://img.test/es_jeruk.jpg",
                "changes": ["NEW_ITEM", "PHOTO_CHANGE"]
            },
            {
                "item_id": "501",
                "item_name": "Mie Ayam",
                "item_name_new": "Mie Ayam Bakso",
                "new_fake_price": 25000,
                "category": "Makanan",
                "photo_link": "https://img.test/mie_ayam_bakso.jpg",
                "changes": ["NAME_CHANGE", "PRICE_CHANGE", "PHOTO_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_999", "username": "user1"},
            updates=updates,
            headless=True
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["item_id"], "502")
        self.assertEqual(results[0]["new_photo"], "hash_of_es_jeruk.jpg")

        self.assertEqual(results[1]["status"], "SUCCESS")
        self.assertEqual(results[1]["item_id"], "501")
        self.assertEqual(results[1]["new_photo"], "hash_of_mie_ayam_bakso.jpg")

        mock_create.assert_called_once()
        create_args = mock_create.call_args[1]
        self.assertEqual(create_args["catalog_id"], 102)
        self.assertEqual(create_args["picture"], "hash_of_es_jeruk.jpg")

        mock_update.assert_called_once()
        update_args = mock_update.call_args[1]
        self.assertEqual(update_args["dish_id"], 501)
        self.assertEqual(update_args["name"], "Mie Ayam Bakso")
        self.assertEqual(update_args["picture"], "hash_of_mie_ayam_bakso.jpg")


if __name__ == "__main__":
    unittest.main()
