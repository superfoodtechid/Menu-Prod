import os
import re
import json
import base64
import logging
import io
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any, Tuple
from dotenv import dotenv_values

logger = logging.getLogger("FoodMasterAPI.GDrivePhotoSync")

DEFAULT_ROOT_FOLDER_ID = "14EFVOjND6brFT6BKdXu5dWJBErbSMqie"
DEFAULT_APPSCRIPT_URL = ""
SCOPES = ["https://www.googleapis.com/auth/drive"]


def _sanitize_name(name: str) -> str:
    """Sanitize folder or file name for filesystem and Drive safe naming."""
    if not name:
        return "Unknown"
    clean = re.sub(r'[\\/*?:"<>|]', '', str(name)).strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean or "Unknown"


# =====================================================================
# Google Drive Service Account Implementation
# =====================================================================

def get_drive_service() -> Optional[Any]:
    """
    Initialize Google Drive v3 client from Service Account credentials.
    Supports:
    1. GDRIVE_SERVICE_ACCOUNT_KEY (raw JSON string or base64 encoded string in .env)
    2. GDRIVE_SERVICE_ACCOUNT_JSON (path to .json file)
    3. GOOGLE_APPLICATION_CREDENTIALS (env var path)
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        env_vals = dotenv_values()
        sa_key_raw = (
            env_vals.get("GDRIVE_SERVICE_ACCOUNT_KEY")
            or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        )
        sa_json_path = (
            env_vals.get("GDRIVE_SERVICE_ACCOUNT_JSON")
            or os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )

        creds = None
        if sa_key_raw and sa_key_raw.strip():
            content = sa_key_raw.strip()
            if not content.startswith("{") and len(content) > 20:
                try:
                    decoded = base64.b64decode(content).decode("utf-8")
                    if decoded.strip().startswith("{"):
                        content = decoded.strip()
                except Exception:
                    pass
            try:
                info = json.loads(content)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=SCOPES
                )
            except Exception as e_json:
                logger.warning(f"Failed parsing GDRIVE_SERVICE_ACCOUNT_KEY JSON: {e_json}")

        if not creds and sa_json_path:
            full_path = os.path.expanduser(sa_json_path.strip())
            if not os.path.isabs(full_path):
                full_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    full_path
                )
            if os.path.exists(full_path):
                creds = service_account.Credentials.from_service_account_file(
                    full_path, scopes=SCOPES
                )
            else:
                logger.warning(f"GDRIVE_SERVICE_ACCOUNT_JSON file not found at: {full_path}")

        if not creds:
            return None

        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.warning(f"Could not build Google Drive service: {exc}")
        return None


def get_or_create_subfolder(service, parent_id: str, folder_name: str) -> Optional[str]:
    """Find an existing folder under parent_id, or create a new one."""
    clean_name = _sanitize_name(folder_name)
    escaped_name = clean_name.replace("'", "\\'")
    try:
        query = (
            f"'{parent_id}' in parents and name = '{escaped_name}' "
            f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        response = service.files().list(
            q=query,
            fields="files(id, name)",
            spaces="drive",
            pageSize=10
        ).execute()
        files = response.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": clean_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder.get("id")
    except Exception as exc:
        logger.warning(f"Failed to get_or_create_subfolder '{folder_name}' under '{parent_id}': {exc}")
        return None


def ensure_folder_public_reader(service, folder_id: str):
    """Grant anyone with link reader access to the folder."""
    try:
        service.permissions().create(
            fileId=folder_id,
            body={"role": "reader", "type": "anyone"},
            fields="id"
        ).execute()
    except Exception as exc:
        logger.debug(f"Permission create warning for folder {folder_id}: {exc}")


def resolve_menu_foto_folder(
    service,
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    timestamp_str: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Creates or resolves the hierarchical Drive folder using Service Account."""
    env_vals = dotenv_values()
    root_folder_id = (
        env_vals.get("GDRIVE_FOLDER_ID")
        or env_vals.get("GDRIVE_PARENT_FOLDER_ID")
        or os.getenv("GDRIVE_FOLDER_ID")
        or os.getenv("GDRIVE_PARENT_FOLDER_ID")
        or DEFAULT_ROOT_FOLDER_ID
    )

    clean_owner = _sanitize_name(owner_name or "Default Owner")
    clean_platform = _sanitize_name(platform or "Platform")
    clean_listing = _sanitize_name(listing_name or "Outlet")
    clean_sid = _sanitize_name(sid or "SID")

    if not timestamp_str:
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        timestamp_str = now_wib.strftime("%Y-%m-%d %H:%M")

    # 1. Level 1: {nama owner}
    owner_folder_id = get_or_create_subfolder(service, root_folder_id, clean_owner)
    if not owner_folder_id:
        return None, None

    # 2. Level 2: Menu Foto
    menu_foto_folder_id = get_or_create_subfolder(service, owner_folder_id, "Menu Foto")
    if not menu_foto_folder_id:
        return None, None

    # 3. Level 3: Platform | Listing Name | SID | YYYY-MM-DD HH:MM
    target_folder_name = f"{clean_platform} | {clean_listing} | {clean_sid} | {timestamp_str}"
    outlet_folder_id = get_or_create_subfolder(service, menu_foto_folder_id, target_folder_name)
    if not outlet_folder_id:
        return None, None

    ensure_folder_public_reader(service, outlet_folder_id)

    folder_url = f"https://drive.google.com/drive/folders/{outlet_folder_id}"
    return outlet_folder_id, folder_url


