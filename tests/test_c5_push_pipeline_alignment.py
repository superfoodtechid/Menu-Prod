# -*- coding: utf-8 -*-
import io
import unittest
import openpyxl
from unittest.mock import MagicMock, patch

import main
from main import parse_c5_template_headers
from menu_core.c5_template_helper import (
    DATA_START_ROW,
    TEMPLATE_RESERVED_ROW,
    is_c5_reserved_row,
)
from shopee.core.push_c5 import push_c5_shopee_for_merchant


class TestC5PushPipelineAlignment(unittest.TestCase):
    def test_parse_c5_template_headers_with_formulas(self):
        """Memverifikasi ekstraksi header formula array tanpa menimpa kolom string murni."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Item"
        # Kolom 1..10 string
        ws.cell(1, 1, "OFD")
        ws.cell(1, 2, "Listing Name")
        ws.cell(1, 6, "Category")
        ws.cell(1, 7, "Item ID")
        ws.cell(1, 8, "Item")
        ws.cell(1, 10, "Description")
        ws.cell(1, 26, "Current Fake Price (Rp)")
        ws.cell(1, 27, "Current Real Price (Rp)")
        # Kolom 19, 20 formula helper (tidak boleh menimpa Category dan Item)
        ws.cell(1, 19, '={"Category"; IF(F2:F845="", , LEN(F2:F845))}')
        ws.cell(1, 20, '={"Item"; IF(H2:H845="", , LEN(H2:H845))}')
        # Kolom 32 formula Slash Price
        ws.cell(1, 32, '={"Current Slash Price (%)"; IF(Z2:Z845="", , (Z2:Z845-AA2:AA845)/Z2:Z845)}')
        # Kolom 39 formula New Fake Price
        ws.cell(1, 39, '={\n"New Fake Price (Rp)";\nIF(AK2:AK845="", , AK2:AK845/(1-N(AL2:AL845)))\n}')

        header_map = parse_c5_template_headers(wb)

        # Standard headers
        self.assertEqual(header_map["OFD"], 0)
        self.assertEqual(header_map["Listing Name"], 1)
        self.assertEqual(header_map["Category"], 5)   # col 6 -> index 5
        self.assertEqual(header_map["Item ID"], 6)     # col 7 -> index 6
        self.assertEqual(header_map["Item"], 7)        # col 8 -> index 7
        self.assertEqual(header_map["Description"], 9) # col 10 -> index 9
        # Formula headers
        self.assertEqual(header_map["Current Slash Price (%)"], 31) # col 32 -> index 31
        self.assertEqual(header_map["New Fake Price (Rp)"], 38)     # col 39 -> index 38

    def test_run_push_price_job_preserves_row_2(self):
        """Memverifikasi bahwa run_push_price_job memperbarui harga di baris 3+ tanpa menyentuh baris 2."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Item"
        # Baris 1: Headers
        headers = ["OFD", "Listing Name", "SID", "Item ID", "Current Real Price (Rp)", "Current Fake Price (Rp)"]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(1, c_idx, h)
        # Baris 2: Reserved
        ws.cell(2, 1, "Don't touch row 2")
        ws.cell(2, 4, "")
        ws.cell(2, 5, "")
        # Baris 3: Item 101
        ws.cell(3, 1, "ShopeeFood")
        ws.cell(3, 2, "Outlet A")
        ws.cell(3, 3, "S-001")
        ws.cell(3, 4, "101")
        ws.cell(3, 5, 20000)
        ws.cell(3, 6, 25000)

        # Simulasikan logika update harga pada file
        item_id_idx = headers.index("Item ID") + 1
        price_idx = headers.index("Current Real Price (Rp)") + 1
        fake_price_idx = headers.index("Current Fake Price (Rp)") + 1
        successful_updates = {"101": 30000}

        for row_idx in range(DATA_START_ROW, ws.max_row + 1):
            if is_c5_reserved_row([ws.cell(row=row_idx, column=c).value for c in range(1, 6)]):
                continue
            cell_item_id = str(ws.cell(row=row_idx, column=item_id_idx).value).strip()
            if cell_item_id in successful_updates:
                new_val = successful_updates[cell_item_id]
                ws.cell(row=row_idx, column=fake_price_idx).value = new_val

        # Cek Baris 2 tetap utuh
        self.assertEqual(ws.cell(2, 1).value, "Don't touch row 2")
        self.assertEqual(ws.cell(2, 5).value, "")
        # Cek Baris 3 berhasil diupdate
        self.assertEqual(ws.cell(3, 6).value, 30000)

    def test_shopee_push_c5_skips_reserved_row(self):
        """Memverifikasi bahwa push_c5_shopee_for_merchant mengabaikan baris khusus template."""
        mock_client = MagicMock()
        mock_client.entity_id = "STORE-123"
        mock_client.get_store_dishes.return_value = []

        updates = [
            # Item dari baris template (harus di-skip)
            {
                "item_id": "",
                "item_name": "Don't touch row 2",
                "category": "",
                "new_fake_price": None,
                "changes": []
            },
            # Item riil
            {
                "item_id": "item-999",
                "item_name": "Ayam Goreng",
                "item_name_new": "Ayam Goreng Crispy",
                "category": "Makanan",
                "new_fake_price": 25000,
                "changes": ["NAME_CHANGE"]
            }
        ]

        store_metadata = {"store_id": "STORE-123", "username": "dummy"}
        with patch("shopee.core.push_c5._boot_push_client", return_value=(mock_client, None)), \
             patch("shopee.core.push_c5.update_dish", return_value={"status": "SUCCESS"}):
            results = push_c5_shopee_for_merchant(store_metadata, updates)

        # Hanya 1 item riil yang diproses, baris template dilewati
        processed_names = [r.get("item_name") for r in results]
        self.assertNotIn("Don't touch row 2", processed_names)
        self.assertIn("Ayam Goreng", processed_names)

    def test_trigger_push_c5_job_filters_reserved_row(self):
        """Memverifikasi bahwa endpoint trigger_push_c5_job memfilter baris template sebelum validasi."""
        mock_req = MagicMock()
        mock_req.platform = "shopee"
        mock_req.selected_sids = ["STORE-123"]

        item_reserved = MagicMock()
        item_reserved.item_name = "Don't touch row 2"
        item_reserved.category = ""
        item_reserved.item_id = ""
        item_reserved.changes = []

        item_valid = MagicMock()
        item_valid.item_name = "Kopi Susu"
        item_valid.item_name_new = "Kopi Susu Gula Aren"
        item_valid.category = "Minuman"
        item_valid.category_id = "cat-1"
        item_valid.item_id = "dish-123"
        item_valid.sid = "STORE-123"
        item_valid.changes = ["NAME_CHANGE"]
        item_valid.description = "Kopi nikmat"
        item_valid.new_fake_price = 18000
        item_valid.dict.return_value = {"item_name": "Kopi Susu", "item_id": "dish-123"}

        mock_req.updates = [item_reserved, item_valid]

        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = MagicMock(id="outlet-1")

        fake_bg = MagicMock()

        res_job = main.trigger_push_c5_job(mock_req, fake_bg, fake_db)

        # Pastikan item_reserved sudah difilter keluar dari request.updates
        self.assertEqual(len(mock_req.updates), 1)
        self.assertEqual(mock_req.updates[0].item_name, "Kopi Susu")


if __name__ == '__main__':
    unittest.main()
