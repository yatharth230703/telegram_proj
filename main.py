"""
Telethon Photo Batch Collector (Test-Ready)

Workflow:
1) Waits for a trigger message: "sending photos" (case-insensitive, whitespace-tolerant)
2) Collects ONLY photos (and optionally image-documents if you enable it)
3) Stops collecting on the first subsequent TEXT message (non-trigger) and treats it as:
      "City | Site"   or   "City - Site"
4) Creates folder:  output/<City> - <Site>/
5) Saves the collected photos into that folder (downloads directly there)

Setup:
- pip install telethon
- Fill api_id, api_hash
- Set TARGET_CHAT to your test group (username, invite link entity, or chat_id)
"""

from telethon import TelegramClient, events
import os
import re
import asyncio
from datetime import datetime
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv() 
# ----------------------------
# CONFIG
# ----------------------------
api_id = int(os.getenv("app_id"))               # <-- your api_id
api_hash = os.getenv("app_hash")      # <-- your api_hash

# You can set this to:
#  - the numeric chat_id (recommended after you print it once),
#  - or a username like "my_test_group",
#  - or leave None to listen to all chats while testing.
TARGET_CHAT =  -5024845521 # e.g. -1001234567890

TRIGGER_TEXT = "sending photos"

OUTPUT_ROOT = "output"          # all batches saved under this folder
DOWNLOAD_TEMP = os.path.join(OUTPUT_ROOT, "_inbox")  # temp download folder

# If True, also collect "document" images (e.g., someone sends as file)
ALLOW_IMAGE_DOCUMENTS = True


# ----------------------------
# INTERNAL STATE
# ----------------------------
collecting = False
batch_started_at: Optional[str] = None
downloaded_files = []  # list[str]


# ----------------------------
# HELPERS
# ----------------------------
INVALID_FS_CHARS = r'<>:"/\|?*\n\r\t'

import re
import unicodedata

def sanitize_name(name: str, max_len: int = 80) -> str:
    name = name.strip()

    # 1) Normalize Unicode (keeps Hindi, accented chars, etc.)
    name = unicodedata.normalize("NFKC", name)

    # 2) Replace ONLY characters the OS absolutely forbids
    # Windows forbids:  \ / : * ? " < > |
    name = re.sub(r'[\\/:*?"<>|]', '_', name)

    # 3) Collapse repeated underscores/spaces
    name = re.sub(r'\s+', ' ', name)   # multiple spaces → single space
    name = re.sub(r'_+', '_', name)    # multiple underscores → one

    # 4) Trim leftover garbage
    name = name.strip(' ._')

    # 5) Truncate if too long
    return name[:max_len]


def parse_city_site(text: str) -> Tuple[str, str]:
    """
    Parse "City | Site" or "City - Site".
    If parsing fails, use UnknownCity and the entire text as site.
    """
    info = text.strip()
    parts = re.split(r"\s*[|-]\s*", info, maxsplit=1)
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
        city = parts[0].strip()
        site = parts[1].strip()
    else:
        city = "UnknownCity"
        site = info if info else "UnknownSite"
    return sanitize_name(city), sanitize_name(site)


def is_trigger(text: str) -> bool:
    return text.strip().lower() == TRIGGER_TEXT


def is_photo_message(msg) -> bool:
    # True for native Telegram photos
    if msg.photo:
        return True

    # Optionally allow image documents
    if ALLOW_IMAGE_DOCUMENTS and msg.document:
        # Check mime type like "image/jpeg"
        mime = getattr(msg.document, "mime_type", "") or ""
        if mime.startswith("image/"):
            return True

    return False


def ensure_dirs():
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    os.makedirs(DOWNLOAD_TEMP, exist_ok=True)


def batch_folder(city: str, site: str, stamp: str) -> str:
    # include timestamp to prevent collisions if you repeat same city/site
    folder = f"{city} - {site}"
    folder = sanitize_name(folder)
    return os.path.join(OUTPUT_ROOT, f"{folder} ({stamp})")


# ----------------------------
# CLIENT
# ----------------------------
client = TelegramClient("session", api_id, api_hash)


@client.on(events.NewMessage(chats=TARGET_CHAT) if TARGET_CHAT is not None else events.NewMessage())
async def handler(event):
    global collecting, batch_started_at, downloaded_files

    ensure_dirs()

    msg = event.message
    text = (event.raw_text or "").strip()

    # Helpful during testing: print chat_id so you can set TARGET_CHAT later.
    # You can remove this after you set TARGET_CHAT.
    if text:
        print(f"[chat_id={event.chat_id}] text: {text}")

    # 1) Trigger starts collection
    if text and is_trigger(text):
        collecting = True
        downloaded_files = []
        batch_started_at = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        print("🟢 Started collecting photos for a new batch.")
        print(f"   Batch stamp: {batch_started_at}")
        return

    # 2) While collecting, download ONLY photos (and optional image documents)
    if collecting and is_photo_message(msg):
        try:
            # Download into temp inbox first so we control location
            file_path = await msg.download_media(file=DOWNLOAD_TEMP)
            if file_path:
                downloaded_files.append(file_path)
                print(f"📥 Collected: {file_path}")
        except Exception as e:
            print(f"⚠️ Download failed: {e}")
        return

    # 3) If collecting and a non-trigger TEXT arrives, treat it as city/site and finalize
    if collecting and text:
        city, site = parse_city_site(text)
        stamp = batch_started_at or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest_folder = batch_folder(city, site, stamp)
        os.makedirs(dest_folder, exist_ok=True)

        moved = 0
        for src in downloaded_files:
            try:
                base = os.path.basename(src)
                # Avoid name collisions inside the folder
                dst = os.path.join(dest_folder, base)
                if os.path.exists(dst):
                    root, ext = os.path.splitext(base)
                    dst = os.path.join(dest_folder, f"{root}_{moved}{ext}")
                os.replace(src, dst)  # atomic move on same filesystem
                moved += 1
            except Exception as e:
                print(f"⚠️ Move failed for {src}: {e}")

        print("📁 Finished batch:")
        print(f"   City: {city}")
        print(f"   Site: {site}")
        print(f"   Saved: {moved} file(s) → {dest_folder}")

        # Reset state
        collecting = False
        batch_started_at = None
        downloaded_files = []
        return


async def main():
    print("✅ Telethon Photo Batch Collector is running...")
    print(f"Trigger text: '{TRIGGER_TEXT}'")
    print("Test steps:")
    print("  1) Send:  sending photos")
    print("  2) Send a bunch of photos")
    print("  3) Send:  City | Site   (example: Mumbai | Gateway of India)")
    print("Photos will be saved under:", os.path.abspath(OUTPUT_ROOT))
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())