def _download_and_upload_single_photo_sa(
    service,
    folder_id: str,
    item_name: str,
    photo_url: str,
    item_id: str = ""
) -> bool:
    """Download image bytes from CDN and upload to Google Drive folder via Service Account."""
    from googleapiclient.http import MediaIoBaseUpload

    if not photo_url or not str(photo_url).strip().startswith(("http://", "https://")):
        return False

    clean_name = _sanitize_name(item_name)
    if not clean_name:
        clean_name = f"Item_{item_id}" if item_id else "Item"
    filename = f"{clean_name}.jpg"

    try:
        resp = requests.get(photo_url, timeout=15)
        if resp.status_code != 200 or not resp.content:
            logger.warning(f"Failed downloading image for '{clean_name}' (HTTP {resp.status_code})")
            return False

        content_bytes = resp.content
        mime_type = resp.headers.get("Content-Type", "image/jpeg")
        if not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime_type, resumable=False)
        metadata = {
            "name": filename,
            "parents": [folder_id]
        }
        service.files().create(body=metadata, media_body=media, fields="id").execute()
        return True
    except Exception as exc:
        logger.warning(f"Error uploading photo for '{clean_name}' to Drive via SA: {exc}")
        return False


# =====================================================================
# Google Apps Script Web App Implementation
# =====================================================================

def _download_photo_content_base64(item_name: str, photo_url: str, item_id: str = "") -> Optional[Dict[str, str]]:
    """Download image from CDN and return filename, mimeType, and base64 string."""
    if not photo_url or not str(photo_url).strip().startswith(("http://", "https://")):
        return None

    clean_name = _sanitize_name(item_name)
    if not clean_name:
        clean_name = f"Item_{item_id}" if item_id else "Item"
    filename = f"{clean_name}.jpg"

    try:
        resp = requests.get(photo_url, timeout=15)
        if resp.status_code != 200 or not resp.content:
            return None

        mime_type = resp.headers.get("Content-Type", "image/jpeg")
        if not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        b64 = base64.b64encode(resp.content).decode("utf-8")
        return {
            "fileName": filename,
            "fileContent": b64,
            "mimeType": mime_type
        }
    except Exception as exc:
        logger.debug(f"Failed to download photo for '{clean_name}': {exc}")
        return None


