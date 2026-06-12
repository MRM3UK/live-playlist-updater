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
SITE_BASE     = "https://booble.com"
AVATAR_BASE   = "https://booble.com/avatar"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://booble.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGE_WAIT  = 10
TIMEOUT    = 30
TOP_N      = 20

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
    for p in paths:
        try:
            r = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                print(f"[BROWSER] Chrome: {p} ({r.stdout.strip()})")
                return p
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
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [n.strip() for n in content.split(",") if n.strip()]
    print(f"[INFO] Loaded {len(models)} favorite(s): {models}")
    return models


def get_avatar_url(model_name):
    """
    Try multiple avatar URL formats and return the first working one.
    """
    extensions = [".jpeg", ".jpg", ".png", ".webp"]
    for ext in extensions:
        avatar_url = f"{AVATAR_BASE}/{model_name}{ext}"
        try:
            resp = requests.head(avatar_url, headers=HEADERS, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "").lower()
                if "image" in ct or resp.status_code == 200:
                    return avatar_url
        except Exception:
            continue

    # Fallback: try without checking (some servers block HEAD)
    return f"{AVATAR_BASE}/{model_name}.jpeg"


def extract_stream_from_logs(logs):
    """Extract m3u8/hls stream URLs from Chrome performance logs."""
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
                if ".m3u8" in url and any(k in url for k in (
                    "edge", "hls", "saawsedge", "master", "live", "stream", "cdn"
                )):
                    found.append(url)
        except Exception:
            continue
    return found


# ─────────────────────────────────────────
#  STREAM FETCHER
# ─────────────────────────────────────────
def fetch_stream(model_name):
    """
    Open booble.com/{model_name} in headless Chrome,
    wait for HLS player, capture the m3u8 URL.
    """
    page_url = f"{SITE_BASE}/{model_name}"
    print(f"  Loading: {page_url}")

    try:
        driver = init_browser()

        driver.get("about:blank")
        time.sleep(0.3)

        try:
            driver.get(page_url)
        except Exception as e:
            print(f"  [WARN] Page load issue: {e}")

        print(f"  Waiting {PAGE_WAIT}s for player...")
        time.sleep(PAGE_WAIT)

        # ── 1. Network logs ──
        try:
            logs = driver.get_log("performance")
            urls = extract_stream_from_logs(logs)
            if urls:
                best = next((u for u in urls if "master" in u), None)
                if not best:
                    best = next((u for u in urls if "auto" in u), urls[0])
                print(f"  ✅ [Network] {best[:120]}...")
                return best
        except Exception as e:
            print(f"  [WARN] Logs: {e}")

        # ── 2. Page source regex ──
        source = driver.page_source

        m3u8_patterns = [
            r'(https?://edge-hls[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]*saawsedge\.com[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+/master/[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+_auto\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+/hls/\d+/[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+\.m3u8\?[^\s"\'\\\]<>]*)',
            r'(https?://[^\s"\'\\\]<>]+\.m3u8)',
        ]

        for pat in m3u8_patterns:
            hits = re.findall(pat, source, re.IGNORECASE)
            if hits:
                clean = hits[0].replace("\\u002F", "/").replace("\\/", "/")
                clean = re.sub(r'["\'\]}>\\]+$', '', clean)
                if any(k in clean.lower() for k in ("hls", "edge", "saaws", "master", "auto", "stream", "live")):
                    print(f"  ✅ [Source] {clean[:120]}...")
                    return clean

        # ── 3. JS extraction ──
        try:
            result = driver.execute_script("""
                for (var v of document.querySelectorAll('video')) {
                    if (v.src && v.src.includes('m3u8')) return v.src;
                    if (v.currentSrc && v.currentSrc.includes('m3u8')) return v.currentSrc;
                }
                for (var s of document.querySelectorAll('video source')) {
                    if (s.src && s.src.includes('m3u8')) return s.src;
                }
                try {
                    if (typeof Hls !== 'undefined') {
                        var videos = document.querySelectorAll('video');
                        for (var v of videos) {
                            if (v.hlsPlayer) return v.hlsPlayer.url;
                            if (v._hls) return v._hls.url;
                        }
                    }
                } catch(e) {}
                var keys = ['hlsUrl','streamUrl','videoUrl','playUrl','liveUrl',
                            'streamSrc','playerSrc','hlsSrc','masterUrl'];
                for (var k of keys) {
                    if (window[k] && typeof window[k] === 'string') return window[k];
                }
                try {
                    if (window.playerConfig && window.playerConfig.hlsUrl)
                        return window.playerConfig.hlsUrl;
                } catch(e){}
                return null;
            """)

            if result and isinstance(result, str):
                if "m3u8" in result and result.startswith("http"):
                    print(f"  ✅ [JS] {result[:120]}...")
                    return result
                hits = re.findall(
                    r'https?://[^\s"\'\\\]<>]+\.m3u8[^\s"\'\\\]<>]*',
                    result, re.IGNORECASE
                )
                if hits:
                    clean = hits[0].replace("\\/", "/")
                    print(f"  ✅ [JS-JSON] {clean[:120]}...")
                    return clean
        except Exception as e:
            print(f"  [WARN] JS: {e}")

        # ── 4. Retry after extra wait ──
        print("  Retrying after 5s...")
        time.sleep(5)
        try:
            logs = driver.get_log("performance")
            urls = extract_stream_from_logs(logs)
            if urls:
                best = next((u for u in urls if "master" in u), urls[0])
                print(f"  ✅ [Retry] {best[:120]}...")
                return best
        except Exception:
            pass

        # ── 5. Offline check ──
        low = driver.page_source.lower()
        offline_words = [
            "offline", "is not online", "currently offline",
            "room is offline", "model is offline", "not broadcasting",
        ]
        if any(x in low for x in offline_words):
            print("  ❌ OFFLINE")
        else:
            print("  ❌ Stream not found")

        return None

    except Exception as e:
        print(f"  [ERROR] {e}")
        close_browser()
        return None


