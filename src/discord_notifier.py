import os
import json
import time
from pathlib import Path


def send_discord_push_summary(platform: str, job_id: str, selected_sids: list, job_status: str, audit_entries: list, outlet_names=None):
    """Post a compact, readable C5 push summary as a Discord embed."""
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("⚠️ WEBHOOK_URL belum dikonfigurasi; ringkasan push C5 tidak dikirim ke Discord.")
        return False

    sections = {"changed": [], "added": [], "deleted": [], "failed": []}
    for entry in audit_entries:
        change_types = [part.strip() for part in (entry.get("field_changed") or "").split(",") if part.strip()]
        status = str(entry.get("status") or "").upper()
        name = str(entry.get("item_name") or entry.get("item_id") or "Item tanpa nama").replace("\n", " ").strip()
        if status != "SUCCESS":
            sections["failed"].append(name)
        elif "DELETE_ITEM" in change_types:
            sections["deleted"].append(name)
        elif "NEW_ITEM" in change_types:
            sections["added"].append(name)
        else:
            sections["changed"].append(name)

    status = str(job_status or "").upper()
    changed_count = len(set(sections["changed"]))
    added_count = len(set(sections["added"]))
    deleted_count = len(set(sections["deleted"]))
    failed_count = len(set(sections["failed"]))
    if status == "SUCCESS" and not failed_count:
        status_label, color = "Selesai", 0x2ECC71
        status_emoji = "✅"
    elif changed_count + added_count + deleted_count:
        status_label, color = "Selesai sebagian", 0xF1C40F
        status_emoji = "⚠️"
    else:
        status_label, color = "Belum berhasil", 0xE74C3C
        status_emoji = "❌"

    names = [str(name).strip() for name in (outlet_names or []) if str(name).strip()]
    outlet_label = ", ".join(dict.fromkeys(names)) or ", ".join(str(sid) for sid in selected_sids if str(sid).strip()) or "Outlet tidak diketahui"

    embed_fields = [{
        "name": "📍 Outlet",
        "value": outlet_label[:1024],
        "inline": False,
    }]
    totals = [
        ("✏️ Diubah", changed_count),
        ("➕ Ditambahkan", added_count),
        ("🗑️ Dihapus", deleted_count),
        ("⚠️ Perlu dicek", failed_count),
    ]
    totals = [(label, count) for label, count in totals if count]
    if totals:
        embed_fields.append({
            "name": "📊 Ringkasan",
            "value": "   ·   ".join(f"**{count}** {label}" for label, count in totals),
            "inline": False,
        })

    item_sections = [
        ("changed", "✏️ Item yang diubah"),
        ("added", "➕ Item yang ditambahkan"),
        ("deleted", "🗑️ Item yang dihapus"),
        ("failed", "⚠️ Item yang perlu dicek"),
    ]
    for key, title in item_sections:
        unique_names = list(dict.fromkeys(sections[key]))
        if not unique_names:
            continue
        sample = unique_names[:6]
        remaining = len(unique_names) - len(sample)
        value = "\n".join(f"• {name}" for name in sample)
        if remaining:
            value += f"\n• dan {remaining} item lainnya"
        embed_fields.append({"name": title, "value": value[:1024], "inline": False})

    if not audit_entries:
        embed_fields.append({"name": "Rincian", "value": "Tidak ada perubahan yang tercatat.", "inline": False})

    embed = {
        "title": "🔔 MenuOps  ·  Ringkasan Push",
        "description": f"{status_emoji} **{status_label}** untuk **{platform.title()}**",
        "color": color,
        "fields": embed_fields,
        "footer": {"text": "MenuOps  •  Menu Push C5"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        import requests
        response = requests.post(
            webhook_url,
            json={"embeds": [embed], "allowed_mentions": {"parse": []}},
            timeout=10,
        )
        if not response.ok:
            print(f"⚠️ Discord webhook menolak ringkasan push C5 (HTTP {response.status_code}).")
            return False
        return True
    except Exception as exc:
        # Avoid logging exception text because HTTP clients can include the webhook URL.
        print(f"⚠️ Gagal mengirim ringkasan push C5 ke Discord ({type(exc).__name__}).")
        return False

def send_discord_error(platform: str, merchant: str, error_type: str, message: str, phone: str = ""):
    """
    Menyimpan informasi error ke folder data/discord_notifications 
    agar Discord Bot dapat memantaunya dan mengirim notifikasi cantik.
    """
    script_dir = Path(__file__).resolve().parent
    notif_dir = script_dir / "data" / "discord_notifications"
    notif_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = int(time.time() * 1000)
    filename = f"error_{platform}_{timestamp}.json"
    filepath = notif_dir / filename
    
    payload = {
        "status": "ERROR_NOTIF",
        "platform": platform,
        "merchant": merchant,
        "error_type": error_type,
        "message": message,
        "phone": phone,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "channel_id": os.environ.get("OFD_CHANNEL_ID", "")
    }
    
    try:
        with open(filepath, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"✅ Notifikasi error (PoC) telah disimpan untuk Discord: {filename}")
    except Exception as e:
        print(f"⚠️ Gagal menyimpan notifikasi Discord: {e}")
