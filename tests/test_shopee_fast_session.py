# -*- coding: utf-8 -*-
import unittest
import json
import time
from unittest.mock import MagicMock, patch

from shopee.core.session_utils import (
    validate_shopee_token,
    get_fast_shopee_session,
    invalidate_shopee_session,
    _IN_MEMORY_SESSION_CACHE,
)
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


if __name__ == "__main__":
    unittest.main()
