import sys
import types
import unittest
import re
from unittest.mock import MagicMock

# Create dummy modules for selenium and other heavy packages if not installed
for mod_name in [
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.support",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "pandas",
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    "openpyxl",
    "webdriver_manager",
    "webdriver_manager.chrome",
    "core",
    "core.browser",
]:
    if mod_name not in sys.modules:
        m = MagicMock()
        m.__spec__ = types.SimpleNamespace(submodule_search_locations=[])
        sys.modules[mod_name] = m


class TestShopeePhotoHashValidation(unittest.TestCase):
    def test_is_valid_shopee_image_hash(self):
        from shopee.core.push_c5 import is_valid_shopee_image_hash

        # Valid hashes
        self.assertTrue(is_valid_shopee_image_hash("id-11134505-822wp-mpyl3mwg1vyk4f"))
        self.assertTrue(is_valid_shopee_image_hash("sg-11134201-23030-abcde12345"))
        self.assertTrue(is_valid_shopee_image_hash("d41d8cd98f00b204e9800998ecf8427e"))

        # Invalid strings
        self.assertFalse(is_valid_shopee_image_hash("Es Degan Ijo"))
        self.assertFalse(is_valid_shopee_image_hash("Item A"))
        self.assertFalse(is_valid_shopee_image_hash(""))
        self.assertFalse(is_valid_shopee_image_hash(None))
        self.assertFalse(is_valid_shopee_image_hash("https://down-id.img.susercontent.com/file/id-12345"))

    def test_resolve_shopee_photo_rejects_plain_text(self):
        from shopee.core.push_c5 import resolve_shopee_photo

        client = MagicMock()
        cache = {}

        # Empty link returns ""
        self.assertEqual(resolve_shopee_photo(client, "", cache), "")

        # Plain text name must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            resolve_shopee_photo(client, "Es Degan Ijo", cache)
        self.assertIn("Es Degan Ijo", str(ctx.exception))
        self.assertIn("tidak valid", str(ctx.exception))

        # Valid hash returns hash directly
        valid_hash = "id-11134505-822wp-mpyl3mwg1vyk4f"
        self.assertEqual(resolve_shopee_photo(client, valid_hash, cache), valid_hash)
        self.assertIn(valid_hash, cache)

        # Shopee URL returns extracted hash
        url = "https://down-id.img.susercontent.com/file/id-11134505-822wp-mpyl3mwg1vyk4f"
        self.assertEqual(resolve_shopee_photo(client, url, cache), valid_hash)

    def test_is_drive_folder_link(self):
        def is_drive_folder_link(value):
            value = str(value or "").strip()
            return "drive.google.com" in value.casefold() and bool(
                re.search(r"/folders/[a-zA-Z0-9_-]+|[?&]id=[a-zA-Z0-9_-]+", value)
            )

        self.assertTrue(is_drive_folder_link("https://drive.google.com/drive/folders/15r_B4LWRe9wEiyegLit27YmEQUUbE24S"))
        self.assertTrue(is_drive_folder_link("https://drive.google.com/open?id=15r_B4LWRe9wEiyegLit27YmEQUUbE24S"))
        self.assertTrue(is_drive_folder_link("https://drive.google.com/drive/u/0/folders/1BaLctP2TL3IwLuokdbu64c9Vr-RkHy8_?usp=sharing"))
        self.assertFalse(is_drive_folder_link("Es Degan Ijo"))
        self.assertFalse(is_drive_folder_link("https://example.com/image.png"))
        self.assertFalse(is_drive_folder_link(""))


if __name__ == "__main__":
    unittest.main()
