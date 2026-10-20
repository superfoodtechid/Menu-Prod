# -*- coding: utf-8 -*-
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from grab.core.grab_api_scraper import parse_menu, GrabAPI


class TestGrabCategoryPromo(unittest.TestCase):
    def test_parse_menu_category_promo_percentage(self):
        sample_menu = {
            "categories": [
                {
                    "categoryID": "CAT_AYAM_CRISPY",
                    "categoryName": "Ayam Crispy Aneka Saos",
                    "items": [
                        {
                            "itemID": "ITEM_BLANGKON_1",
                            "itemName": "Ayam Crispy Geprek Saos Lava",
                            "priceInMin": 2000000,
                            "availableStatus": 1,
                            "description": "Pedas mantap"
                        }
                    ]
                }
            ]
        }

        campaign_promos_map = {
            "category:cat_ayam_crispy": {
                "campaign_id": "CAMP_DISC_30",
                "campaign_name": "Diskon 30% untuk Ayam Crispy Aneka Saos",
                "discount_type": "percentage",
                "discount_value": 30.0,
                "slash_pct": "30%",
                "scope_type": "category"
            }
        }

        items, modifiers = parse_menu(
            menu_data=sample_menu,
            store_id="6-C8JHGRACJVL3JX",
            outlet_name="Ayam Crispy Bakar Cak Blangkon - Lawang",
            shopee_short_name="",
            campaign_promos_map=campaign_promos_map
        )

        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["Item ID"], "ITEM_BLANGKON_1")
        self.assertEqual(it["Harga item sebelum promo (harga coret)"], 20000.0)
        self.assertEqual(it["Harga item setelah promo (harga coret)"], 14000.0)
        self.assertEqual(it["Nominal atau persentase promo (harga coret)"], 6000)
        self.assertEqual(it["Persentase promo"], "30%")
        self.assertEqual(it["Sedang promo"], "Ya")

    def test_parse_menu_category_promo_by_name(self):
        sample_menu = {
            "categories": [
                {
                    "categoryID": "CAT_999",
                    "categoryName": "Lalapan Mantap",
                    "items": [
                        {
                            "itemID": "ITEM_LALAPAN_1",
                            "itemName": "Bebek Goreng Sambal Bawang",
                            "priceInMin": 3000000,
                            "availableStatus": 1
                        }
                    ]
                }
            ]
        }

        campaign_promos_map = {
            "category:lalapan mantap": {
                "campaign_id": "CAMP_DISC_25",
                "campaign_name": "Diskon 25% untuk Lalapan Mantap",
                "discount_type": "percentage",
                "discount_value": 25.0,
                "slash_pct": "25%",
                "scope_type": "category"
            }
        }

        items, _ = parse_menu(
            menu_data=sample_menu,
            store_id="6-C8JHGRACJVL3JX",
            outlet_name="Ayam Crispy Bakar Cak Blangkon - Lawang",
            shopee_short_name="",
            campaign_promos_map=campaign_promos_map
        )

        it = items[0]
        self.assertEqual(it["Harga item sebelum promo (harga coret)"], 30000.0)
        self.assertEqual(it["Harga item setelah promo (harga coret)"], 22500.0)
        self.assertEqual(it["Nominal atau persentase promo (harga coret)"], 7500)
        self.assertEqual(it["Persentase promo"], "25%")
        self.assertEqual(it["Sedang promo"], "Ya")

    def test_fetch_grab_campaign_promotions_category_scope(self):
        scraper = GrabAPI(MagicMock(), "user", "pass")
        scraper.get_advertiser_id = AsyncMock(return_value="ADV_12345")
        scraper.get_active_campaigns = AsyncMock(return_value=([
            {
                "id": "CAMP_CAT_1",
                "name": "Diskon 30% Kategori Ayam",
                "status": "ongoing"
            }
        ], None))

        campaign_detail = {
            "info": {
                "name": "Diskon 30% Kategori Ayam",
                "discount": {
                    "type": "percentage",
                    "discountValue": 30,
                    "discountValueDisplay": "30%"
                },
                "scope": {
                    "type": "category",
                    "objects": [
                        {
                            "objectID": "IDCAT2026100206054916113",
                            "objectName": "Ayam Crispy Aneka Saos"
                        }
                    ]
                }
            }
        }
        scraper.get_campaign_detail = AsyncMock(return_value=(campaign_detail, None))

        promo_map = asyncio.run(scraper.fetch_grab_campaign_promotions(target_store_id="6-C8JHGRACJVL3JX"))

        self.assertIn("category:IDCAT2026100206054916113", promo_map)
        self.assertIn("category:ayam crispy aneka saos", promo_map)
        entry = promo_map["category:IDCAT2026100206054916113"]
        self.assertEqual(entry["discount_value"], 30.0)
        self.assertEqual(entry["slash_pct"], "30%")
        self.assertEqual(entry["scope_type"], "category")


if __name__ == "__main__":
    unittest.main()
