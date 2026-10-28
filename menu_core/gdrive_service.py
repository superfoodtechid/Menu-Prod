import os
import re
import math
import json
import base64
import logging
import io
import time
import threading
import requests
from datetime import datetime, timedelta
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


def format_photo_folder_label(
    platform: str,
    listing_name: str,
    sid: str,
    timestamp_str: Optional[str] = None,
) -> str:
    """Format the standard folder label: Platform | Listing Name | SID | YYYY-MM-DD HH:MM."""
    clean_platform = _sanitize_name(platform or "Platform")
    clean_listing = _sanitize_name(listing_name or "Outlet")
    clean_sid = _sanitize_name(sid or "SID")
    if not timestamp_str:
        timestamp_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M")
    return f"{clean_platform} | {clean_listing} | {clean_sid} | {timestamp_str}"


def is_photo_sync_enabled() -> bool:
    """Return True if Google Drive menu photo sync is enabled in environment configuration."""
    env_vals = dotenv_values()
    raw_val = (
        os.getenv("ENABLE_GDRIVE_PHOTO_SYNC")
        or env_vals.get("ENABLE_GDRIVE_PHOTO_SYNC")
        or "true"
    )
    return str(raw_val).strip().lower() not in ("false", "0", "no", "off", "disabled")


def calculate_photo_sync_eta(photo_count: int, batch_size: int = 25) -> Dict[str, Any]:
    """Calculate estimated completion time in WIB for background photo collection."""
    now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
    if photo_count <= 0:
        return {
            "total_photos": 0,
            "estimated_seconds": 0,
            "estimated_completion": now_wib.strftime("%H:%M WIB"),
            "estimated_completion_iso": now_wib.isoformat(),
        }

    batches = math.ceil(photo_count / max(1, batch_size))
    est_seconds = max(20, batches * 18)
    eta_wib = now_wib + timedelta(seconds=est_seconds)
    return {
        "total_photos": photo_count,
        "estimated_seconds": est_seconds,
        "estimated_completion": eta_wib.strftime("%H:%M WIB"),
        "estimated_completion_iso": eta_wib.isoformat(),
    }


