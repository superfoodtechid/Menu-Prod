import json
import os
import sys
import requests
import pandas as pd
from pathlib import Path
from openpyxl import Workbook

from selenium.webdriver.chrome.options import Options

# Add shopee-omzet-automation to sys.path
AUTOMATION_DIR = Path(__file__).resolve().parents[1] / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

from core import browser

# FORCE the profile directory to be menu-prod/shopee/data/chrome_profile without modifying browser.py
BASE_DIR = Path(__file__).resolve().parent.parent
orig_add_argument = Options.add_argument
def custom_add_argument(self, argument):
    if "--user-data-dir=" in argument:
        chrome_profile_dir = BASE_DIR / "shopee" / "data" / "chrome_profile"
        argument = f"--user-data-dir={chrome_profile_dir}"
        print(f"🔧 [PATCH] Mengalihkan user data dir ke: {argument}")
    orig_add_argument(self, argument)
Options.add_argument = custom_add_argument


# Expose push/write endpoints and clients using absolute package names
from shopee.core.client import ShopeeClient, ShopeeModifyClient
from shopee.core.item.create import add_menu_shopee, create_dish, create_category
from shopee.core.item.edit import edit_menu_shopee, update_dish, update_category, reorder_categories, edit_dish_via_portal
from shopee.core.modifier.create import create_option_group
from shopee.core.modifier.edit import update_option_group
from shopee.core.modifier.delete import delete_option_group


SELLER_BASE = "https://foody.shopee.co.id"
IMG_BASE    = "https://down-id.img.susercontent.com/file"


def extract_shopee_menu(store_metadata: dict, output_dir: str):
    # Add project root to sys.path to resolve shopee.* absolute imports correctly
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    from shopee.core.pull import extract_shopee_menu as new_extract
    return new_extract(store_metadata, output_dir)
