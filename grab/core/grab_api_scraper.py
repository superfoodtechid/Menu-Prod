import os
import json
import asyncio
import time
import uuid
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from dotenv import load_dotenv
try:
    from filelock import FileLock
except ImportError:
    import contextlib
    class FileLock:
        def __init__(self, path, timeout=-1): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        @contextlib.contextmanager
        def acquire(self, *a, **kw): yield

load_dotenv(override=True)

import logging
from pathlib import Path

# --- Dynamic Path Definitions ---
BASE_GRAB_DIR = Path(__file__).resolve().parents[1]  # menu-prod/grab/
DATA_DIR = BASE_GRAB_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
SESSION_DIR = DATA_DIR / "sessions"
DOWNLOADS_DIR = DATA_DIR / "downloads"

# Ensure directories exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("GrabAuto")

class SessionStuckError(Exception):
    """Custom exception when API calls are stuck due to persistent network errors"""
    pass

class IncorrectCredentialsError(Exception):
    """Custom exception when login fails due to wrong username or password"""
    pass


import re

def validate_credentials(username, password):
    """
    Smarter and stricter credential validation to catch common human errors.
    Returns (is_valid, error_message)
    """
    if not username or not password:
        return False, "Username or password is empty"
        
    u = str(username).strip().replace('\xa0', '')
    p = str(password).strip().replace('\xa0', '')
    
    if not u or not p:
        return False, "Username or password contains only whitespace"
        
    placeholders = {'-', '--', 'null', 'none', 'n/a', 'na', 'sandi', 'password', 'username', 'pengguna'}
    if u.lower() in placeholders or p.lower() in placeholders:
        return False, f"Credential contains a placeholder value (user: '{u}', pwd: '{p}')"
        
    if len(p) < 6:
        return False, f"Password is too short (less than 6 characters): '{p}'"
        
    email_pattern = r'[^@\s]+@[^@\s]+\.[^@\s]+'
    if re.search(email_pattern, p):
        return False, f"Password looks like an email address (likely copy-paste or swap error): '{p}'"
        
    if p.lower().endswith('superfood') and len(p) > 10:
        return False, f"Password looks like a Superfood merchant username (ends with 'superfood'): '{p}'"
        
    return True, ""