def _extract_photo_tasks(dishes: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """Build deduplicated (unique_name, photo_url, item_id) tuples from dish records."""
    photo_tasks: List[Tuple[str, str, str]] = []
    name_counts: Dict[str, int] = {}
    for d in dishes or []:
        item_name = str(d.get("item_name") or d.get("Item") or d.get("nama_item") or "").strip()
        photo_url = str(d.get("photo_url") or d.get("link_foto") or d.get("Photo Link") or "").strip()
        item_id = str(d.get("item_id") or d.get("dish_id") or d.get("Item ID") or "").strip()

        if photo_url and photo_url.startswith(("http://", "https://")):
            norm_name = (item_name or f"Item_{item_id}").casefold()
            name_counts[norm_name] = name_counts.get(norm_name, 0) + 1
            unique_name = item_name or f"Item_{item_id}" or "Item"
            if name_counts[norm_name] > 1:
                unique_name = f"{unique_name} ({item_id or name_counts[norm_name]})"
            photo_tasks.append((unique_name, photo_url, item_id))
    return photo_tasks


def _persist_drive_photo_baseline(
    folder_url: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    uploaded_files: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Persist Drive file identities for the items in a completed menu pull."""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)|[?&]id=([a-zA-Z0-9_-]+)", str(folder_url or ""))
    if not match or not sid:
        return

    folder_id = match.group(1) or match.group(2)
    try:
        by_filename: Dict[str, Dict[str, Any]] = {}
        for uf in uploaded_files or []:
            fname = str(uf.get("fileName") or uf.get("name") or "").strip().casefold()
            fid = str(uf.get("fileId") or uf.get("id") or "").strip()
            if fname and fid:
                by_filename[fname] = {"id": fid, "name": fname}

        api_key = os.getenv("GOOGLE_DRIVE_API_KEY")
        if not by_filename and api_key:
            response = requests.get(
                "https://www.googleapis.com/drive/v3/files",
                params={
                    "q": f"'{folder_id}' in parents and trashed = false",
                    "fields": "files(id,name,mimeType)",
                    "pageSize": 1000,
                    "key": api_key,
                },
                timeout=20,
            )
            response.raise_for_status()
            files = [f for f in response.json().get("files", []) if str(f.get("mimeType", "")).startswith("image/")]
            by_filename = {str(f.get("name", "")).casefold(): f for f in files}

        if not by_filename:
            return

        name_counts = {}
        by_id, by_name = {}, {}
        for dish in dishes:
            item_name = str(dish.get("item_name") or dish.get("Item") or dish.get("nama_item") or "").strip()
            item_id = str(dish.get("item_id") or dish.get("dish_id") or dish.get("Item ID") or "").strip()
            if not item_name:
                continue
            norm_name = re.sub(r"[^a-z0-9]+", " ", item_name.casefold()).strip()
            name_counts[norm_name] = name_counts.get(norm_name, 0) + 1
            unique_name = item_name
            if name_counts[norm_name] > 1:
                unique_name = f"{item_name} ({item_id or name_counts[norm_name]})"
            file = by_filename.get(f"{_sanitize_name(unique_name)}.jpg".casefold())
            if not file:
                continue
            record = {"file_id": file["id"], "folder_id": folder_id}
            if item_id:
                by_id[item_id] = record
            by_name.setdefault(norm_name, record)

        if not by_id and not by_name:
            return
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "photo_baselines")
        os.makedirs(output_dir, exist_ok=True)
        safe_sid = _sanitize_name(sid)
        with open(os.path.join(output_dir, f"{safe_sid}.json"), "w", encoding="utf-8") as f:
            json.dump({"sid": str(sid), "folder_id": folder_id, "by_id": by_id, "by_name": by_name}, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not persist Drive photo baseline for SID %s: %s", sid, exc)


def _restore_cdn_urls_in_excel(excel_path: Optional[str], dishes: List[Dict[str, Any]]) -> None:
    """Restore original CDN photo URLs in the O.C5 Excel file if background Drive upload fails completely."""
    if not excel_path or not os.path.exists(excel_path):
        return
    try:
        import openpyxl
        from menu_core.c5_template_helper import DATA_START_ROW, is_c5_reserved_row

        url_by_id: Dict[str, str] = {}
        url_by_name: Dict[str, str] = {}
        for d in dishes or []:
            item_name = str(d.get("item_name") or d.get("Item") or d.get("nama_item") or "").strip()
            photo_url = str(d.get("photo_url") or d.get("link_foto") or d.get("Photo Link") or "").strip()
            item_id = str(d.get("item_id") or d.get("dish_id") or d.get("Item ID") or "").strip()
            if photo_url:
                if item_id:
                    url_by_id[item_id] = photo_url
                if item_name:
                    url_by_name[item_name.casefold()] = photo_url

        if not url_by_id and not url_by_name:
            return

        wb = openpyxl.load_workbook(excel_path)
        if "Item" not in wb.sheetnames:
            wb.close()
            return

        sheet = wb["Item"]
        headers = {str(cell.value).strip(): cell.column for cell in sheet[1] if cell.value}
        photo_col = headers.get("Photo Link")
        item_id_col = headers.get("Item ID")
        item_name_col = headers.get("Item") or headers.get("Item Name")

        if not photo_col:
            wb.close()
            return

        updated = 0
        for row_idx in range(DATA_START_ROW, sheet.max_row + 1):
            row_vals = [sheet.cell(row=row_idx, column=c).value for c in range(1, min(8, sheet.max_column + 1))]
            if is_c5_reserved_row(row_vals):
                continue
            iid = str(sheet.cell(row=row_idx, column=item_id_col).value or "").strip() if item_id_col else ""
            iname = str(sheet.cell(row=row_idx, column=item_name_col).value or "").strip().casefold() if item_name_col else ""
            orig_url = url_by_id.get(iid) or url_by_name.get(iname)
            if orig_url is not None:
                sheet.cell(row=row_idx, column=photo_col, value=orig_url)
                updated += 1

        if updated > 0:
            wb.save(excel_path)
            logger.info("Restored %d original CDN photo URLs in %s after Drive sync failure.", updated, excel_path)
        wb.close()
    except Exception as exc:
        logger.warning("Failed to restore CDN photo URLs in Excel %s: %s", excel_path, exc)


def update_excel_folder_link(excel_path: Optional[str], folder_label: str, folder_url: str) -> bool:
    """Safely update the 'Folder Link' sheet in an existing Excel file without blocking execution."""
    if not excel_path or not os.path.exists(excel_path) or not folder_url:
        return False
    try:
        import openpyxl
        from menu_core.c5_template_helper import upsert_folder_link_sheet

        wb = openpyxl.load_workbook(excel_path)
        upsert_folder_link_sheet(wb, [(folder_label, folder_url)])
        wb.save(excel_path)
        wb.close()
        logger.info(f"Updated Folder Link in {excel_path}: {folder_label} -> {folder_url}")
        return True
    except Exception as exc:
        logger.warning(f"Failed to update Folder Link in {excel_path}: {exc}")
        return False


def _update_job_photo_sync_metadata(job_id: Optional[str], photo_sync_meta: Dict[str, Any]) -> None:
    """Update Job.result_metadata['photo_sync'] in the database from a background thread."""
    if not job_id:
        return
    try:
        import uuid
        from sqlalchemy.orm.attributes import flag_modified
        from menu_core.database import SessionLocal, Job

        parsed_id = uuid.UUID(str(job_id)) if not isinstance(job_id, uuid.UUID) else job_id
        with SessionLocal() as db:
            job = db.query(Job).filter(Job.id == parsed_id).first()
            if not job:
                return
            meta = dict(job.result_metadata or {})
            existing_ps = dict(meta.get("photo_sync") or {})
            existing_ps.update(photo_sync_meta)
            meta["photo_sync"] = existing_ps
            job.result_metadata = meta
            flag_modified(job, "result_metadata")
            db.commit()
    except Exception as exc:
        logger.warning("Could not update photo_sync metadata for job %s: %s", job_id, exc)


def get_drive_service() -> Optional[Any]:
    """Initialize Google Drive v3 client from Service Account credentials if configured."""
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

    owner_folder_id = get_or_create_subfolder(service, root_folder_id, clean_owner)
    if not owner_folder_id:
        return None, None

    menu_foto_folder_id = get_or_create_subfolder(service, owner_folder_id, "Menu Foto")
    if not menu_foto_folder_id:
        return None, None

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


def _download_photo_content_base64(item_name: str, photo_url: str, item_id: str = "") -> Optional[Dict[str, str]]:
    """Download image from CDN and return filename, mimeType, and base64 string."""
    if not photo_url or not str(photo_url).strip().startswith(("http://", "https://")):
        return None

    clean_name = _sanitize_name(item_name)
    if not clean_name:
        clean_name = f"Item_{item_id}" if item_id else "Item"
    filename = f"{clean_name}.jpg"

    try:
        resp = requests.get(
            photo_url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
        )
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


def _post_to_appscript_with_retry(
    target_url: str,
    payload: Dict[str, Any],
    timeout: int = 75,
    max_retries: int = 3,
    backoff_delays: Tuple[float, ...] = (2.0, 5.0, 10.0)
) -> Optional[Dict[str, Any]]:
    """Send POST request to Apps Script Web App with exponential backoff retry on transient errors."""
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(target_url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data
                last_err = f"Apps Script error: {data.get('message')}"
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            last_err = str(exc)

        if attempt < max_retries - 1:
            delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
            logger.warning(
                "Apps Script request failed (attempt %d/%d: %s). Retrying in %.1fs...",
                attempt + 1, max_retries, last_err, delay
            )
            time.sleep(delay)

    logger.warning("Apps Script request failed after %d attempts: %s", max_retries, last_err)
    return None


def _upload_tasks_via_base64_fallback(
    target_url: str,
    sub_folder_id: str,
    tasks: List[Tuple[str, str, str]],
    batch_size: int = 10
) -> int:
    """Download images on backend and upload as Base64 chunks when direct CDN fetch fails or legacy script is active."""
    if not tasks or not sub_folder_id:
        return 0

    downloaded_files: List[Dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_task = {
            executor.submit(_download_photo_content_base64, t[0], t[1], t[2]): t
            for t in tasks
        }
        for fut in as_completed(future_to_task):
            try:
                res = fut.result()
                if res:
                    downloaded_files.append(res)
            except Exception:
                pass

    if not downloaded_files:
        return 0

    uploaded_count = 0
    for i in range(0, len(downloaded_files), batch_size):
        chunk = downloaded_files[i:i + batch_size]
        payload = {
            "folderId": sub_folder_id,
            "targetFolderId": sub_folder_id,
            "files": chunk,
        }
        res = _post_to_appscript_with_retry(target_url, payload, timeout=90, max_retries=3)
        if res and res.get("status") == "success":
            cnt = res.get("uploadedCount")
            uploaded_count += int(cnt) if cnt is not None else len(chunk)
        time.sleep(0.5)

    return uploaded_count


def _execute_appscript_photo_batches(
    target_url: str,
    sub_folder_id: str,
    folder_url: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    photo_tasks: List[Tuple[str, str, str]],
    batch_size: int = 25,
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
) -> int:
    """Upload photo tasks to Apps Script using direct CDN URLs first, falling back to Base64 on failure."""
    if not photo_tasks or not sub_folder_id:
        if job_id:
            _update_job_photo_sync_metadata(job_id, {
                "status": "SUCCESS",
                "uploaded_photos": 0,
                "completed_at": datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%H:%M WIB"),
            })
        return 0

    total_uploaded = 0
    legacy_base64_mode = False
    uploaded_files_list: List[Dict[str, Any]] = []

    for i in range(0, len(photo_tasks), batch_size):
        chunk_tasks = photo_tasks[i:i + batch_size]

        if legacy_base64_mode:
            total_uploaded += _upload_tasks_via_base64_fallback(
                target_url, sub_folder_id, chunk_tasks, batch_size=10
            )
            continue

        url_files = []
        task_by_filename: Dict[str, Tuple[str, str, str]] = {}
        for unique_name, photo_url, item_id in chunk_tasks:
            clean_name = _sanitize_name(unique_name) or (f"Item_{item_id}" if item_id else "Item")
            fname = f"{clean_name}.jpg"
            url_files.append({
                "fileName": fname,
                "fileUrl": photo_url,
                "url": photo_url,
                "itemId": item_id,
            })
            task_by_filename[fname.casefold()] = (unique_name, photo_url, item_id)

        payload = {
            "folderId": sub_folder_id,
            "targetFolderId": sub_folder_id,
            "files": url_files,
        }
        res = _post_to_appscript_with_retry(target_url, payload, timeout=75, max_retries=3)

        if not res:
            logger.warning(
                "Direct URL batch %d failed after retries. Falling back to Base64 upload in smaller chunks...",
                i // batch_size + 1,
            )
            total_uploaded += _upload_tasks_via_base64_fallback(
                target_url, sub_folder_id, chunk_tasks, batch_size=10
            )
            continue

        mode = res.get("mode")
        uploaded_cnt = res.get("uploadedCount")
        failed_files = res.get("failedFiles") or []
        if isinstance(res.get("files"), list):
            uploaded_files_list.extend(res["files"])

        if mode != "direct_url_v2" and uploaded_cnt == 0 and len(url_files) > 0:
            logger.info(
                "Apps Script endpoint did not process fileUrl payload (legacy Web App detected). Switching to Base64 fallback."
            )
            legacy_base64_mode = True
            total_uploaded += _upload_tasks_via_base64_fallback(
                target_url, sub_folder_id, chunk_tasks, batch_size=10
            )
            continue

        batch_uploaded = int(uploaded_cnt) if uploaded_cnt is not None else len(url_files)
        total_uploaded += batch_uploaded

        if failed_files:
            retry_tasks: List[Tuple[str, str, str]] = []
            for ff in failed_files:
                ff_name = str(ff.get("fileName") or "").strip().casefold()
                if ff_name in task_by_filename:
                    retry_tasks.append(task_by_filename[ff_name])
                elif ff.get("fileUrl"):
                    retry_tasks.append((
                        str(ff.get("fileName") or "Item").removesuffix(".jpg"),
                        str(ff.get("fileUrl")),
                        str(ff.get("itemId") or ""),
                    ))
            if retry_tasks:
                logger.info(
                    "Retrying %d failed direct-fetch photos via backend Base64 fallback...",
                    len(retry_tasks),
                )
                total_uploaded += _upload_tasks_via_base64_fallback(
                    target_url, sub_folder_id, retry_tasks, batch_size=10
                )

    if total_uploaded == 0 and len(photo_tasks) > 0:
        logger.error(
            "All photo uploads failed for SID %s (0/%d uploaded). Restoring original CDN URLs in Excel.",
            sid, len(photo_tasks),
        )
        _restore_cdn_urls_in_excel(excel_path, dishes)
        if job_id:
            _update_job_photo_sync_metadata(job_id, {
                "status": "FAILED",
                "uploaded_photos": 0,
                "message": "Gagal menyalin foto ke Google Drive.",
            })
        return 0

    _persist_drive_photo_baseline(folder_url, sid, dishes, uploaded_files=uploaded_files_list)

    completed_wib = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%H:%M WIB")
    final_status = "SUCCESS" if total_uploaded >= len(photo_tasks) else "PARTIAL"
    if job_id:
        _update_job_photo_sync_metadata(job_id, {
            "status": final_status,
            "uploaded_photos": min(total_uploaded, len(photo_tasks)),
            "completed_at": completed_wib,
        })
    logger.info(
        "Photo sync finished for SID %s: %d/%d photos uploaded to %s",
        sid, total_uploaded, len(photo_tasks), folder_url,
    )
    return total_uploaded


def sync_menu_photos_via_appscript(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    timestamp_str: Optional[str] = None,
    batch_size: int = 25,
    run_async: bool = False,
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[str]:
    """
    Upload menu photos to Google Drive using Google Apps Script Web App endpoint.
    Hierarchical folder structure: {GDRIVE_FOLDER_ID} -> {nama owner} -> Menu Foto -> {Platform} | {Listing Name} | {SID} | {YYYY-MM-DD HH:MM}
    """
    if not is_photo_sync_enabled():
        logger.info("ENABLE_GDRIVE_PHOTO_SYNC is disabled. Skipping photo Drive sync.")
        return None

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
    photo_tasks = _extract_photo_tasks(dishes)

    init_payload = {
        "folderPath": folder_path,
        "folderId": root_folder_id,
        "targetFolderId": root_folder_id,
        "files": [],
    }

    try:
        logger.info(f"Resolving Drive folder '{target_folder_name}' via Apps Script Web App...")
        result = _post_to_appscript_with_retry(target_url, init_payload, timeout=30, max_retries=3)
        if not result:
            logger.warning("Failed to resolve Drive folder via Apps Script. Keeping original CDN URLs.")
            return None

        folder_url = result.get("folderUrl")
        sub_folder_id = result.get("subFolderId")
        if not folder_url and sub_folder_id:
            folder_url = f"https://drive.google.com/drive/folders/{sub_folder_id}"

        if not folder_url or not sub_folder_id:
            logger.warning("Apps Script did not return valid folderUrl/subFolderId.")
            return None

        logger.info(f"Drive folder resolved: {folder_url}")

        if job_id:
            _update_job_photo_sync_metadata(job_id, {"drive_folder_url": folder_url})
        if excel_path:
            update_excel_folder_link(excel_path, target_folder_name, folder_url)

        if not photo_tasks:
            return folder_url

        if run_async:
            bg_thread = threading.Thread(
                target=_execute_appscript_photo_batches,
                kwargs={
                    "target_url": target_url,
                    "sub_folder_id": sub_folder_id,
                    "folder_url": folder_url,
                    "sid": sid,
                    "dishes": dishes,
                    "photo_tasks": photo_tasks,
                    "batch_size": batch_size,
                    "excel_path": excel_path,
                    "job_id": job_id,
                },
                daemon=True,
            )
            bg_thread.start()
            return folder_url

        _execute_appscript_photo_batches(
            target_url=target_url,
            sub_folder_id=sub_folder_id,
            folder_url=folder_url,
            sid=sid,
            dishes=dishes,
            photo_tasks=photo_tasks,
            batch_size=batch_size,
            excel_path=excel_path,
            job_id=job_id,
        )
        return folder_url
    except Exception as exc:
        logger.error(f"Exception calling Google Apps Script Web App: {exc}")
        return None


def _execute_sa_photo_uploads(
    sa_service,
    folder_id: str,
    folder_url: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    photo_tasks: List[Tuple[str, str, str]],
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
) -> int:
    """Upload photos via Google Drive Service Account with fallback to Apps Script if all uploads fail."""
    uploaded = 0
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
                    t[2],
                )
                for t in photo_tasks
            ]
            for future in as_completed(futures):
                try:
                    if future.result():
                        uploaded += 1
                except Exception:
                    pass

    if uploaded == 0 and len(photo_tasks) > 0:
        logger.warning("Service Account uploaded 0 photos. Restoring original CDN URLs in Excel.")
        _restore_cdn_urls_in_excel(excel_path, dishes)
        if job_id:
            _update_job_photo_sync_metadata(job_id, {
                "status": "FAILED",
                "uploaded_photos": 0,
                "message": "Gagal menyalin foto ke Google Drive. Kolom Photo Link di Excel telah dikembalikan ke link CDN asli.",
            })
        return 0

    _persist_drive_photo_baseline(folder_url, sid, dishes)
    if job_id:
        _update_job_photo_sync_metadata(job_id, {
            "status": "SUCCESS" if uploaded >= len(photo_tasks) else "PARTIAL",
            "uploaded_photos": uploaded,
            "completed_at": datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%H:%M WIB"),
        })
    return uploaded


def sync_menu_photos_to_drive(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    timestamp_str: Optional[str] = None,
    run_async: bool = False,
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[str]:
    """
    Main entry point for photo sync:
    1. Checks ENABLE_GDRIVE_PHOTO_SYNC toggle.
    2. If Service Account credentials are valid, uses Service Account.
    3. Otherwise, uses Google Apps Script Web App (GDRIVE_APPSCRIPT_URL).
    4. If neither or if folder creation fails, returns None so caller keeps CDN URLs.
    """
    if not is_photo_sync_enabled():
        logger.info("ENABLE_GDRIVE_PHOTO_SYNC is disabled. Skipping photo sync to Google Drive.")
        return None

    photo_tasks = _extract_photo_tasks(dishes)

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
                target_folder_name = format_photo_folder_label(platform, listing_name, sid, timestamp_str)
                if job_id:
                    _update_job_photo_sync_metadata(job_id, {"drive_folder_url": folder_url})
                if excel_path:
                    update_excel_folder_link(excel_path, target_folder_name, folder_url)

                if run_async and photo_tasks:
                    threading.Thread(
                        target=_execute_sa_photo_uploads,
                        kwargs={
                            "sa_service": sa_service,
                            "folder_id": folder_id,
                            "folder_url": folder_url,
                            "sid": sid,
                            "dishes": dishes,
                            "photo_tasks": photo_tasks,
                            "excel_path": excel_path,
                            "job_id": job_id,
                        },
                        daemon=True,
                    ).start()
                    return folder_url

                _execute_sa_photo_uploads(
                    sa_service=sa_service,
                    folder_id=folder_id,
                    folder_url=folder_url,
                    sid=sid,
                    dishes=dishes,
                    photo_tasks=photo_tasks,
                    excel_path=excel_path,
                    job_id=job_id,
                )
                return folder_url
        except Exception as e_sa:
            logger.warning(f"Service Account sync failed: {e_sa}. Falling back to Apps Script Web App.")

    return sync_menu_photos_via_appscript(
        owner_name=owner_name,
        platform=platform,
        listing_name=listing_name,
        sid=sid,
        dishes=dishes,
        timestamp_str=timestamp_str,
        run_async=run_async,
        excel_path=excel_path,
        job_id=job_id,
    )


def prepare_and_start_photo_sync(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
    timestamp_str: Optional[str] = None,
    run_async: bool = True,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Start menu photo sync to Google Drive in the background and return immediately.
    The Excel file can be saved right away without waiting for Drive folder creation.
    """
    photo_tasks = _extract_photo_tasks(dishes)
    total_photos = len(photo_tasks)

    if not timestamp_str:
        timestamp_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M")

    target_folder_name = format_photo_folder_label(platform, listing_name, sid, timestamp_str)

    if not is_photo_sync_enabled():
        return None, {
            "status": "DISABLED",
            "total_photos": total_photos,
            "target_folder_name": target_folder_name,
            "message": "Sinkronisasi foto Google Drive dinonaktifkan melalui konfigurasi server.",
        }

    if total_photos == 0:
        return None, {
            "status": "SKIPPED",
            "total_photos": 0,
            "target_folder_name": target_folder_name,
            "message": "Tidak ada foto menu untuk disinkronkan.",
        }

    eta_info = calculate_photo_sync_eta(total_photos)
    initial_meta = {
        "status": "PROCESSING",
        "total_photos": total_photos,
        "uploaded_photos": 0,
        "estimated_seconds": eta_info["estimated_seconds"],
        "estimated_completion": eta_info["estimated_completion"],
        "estimated_completion_iso": eta_info["estimated_completion_iso"],
        "drive_folder_url": None,
        "target_folder_name": target_folder_name,
    }

    if job_id:
        _update_job_photo_sync_metadata(job_id, initial_meta)

    if run_async:
        def _async_worker():
            try:
                sync_menu_photos_to_drive(
                    owner_name=owner_name,
                    platform=platform,
                    listing_name=listing_name,
                    sid=sid,
                    dishes=dishes,
                    timestamp_str=timestamp_str,
                    run_async=False,
                    excel_path=excel_path,
                    job_id=job_id,
                )
            except Exception as exc:
                logger.error(f"Error in background photo sync: {exc}")
                if job_id:
                    _update_job_photo_sync_metadata(job_id, {
                        "status": "FAILED",
                        "message": f"Sinkronisasi foto latar belakang gagal: {exc}",
                    })

        bg_thread = threading.Thread(target=_async_worker, daemon=True)
        bg_thread.start()
        return None, initial_meta

    folder_url = sync_menu_photos_to_drive(
        owner_name=owner_name,
        platform=platform,
        listing_name=listing_name,
        sid=sid,
        dishes=dishes,
        timestamp_str=timestamp_str,
        run_async=False,
        excel_path=excel_path,
        job_id=job_id,
    )

    if not folder_url:
        return None, {
            "status": "FAILED",
            "total_photos": total_photos,
            "target_folder_name": target_folder_name,
            "message": "Gagal membuat folder Google Drive. Kolom Photo Link di Excel menggunakan link CDN asli.",
        }

    initial_meta["drive_folder_url"] = folder_url
    return folder_url, initial_meta


def prepare_photo_folder(
    owner_name: str,
    platform: str,
    listing_name: str,
    sid: str,
    dishes: List[Dict[str, Any]],
    excel_path: Optional[str] = None,
    job_id: Optional[str] = None,
    timestamp_str: Optional[str] = None,
    workbook: Optional[Any] = None,
    skip_excel_update: bool = False,
    defer_photo_upload: bool = False,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Create/resolve the photo folder and record its URL without uploading photos.

    Folder preparation stays in the pull job so the URL is present in the
    source workbook before C5 files are combined. Photo file uploads are
    started separately after the combined workbook is ready.
    """
    if not timestamp_str:
        timestamp_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M")
    photo_tasks = _extract_photo_tasks(dishes)
    total_photos = len(photo_tasks)
    folder_label = format_photo_folder_label(platform, listing_name, sid, timestamp_str)
    metadata = {
        "status": "PREPARING_FOLDER",
        "total_photos": total_photos,
        "uploaded_photos": 0,
        "drive_folder_url": None,
        "target_folder_name": folder_label,
        "owner_name": owner_name,
        "platform": platform,
        "listing_name": listing_name,
        "sid": str(sid),
        "timestamp_str": timestamp_str,
        "excel_path": excel_path,
        "photo_upload_deferred": bool(defer_photo_upload),
        "photo_upload_trigger": "AFTER_COMBINED_C5" if defer_photo_upload else "MANUAL_OR_COMBINED",
    }
    if job_id:
        _update_job_photo_sync_metadata(job_id, metadata)

    if not is_photo_sync_enabled():
        metadata.update({
            "status": "DISABLED",
            "message": "Sinkronisasi foto Google Drive dinonaktifkan melalui konfigurasi server.",
        })
        return None, metadata

    try:
        folder_id = folder_url = None
        drive_service = get_drive_service()
        if drive_service:
            folder_id, folder_url = resolve_menu_foto_folder(
                drive_service, owner_name, platform, listing_name, sid, timestamp_str
            )

        if not folder_url:
            # The Apps Script resolves the hierarchy even when files is empty.
            folder_url = sync_menu_photos_via_appscript(
                owner_name=owner_name,
                platform=platform,
                listing_name=listing_name,
                sid=sid,
                dishes=[],
                timestamp_str=timestamp_str,
                run_async=False,
                excel_path=None,
                job_id=None,
            )

        if not folder_url:
            raise RuntimeError("Google Drive tidak mengembalikan tautan folder.")

        if workbook is not None:
            from menu_core.c5_template_helper import upsert_folder_link_sheet
            upsert_folder_link_sheet(workbook, [(folder_label, folder_url)])
        elif not skip_excel_update and excel_path:
            if not update_excel_folder_link(excel_path, folder_label, folder_url):
                raise RuntimeError("Tautan folder tidak berhasil disimpan ke file C5 outlet.")
        eta = calculate_photo_sync_eta(total_photos)
        metadata.update(eta)
        metadata.update({
            "status": "WAITING_FOR_C5" if total_photos else "SKIPPED",
            "drive_folder_url": folder_url,
            "message": (
                "Upload foto dijadwalkan setelah C5 combined selesai."
                if total_photos and defer_photo_upload
                else (None if total_photos else "Tidak ada foto menu untuk diunggah.")
            ),
        })
        if job_id:
            _update_job_photo_sync_metadata(job_id, metadata)
        return folder_url, metadata
    except Exception as exc:
        logger.warning("Photo folder preparation failed for SID %s: %s", sid, exc)
        metadata.update({
            "status": "FAILED",
            "message": f"Folder foto belum siap; foto tidak akan diunggah. {exc}",
        })
        if job_id:
            _update_job_photo_sync_metadata(job_id, metadata)
        return None, metadata


def start_deferred_photo_sync(job_id: str) -> bool:
    """Start a prepared photo upload once the combined C5 has reached Drive."""
    import uuid
    from menu_core.database import SessionLocal, Job

    try:
        parsed_id = uuid.UUID(str(job_id))
        with SessionLocal() as db:
            job = db.query(Job).filter(Job.id == parsed_id).with_for_update().first()
            if not job:
                return False
            result = dict(job.result_metadata or {})
            photo_meta = dict(result.get("photo_sync") or {})
            if photo_meta.get("status") != "WAITING_FOR_C5":
                return False
            photo_meta.update(calculate_photo_sync_eta(int(photo_meta.get("total_photos") or 0)))
            photo_meta["status"] = "PROCESSING"
            photo_meta["message"] = None
            photo_job = Job(
                outlet_id=job.outlet_id,
                job_type="PHOTO_SYNC",
                platform=job.platform,
                status="RUNNING",
                progress_pct=5,
                current_step="Menunggu file C5 combined selesai diunggah...",
                payload={"source_job_id": str(parsed_id)},
                result_metadata={"source_job_id": str(parsed_id), "photo_sync": photo_meta},
                created_by="system",
                started_at=datetime.utcnow(),
            )
            db.add(photo_job)
            db.flush()
            photo_meta["photo_job_id"] = str(photo_job.id)
            photo_job.result_metadata = {"source_job_id": str(parsed_id), "photo_sync": photo_meta}
            result["photo_sync"] = photo_meta
            job.result_metadata = result
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(job, "result_metadata")
            db.commit()
            photo_job_id = str(photo_job.id)

        def _worker():
            try:
                with SessionLocal() as db:
                    job = db.query(Job).filter(Job.id == parsed_id).first()
                    result = dict(job.result_metadata or {}) if job else {}
                    meta = dict(result.get("photo_sync") or {})
                    photo_job = db.query(Job).filter(Job.id == uuid.UUID(photo_job_id)).first()
                    if photo_job:
                        photo_job.progress_pct = 10
                        photo_job.current_step = "Membaca data foto dari file C5..."
                        db.commit()
                excel_path = meta.get("excel_path") or result.get("excel_path")
                if not excel_path or not os.path.exists(excel_path):
                    raise FileNotFoundError("File PULL tidak ditemukan untuk mengunggah foto.")

                import openpyxl
                workbook = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
                try:
                    if "Item" not in workbook.sheetnames:
                        raise ValueError("Sheet Item tidak ditemukan pada file PULL.")
                    sheet = workbook["Item"]
                    headers = {str(c.value).strip(): c.column - 1 for c in sheet[1] if c.value}
                    dishes = []
                    for row in sheet.iter_rows(min_row=3, values_only=True):
                        item_name = row[headers["Item"]] if "Item" in headers and headers["Item"] < len(row) else ""
                        item_id = row[headers["Item ID"]] if "Item ID" in headers and headers["Item ID"] < len(row) else ""
                        photo_url = row[headers["Photo Link"]] if "Photo Link" in headers and headers["Photo Link"] < len(row) else ""
                        if photo_url:
                            dishes.append({"item_name": str(item_name or ""), "item_id": str(item_id or ""), "photo_url": str(photo_url)})
                finally:
                    workbook.close()

                prepared_count = int(meta.get("total_photos") or 0)
                actual_count = len(_extract_photo_tasks(dishes))
                if prepared_count and actual_count != prepared_count:
                    logger.info(
                        "Jumlah foto pada file outlet disesuaikan dari %d menjadi %d untuk job %s.",
                        prepared_count,
                        actual_count,
                        job_id,
                    )
                folder_url = sync_menu_photos_to_drive(
                    owner_name=meta["owner_name"],
                    platform=meta["platform"],
                    listing_name=meta["listing_name"],
                    sid=meta["sid"],
                    dishes=dishes,
                    timestamp_str=meta["timestamp_str"],
                    run_async=False,
                    excel_path=excel_path,
                    job_id=str(parsed_id),
                )
                if not folder_url:
                    raise RuntimeError("Folder Drive tidak dapat ditemukan saat memulai unggah foto.")
                with SessionLocal() as db:
                    photo_job = db.query(Job).filter(Job.id == uuid.UUID(photo_job_id)).first()
                    if photo_job:
                        photo_job.status = "SUCCESS"
                        photo_job.progress_pct = 100
                        photo_job.current_step = "Sinkronisasi foto selesai."
                        photo_job.completed_at = datetime.utcnow()
                        photo_job.result_metadata = {
                            "source_job_id": str(parsed_id),
                            "photo_sync": {"status": "SUCCESS", "drive_folder_url": folder_url},
                        }
                        db.commit()
            except Exception as exc:
                logger.exception("Deferred photo sync failed for job %s", job_id)
                _update_job_photo_sync_metadata(str(parsed_id), {
                    "status": "FAILED",
                    "message": f"Gagal memulai pengumpulan foto setelah C5 terkirim: {exc}",
                })
                with SessionLocal() as db:
                    photo_job = db.query(Job).filter(Job.id == uuid.UUID(photo_job_id)).first()
                    if photo_job:
                        photo_job.status = "FAILED"
                        photo_job.progress_pct = 100
                        photo_job.current_step = "Sinkronisasi foto gagal."
                        photo_job.error_message = str(exc)
                        photo_job.completed_at = datetime.utcnow()
                        db.commit()

        threading.Thread(target=_worker, daemon=True).start()
        return True
    except Exception as exc:
        logger.warning("Could not start deferred photo sync for job %s: %s", job_id, exc)
        return False


_DRIVE_FOLDER_IMAGE_INDEX: Dict[str, Dict[str, str]] = {}
_DRIVE_FOLDER_INDEX_LOCK = threading.Lock()


def resolve_drive_folder_image(folder_url: str, item_name: str) -> Optional[str]:
    """Find the first image in a recursively nested Drive item folder matching item_name.

    Returns direct image URL (https://lh3.googleusercontent.com/d/{file_id}=s0) or None.
    """
    root_url = folder_url or os.getenv("MENU_FOTO_GDRIVE", "")
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)|[?&]id=([a-zA-Z0-9_-]+)", str(root_url))
    raw_item = str(item_name or "").strip()
    wanted_name = re.sub(r"[^a-z0-9]+", " ", raw_item.casefold()).strip()
    if not match or not wanted_name:
        return None
    parent_id = match.group(1) or match.group(2)

    api_url = "https://www.googleapis.com/drive/v3/files"
    env_vals = dotenv_values()
    api_key = os.getenv("GOOGLE_DRIVE_API_KEY") or env_vals.get("GOOGLE_DRIVE_API_KEY")

    def list_children(parent):
        params = {
            "q": f"'{parent}' in parents and trashed = false",
            "fields": "files(id,name,mimeType)",
            "pageSize": 1000,
            "orderBy": "name",
        }
        if api_key:
            params["key"] = api_key
        response = requests.get(api_url, params=params, timeout=20)
        response.raise_for_status()
        return response.json().get("files", [])

    try:
        with _DRIVE_FOLDER_INDEX_LOCK:
            if parent_id in _DRIVE_FOLDER_IMAGE_INDEX:
                image_index = _DRIVE_FOLDER_IMAGE_INDEX[parent_id]
            else:
                image_index = {}
                queue = [(parent_id, 0)]
                visited = set()
                while queue:
                    current_id, depth = queue.pop(0)
                    if current_id in visited or depth > 4:
                        continue
                    visited.add(current_id)
                    children = list_children(current_id)
                    for child in children:
                        if str(child.get("mimeType", "")).startswith("image/"):
                            image_name = re.sub(r"[^a-z0-9]+", " ", str(child.get("name", "")).rsplit(".", 1)[0].casefold()).strip()
                            image_index.setdefault(image_name, f"https://lh3.googleusercontent.com/d/{child['id']}=s0")
                            continue
                        if child.get("mimeType") != "application/vnd.google-apps.folder":
                            continue
                        child_name = re.sub(r"[^a-z0-9]+", " ", str(child.get("name", "")).casefold()).strip()
                        if child_name == wanted_name:
                            images = [item for item in list_children(child["id"])
                                      if str(item.get("mimeType", "")).startswith("image/")]
                            if images:
                                image_index.setdefault(wanted_name, f"https://lh3.googleusercontent.com/d/{images[0]['id']}=s0")
                        queue.append((child["id"], depth + 1))
                _DRIVE_FOLDER_IMAGE_INDEX[parent_id] = image_index

        # 1. Exact match
        if wanted_name in image_index:
            return image_index[wanted_name]

        # 2. Substring / partial word match fallback
        for k, v in image_index.items():
            if len(k) >= 4 and (k == wanted_name or k in wanted_name or wanted_name in k):
                return v

        return None
    except Exception as exc:
        logger.warning("Gagal resolve gambar Drive untuk '%s': %s", item_name, exc)
        return None

