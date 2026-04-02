"""
Scraper core — all TikTok UI automation logic.

This module is a clean extraction of the original automator_mobile.py.
It is stateless: every public function receives the uiautomator2 device
handle `d` as its first argument so it can be driven by any caller
(worker task, CLI, tests).
"""

import logging
import re
import time

import requests
import uiautomator2 as u2

import config

logger = logging.getLogger(__name__)


# ── Low-level UI helpers ──────────────────────────────────────────────────────

def safe_click(d: u2.Device, timeout: int = 5, **kwargs) -> bool:
    """Click a UI element if it exists within *timeout* seconds."""
    
    # Convert resourceId prefix to a regex match automatically
    if "resourceId" in kwargs:
        resource_id = kwargs.pop("resourceId")
        stable_prefix = resource_id[:-3]  # drop last 3 chars
        kwargs["resourceIdMatches"] = re.escape(stable_prefix) + ".{3}"
    
    el = d(**kwargs)
    if el.exists(timeout=timeout):
        el.click()
        time.sleep(1)
        return True
    return False


# ── Device connection ─────────────────────────────────────────────────────────

def connect_device(serial: str) -> u2.Device:
    """
    Connect to a specific Android device by ADB serial.

    Raises `RuntimeError` if the connection fails.
    """
    logger.info("Connecting to device %s …", serial)
    d = u2.connect(serial)
    product = d.info.get("productName", "unknown")
    logger.info("Connected to %s (%s)", serial, product)
    return d


# ── TikTok navigation ─────────────────────────────────────────────────────────

def open_search(d: u2.Device) -> None:
    """Tap the TikTok search icon."""
    logger.debug("Opening search bar …")
    search_selectors = [
        {"description": "Search"},
        {"resourceId": f"{config.TIKTOK_PKG}:id/search"},
        {"resourceId": f"{config.TIKTOK_PKG}:id/iv_search"},
        {"text": "Search"},
    ]
    for sel in search_selectors:
        el = d(**sel)
        if el.exists(timeout=2):
            el.click()
            time.sleep(2)
            return
    raise RuntimeError("Could not find Search button — TikTok UI may have changed.")


def type_keyword(d: u2.Device, keyword: str) -> None:
    """Type *keyword* into the search field and submit."""
    logger.debug("Typing keyword: %r", keyword)
    input_selectors = [
        {"resourceId": f"{config.TIKTOK_PKG}:id/et_search_kw"},
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
    raise RuntimeError("Could not find search input field.")


def goto_videos_tab(d: u2.Device) -> None:
    """Navigate to the Videos tab in search results."""
    logger.debug("Navigating to Videos tab …")
    safe_click(d, description="Videos")
    time.sleep(2)


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


# ── Video link extraction ─────────────────────────────────────────────────────

def _expand_url(short_url: str) -> str:
    """Resolve a TikTok short URL to its canonical form via the FAIR API."""
    try:
        response = requests.post(
            "https://api.fair-studio.com/helper/expand-url",
            json={"url": short_url},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["url"]
    except requests.exceptions.Timeout:
        logger.warning("URL expansion timed out for %s — using original.", short_url)
        return short_url
    except requests.exceptions.RequestException as exc:
        logger.warning("URL expansion failed (%s) — using original.", exc)
        return short_url


def _extract_video_id_from_url(url: str) -> str | None:
    """Pull the numeric video ID out of a TikTok URL."""
    match = re.search(r'/video/(\d{15,20})', url)
    return match.group(1) if match else None


def collect_video_ids(d: u2.Device) -> list[str]:
    """
    Open each video in the search result grid, copy its share link,
    resolve it, and extract the video ID.

    Returns a deduplicated list of video IDs in discovery order.
    """
    video_ids: list[str] = []
    seen: set[str] = set()
    last_link = ""

    grid = d(className="android.widget.GridView")
    if not grid.exists:
        logger.error("GridView not found — cannot collect videos.")
        return video_ids

    grid.child(index=0).click()
    time.sleep(2)

    while True:
        try:
            logger.debug("Collecting video %d …", len(video_ids) + 1)
            safe_click(d, descriptionContains="Share")
            time.sleep(1)
            safe_click(d, description="Copy link")

            link: str = d.clipboard
            expanded = _expand_url(link)

            # Detect end-of-feed: same link twice in a row
            if expanded == last_link:
                logger.info("Reached end of feed after %d videos.", len(video_ids))
                break
            last_link = expanded

            vid_id = _extract_video_id_from_url(expanded)
            if vid_id and vid_id not in seen:
                seen.add(vid_id)
                video_ids.append(vid_id)
                logger.info("Collected video ID: %s", vid_id)

        except Exception as exc:
            logger.warning("Error during share flow: %s", exc)

        # Swipe to next video
        d.swipe(0.5, 0.8, 0.5, 0.2, duration=0.3)
        time.sleep(config.SCROLL_DELAY)

    return video_ids


# ── Top-level scrape entry point ──────────────────────────────────────────────

def run_scrape(serial: str, hashtag: str) -> list[str]:
    """
    Full scrape pipeline for one device + hashtag.

    1. Connect to *serial*
    2. Search for *hashtag*
    3. Apply latest filter
    4. Collect all video IDs
    5. Return the list

    Raises on any unrecoverable error (caller decides what to do).
    """
    logger.info("[%s] Starting scrape for hashtag=%r", serial, hashtag)
    d = connect_device(serial)

    open_search(d)
    type_keyword(d, hashtag)
    time.sleep(2)
    goto_videos_tab(d)
    time.sleep(2)
    apply_latest_filter(d)
    time.sleep(2)

    video_ids = collect_video_ids(d)
    logger.info("[%s] Scrape complete — %d video IDs collected.", serial, len(video_ids))
    return video_ids
