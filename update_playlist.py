import requests
import time
import os
import re
import json
import subprocess
import sys

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

TIMEOUT = 25
PAGE_WAIT = 8  # seconds to wait for video player to load

browser = None


def get_chrome_binary():
    """Find Chrome binary path."""
    paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "google-chrome",
        "google-chrome-stable",
    ]
    for path in paths:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"[BROWSER] Found Chrome at: {path} ({result.stdout.strip()})")
                return path
        except Exception:
            continue
    return None


def init_browser():
    """Initialize headless Chrome with GitHub Actions compatible settings."""
    global browser
    if browser is not None:
        return browser

    print("[BROWSER] Initializing Chrome...")

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()

    # Core headless settings
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")

    # Window & display
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")

    # Anti-detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    # Performance
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")

    # Network logging to capture stream URLs
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # Set Chrome binary if found
    chrome_binary = get_chrome_binary()
    if chrome_binary:
        options.binary_location = chrome_binary

    try:
        service = Service(ChromeDriverManager().install())
        browser = webdriver.Chrome(service=service, options=options)
        browser.set_page_load_timeout(TIMEOUT)
        browser.implicitly_wait(5)
        print("[BROWSER] ✅ Chrome started successfully")
        return browser
    except Exception as e:
        print(f"[BROWSER] ❌ Failed: {e}")
        raise


def close_browser():
    global browser
    if browser:
        try:
            browser.quit()
        except Exception:
            pass
        browser = None


def extract_stream_from_logs(logs):
    """Extract m3u8 stream URL from Chrome performance logs."""
    stream_urls = []

    for entry in logs:
        try:
            log_data = json.loads(entry["message"])["message"]

            # Check both requests and responses
            if log_data["method"] in (
                "Network.requestWillBeSent",
                "Network.responseReceived",
            ):
                params = log_data["params"]

                # Get URL from request or response
                if "request" in params:
                    req_url = params["request"]["url"]
                elif "response" in params:
                    req_url = params["response"]["url"]
                else:
                    continue

                # Check if it's a stream URL
                if (
                    "m3u8" in req_url
                    and ("edge" in req_url or "mmcdn" in req_url or "live" in req_url)
                ):
                    stream_urls.append(req_url)

        except (KeyError, json.JSONDecodeError, ValueError):
            continue

    return stream_urls


