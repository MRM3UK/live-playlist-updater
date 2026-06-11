import requests
import time
import os
import re
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

MODELS_FILE = "models.txt"
PLAYLIST_FILE = "playlist.m3u"
SITE_BASE = "https://www.2kcams.com"
ALLOWED_CATEGORIES = ["girl", "couple"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.2kcams.com/",
}

TIMEOUT = 20

# Global browser instance
browser = None


def init_browser():
    """Initialize headless Chrome browser."""
    global browser
    if browser is not None:
        return browser

    print("[BROWSER] Initializing headless Chrome...")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    # Disable images/css for faster loading
    prefs = {
        "profile.managed_default_content_settings.images": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # Enable performance logging to capture network requests
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    browser = webdriver.Chrome(service=service, options=options)
    browser.set_page_load_timeout(TIMEOUT)

    print("[BROWSER] Chrome initialized")
    return browser


def close_browser():
    """Close browser instance."""
    global browser
    if browser:
        browser.quit()
        browser = None


def load_models(filepath):
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [name.strip().lower() for name in content.split(",") if name.strip()]
    print(f"[INFO] Loaded {len(models)} favorite model(s): {models}")
    return models


def fetch_stream_with_selenium(model_name):
    """
    Use Selenium to load the page and extract the m3u8 stream URL
    from network requests or page source.
    """
    global browser
    url = f"{SITE_BASE}/cam/{model_name}"
    print(f"  Loading: {url}")

    try:
        browser = init_browser()
        browser.get(url)

        # Wait for page to load and video player to initialize
        time.sleep(5)

        stream_url = None

        # ── Method 1: Check network logs for m3u8 requests ──
        try:
            logs = browser.get_log("performance")
            for entry in logs:
                try:
                    log_data = json.loads(entry["message"])["message"]
                    if log_data["method"] == "Network.requestWillBeSent":
                        req_url = log_data["params"]["request"]["url"]
                        if "m3u8" in req_url and ("edge" in req_url or "mmcdn" in req_url):
                            print(f"  ✅ Found in network logs: {req_url[:100]}...")
                            stream_url = req_url
                            break
                except (KeyError, json.JSONDecodeError):
                    continue
        except Exception as e:
            print(f"  [WARN] Could not read network logs: {e}")

        if stream_url:
            return stream_url

        # ── Method 2: Check page source after JS execution ──
        page_source = browser.page_source

        m3u8_patterns = [
            r'(https?://edge[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]*\.live\.mmcdn\.com[^\s"\'\\\]<>]+)',
            r'(https?://[^\s"\'\\\]<>]*mmcdn[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+/llhls\.m3u8[^\s"\'\\\]<>]*)',
        ]

        for pattern in m3u8_patterns:
            matches = re.findall(pattern, page_source, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                # Clean up escaped characters
                stream_url = stream_url.replace("\\u002F", "/").replace("\\/", "/")
                stream_url = re.sub(r'["\'\]\)}>\\]+$', '', stream_url)
                print(f"  ✅ Found in page source: {stream_url[:100]}...")
                return stream_url

        # ── Method 3: Execute JS to get video source ──
        try:
            video_src = browser.execute_script("""
                var video = document.querySelector('video');
                if (video && video.src) return video.src;
                
                var source = document.querySelector('video source');
                if (source && source.src) return source.src;
                
                // Check for HLS.js
                if (typeof Hls !== 'undefined') {
                    var hlsInstances = document.querySelectorAll('video');
                    for (var v of hlsInstances) {
                        if (v.hlsPlayer && v.hlsPlayer.url) return v.hlsPlayer.url;
                    }
                }
                
                // Check common player variables
                if (typeof hlsUrl !== 'undefined') return hlsUrl;
                if (typeof streamUrl !== 'undefined') return streamUrl;
                if (typeof videoUrl !== 'undefined') return videoUrl;
                
                // Check window object
                if (window.hlsUrl) return window.hlsUrl;
                if (window.streamUrl) return window.streamUrl;
                if (window.playerConfig && window.playerConfig.hlsUrl) return window.playerConfig.hlsUrl;
                
                return null;
            """)
            if video_src and "m3u8" in video_src:
                print(f"  ✅ Found via JS execution: {video_src[:100]}...")
                return video_src
        except Exception as e:
            print(f"  [WARN] JS execution failed: {e}")

        # ── Method 4: Check for offline status ──
        page_lower = page_source.lower()
        if any(x in page_lower for x in ["offline", "is not online", "currently offline", "room is offline"]):
            print(f"  ❌ Model is OFFLINE")
            return None

        print(f"  ❌ No stream URL found")
        return None

    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def fetch_live_models_from_site():
    """Scrape listing pages to discover live models."""
    all_models = []
    seen = set()

    category_urls = {
        "girl": [
            f"{SITE_BASE}/",
            f"{SITE_BASE}/?page=2",
            f"{SITE_BASE}/?page=3",
        ],
        "couple": [
            f"{SITE_BASE}/couple",
            f"{SITE_BASE}/couple?page=2",
        ],
    }

    for category, urls in category_urls.items():
        for page_url in urls:
            print(f"[SCRAPE] {page_url}")
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue

                html = resp.text

                # Find /cam/username links
                cam_links = re.findall(
                    r'href=["\'](?:https?://[^"\']*)?/cam/([a-zA-Z0-9_-]+)["\']',
                    html, re.IGNORECASE
                )

                # Extract from stream URLs
                stream_names = re.findall(
                    r'origin\.([a-zA-Z0-9_]+)\.',
                    html, re.IGNORECASE
                )

                all_names = cam_links + stream_names

                skip_words = {
                    "girl", "couple", "trans", "guy", "login", "signup",
                    "register", "terms", "privacy", "contact", "about",
                    "faq", "help", "support", "search", "categories",
                    "tags", "popular", "new", "top", "index", "page",
                    "home", "cam", "category", "male", "female",
                }

                count = 0
                for name in all_names:
                    name = name.lower().strip()
                    if (
                        name not in seen
                        and name not in skip_words
                        and len(name) >= 3
                        and len(name) <= 50
                        and re.match(r'^[a-z0-9_-]+$', name)
                    ):
                        seen.add(name)
                        all_models.append({
                            "name": name,
                            "category": category,
                        })
                        count += 1

                print(f"  Found {count} new model(s)")
                time.sleep(0.5)

            except Exception as e:
                print(f"  Error: {e}")

    print(f"\n[SCRAPE] Total discovered: {len(all_models)} models")
    return all_models


def generate_m3u(favorite_live, other_live):
    """Generate M3U playlist."""
    lines = ["#EXTM3U"]
    lines.append(f"# Last updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Source: 2kcams.com")
    lines.append(f"# Favorites live: {len(favorite_live)}")
    lines.append(f"# Others live: {len(other_live)}")
    lines.append(f"# Total: {len(favorite_live) + len(other_live)}")
    lines.append("")

    # Favorites first (with star)
    for model, url in favorite_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="⭐ Favorites",⭐ {model}'
        )
        lines.append(url)

    # Others by category
    for model, info in other_live.items():
        cat_label = info["category"].capitalize()
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="{cat_label}",{model}'
        )
        lines.append(info["url"])

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  Live Playlist Updater (2kcams.com)")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    try:
        # ─── Load favorites ───
        favorite_names = load_models(MODELS_FILE)

        # ─── Check favorites ───
        favorite_live = {}
        print("\n" + "─" * 50)
        print("  CHECKING FAVORITE MODELS")
        print("─" * 50)

        for model_name in favorite_names:
            print(f"\n[FAV] {model_name}")
            stream_url = fetch_stream_with_selenium(model_name)
            if stream_url:
                favorite_live[model_name] = stream_url
            time.sleep(1)

        # ─── Discover other live models ───
        print("\n" + "─" * 50)
        print("  DISCOVERING OTHER LIVE MODELS")
        print("─" * 50)

        discovered = fetch_live_models_from_site()
        fav_set = set(favorite_names)
        other_candidates = [m for m in discovered if m["name"] not in fav_set]

        print(f"\n[INFO] {len(other_candidates)} other candidate(s)")

        other_live = {}
        max_others = 50  # Limit to avoid long runtime

        for i, model_info in enumerate(other_candidates):
            if i >= max_others:
                print(f"\n[INFO] Reached limit of {max_others}")
                break

            model_name = model_info["name"]
            category = model_info["category"]

            print(f"\n[OTHER {i+1}/{min(len(other_candidates), max_others)}] {model_name} ({category})")
            stream_url = fetch_stream_with_selenium(model_name)

            if stream_url:
                other_live[model_name] = {
                    "url": stream_url,
                    "category": category,
                }

            time.sleep(1)

        # ─── Generate playlist ───
        print("\n" + "─" * 50)
        print("  RESULTS")
        print("─" * 50)

        playlist = generate_m3u(favorite_live, other_live)

        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write(playlist)

        print(f"\n  ⭐ Favorites live: {len(favorite_live)}/{len(favorite_names)}")
        for name in favorite_live:
            print(f"     ✅ {name}")
        for name in favorite_names:
            if name not in favorite_live:
                print(f"     ❌ {name} (offline)")

        print(f"\n  👥 Others live: {len(other_live)}")

        print(f"\n  📺 Total: {len(favorite_live) + len(other_live)}")
        print(f"\n[SAVED] {PLAYLIST_FILE}")

    finally:
        close_browser()


if __name__ == "__main__":
    main()
