import requests
import time
import os
import re
import json
import subprocess

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
MODELS_FILE   = "models.txt"
PLAYLIST_FILE = "playlist.m3u"
SITE_BASE     = "https://www.2kcams.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.2kcams.com/",
}

PAGE_WAIT  = 8   # seconds to wait for video player
TIMEOUT    = 25
MAX_OTHERS = 50  # max other models to check

# ─────────────────────────────────────────
#  BROWSER
# ─────────────────────────────────────────
browser = None


def get_chrome_binary():
    paths = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for path in paths:
        try:
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                print(f"[BROWSER] Chrome: {path} ({r.stdout.strip()})")
                return path
        except Exception:
            continue
    return None


def init_browser():
    global browser
    if browser is not None:
        return browser

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    print("[BROWSER] Starting Chrome...")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Enable network log capture
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    chrome_bin = get_chrome_binary()
    if chrome_bin:
        options.binary_location = chrome_bin

    service = Service(ChromeDriverManager().install())
    browser = webdriver.Chrome(service=service, options=options)
    browser.set_page_load_timeout(TIMEOUT)

    print("[BROWSER] ✅ Chrome ready")
    return browser


def close_browser():
    global browser
    if browser:
        try:
            browser.quit()
        except Exception:
            pass
        browser = None
        print("[BROWSER] Closed")


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def load_models(filepath):
    """Load comma-separated model names from txt file."""
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [n.strip().lower() for n in content.split(",") if n.strip()]
    print(f"[INFO] Loaded {len(models)} favorite(s): {models}")
    return models


def extract_stream_from_logs(logs):
    """Pull m3u8 URLs out of Chrome performance logs."""
    found = []
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg["method"] in ("Network.requestWillBeSent", "Network.responseReceived"):
                params = msg["params"]
                url = (
                    params.get("request", {}).get("url")
                    or params.get("response", {}).get("url")
                    or ""
                )
                if "m3u8" in url and any(x in url for x in ("edge", "mmcdn", "live")):
                    found.append(url)
        except Exception:
            continue
    return found


# ─────────────────────────────────────────
#  STREAM FETCHER
# ─────────────────────────────────────────
def fetch_stream(model_name):
    """
    Open model page in headless Chrome and extract HLS stream URL.
    Returns stream URL string or None.
    """
    page_url = f"{SITE_BASE}/cam/{model_name}"
    print(f"  Loading: {page_url}")

    try:
        driver = init_browser()

        # Clear logs from previous page
        driver.get("about:blank")
        time.sleep(0.3)

        # Load model page
        try:
            driver.get(page_url)
        except Exception as e:
            print(f"  [WARN] Page load timeout (continuing): {e}")

        print(f"  Waiting {PAGE_WAIT}s for player...")
        time.sleep(PAGE_WAIT)

        # ── Method 1: Network logs ──
        try:
            logs  = driver.get_log("performance")
            urls  = extract_stream_from_logs(logs)
            if urls:
                best = next((u for u in urls if "token=" in u), urls[0])
                print(f"  ✅ [Network] {best[:100]}...")
                return best
        except Exception as e:
            print(f"  [WARN] Log read: {e}")

        # ── Method 2: Page source regex ──
        source = driver.page_source
        patterns = [
            r'(https?://edge\d*-[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]*live\.mmcdn\.com[^\s"\'\\\]<>]+m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]*mmcdn\.com[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+/llhls\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+/playlist\.m3u8[^\s"\'\\\]<>]*)',
        ]
        for pat in patterns:
            hits = re.findall(pat, source, re.IGNORECASE)
            if hits:
                clean = hits[0].replace("\\u002F", "/").replace("\\/", "/")
                clean = re.sub(r'["\'\]}>\\]+$', '', clean)
                print(f"  ✅ [Source] {clean[:100]}...")
                return clean

        # ── Method 3: JS extraction ──
        try:
            result = driver.execute_script("""
                // Video element
                for (var v of document.querySelectorAll('video')) {
                    if (v.src && v.src.includes('m3u8')) return v.src;
                    if (v.currentSrc && v.currentSrc.includes('m3u8')) return v.currentSrc;
                }
                // Source elements
                for (var s of document.querySelectorAll('video source')) {
                    if (s.src && s.src.includes('m3u8')) return s.src;
                }
                // Window variables
                var keys = ['hlsUrl','streamUrl','videoUrl','playUrl','liveUrl','streamSrc'];
                for (var k of keys) {
                    if (window[k] && typeof window[k] === 'string') return window[k];
                }
                // Next.js / Nuxt state
                if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
                if (window.__NUXT__) return JSON.stringify(window.__NUXT__);
                if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__);
                return null;
            """)

            if result:
                hits = re.findall(
                    r'https?://[^\s"\'\\\]<>]+(?:m3u8|mmcdn)[^\s"\'\\\]<>]*',
                    str(result), re.IGNORECASE
                )
                if hits:
                    clean = hits[0].replace("\\/", "/")
                    print(f"  ✅ [JS] {clean[:100]}...")
                    return clean
        except Exception as e:
            print(f"  [WARN] JS: {e}")

        # ── Method 4: Extra wait + retry logs ──
        print("  Waiting 5 more seconds...")
        time.sleep(5)
        try:
            logs = driver.get_log("performance")
            urls = extract_stream_from_logs(logs)
            if urls:
                best = next((u for u in urls if "token=" in u), urls[0])
                print(f"  ✅ [Retry] {best[:100]}...")
                return best
        except Exception:
            pass

        # Offline check
        low = driver.page_source.lower()
        if any(x in low for x in ("offline", "not online", "currently offline")):
            print("  ❌ OFFLINE")
        else:
            print("  ❌ Stream not found")

        return None

    except Exception as e:
        print(f"  [ERROR] {e}")
        close_browser()   # reset on crash
        return None


