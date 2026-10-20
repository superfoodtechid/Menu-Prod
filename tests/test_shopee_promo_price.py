# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch

from shopee.core.push_c5 import push_c5_shopee_for_merchant
from shopee.core.item.create import _build_dish_payload


class TestShopeePromoPrice(unittest.TestCase):
    def test_build_dish_payload_strike_price(self):
        existing = {
            "id": "DISH_101",
            "name": "Item E",
            "price": "6300000000",
            "list_price": 7000000000,
            "rank": 3,
            "item_discount": {
                "discount_price": "6300000000",
                "discount_percentage": 1000
            }
        }

        # Update strike price (list_price) to 80,000 and price to 72,000
        payload = _build_dish_payload(
            name="Item E",
            price=72000,
            description="Desc E",
            available=True,
            catalog_id=123,
            existing_dish=existing,
            list_price=80000
        )

        self.assertEqual(payload["price"], "7200000000")
        self.assertEqual(payload["list_price"], 8000000000)
        self.assertEqual(payload["item_discount"]["discount_price"], "7200000000")

    @patch("shopee.core.push_c5._boot_push_client")
    @patch("shopee.core.push_c5.update_dish")
    def test_push_c5_shopee_updates_promo_strike_price(self, mock_update, mock_boot):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_001"
        mock_client.get_store_dishes.return_value = [
            {
                "id": 10,
                "name": "Food",
                "dishes": [
                    {
                        "id": "3148484649480704",
                        "catalog_id": "10",
                        "name": "Item E",
                        "price": "6300000000",      # Rp 63,000 (promo selling price)
                        "list_price": "7000000000",  # Rp 70,000 (strike price before discount)
                        "discount_percentage": 1000, # 10%
                        "discount_status": 1,
                        "available": True
                    }
                ]
            }
        ]
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True

        updates = [
            {
                "item_id": "3148484649480704",
                "item_name": "Item E",
                "new_fake_price": 80000, # New strike price: Rp 80,000
                "changes": ["PRICE_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_001", "username": "test_user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["new_price"], 80000.0)

        # Verify update_dish was called with list_price = 80000 and price = 72000 (retained 10% promo)
        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs["dish_id"], 3148484649480704)
        self.assertEqual(kwargs["list_price"], 80000.0)
        self.assertEqual(kwargs["price"], 72000.0)

    @patch("shopee.core.push_c5._boot_push_client")
    @patch("shopee.core.push_c5.update_dish")
    def test_push_c5_shopee_preserves_price_when_price_not_in_changes(self, mock_update, mock_boot):
        mock_client = MagicMock()
        mock_client.entity_id = "STORE_001"
        mock_client.get_store_dishes.return_value = [
            {
                "id": 10,
                "name": "Food",
                "dishes": [
                    {
                        "id": "3148484649480704",
                        "catalog_id": "10",
                        "name": "Item E",
                        "price": "6300000000",      # Rp 63,000
                        "list_price": "7000000000",  # Rp 70,000
                        "discount_percentage": 1000,
                        "discount_status": 1,
                        "available": True
                    }
                ]
            }
        ]
        mock_boot.return_value = (mock_client, None)
        mock_update.return_value = True

        updates = [
            {
                "item_id": "3148484649480704",
                "item_name": "Item E",
                "item_name_new": "Item E Baru",
                "new_fake_price": 85000, # Should be ignored because PRICE_CHANGE is not in changes
                "changes": ["NAME_CHANGE"]
            }
        ]

        results = push_c5_shopee_for_merchant(
            store_metadata={"store_id": "STORE_001", "username": "test_user"},
            updates=updates
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")

        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs["dish_id"], 3148484649480704)
        self.assertEqual(kwargs["name"], "Item E Baru")
        # Ensure prices remain unchanged
        self.assertEqual(kwargs["list_price"], 70000.0)
        self.assertEqual(kwargs["price"], 63000.0)


if __name__ == "__main__":
    unittest.main()
