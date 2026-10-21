# -*- coding: utf-8 -*-
"""Helper untuk manajemen template C5 Excel (O. C5 .xlsx).

Menjamin integritas template C5:
1. Memastikan Baris 2 ('Don't touch row 2') tidak pernah disentuh, ditimpa, atau dihapus.
2. Data menu dan modifier selalu dimulai dari Baris 3.
3. Seluruh tab bawaan (Item ME, Modifier ME, Structure, Pricing, Meaning, Tech Hierarchy, dll) tetap utuh.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

DATA_START_ROW = 3
TEMPLATE_RESERVED_ROW = 2


def get_c5_template_path(base_dir: Optional[Path] = None) -> Path:
    """Mengembalikan path file template C5 yang valid.
    Memprioritaskan 'O. C5 .xlsx' dan fallback ke 'O. C5 Template.xlsx'.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[1]

    primary = base_dir / "O. C5 .xlsx"
    if primary.exists():
        return primary

    fallback = base_dir / "O. C5 Template.xlsx"
    if fallback.exists():
        return fallback

    return primary


def prepare_c5_sheet(sheet) -> None:
    """Membersihkan baris data menu/modifier sebelumnya dari baris 3 ke bawah.
    PENTING: Jangan pernah menghapus baris 2 ('Don't touch row 2') karena menjadi
    acuan rumus ArrayFormula di baris 1.
    """
    if sheet.max_row >= DATA_START_ROW:
        sheet.delete_rows(DATA_START_ROW, sheet.max_row - (DATA_START_ROW - 1))


def get_c5_headers(sheet) -> Dict[str, int]:
    """Mengambil dictionary {nama_header: nomor_kolom} dari baris 1 sheet.
    Hanya mengekstrak nama kolom string murni dan mengabaikan objek ArrayFormula
    agar tidak merusak atau menimpa kolom formula bawaan template.
    """
    headers = {}
    for cell in sheet[1]:
        val = cell.value
        if val is not None and isinstance(val, str):
            clean_val = val.strip()
            if clean_val:
                headers[clean_val] = cell.column
    return headers


def is_c5_reserved_row(row_values) -> bool:
    """Memeriksa apakah suatu baris adalah baris khusus template (Baris 2 'Don't touch row 2')
    sehingga harus dilewati saat membaca data menu.
    """
    if not row_values:
        return True
    first_few = row_values[:5] if isinstance(row_values, (list, tuple)) else [row_values]
    for val in first_few:
        if val is not None and "don't touch" in str(val).lower():
            return True
    return False

