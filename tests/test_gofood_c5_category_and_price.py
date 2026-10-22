import asyncio
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
from fastapi import UploadFile

import Gofood.GO.actions._menu_api  # noqa: F401
import main


class TestGofoodC5Fixes(unittest.TestCase):
    def _build_c5_workbook_bytes(self, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Item"
        headers = [
            "Platform",
            "SID",
            "Outlet Name",
            "Category ID",
            "Category",
            "Item ID",
            "Item",
            "Item Name Improvement",
            "Current Fake Price (Rp)",
            "New Fake Price (Rp)",
            "Photo Link",
            "Description",
        ]
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.getvalue()

    def test_price_decrease_is_negative_and_new_category_detected_for_moved_item(self):
        sid = "G-UNITTEST-999"
        baseline_data = {
            "menus": [
                {
                    "id": "v1-cat-old",
                    "common_id": "cat-old-common-1",
                    "name": "Kategori Lama",
                    "menu_items": [
                        {
                            "id": "v1-item-1",
                            "common_id": "item-common-1",
                            "name": "Ayam Bakar Madu",
                            "price": 30000,
                            "image": "https://img.example.com/1.jpg",
                            "description": "Ayam bakar",
                        },
                        {
                            "id": "v1-item-2",
                            "common_id": "item-common-2",
                            "name": "Es Teh Manis",
                            "price": 10000,
                            "image": "",
                            "description": "",
                        },
                    ],
                }
            ]
        }

        wb_bytes = self._build_c5_workbook_bytes([
            [
                "GoFood",
                sid,
                "Outlet Unit Test",
                "",
                "Kategori Baru Spesial",
                "item-common-1",
                "Ayam Bakar Madu",
                "",
                30000,
                22000,
                "https://img.example.com/1.jpg",
                "Ayam bakar",
            ]
        ])

        upload = UploadFile(filename="c5_test.xlsx", file=io.BytesIO(wb_bytes))
        fake_db = MagicMock()

        gofood_api_dir = Path(main.__file__).parent / "Gofood" / "API"
        gofood_api_dir.mkdir(parents=True, exist_ok=True)
        target_baseline_path = gofood_api_dir / f"menu-response-{sid}.json"
        target_baseline_path.write_text(json.dumps(baseline_data), encoding="utf-8")
        try:
            res = asyncio.run(main.parse_c5_endpoint(file=upload, db=fake_db))
        finally:
            if target_baseline_path.exists():
                target_baseline_path.unlink()

        self.assertTrue(res["success"])
        items_by_id = {it["item_id"]: it for it in res["items"]}

        moved_item = items_by_id["item-common-1"]
        # 1. Price decrease must be negative (-26.67%), not +26.67%
        self.assertAlmostEqual(moved_item["price_diff_percent"], -26.67, places=2)
        self.assertTrue(moved_item["price_warning"])
        price_diff_notes = [d["new_val"] for d in moved_item["diff_details"] if d["column"] == "Price"]
        self.assertTrue(any("Penurunan -26.7%" in note for note in price_diff_notes), price_diff_notes)

        # 2. Moved item to new category has NEW_CATEGORY and c5_categories populated
        self.assertIn("NEW_CATEGORY", moved_item["change_types"])
        self.assertEqual(moved_item["c5_categories"], ["Kategori Baru Spesial"])

        # 3. Missing item is marked DELETE_ITEM
        deleted_item = items_by_id["item-common-2"]
        self.assertIn("DELETE_ITEM", deleted_item["change_types"])

    @patch("playwright.sync_api.sync_playwright")
    @patch("src.core.browser_factory.launch_universal_playwright_browser")
    @patch("login_gofood.load_gofood_session", return_value={"access_token": "Bearer fake-token", "cookies": []})
    @patch("menu_core.gofood.fetch_gofood_mpp_promotions", return_value={})
    @patch("Gofood.GO.actions._menu_api.delete_menu_item")
    @patch("Gofood.GO.actions._menu_api.delete_v2_menu_item")
    @patch("Gofood.GO.actions._menu_api.update_v2_menu_item")
    @patch("Gofood.GO.actions._menu_api.create_category")
    @patch("Gofood.GO.actions._menu_api.fetch_menus_v2")
    @patch("Gofood.GO.actions._menu_api.fetch_menus")
    def test_push_gofood_attaches_new_category_to_item_and_deletes_obsolete_category_after_item_move(
        self,
        mock_fetch_menus,
        mock_fetch_menus_v2,
        mock_create_cat,
        mock_update_v2_item,
        mock_delete_v2_item,
        mock_delete_menu_item,
        _mock_mpp,
        _mock_load_session,
        mock_launch_browser,
        mock_sync_pw,
    ):
        call_order = []

        initial_menu = {
            "menus": [
                {
                    "id": "v1-cat-old",
                    "common_id": "cat-old-common-1",
                    "name": "Kategori Lama",
                    "menu_items": [
                        {
                            "id": "v1-item-1",
                            "common_id": "item-common-1",
                            "name": "Ayam Bakar Madu",
                            "price": 30000,
                            "active": True,
                        },
                        {
                            "id": "v1-item-2",
                            "common_id": "item-common-2",
                            "name": "Es Teh Manis",
                            "price": 10000,
                            "active": True,
                        },
                    ],
                }
            ]
        }

        mock_fetch_menus.return_value = initial_menu
        mock_fetch_menus_v2.return_value = {"menus": []}

        def fake_create_category(page, token, group_id, payload, passkey=None):
            call_order.append(("create_category", payload["name"]))
            return {"ok": True, "status": 200, "body": json.dumps({"data": {"common_id": "cat-new-common-99", "name": payload["name"]}})}

        def fake_update_v2_item(page, token, group_id, item_id, payload, passkey=None):
            call_order.append(("update_v2_menu_item", item_id, payload.get("menu_common_id"), payload.get("price")))
            return {"ok": True, "status": 200, "body": "{}"}

        def fake_delete_v2_item(page, token, group_id, item_id, passkey=None):
            call_order.append(("delete_v2_menu_item", item_id))
            return {"ok": True, "status": 200, "body": "{}"}

        def fake_delete_category(page, token, group_id, cat_id, passkey=None):
            call_order.append(("delete_category", cat_id))
            return {"ok": True, "status": 200, "body": "{}"}

        mock_create_cat.side_effect = fake_create_category
        mock_update_v2_item.side_effect = fake_update_v2_item
        mock_delete_v2_item.side_effect = fake_delete_v2_item
        mock_delete_menu_item.side_effect = fake_delete_category

        fake_pw_cm = MagicMock()
        mock_sync_pw.return_value = fake_pw_cm
        fake_browser_obj = MagicMock()
        fake_ctx = MagicMock()
        fake_page = MagicMock()

        def fake_on(event_name, handler):
            if event_name == "request":
                req = MagicMock()
                req.url = "https://api.gojekapi.com/gofood/merchant/v2/menu_groups/11111111-1111-1111-1111-111111111111/menus"
                req.headers = {
                    "authorization": "Bearer fake-token",
                    "x-passkey": "passkey-123",
                }
                handler(req)
                req2 = MagicMock()
                req2.url = "https://api.gojekapi.com/gofood/merchant/v1/restaurants/12345678-1234-1234-1234-1234567890ab/menus"
                req2.headers = {"authorization": "Bearer fake-token"}
                handler(req2)

        fake_page.on.side_effect = fake_on
        fake_ctx.new_page.return_value = fake_page
        fake_browser_obj.new_context.return_value = fake_ctx
        mock_launch_browser.return_value = (fake_browser_obj, None)

        updates = [
            {
                "sid": "G-UNITTEST-999",
                "item_id": "item-common-1",
                "item_name": "Ayam Bakar Madu",
                "category_id": "",
                "category": "Kategori Baru Spesial",
                "baseline_category": "Kategori Lama",
                "current_fake_price": 30000,
                "new_fake_price": 30000,
                "changes": ["NEW_CATEGORY", "CATEGORY_CHANGE"],
                "c5_categories": ["Kategori Baru Spesial"],
            },
            {
                "sid": "G-UNITTEST-999",
                "item_id": "item-common-2",
                "item_name": "Es Teh Manis",
                "category_id": None,
                "category": "Kategori Lama",
                "changes": ["DELETE_ITEM"],
                "c5_categories": ["Kategori Baru Spesial"],
            },
        ]

        cache_path = Path(main.__file__).parent / "Gofood" / "API" / "menu-response-G-UNITTEST-999.json"
        try:
            with patch("main.time.sleep"):
                results = main._push_c5_gofood_for_merchant(
                    email="test@example.com",
                    password="secret",
                    merchant_id="G-UNITTEST-999",
                    updates=updates,
                )
        finally:
            if cache_path.exists():
                cache_path.unlink()

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "SUCCESS" for r in results), results)

        self.assertEqual(call_order[0], ("create_category", "Kategori Baru Spesial"))
        self.assertEqual(call_order[1], ("update_v2_menu_item", "item-common-1", "cat-new-common-99", 30000))
        self.assertEqual(call_order[2], ("delete_v2_menu_item", "item-common-2"))
        self.assertEqual(call_order[3], ("delete_category", "cat-old-common-1"))

    def test_gofood_menu_and_item_ordering_weights_parsed_from_c5(self):
        sid = "G-ORDER-123"
        baseline_data = {
            "menus": [
                {
                    "id": "v1-c1",
                    "common_id": "c1-id",
                    "name": "Minuman",
                    "weight": 1,
                    "menu_items": [
                        {"id": "m1", "common_id": "m1", "name": "Es Jeruk", "price": 8000, "weight": 1},
                        {"id": "m2", "common_id": "m2", "name": "Es Kelapa", "price": 10000, "weight": 2},
                    ],
                },
                {
                    "id": "v1-c2",
                    "common_id": "c2-id",
                    "name": "Makanan",
                    "weight": 2,
                    "menu_items": [
                        {"id": "m3", "common_id": "m3", "name": "Nasi Goreng", "price": 20000, "weight": 1},
                    ],
                },
            ]
        }

        # In C5, user lists "Makanan" first, then "Minuman" (reversing category order)
        # And in Minuman, lists "Es Kelapa" before "Es Jeruk" (reversing item order)
        wb_bytes = self._build_c5_workbook_bytes([
            ["GoFood", sid, "Outlet Test", "", "Makanan", "m3", "Nasi Goreng", "", 20000, 21000, "", ""],
            ["GoFood", sid, "Outlet Test", "", "Minuman", "m2", "Es Kelapa", "", 10000, 11000, "", ""],
            ["GoFood", sid, "Outlet Test", "", "Minuman", "m1", "Es Jeruk", "", 8000, 9000, "", ""],
        ])

        upload = UploadFile(filename="c5_order_test.xlsx", file=io.BytesIO(wb_bytes))
        fake_db = MagicMock()
        gofood_api_dir = Path(main.__file__).parent / "Gofood" / "API"
        gofood_api_dir.mkdir(parents=True, exist_ok=True)
        target_baseline_path = gofood_api_dir / f"menu-response-{sid}.json"
        target_baseline_path.write_text(json.dumps(baseline_data), encoding="utf-8")
        try:
            res = asyncio.run(main.parse_c5_endpoint(file=upload, db=fake_db))
        finally:
            if target_baseline_path.exists():
                target_baseline_path.unlink()

        self.assertTrue(res["success"])
        items_by_id = {it["item_id"]: it for it in res["items"]}

        # Makanan appeared first in C5 -> category_weight = 1, item_weight = 1
        m3_item = items_by_id["m3"]
        self.assertEqual(m3_item["category_weight"], 1)
        self.assertEqual(m3_item["item_weight"], 1)
        self.assertEqual(m3_item["category"], "Makanan")

        # Minuman appeared second in C5 -> category_weight = 2
        # Es Kelapa appeared first in Minuman -> item_weight = 1
        m2_item = items_by_id["m2"]
        self.assertEqual(m2_item["category_weight"], 2)
        self.assertEqual(m2_item["item_weight"], 1)
        self.assertEqual(m2_item["category"], "Minuman")

        # Es Jeruk appeared second in Minuman -> item_weight = 2
        m1_item = items_by_id["m1"]
        self.assertEqual(m1_item["category_weight"], 2)
        self.assertEqual(m1_item["item_weight"], 2)
        self.assertEqual(m1_item["category"], "Minuman")

        # C5 categories preserves the exact C5 sheet sequence
        self.assertEqual(m3_item["c5_categories"], ["Makanan", "Minuman"])

    @patch("playwright.sync_api.sync_playwright")
    @patch("src.core.browser_factory.launch_universal_playwright_browser")
    @patch("login_gofood.load_gofood_session", return_value={"access_token": "Bearer fake-token", "cookies": []})
    @patch("menu_core.gofood.fetch_gofood_mpp_promotions", return_value={})
    @patch("Gofood.GO.actions._menu_api.update_item_weights")
    @patch("Gofood.GO.actions._menu_api.update_category_weights")
    @patch("Gofood.GO.actions._menu_api.update_v2_menu_item")
    @patch("Gofood.GO.actions._menu_api.create_menu_item")
    @patch("Gofood.GO.actions._menu_api.create_category")
    @patch("Gofood.GO.actions._menu_api.update_menu_item")
    @patch("Gofood.GO.actions._menu_api.fetch_menus")
    def test_push_gofood_weights_and_fallback(
        self,
        mock_fetch_menus,
        mock_update_category,
        mock_create_category,
        mock_create_item,
        mock_update_item,
        mock_update_cat_weights,
        mock_update_it_weights,
        _mock_mpp,
        _mock_load_session,
        mock_launch_browser,
        mock_sync_pw,
    ):
        initial_menu = {
            "menus": [
                {
                    "id": "v1-c1",
                    "common_id": "c1-common",
                    "name": "Minuman",
                    "weight": 1,
                    "menu_items": [
                        {
                            "id": "v1-m1",
                            "common_id": "m1-common",
                            "name": "Es Jeruk",
                            "price": 8000,
                            "active": True,
                            "weight": 1,
                        },
                        {
                            "id": "v1-m2",
                            "common_id": "m2-common",
                            "name": "Teh Botol",
                            "price": 5000,
                            "active": True,
                            "weight": 2,
                        }
                    ],
                }
            ]
        }
        mock_fetch_menus.return_value = initial_menu

        item_weight_calls = []
        def fake_update_it_weights(page, token, group_id, cat_id, common_ids, passkey=None):
            item_weight_calls.append((cat_id, list(common_ids)))
            return {"ok": True, "status": 200, "body": "{}"}
        mock_update_it_weights.side_effect = fake_update_it_weights

        category_weight_calls = []
        def fake_update_cat_weights(page, token, group_id, common_ids, passkey=None):
            category_weight_calls.append((group_id, list(common_ids)))
            return {"ok": True, "status": 200, "body": "{}"}
        mock_update_cat_weights.side_effect = fake_update_cat_weights

        category_payloads = []
        def fake_update_category(page, token, group_id, menu_id, payload, passkey=None):
            category_payloads.append((menu_id, payload))
            return {"ok": True, "status": 200, "body": "{}"}
        mock_update_category.side_effect = fake_update_category

        new_cat_payloads = []
        def fake_create_category(page, token, group_id, payload, passkey=None):
            new_cat_payloads.append(payload)
            return {"ok": True, "status": 200, "body": json.dumps({"data": {"common_id": "new-cat-id", "name": payload["name"]}})}
        mock_create_category.side_effect = fake_create_category

        item_patch_calls = []
        def fake_update_v2_item(page, token, group_id, item_id, payload, passkey=None):
            item_patch_calls.append((item_id, dict(payload)))
            # Simulate rejection if weight is included, to verify non-weight fallback
            if "weight" in payload:
                return {"ok": False, "status": 400, "body": json.dumps({"error": "weight not accepted"})}
            return {"ok": True, "status": 200, "body": "{}"}
        mock_update_item.side_effect = fake_update_v2_item

        new_item_calls = []
        def fake_create_item(page, token, group_id, payload, passkey=None):
            new_item_calls.append(dict(payload))
            return {"ok": True, "status": 200, "body": "{}"}
        mock_create_item.side_effect = fake_create_item

        fake_pw_cm = MagicMock()
        mock_sync_pw.return_value = fake_pw_cm
        fake_browser_obj = MagicMock()
        fake_ctx = MagicMock()
        fake_page = MagicMock()

        def fake_on(event_name, handler):
            if event_name == "request":
                req = MagicMock()
                req.url = "https://api.gojekapi.com/gofood/merchant/v2/menu_groups/11111111-1111-1111-1111-111111111111/menus"
                req.headers = {"authorization": "Bearer fake-token", "x-passkey": "passkey-123"}
                handler(req)
                req2 = MagicMock()
                req2.url = "https://api.gojekapi.com/gofood/merchant/v1/restaurants/12345678-1234-1234-1234-1234567890ab/menus"
                req2.headers = {"authorization": "Bearer fake-token"}
                handler(req2)

        fake_page.on.side_effect = fake_on
        fake_ctx.new_page.return_value = fake_page
        fake_browser_obj.new_context.return_value = fake_ctx
        mock_launch_browser.return_value = (fake_browser_obj, None)

        updates = [
            {
                "sid": "G-ORDER-999",
                "item_id": "m1-common",
                "item_name": "Es Jeruk",
                "category_id": "c1-common",
                "category": "Minuman",
                "current_fake_price": 8000,
                "new_fake_price": 9000,
                "category_weight": 2,
                "item_weight": 2,
                "changes": ["PRICE_CHANGE", "ITEM_ORDER_CHANGE"],
                "c5_categories": ["Makanan Baru", "Minuman"],
            },
            {
                "sid": "G-ORDER-999",
                "item_id": "m2-common",
                "item_name": "Teh Botol",
                "category_id": "c1-common",
                "category": "Minuman",
                "current_fake_price": 5000,
                "new_fake_price": 5000,
                "category_weight": 2,
                "item_weight": 1,
                "changes": ["ITEM_ORDER_CHANGE"],
                "c5_categories": ["Makanan Baru", "Minuman"],
            },
            {
                "sid": "G-ORDER-999",
                "item_id": "NEW_1",
                "item_name": "Nasi Ayam Baru",
                "category_id": "",
                "category": "Makanan Baru",
                "current_fake_price": None,
                "new_fake_price": 25000,
                "category_weight": 1,
                "item_weight": 1,
                "changes": ["NEW_ITEM", "NEW_CATEGORY"],
                "c5_categories": ["Makanan Baru", "Minuman"],
            },
        ]

        cache_path = Path(main.__file__).parent / "Gofood" / "API" / "menu-response-G-ORDER-999.json"
        try:
            with patch("main.time.sleep"):
                results = main._push_c5_gofood_for_merchant(
                    email="test@example.com",
                    password="secret",
                    merchant_id="G-ORDER-999",
                    updates=updates,
                )
        finally:
            if cache_path.exists():
                cache_path.unlink()

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["status"] == "SUCCESS" for r in results), results)

        # Verify new category creation received weight = 1
        self.assertTrue(len(new_cat_payloads) > 0)
        self.assertEqual(new_cat_payloads[0]["name"], "Makanan Baru")
        self.assertEqual(new_cat_payloads[0]["weight"], 1)

        # Verify category weights were reordered via PUT /menus/weights
        self.assertTrue(len(category_weight_calls) > 0)
        self.assertEqual(category_weight_calls[0][1], ["new-cat-id", "c1-common"])

        # Verify item weights were reordered via PUT /menus/{cat_id}/menu_items/weights
        self.assertTrue(len(item_weight_calls) > 0)
        self.assertEqual(item_weight_calls[0], ("c1-common", ["m2-common", "m1-common"]))

        # Verify new item creation received weight = 1
        self.assertTrue(len(new_item_calls) > 0)
        self.assertEqual(new_item_calls[0]["name"], "Nasi Ayam Baru")
        self.assertEqual(new_item_calls[0]["weight"], 1)

        # Verify item update tried with weight = 2 first, then succeeded without weight
        self.assertTrue(len(item_patch_calls) >= 2)
        first_call = item_patch_calls[0]
        self.assertEqual(first_call[1]["weight"], 2)
        fallback_call = item_patch_calls[1]
        self.assertNotIn("weight", fallback_call[1])

    def test_c5_category_and_item_order_change_detection(self):
        sid = "G-ORDER-DETECT-1"
        baseline_data = {
            "menus": [
                {
                    "id": "v1-cat-a",
                    "common_id": "cat-common-a",
                    "name": "Kategori A",
                    "weight": 10,
                    "menu_items": [
                        {
                            "id": "v1-item-a1",
                            "common_id": "item-common-a1",
                            "name": "Item A1",
                            "price": 20000,
                            "weight": 1,
                        },
                        {
                            "id": "v1-item-a2",
                            "common_id": "item-common-a2",
                            "name": "Item A2",
                            "price": 25000,
                            "weight": 2,
                        },
                    ],
                },
                {
                    "id": "v1-cat-b",
                    "common_id": "cat-common-b",
                    "name": "Kategori B",
                    "weight": 20,
                    "menu_items": [
                        {
                            "id": "v1-item-b1",
                            "common_id": "item-common-b1",
                            "name": "Item B1",
                            "price": 30000,
                            "weight": 1,
                        },
                    ],
                },
            ]
        }

        # C5 file swaps category order (B first, then A) and swaps item order in A (A2 first, then A1)
        wb_bytes = self._build_c5_workbook_bytes([
            [
                "GoFood",
                sid,
                "Outlet Reorder Test",
                "cat-common-b",
                "Kategori B",
                "item-common-b1",
                "Item B1",
                "",
                30000,
                30000,
                "",
                "",
            ],
            [
                "GoFood",
                sid,
                "Outlet Reorder Test",
                "cat-common-a",
                "Kategori A",
                "item-common-a2",
                "Item A2",
                "",
                25000,
                25000,
                "",
                "",
            ],
            [
                "GoFood",
                sid,
                "Outlet Reorder Test",
                "cat-common-a",
                "Kategori A",
                "item-common-a1",
                "Item A1",
                "",
                20000,
                20000,
                "",
                "",
            ],
        ])

        upload = UploadFile(filename="c5_order_test.xlsx", file=io.BytesIO(wb_bytes))
        fake_db = MagicMock()

        gofood_api_dir = Path(main.__file__).parent / "Gofood" / "API"
        gofood_api_dir.mkdir(parents=True, exist_ok=True)
        target_baseline_path = gofood_api_dir / f"menu-response-{sid}.json"
        target_baseline_path.write_text(json.dumps(baseline_data), encoding="utf-8")
        try:
            res = asyncio.run(main.parse_c5_endpoint(file=upload, db=fake_db))
        finally:
            if target_baseline_path.exists():
                target_baseline_path.unlink()

        self.assertTrue(res["success"])
        items_by_id = {it["item_id"]: it for it in res["items"]}

        # Check Item B1: category weight changed from 2 to 1
        item_b1 = items_by_id["item-common-b1"]
        self.assertTrue(item_b1["is_changed"])
        self.assertTrue(item_b1["changes"]["cat_order_changed"])
        self.assertFalse(item_b1["changes"]["item_order_changed"])
        self.assertIn("CATEGORY_ORDER_CHANGE", item_b1["change_types"])
        self.assertTrue(any(d["column"] == "Urutan Kategori" and "ke-2" in d["old_val"] and "ke-1" in d["new_val"] for d in item_b1["diff_details"]))

        # Check Item A2: category weight changed from 1 to 2, item weight changed from 2 to 1
        item_a2 = items_by_id["item-common-a2"]
        self.assertTrue(item_a2["is_changed"])
        self.assertTrue(item_a2["changes"]["cat_order_changed"])
        self.assertTrue(item_a2["changes"]["item_order_changed"])
        self.assertIn("CATEGORY_ORDER_CHANGE", item_a2["change_types"])
        self.assertIn("ITEM_ORDER_CHANGE", item_a2["change_types"])
        self.assertTrue(any(d["column"] == "Urutan Item" and "ke-2" in d["old_val"] and "ke-1" in d["new_val"] for d in item_a2["diff_details"]))

        # Check Item A1: category weight changed from 1 to 2, item weight changed from 1 to 2
        item_a1 = items_by_id["item-common-a1"]
        self.assertTrue(item_a1["is_changed"])
        self.assertTrue(item_a1["changes"]["cat_order_changed"])
        self.assertTrue(item_a1["changes"]["item_order_changed"])
        self.assertIn("CATEGORY_ORDER_CHANGE", item_a1["change_types"])
        self.assertIn("ITEM_ORDER_CHANGE", item_a1["change_types"])
        self.assertTrue(any(d["column"] == "Urutan Item" and "ke-1" in d["old_val"] and "ke-2" in d["new_val"] for d in item_a1["diff_details"]))

        # Summary check
        self.assertEqual(res["summary"]["order_changes_count"], 3)
        self.assertEqual(res["summary"]["total_changes"], 3)
        self.assertEqual(res["stores"][0]["changed_count"], 3)

    def test_c5_discontinuous_category_order_validation(self):
        sid = "G-DISC-TEST-1"
        baseline_data = {
            "menus": [
                {
                    "id": "v1-c1",
                    "common_id": "c1-id",
                    "name": "Saos Special",
                    "weight": 1,
                    "menu_items": [{"id": "v1-m1", "common_id": "m1-id", "name": "Buldak", "price": 10000}],
                },
                {
                    "id": "v1-c2",
                    "common_id": "c2-id",
                    "name": "Saos",
                    "weight": 2,
                    "menu_items": [
                        {"id": "v1-m2", "common_id": "m2-id", "name": "Cabe", "price": 5000},
                        {"id": "v1-m3", "common_id": "m3-id", "name": "Teriyaki", "price": 5000},
                    ],
                },
                {
                    "id": "v1-c3",
                    "common_id": "c3-id",
                    "name": "Sauce",
                    "weight": 3,
                    "menu_items": [
                        {"id": "v1-m4", "common_id": "m4-id", "name": "Sauce Buldak", "price": 12000},
                        {"id": "v1-m5", "common_id": "m5-id", "name": "Sauce Cabe", "price": 12000},
                        {"id": "v1-m6", "common_id": "m6-id", "name": "Sauce Teriyaki", "price": 12000},
                    ],
                },
                {
                    "id": "v1-c4",
                    "common_id": "c4-id",
                    "name": "Endog",
                    "weight": 4,
                    "menu_items": [
                        {"id": "v1-m7", "common_id": "m7-id", "name": "Ceplok", "price": 4000},
                        {"id": "v1-m8", "common_id": "m8-id", "name": "Dadar", "price": 4000},
                    ],
                },
            ]
        }

        # C5 rows with fragmented/interleaved categories:
        # Row 2: Saos Special
        # Row 3: Saos
        # Row 4: Saos
        # Row 5: Sauce  <-- First occurrence of Sauce
        # Row 6: Endog  <-- First occurrence of Endog
        # Row 7: Sauce  <-- Sauce reappears (DISCONTINUOUS!)
        # Row 8: Sauce
        # Row 9: Endog  <-- Endog reappears (DISCONTINUOUS!)
        wb_bytes = self._build_c5_workbook_bytes([
            ["GoFood", sid, "Outlet Test", "c1-id", "Saos Special", "m1-id", "Buldak", "", 10000, 10000, "", ""],
            ["GoFood", sid, "Outlet Test", "c2-id", "Saos", "m2-id", "Cabe", "", 5000, 5000, "", ""],
            ["GoFood", sid, "Outlet Test", "c2-id", "Saos", "m3-id", "Teriyaki", "", 5000, 5000, "", ""],
            ["GoFood", sid, "Outlet Test", "c3-id", "Sauce", "m4-id", "Sauce Buldak", "", 12000, 12000, "", ""],
            ["GoFood", sid, "Outlet Test", "c4-id", "Endog", "m7-id", "Ceplok", "", 4000, 4000, "", ""],
            ["GoFood", sid, "Outlet Test", "c3-id", "Sauce", "m5-id", "Sauce Cabe", "", 12000, 12000, "", ""],
            ["GoFood", sid, "Outlet Test", "c3-id", "Sauce", "m6-id", "Sauce Teriyaki", "", 12000, 12000, "", ""],
            ["GoFood", sid, "Outlet Test", "c4-id", "Endog", "m8-id", "Dadar", "", 4000, 4000, "", ""],
        ])

        upload = UploadFile(filename="c5_discontinuous_order.xlsx", file=io.BytesIO(wb_bytes))
        fake_db = MagicMock()

        gofood_api_dir = Path(main.__file__).parent / "Gofood" / "API"
        gofood_api_dir.mkdir(parents=True, exist_ok=True)
        target_baseline_path = gofood_api_dir / f"menu-response-{sid}.json"
        target_baseline_path.write_text(json.dumps(baseline_data), encoding="utf-8")
        try:
            res = asyncio.run(main.parse_c5_endpoint(file=upload, db=fake_db))
        finally:
            if target_baseline_path.exists():
                target_baseline_path.unlink()

        self.assertTrue(res["success"])
        # Validation error flag must be True
        self.assertTrue(res["summary"]["has_validation_errors"])
        self.assertTrue(res["summary"]["validation_errors_count"] > 0)

        # Validation error messages must mention 'Sauce' and 'Endog'
        error_msgs = res["summary"]["validation_error_messages"]
        self.assertTrue(any("Sauce" in msg and "terpisah" in msg for msg in error_msgs), error_msgs)
        self.assertTrue(any("Endog" in msg and "terpisah" in msg for msg in error_msgs), error_msgs)

        # Items in discontinuous categories must have INVALID_CATEGORY_ORDER
        items_by_id = {it["item_id"]: it for it in res["items"]}
        item_m5 = items_by_id["m5-id"]
        self.assertFalse(item_m5["is_valid"])
        self.assertIn("INVALID_CATEGORY_ORDER", item_m5["change_types"])
        self.assertIn("terpecah", item_m5["validation_error"])

        item_m8 = items_by_id["m8-id"]
        self.assertFalse(item_m8["is_valid"])
        self.assertIn("INVALID_CATEGORY_ORDER", item_m8["change_types"])
        self.assertIn("terpecah", item_m8["validation_error"])

    def test_trigger_push_c5_discontinuous_category_rejected(self):
        # Verify that trigger_push_c5_job rejects any push request with fragmented/interleaved categories
        from main import C5PushRequest, C5PushItemUpdate
        from fastapi import HTTPException

        req = C5PushRequest(
            platform="gofood",
            selected_sids=["G-DISC-999"],
            updates=[
                C5PushItemUpdate(
                    sid="G-DISC-999",
                    item_id="it-1",
                    item_name="Item 1",
                    category="Sauce",
                    category_id="cat-sauce",
                    changes=["PRICE_CHANGE"],
                ),
                C5PushItemUpdate(
                    sid="G-DISC-999",
                    item_id="it-2",
                    item_name="Item 2",
                    category="Endog",
                    category_id="cat-endog",
                    changes=["PRICE_CHANGE"],
                ),
                C5PushItemUpdate(
                    sid="G-DISC-999",
                    item_id="it-3",
                    item_name="Item 3",
                    category="Sauce",  # Interleaved!
                    category_id="cat-sauce",
                    changes=["PRICE_CHANGE"],
                ),
            ]
        )

        fake_bg = MagicMock()
        fake_db = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            main.trigger_push_c5_job(req, fake_bg, fake_db)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Urutan kategori tidak valid", ctx.exception.detail)
        self.assertIn("Sauce", ctx.exception.detail)

    def test_c5_field_character_length_validation(self):
        sid = "G-LEN-TEST-1"
        baseline_data = {"menus": []}

        # Row 1: Valid lengths (name=60, cat=80, desc=250)
        valid_name = "A" * 60
        valid_cat = "C" * 80
        valid_desc = "D" * 250

        # Row 2: Invalid item name (name=61 chars)
        long_name = "B" * 61

        # Row 3: Invalid category (cat=81 chars)
        long_cat = "E" * 81

        # Row 4: Invalid description (desc=251 chars)
        valid_cat_2 = "G" * 80
        long_desc = "F" * 251

        wb_bytes = self._build_c5_workbook_bytes([
            ["GoFood", sid, "Outlet Test", "", valid_cat, "", valid_name, "", 10000, 10000, "", valid_desc],
            ["GoFood", sid, "Outlet Test", "", valid_cat, "", long_name, "", 10000, 10000, "", ""],
            ["GoFood", sid, "Outlet Test", "", long_cat, "", "Normal Item 2", "", 10000, 10000, "", ""],
            ["GoFood", sid, "Outlet Test", "", valid_cat_2, "", "Normal Item 3", "", 10000, 10000, "", long_desc],
        ])

        upload = UploadFile(filename="c5_length_test.xlsx", file=io.BytesIO(wb_bytes))
        fake_db = MagicMock()

        gofood_api_dir = Path(main.__file__).parent / "Gofood" / "API"
        gofood_api_dir.mkdir(parents=True, exist_ok=True)
        target_baseline_path = gofood_api_dir / f"menu-response-{sid}.json"
        target_baseline_path.write_text(json.dumps(baseline_data), encoding="utf-8")
        try:
            res = asyncio.run(main.parse_c5_endpoint(file=upload, db=fake_db))
        finally:
            if target_baseline_path.exists():
                target_baseline_path.unlink()

        self.assertTrue(res["success"])
        self.assertTrue(res["summary"]["has_validation_errors"])
        self.assertGreaterEqual(res["summary"]["validation_errors_count"], 3)

        items = res["items"]
        # Item 0: valid (name 60, cat 80, desc 250)
        self.assertTrue(items[0]["is_valid"], items[0].get("validation_error"))

        # Item 1: long item name (61 > 60)
        self.assertFalse(items[1]["is_valid"])
        self.assertIn("INVALID_ITEM_NAME_LENGTH", items[1]["change_types"])
        self.assertIn("60 karakter", items[1]["validation_error"])

        # Item 2: long category name (81 > 80)
        self.assertFalse(items[2]["is_valid"])
        self.assertIn("INVALID_CATEGORY_LENGTH", items[2]["change_types"])
        self.assertIn("80 karakter", items[2]["validation_error"])

        # Item 3: long description (251 > 250)
        self.assertFalse(items[3]["is_valid"])
        self.assertIn("INVALID_DESCRIPTION_LENGTH", items[3]["change_types"])
        self.assertIn("250 karakter", items[3]["validation_error"])

    def test_trigger_push_c5_character_length_rejected(self):
        from main import C5PushRequest, C5PushItemUpdate
        from fastapi import HTTPException

        fake_bg = MagicMock()
        fake_db = MagicMock()

        # 1. Reject long item name > 60
        req_name = C5PushRequest(
            platform="gofood",
            selected_sids=["G-TEST-1"],
            updates=[
                C5PushItemUpdate(
                    sid="G-TEST-1",
                    item_id="it-1",
                    item_name="N" * 61,
                    category="Normal Cat",
                    changes=["NAME_CHANGE"],
                )
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            main.trigger_push_c5_job(req_name, fake_bg, fake_db)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("60 karakter", ctx.exception.detail)

        # 2. Reject long category > 80
        req_cat = C5PushRequest(
            platform="gofood",
            selected_sids=["G-TEST-1"],
            updates=[
                C5PushItemUpdate(
                    sid="G-TEST-1",
                    item_id="it-1",
                    item_name="Normal Name",
                    category="C" * 81,
                    changes=["CATEGORY_CHANGE"],
                )
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            main.trigger_push_c5_job(req_cat, fake_bg, fake_db)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("80 karakter", ctx.exception.detail)

        # 3. Reject long description > 250
        req_desc = C5PushRequest(
            platform="gofood",
            selected_sids=["G-TEST-1"],
            updates=[
                C5PushItemUpdate(
                    sid="G-TEST-1",
                    item_id="it-1",
                    item_name="Normal Name",
                    category="Normal Cat",
                    description="D" * 251,
                    changes=["DESCRIPTION_CHANGE"],
                )
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            main.trigger_push_c5_job(req_desc, fake_bg, fake_db)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("250 karakter", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()


