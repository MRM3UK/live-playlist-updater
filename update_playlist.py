import requests
import time
import os
import re

MODELS_FILE = "models.txt"
PLAYLIST_FILE = "playlist.m3u"

STREAM_BASE = "https://videos.myhotcams.net/"
SERVERS = [f"d{str(i).zfill(2)}" for i in range(1, 21)]  # d01 to d20
EXTENSIONS = [".mp4", ".m3u8"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://myhotcams.net/",
    "Origin": "https://myhotcams.net",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Range": "bytes=0-1024",  # Request just first 1KB to confirm stream is live
}

TIMEOUT = 8


def load_models(filepath):
    if not os.path.exists(filepath):
        print(f"[ERROR] {filepath} not found!")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    models = [name.strip().lower() for name in content.split(",") if name.strip()]
    print(f"[INFO] Loaded {len(models)} model(s): {models}")
    return models


def check_stream_url(url):
    """
    Try HEAD then GET with Range to confirm stream is accessible and has content.
    Returns True if stream is live.
    """
    # Try HEAD first
    try:
        resp = requests.head(
            url,
            headers={**HEADERS, "Range": None},  # HEAD without range
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        print(f"  HEAD {url} → {resp.status_code} | CT: {resp.headers.get('Content-Type','?')} | CL: {resp.headers.get('Content-Length','?')}")
        
        if resp.status_code in (200, 206):
            ct = resp.headers.get("Content-Type", "").lower()
            cl = int(resp.headers.get("Content-Length", 0) or 0)
            
            # If content-type is video or content-length > 0, it's live
            if "video" in ct or "octet" in ct or "mpegurl" in ct or cl > 1000:
                return True
    except Exception as e:
        print(f"  HEAD failed: {e}")

    # Try GET with Range
    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        print(f"  GET  {url} → {resp.status_code} | CT: {resp.headers.get('Content-Type','?')} | CL: {resp.headers.get('Content-Length','?')}")
        
        if resp.status_code in (200, 206):
            # Read first chunk
            chunk = b""
            for data in resp.iter_content(chunk_size=512):
                chunk += data
                if len(chunk) >= 512:
                    break
            resp.close()
            
            if len(chunk) > 100:
                print(f"  ✓ Got {len(chunk)} bytes — stream is LIVE")
                return True
        resp.close()
    except Exception as e:
        print(f"  GET failed: {e}")

    return False


def find_live_stream(model_name):
    """
    Check all servers d01-d20 for both .mp4 and .m3u8
    Returns working URL or None
    """
    print(f"\n[CHECKING] {model_name}")
    
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
                
                print(f"  {server}/{model_name}{ext} → {resp.status_code}")
                
                if resp.status_code == 200:
                    ct = resp.headers.get("Content-Type", "").lower()
                    cl = int(resp.headers.get("Content-Length", 0) or 0)
                    print(f"    Content-Type: {ct} | Content-Length: {cl}")
                    
                    # Confirm with a GET chunk
                    if check_stream_url(url):
                        print(f"  ✅ LIVE: {url}")
                        return url

                elif resp.status_code == 206:
                    print(f"  ✅ LIVE (206): {url}")
                    return url
                    
            except requests.exceptions.ConnectionError:
                print(f"  {server}/{model_name}{ext} → Connection refused")
            except requests.exceptions.Timeout:
                print(f"  {server}/{model_name}{ext} → Timeout")
            except Exception as e:
                print(f"  {server}/{model_name}{ext} → Error: {e}")
            
            time.sleep(0.2)  # Small delay between requests

    print(f"  ❌ No live stream found for {model_name}")
    return None


def scrape_from_model_page(model_name):
    """
    Scrape the model page directly for stream URL.
    """
    url = f"https://myhotcams.net/{model_name}"
    print(f"  Scraping page: {url}")
    
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            timeout=10,
        )
        print(f"  Page status: {resp.status_code}")
        
        if resp.status_code != 200:
            return None
        
        html = resp.text
        
        # Debug: print snippet around "video" keyword
        idx = html.lower().find("video")
        if idx > 0:
            print(f"  Page snippet near 'video': ...{html[max(0,idx-50):idx+200]}...")
        
        # Search for stream URLs in page
        patterns = [
            r'https?://videos\.myhotcams\.net/[^\s\'"<>]+\.mp4',
            r'https?://videos\.myhotcams\.net/[^\s\'"<>]+\.m3u8',
            r'"url"\s*:\s*"(https?://[^\s\'"<>]+\.mp4)"',
            r'"url"\s*:\s*"(https?://[^\s\'"<>]+\.m3u8)"',
            r'src\s*[=:]\s*["\']?(https?://videos\.myhotcams\.net/[^\s\'"<>]+)',
            r'file\s*[=:]\s*["\']?(https?://videos\.myhotcams\.net/[^\s\'"<>]+)',
            r'source\s*[=:]\s*["\']?(https?://videos\.myhotcams\.net/[^\s\'"<>]+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                print(f"  Found URL in page: {stream_url}")
                return stream_url
        
        # Also search for JSON-like stream data
        json_patterns = [
            r'"stream_url"\s*:\s*"([^"]+)"',
            r'"hls_url"\s*:\s*"([^"]+)"',
            r'"hlsUrl"\s*:\s*"([^"]+)"',
            r'"mp4_url"\s*:\s*"([^"]+)"',
            r'"streamUrl"\s*:\s*"([^"]+)"',
            r'"live_url"\s*:\s*"([^"]+)"',
            r'"video_url"\s*:\s*"([^"]+)"',
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                print(f"  Found JSON URL in page: {stream_url}")
                return stream_url
                
        print(f"  No stream URL found in page source")
        return None
        
    except Exception as e:
        print(f"  Page scrape error: {e}")
        return None


def generate_m3u(live_streams):
    lines = ["#EXTM3U"]
    lines.append(f"# Last updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"# Live: {len(live_streams)} model(s)")

    for model, url in live_streams.items():
        lines.append(f'#EXTINF:-1 tvg-id="{model}" tvg-name="{model}" group-title="Live",{model}')
        lines.append(url)

    return "\n".join(lines)


def main():
    print("=" * 60)
    print(f"  Live Playlist Updater")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    models = load_models(MODELS_FILE)
    if not models:
        return

    live_streams = {}

    for model_name in models:
        # Method 1: Scrape page first (fastest if it works)
        stream_url = scrape_from_model_page(model_name)

        # Method 2: Brute force all servers
        if not stream_url:
            stream_url = find_live_stream(model_name)

        if stream_url:
            live_streams[model_name] = stream_url

        time.sleep(1)

    # Write playlist
    playlist = generate_m3u(live_streams)
    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write(playlist)

    print("\n" + "=" * 60)
    print(f"  Done! {len(live_streams)}/{len(models)} live")
    print("=" * 60)
    print(f"\n[PLAYLIST]\n{playlist}")


if __name__ == "__main__":
    main()
