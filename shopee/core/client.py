# -*- coding: utf-8 -*-
import json
import requests
import hashlib
import time
import uuid
from pathlib import Path
from selenium.webdriver.chrome.options import Options

WORKSPACE_DIR = Path(__file__).resolve().parents[3]
SELLER_BASE = "https://foody.shopee.co.id"
MMS_PREUPLOAD = "https://api.mms.shopee.co.id/uploadapi/api/v1/image/preupload"
WS_UPLOAD     = "https://up-ws-id.img.susercontent.com/file/upload"
IMG_PLAY_BASE = "https://down-id.img.susercontent.com/file"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

# Options monkeypatch removed to allow dynamic browser profiles to resolve correctly.

class ShopeeClient:
    def __init__(self, tob_token: str, entity_id: str, extra_cookies: dict = None, merchant_id: str = None, username: str = None):
        self.tob_token     = tob_token
        self.extra_cookies = extra_cookies or {}
        self.entity_id     = str(entity_id or "")
        self.merchant_id   = str(merchant_id or self.extra_cookies.get("shopee_foody_mid") or entity_id or "")
        self.username      = str(username or self.extra_cookies.get("shopee_user_name") or "")
        self.session       = requests.Session()
        self.user_agent    = USER_AGENT
        self.last_code     = None
        self.last_error    = ""
        self.last_http_status = None

    def _seller_headers(self, override_entity_id: str = None) -> dict:
        eid = str(override_entity_id or self.entity_id or "")
        mid = str(self.merchant_id or eid)
        cookies = self.extra_cookies.copy()
        if self.tob_token:
            cookies["shopee_tob_token"] = self.tob_token
        if self.username:
            cookies["shopee_user_name"] = self.username
        cookies["shopee_request_from"] = "partner_web"
        if mid:
            cookies["shopee_foody_mid"] = mid
        if eid:
            cookies["shopee_tob_entity_id"] = eid
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

        headers = {
            "Host":           "foody.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     self.user_agent,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }
        if self.tob_token:
            headers["x-merchant-token"] = self.tob_token
        if mid:
            headers["x-merchant-id"] = mid
        if eid:
            headers["shopee_tob_entity_id"] = eid
        return headers

    def get_store_dishes(self, store_id: str) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/dishes"
        try:
            resp = self.session.get(url, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            self.last_http_status = resp.status_code
            if resp.status_code in (401, 403):
                self.last_code = resp.status_code
                self.last_error = "Catalog API menolak autentikasi (HTTP auth status)."
                return []
            if not resp.ok:
                self.last_code = None
                self.last_error = f"Catalog API mengembalikan HTTP {resp.status_code}."
                return []
            data = resp.json()
            self.last_code = data.get("code")
            self.last_error = "" if self.last_code == 0 else f"Catalog API error code {self.last_code}."
            if self.last_code == 0:
                return data.get("data", {}).get("catalogs", [])
            else:
                print(f"[Shopee API] Catalog request rejected: HTTP {resp.status_code}, code={self.last_code}.")
        except Exception as e:
            self.last_http_status = None
            self.last_code = None
            self.last_error = f"Catalog request failed ({type(e).__name__})."
            print(f"[Shopee API] Catalog request failed ({type(e).__name__}).")
        return []

    def get_store_option_groups(self, store_id: str, dish_ids: list = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/option-groups/search"
        payload = {"page_no": 1, "page_size": 100}
        if dish_ids:
            payload["filter"] = {"dish_ids": dish_ids}
        try:
            resp = self.session.post(url, json=payload, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            self.last_code = data.get("code")
            self.last_error = data.get("msg", "")
            if self.last_code == 0:
                return data.get("data", {}).get("option_groups", [])
            else:
                print(f"[DEBUG] API error code: {self.last_code}, msg: {self.last_error}")
        except Exception as e:
            self.last_error = str(e)
            print(f"[Shopee API] get_store_option_groups error: {e}")
        return []

    def get_stores(self, page_no: int = 1, page_size: int = 50) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/stores"
        payload = {
            "store_name": "",
            "page_size": page_size,
            "page_no": page_no,
        }
        try:
            resp = self.session.post(url, json=payload, headers=self._seller_headers(), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("stores", [])
            else:
                self.last_code = data.get("code")
                self.last_error = data.get("msg", "")
        except Exception as e:
            self.last_error = str(e)
            print(f"[Shopee API] get_stores error: {e}")
        return []

class ShopeeModifyClient:
    def __init__(self, tob_token: str, entity_id: str, extra_cookies: dict = None, merchant_id: str = None, username: str = None):
        self.tob_token     = tob_token
        self.entity_id     = entity_id
        self.merchant_id   = merchant_id or entity_id
        self.username      = username or ""
        self.extra_cookies = extra_cookies or {}
        self.session       = requests.Session()
        self.user_agent    = USER_AGENT
        self.uploaded_image_hash = ""
        self.last_code = None
        self.last_error = ""

    def _seller_headers(self, override_entity_id: str = None) -> dict:
        eid = str(override_entity_id or self.entity_id or "")
        mid = str(self.merchant_id or eid)
        cookies = self.extra_cookies.copy()
        if self.tob_token:
            cookies["shopee_tob_token"] = self.tob_token
        if self.username:
            cookies["shopee_user_name"] = self.username
        cookies["shopee_request_from"] = "partner_web"
        if mid:
            cookies["shopee_foody_mid"] = mid
        if eid:
            cookies["shopee_tob_entity_id"] = eid
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
        headers = {
            "Host":           "foody.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     USER_AGENT,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }
        if self.tob_token:
            headers["x-merchant-token"] = self.tob_token
        if mid:
            headers["x-merchant-id"] = mid
        if eid:
            headers["shopee_tob_entity_id"] = eid
        return headers

    def _mms_headers(self) -> dict:
        cookies = self.extra_cookies.copy()
        if self.tob_token:
            cookies["shopee_tob_token"] = self.tob_token
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
        headers = {
            "Host":           "api.mms.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     USER_AGENT,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }
        if self.tob_token:
            headers["x-merchant-token"] = self.tob_token
        return headers

    @staticmethod
    def _make_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _make_sign(prefix: str = "PnjKKY") -> str:
        t = str(int(time.time()))
        combined = f"{prefix}{t}"
        h = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return f"{t}-{h}"

    def get_stores(self) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/stores"
        params = {
            "request_id": self._make_request_id(),
            "sign":       self._make_sign()
        }
        try:
            resp = self.session.get(url, headers=self._seller_headers(), params=params, timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("stores", [])
            else:
                self.last_error = f"API error get_stores: code={data.get('code')} msg={data.get('msg')}"
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_store_dishes(self, store_id: str = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/dishes"
        try:
            resp = self.session.get(url, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("catalogs", [])
            else:
                self.last_error = f"API error get_store_dishes: code={data.get('code')} msg={data.get('msg')}"
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_store_option_groups(self, store_id: str = None, dish_ids: list = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/option-groups/search"
        payload = {"page_no": 1, "page_size": 100}
        if dish_ids:
            payload["filter"] = {"dish_ids": dish_ids}
        try:
            resp = self.session.post(url, json=payload, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("option_groups", [])
            else:
                self.last_error = f"API error get_store_option_groups: code={data.get('code')} msg={data.get('msg')}"
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_dish_detail(self, dish_id: str, store_id: str = None) -> dict | None:
        sid = store_id or self.entity_id
        catalogs = self.get_store_dishes(sid)
        for cat in catalogs:
            for dish in cat.get("dishes", []):
                if str(dish.get("id")) == str(dish_id):
                    return dish
        if not self.last_error:
            self.last_error = f"Item ID {dish_id} tidak ditemukan di daftar menu toko (total katalog: {len(catalogs)})."
        return None

    def _preupload_image(self) -> dict | None:
        self.last_error = ""
        timestamp = str(int(time.time()))
        signature_hash = hashlib.sha256(f"PnjKKY{timestamp}".encode("utf-8")).hexdigest()
        sign = f"PnjKKY-{signature_hash}-{timestamp}"
        request_id = uuid.uuid4().hex
        header_v2 = {
            "version": 1,
            "sign": sign,
            "biz": 4505,
            "app_version": "mms-2.3.8",
            "client_region": "ID",
            "device_model": self.user_agent,
            "os_type": 2,
            "request_id": request_id,
            "sdk_version": "mms-2.3.8",
        }
        # The Partner portal sends the MMS HeaderV2 both in _header and as
        # top-level metadata. Sending only app_id is rejected by MMS with 400.
        payload = {
            "_header": header_v2,
            "count": 1,
            **header_v2,
        }
        try:
            resp = self.session.post(MMS_PREUPLOAD, json=payload, headers=self._mms_headers(), timeout=15)
            if resp.status_code != 200:
                self.last_error = f"MMS preupload failed with HTTP {resp.status_code}: {resp.text[:200]}"
                return None
            try:
                data = resp.json()
            except Exception as je:
                self.last_error = f"MMS preupload JSON decode error: {je}"
                return None

            if data.get("code") == 0:
                response_data = data.get("data", {})
                services = response_data.get("upload_services") or response_data.get("services") or []
                if services:
                    service = services[0]
                    upload_token = response_data.get("upload_token") or service.get("token")
                    image_ids = response_data.get("img_ids") or []
                    image_id = response_data.get("img_id") or (image_ids[0] if image_ids else "")
                    if not image_id:
                        fingerprints = response_data.get("fingerprint_infos") or []
                        if fingerprints:
                            image_id = fingerprints[0].get("img_id") or ""
                    upload_domain = service.get("upload_domain") or WS_UPLOAD.rsplit("/file/upload", 1)[0]
                    if upload_token and image_id:
                        return {
                            "token": upload_token,
                            "img_id": image_id,
                            "upload_domain": upload_domain,
                        }
                    self.last_error = "MMS preupload response tidak memiliki upload token atau img_id."
                else:
                    self.last_error = "MMS preupload berhasil tetapi tidak mengembalikan layanan upload."
            else:
                self.last_error = f"MMS preupload API error: code={data.get('code')} msg={data.get('msg')}"
        except Exception as e:
            self.last_error = str(e)
        return None

    def _upload_image_binary(
        self,
        upload_domain: str,
        token: str,
        img_id: str,
        img_data: bytes,
        filename: str = "dish.jpg",
        content_type: str = "image/jpeg"
    ) -> str | None:
        upload_url = f"{upload_domain}/file/upload"
        headers = {
            "Accept":         "application/json, text/plain, */*",
            "User-Agent":     USER_AGENT,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
        }
        try:
            h = hashlib.md5(img_data).hexdigest()
            files = {
                "file": (filename, img_data, content_type)
            }
            params = {
                "token":  token,
                "img_id": img_id,
                "md5":    h
            }
            data = {
                "token":    token,
                "key":      img_id,
                "mimeType": content_type
            }
            resp = self.session.post(upload_url, files=files, data=data, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                return img_id
            self.last_error = f"Binary upload failed: HTTP {resp.status_code} {resp.text}"
        except Exception as e:
            self.last_error = str(e)
        return None

    def upload_image_bytes(
        self,
        img_data: bytes,
        filename: str = "dish.jpg",
        content_type: str = "image/jpeg"
    ) -> str | None:
        pre = self._preupload_image()
        if not pre:
            return None
        return self._upload_image_binary(
            upload_domain=pre["upload_domain"],
            token=pre["token"],
            img_id=pre["img_id"],
            img_data=img_data,
            filename=filename,
            content_type=content_type
        )

    def upload_image(self, image_path: str) -> str | None:
        try:
            p = Path(image_path)
            with open(p, "rb") as f:
                img_data = f.read()
            ext = p.suffix.lower()
            content_type = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
            return self.upload_image_bytes(img_data=img_data, filename=p.name, content_type=content_type)
        except Exception as e:
            self.last_error = str(e)
            return None
