import requests
import time
import os

MODELS_FILE = "models.txt"
PLAYLIST_FILE = "playlist.m3u"
BASE_CHECK_URL = "https://myhotcams.net/"
STREAM_SERVERS = [
    "https://videos.myhotcams.net/d01/",
    "https://videos.myhotcams.net/d02/",
    "https://videos.myhotcams.net/d03/",
    "https://videos.myhotcams.net/d04/",
    "https://videos.myhotcams.net/d05/",
    "https://videos.myhotcams.net/d06/",
    "https://videos.myhotcams.net/d07/",
    "https://videos.myhotcams.net/d08/",
    "https://videos.myhotcams.net/d09/",
    "https://videos.myhotcams.net/d10/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://myhotcams.net/",
    "Accept": "*/*",
    "Connection": "keep-alive",
}

TIMEOUT = 10


def load_models(filepath):
    """Load model names from comma-separated text file."""
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    models = [name.strip().lower() for name in content.split(",") if name.strip()]
    print(f"[INFO] Loaded {len(models)} model(s): {models}")
    return models


def check_model_page_live(model_name):
    """
    Check if model's profile page indicates they are live.
    Returns True if the page exists and suggests the model is online.
    """
    url = f"{BASE_CHECK_URL}{model_name}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            html = resp.text.lower()
            # Look for indicators that the model is currently live/online
            live_indicators = [
                '"online"',
                '"status":"online"',
                "is_live",
                "live_now",
                "currently live",
                "streaming now",
                "player",
                "video-container",
                ".mp4",
                ".m3u8",
                "hlsurl",
                "stream_url",
            ]
            for indicator in live_indicators:
                if indicator in html:
                    return True
        return False
    except requests.RequestException as e:
        print(f"[WARN] Could not check page for {model_name}: {e}")
        return False


def find_live_stream(model_name):
    """
    Try to find a working live stream URL for a model.
    Checks multiple server paths and extensions.
    Returns the working stream URL or None.
    """
    extensions = [".mp4", ".m3u8"]

    # First check if model page suggests they are live
    page_live = check_model_page_live(model_name)
    if not page_live:
        print(f"[SKIP] {model_name} — page does not indicate live status")
        return None

    # Try each server + extension combination
    for server in STREAM_SERVERS:
        for ext in extensions:
            stream_url = f"{server}{model_name}{ext}"
            try:
                resp = requests.head(
                    stream_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    content_length = resp.headers.get("Content-Length", "0")

                    # Validate it's actually a media stream
                    valid_types = [
                        "video/",
                        "application/vnd.apple.mpegurl",
                        "application/x-mpegurl",
                        "application/octet-stream",
                        "binary/octet-stream",
                    ]

                    is_valid_type = any(vt in content_type for vt in valid_types)
                    is_nonzero = int(content_length) > 0 if content_length.isdigit() else True

                    if is_valid_type and is_nonzero:
                        print(f"[LIVE] {model_name} → {stream_url}")
                        return stream_url

            except requests.RequestException:
                continue

    # Also try GET request on first few servers (some servers don't support HEAD)
    for server in STREAM_SERVERS[:3]:
        for ext in extensions:
            stream_url = f"{server}{model_name}{ext}"
            try:
                resp = requests.get(
                    stream_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    stream=True,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    # Read a small chunk to verify it's real content
                    chunk = resp.raw.read(1024)
                    resp.close()
                    if chunk and len(chunk) > 100:
                        print(f"[LIVE] {model_name} → {stream_url}")
                        return stream_url
                resp.close()
            except requests.RequestException:
                continue

    print(f"[OFFLINE] {model_name} — no live stream found")
    return None


def scrape_stream_from_page(model_name):
    """
    Alternative: scrape the model's page directly for stream URLs.
    """
    url = f"{BASE_CHECK_URL}{model_name}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None

        import re
        html = resp.text

        # Look for direct stream URLs in page source
        patterns = [
            r'(https?://videos\.myhotcams\.net/[^"\'\s]+\.mp4)',
            r'(https?://videos\.myhotcams\.net/[^"\'\s]+\.m3u8)',
            r'source["\s:]+["\']?(https?://[^"\'\s]+\.mp4)',
            r'hlsUrl["\s:]+["\']?(https?://[^"\'\s]+)',
            r'streamUrl["\s:]+["\']?(https?://[^"\'\s]+)',
            r'file["\s:]+["\']?(https?://[^"\'\s]+\.mp4)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html)
            if matches:
                stream_url = matches[0]
                print(f"[SCRAPED] {model_name} → {stream_url}")
                return stream_url

        return None
    except Exception as e:
        print(f"[WARN] Scrape failed for {model_name}: {e}")
        return None


def generate_playlist(live_streams):
    """Generate M3U playlist content."""
    lines = ["#EXTM3U"]
    lines.append(f"# Updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Live models: {len(live_streams)}")
    lines.append("")

    for model_name, stream_url in live_streams.items():
        lines.append(f'#EXTINF:-1 tvg-name="{model_name}",{model_name}')
        lines.append(stream_url)
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print(f"Playlist Updater — {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    models = load_models(MODELS_FILE)
    if not models:
        print("[ERROR] No models found. Exiting.")
        # Write empty playlist
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n# No models configured\n")
        return

    live_streams = {}

    for model_name in models:
        print(f"\n[CHECK] Checking {model_name}...")

        # Method 1: Try scraping stream URL directly from model page
        stream_url = scrape_stream_from_page(model_name)

        # Method 2: Try brute-force checking known server paths
        if not stream_url:
            stream_url = find_live_stream(model_name)

        if stream_url:
            live_streams[model_name] = stream_url

        # Small delay to be respectful
        time.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"Results: {len(live_streams)}/{len(models)} models are LIVE")
    print("=" * 60)

    # Generate and save playlist
    playlist_content = generate_playlist(live_streams)

    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write(playlist_content)

    print(f"\n[SAVED] Playlist written to {PLAYLIST_FILE}")
    print(f"[CONTENT]\n{playlist_content}")


if __name__ == "__main__":
    main()
