import unittest
import asyncio
from unittest.mock import AsyncMock
from grab.core.grab_api_scraper import GrabAPI


class TestGrabC5SortOrder(unittest.TestCase):
    def test_grab_category_sort_order_descending(self):
        """Verify that sort_categories builds a descending sortOrder payload."""
        scraper = GrabAPI(AsyncMock(), "user", "pass")
        scraper.call_api = AsyncMock(return_value={"status": 200, "data": {}})

        target_cat_ids = ["IDCAT_TOP", "IDCAT_MID", "IDCAT_BOT"]
        res, err = asyncio.run(scraper.sort_categories("MG1", "SID1", target_cat_ids))
        self.assertTrue(res)
        self.assertIsNone(err)

        call_args = scraper.call_api.call_args
        body = call_args[1]["body"]
        sorts = body["sectionSorts"][0]["sorts"]
        self.assertEqual(len(sorts), 3)
        # In Grab, top element has highest sortOrder, bottom has 1
        self.assertEqual(sorts[0], {"resourceID": "IDCAT_TOP", "sortOrder": 3})
        self.assertEqual(sorts[1], {"resourceID": "IDCAT_MID", "sortOrder": 2})
        self.assertEqual(sorts[2], {"resourceID": "IDCAT_BOT", "sortOrder": 1})

    def test_grab_item_sort_order_descending(self):
        """Verify that sort_items builds a descending sortOrder payload."""
        scraper = GrabAPI(AsyncMock(), "user", "pass")
        scraper.call_api = AsyncMock(return_value={"status": 200, "data": {}})

        target_item_ids = ["ITEM_1", "ITEM_2", "ITEM_3", "ITEM_4"]
        res, err = asyncio.run(scraper.sort_items("MG1", "SID1", "CAT1", target_item_ids))
        self.assertTrue(res)
        self.assertIsNone(err)

        call_args = scraper.call_api.call_args
        body = call_args[1]["body"]
        sorts = body["sorts"]
        self.assertEqual(len(sorts), 4)
        self.assertEqual(sorts[0], {"resourceID": "ITEM_1", "sortOrder": 4})
        self.assertEqual(sorts[1], {"resourceID": "ITEM_2", "sortOrder": 3})
        self.assertEqual(sorts[2], {"resourceID": "ITEM_3", "sortOrder": 2})
        self.assertEqual(sorts[3], {"resourceID": "ITEM_4", "sortOrder": 1})

    def test_category_id_priority_over_name_in_resolution(self):
        """Verify that Category ID provided in C5 takes priority when category name is changed."""
        categories = [
            {"categoryID": "IDCAT_1", "name": "Old Category Name", "sortOrder": 10},
            {"categoryID": "IDCAT_2", "name": "Minuman", "sortOrder": 5},
        ]
        cat_map = {"old category name": "IDCAT_1", "minuman": "IDCAT_2"}
        cat_obj_map = {"IDCAT_1": categories[0], "IDCAT_2": categories[1]}

        valid_grab_cat_ids = {"IDCAT_1", "IDCAT_2"}
        updates = [
            {"category": "Nama Kategori Baru", "category_id": "IDCAT_1"},
            {"category": "Minuman", "category_id": "IDCAT_2"},
        ]

        c5_name_to_cid = {}
        for upd in updates:
            c_name = (upd.get("category") or "").strip().casefold()
            c_id = str(upd.get("category_id") or "").strip()
            if c_name and c_id and c_id in valid_grab_cat_ids and c_name not in c5_name_to_cid:
                c5_name_to_cid[c_name] = c_id

        ordered_c5_cat_names = ["Nama Kategori Baru", "Minuman"]
        target_cat_ids = []
        seen_cat_ids = set()
        for c_name in ordered_c5_cat_names:
            c_key = (c_name or "").strip().casefold()
            cid = c5_name_to_cid.get(c_key) or cat_map.get(c_key)
            if not cid and c_name in valid_grab_cat_ids:
                cid = c_name
            if cid and str(cid) not in seen_cat_ids:
                target_cat_ids.append(str(cid))
                seen_cat_ids.add(str(cid))

        self.assertEqual(target_cat_ids, ["IDCAT_1", "IDCAT_2"])


if __name__ == "__main__":
    unittest.main()
