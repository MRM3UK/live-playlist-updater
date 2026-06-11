import requests
import time
import os
import re
import json

MODELS_FILE = "models.txt"
PLAYLIST_FILE = "playlist.m3u"

SITE_BASE = "https://www.2kcams.com"
ALLOWED_CATEGORIES = ["girl", "couple"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.2kcams.com/",
    "Origin": "https://www.2kcams.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

TIMEOUT = 15


def load_models(filepath):
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [name.strip().lower() for name in content.split(",") if name.strip()]
    print(f"[INFO] Loaded {len(models)} favorite model(s): {models}")
    return models


def fetch_stream_from_page(model_name):
    """
    Fetch the model's page on 2kcams and extract the HLS/m3u8 stream URL.
    Page: https://www.2kcams.com/cam/{model_name}
    """
    url = f"{SITE_BASE}/cam/{model_name}"
    print(f"  Fetching: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        print(f"  Status: {resp.status_code}")

        if resp.status_code != 200:
            return None

        html = resp.text

        # ── Method 1: Find m3u8 URL directly in page ──
        m3u8_patterns = [
            r'(https?://edge[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]*\.live\.mmcdn\.com[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]*mmcdn[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]+/llhls\.m3u8[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]+/playlist\.m3u8[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]+origin\.[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
        ]

        for pattern in m3u8_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                # Clean up any trailing quotes or brackets
                stream_url = re.sub(r'["\'\]\)}>]+$', '', stream_url)
                print(f"  ✅ Found m3u8: {stream_url[:120]}...")
                return stream_url

        # ── Method 2: Find in JSON/JS data blocks ──
        json_patterns = [
            r'"hlsUrl"\s*:\s*"([^"]+)"',
            r'"hls_url"\s*:\s*"([^"]+)"',
            r'"stream_url"\s*:\s*"([^"]+)"',
            r'"streamUrl"\s*:\s*"([^"]+)"',
            r'"url"\s*:\s*"(https?://[^"]*m3u8[^"]*)"',
            r'"src"\s*:\s*"(https?://[^"]*m3u8[^"]*)"',
            r'"source"\s*:\s*"(https?://[^"]*m3u8[^"]*)"',
            r'"file"\s*:\s*"(https?://[^"]*m3u8[^"]*)"',
            r"hlsUrl\s*=\s*['\"]([^'\"]+)['\"]",
            r"streamSrc\s*=\s*['\"]([^'\"]+)['\"]",
            r"videoUrl\s*=\s*['\"]([^'\"]+)['\"]",
            r"playUrl\s*=\s*['\"]([^'\"]+)['\"]",
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                stream_url = matches[0].replace("\\u002F", "/").replace("\\/", "/")
                if "m3u8" in stream_url or "mmcdn" in stream_url or "edge" in stream_url:
                    print(f"  ✅ Found stream (JSON): {stream_url[:120]}...")
                    return stream_url

        # ── Method 3: Look inside <script> tags for encoded data ──
        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        for script in script_blocks:
            # Search for m3u8 URLs in script content
            m3u8_in_script = re.findall(
                r'(https?://[^\s"\'\\]+\.m3u8[^\s"\'\\]*)',
                script, re.IGNORECASE
            )
            if m3u8_in_script:
                stream_url = m3u8_in_script[0]
                print(f"  ✅ Found stream (script): {stream_url[:120]}...")
                return stream_url

            # Check for escaped URLs
            escaped_urls = re.findall(
                r'(https?:\\?/\\?/[^\s"\']+m3u8[^\s"\']*)',
                script, re.IGNORECASE
            )
            if escaped_urls:
                stream_url = escaped_urls[0].replace("\\/", "/").replace("\\", "")
                print(f"  ✅ Found stream (escaped): {stream_url[:120]}...")
                return stream_url

        # ── Method 4: Check for iframe src that might contain stream ──
        iframe_matches = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for iframe_url in iframe_matches:
            if "embed" in iframe_url or "player" in iframe_url or "stream" in iframe_url:
                print(f"  Found iframe: {iframe_url}")
                try:
                    if not iframe_url.startswith("http"):
                        iframe_url = f"{SITE_BASE}{iframe_url}"
                    iframe_resp = requests.get(
                        iframe_url,
                        headers={**HEADERS, "Referer": url},
                        timeout=TIMEOUT,
                    )
                    if iframe_resp.status_code == 200:
                        iframe_html = iframe_resp.text
                        for pattern in m3u8_patterns:
                            matches = re.findall(pattern, iframe_html, re.IGNORECASE)
                            if matches:
                                stream_url = re.sub(r'["\'\]\)}>]+$', '', matches[0])
                                print(f"  ✅ Found stream (iframe): {stream_url[:120]}...")
                                return stream_url
                except Exception:
                    pass

        # ── Debug: Show what we found on the page ──
        if "offline" in html.lower() or "is not online" in html.lower() or "room is currently offline" in html.lower():
            print(f"  ❌ Model appears OFFLINE")
        else:
            # Print hints about what's on the page
            video_idx = html.lower().find("m3u8")
            if video_idx > 0:
                snippet = html[max(0, video_idx - 100):video_idx + 200]
                print(f"  [DEBUG] Found 'm3u8' in page but couldn't extract: ...{snippet}...")
            
            edge_idx = html.lower().find("edge")
            if edge_idx > 0:
                snippet = html[max(0, edge_idx - 50):edge_idx + 200]
                print(f"  [DEBUG] Found 'edge' in page: ...{snippet[:200]}...")

            mmcdn_idx = html.lower().find("mmcdn")
            if mmcdn_idx > 0:
                snippet = html[max(0, mmcdn_idx - 100):mmcdn_idx + 200]
                print(f"  [DEBUG] Found 'mmcdn' in page: ...{snippet[:300]}...")

        return None

    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def verify_stream(stream_url):
    """Verify that a stream URL is actually accessible."""
    try:
        resp = requests.head(
            stream_url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": f"{SITE_BASE}/",
                "Origin": SITE_BASE,
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code in (200, 206):
            return True

        # Some CDNs don't support HEAD, try GET
        resp = requests.get(
            stream_url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": f"{SITE_BASE}/",
                "Origin": SITE_BASE,
            },
            timeout=TIMEOUT,
            stream=True,
        )
        chunk = next(resp.iter_content(512), None)
        resp.close()
        if chunk and len(chunk) > 10:
            return True

    except Exception:
        pass
    return False


def fetch_live_models_from_site():
    """
    Scrape 2kcams.com listing pages for girl and couple categories.
    Returns list of model dicts.
    """
    all_models = []
    seen = set()

    category_urls = {
        "girl": [
            f"{SITE_BASE}/",
            f"{SITE_BASE}/?page=2",
            f"{SITE_BASE}/?page=3",
            f"{SITE_BASE}/female",
            f"{SITE_BASE}/female?page=2",
            f"{SITE_BASE}/female?page=3",
            f"{SITE_BASE}/girls",
            f"{SITE_BASE}/girls?page=2",
        ],
        "couple": [
            f"{SITE_BASE}/couple",
            f"{SITE_BASE}/couple?page=2",
            f"{SITE_BASE}/couple?page=3",
            f"{SITE_BASE}/couples",
            f"{SITE_BASE}/couples?page=2",
        ],
    }

    for category, urls in category_urls.items():
        for page_url in urls:
            print(f"[SCRAPE] {page_url}")
            try:
                resp = requests.get(
                    page_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                if resp.status_code != 200:
                    continue

                html = resp.text

                # Pattern: /cam/username links
                cam_links = re.findall(
                    r'href=["\'](?:https?://[^"\']*)?/cam/([a-zA-Z0-9_]+)["\']',
                    html, re.IGNORECASE
                )

                # Pattern: data attributes with model names
                data_models = re.findall(
                    r'data-(?:model|performer|username|name|slug)=["\']([a-zA-Z0-9_]+)["\']',
                    html, re.IGNORECASE
                )

                # Pattern: stream URLs with model names embedded
                stream_names = re.findall(
                    r'origin\.([a-zA-Z0-9_]+)\.',
                    html, re.IGNORECASE
                )

                all_names = cam_links + data_models + stream_names

                skip_words = {
                    "girl", "couple", "trans", "guy", "login", "signup",
                    "register", "terms", "privacy", "contact", "about",
                    "faq", "help", "support", "search", "categories",
                    "tags", "popular", "new", "top", "index", "page",
                    "home", "cam", "category", "male", "female",
                    "couples", "girls", "guys", "undefined", "null",
                }

                count = 0
                for name in all_names:
                    name = name.lower().strip()
                    if (
                        name not in seen
                        and name not in skip_words
                        and len(name) >= 3
                        and len(name) <= 40
                        and re.match(r'^[a-z][a-z0-9_]+$', name)
                    ):
                        seen.add(name)
                        all_models.append({
                            "name": name,
                            "category": category,
                        })
                        count += 1

                print(f"  Found {count} new model(s)")
                time.sleep(1)

            except Exception as e:
                print(f"  Error: {e}")

    print(f"\n[SCRAPE] Total discovered: {len(all_models)} models")
    return all_models


def generate_m3u(favorite_live, other_live):
    """Generate M3U with favorites first, then others."""
    lines = ["#EXTM3U"]
    lines.append(f"# Last updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Favorites live: {len(favorite_live)}")
    lines.append(f"# Others live: {len(other_live)}")
    lines.append(f"# Total live: {len(favorite_live) + len(other_live)}")
    lines.append("")

    # Favorites first
    for model, url in favorite_live.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" '
            f'group-title="⭐ Favorites",⭐ {model}'
        )
        lines.append(url)

    # Others grouped by category
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
    print(f"  Live Playlist Updater (2kcams)")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    # ─── STEP 1: Load favorites ───
    favorite_names = load_models(MODELS_FILE)

    # ─── STEP 2: Check favorites ───
    favorite_live = {}
    print("\n" + "─" * 50)
    print("  CHECKING FAVORITE MODELS")
    print("─" * 50)

    for model_name in favorite_names:
        print(f"\n[FAV] {model_name}")
        stream_url = fetch_stream_from_page(model_name)
        if stream_url:
            favorite_live[model_name] = stream_url
        else:
            print(f"  ❌ {model_name} — offline or no stream found")
        time.sleep(1)

    # ─── STEP 3: Discover other live models ───
    print("\n" + "─" * 50)
    print("  DISCOVERING OTHER LIVE MODELS (girl, couple)")
    print("─" * 50)

    discovered = fetch_live_models_from_site()

    # Remove favorites from discovered list
    fav_set = set(favorite_names)
    other_candidates = [m for m in discovered if m["name"] not in fav_set]

    print(f"\n[INFO] {len(other_candidates)} other candidate(s) to check")

    other_live = {}
    max_others = 80

    for i, model_info in enumerate(other_candidates):
        if i >= max_others:
            print(f"[INFO] Reached limit of {max_others}")
            break

        model_name = model_info["name"]
        category = model_info["category"]

        print(f"\n[OTHER {i+1}/{min(len(other_candidates), max_others)}] {model_name} ({category})")
        stream_url = fetch_stream_from_page(model_name)

        if stream_url:
            other_live[model_name] = {
                "url": stream_url,
                "category": category,
            }

        time.sleep(0.8)

    # ─── STEP 4: Generate playlist ───
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
            print(f"     ❌ {name}")

    print(f"\n  👥 Others live: {len(other_live)}")
    for name, info in other_live.items():
        print(f"     ✅ {name} ({info['category']})")

    print(f"\n  📺 Total: {len(favorite_live) + len(other_live)}")
    print(f"\n[SAVED] {PLAYLIST_FILE}")


if __name__ == "__main__":
    main()
