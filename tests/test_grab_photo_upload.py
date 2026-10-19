import unittest
import asyncio
import base64
from unittest.mock import AsyncMock, patch, MagicMock
from grab.core.grab_api_scraper import GrabAPI
from grab.core.push_c5 import download_and_encode_image


class TestGrabPhotoUpload(unittest.TestCase):
    def test_upload_item_photo_store_level(self):
        """Verify upload_item_photo payload for standard store level."""
        scraper = GrabAPI(AsyncMock(), "user", "pass")
        expected_url = "https://food-cms.grab.com/temporary/item/photo/test_photo.jpeg"
        scraper.call_api = AsyncMock(return_value={"status": 200, "data": {"url": expected_url}})

        res_url, err = asyncio.run(
            scraper.upload_item_photo(
                group_id="MG_123",
                store_id="SID_456",
                photo_b64="dGVzdF9kYXRh",
                photo_type="jpeg",
                is_menu_group=False,
            )
        )

        self.assertEqual(res_url, expected_url)
        self.assertIsNone(err)

        scraper.call_api.assert_called_once()
        call_args = scraper.call_api.call_args
        called_url = call_args[0][0]
        called_headers = call_args[1]["headers"]
        called_body = call_args[1]["body"]

        self.assertIn("/food/merchant/v2/upload-file", called_url)
        self.assertEqual(called_headers["merchantid"], "SID_456")
        self.assertEqual(called_headers["merchantgroupid"], "MG_123")
        self.assertEqual(called_body["file"]["data"], "dGVzdF9kYXRh")
        self.assertEqual(called_body["file"]["type"], "jpeg")
        self.assertEqual(called_body["category"], "menu_item_img")
        self.assertNotIn("menuGroupID", called_body)

    def test_upload_item_photo_menu_group(self):
        """Verify upload_item_photo payload for menu-group level."""
        scraper = GrabAPI(AsyncMock(), "user", "pass")
        expected_url = "https://food-cms.grab.com/temporary/item/photo/test_mg_photo.png"
        scraper.call_api = AsyncMock(return_value={"status": 200, "data": {"url": expected_url}})

        res_url, err = asyncio.run(
            scraper.upload_item_photo(
                group_id="MG_123",
                store_id="SID_456",
                photo_b64="cG5nX2RhdGE=",
                photo_type="png",
                is_menu_group=True,
                menu_group_id="MENU_GROUP_789",
            )
        )

        self.assertEqual(res_url, expected_url)
        self.assertIsNone(err)

        call_args = scraper.call_api.call_args
        called_url = call_args[0][0]
        called_headers = call_args[1]["headers"]
        called_body = call_args[1]["body"]

        self.assertIn("/food/merchant/v1/upload-menu-group-file", called_url)
        self.assertEqual(called_headers["merchantid"], "MENU_GROUP_789")
        self.assertEqual(called_body["menuGroupID"], "MENU_GROUP_789")
        self.assertEqual(called_body["file"]["type"], "png")

    def test_download_and_encode_image_invalid_url(self):
        """Verify that an invalid URL raises ValueError."""
        with self.assertRaises(ValueError):
            download_and_encode_image("invalid_not_a_url")

    @patch("requests.get")
    def test_download_and_encode_image_google_drive(self, mock_get):
        """Verify Google Drive share link is resolved and encoded to base64."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_get.return_value = mock_resp

        drive_url = "https://drive.google.com/file/d/1atOl2Q3oqGivBT5e6-aRMMrhxWypMCqi/view?usp=sharing"
        b64, img_type = download_and_encode_image(drive_url)

        self.assertEqual(img_type, "jpeg")
        self.assertEqual(base64.b64decode(b64), mock_resp.content)
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        self.assertIn("https://lh3.googleusercontent.com/d/1atOl2Q3oqGivBT5e6-aRMMrhxWypMCqi=s0", called_url)


if __name__ == "__main__":
    unittest.main()
