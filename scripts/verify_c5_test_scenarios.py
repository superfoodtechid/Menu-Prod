import os
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from main import parse_c5_endpoint
from menu_core.database import SessionLocal, init_db
from fastapi import UploadFile

class MockUploadFile:
    def __init__(self, filepath: Path):
        self.filename = filepath.name
        self._path = filepath

    async def read(self):
        with open(self._path, "rb") as f:
            return f.read()

async def verify():
    init_db()
    db = SessionLocal()
    file_path = BASE_DIR / "C5. Unit Tes All Scenarios.xlsx"
    mock_file = MockUploadFile(file_path)

    print("=== TESTING parse_c5_endpoint with C5. Unit Tes All Scenarios.xlsx ===")
    res = await parse_c5_endpoint(file=mock_file, drive_url=None, db=db)

    print("\n--- Summary ---")
    summary = res.get("summary", {})
    print(json.dumps(summary, indent=2))

    print("\n--- Stores Detected ---")
    for s in res.get("stores", []):
        print(f"  SID: {s['sid']} | Name: {s['name']} | Items: {s['item_count']} | Changed: {s['changed_count']}")

    print("\n--- Detected Changes Breakdown ---")
    change_type_counts = {}
    changed_items = []
    deleted_items = []
    offline_changes = []

    for item in res.get("items", []):
        ctypes = item.get("change_types", [])
        for ct in ctypes:
            change_type_counts[ct] = change_type_counts.get(ct, 0) + 1
        
        if item.get("is_changed"):
            changed_items.append(item)
        if item.get("row_number") == 0:
            deleted_items.append(item)
        if item.get("changes", {}).get("offline_price_changed"):
            offline_changes.append(item)

    print("Change Types:")
    for ct, count in sorted(change_type_counts.items()):
        print(f"  {ct}: {count}")

    print(f"\nTotal Changed Items: {len(changed_items)}")
    print(f"Total Deleted Items Detected: {len(deleted_items)}")
    for d in deleted_items:
        print(f"  [DELETED] SID: {d['sid']} | Item: {d['item_name']} (ID: {d['item_id']})")

    print(f"\nTotal Offline Price Changes Detected: {len(offline_changes)}")
    for off in offline_changes:
        print(f"  [OFFLINE_PRICE] SID: {off['sid']} | Item: {off['item_name']}")

    print("\nValidation Errors:")
    val_errors = [it for it in res.get("items", []) if not it.get("is_valid")]
    if val_errors:
        for it in val_errors:
            print(f"  ❌ Error on {it['item_name']} (SID: {it['sid']}): {it.get('validation_error')}")
    else:
        print("  ✅ 0 Validation Errors. All items are valid!")

    print("\nSample Mutated Items:")
    for it in changed_items[:15]:
        print(f"  - [{it['sid']}] {it['item_name']}: {it.get('change_types')} | diffs: {len(it.get('diff_details', []))}")

    db.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(verify())

