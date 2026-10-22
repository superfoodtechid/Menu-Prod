import os
import unittest
from unittest.mock import MagicMock, patch

from menu_core.gdrive_service import (
    _sanitize_name,
    get_or_create_subfolder,
    resolve_menu_foto_folder,
    _download_photo_content_base64,
    sync_menu_photos_via_appscript,
    sync_menu_photos_to_drive,
)


class TestGDrivePhotoSync(unittest.TestCase):

    def test_sanitize_name(self):
        self.assertEqual(_sanitize_name("Ayam / Goreng: Enak*?"), "Ayam Goreng Enak")
        self.assertEqual(_sanitize_name(""), "Unknown")
        self.assertEqual(_sanitize_name(None), "Unknown")
        self.assertEqual(_sanitize_name("  Burger   King  "), "Burger King")

    @patch("menu_core.gdrive_service.dotenv_values")
    def test_resolve_menu_foto_folder_hierarchy(self, mock_dotenv):
        mock_dotenv.return_value = {"GDRIVE_FOLDER_ID": "root123"}
        mock_service = MagicMock()

        mock_service.files().list().execute.side_effect = [
            {"files": [{"id": "owner_folder_id", "name": "PT Rasa"}]},
            {"files": [{"id": "menu_foto_folder_id", "name": "Menu Foto"}]},
            {"files": [{"id": "outlet_folder_id", "name": "ShopeeFood | Ayam Bakar | 12345 | 2026-10-22 10:00"}]},
        ]

        folder_id, folder_url = resolve_menu_foto_folder(
            service=mock_service,
            owner_name="PT Rasa",
            platform="ShopeeFood",
            listing_name="Ayam Bakar",
            sid="12345",
            timestamp_str="2026-10-22 10:00"
        )

        self.assertEqual(folder_id, "outlet_folder_id")
        self.assertEqual(folder_url, "https://drive.google.com/drive/folders/outlet_folder_id")

    @patch("menu_core.gdrive_service.requests.get")
    def test_download_photo_content_base64(self, mock_requests_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-image-bytes"
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_requests_get.return_value = mock_resp

        res = _download_photo_content_base64("Ayam Bakar", "https://cf.shopee.co.id/image.jpg", "dish_1")
        self.assertIsNotNone(res)
        self.assertEqual(res["fileName"], "Ayam Bakar.jpg")
        self.assertIn("fileContent", res)

    @patch("menu_core.gdrive_service.requests.post")
    @patch("menu_core.gdrive_service.requests.get")
    def test_sync_menu_photos_via_appscript(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = b"fake-image"
        mock_get_resp.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "status": "success",
            "folderUrl": "https://drive.google.com/drive/folders/folder_appscript_123",
            "subFolderId": "folder_appscript_123"
        }
        mock_post.return_value = mock_post_resp

        folder_url = sync_menu_photos_via_appscript(
            owner_name="PT Rasa",
            platform="ShopeeFood",
            listing_name="Ayam Bakar",
            sid="12345",
            dishes=[{"item_name": "Ayam Bakar", "photo_url": "https://example.com/img.jpg", "item_id": "1"}],
            timestamp_str="2026-10-22 10:00"
        )
        self.assertEqual(folder_url, "https://drive.google.com/drive/folders/folder_appscript_123")

    @patch("menu_core.gdrive_service.get_drive_service")
    @patch("menu_core.gdrive_service.sync_menu_photos_via_appscript")
    def test_sync_menu_photos_to_drive_uses_appscript_fallback(self, mock_appscript, mock_sa):
        mock_sa.return_value = None
        mock_appscript.return_value = "https://drive.google.com/drive/folders/fallback_url"

        res = sync_menu_photos_to_drive(
            owner_name="Owner",
            platform="ShopeeFood",
            listing_name="Outlet",
            sid="123",
            dishes=[]
        )
        self.assertEqual(res, "https://drive.google.com/drive/folders/fallback_url")
        mock_appscript.assert_called_once()


if __name__ == "__main__":
    unittest.main()