# ─────────────────────────────────────────
#  SITE SCRAPER
# ─────────────────────────────────────────
SKIP_WORDS = {
    "girl", "couple", "trans", "guy", "login", "signup", "register",
    "terms", "privacy", "contact", "about", "faq", "help", "support",
    "search", "categories", "tags", "popular", "new", "top", "index",
    "page", "home", "cam", "category", "male", "female", "couples",
    "girls", "boys", "men", "women", "lang", "en", "de", "es", "fr",
    "settings", "favorites", "tokens", "premium", "vip", "join",
    "undefined", "null", "true", "false", "api", "static", "assets",
    "avatar", "images", "css", "js", "fonts", "embed", "player",
}


def scrape_top_models():
    """
    Scrape booble.com for top live models (girl + couple).
    Returns dict: {"girl": [names], "couple": [names]}
    """
    result = {"girl": [], "couple": []}
    seen = set()

    # ── Try with requests first ──
    pages = [
        (f"{SITE_BASE}/",        "girl"),
        (f"{SITE_BASE}/girls",   "girl"),
        (f"{SITE_BASE}/couple",  "couple"),
        (f"{SITE_BASE}/couples", "couple"),
    ]

    for page_url, category in pages:
        if len(result[category]) >= TOP_N:
            continue

        print(f"[SCRAPE] {page_url}")
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15, allow_redirects=True)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
                continue

            html = resp.text

            names_found = re.findall(
                r'href=["\'](?:https?://[^"\']*)?/([a-zA-Z0-9_-]{3,50})["\']',
                html, re.IGNORECASE
            )
            names_found += re.findall(
                r'data-(?:model|performer|username|name|slug)=["\']([a-zA-Z0-9_-]{3,50})["\']',
                html, re.IGNORECASE
            )

            count = 0
            for name in names_found:
                if len(result[category]) >= TOP_N:
                    break
                name_clean = name.strip().strip("-_")
                name_lower = name_clean.lower()
                if (
                    name_lower not in seen
                    and name_lower not in SKIP_WORDS
                    and 3 <= len(name_clean) <= 50
                    and re.match(r'^[a-zA-Z0-9_-]+$', name_clean)
                    and not name_lower.endswith((".js", ".css", ".png", ".jpg", ".gif", ".svg"))
                ):
                    seen.add(name_lower)
                    result[category].append(name_clean)
                    count += 1

            print(f"  +{count} ({category}) → total {len(result[category])}")
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")

    # ── Fallback to Selenium if not enough ──
    for category in ["girl", "couple"]:
        if len(result[category]) < TOP_N:
            print(f"[SCRAPE] Selenium fallback for {category}...")
            try:
                driver = init_browser()
                target = f"{SITE_BASE}/" if category == "girl" else f"{SITE_BASE}/{category}"
                driver.get(target)
                time.sleep(5)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)

                html = driver.page_source
                names_found = re.findall(
                    r'href=["\'](?:https?://[^"\']*)?/([a-zA-Z0-9_-]{3,50})["\']',
                    html, re.IGNORECASE
                )

                count = 0
                for name in names_found:
                    if len(result[category]) >= TOP_N:
                        break
                    name_clean = name.strip().strip("-_")
                    name_lower = name_clean.lower()
                    if (
                        name_lower not in seen
                        and name_lower not in SKIP_WORDS
                        and 3 <= len(name_clean) <= 50
                        and re.match(r'^[a-zA-Z0-9_-]+$', name_clean)
                        and not name_lower.endswith((".js", ".css", ".png", ".jpg"))
                    ):
                        seen.add(name_lower)
                        result[category].append(name_clean)
                        count += 1

                print(f"  +{count} ({category}) via Selenium → total {len(result[category])}")

            except Exception as e:
                print(f"  Selenium error: {e}")

    print(f"\n[SCRAPE] Girls: {len(result['girl'])} | Couples: {len(result['couple'])}")
    return result