def fetch_stream_with_selenium(model_name):
    """
    Use Selenium to open the model page and extract HLS stream URL.
    """
    url = f"{SITE_BASE}/cam/{model_name}"
    print(f"  → {url}")

    try:
        driver = init_browser()

        # Clear previous logs by navigating first
        driver.get("about:blank")
        time.sleep(0.5)

        # Load the model page
        driver.get(url)
        print(f"  Waiting {PAGE_WAIT}s for player to load...")
        time.sleep(PAGE_WAIT)

        # ── Method 1: Network performance logs ──
        print("  Checking network logs...")
        try:
            logs = driver.get_log("performance")
            stream_urls = extract_stream_from_logs(logs)

            if stream_urls:
                # Prefer llhls or m3u8 with token
                best = next(
                    (u for u in stream_urls if "token=" in u),
                    stream_urls[0]
                )
                print(f"  ✅ [Network Log] {best[:100]}...")
                return best
        except Exception as e:
            print(f"  [WARN] Log read failed: {e}")

        # ── Method 2: Page source regex ──
        print("  Checking page source...")
        page_source = driver.page_source

        patterns = [
            r'(https?://edge\d*[^"\'\s\\<>]+\.m3u8[^"\'\s\\<>]*)',
            r'(https?://[^"\'\s\\<>]*live\.mmcdn\.com[^"\'\s\\<>]+)',
            r'(https?://[^"\'\s\\<>]*mmcdn\.com[^"\'\s\\<>]+\.m3u8[^"\'\s\\<>]*)',
            r'(https?://[^"\'\s\\<>]+/llhls\.m3u8[^"\'\s\\<>]*)',
            r'(https?://[^"\'\s\\<>]+/playlist\.m3u8[^"\'\s\\<>]*)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, page_source, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                stream_url = stream_url.replace("\\u002F", "/").replace("\\/", "/")
                stream_url = re.sub(r'["\'\]}>\\]+$', '', stream_url)
                print(f"  ✅ [Page Source] {stream_url[:100]}...")
                return stream_url

        # ── Method 3: JavaScript extraction ──
        print("  Trying JS extraction...")
        try:
            result = driver.execute_script("""
                // Check video element
                var videos = document.querySelectorAll('video');
                for (var v of videos) {
                    if (v.src && v.src.includes('m3u8')) return v.src;
                    if (v.currentSrc && v.currentSrc.includes('m3u8')) return v.currentSrc;
                }

                // Check source elements
                var sources = document.querySelectorAll('video source');
                for (var s of sources) {
                    if (s.src && s.src.includes('m3u8')) return s.src;
                }

                // Check window-level variables
                var keys = ['hlsUrl','streamUrl','videoUrl','playUrl','liveUrl',
                            'streamSrc','playerSrc','liveSrc','m3u8Url'];
                for (var k of keys) {
                    if (window[k] && typeof window[k] === 'string') return window[k];
                }

                // Check nested objects
                if (window.playerConfig) {
                    var pc = window.playerConfig;
                    for (var k of ['hlsUrl','streamUrl','url','src','stream']) {
                        if (pc[k]) return pc[k];
                    }
                }

                if (window.__INITIAL_STATE__) {
                    return JSON.stringify(window.__INITIAL_STATE__);
                }

                if (window.__NEXT_DATA__) {
                    return JSON.stringify(window.__NEXT_DATA__);
                }

                if (window.Nuxt && window.Nuxt.state) {
                    return JSON.stringify(window.Nuxt.state);
                }

                return null;
            """)

            if result:
                if "m3u8" in str(result) or "mmcdn" in str(result):
                    # Extract URL if it's embedded in JSON string
                    url_matches = re.findall(
                        r'https?://[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*',
                        str(result), re.IGNORECASE
                    )
                    if url_matches:
                        stream_url = url_matches[0].replace("\\/", "/")
                        print(f"  ✅ [JS] {stream_url[:100]}...")
                        return stream_url
                    elif "mmcdn" in str(result):
                        url_matches = re.findall(
                            r'https?://[^\s"\'\\\]<>]*mmcdn[^\s"\'\\\]<>]+',
                            str(result), re.IGNORECASE
                        )
                        if url_matches:
                            stream_url = url_matches[0].replace("\\/", "/")
                            print(f"  ✅ [JS mmcdn] {stream_url[:100]}...")
                            return stream_url

        except Exception as e:
            print(f"  [WARN] JS extraction failed: {e}")

        # ── Method 4: Wait more and retry logs ──
        print("  Waiting 5 more seconds and retrying...")
        time.sleep(5)
        try:
            logs = driver.get_log("performance")
            stream_urls = extract_stream_from_logs(logs)
            if stream_urls:
                best = next((u for u in stream_urls if "token=" in u), stream_urls[0])
                print(f"  ✅ [Retry Log] {best[:100]}...")
                return best
        except Exception:
            pass

        # Check if offline
        page_lower = driver.page_source.lower()
        if any(x in page_lower for x in ["offline", "not online", "currently offline"]):
            print(f"  ❌ OFFLINE")
        else:
            print(f"  ❌ Stream not found")

        return None

    except Exception as e:
        print(f"  [ERROR] {e}")
        # Reset browser on error
        close_browser()
        return None


def fetch_live_models_from_site():
    """Scrape listing pages to discover live models."""
    all_models = []
    seen = set()

    pages = [
        (f"{SITE_BASE}/", "girl"),
        (f"{SITE_BASE}/?page=2", "girl"),
        (f"{SITE_BASE}/?page=3", "girl"),
        (f"{SITE_BASE}/couple", "couple"),
        (f"{SITE_BASE}/couple?page=2", "couple"),
    ]

    skip_words = {
        "girl", "couple", "trans", "guy", "login", "signup", "register",
        "terms", "privacy", "contact", "about", "faq", "help", "support",
        "search", "categories", "tags", "popular", "new", "top", "index",
        "page", "home", "cam", "category", "male", "female", "couples", "girls",
    }

    for page_url, category in pages:
        print(f"[SCRAPE] {page_url}")
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"  Status: {resp.status_code}")
                continue

            html = resp.text

            # Find /cam/username links
            cam_links = re.findall(
                r'href=["\'](?:https?://[^"\']*)?/cam/([a-zA-Z0-9_-]+)["\']',
                html, re.IGNORECASE
            )

            count = 0
            for name in cam_links:
                name = name.lower().strip().strip("-_")
                if (
                    name not in seen
                    and name not in skip_words
                    and len(name) >= 3
                    and len(name) <= 50
                    and re.match(r'^[a-z0-9_-]+$', name)
                ):
                    seen.add(name)
                    all_models.append({"name": name, "category": category})
                    count += 1

            print(f"  Found {count} new model(s)")
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")

    print(f"\n[SCRAPE] Total: {len(all_models)} models discovered")
    return all_models


