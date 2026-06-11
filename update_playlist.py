import requests
import time
import os
import re
from html.parser import HTMLParser

MODELS_FILE = "models.txt"
PLAYLIST_FILE = "playlist.m3u"

STREAM_BASE = "https://videos.myhotcams.net/"
SITE_BASE = "https://myhotcams.net"
SERVERS = [f"d{str(i).zfill(2)}" for i in range(1, 21)]
EXTENSIONS = [".mp4"]
ALLOWED_CATEGORIES = ["girl", "couple"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://myhotcams.net/",
    "Origin": "https://myhotcams.net",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

TIMEOUT = 8


def load_models(filepath):
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [name.strip().lower() for name in content.split(",") if name.strip()]
    print(f"[INFO] Loaded {len(models)} favorite model(s): {models}")
    return models


def check_stream_url(url):
    """Confirm stream is live by requesting a small chunk."""
    try:
        resp = requests.get(
            url,
            headers={**HEADERS, "Range": "bytes=0-1024"},
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        if resp.status_code in (200, 206):
            chunk = b""
            for data in resp.iter_content(chunk_size=512):
                chunk += data
                if len(chunk) >= 512:
                    break
            resp.close()
            if len(chunk) > 100:
                return True
        resp.close()
    except Exception:
        pass
    return False


def find_live_stream(model_name):
    """Check all servers for a working stream URL."""
    for server in SERVERS:
        for ext in EXTENSIONS:
            url = f"{STREAM_BASE}{server}/{model_name}{ext}"
            try:
                resp = requests.head(
                    url,
                    headers={
                        "User-Agent": HEADERS["User-Agent"],
                        "Referer": HEADERS["Referer"],
                    },
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

                if resp.status_code in (200, 206):
                    if check_stream_url(url):
                        print(f"  ✅ LIVE: {url}")
                        return url

            except Exception:
                pass

            time.sleep(0.15)

    return None


def scrape_from_model_page(model_name):
    """Scrape the model page for a stream URL."""
    url = f"{SITE_BASE}/{model_name}"
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        html = resp.text
        patterns = [
            r'https?://videos\.myhotcams\.net/[^\s\'"<>]+\.mp4',
            r'https?://videos\.myhotcams\.net/[^\s\'"<>]+\.m3u8',
            r'"stream_url"\s*:\s*"([^"]+)"',
            r'"hlsUrl"\s*:\s*"([^"]+)"',
            r'"video_url"\s*:\s*"([^"]+)"',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                return matches[0]

        return None
    except Exception:
        return None


def fetch_live_models_from_site():
    """
    Scrape the main site pages to get all currently live models.
    Returns list of dicts: [{"name": "model_name", "category": "girl", "thumb": "...", "url": "..."}, ...]
    """
    all_models = []
    seen = set()

    for category in ALLOWED_CATEGORIES:
        page = 1
        while True:
            if category == "girl":
                url = f"{SITE_BASE}/?page={page}"
            else:
                url = f"{SITE_BASE}/{category}?page={page}"

            print(f"[SCRAPE] Fetching {url}")

            try:
                resp = requests.get(
                    url,
                    headers={
                        "User-Agent": HEADERS["User-Agent"],
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=15,
                )

                if resp.status_code != 200:
                    print(f"  Page {page} returned {resp.status_code}, stopping.")
                    break

                html = resp.text

                # Find model usernames from the page
                # Common patterns on cam sites:
                # /model_name or href="/model_name" or data-performer="model_name"

                # Pattern 1: Links like href="/username" with cam-related context
                link_patterns = [
                    # Direct profile links
                    r'href=["\']/?([a-zA-Z0-9_]+)["\'][^>]*class=["\'][^"\']*(?:cam|model|performer|thumb|preview)',
                    r'class=["\'][^"\']*(?:cam|model|performer|thumb|preview)[^"\']*["\'][^>]*href=["\']/?([a-zA-Z0-9_]+)["\']',
                    # Data attributes
                    r'data-(?:performer|model|username|name)=["\']([a-zA-Z0-9_]+)["\']',
                    # Links within listing containers
                    r'<a[^>]+href=["\']/?([a-zA-Z0-9_]+)["\'][^>]*>',
                ]

                models_found_on_page = []

                for pattern in link_patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    for match in matches:
                        name = match.lower().strip()
                        # Filter out non-model links
                        skip_words = [
                            "girl", "couple", "trans", "guy", "login", "signup",
                            "register", "terms", "privacy", "contact", "about",
                            "faq", "help", "support", "search", "categories",
                            "tags", "popular", "new", "top", "index", "page",
                            "home", "favicon", "css", "js", "img", "images",
                            "static", "assets", "api", "ajax", "cdn",
                            "undefined", "null", "true", "false",
                            "male", "female", "category", "lang",
                        ]
                        if (
                            len(name) >= 3
                            and len(name) <= 30
                            and name not in skip_words
                            and not name.startswith(("http", "www", "//", "#", "?"))
                            and not name.endswith((".js", ".css", ".png", ".jpg", ".gif", ".ico"))
                            and re.match(r'^[a-z][a-z0-9_]+$', name)
                        ):
                            models_found_on_page.append(name)

                # Also try to find stream URLs directly embedded
                stream_pattern = r'https?://videos\.myhotcams\.net/d\d+/([a-zA-Z0-9_]+)\.mp4'
                stream_matches = re.findall(stream_pattern, html, re.IGNORECASE)
                for name in stream_matches:
                    name = name.lower().strip()
                    if len(name) >= 3:
                        models_found_on_page.append(name)

                # Deduplicate while preserving order
                unique_on_page = []
                for name in models_found_on_page:
                    if name not in seen:
                        seen.add(name)
                        unique_on_page.append(name)
                        all_models.append({
                            "name": name,
                            "category": category,
                        })

                print(f"  Found {len(unique_on_page)} new model(s) on page {page}")

                # If no new models found, no more pages
                if len(unique_on_page) == 0:
                    break

                # Check if there's a next page link
                if f"page={page + 1}" not in html and page > 1:
                    break

                page += 1
                time.sleep(1)

                # Safety limit
                if page > 10:
                    break

            except Exception as e:
                print(f"  Error fetching page {page}: {e}")
                break

    print(f"\n[SCRAPE] Total discovered: {len(all_models)} models from site")
    return all_models


def fetch_live_models_api():
    """
    Try API endpoints that cam sites commonly use.
    """
    all_models = []

    for category in ALLOWED_CATEGORIES:
        api_urls = [
            f"{SITE_BASE}/api/models?category={category}&online=true",
            f"{SITE_BASE}/api/performers?category={category}&status=online",
            f"{SITE_BASE}/api/v1/models?gender={category}&online=1",
            f"{SITE_BASE}/api/models/online?category={category}",
        ]

        for api_url in api_urls:
            try:
                resp = requests.get(
                    api_url,
                    headers={
                        "User-Agent": HEADERS["User-Agent"],
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        print(f"[API] Got response from {api_url}")

                        # Try to extract model names from various JSON structures
                        models = []
                        if isinstance(data, list):
                            models = data
                        elif isinstance(data, dict):
                            for key in ["models", "performers", "data", "results", "items"]:
                                if key in data and isinstance(data[key], list):
                                    models = data[key]
                                    break

                        for m in models:
                            name = None
                            if isinstance(m, str):
                                name = m
                            elif isinstance(m, dict):
                                for key in ["username", "name", "performer", "model", "slug", "nickname"]:
                                    if key in m:
                                        name = str(m[key])
                                        break

                            if name:
                                all_models.append({
                                    "name": name.lower().strip(),
                                    "category": category,
                                })

                        if models:
                            print(f"[API] Found {len(models)} models via API")
                            return all_models

                    except ValueError:
                        pass
            except Exception:
                pass

    return all_models


def generate_m3u(favorite_live, other_live):
    """Generate M3U with favorites first, then other live models."""
    lines = ["#EXTM3U"]
    lines.append(f"# Last updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Favorites live: {len(favorite_live)}")
    lines.append(f"# Others live: {len(other_live)}")
    lines.append(f"# Total live: {len(favorite_live) + len(other_live)}")
    lines.append("")

    # Favorites first
    if favorite_live:
        for model, url in favorite_live.items():
            lines.append(
                f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
                f'group-title="⭐ Favorites",⭐ {model}'
            )
            lines.append(url)

    # Then others
    if other_live:
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
    print(f"  Live Playlist Updater")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    # ─── STEP 1: Load favorite models from txt ───
    favorite_names = load_models(MODELS_FILE)

    # ─── STEP 2: Check favorites ───
    favorite_live = {}
    print("\n" + "─" * 40)
    print("CHECKING FAVORITE MODELS")
    print("─" * 40)

    for model_name in favorite_names:
        print(f"\n[FAV] Checking {model_name}...")
        stream_url = scrape_from_model_page(model_name)
        if not stream_url:
            stream_url = find_live_stream(model_name)
        if stream_url:
            favorite_live[model_name] = stream_url
            print(f"  ✅ {model_name} is LIVE")
        else:
            print(f"  ❌ {model_name} is offline")
        time.sleep(0.5)

    # ─── STEP 3: Discover other live models from site ───
    print("\n" + "─" * 40)
    print("DISCOVERING OTHER LIVE MODELS (girl, couple)")
    print("─" * 40)

    discovered_models = fetch_live_models_api()
    if not discovered_models:
        discovered_models = fetch_live_models_from_site()

    # Filter out favorites (already handled)
    other_candidates = [
        m for m in discovered_models
        if m["name"] not in favorite_names and m["name"] not in favorite_live
    ]

    print(f"\n[INFO] {len(other_candidates)} non-favorite candidate(s) to check")

    other_live = {}
    checked = 0
    max_others = 100  # Limit to avoid timeout

    for model_info in other_candidates:
        if checked >= max_others:
            print(f"[INFO] Reached limit of {max_others} checks")
            break

        model_name = model_info["name"]
        category = model_info["category"]

        print(f"\n[OTHER] Checking {model_name} ({category})...")
        stream_url = find_live_stream(model_name)

        if stream_url:
            other_live[model_name] = {
                "url": stream_url,
                "category": category,
            }
            print(f"  ✅ {model_name} is LIVE ({category})")

        checked += 1
        time.sleep(0.3)

    # ─── STEP 4: Write playlist ───
    print("\n" + "─" * 40)
    print("GENERATING PLAYLIST")
    print("─" * 40)

    playlist = generate_m3u(favorite_live, other_live)

    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write(playlist)

    print(f"\n[SAVED] {PLAYLIST_FILE}")
    print(f"  ⭐ Favorites live: {len(favorite_live)}")
    print(f"  👥 Others live:    {len(other_live)}")
    print(f"  📺 Total:          {len(favorite_live) + len(other_live)}")
    print(f"\n[PLAYLIST]\n{playlist}")


if __name__ == "__main__":
    main()