def sync_menu_photos_via_appscript(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    timestamp_str: Optional[str] = None,
    batch_size: int = 10
) -> Optional[str]:
    """
    Upload menu photos to Google Drive using Google Apps Script Web App endpoint.
    Hierarchical folder structure: {GDRIVE_FOLDER_ID} -> {nama owner} -> Menu Foto -> {Platform} | {Listing Name} | {SID} | {YYYY-MM-DD HH:MM}
    """
    env_vals = dotenv_values()
    target_url = (
        env_vals.get("GDRIVE_APPSCRIPT_URL")
        or os.getenv("GDRIVE_APPSCRIPT_URL")
        or DEFAULT_APPSCRIPT_URL
    )
    if not target_url:
        logger.info("GDRIVE_APPSCRIPT_URL is not configured in .env. Skipping photo Drive sync.")
        return None
    root_folder_id = (
        env_vals.get("GDRIVE_FOLDER_ID")
        or env_vals.get("GDRIVE_PARENT_FOLDER_ID")
        or os.getenv("GDRIVE_FOLDER_ID")
        or os.getenv("GDRIVE_PARENT_FOLDER_ID")
        or DEFAULT_ROOT_FOLDER_ID
    )

    clean_owner = _sanitize_name(owner_name or "Default Owner")
    clean_platform = _sanitize_name(platform or "Platform")
    clean_listing = _sanitize_name(listing_name or "Outlet")
    clean_sid = _sanitize_name(sid or "SID")

    if not timestamp_str:
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        timestamp_str = now_wib.strftime("%Y-%m-%d %H:%M")

    target_folder_name = f"{clean_platform} | {clean_listing} | {clean_sid} | {timestamp_str}"
    folder_path = [clean_owner, "Menu Foto", target_folder_name]

    # Filter dishes with photo URLs and download them concurrently
    photo_tasks = []
    name_counts = {}
    for d in dishes:
        item_name = str(d.get("item_name") or d.get("Item") or d.get("nama_item") or "").strip()
        photo_url = str(d.get("photo_url") or d.get("link_foto") or d.get("Photo Link") or "").strip()
        item_id = str(d.get("item_id") or d.get("dish_id") or d.get("Item ID") or "").strip()

        if photo_url and photo_url.startswith(("http://", "https://")):
            norm_name = item_name.casefold()
            name_counts[norm_name] = name_counts.get(norm_name, 0) + 1
            unique_name = item_name
            if name_counts[norm_name] > 1:
                unique_name = f"{item_name} ({item_id or name_counts[norm_name]})"
            photo_tasks.append((unique_name, photo_url, item_id))

    downloaded_files = []
    if photo_tasks:
        logger.info(f"Downloading {len(photo_tasks)} photos from platform CDN...")
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_task = {
                executor.submit(_download_photo_content_base64, t[0], t[1], t[2]): t
                for t in photo_tasks
            }
            for fut in as_completed(future_to_task):
                res = fut.result()
                if res:
                    downloaded_files.append(res)
        logger.info(f"Downloaded {len(downloaded_files)}/{len(photo_tasks)} photos successfully.")

    # 1. Step 1: Create or resolve folder & upload first batch of photos (if any)
    first_chunk = downloaded_files[:batch_size]
    init_payload = {
        "folderPath": folder_path,
        "folderId": root_folder_id,
        "targetFolderId": root_folder_id,
        "files": first_chunk
    }

    try:
        logger.info(f"Sending request to Apps Script Web App for folder '{target_folder_name}'...")
        resp = requests.post(target_url, json=init_payload, timeout=90)
        if resp.status_code != 200:
            logger.warning(f"Apps Script Web App HTTP error {resp.status_code}: {resp.text[:200]}")
            return None

        result = resp.json()
        if result.get("status") != "success":
            logger.warning(f"Apps Script Web App failed: {result.get('message')}")
            return None

        folder_url = result.get("folderUrl")
        sub_folder_id = result.get("subFolderId")
        if not folder_url and sub_folder_id:
            folder_url = f"https://drive.google.com/drive/folders/{sub_folder_id}"

        logger.info(f"✅ Folder Drive successfully resolved: {folder_url}")

        # 2. Step 2: Upload remaining chunks (if any)
        remaining_files = downloaded_files[batch_size:]
        if remaining_files and sub_folder_id:
            for i in range(0, len(remaining_files), batch_size):
                chunk = remaining_files[i:i + batch_size]
                chunk_payload = {
                    "folderId": sub_folder_id,
                    "targetFolderId": sub_folder_id,
                    "files": chunk
                }
                try:
                    resp_c = requests.post(target_url, json=chunk_payload, timeout=90)
                    if resp_c.status_code == 200:
                        logger.info(f"Uploaded photo batch {i // batch_size + 2} ({len(chunk)} photos)")
                    time.sleep(1)
                except Exception as ec:
                    logger.warning(f"Warning uploading photo chunk: {ec}")

        return folder_url
    except Exception as exc:
        logger.error(f"Exception calling Google Apps Script Web App: {exc}")
        return None


# =====================================================================
# Main Unified Interface
# =====================================================================

def sync_menu_photos_to_drive(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    timestamp_str: Optional[str] = None
) -> Optional[str]:
    """
    Main entry point for photo sync:
    1. If Service Account credentials are valid, uses Service Account.
    2. Otherwise, uses Google Apps Script Web App (GDRIVE_APPSCRIPT_URL).
    3. If neither or if it fails, logs warning and returns None (caller keeps CDN URLs).
    """
    # 1. Try Service Account first if available
    sa_service = get_drive_service()
    if sa_service:
        try:
            folder_id, folder_url = resolve_menu_foto_folder(
                service=sa_service,
                owner_name=owner_name,
                platform=platform,
                listing_name=listing_name,
                sid=sid,
                timestamp_str=timestamp_str
            )
            if folder_id and folder_url:
                photo_tasks = []
                name_counts = {}
                for d in dishes:
                    item_name = str(d.get("item_name") or d.get("Item") or d.get("nama_item") or "").strip()
                    photo_url = str(d.get("photo_url") or d.get("link_foto") or d.get("Photo Link") or "").strip()
                    item_id = str(d.get("item_id") or d.get("dish_id") or d.get("Item ID") or "").strip()

                    if photo_url and photo_url.startswith(("http://", "https://")):
                        norm_name = item_name.casefold()
                        name_counts[norm_name] = name_counts.get(norm_name, 0) + 1
                        unique_name = item_name
                        if name_counts[norm_name] > 1:
                            unique_name = f"{item_name} ({item_id or name_counts[norm_name]})"
                        photo_tasks.append((unique_name, photo_url, item_id))

                if photo_tasks:
                    logger.info(f"Uploading {len(photo_tasks)} photos via Service Account...")
                    with ThreadPoolExecutor(max_workers=6) as executor:
                        futures = [
                            executor.submit(
                                _download_and_upload_single_photo_sa,
                                sa_service,
                                folder_id,
                                t[0],
                                t[1],
                                t[2]
                            )
                            for t in photo_tasks
                        ]
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception:
                                pass
                return folder_url
        except Exception as e_sa:
            logger.warning(f"Service Account sync failed: {e_sa}. Falling back to Apps Script Web App.")

    # 2. Use Google Apps Script Web App
    return sync_menu_photos_via_appscript(
        owner_name=owner_name,
        platform=platform,
        listing_name=listing_name,
        sid=sid,
        dishes=dishes,
        timestamp_str=timestamp_str
    )
