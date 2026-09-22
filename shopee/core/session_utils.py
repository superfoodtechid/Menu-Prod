# -*- coding: utf-8 -*-
"""
shopee/core/session_utils.py — Resolusi sesi multi-kandidat untuk Shopee Partner.
Mencari berkas sesi dari berbagai kemungkinan kunci (username, phone 628xxx, store_id, merchant_name)
dan menyinkronkan profil Chrome yang cocok.
"""

import os
import re
import json
import shutil
import logging
from pathlib import Path

log = logging.getLogger(__name__)

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DATA_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation" / "data"
SHOPEE_DATA_DIR = WORKSPACE_DIR / "shopee" / "data"
ROOT_DATA_DIR = WORKSPACE_DIR / "data"


def get_cached_phone_map(cache_path: Path) -> dict:
    """Membaca pemetaan store_id -> nomor HP dari CSV master_merchants_cache."""
    phone_map = {}
    if not cache_path.exists():
        return phone_map
    try:
        import csv
        with open(cache_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = (row.get("Store ID") or row.get("store_id") or "").strip()
                p_val = (row.get("No HP Shopee") or row.get("phone") or row.get("username") or "").strip()
                if sid and p_val:
                    phone_map[sid] = p_val
    except Exception as e:
        log.debug(f"Gagal membaca phone map cache: {e}")
    return phone_map


def to_canonical_phone(raw: str) -> str:
    """Mengubah format nomor HP ke standar tunggal kanonikal 628xxx."""
    digits = re.sub(r'[^0-9]', '', str(raw or ""))
    if len(digits) < 8:
        return ""
    if digits.startswith("0"):
        return "62" + digits[1:]
    elif digits.startswith("8"):
        return "62" + digits
    elif digits.startswith("62"):
        return digits
    return "62" + digits


def resolve_shopee_session(store_metadata: dict, base_dir: Path = None) -> Path:
    """
    Mencari file sesi Shopee terbaik dari berbagai candidate key:
    - username
    - canonical phone (628xxx), local phone (08xxx), 8xxx
    - store_id
    - merchant_name / clean profile name
    - mapping CSV dari store_id ke nomor HP
    
    Jika berkas sesi valid ditemukan, disinkronkan juga ke
    AUTOMATION_DATA_DIR / session_{username}.json dan profil Chrome diselaraskan.
    """
    ws = base_dir or WORKSPACE_DIR
    auto_dir = ws / "src" / "shopee-omzet-automation" / "data"
    shopee_dir = ws / "shopee" / "data"
    root_dir = ws / "data"

    for d in [auto_dir, shopee_dir, root_dir]:
        d.mkdir(parents=True, exist_ok=True)

    username = (store_metadata.get("username") or "").strip()
    store_id = str(store_metadata.get("store_id") or "").strip()
    phone = str(store_metadata.get("phone") or "").strip()
    m_name = (store_metadata.get("merchant_name") or store_metadata.get("nama_resto_final") or store_metadata.get("nama_outlet") or "").strip()

    # Lookup phone dari cache jika belum ada
    if not phone and store_id:
        cache_file = ws / "master_merchants_cache.csv"
        p_map = get_cached_phone_map(cache_file)
        phone = p_map.get(store_id, "")

    search_keys = set()
    if username:
        search_keys.add(username)
        search_keys.add(username.lower())
        u_clean = re.sub(r'[^a-zA-Z0-9_]', '_', username).strip('_').lower()
        if u_clean:
            search_keys.add(u_clean)

    if store_id and store_id != "-" and store_id.lower() != "nan":
        search_keys.add(store_id)

    for p_candidate in [phone, username]:
        can_p = to_canonical_phone(p_candidate)
        if can_p:
            search_keys.add(can_p)
            if can_p.startswith("62"):
                search_keys.add("0" + can_p[2:])
                search_keys.add(can_p[2:])

    if m_name and m_name != "-" and m_name.lower() != "nan":
        m_clean = re.sub(r'[^a-zA-Z0-9_]', '_', m_name).strip('_').lower()
        if m_clean:
            search_keys.add(m_clean)

    # Direktori pencarian sesuai prioritas
    search_dirs = [auto_dir, shopee_dir, root_dir]

    found_session_path = None
    found_key = None
    found_data = None

    for k in search_keys:
        fname = f"session_{k}.json"
        for d in search_dirs:
            cand_path = d / fname
            if cand_path.exists():
                try:
                    data = json.loads(cand_path.read_text(encoding="utf-8"))
                    if data and data.get("shopee_tob_token"):
                        found_session_path = cand_path
                        found_key = k
                        found_data = data
                        break
                except Exception:
                    pass
        if found_session_path:
            break

    target_session_file = auto_dir / f"session_{username or 'user'}.json"

    if found_session_path and found_data:
        log.info(f"📂 [SESSION] Berhasil menemukan sesi Shopee dari kunci '{found_key}': {found_session_path}")
        
        # Sinkronkan ke target session_{username}.json di auto_dir jika belum sama
        try:
            if target_session_file.resolve() != found_session_path.resolve():
                target_session_file.write_text(json.dumps(found_data, indent=2), encoding="utf-8")
                log.info(f"🔄 [SESSION] Menyinkronkan data sesi ke {target_session_file}")
        except Exception as sync_err:
            log.warning(f"Gagal menyinkronkan file sesi target: {sync_err}")

        # Sinkronkan profil Chrome jika kandidat memiliki folder profil fisik
        if found_key:
            target_profile_name = f"chrome_profile_{username or 'user'}"
            source_profile_name = f"chrome_profile_{found_key}"
            for pdir in [auto_dir, root_dir, shopee_dir]:
                src_prof = pdir / source_profile_name
                tgt_prof = auto_dir / target_profile_name
                if src_prof.exists() and src_prof.is_dir() and src_prof.resolve() != tgt_prof.resolve():
                    # Periksa apakah tgt_prof kosong atau tidak memiliki database sesi aktif
                    def _has_session_storage(p: Path) -> bool:
                        if not p.exists() or not p.is_dir():
                            return False
                        for sub in ["Default", f"profile_{username}", "shopee_profile"]:
                            if (p / sub / "IndexedDB").exists() or (p / sub / "Local Storage").exists():
                                return True
                        return False

                    if not tgt_prof.exists() or not _has_session_storage(tgt_prof):
                        try:
                            if tgt_prof.exists() or tgt_prof.is_symlink():
                                shutil.rmtree(tgt_prof, ignore_errors=True)
                            try:
                                os.symlink(str(src_prof.resolve()), str(tgt_prof))
                                log.info(f"🔗 [SESSION] Membuat symlink profil Chrome: {tgt_prof} -> {src_prof}")
                            except Exception:
                                shutil.copytree(str(src_prof), str(tgt_prof), dirs_exist_ok=True)
                                log.info(f"📋 [SESSION] Menyalin profil Chrome: {src_prof} -> {tgt_prof}")
                        except Exception as prof_err:
                            log.warning(f"Gagal menyinkronkan folder profil Chrome: {prof_err}")
                    break

        # Kembalikan file sesi yang sebenarnya ditemukan agar Chrome langsung memuat profil owner
        return found_session_path

    log.info(f"ℹ️ [SESSION] Tidak ditemukan sesi tersimpan untuk kunci {sorted(list(search_keys))}. Menggunakan default: {target_session_file}")
    return target_session_file