# ─────────────────────────────────────────
#  PLAYLIST WRITER
# ─────────────────────────────────────────
def generate_m3u(favorite_live, girls_live, couples_live):
    lines = [
        "#EXTM3U",
        f"# Updated  : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"# Source   : booble.com",
        f"# Favs     : {len(favorite_live)}",
        f"# Girls    : {len(girls_live)}",
        f"# Couples  : {len(couples_live)}",
        f"# Total    : {len(favorite_live) + len(girls_live) + len(couples_live)}",
        "",
    ]

    # ⭐ Favorites
    for model, info in favorite_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'tvg-logo="{info["avatar"]}" '
            f'group-title="⭐ Favorites",⭐ {model}'
        )
        lines.append(info["stream"])

    # 👩 Girls
    for model, info in girls_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'tvg-logo="{info["avatar"]}" '
            f'group-title="Girl",{model}'
        )
        lines.append(info["stream"])

    # 👫 Couples
    for model, info in couples_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'tvg-logo="{info["avatar"]}" '
            f'group-title="Couple",{model}'
        )
        lines.append(info["stream"])

    return "\n".join(lines)


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Live Playlist Updater — booble.com")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    try:
        # ── 1. Load favorites ──
        favorite_names = load_models(MODELS_FILE)

        # ── 2. Check favorites ──
        favorite_live = {}
        if favorite_names:
            print("\n" + "─" * 50)
            print("  ⭐ CHECKING FAVORITES")
            print("─" * 50)
            for name in favorite_names:
                print(f"\n[FAV] {name}")
                stream = fetch_stream(name)
                if stream:
                    avatar = get_avatar_url(name)
                    favorite_live[name] = {"stream": stream, "avatar": avatar}
                    print(f"  🖼️  Avatar: {avatar}")
                    print(f"  → LIVE ✅")
                else:
                    print(f"  → offline ❌")
                time.sleep(2)

        # ── 3. Discover top models ──
        print("\n" + "─" * 50)
        print(f"  👥 DISCOVERING TOP {TOP_N} GIRLS & TOP {TOP_N} COUPLES")
        print("─" * 50)

        discovered = scrape_top_models()
        fav_set = set(n.lower() for n in favorite_names)

        # ── 4. Check girls ──
        girls_live = {}
        girl_candidates = [n for n in discovered["girl"] if n.lower() not in fav_set]
        print(f"\n[GIRLS] {len(girl_candidates)} candidate(s)")

        for i, name in enumerate(girl_candidates[:TOP_N]):
            print(f"\n[Girl {i+1}/{min(len(girl_candidates), TOP_N)}] {name}")
            stream = fetch_stream(name)
            if stream:
                avatar = get_avatar_url(name)
                girls_live[name] = {"stream": stream, "avatar": avatar}
                print(f"  🖼️  Avatar: {avatar}")
                print(f"  → LIVE ✅")
            else:
                print(f"  → offline ❌")
            time.sleep(1.5)

        # ── 5. Check couples ──
        couples_live = {}
        couple_candidates = [n for n in discovered["couple"] if n.lower() not in fav_set]
        print(f"\n[COUPLES] {len(couple_candidates)} candidate(s)")

        for i, name in enumerate(couple_candidates[:TOP_N]):
            print(f"\n[Couple {i+1}/{min(len(couple_candidates), TOP_N)}] {name}")
            stream = fetch_stream(name)
            if stream:
                avatar = get_avatar_url(name)
                couples_live[name] = {"stream": stream, "avatar": avatar}
                print(f"  🖼️  Avatar: {avatar}")
                print(f"  → LIVE ✅")
            else:
                print(f"  → offline ❌")
            time.sleep(1.5)

        # ── 6. Write playlist ──
        playlist = generate_m3u(favorite_live, girls_live, couples_live)
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write(playlist)

        # ── 7. Summary ──
        total = len(favorite_live) + len(girls_live) + len(couples_live)
        print("\n" + "=" * 60)
        print("  📊 RESULTS")
        print("=" * 60)

        print(f"\n  ⭐ Favorites: {len(favorite_live)}/{len(favorite_names)}")
        for n in favorite_names:
            if n in favorite_live:
                print(f"     ✅ {n}")
            else:
                print(f"     ❌ {n}")

        print(f"\n  👩 Girls: {len(girls_live)} live")
        for n in girls_live:
            print(f"     ✅ {n}")

        print(f"\n  👫 Couples: {len(couples_live)} live")
        for n in couples_live:
            print(f"     ✅ {n}")

        print(f"\n  📺 Total: {total}")
        print(f"  💾 Saved: {PLAYLIST_FILE}")
        print("=" * 60)

    finally:
        close_browser()


if __name__ == "__main__":
    main()
