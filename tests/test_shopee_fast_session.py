# -*- coding: utf-8 -*-
import unittest
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from shopee.core.session_utils import (
    validate_shopee_token,
    get_fast_shopee_session,
    invalidate_shopee_session,
    resolve_shopee_merchant_id,
    resolve_shopee_outlet_context,
    _IN_MEMORY_SESSION_CACHE,
)
from shopee.core.client import ShopeeClient
from shopee.core.push import _boot_push_client
from core.browser import (
    _acquire_profile_lock,
    _attach_profile_lock,
    _release_profile_lock,
    _session_is_auth_expired,
    _trigger_and_extract_tokens,
)


class TestShopeeFastSession(unittest.TestCase):
    def setUp(self):
        _IN_MEMORY_SESSION_CACHE.clear()

    def tearDown(self):
        _IN_MEMORY_SESSION_CACHE.clear()

    def test_missing_merchant_selector_is_not_treated_as_expired_session(self):
        driver = MagicMock()
        driver.current_url = "https://partner.shopee.co.id/food/dashboard"
        driver.find_elements.return_value = []
        self.assertFalse(_session_is_auth_expired(driver))

    def test_login_url_is_treated_as_expired_session(self):
        driver = MagicMock()
        driver.current_url = "https://partner.shopee.co.id/login"
        self.assertTrue(_session_is_auth_expired(driver))

    def test_profile_lock_serializes_browser_users(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "chrome-profile"
            first_lock = _acquire_profile_lock(profile_dir)
            try:
                with self.assertRaises(TimeoutError):
                    _acquire_profile_lock(profile_dir, timeout=0.05)
            finally:
                _release_profile_lock(first_lock)

            second_lock = _acquire_profile_lock(profile_dir, timeout=0.05)
            _release_profile_lock(second_lock)

    def test_quitting_driver_releases_profile_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "chrome-profile"
            held_lock = _acquire_profile_lock(profile_dir)
            driver = MagicMock()
            _attach_profile_lock(driver, held_lock)

            driver.quit()
            replacement_lock = _acquire_profile_lock(profile_dir, timeout=0.05)
            _release_profile_lock(replacement_lock)

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

    @patch("shopee.core.push.browser.get_session", side_effect=RuntimeError("AUTH_REQUIRED_NO_LOGIN: expired"))
    @patch("shopee.core.push.browser.set_session_file")
    @patch("shopee.core.push.resolve_shopee_session", return_value=Path("session_superfoodapp.json"))
    @patch("shopee.core.push.get_fast_shopee_session", return_value=None)
    def test_push_never_starts_login_when_cached_owner_session_is_invalid(
        self, mock_fast_session, mock_resolve_session, mock_set_session, mock_get_session
    ):
        client, err = _boot_push_client({
            "username": "superfoodapp",
            "store_id": "22459819",
            "merchant_name": "SuperFood",
        })

        self.assertIsNone(client)
        self.assertIn("Push tidak melakukan login ulang", err)
        mock_get_session.assert_called_once()
        self.assertFalse(mock_get_session.call_args.kwargs["allow_login"])
        self.assertFalse(mock_get_session.call_args.kwargs["interactive"])

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

    def test_resolve_shopee_outlet_context(self):
        # 1. Store ID is actually Group ID 23988560 (Bebek Bumbu Hitam Penyetan Rizqna)
        sid, mid = resolve_shopee_outlet_context({"store_id": "23988560"})
        self.assertEqual(sid, "23836720")
        self.assertEqual(mid, "23988560")

        # 2. Store ID is physical store 1456964 (Ayam Geprek Cinta)
        sid, mid = resolve_shopee_outlet_context({"store_id": "1456964"})
        self.assertEqual(sid, "1456964")
        self.assertEqual(mid, "1455780")

        # 3. By Portal Name when store_id is empty
        sid, mid = resolve_shopee_outlet_context({"nama_portal": "[SR] Ayam geprek cinta_"})
        self.assertEqual(sid, "1456964")
        self.assertEqual(mid, "1455780")

    @patch("shopee.core.pull.pd.DataFrame.to_excel")
    @patch("shopee.core.pull.browser.get_session")
    @patch("shopee.core.pull.ShopeeClient")
    def test_extract_shopee_menu_auto_recovery_on_code_1130014(self, mock_client_cls, mock_get_session, mock_to_excel):
        from shopee.core.pull import extract_shopee_menu
        mock_client = MagicMock()
        mock_client.last_code = 1130014
        mock_client.last_error = "merchant authority invalid"

        sample_catalog = [
            {
                "id": "111",
                "name": "Makanan",
                "dishes": [
                    {
                        "id": "222",
                        "name": "Bebek Goreng",
                        "price": "3000000000",
                        "list_price": "3500000000",
                        "available": True,
                        "option_group_count": 0,
                    }
                ]
            }
        ]

        def side_effect_get_dishes(sid):
            if str(sid) == "23988560":
                mock_client.last_code = 1130014
                mock_client.last_error = "merchant authority invalid"
                return []
            mock_client.last_code = 0
            mock_client.last_error = ""
            return sample_catalog

        mock_client.get_store_dishes.side_effect = side_effect_get_dishes
        mock_client_cls.return_value = mock_client

        store_metadata = {
            "store_id": "23988560",
            "nama_portal": "[SR] Bebek bumbu hitam & Ayam crispy rizqna"
        }

        with patch("shopee.core.pull.get_fast_shopee_session", return_value={"shopee_tob_token": "valid_token"}), \
             patch("menu_core.gdrive_service.prepare_and_start_photo_sync", return_value=(None, None)), \
             patch("openpyxl.load_workbook", side_effect=Exception("skip template")), \
             patch("shopee.core.pull.pd.ExcelWriter"):
            success, res_path = extract_shopee_menu(store_metadata, output_dir="/tmp/test_shopee_out")
            self.assertTrue(success)
            self.assertEqual(store_metadata["store_id"], "23836720")
            self.assertEqual(store_metadata["merchant_id"], "23988560")

    @patch("shopee.core.pull.pd.DataFrame.to_excel")
    @patch("shopee.core.pull.ShopeeClient")
    def test_extract_shopee_menu_parallel_modifiers(self, mock_client_cls, mock_to_excel):
        from shopee.core.pull import extract_shopee_menu
        mock_client = MagicMock()
        mock_client.last_code = 0
        mock_client.last_error = ""

        sample_catalog = [
            {
                "id": "100",
                "name": "Kategori A",
                "dishes": [
                    {
                        "id": "dish_1",
                        "name": "Nasi Goreng",
                        "price": "2000000000",
                        "list_price": "2000000000",
                        "available": True,
                        "option_group_count": 1,
                    },
                    {
                        "id": "dish_2",
                        "name": "Mie Goreng",
                        "price": "2500000000",
                        "list_price": "2500000000",
                        "available": True,
                        "option_group_count": 1,
                    }
                ]
            }
        ]
        mock_client.get_store_dishes.return_value = sample_catalog

        def mock_get_option_groups(store_id, dish_ids=None):
            did = dish_ids[0] if dish_ids else ""
            return [
                {
                    "option_group": {
                        "id": f"group_{did}",
                        "name": f"Level Pedas {did}",
                        "select_min": 1,
                        "select_max": 1
                    },
                    "options": [
                        {"id": f"opt_{did}_1", "name": "Sedang", "price": "0", "available": True},
                        {"id": f"opt_{did}_2", "name": "Pedas", "price": "200000000", "available": True}
                    ]
                }
            ]

        mock_client.get_store_option_groups.side_effect = mock_get_option_groups
        mock_client_cls.return_value = mock_client

        store_metadata = {
            "store_id": "1456964",
            "nama_portal": "[SR] Ayam geprek cinta_"
        }

        with patch("shopee.core.pull.get_fast_shopee_session", return_value={"shopee_tob_token": "valid_token"}), \
             patch("menu_core.gdrive_service.prepare_and_start_photo_sync", return_value=(None, None)), \
             patch("openpyxl.load_workbook", side_effect=Exception("skip template")), \
             patch("shopee.core.pull.pd.ExcelWriter"):
            success, res_path = extract_shopee_menu(store_metadata, output_dir="/tmp/test_shopee_out")
            self.assertTrue(success)
            self.assertEqual(mock_client.get_store_option_groups.call_count, 2)

    def test_attempt_dishes_pull_recovery_portal_fallback(self):
        from shopee.core.pull import _attempt_dishes_pull_recovery
        mock_client = MagicMock()
        mock_client.last_code = 1130014
        mock_client.last_error = "merchant authority invalid"

        def mock_get_dishes(sid):
            if str(sid) == "21150787":
                mock_client.last_code = 1130014
                return []
            mock_client.last_code = 0
            return [{"id": "cat_1", "name": "Kategori", "dishes": []}]

        mock_client.get_store_dishes.side_effect = mock_get_dishes
        extra_cookies = {}

        catalogs, sid, mid = _attempt_dishes_pull_recovery(
            client=mock_client,
            store_id="21150787",
            merchant_id="1455780",
            target_name="[SR] Ayam geprek cinta_",
            extra_cookies=extra_cookies
        )

        self.assertEqual(len(catalogs), 1)
        self.assertEqual(sid, "1456964")
        self.assertEqual(mid, "1455780")
        self.assertEqual(extra_cookies["shopee_tob_entity_id"], "1456964")

    def test_attempt_dishes_pull_recovery_get_stores_fallback(self):
        from shopee.core.pull import _attempt_dishes_pull_recovery
        mock_client = MagicMock()
        mock_client.last_code = 1130014
        mock_client.last_error = "merchant authority invalid"

        def mock_get_dishes(sid):
            if str(sid) == "999999":
                return []
            mock_client.last_code = 0
            return [{"id": "cat_1", "name": "Kategori", "dishes": []}]

        mock_client.get_store_dishes.side_effect = mock_get_dishes
        mock_client.get_stores.return_value = [
            {"id": "888888", "name": "Toko Eksklusif Target"}
        ]
        extra_cookies = {}

        catalogs, sid, mid = _attempt_dishes_pull_recovery(
            client=mock_client,
            store_id="999999",
            merchant_id="123456",
            target_name="Toko Eksklusif Target",
            extra_cookies=extra_cookies
        )

        self.assertEqual(len(catalogs), 1)
        self.assertEqual(sid, "888888")
        self.assertEqual(extra_cookies["shopee_tob_entity_id"], "888888")

    def test_attempt_dishes_pull_recovery_no_blind_stores_fallback(self):
        from shopee.core.pull import _attempt_dishes_pull_recovery
        mock_client = MagicMock()
        mock_client.last_code = 1130014
        mock_client.last_error = "merchant authority invalid"
        mock_client.get_store_dishes.return_value = []
        mock_client.get_stores.return_value = [
            {"id": "1456964", "name": "[SR] Ayam geprek cinta_"}
        ]
        extra_cookies = {}

        catalogs, sid, mid = _attempt_dishes_pull_recovery(
            client=mock_client,
            store_id="22459819",
            merchant_id="11511947",
            target_name="SuperFood",
            extra_cookies=extra_cookies
        )

        self.assertEqual(catalogs, [])
        self.assertEqual(sid, "22459819")
        self.assertEqual(mid, "11511947")
        self.assertNotIn("shopee_tob_entity_id", extra_cookies)


if __name__ == "__main__":
    unittest.main()