def generate_m3u(favorite_live, other_live):
    lines = ["#EXTM3U"]
    lines.append(f"# Last updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Source: 2kcams.com")
    lines.append(f"# Favorites: {len(favorite_live)} live")
    lines.append(f"# Others: {len(other_live)} live")
    lines.append(f"# Total: {len(favorite_live) + len(other_live)}")
    lines.append("")

    for model, url in favorite_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="⭐ Favorites",⭐ {model}'
        )
        lines.append(url)

    for model, info in other_live.items():
        cat = info["category"].capitalize()
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="{cat}",{model}'
        )
        lines.append(info["url"])

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  Live Playlist Updater — 2kcams.com")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    try:
        # ── Load favorites ──
        favorite_names = load_models(MODELS_FILE)

        # ── Check favorites ──
        favorite_live = {}
        if favorite_names:
            print("\n" + "─" * 50)
            print("  FAVORITE MODELS")
            print("─" * 50)
            for model_name in favorite_names:
                print(f"\n[FAV] {model_name}")
                stream_url = fetch_stream_with_selenium(model_name)
                if stream_url:
                    favorite_live[model_name] = stream_url
                    print(f"  ✅ LIVE")
                else:
                    print(f"  ❌ offline")
                time.sleep(2)

        # ── Discover others ──
        print("\n" + "─" * 50)
        print("  DISCOVERING OTHER LIVE MODELS")
        print("─" * 50)

        discovered = fetch_live_models_from_site()
        fav_set = set(favorite_names)
        candidates = [m for m in discovered if m["name"] not in fav_set]
        print(f"\n[INFO] {len(candidates)} candidate(s) to check")

        other_live = {}
        MAX = 50

        for i, m in enumerate(candidates):
            if i >= MAX:
                print(f"\n[INFO] Reached limit ({MAX})")
                break

            name = m["name"]
            cat = m["category"]
            print(f"\n[{i+1}/{min(len(candidates), MAX)}] {name} ({cat})")

            stream_url = fetch_stream_with_selenium(name)
            if stream_url:
                other_live[name] = {"url": stream_url, "category": cat}
                print(f"  ✅ LIVE")

            time.sleep(1.5)

        # ── Save playlist ──
        playlist = generate_m3u(favorite_live, other_live)
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write(playlist)

        print("\n" + "=" * 60)
        print(f"  ⭐ Favorites: {len(favorite_live)}/{len(favorite_names)} live")
        print(f"  👥 Others:    {len(other_live)} live")
        print(f"  📺 Total:     {len(favorite_live) + len(other_live)}")
        print(f"  💾 Saved:     {PLAYLIST_FILE}")
        print("=" * 60)

    finally:
        close_browser()
        print("[BROWSER] Closed")


if __name__ == "__main__":
    main()
