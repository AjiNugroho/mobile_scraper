"""
TikTok Android Automation — LEGACY STANDALONE SCRIPT
=====================================================
This file is kept for reference and quick local testing only.

For the production distributed system see:
  - config.py          — environment-based configuration
  - scraper_core.py    — all UI automation logic (extracted from here)
  - device_manager.py  — ADB device discovery and exclusive locking
  - models.py          — SQLAlchemy ORM + PostgreSQL persistence
  - worker.py          — Celery task definition and application factory

Requirements (standalone):
    pip install uiautomator2
    python -m uiautomator2 init   (run once, with phone connected)

Usage (standalone):
    python automator_mobile.py
"""

import re
import time
import json
import requests
import uiautomator2 as u2


# ─── CONFIG ────────────────────────────────────────────────────────────────────
KEYWORD        = "#wardah"   # <-- change this
SCROLL_TIMES   = 10                     # how many times to scroll
SCROLL_DELAY   = 1.8                    # seconds between scrolls (avoid detection)
OUTPUT_FILE    = "video_ids.json"
TIKTOK_PKG     = "com.zhiliaoapp.musically"  # change to com.ss.android.ugc.trill if needed
VIDEO_PER_SCREEN = 10
SCROLL_DELAY = 5
# ───────────────────────────────────────────────────────────────────────────────

def safe_click(d, timeout=5, **kwargs):
    """safely click a button"""
    el = d(**kwargs)
    if el.exists(timeout=timeout):
        el.click()
        time.sleep(1)
        return True
    return False
    
def connect_device():
    """connecting to mobile device"""
    print("🔌 Connecting to device...")
    d = u2.connect()
    print(f"✅ Connected: {d.info['productName']}")
    return d

def open_search(d):
    "open search bar"
    print("🔍 Opening search...")

    # Try common search icon resource IDs / descriptions
    search_selectors = [
        {"description": "Search"},
        {"resourceId": f"{TIKTOK_PKG}:id/search"},
        {"resourceId": f"{TIKTOK_PKG}:id/iv_search"},
        {"text": "Search"},
    ]

    for sel in search_selectors:
        el = d(**sel)
        if el.exists(timeout=2):
            el.click()
            time.sleep(2)
            return

    raise RuntimeError("❌ Could not find Search button. TikTok UI may have changed.")


def type_keyword(d, keyword):
    """typing the keyword"""
    print(f"⌨️  Typing keyword: '{keyword}'")

    # Find the search input field
    input_selectors = [
        {"resourceId": f"{TIKTOK_PKG}:id/et_search_kw"},
        {"focused": True},
        {"className": "android.widget.EditText"},
    ]

    for sel in input_selectors:
        el = d(**sel)
        if el.exists(timeout=2):
            el.set_text(keyword)
            time.sleep(1)
            d.press("enter")
            time.sleep(3)
            return

    raise RuntimeError("❌ Could not find search input field.")


def apply_latest_filter(d):
    """applying to the latest filters"""
    print("🗂️ Applying filter...")

    if not safe_click(d, description="More"):
        return

    if not safe_click(d, descriptionContains="Filter"):
        return

    if not safe_click(
        d,
        resourceId="com.ss.android.ugc.trill:id/eeq",
        text="Date posted"
    ):
        return
    
    if not safe_click(
        d,
        resourceId="com.ss.android.ugc.trill:id/eeq",
        text="Past 24 hours"
    ):
        return

    safe_click(d, description="Apply")
    print("✅ Done.")

def goto_videos_tab(d):
    """action navigating to videos tab"""
    print("Navigating to Videos tab...")

    if not safe_click(d, description="Videos"):
        return
    time.sleep(2)
    print("✅ Done.")


def extract_video_ids(xml_text):
    """Pull TikTok video IDs from the UI XML dump."""

    print(xml_text)
    # Video IDs appear in URLs like /video/7123456789012345678
    ids = re.findall(r'/video/(\d{15,20})', xml_text)
    # Also try content-desc patterns
    ids += re.findall(r'video_id[=:/](\d{15,20})', xml_text, re.IGNORECASE)
    return set(ids)

def video_link_getter(url):
    """get url from api request"""
    try:
        apiurl = "https://api.fair-studio.com/helper/expand-url"
        payload = json.dumps({
            "url": url
        })
        headers = {
        'Content-Type': 'application/json'
        }

        response = requests.request("POST", apiurl, headers=headers, data=payload,timeout=10)

        response.raise_for_status()
        data = response.json()

        return data['url']
    
    except requests.exceptions.Timeout:
        print("Request timeout")
        return url

    except requests.exceptions.RequestException as e:
        print("Request failed:", e)
        return url


def collect_video_links(d):
    """start scroll and collect videos"""
    links = []
    last_link = ''

    # 1️⃣ Click first item inside GridView
    grid = d(className="android.widget.GridView")

    if not grid.exists:
        print("❌ GridView not found")
        return links

    grid.child(index=0).click()
    time.sleep(2)

    # print("🎬 Opened first video")

    while True:
        try:
            print(f"\n========== VIDEO {len(links)+1} ==========")
            safe_click(d, descriptionContains="Share")
            time.sleep(1)
            safe_click(d, description="Copy link")

            link = d.clipboard

            url_link = video_link_getter(link)

            links.append(url_link)
            
            if(url_link==last_link):
                break

            last_link=url_link

            print("🔗 get:", url_link)

        except Exception as e:
            print("⚠️ Error during share flow:", e)

        # Swipe to next video
        d.swipe(0.5, 0.8, 0.5, 0.2, duration=0.3)
        
        time.sleep(SCROLL_DELAY)
        
    return links

def save_results(ids):
    """saving result to a file output"""
    data = sorted(list(ids))
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n💾 Saved {len(data)} video IDs to '{OUTPUT_FILE}'")
    return data

def main():
    """main process"""
    print("=" * 50)
    print("   TikTok Automation — Video ID Collector")
    print("=" * 50)

    d = connect_device()
    # launch_tiktok(d)
    open_search(d)
    type_keyword(d, KEYWORD)
    time.sleep(2)
    goto_videos_tab(d)
    time.sleep(2)
    apply_latest_filter(d)
    time.sleep(2)
    ids = collect_video_links(d)
    results = save_results(ids)

    print(f"\n🎉 Done! Collected {len(results)} unique video IDs.")
    print("=" * 50)


if __name__ == "__main__":
    main()
