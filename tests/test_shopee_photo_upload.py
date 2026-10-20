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
    _process_photo_fallback_queue,
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

    def test_outlet_model_outlet_name_property(self):
        from menu_core.database import Outlet
        outlet = Outlet(store_id="22459819", merchant_name="Bakso Solo", nama_outlet="Solo Baru", nama_resto_final="Bakso Solo Baru")
        self.assertEqual(outlet.outlet_name, "Bakso Solo Baru")
        self.assertEqual(outlet.nama_listing, "Bakso Solo Baru")

        outlet_fallback = Outlet(store_id="22459819", merchant_name="Bakso Solo")
        self.assertEqual(outlet_fallback.outlet_name, "Bakso Solo")

    @patch("shopee.core.push_c5._process_photo_fallback_queue")
    @patch("shopee.core.push_c5.resolve_shopee_photo")
    @patch("shopee.core.push_c5.create_dish")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_push_c5_queues_fallback_when_api_photo_fails(
        self, mock_boot, mock_update, mock_create, mock_resolve_photo, mock_process_queue
    ):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_888"
        mock_client.get_store_dishes.return_value = [
            {
                "id": 101,
                "name": "Makanan",
                "rank": 1,
                "dishes": [
                    {
                        "id": 601,
                        "name": "Nasi Goreng",
                        "price": 2000000000,
                        "list_price": 2000000000,
                        "picture": "id-old-pic",
                        "catalog_id": 101,
                        "available": True,
                        "discount_percentage": 0,
                    }
                ]
            }
        ]
        mock_boot.return_value = (mock_client, None)
        mock_resolve_photo.side_effect = ValueError("MMS upload failed: HTTP 400")
        mock_create.return_value = {"id": 602, "name": "Mie Goreng"}
        mock_update.return_value = True

        updates = [
            {
                "item_id": "NEW_ITEM",
                "item_name": "Mie Goreng",
                "new_fake_price": 18000,
                "category": "Makanan",
                "photo_link": "https://external.cdn/miegoreng.jpg",
                "changes": ["NEW_ITEM", "PHOTO_CHANGE"]
            },
            {
                "item_id": "601",
                "item_name": "Nasi Goreng Spesial",
                "item_name_new": "Nasi Goreng Spesial",
                "new_fake_price": 22000,
                "category": "Makanan",
                "photo_link": "https://external.cdn/nasgor.jpg",
                "changes": ["NAME_CHANGE", "PHOTO_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_888", "username": "user888"},
            updates=updates,
            headless=True
        )

        self.assertEqual(len(results), 2)
        mock_process_queue.assert_called_once()
        queued_items = mock_process_queue.call_args[0][1]
        self.assertEqual(len(queued_items), 2)
        self.assertEqual(queued_items[0]["dish_id"], "602")
        self.assertEqual(queued_items[0]["photo_link"], "https://external.cdn/miegoreng.jpg")
        self.assertEqual(queued_items[1]["dish_id"], "601")
        self.assertEqual(queued_items[1]["photo_link"], "https://external.cdn/nasgor.jpg")

    @patch("shopee.core.push_c5.edit_dish_upload_image")
    @patch("shopee.core.push_c5.download_image_bytes")
    @patch("shopee.core.push_c5._sync_store_session")
    @patch("shopee.core.push_c5.browser.get_session")
    @patch("shopee.core.push_c5.resolve_shopee_session")
    def test_process_photo_fallback_queue_success(
        self, mock_resolve_session, mock_get_session, mock_sync_session, mock_download, mock_upload_image
    ):
        mock_driver = MagicMock()
        mock_get_session.return_value = {"driver": mock_driver}
        mock_download.return_value = (b"\xff\xd8fakejpeg", "dish.jpg", "image/jpeg")
        mock_upload_image.return_value = True

        res_item = {"item_id": "701", "status": "SUCCESS", "note": "Foto ditandai untuk fallback portal"}
        queue = [
            {
                "dish_id": "701",
                "photo_link": "https://external.cdn/dish.jpg",
                "res_item": res_item,
                "target_name": "Sate Ayam",
                "update_payload": {"item_id": "701"}
            }
        ]

        _process_photo_fallback_queue(
            store_metadata={"store_id": "STORE_777", "username": "user777"},
            queue=queue,
            headless=True
        )

        mock_sync_session.assert_called_once_with(mock_driver, "STORE_777")
        mock_upload_image.assert_called_once()
        upload_call = mock_upload_image.call_args[1]
        self.assertEqual(upload_call["dish_id"], "701")
        self.assertEqual(upload_call["driver"], mock_driver)
        self.assertEqual(upload_call["store_id"], "STORE_777")
        self.assertFalse(upload_call["sync_session"])

        self.assertEqual(res_item["status"], "SUCCESS")
        self.assertIsNone(res_item["error"])
        self.assertEqual(res_item["new_photo"], "Uploaded via portal")
        self.assertIn("Foto berhasil diunggah via portal", res_item["note"])
        mock_driver.quit.assert_called_once()

    @patch("shopee.core.push_c5._process_photo_fallback_queue")
    @patch("shopee.core.push_c5.resolve_shopee_photo")
    @patch("shopee.core.push_c5.update_dish")
    @patch("shopee.core.push_c5._boot_push_client")
    def test_push_c5_queues_fallback_even_when_api_update_fails(
        self, mock_boot, mock_update, mock_resolve_photo, mock_process_queue
    ):
        mock_client = MagicMock()
        mock_client.entity_id = "11511947"
        mock_client.last_error = "merchant authority invalid"
        mock_client.get_store_dishes.return_value = [
            {
                "id": 101,
                "name": "Makanan",
                "dishes": [
                    {
                        "id": 801,
                        "name": "New Item",
                        "price": 2000000000,
                        "list_price": 2000000000,
                        "picture": "id-old-pic",
                        "catalog_id": 101,
                        "available": True,
                    }
                ]
            }
        ]
        mock_boot.return_value = (mock_client, None)
        mock_resolve_photo.side_effect = ValueError("Upload foto ke Shopee MMS gagal: Gagal tanpa pesan error")
        mock_update.return_value = False

        updates = [
            {
                "item_id": "801",
                "item_name": "New Item",
                "photo_link": "https://external.cdn/newitem.jpg",
                "changes": ["PHOTO_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "20093460", "username": "superfoodapp"},
            updates=updates,
            headless=True
        )

        self.assertEqual(mock_client.entity_id, "20093460")
        mock_process_queue.assert_called_once()
        queued_items = mock_process_queue.call_args[0][1]
        self.assertEqual(len(queued_items), 1)
        self.assertEqual(queued_items[0]["dish_id"], "801")
        self.assertEqual(mock_process_queue.call_args[1]["store_id"], "20093460")


if __name__ == "__main__":
    unittest.main()
