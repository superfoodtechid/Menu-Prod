import asyncio
import sys
import os
import pandas as pd
import requests
import io
from dotenv import load_dotenv

# Add current directory to path to allow importing local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from grab_api_scraper import run_api_download_for_portal, validate_credentials
from result import main as run_result

DEFAULT_DBR_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSsAq8JmDfGI8KY7aSCRpzC2EaQARkK1OvhWrll7g3qlxFMIcwtDpAF-Wxf4aQnGET4eCmncjdEgre5/pub?output=csv"
CSV_URL = os.getenv("DBR_CSV_URL") or os.getenv("GSHEETS_URL") or os.getenv("NOMOR_HP_CSV_URL") or DEFAULT_DBR_URL

async def run_all():
    # Reload env just in case
    load_dotenv(override=True)
    
    print(f"Fetching merchant list from spreadsheet...")
    try:
        import time
        cache_buster_url = CSV_URL + f"&t={int(time.time())}"
        resp = requests.get(cache_buster_url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        
        # Filter for GrabFood, Tipe Agency, and Status Live/Progress
        col_app = "Aplikator" if "Aplikator" in df.columns else ("Aplikasi" if "Aplikasi" in df.columns else None)
        col_st = "Status Internal" if "Status Internal" in df.columns else ("Status" if "Status" in df.columns else None)
        col_type = "Tipe" if "Tipe" in df.columns else None

        grab_df = df[df[col_app].astype(str).str.contains("Grab", na=False, case=False)] if col_app else df
        if col_type:
            grab_df = grab_df[grab_df[col_type].astype(str).str.contains("Agency", na=False, case=False)]
        grab_df = grab_df[grab_df[col_st].astype(str).str.contains("Live|Progress", na=False, case=False)] if col_st else grab_df
        
        portals = []
        for idx, row in grab_df.iterrows():
            # Columns logic: 
            # 1st Nama Pengguna (index 16), 2nd Nama Pengguna (index 25, usually SuperFood)
            # We take the 2nd one if available, fallback to 1st
            user_sf = row.get("Nama Pengguna.1")
            user_mt = row.get("Nama Pengguna")
            pwd_sf = row.get("Kata Sandi.1")
            pwd_mt = row.get("Kata Sandi")
            
            user = user_sf if pd.notna(user_sf) and str(user_sf).strip() != "-" else user_mt
            pwd = pwd_sf if pd.notna(pwd_sf) and str(pwd_sf).strip() != "-" else pwd_mt
            if pd.isna(pwd) or str(pwd).strip() in ("-", "", "nan", "None"):
                pwd = "Master@123"
            
            if pd.notna(user) and str(user).strip() not in ("-", "", "nan", "None"):
                u_str = str(user).strip()
                p_str = str(pwd).strip()
                outlet = str(row.get("Nama Outlet", "Unknown")).strip()
                
                # Di Master DB, kolom Cabang tidak ada, gunakan Brand
                branch_val = row.get("Cabang", row.get("Brand", ""))
                branch = str(branch_val).strip() if pd.notna(branch_val) else ""
                
                # Smart credential validation
                is_valid, err_msg = validate_credentials(u_str, p_str)
                if not is_valid:
                    print(f"⚠️  [VALIDATION WARNING] Row #{idx+1} for '{outlet} ({branch})' has invalid credentials: {err_msg}")
                    
                portals.append({
                    "id": len(portals) + 1,
                    "outlet": outlet,
                    "branch": branch,
                    "user": u_str,
                    "pwd": p_str
                })

        
    except Exception as e:
        print(f"[ERROR] Failed to fetch or parse spreadsheet: {e}")
        return

    if not portals:
        print("[ERROR] No active Grab portals found in the spreadsheet.")
        return

    print("="*60)
    print(f"  GRAB MULTI-PORTAL AUTOMATION ({len(portals)} accounts from Spreadsheet)")
    print("="*60)
    
    MAX_RETRIES = 3
    failed_portals = []

    for portal in portals:
        user = portal["user"]
        pwd = portal["pwd"]
        outlet_name = f"{portal['outlet']} ({portal['branch']})" if portal['branch'] else portal['outlet']
        success = False

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                print(f"\n  [RETRY {attempt-1}/{MAX_RETRIES-1}] Retrying {outlet_name} in 5 seconds...")
                await asyncio.sleep(5)

            print(f"\n\n[PORTAL {portal['id']}] Starting process for: {outlet_name} (Attempt {attempt}/{MAX_RETRIES})")
            print(f"User: {user}")
            print("-" * 50)

            try:
                # Step 1: Download data via API
                print(f"Step 1: Downloading data via API...")
                downloaded_file, error = await run_api_download_for_portal(user, pwd)

                if not downloaded_file:
                    print(f"✗ [PORTAL {portal['id']}] Gagal mengunduh data (attempt {attempt}).")
                    print(f"  Pesan Error: {error}")
                    continue  # retry

                # Step 2: Process and Push
                print(f"\nStep 2: Processing and pushing to Google Sheets...")
                run_result(username=user, outlet=portal['outlet'], branch=portal['branch'])

                print(f"\n✓ [PORTAL {portal['id']}] {outlet_name} COMPLETED SUCCESSFULLY")
                success = True
                break  # done, no more retries needed

            except Exception as e:
                print(f"\n✗ [PORTAL {portal['id']}] FAILED (attempt {attempt}): {str(e)}")
                continue  # retry

        if not success:
            print(f"\n✗✗ [PORTAL {portal['id']}] {outlet_name} GAGAL setelah {MAX_RETRIES} percobaan.")
            failed_portals.append(outlet_name)

    print("\n" + "="*60)
    print("  ALL PORTALS FINISHED PROCESSING")
    if failed_portals:
        print(f"\n  ✗ {len(failed_portals)} PORTAL GAGAL:")
        for name in failed_portals:
            print(f"    - {name}")
    else:
        print("  ✓ Semua portal berhasil diproses.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(run_all())