# ─────────────────────────────────────────
#  SITE SCRAPER
# ─────────────────────────────────────────
SKIP_WORDS = {
    "girl", "couple", "trans", "guy", "login", "signup", "register",
    "terms", "privacy", "contact", "about", "faq", "help", "support",
    "search", "categories", "tags", "popular", "new", "top", "index",
    "page", "home", "cam", "category", "male", "female", "couples", "girls",
}

PAGES = [
    (f"{SITE_BASE}/",             "girl"),
    (f"{SITE_BASE}/?page=2",      "girl"),
    (f"{SITE_BASE}/?page=3",      "girl"),
    (f"{SITE_BASE}/couple",       "couple"),
    (f"{SITE_BASE}/couple?page=2","couple"),
]


def fetch_discovered_models():
    """Scrape listing pages and return list of {name, category} dicts."""
    all_models = []
    seen       = set()

    for page_url, category in PAGES:
        print(f"[SCRAPE] {page_url}")
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
                continue

            links = re.findall(
                r'href=["\'](?:https?://[^"\']*)?/cam/([a-zA-Z0-9_-]+)["\']',
                resp.text, re.IGNORECASE
            )

            count = 0
            for name in links:
                name = name.lower().strip().strip("-_")
                if (
                    name not in seen
                    and name not in SKIP_WORDS
                    and 3 <= len(name) <= 50
                    and re.match(r'^[a-z0-9_-]+$', name)
                ):
                    seen.add(name)
                    all_models.append({"name": name, "category": category})
                    count += 1

            print(f"  +{count} models")
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")

    print(f"[SCRAPE] Total discovered: {len(all_models)}")
    return all_models


# ─────────────────────────────────────────
#  PLAYLIST WRITER
# ─────────────────────────────────────────
def generate_m3u(favorite_live: dict, other_live: dict) -> str:
    lines = [
        "#EXTM3U",
        f"# Updated : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"# Source  : 2kcams.com",
        f"# Favs    : {len(favorite_live)}",
        f"# Others  : {len(other_live)}",
        f"# Total   : {len(favorite_live) + len(other_live)}",
        "",
    ]

    # Favorites first
    for model, url in favorite_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="⭐ Favorites",⭐ {model}'
        )
        lines.append(url)

    # Others by category
    for model, info in other_live.items():
        cat = info["category"].capitalize()
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="{cat}",{model}'
        )
        lines.append(info["url"])

    return "\n".join(lines)


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Live Playlist Updater — 2kcams.com")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    try:
        # 1. Load favorites
        favorite_names = load_models(MODELS_FILE)

        # 2. Check each favorite
        favorite_live = {}
        if favorite_names:
            print("\n" + "─" * 50)
            print("  FAVORITE MODELS")
            print("─" * 50)
            for name in favorite_names:
                print(f"\n[FAV] {name}")
                url = fetch_stream(name)
                if url:
                    favorite_live[name] = url
                    print(f"  → LIVE ✅")
                else:
                    print(f"  → offline ❌")
                time.sleep(2)

        # 3. Discover other live models
        print("\n" + "─" * 50)
        print("  OTHER LIVE MODELS  (girl / couple)")
        print("─" * 50)

        discovered = fetch_discovered_models()
        fav_set    = set(favorite_names)
        candidates = [m for m in discovered if m["name"] not in fav_set]
        print(f"[INFO] {len(candidates)} candidate(s) to check")

        other_live = {}
        for i, m in enumerate(candidates):
            if i >= MAX_OTHERS:
                print(f"[INFO] Limit reached ({MAX_OTHERS})")
                break

            name = m["name"]
            cat  = m["category"]
            print(f"\n[{i+1}/{min(len(candidates), MAX_OTHERS)}] {name} ({cat})")

            url = fetch_stream(name)
            if url:
                other_live[name] = {"url": url, "category": cat}
                print(f"  → LIVE ✅")

            time.sleep(1.5)

        # 4. Write playlist
        playlist = generate_m3u(favorite_live, other_live)
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write(playlist)

        # 5. Summary
        print("\n" + "=" * 60)
        print(f"  ⭐ Favorites : {len(favorite_live)}/{len(favorite_names)} live")
        for n in favorite_names:
            mark = "✅" if n in favorite_live else "❌"
            print(f"     {mark} {n}")
        print(f"  👥 Others    : {len(other_live)} live")
        print(f"  📺 Total     : {len(favorite_live) + len(other_live)}")
        print(f"  💾 Saved     : {PLAYLIST_FILE}")
        print("=" * 60)

    finally:
        close_browser()


if __name__ == "__main__":
    main()