class GrabAPI:
    def __init__(self, page, username, password):
        self.page = page
        self.username = username
        self.password = password
        self.base_url = "https://merchant.grab.com"

    async def call_api(self, url, method="GET", params=None, headers=None, body=None):
        """Call Grab API from within the page context to reuse session/headers"""
        full_url = url
        if params and method == "GET":
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
        
        headers_js = json.dumps(headers or {})
        body_js = json.dumps(body) if body is not None else "null"
        
        js_code = f"""
        async () => {{
            try {{
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 15000);
                
                const extraHeaders = {headers_js};
                const bodyObj = {body_js};
                
                const fetchOptions = {{
                    method: "{method}",
                    signal: controller.signal,
                    headers: {{
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        ...extraHeaders
                    }},
                    credentials: "include"
                }};
                
                if (bodyObj !== null) {{
                    fetchOptions.body = JSON.stringify(bodyObj);
                }}
                
                const response = await fetch("{full_url}", fetchOptions);
                clearTimeout(timeoutId);
                const status = response.status;
                const text = await response.text();
                try {{
                    return {{ status, data: JSON.parse(text) }};
                }} catch (e) {{
                    return {{ status, data: text }};
                }}
            }} catch (e) {{
                return {{ status: 0, error: e.toString() }};
            }}
        }}
        """
        
        for attempt in range(5):
            try:
                if self.page.is_closed():
                    return {"status": 0, "error": "Page closed"}
                
                res = await self.page.evaluate(js_code)
                
                if res is None:
                    res = {"status": 0, "error": "Evaluation returned None"}

                if res.get("status") == 0 and res.get("error"):
                    err_msg = res["error"].lower()
                    if "failed to fetch" in err_msg or "networkerror" in err_msg or "aborted" in err_msg:
                        if attempt < 4:
                            logger.info(f"  [Retry] Network error detected in JS fetch, retrying... ({attempt+1})")
                            try:
                                ss_path = os.path.join(LOG_DIR, f"net_error_{self.username}_try{attempt+1}.png")
                                await self.page.screenshot(path=ss_path)
                            except: pass
                            await asyncio.sleep(3)
                            continue
                        else:
                            raise SessionStuckError(f"Network stuck for {self.username} after 5 attempts")
                
                return res
            except SessionStuckError:
                raise
            except Exception as e:
                err_msg = str(e).lower()
                if ("context was destroyed" in err_msg or "navigation" in err_msg or "network" in err_msg) and attempt < 4:
                    logger.info(f"  [Retry] Playwright execution error, retrying API call... ({attempt+1})")
                    await asyncio.sleep(2)
                    continue
                return {"status": 0, "error": str(e)}
        
        return {"status": 0, "error": "Max retries reached without successful response"}

    async def get_merchant_group_id(self):
        """GET /troy/user-profile/v1/merchant-selector"""
        url = f"{self.base_url}/troy/user-profile/v1/merchant-selector"
        resp = await self.call_api(url)
        status = resp.get("status")
        if status == 200:
            data = resp.get("data", {})
            merchants = data.get("merchants", [])
            if merchants:
                mgid = merchants[0].get("id")
                return mgid
        else:
            logger.warning(f"  [API] merchant-selector returned status {status}: {str(resp.get('data'))[:100]}")
        return None

    async def get_all_merchants_and_stores(self):
        """Get all merchant groups and their store list from the selector.
        Tries multiple field name variants for robustness.
        """
        url = f"{self.base_url}/troy/user-profile/v1/merchant-selector"
        resp = await self.call_api(url)
        if resp.get("status") != 200:
            logger.error(f"Failed to fetch merchant-selector: {resp.get('error') or resp.get('status')}")
            return []

        data = resp.get("data", {})
        merchants = data.get("merchants", [])
        logger.info(f"  [Selector] Raw merchant-selector: {len(merchants)} merchant(s). Sample: {str(merchants[:1])[:300]}")

        results = []
        for m in merchants:
            group_id   = m.get("id")
            group_name = m.get("name") or m.get("merchantName") or m.get("group_name") or m.get("display_name") or ""
            stores = (m.get("stores") or m.get("branches") or
                      m.get("outlets") or m.get("merchantOutlets") or [])
            if stores and isinstance(stores, list):
                for s in stores:
                    sid = (s.get("id") or s.get("storeId") or s.get("store_id")
                           or s.get("merchantId") or s.get("outletId"))
                    sname = (s.get("name") or s.get("storeName") or s.get("store_name")
                             or s.get("outletName") or group_name)
                    if sid:
                        results.append({
                            "group_id": group_id,
                            "group_name": group_name,
                            "store_id": sid,
                            "store_name": sname,
                        })
            else:
                # Jika group_id bertipe MLM/IDMG, coba fetch menu-groups API untuk list cabang
                if group_id and str(group_id).startswith("IDMG"):
                    logger.info(f"  [Selector] Group ID {group_id} detected without direct stores. Trying menu-groups API...")
                    mg_url = "https://api.grab.com/food/merchant/v1/menu-groups?isWithItemPhotoCount=true"
                    js_code = f"""
                    async () => {{
                        try {{
                            const response = await fetch("{mg_url}", {{
                                method: "GET",
                                headers: {{
                                    "Accept": "application/json",
                                    "Accept-Language": "en",
                                    "merchantgroupid": "{group_id}",
                                    "requestsource": "troyPortal"
                                }},
                                credentials: "include"
                            }});
                            return {{ status: response.status, data: await response.json() }};
                        }} catch (e) {{
                            return {{ status: 0, error: e.toString() }};
                        }}
                    }}
                    """
                    try:
                        mg_resp = await self.page.evaluate(js_code)
                        if mg_resp and mg_resp.get("status") == 200:
                            mg_data = mg_resp.get("data", {})
                            menu_groups = mg_data.get("menuGroups") or mg_data.get("groups") or []
                            logger.info(f"  [Selector] Ditemukan {len(menu_groups)} menu group(s) dari API untuk {group_id}")
                            for mg in menu_groups:
                                mg_id = mg.get("menuGroupID") or mg.get("id")
                                mg_name = mg.get("name") or mg.get("groupName") or mg.get("menuGroupName") or group_name
                                if mg_id:
                                    results.append({
                                        "group_id": group_id,
                                        "group_name": group_name,
                                        "store_id": mg_id,
                                        "store_name": mg_name,
                                        "is_menu_group": True
                                    })
                        else:
                            logger.warning(f"  [Selector] menu-groups API returned status {mg_resp.get('status') if mg_resp else 'None'}")
                    except Exception as e:
                        logger.warning(f"  [Selector] Failed to evaluate menu-groups: {e}")
                
                # Fallback ketiga: catalog-stores API (untuk akun seperti Roti Bakar 41)
                if not results and group_id:
                    logger.info(f"  [Selector] Mencoba catalog-stores API untuk {group_id}...")
                    catalog_url = "https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset=0&limit=100&isWithItemPhotoCount=true"
                    js_catalog = f"""
                    async () => {{
                        try {{
                            const response = await fetch("{catalog_url}", {{
                                method: "GET",
                                headers: {{
                                    "Accept": "application/json",
                                    "Accept-Language": "en",
                                    "merchantgroupid": "{group_id}",
                                    "requestsource": "troyPortal"
                                }},
                                credentials: "include"
                            }});
                            const status = response.status;
                            const text = await response.text();
                            try {{
                                return {{ status, data: JSON.parse(text) }};
                            }} catch (e) {{
                                return {{ status, data: text }};
                            }}
                        }} catch (e) {{
                            return {{ status: 0, error: e.toString() }};
                        }}
                    }}
                    """
                    try:
                        cat_resp = await self.page.evaluate(js_catalog)
                        if cat_resp and cat_resp.get("status") == 200:
                            cat_data = cat_resp.get("data", {})
                            # Coba berbagai field name yang mungkin digunakan oleh API
                            cat_stores = (cat_data.get("stores") or cat_data.get("catalogStores") or
                                         cat_data.get("merchants") or cat_data.get("items") or [])
                            logger.info(f"  [Selector] Ditemukan {len(cat_stores)} catalog store(s) dari catalog-stores API untuk {group_id}")
                            for cs in cat_stores:
                                cs_id = (cs.get("merchantID") or cs.get("id") or cs.get("storeId") or
                                        cs.get("merchantId") or cs.get("store_id"))
                                cs_name = (cs.get("name") or cs.get("merchantName") or cs.get("storeName") or
                                          cs.get("displayName") or group_name)
                                if cs_id:
                                    results.append({
                                        "group_id": group_id,
                                        "group_name": group_name,
                                        "store_id": cs_id,
                                        "store_name": cs_name,
                                        "is_catalog": True
                                    })
                        else:
                            logger.warning(f"  [Selector] catalog-stores API returned status {cat_resp.get('status') if cat_resp else 'None'}")
                    except Exception as e:
                        logger.warning(f"  [Selector] Failed to evaluate catalog-stores: {e}")

                # Final fallback jika semua API gagal
                if not results and group_id:
                    results.append({
                        "group_id": group_id,
                        "group_name": group_name,
                        "store_id": group_id,
                        "store_name": group_name,
                    })
        return results

    async def get_merchant_ids_from_page_requests(self):
        """
        Navigasi ke /food/menu dan intercept request halaman ke
        api.grab.com/food/merchant/v2/menu untuk mendapatkan merchantId/merchantgroupid.
        Jika halaman cache (tidak membuat request baru), paksa reload.
        """
        captured = []
        seen_ids = set()

        def on_request(request):
            if "food/merchant/v2/menu" in request.url:
                hdrs = request.headers
                sid  = hdrs.get("merchantid")      or hdrs.get("merchantId")
                gid  = hdrs.get("merchantgroupid") or hdrs.get("merchantGroupId")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    captured.append({"store_id": sid, "group_id": gid or sid})
                    logger.info(f"  [Intercept] merchantid={sid}, merchantgroupid={gid}")

        self.page.on("request", on_request)
        try:
            # Navigasi pertama
            await self.page.goto(
                "https://merchant.grab.com/food/menu",
                wait_until="networkidle",
                timeout=30000
            )
            await self.page.wait_for_timeout(3000)

            # Jika halaman loaded dari cache → paksa reload
            if not captured:
                logger.info("  [Intercept] No requests caught (likely cached). Forcing reload...")
                await self.page.reload(wait_until="networkidle", timeout=30000)
                await self.page.wait_for_timeout(4000)

            # Fallback: cek URL apakah mengandung store ID
            # (beberapa versi portal redirect ke /food/menu/{storeId})
            if not captured:
                current_url = self.page.url
                if "/food/menu/" in current_url:
                    sid = current_url.split("/food/menu/")[-1].split("?")[0].split("/")[0]
                    if sid and sid != "menu":
                        logger.info(f"  [Intercept] merchantid={sid} extracted from URL: {current_url}")
                        captured.append({"store_id": sid, "group_id": sid})

        except Exception as e:
            logger.warning(f"  [Intercept] Navigation/reload failed: {e}")
        finally:
            self.page.remove_listener("request", on_request)

        return captured


    async def fetch_menu(self, group_id, store_id, store_name=None, is_menu_group=False):
        """GET /food/merchant/v2/menu — dipanggil dari konteks halaman /food/menu.
        Mendukung deteksi otomatis Menu Groups untuk multi-cabang (seperti AGSA).
        """
        if is_menu_group:
            logger.info(f"  [MenuGroups] Direct group menu fetch for store_id/groupID: {store_id}")
            group_menu_url = f"https://api.grab.com/food/merchant/v2/menu-groups/menu?menuGroupID={store_id}"
            js_group_menu = f"""
            async () => {{
                try {{
                    const response = await fetch("{group_menu_url}", {{
                        method: "GET",
                        headers: {{
                            "Accept": "application/json",
                            "Accept-Language": "en",
                            "merchantgroupid": "{group_id}",
                            "requestsource": "troyPortal"
                        }},
                        credentials: "include"
                    }});
                    const status = response.status;
                    const text = await response.text();
                    try {{
                        return {{ status, data: JSON.parse(text) }};
                    }} catch (e) {{
                        return {{ status, data: text }};
                    }}
                }} catch (e) {{
                    return {{ status: 0, error: e.toString() }};
                }}
            }}
            """
            for attempt in range(3):
                try:
                    res = await self.page.evaluate(js_group_menu)
                    if res and res.get("status") == 200:
                        data = res.get("data", {})
                        if isinstance(data, dict):
                            data["menuGroupID"] = store_id
                            data["is_menu_group"] = True
                            for cat in data.get("categories", []):
                                cat["menuGroupID"] = store_id
                                for item in cat.get("items") or []:
                                    item["menuGroupID"] = store_id
                        return data, None
                    err = res.get("error") or f"Status {res.get('status')}: {res.get('data')}"
                    logger.warning(f"Attempt {attempt+1} to fetch group menu failed: {err}")
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"Attempt {attempt+1} to evaluate fetch group menu failed: {e}")
                    await asyncio.sleep(2)
                    
            return None, "Failed to retrieve group menu after 3 attempts"

        # Coba deteksi menu groups terlebih dahulu
        menu_groups_url = "https://api.grab.com/food/merchant/v1/menu-groups?isWithItemPhotoCount=true"
        js_menu_groups = f"""
        async () => {{
            try {{
                const response = await fetch("{menu_groups_url}", {{
                    method: "GET",
                    headers: {{
                        "Accept": "application/json",
                        "Accept-Language": "en",
                        "merchantgroupid": "{group_id}",
                        "requestsource": "troyPortal"
                    }},
                    credentials: "include"
                }});
                const status = response.status;
                const text = await response.text();
                try {{
                    return {{ status, data: JSON.parse(text) }};
                }} catch (e) {{
                    return {{ status, data: text }};
                }}
            }} catch (e) {{
                return {{ status: 0, error: e.toString() }};
            }}
        }}
        """
        
        try:
            mg_res = await self.page.evaluate(js_menu_groups)
            if mg_res and mg_res.get("status") == 200:
                mg_data = mg_res.get("data", {})
                menu_groups = mg_data.get("menuGroups") or mg_data.get("groups") or []
                if menu_groups and isinstance(menu_groups, list):
                    logger.info(f"  [MenuGroups] Ditemukan {len(menu_groups)} menu group(s) untuk group_id {group_id}")
                    
                    # Cari group yang cocok dengan store_name
                    matched_group = None
                    if store_name:
                        def clean_str(s):
                            return "".join(c for c in str(s).lower() if c.isalnum())
                        
                        target_clean = clean_str(store_name)
                        for g in menu_groups:
                            g_name = g.get("name") or g.get("groupName") or g.get("menuGroupName") or ""
                            if clean_str(g_name) == target_clean:
                                matched_group = g
                                break
                        if not matched_group:
                            # Substring match
                            for g in menu_groups:
                                g_name = g.get("name") or g.get("groupName") or g.get("menuGroupName") or ""
                                cg = clean_str(g_name)
                                if cg and target_clean and (cg in target_clean or target_clean in cg):
                                    matched_group = g
                                    break
                    
                    if not matched_group:
                        matched_group = menu_groups[0]
                        logger.warning(f"  [MenuGroups] Tidak ditemukan kecocokan persis untuk '{store_name}'. Menggunakan group pertama: '{matched_group.get('name')}'")
                    
                    menu_group_id = matched_group.get("menuGroupID") or matched_group.get("id")
                    if menu_group_id:
                        logger.info(f"  [MenuGroups] Mengambil menu group: '{matched_group.get('name')}' (ID: {menu_group_id})")
                        group_menu_url = f"https://api.grab.com/food/merchant/v2/menu-groups/menu?menuGroupID={menu_group_id}"
                        
                        js_group_menu = f"""
                        async () => {{
                            try {{
                                const response = await fetch("{group_menu_url}", {{
                                    method: "GET",
                                    headers: {{
                                        "Accept": "application/json",
                                        "Accept-Language": "en",
                                        "merchantgroupid": "{group_id}",
                                        "requestsource": "troyPortal"
                                    }},
                                    credentials: "include"
                                }});
                                const status = response.status;
                                const text = await response.text();
                                try {{
                                    return {{ status, data: JSON.parse(text) }};
                                }} catch (e) {{
                                    return {{ status, data: text }};
                                }}
                            }} catch (e) {{
                                return {{ status: 0, error: e.toString() }};
                            }}
                        }}
                        """
                        for attempt in range(3):
                            try:
                                res = await self.page.evaluate(js_group_menu)
                                if res and res.get("status") == 200:
                                    data = res.get("data", {})
                                    if isinstance(data, dict):
                                        data["menuGroupID"] = menu_group_id
                                        data["is_menu_group"] = True
                                        for cat in data.get("categories", []):
                                            cat["menuGroupID"] = menu_group_id
                                            for item in cat.get("items") or []:
                                                item["menuGroupID"] = menu_group_id
                                    return data, None
                                err = res.get("error") or f"Status {res.get('status')}: {res.get('data')}"
                                logger.warning(f"Attempt {attempt+1} to fetch group menu failed: {err}")
                                await asyncio.sleep(2)
                            except Exception as e:
                                logger.warning(f"Attempt {attempt+1} to evaluate fetch group menu failed: {e}")
                                await asyncio.sleep(2)
                                
                        return None, "Failed to retrieve group menu after 3 attempts"
        except Exception as ex:
            logger.debug(f"Menu groups check failed or not supported: {ex}. Proceeding to standard fetch.")

        # Fallback ke alur standard jika bukan Menu Groups
        url = "https://api.grab.com/food/merchant/v2/menu"
        for attempt in range(3):
            target_gid = group_id if attempt == 0 else (store_id if attempt == 1 else None)
            gid_hdr = f'hdrs["merchantgroupid"] = "{target_gid}";' if target_gid else ""
            js_code = f"""
            async () => {{
                try {{
                    const hdrs = {{
                        "Accept": "application/json",
                        "Accept-Language": "en",
                        "merchantid": "{store_id}",
                        "requestsource": "troyPortal"
                    }};
                    {gid_hdr}
                    const response = await fetch("{url}", {{
                        method: "GET",
                        headers: hdrs,
                        credentials: "include"
                    }});
                    const status = response.status;
                    const text = await response.text();
                    try {{
                        return {{ status, data: JSON.parse(text) }};
                    }} catch (e) {{
                        return {{ status, data: text }};
                    }}
                }} catch (e) {{
                    return {{ status: 0, error: e.toString() }};
                }}
            }}
            """
            try:
                res = await self.page.evaluate(js_code)
                if res and res.get("status") == 200:
                    return res.get("data", {}), None
                err = res.get("error") or f"Status {res.get('status')}: {res.get('data')}"
                logger.warning(f"Attempt {attempt+1} to fetch standard menu failed (using gid={target_gid}): {err}")
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} to evaluate fetch standard menu failed: {e}")
                await asyncio.sleep(1.5)
                
        return None, "Failed to retrieve standard menu after 3 attempts"

    async def create_category(self, group_id, store_id, name, selling_time_id):
        """POST /food/merchant/v2/categories"""
        url = f"{self.base_url}/food/merchant/v2/categories"
        headers = {
            "merchantgroupid": group_id,
            "merchantid": store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        body = {
            "name": name,
            "categoryID": "",
            "sectionID": "",
            "sellingTimeID": selling_time_id
        }
        res = await self.call_api(url, method="POST", headers=headers, body=body)
        if res.get("status") == 200:
            return res.get("data", {}), None
        return None, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def edit_category(self, group_id, store_id, category_id, name, selling_time_id):
        """PUT /food/merchant/v3/categories/{category_id}"""
        url = f"{self.base_url}/food/merchant/v3/categories/{category_id}"
        headers = {
            "merchantgroupid": group_id,
            "merchantid": store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        body = {
            "name": name,
            "categoryID": category_id,
            "sectionID": "",
            "sellingTimeID": selling_time_id
        }
        res = await self.call_api(url, method="PUT", headers=headers, body=body)
        if res.get("status") in (200, 204):
            return True, None
        return False, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def delete_category(self, group_id, store_id, category_id):
        """DELETE /food/merchant/v2/categories/{category_id}"""
        url = f"{self.base_url}/food/merchant/v2/categories/{category_id}"
        headers = {
            "merchantgroupid": group_id,
            "merchantid": store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        body = {
            "menuGroupID": "",
            "categoryID": category_id
        }
        res = await self.call_api(url, method="DELETE", headers=headers, body=body)
        if res.get("status") in (200, 204):
            return True, None
        return False, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def sort_categories(self, group_id, store_id, sorted_category_ids):
        """PUT /food/merchant/categories-sort"""
        url = f"{self.base_url}/food/merchant/categories-sort"
        headers = {
            "merchantgroupid": group_id,
            "merchantid": store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        sorts = []
        for idx, cat_id in enumerate(sorted_category_ids):
            sorts.append({
                "resourceID": cat_id,
                "sortOrder": idx + 1
            })
        body = {
            "sectionSorts": [
                {
                    "sectionID": "",
                    "sorts": sorts
                }
            ]
        }
        res = await self.call_api(url, method="PUT", headers=headers, body=body)
        return False, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def validate_item(self, group_id, store_id, category_id, item_data, is_menu_group: bool = False, menu_group_id: str = None, force_store_level: bool = False):
        """POST /food/merchant/v2/item-validation or /food/merchant/v2/menu-groups/item-validation"""
        if force_store_level:
            mg_id = None
            use_mg_ep = False
        else:
            mg_id = menu_group_id or item_data.get("menuGroupID") or (store_id if is_menu_group else None)
            if not mg_id and "-" in str(item_data.get("itemID", "")):
                parts = str(item_data.get("itemID")).split("-")
                if len(parts) >= 2 and parts[0].isdigit():
                    mg_id = f"{parts[0]}-{parts[1]}"
            use_mg_ep = bool(is_menu_group or mg_id)

        if use_mg_ep:
            url = f"{self.base_url}/food/merchant/v2/menu-groups/item-validation"
        else:
            url = f"{self.base_url}/food/merchant/v2/item-validation"

        headers = {
            "merchantgroupid": group_id,
            "merchantid": mg_id or store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        if use_mg_ep:
            headers["x-api-source"] = "food-max-api"

        item_copy = dict(item_data)
        item_copy["categoryID"] = category_id
        if "categoryName" not in item_copy:
            item_copy["categoryName"] = ""
        if use_mg_ep:
            item_copy["menuGroupID"] = mg_id or store_id
        else:
            item_copy.pop("menuGroupID", None)

        if "nameTranslation" not in item_copy or item_copy["nameTranslation"] is None:
            item_copy["nameTranslation"] = {"translation": {}}
        if "descriptionTranslation" not in item_copy or item_copy["descriptionTranslation"] is None:
            item_copy["descriptionTranslation"] = {"translation": {}}
        if "advancedPricing" not in item_copy or item_copy["advancedPricing"] is None:
            item_copy["advancedPricing"] = {}
        if "purchasability" not in item_copy or item_copy["purchasability"] is None:
            item_copy["purchasability"] = {}
        if "prediction" not in item_copy or item_copy["prediction"] is None:
            item_copy["prediction"] = {}

        body = {
            "categoryID": category_id,
            "item": item_copy
        }
        if use_mg_ep:
            body["menuGroupID"] = mg_id or store_id

        res = await self.call_api(url, method="POST", headers=headers, body=body)
        if res.get("status") in (200, 204):
            return True, None

        err_detail = str(res.get("error") or res.get("data") or "")
        # Automatic bidirectional fallback if endpoint failed with 403, 404, or menu group / DAL error
        if ("menu group v2" in err_detail.lower() or res.get("status") in (403, 404) or "GetMenu failed in DAL" in err_detail):
            if use_mg_ep and not getattr(self, "_in_val_fallback", False):
                self._in_val_fallback = True
                try:
                    logger.info(f"  [Fallback] Menu Group validation received {res.get('status')} ({err_detail}). Retrying with standard Store Level endpoint...")
                    item_data_no_mg = dict(item_data)
                    item_data_no_mg.pop("menuGroupID", None)
                    return await self.validate_item(group_id, store_id, category_id, item_data_no_mg, is_menu_group=False, menu_group_id=None, force_store_level=True)
                finally:
                    self._in_val_fallback = False
            elif not use_mg_ep and not getattr(self, "_in_val_fallback", False):
                self._in_val_fallback = True
                try:
                    extracted_mg_id = item_data.get("menuGroupID")
                    if not extracted_mg_id and "-" in str(item_data.get("itemID", "")):
                        parts = str(item_data.get("itemID")).split("-")
                        if len(parts) >= 2 and parts[0].isdigit():
                            extracted_mg_id = f"{parts[0]}-{parts[1]}"
                    target_id = extracted_mg_id or store_id
                    logger.info(f"  [Fallback] Store level validation received {res.get('status')}. Retrying with Menu Group V2 endpoint...")
                    return await self.validate_item(group_id, store_id, category_id, item_data, is_menu_group=True, menu_group_id=target_id)
                finally:
                    self._in_val_fallback = False

        return False, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def upsert_item(self, group_id, store_id, category_id, item_data, is_menu_group: bool = False, menu_group_id: str = None, force_store_level: bool = False):
        """POST /food/merchant/v2/upsert-item or /food/merchant/v2/menu-groups/upsert-item"""
        if force_store_level:
            mg_id = None
            use_mg_ep = False
        else:
            mg_id = menu_group_id or item_data.get("menuGroupID") or (store_id if is_menu_group else None)
            if not mg_id and "-" in str(item_data.get("itemID", "")):
                parts = str(item_data.get("itemID")).split("-")
                if len(parts) >= 2 and parts[0].isdigit():
                    mg_id = f"{parts[0]}-{parts[1]}"
            use_mg_ep = bool(is_menu_group or mg_id)

        if use_mg_ep:
            url = f"{self.base_url}/food/merchant/v2/menu-groups/upsert-item"
        else:
            url = f"{self.base_url}/food/merchant/v2/upsert-item"

        headers = {
            "merchantgroupid": group_id,
            "merchantid": mg_id or store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        if use_mg_ep:
            headers["x-api-source"] = "food-max-api"
        item_copy = dict(item_data)
        item_copy["categoryID"] = category_id
        if "categoryName" not in item_copy:
            item_copy["categoryName"] = ""
        if use_mg_ep:
            item_copy["menuGroupID"] = mg_id or store_id
        else:
            item_copy.pop("menuGroupID", None)

        if "nameTranslation" not in item_copy or item_copy["nameTranslation"] is None:
            item_copy["nameTranslation"] = {"translation": {}}
        if "descriptionTranslation" not in item_copy or item_copy["descriptionTranslation"] is None:
            item_copy["descriptionTranslation"] = {"translation": {}}
        if "advancedPricing" not in item_copy or item_copy["advancedPricing"] is None:
            item_copy["advancedPricing"] = {}
        if "purchasability" not in item_copy or item_copy["purchasability"] is None:
            item_copy["purchasability"] = {}
        if "prediction" not in item_copy or item_copy["prediction"] is None:
            item_copy["prediction"] = {}

        body = {
            "categoryID": category_id,
            "item": item_copy
        }
        if use_mg_ep:
            body["menuGroupID"] = mg_id or store_id
        res = await self.call_api(url, method="POST", headers=headers, body=body)
        if res.get("status") == 200:
            return res.get("data", {}), None

        err_detail = str(res.get("error") or res.get("data") or "")
        # Automatic bidirectional fallback if endpoint failed with 403, 404, or menu group / DAL error
        if ("menu group v2" in err_detail.lower() or res.get("status") in (403, 404) or "GetMenu failed in DAL" in err_detail):
            if use_mg_ep and not getattr(self, "_in_upsert_fallback", False):
                self._in_upsert_fallback = True
                try:
                    logger.info(f"  [Fallback] Menu Group upsert received {res.get('status')} ({err_detail}). Retrying with standard Store Level endpoint...")
                    item_data_no_mg = dict(item_data)
                    item_data_no_mg.pop("menuGroupID", None)
                    res_fb, err_fb = await self.upsert_item(group_id, store_id, category_id, item_data_no_mg, is_menu_group=False, menu_group_id=None, force_store_level=True)
                    if res_fb and not err_fb:
                        return res_fb, None
                finally:
                    self._in_upsert_fallback = False
            elif not use_mg_ep and not getattr(self, "_in_upsert_fallback", False):
                self._in_upsert_fallback = True
                try:
                    extracted_mg_id = item_data.get("menuGroupID")
                    if not extracted_mg_id and "-" in str(item_data.get("itemID", "")):
                        parts = str(item_data.get("itemID")).split("-")
                        if len(parts) >= 2 and parts[0].isdigit():
                            extracted_mg_id = f"{parts[0]}-{parts[1]}"
                    target_id = extracted_mg_id or store_id
                    logger.info(f"  [Fallback] Store level upsert received {res.get('status')}. Retrying with Menu Group V2 endpoint...")
                    res_fb, err_fb = await self.upsert_item(group_id, store_id, category_id, item_data, is_menu_group=True, menu_group_id=target_id)
                    if res_fb and not err_fb:
                        return res_fb, None
                finally:
                    self._in_upsert_fallback = False

        return None, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

    async def delete_item(self, group_id, store_id, item_id):
        """DELETE /food/merchant/v2/items/{item_id}"""
        url = f"{self.base_url}/food/merchant/v2/items/{item_id}"
        headers = {
            "merchantgroupid": group_id,
            "merchantid": store_id,
            "requestsource": "troyPortal",
            "x-client-id": "GrabMerchant-Portal",
            "x-grabkit-clientid": "grabmerchant-portal"
        }
        body = {
            "itemID": item_id,
            "menuGroupID": ""
        }
        res = await self.call_api(url, method="DELETE", headers=headers, body=body)
        if res.get("status") in (200, 204):
            return True, None
        return False, res.get("error") or f"Status {res.get('status')}: {res.get('data')}"

async def perform_login(page, user, pwd):
    """Robust login steps — clears cookies on mismatch and handles sticky 'Welcome back' pages."""
    CLEAN_LOGIN_URL = (
        "https://weblogin.grab.com/merchant/login"
        "?service_id=MEXUSERS&redirect=https%3A%2F%2Fmerchant.grab.com%2Fportal"
    )
    
    import random
    stagger = random.uniform(1.0, 5.0)
    await asyncio.sleep(stagger)
    try:
        async def check_block_and_errors():
            block_texts = [
                "temporarily blocked due to multiple invalid login attempts",
                "try again later",
                "coba lagi nanti",
                "diblokir sementara"
            ]
            page_content = await page.content()
            for text in block_texts:
                if text.lower() in page_content.lower():
                    ss_path = os.path.join(LOG_DIR, f"account_blocked_{user}.png")
                    await page.screenshot(path=ss_path)
                    logger.error(f"  ✗ [Login] Account blocked screen detected for {user}. Screenshot saved to {ss_path}.")
                    raise IncorrectCredentialsError(f"Account is temporarily blocked due to multiple invalid login attempts.")

            error_texts = [
                "Make sure you have the right username",
                "attempts left",
                "Pastikan nama pengguna dan kata sandi",
                "kesempatan tersisa",
                "salah memasukkan password"
            ]
            for text in error_texts:
                if text.lower() in page_content.lower():
                    ss_path = os.path.join(LOG_DIR, f"incorrect_credentials_{user}.png")
                    await page.screenshot(path=ss_path)
                    logger.error(f"  ✗ [Login] Wrong credentials error screen detected for {user}. Screenshot saved to {ss_path}.")
                    raise IncorrectCredentialsError(f"Incorrect username or password. Remaining attempts warning shown on page.")

        print(f"  [Login] Navigating to login page for {user}...")
        for attempt in range(3):
            try:
                await page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as nav_err:
                if attempt < 2:
                    logger.info(f"  [Login] Navigation error ({nav_err}), retrying... ({attempt+1})")
                    await asyncio.sleep(5)
                else:
                    raise nav_err

        await page.wait_for_timeout(3000)
        await check_block_and_errors()

        content = await page.content()
        if "Attention Required" in await page.title() or "cloudflare" in content.lower() or "distil" in content.lower():
            logger.error(f"  ✗ [BLOCK] Detected anti-bot page for {user}.")
            await page.screenshot(path=f"blocked_{user}.png")
            return False

        is_saved_accounts = "saved-accounts" in page.url
        welcome_back_locator = page.locator('h1:has-text("Welcome back"), h2:has-text("Welcome back"), div:has-text("Welcome back")')

        if is_saved_accounts or await welcome_back_locator.count() > 0:
            content_lower = (await page.content()).lower()
            if user.lower() in content_lower:
                logger.info(f"  [Login] Saved account matches {user}, clicking 'Continue'...")
                continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")')
                if await continue_btn.count() > 0:
                    await continue_btn.first.click()
                    try:
                        await page.wait_for_selector('input[type="password"], .dashboard, .portal-content', timeout=10000)
                    except: pass
                    
                    if "login" not in page.url.lower() and "saved-accounts" not in page.url:
                        return True
            else:
                logger.info(f"  [Login] Saved account mismatch for {user}. Clearing cookies for fresh start...")
                await page.context.clear_cookies()
                await page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

        await check_block_and_errors()

        user_selectors = [
            'input[type="email"]', 'input[name="email"]', 'input[type="text"]',
            'input[placeholder*="Email" i]', 'input[placeholder*="Username" i]',
            '#email', '#username',
        ]

        async def find_username_field():
            for sel in user_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=5000) and await el.is_enabled():
                        return el
                except: continue
            return None

        user_field = await find_username_field()
        if not user_field and "saved-accounts" in page.url:
            await page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            user_field = await find_username_field()

        if user_field:
            for fill_attempt in range(3):
                await user_field.click()
                await user_field.fill("")
                await user_field.fill(user)
                await page.wait_for_timeout(500)
                
                val = await user_field.input_value()
                if val.strip() == user.strip():
                    break
                
                logger.warning(f"  [Login] Field value mismatch for {user} (got '{val}'), using keyboard simulation... ({fill_attempt+1})")
                await user_field.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.type(user, delay=50)
                await page.wait_for_timeout(500)
                
                val = await user_field.input_value()
                if val.strip() == user.strip():
                    break
                await page.wait_for_timeout(1000)

            continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")').first
            if await continue_btn.count() > 0 and await continue_btn.is_visible():
                await continue_btn.click()
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(2500)

            await check_block_and_errors()

        pwd_selector = 'input[type="password"], #password'
        try:
            await page.wait_for_selector(pwd_selector, timeout=15000)
        except:
            continue_btns = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Lanjut")')
            if await continue_btns.count() > 0:
                await continue_btns.first.click()
                try: await page.wait_for_selector(pwd_selector, timeout=10000)
                except: pass
        
        await check_block_and_errors()

        if await page.locator(pwd_selector).count() > 0:
            await page.fill(pwd_selector, pwd)
            await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            await check_block_and_errors()
                    
            try:
                await page.wait_for_url(lambda u: "login" not in u.lower() and "saved-accounts" not in u, timeout=20000)
                await page.wait_for_load_state("networkidle")
            except: pass

        return "login" not in page.url.lower() and "saved-accounts" not in page.url
    except IncorrectCredentialsError:
        raise
    except Exception as e:
        logger.error(f"  ✗ [Login] Failed: {e}")
        return False

def parse_numeric_price(val):
    if not val:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).replace("Rp", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def parse_menu(menu_data, store_id, outlet_name, shopee_short_name):
    items_list = []
    modifiers_list = []
    
    # Ambil modifierGroups global
    global_mod_groups = {}
    for mg in menu_data.get("modifierGroups", []):
        mg_id = mg.get("modifierGroupID") or mg.get("id")
        if mg_id:
            global_mod_groups[mg_id] = mg

    categories = menu_data.get("categories") or menu_data.get("menu", {}).get("categories") or []
    
    for cat in categories:
        cat_id = cat.get("categoryID") or cat.get("id") or ""
        cat_name = cat.get("categoryName") or cat.get("name") or cat.get("title") or "Unknown Category"
        
        items = cat.get("items") or cat.get("menuItems") or []
        for item in items:
            item_id = item.get("itemID") or item.get("id") or ""
            item_name = item.get("itemName") or item.get("name") or item.get("title") or "Unknown Item"
            item_desc = item.get("description") or ""
            
            # Ketersediaan
            avail_status = item.get("availableStatus")
            if avail_status is not None:
                availability = "Available" if avail_status == 1 else "Sold Out"
            else:
                status_val = item.get("status") or item.get("availability") or "AVAILABLE"
                availability = "Available" if status_val in ("AVAILABLE", 1) else "Sold Out"
            
            # Foto
            photo_url = item.get("imageURL") or ""
            if not photo_url:
                images = item.get("imageURLs") or item.get("images") or item.get("photos") or []
                if images:
                    first_img = images[0]
                    if isinstance(first_img, dict):
                        photo_url = first_img.get("url") or first_img.get("urlLarge") or ""
                    else:
                        photo_url = str(first_img)
            
            # Harga
            discounted_price = 0.0
            if "priceInMin" in item and item["priceInMin"] is not None:
                discounted_price = float(item["priceInMin"]) / 100.0
            elif item.get("priceDisplay"):
                discounted_price = parse_numeric_price(item.get("priceDisplay"))
            elif item.get("priceRange"):
                discounted_price = parse_numeric_price(item.get("priceRange"))
            
            # Cek jika ada priceInfo (struktur lama)
            price_info = item.get("priceInfo") or item.get("price") or {}
            original_price = 0.0
            if isinstance(price_info, dict) and (price_info.get("price") or price_info.get("originalPrice")):
                discounted_price = price_info.get("price") or price_info.get("amount") or discounted_price
                original_price = price_info.get("originalPrice") or price_info.get("original_price") or 0.0
                
                # Konversi jika minor unit (sangat besar)
                try:
                    discounted_price = float(discounted_price)
                    if discounted_price > 1000000:
                        discounted_price = discounted_price / 100.0
                except: pass
                try:
                    original_price = float(original_price)
                    if original_price > 1000000:
                        original_price = original_price / 100.0
                except: pass
            
            if original_price == 0.0:
                original_price = discounted_price
            
            # Cek campaign / promo
            campaign = item.get("itemCampaignInfo")
            if campaign and isinstance(campaign, dict):
                promo_price = campaign.get("campaignPrice") or campaign.get("discountedPrice") or campaign.get("price")
                if promo_price is not None:
                    promo_price_val = float(promo_price)
                    if promo_price_val > 1000000 and discounted_price < 100000:
                        promo_price_val = promo_price_val / 100.0
                    original_price = discounted_price
                    discounted_price = promo_price_val
                else:
                    discount_amount = campaign.get("discountAmount") or campaign.get("discount")
                    if discount_amount is not None:
                        discount_amount_val = float(discount_amount)
                        if discount_amount_val > 1000000 and discounted_price < 100000:
                            discount_amount_val = discount_amount_val / 100.0
                        original_price = discounted_price + discount_amount_val
            
            promo_val = original_price - discounted_price
            if promo_val < 0:
                promo_val = 0.0
            
            # Proses modifier groups (nested atau global)
            mod_groups = item.get("modifierGroups") or item.get("modifier_groups") or []
            
            # Jika tidak ada nested modifier groups, cek linkedModifierGroupIDs
            linked_ids = item.get("linkedModifierGroupIDs")
            if not mod_groups and linked_ids:
                mod_groups = []
                for mg_id in linked_ids:
                    if mg_id in global_mod_groups:
                        mod_groups.append(global_mod_groups[mg_id])
            
            num_mod_groups = len(mod_groups)
            total_mods = 0
            
            for mg in mod_groups:
                mods = mg.get("modifiers") or mg.get("modifierOptions") or mg.get("options") or []
                total_mods += len(mods)
                
                mg_name = mg.get("modifierGroupName") or mg.get("name") or mg.get("title") or "Unknown Modifier Group"
                mg_min = mg.get("minSelection") or mg.get("min") or 0
                mg_max = mg.get("maxSelection") or mg.get("max") or 1
                mg_type = mg.get("selectionType") or ("SINGLE" if mg_max == 1 else "MULTIPLE")
                
                for mod in mods:
                    mod_id = mod.get("modifierID") or mod.get("id") or ""
                    mod_name = mod.get("modifierName") or mod.get("name") or mod.get("title") or "Unknown Modifier"
                    
                    # Harga modifier
                    mod_price = 0.0
                    if "priceInMin" in mod and mod["priceInMin"] is not None:
                        mod_price = float(mod["priceInMin"]) / 100.0
                    else:
                        raw_mod_price = mod.get("price") or mod.get("amount") or 0.0
                        try:
                            mod_price = float(raw_mod_price)
                            if mod_price > 1000000:
                                mod_price = mod_price / 100.0
                        except:
                            mod_price = 0.0
                    
                    # Status ketersediaan modifier
                    mod_avail_status = mod.get("availableStatus")
                    if mod_avail_status is not None:
                        mod_availability = "Available" if mod_avail_status == 1 else "Sold Out"
                    else:
                        mod_status = mod.get("status") or mod.get("availability") or "AVAILABLE"
                        mod_availability = "Available" if mod_status in ("AVAILABLE", 1) else "Sold Out"
                    
                    modifiers_list.append({
                        "Link outlet": f"https://food.grab.com/id/en/restaurant/{store_id}",
                        "Nama panjang": outlet_name,
                        "Store ID": store_id,
                        "Item ID": item_id,
                        "Nama item": item_name,
                        "Modifier Group ID": mg_id,
                        "Nama modifier group": mg_name,
                        "Modifier ID": mod_id,
                        "Nama modifier": mod_name,
                        "Tipe modifier": mg_type,
                        "Minimal": mg_min,
                        "Maksimal": mg_max,
                        "Harga modifier": mod_price,
                        "Ketersediaan modifier": mod_availability
                    })
            
            sold_qty = item.get("soldQuantity") or item.get("soldQty") or item.get("sold_qty") or 0
            
            is_in_promo = (item.get("itemCampaignInfo") is not None) or (item.get("advancedPricing") is not None) or (original_price > discounted_price and original_price > 0)

            items_list.append({
                "Link outlet": f"https://food.grab.com/id/en/restaurant/{store_id}",
                "Nama panjang": outlet_name,
                "Store ID": store_id,
                "Category ID": cat_id,
                "Nama kategori": cat_name,
                "Item ID": item_id,
                "Nama item": item_name,
                "Jumlah terjual": sold_qty,
                "Jumlah modifier group": num_mod_groups,
                "Jumlah modifier": total_mods,
                "Deskripsi item": item_desc,
                "Harga item sebelum promo (harga coret)": original_price,
                "Harga item setelah promo (harga coret)": discounted_price,
                "Nominal atau persentase promo (harga coret)": promo_val,
                "Ketersediaan item": availability,
                "Sedang promo": "Ya" if is_in_promo else "Tidak",
                "Link foto": photo_url
            })
            
    return items_list, modifiers_list

async def run_api_download_for_portal(user, pwd, start_date: str = None, end_date: str = None, browser=None, target_store_id: str = None):
    is_valid, err_msg = validate_credentials(user, pwd)
    if not is_valid:
        logger.error(f"  ✗ [Validation] Invalid credentials for {user}: {err_msg}")
        return None, f"Invalid credentials: {err_msg}"

    session_path = os.path.join(SESSION_DIR, f"{user}.json")

    p = None
    managed_browser = None

    for run_attempt in range(2):
        context = None
        page = None
        try:
            if browser is None and managed_browser is None:
                p_inst = await async_playwright().start()
                headless_env = True
                try:
                    from pathlib import Path
                    import json as _json
                    for parent in Path(__file__).resolve().parents:
                        config_file = parent / "config.json"
                        if config_file.exists():
                            with open(config_file, "r") as f:
                                headless_env = _json.load(f).get("headless_grab", True)
                            break
                except Exception:
                    pass
                managed_browser = await p_inst.chromium.launch(headless=headless_env)
                browser = managed_browser
                p = p_inst

            storage_state = session_path if os.path.exists(session_path) and run_attempt == 0 else None
            context = await browser.new_context(
                storage_state=storage_state,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Step 1: Buka dashboard (cek sesi)
            logger.info(f"  [Nav] Checking session via dashboard for {user}...")
            try:
                await page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            except:
                pass

            api = GrabAPI(page, user, pwd)
            mgid = await api.get_merchant_group_id()

            if not mgid:
                logger.info(f"  [Session] Not active. Logging in...")
                if await perform_login(page, user, pwd):
                    mgid = await api.get_merchant_group_id()
                    if mgid:
                        _lock = FileLock(f"{session_path}.lock", timeout=30)
                        with _lock:
                            await context.storage_state(path=session_path)
                        logger.info(f"  [Session] Login success, session saved.")
                    else:
                        logger.error(f"  ✗ [Session] Login success but failed to get MGID.")
                else:
                    logger.error(f"  ✗ [Session] Login failed.")

            if not mgid:
                await context.close()
                continue

            # Step 2: Navigasi ke /food/menu + intercept request halaman untuk
            # mendapatkan merchantId yang BENAR (sama dengan curl yang digunakan manual).
            logger.info(f"  [Nav] Opening /food/menu and intercepting merchant IDs...")
            intercepted = await api.get_merchant_ids_from_page_requests()

            if intercepted:
                logger.info(f"  [Intercept] {len(intercepted)} store(s) found via page request interception.")
                selector_stores = await api.get_all_merchants_and_stores()
                name_map = {s["store_id"]: s["store_name"] for s in selector_stores if s["store_id"]}
                stores = []
                for item in intercepted:
                    sid = item["store_id"]
                    stores.append({
                        "group_id":   item["group_id"] or mgid,
                        "group_name": "",
                        "store_id":   sid,
                        "store_name": name_map.get(sid) or sid,
                    })
            else:
                logger.warning(f"  [Intercept] No requests intercepted. Falling back to merchant-selector.")
                stores = await api.get_all_merchants_and_stores()
                if not stores:
                    logger.warning(f"  No stores found via merchant-selector. Using group_id as fallback.")
                    stores = [{
                        "group_id":   mgid,
                        "group_name": "Default Group",
                        "store_id":   mgid,
                        "store_name": "Default Store",
                    }]
            
            # Filter stores to target_store_id if provided
            if target_store_id:
                filtered_stores = [s for s in stores if s.get("store_id") == target_store_id]
                if filtered_stores:
                    stores = filtered_stores
                    logger.info(f"  🎯 Filtered to target store: {target_store_id}")
                else:
                    logger.info(f"  🎯 Direct target store ID specified: {target_store_id}")
                    stores = [{
                        "group_id":   mgid,
                        "group_name": "",
                        "store_id":   target_store_id,
                        "store_name": target_store_id,
                    }]

            all_items = []
            all_modifiers = []

            for s in stores:
                store_id   = s["store_id"]
                group_id   = s["group_id"]
                store_name = s["store_name"]
                is_mg      = s.get("is_menu_group", False)

                # Navigasi ke food/menu/{store_id} untuk mengaktifkan konteks sesi store di frontend Grab
                if store_id and not is_mg:
                    try:
                        menu_tab_url = f"https://merchant.grab.com/food/menu/{store_id}"
                        logger.info(f"  [Nav] Navigating to store menu page: {menu_tab_url}")
                        await page.goto(menu_tab_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(3000)
                    except Exception as nav_err:
                        logger.warning(f"  [Nav] food/menu/{store_id} navigation warning: {nav_err}")

                # Step 3: Fetch menu dari konteks halaman /food/menu
                logger.info(f"  [Fetch] Fetching menu API for {store_name} ({store_id})...")
                menu_data, err = await api.fetch_menu(group_id, store_id, store_name, is_mg)
                if menu_data:
                    items, modifiers = parse_menu(menu_data, store_id, store_name, "")
                    all_items.extend(items)
                    all_modifiers.extend(modifiers)
                    logger.info(f"  ✓ {store_name}: {len(items)} items, {len(modifiers)} modifiers")
                else:
                    logger.error(f"  ✗ Failed to fetch menu for {store_name}: {err}")

            job_id   = uuid.uuid4().hex[:8]
            filename = os.path.join(DOWNLOADS_DIR, f"grab_menu_{user}_{job_id}.json")
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({"items": all_items, "modifiers": all_modifiers}, f, ensure_ascii=False, indent=2)

            await context.close()
            if managed_browser:
                await managed_browser.close()
            if p:
                await p.stop()
            return (filename, None)

        except Exception as e:
            logger.error(f"Error in run_attempt {run_attempt}: {e}")
            if context:
                await context.close()
            if run_attempt >= 1:
                if managed_browser:
                    await managed_browser.close()
                if p:
                    await p.stop()
                return None, str(e)

    if managed_browser:
        await managed_browser.close()
    if p:
        await p.stop()
    return None, "Max retries reached"


# ============================================================
# COOKIE-BASED DIRECT HTTP MODE (no Playwright needed)
# Alur: cookie dari browser → merchant-selector → /food/menu
#       → fetch menu API → parse → simpan JSON
# ============================================================

def get_merchants_via_cookie(cookie_str: str):
    """Ambil semua merchant yang dapat diakses via cookie menggunakan requests."""
    import requests as _req
    url = "https://merchant.grab.com/troy/user-profile/v1/merchant-selector"
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en",
        "Cookie": cookie_str,
        "Origin": "https://merchant.grab.com",
        "Referer": "https://merchant.grab.com/food/menu",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "requestsource": "troyPortal",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    try:
        resp = _req.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            merchants = data.get("merchants", [])
            results = []
            for m in merchants:
                group_id = m.get("id")
                group_name = m.get("name") or m.get("merchantName") or m.get("group_name") or m.get("display_name") or ""
                stores = m.get("stores") or m.get("branches") or m.get("outlets")
                if stores and isinstance(stores, list):
                    for s in stores:
                        results.append({
                            "group_id": group_id,
                            "group_name": group_name,
                            "store_id": s.get("id"),
                            "store_name": s.get("name"),
                        })
                else:
                    if group_id and str(group_id).startswith("IDMG"):
                        logger.info(f"  [Cookie Mode Selector] Group ID {group_id} detected without direct stores. Trying menu-groups API...")
                        mg_url = "https://api.grab.com/food/merchant/v1/menu-groups?isWithItemPhotoCount=true"
                        headers_mg = dict(headers)
                        headers_mg["merchantgroupid"] = group_id
                        try:
                            mg_resp = _req.get(mg_url, headers=headers_mg, timeout=30)
                            if mg_resp.status_code == 200:
                                mg_data = mg_resp.json()
                                menu_groups = mg_data.get("menuGroups") or mg_data.get("groups") or []
                                logger.info(f"  [Cookie Mode Selector] Ditemukan {len(menu_groups)} menu group(s) dari API")
                                for mg in menu_groups:
                                    mg_id = mg.get("menuGroupID") or mg.get("id")
                                    mg_name = mg.get("name") or mg.get("groupName") or mg.get("menuGroupName") or group_name
                                    if mg_id:
                                        results.append({
                                            "group_id": group_id,
                                            "group_name": group_name,
                                            "store_id": mg_id,
                                            "store_name": mg_name,
                                            "is_menu_group": True
                                        })
                        except Exception as e:
                            logger.warning(f"  [Cookie Mode Selector] menu-groups fetch exception: {e}")
                    
                    # Fallback ketiga: catalog-stores API (untuk akun seperti Roti Bakar 41)
                    if not results and group_id:
                        logger.info(f"  [Cookie Mode Selector] Mencoba catalog-stores API untuk {group_id}...")
                        cat_url = "https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset=0&limit=100&isWithItemPhotoCount=true"
                        cat_headers = dict(headers)
                        cat_headers["merchantgroupid"] = group_id
                        try:
                            cat_resp = _req.get(cat_url, headers=cat_headers, timeout=30)
                            if cat_resp.status_code == 200:
                                cat_data = cat_resp.json()
                                # Coba berbagai field name yang mungkin digunakan oleh API
                                cat_stores = (cat_data.get("stores") or cat_data.get("catalogStores") or
                                             cat_data.get("merchants") or cat_data.get("items") or [])
                                logger.info(f"  [Cookie Mode Selector] Ditemukan {len(cat_stores)} catalog store(s) dari API")
                                for cs in cat_stores:
                                    cs_id = (cs.get("merchantID") or cs.get("id") or cs.get("storeId") or
                                            cs.get("merchantId") or cs.get("store_id"))
                                    cs_name = (cs.get("name") or cs.get("merchantName") or cs.get("storeName") or
                                              cs.get("displayName") or group_name)
                                    if cs_id:
                                        results.append({
                                            "group_id": group_id,
                                            "group_name": group_name,
                                            "store_id": cs_id,
                                            "store_name": cs_name,
                                            "is_catalog": True
                                        })
                            else:
                                logger.warning(f"  [Cookie Mode Selector] catalog-stores API returned status {cat_resp.status_code}: {cat_resp.text[:200]}")
                        except Exception as e:
                            logger.warning(f"  [Cookie Mode Selector] catalog-stores fetch exception: {e}")

                    # Final fallback jika semua API gagal
                    if not results:
                        results.append({
                            "group_id": group_id,
                            "group_name": group_name,
                            "store_id": group_id,
                            "store_name": group_name,
                        })
            return results, None
        else:
            return [], f"merchant-selector returned status {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return [], str(e)


def fetch_menu_via_cookie(cookie_str: str, group_id: str, store_id: str, store_name: str = None, is_menu_group=False):
    """
    Fetch menu untuk satu store via cookie menggunakan requests.
    Mendukung deteksi otomatis Menu Groups untuk multi-cabang (seperti AGSA).
    """
    import requests as _req
    
    if is_menu_group:
        logger.info(f"  [Cookie Mode MenuGroups] Direct group menu fetch for store_id/groupID: {store_id}")
        group_menu_url = f"https://api.grab.com/food/merchant/v2/menu-groups/menu?menuGroupID={store_id}"
        headers_mg = {
            "Accept": "application/json",
            "Accept-Language": "en",
            "Cookie": cookie_str,
            "merchantgroupid": group_id,
            "Origin": "https://merchant.grab.com",
            "Referer": "https://merchant.grab.com/food/menu",
            "requestsource": "troyPortal",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        for attempt in range(3):
            try:
                resp_gm = _req.get(group_menu_url, headers=headers_mg, timeout=30)
                if resp_gm.status_code == 200:
                    return resp_gm.json(), None
                err = f"Status {resp_gm.status_code}: {resp_gm.text[:300]}"
                logger.warning(f"  [Cookie Mode] Attempt {attempt+1} fetch group menu failed: {err}")
                time.sleep(2)
            except Exception as e:
                logger.warning(f"  [Cookie Mode] Attempt {attempt+1} fetch group menu exception: {e}")
                time.sleep(2)
                
        return None, "fetch_group_menu_via_cookie failed after 3 attempts"

    # 1. Coba cek menu groups terlebih dahulu
    menu_groups_url = "https://api.grab.com/food/merchant/v1/menu-groups?isWithItemPhotoCount=true"
    headers_mg = {
        "Accept": "application/json",
        "Accept-Language": "en",
        "Cookie": cookie_str,
        "merchantgroupid": group_id,
        "Origin": "https://merchant.grab.com",
        "Referer": "https://merchant.grab.com/food/menu",
        "requestsource": "troyPortal",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    try:
        resp = _req.get(menu_groups_url, headers=headers_mg, timeout=30)
        if resp.status_code == 200:
            mg_data = resp.json()
            menu_groups = mg_data.get("menuGroups") or mg_data.get("groups") or []
            if menu_groups and isinstance(menu_groups, list):
                logger.info(f"  [Cookie Mode] Ditemukan {len(menu_groups)} menu group(s) untuk group_id {group_id}")
                
                matched_group = None
                if store_name:
                    def clean_str(s):
                        return "".join(c for c in str(s).lower() if c.isalnum())
                    
                    target_clean = clean_str(store_name)
                    for g in menu_groups:
                        g_name = g.get("name") or g.get("groupName") or g.get("menuGroupName") or ""
                        if clean_str(g_name) == target_clean:
                            matched_group = g
                            break
                    if not matched_group:
                        for g in menu_groups:
                            g_name = g.get("name") or g.get("groupName") or g.get("menuGroupName") or ""
                            cg = clean_str(g_name)
                            if cg and target_clean and (cg in target_clean or target_clean in cg):
                                matched_group = g
                                break
                                
                if not matched_group:
                    matched_group = menu_groups[0]
                    logger.warning(f"  [Cookie Mode] Tidak ditemukan kecocokan persis untuk '{store_name}'. Menggunakan group pertama: '{matched_group.get('name')}'")
                
                menu_group_id = matched_group.get("menuGroupID") or matched_group.get("id")
                if menu_group_id:
                    logger.info(f"  [Cookie Mode] Mengambil menu group: '{matched_group.get('name')}' (ID: {menu_group_id})")
                    group_menu_url = f"https://api.grab.com/food/merchant/v2/menu-groups/menu?menuGroupID={menu_group_id}"
                    
                    for attempt in range(3):
                        try:
                            resp_gm = _req.get(group_menu_url, headers=headers_mg, timeout=30)
                            if resp_gm.status_code == 200:
                                return resp_gm.json(), None
                            err = f"Status {resp_gm.status_code}: {resp_gm.text[:300]}"
                            logger.warning(f"  [Cookie Mode] Attempt {attempt+1} fetch group menu failed: {err}")
                            time.sleep(2)
                        except Exception as e:
                            logger.warning(f"  [Cookie Mode] Attempt {attempt+1} fetch group menu exception: {e}")
                            time.sleep(2)
                            
                    return None, "fetch_group_menu_via_cookie failed after 3 attempts"
    except Exception as ex:
        logger.debug(f"Cookie Mode menu groups check failed: {ex}. Proceeding to standard fetch.")

    # Fallback ke alur standard jika bukan Menu Groups
    url = "https://api.grab.com/food/merchant/v2/menu"
    for attempt in range(3):
        target_gid = group_id if attempt == 0 else (store_id if attempt == 1 else None)
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en",
            "Cookie": cookie_str,
            "merchantid": store_id,
            "Origin": "https://merchant.grab.com",
            "Referer": "https://merchant.grab.com/food/menu",
            "requestsource": "troyPortal",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        if target_gid:
            headers["merchantgroupid"] = target_gid

        try:
            resp = _req.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json(), None
            err = f"Status {resp.status_code}: {resp.text[:300]}"
            logger.warning(f"  [Cookie] Attempt {attempt+1} fetch_menu failed (gid={target_gid}): {err}")
            time.sleep(1.5)
        except Exception as e:
            logger.warning(f"  [Cookie] Attempt {attempt+1} fetch_menu exception: {e}")
            time.sleep(1.5)
    return None, "fetch_menu_via_cookie failed after 3 attempts"


def run_cookie_download(cookie_str: str):
    """
    Download semua menu yang dapat diakses via cookie.
    Tidak membutuhkan Playwright/browser sama sekali.
    Meniru alur manual: merchant-selector → /food/menu → fetch API.
    """
    logger.info("[Cookie Mode] Fetching merchant list via cookie...")
    merchants, err = get_merchants_via_cookie(cookie_str)
    if err:
        logger.error(f"[Cookie Mode] Gagal mengambil merchant list: {err}")
        return None, err
    if not merchants:
        return None, "[Cookie Mode] Tidak ada merchant ditemukan. Cookie mungkin sudah kadaluarsa."

    logger.info(f"[Cookie Mode] Ditemukan {len(merchants)} store.")

    all_items = []
    all_modifiers = []

    for s in merchants:
        store_id   = s["store_id"]
        group_id   = s["group_id"]
        store_name = s.get("store_name") or s.get("group_name") or store_id

        logger.info(f"  [Cookie Mode] Fetching menu: {store_name} ({store_id})...")
        menu_data, err = fetch_menu_via_cookie(cookie_str, group_id, store_id, store_name, s.get("is_menu_group", False))
        if menu_data:
            items, modifiers = parse_menu(menu_data, store_id, store_name, "")
            all_items.extend(items)
            all_modifiers.extend(modifiers)
            logger.info(f"  ✓ {store_name}: {len(items)} items, {len(modifiers)} modifiers")
        else:
            logger.error(f"  ✗ Gagal fetch menu {store_name}: {err}")

    job_id   = uuid.uuid4().hex[:8]
    filename = os.path.join(DOWNLOADS_DIR, f"grab_menu_cookie_{job_id}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump({"items": all_items, "modifiers": all_modifiers}, f, ensure_ascii=False, indent=2)

    logger.info(f"[Cookie Mode] Saved {len(all_items)} items, {len(all_modifiers)} modifiers -> {filename}")
    return filename, None


if __name__ == "__main__":
    async def main():
        load_dotenv()
        u, p = os.getenv("GRAB_USERNAME_PORTAL1"), os.getenv("GRAB_PASSWORD_PORTAL1")
        if u and p:
            res, err = await run_api_download_for_portal(u, p)
            print(f"Result: {res or err}")
    asyncio.run(main())
