# -*- coding: utf-8 -*-
import unittest
import json
import time
from unittest.mock import MagicMock, patch

from shopee.core.session_utils import (
    validate_shopee_token,
    get_fast_shopee_session,
    invalidate_shopee_session,
    resolve_shopee_merchant_id,
    _IN_MEMORY_SESSION_CACHE,
)
from shopee.core.client import ShopeeClient
from shopee.core.push import _boot_push_client
from core.browser import _trigger_and_extract_tokens


class TestShopeeFastSession(unittest.TestCase):
    def setUp(self):
        _IN_MEMORY_SESSION_CACHE.clear()

    def tearDown(self):
        _IN_MEMORY_SESSION_CACHE.clear()

    @patch("requests.post")
    def test_validate_shopee_token_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "userName": "superfoodapp",
                "merchantId": 11511947,
                "store_id": 22459819
            }
        }
        mock_post.return_value = mock_resp

        is_valid, user_data = validate_shopee_token("valid_mock_token_123")
        self.assertTrue(is_valid)
        self.assertEqual(user_data.get("userName"), "superfoodapp")
        self.assertEqual(user_data.get("store_id"), 22459819)

    @patch("requests.post")
    def test_validate_shopee_token_expired(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 3004,
            "msg": "auth_failed"
        }
        mock_post.return_value = mock_resp

        is_valid, user_data = validate_shopee_token("expired_token")
        self.assertFalse(is_valid)
        self.assertEqual(user_data, {})

    @patch("shopee.core.session_utils.validate_shopee_token")
    @patch("shopee.core.session_utils.resolve_shopee_session")
    def test_get_fast_shopee_session_valid(self, mock_resolve, mock_validate):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.name = "session_superfoodapp.json"
        mock_path.read_text.return_value = json.dumps({
            "username": "superfoodapp",
            "shopee_tob_token": "token_abc_123",
            "shopee_tob_entity_id": "22459819",
            "extra_cookies": {"csrftoken": "csrf123"}
        })
        mock_resolve.return_value = mock_path
        mock_validate.return_value = (True, {"store_id": "22459819", "merchantId": "11511947"})

        metadata = {"username": "superfoodapp", "store_id": "22459819"}
        sess = get_fast_shopee_session(metadata)

        self.assertIsNotNone(sess)
        self.assertEqual(sess["shopee_tob_token"], "token_abc_123")
        self.assertEqual(sess["shopee_tob_entity_id"], "22459819")
        self.assertEqual(sess["merchant_id"], "11511947")
        self.assertEqual(sess["source"], "fast_cache")

        # Second call should use in-memory cache directly
        mock_validate.reset_mock()
        sess_mem = get_fast_shopee_session(metadata)
        self.assertEqual(sess_mem["shopee_tob_token"], "token_abc_123")
        mock_validate.assert_not_called()

    @patch("shopee.core.session_utils.validate_shopee_token")
    @patch("shopee.core.session_utils.resolve_shopee_session")
    def test_get_fast_shopee_session_expired(self, mock_resolve, mock_validate):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps({
            "username": "superfoodapp",
            "shopee_tob_token": "expired_token"
        })
        mock_resolve.return_value = mock_path
        mock_validate.return_value = (False, {})

        metadata = {"username": "superfoodapp", "store_id": "22459819"}
        sess = get_fast_shopee_session(metadata)
        self.assertIsNone(sess)

    @patch("shopee.core.push.get_fast_shopee_session")
    @patch("core.browser.get_session")
    def test_boot_push_client_fast_path(self, mock_browser_get_session, mock_fast_session):
        mock_fast_session.return_value = {
            "shopee_tob_token": "fast_token_999",
            "shopee_tob_entity_id": "22459819",
            "merchant_id": "11511947",
            "extra_cookies": {"test": "1"}
        }

        metadata = {"username": "superfoodapp", "store_id": "22459819"}
        client, err = _boot_push_client(metadata)

        self.assertEqual(err, "")
        self.assertIsNotNone(client)
        self.assertEqual(client.tob_token, "fast_token_999")
        self.assertEqual(client.entity_id, "22459819")
        mock_browser_get_session.assert_not_called()

    def test_trigger_and_extract_tokens_skips_trigger_page_when_cookie_exists(self):
        mock_driver = MagicMock()
        mock_driver.get_cookies.return_value = [
            {"name": "shopee_tob_token", "value": "existing_dash_token_xyz"},
            {"name": "shopee_tob_entity_id", "value": "11511947"}
        ]

        tok, eid = _trigger_and_extract_tokens(mock_driver)

        self.assertEqual(tok, "existing_dash_token_xyz")
        self.assertEqual(eid, "11511947")
        # Ensure it did NOT delete cookies or navigate to TOKEN_TRIGGER_PAGE
        mock_driver.delete_cookie.assert_not_called()
        mock_driver.get.assert_not_called()

    def test_shopee_client_headers_and_cookies(self):
        client = ShopeeClient(
            tob_token="tok_12345",
            entity_id="1456964",
            merchant_id="1455780",
            username="allvbadmin",
            extra_cookies={"__shopee_token": "abc"}
        )
        headers = client._seller_headers()

        self.assertEqual(headers["x-merchant-token"], "tok_12345")
        self.assertEqual(headers["x-merchant-id"], "1455780")
        self.assertEqual(headers["shopee_tob_entity_id"], "1456964")

        cookie_str = headers["Cookie"]
        self.assertIn("shopee_tob_token=tok_12345", cookie_str)
        self.assertIn("shopee_foody_mid=1455780", cookie_str)
        self.assertIn("shopee_tob_entity_id=1456964", cookie_str)
        self.assertIn("shopee_user_name=allvbadmin", cookie_str)
        self.assertIn("shopee_request_from=partner_web", cookie_str)

    @patch("requests.Session.get")
    def test_shopee_client_records_last_code_and_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 1130002,
            "msg": "need to select a store"
        }
        mock_get.return_value = mock_resp

        client = ShopeeClient(
            tob_token="tok_123",
            entity_id="1456964",
            merchant_id="1455780"
        )
        res = client.get_store_dishes("1456964")

        self.assertEqual(res, [])
        self.assertEqual(client.last_code, 1130002)
        self.assertEqual(client.last_error, "need to select a store")

    def test_resolve_shopee_merchant_id_from_cache(self):
        # 1. By store_id (Ayam Geprek Cinta)
        mid_1 = resolve_shopee_merchant_id({"store_id": "1456964"})
        self.assertEqual(mid_1, "1455780")

        # 2. By portal name
        mid_2 = resolve_shopee_merchant_id({"nama_portal": "[SR] Ayam geprek cinta_"})
        self.assertEqual(mid_2, "1455780")

        # 3. Explicit merchant_id takes precedence
        mid_3 = resolve_shopee_merchant_id({"store_id": "1456964", "merchant_id": "999999"})
        self.assertEqual(mid_3, "999999")

    @patch("shopee.core.pull.browser.get_session")
    @patch("shopee.core.pull.ShopeeClient")
    def test_extract_shopee_menu_does_not_delete_session_on_1130002(self, mock_client_cls, mock_get_session):
        from shopee.core.pull import extract_shopee_menu
        mock_client = MagicMock()
        mock_client.get_store_dishes.return_value = []
        mock_client.last_code = 1130002
        mock_client.last_error = "need to select a store"
        mock_client_cls.return_value = mock_client

        mock_get_session.return_value = {
            "shopee_tob_token": "refreshed_token",
            "shopee_tob_entity_id": "1456964",
            "merchant_id": "1455780"
        }

        with patch("shopee.core.pull.Path.unlink") as mock_unlink:
            store_metadata = {
                "store_id": "1456964",
                "nama_portal": "[SR] Ayam geprek cinta_"
            }
            # Fast-path mock to provide initial session
            with patch("shopee.core.pull.get_fast_shopee_session", return_value={"shopee_tob_token": "valid_token"}):
                extract_shopee_menu(store_metadata, output_dir="/tmp/test_shopee_out")
                # Ensure unlink was NOT called for code 1130002
                mock_unlink.assert_not_called()


if __name__ == "__main__":
    unittest.main()

