import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

MAX_WORKERS = 16
SESSION_COOKIES = []
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def apply_stealth(page):
    """Removes automation flags to mimic real user behavior."""
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )


def extract_album_folder_name(url):
    """Parses the URL to find the last valid segment for the folder name."""
    parsed = urlparse(url)
    path_segments = [seg for seg in parsed.path.split("/") if seg]
    if path_segments:
        return path_segments[-1]
    return "downloaded_album"


def get_auth_session(album_url):
    """Launches a single headed browser to pass Cloudflare and gather all pages/images."""
    global SESSION_COOKIES
    print(f"Opening target URL: {album_url}")
    print("Launching browser in headed mode for authentication (this window will focus)...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        apply_stealth(page)

        page.goto(album_url, wait_until="load", timeout=60000)

        print("Please complete the Cloudflare verification if it appears.")
        print("The script will save credentials and close this window in 10 seconds...")
        time.sleep(10)

        SESSION_COOKIES = context.cookies()
        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Extract and convert ALL thumbnail URLs to original full-resolution image URLs
        album_art_urls = []
        album_img_containers = soup.find_all(class_="albumImage")
        for container in album_img_containers:
            img_tags = container.find_all("img")
            for img in img_tags:
                if img.get("src"):
                    thumb_url = urljoin(album_url, img.get("src"))
                    original_url = thumb_url.replace("/thumbs/", "/")
                    if original_url not in album_art_urls:
                        album_art_urls.append(original_url)

        # Extract song pages from table
        table = soup.find("table", id="songlist")
        if not table:
            print("Error: Authentication failed or could not find table with id='songlist'.")
            return [], []

        song_links = []
        td_elements = table.find_all("td", class_="playlistDownloadSong")
        for td in td_elements:
            a_tag = td.find("a")
            if a_tag and a_tag.get("href"):
                song_links.append(urljoin(album_url, a_tag.get("href")))

        print(
            f"Authentication successful. Extracted {len(song_links)} song pages "
            f"and {len(album_art_urls)} image links."
        )
        return song_links, album_art_urls


def select_audio_url_from_soup(soup, song_url, preferred_format="mp3", allow_fallback=True):
    """Selects the audio download URL matching preferred_format if available."""
    fmt = preferred_format.lower().lstrip(".")
    available_links = []  # list of (ext, full_url)

    # Primary: look for <span class="songDownloadLink"> inside <a href="...">
    for span in soup.find_all("span", class_="songDownloadLink"):
        a_tag = span.find_parent("a")
        if a_tag and a_tag.get("href"):
            full_url = urljoin(song_url, a_tag.get("href"))
            ext = os.path.splitext(urlparse(full_url).path)[1].lower().lstrip(".")
            # Also check label text like "Click here to download as FLAC"
            label_match = re.search(r"download as\s+([a-z0-9]+)", span.get_text(" ", strip=True), re.I)
            fmt_tag = label_match.group(1).lower() if label_match else ext
            if full_url not in [u for _, u in available_links]:
                available_links.append((fmt_tag or ext, full_url))

    # Secondary fallback: check <audio id="audio"> if no songDownloadLink spans were found
    if not available_links:
        audio_tag = soup.find("audio", id="audio")
        if audio_tag:
            src = audio_tag.get("src") or (
                audio_tag.find("source").get("src") if audio_tag.find("source") else None
            )
            if src:
                full_url = urljoin(song_url, src)
                ext = os.path.splitext(urlparse(full_url).path)[1].lower().lstrip(".")
                available_links.append((ext, full_url))

    if not available_links:
        return None, None

    # Look for exact format match
    for link_fmt, url in available_links:
        if link_fmt == fmt:
            return url, link_fmt

    # Fallback to first available format if permitted
    if allow_fallback:
        fallback_fmt, fallback_url = available_links[0]
        return fallback_url, fallback_fmt

    return None, None


def worker_extract_audio_src(song_url, preferred_format="mp3", allow_fallback=True):
    """Background thread worker to resolve the audio file URL for the chosen format."""
    global SESSION_COOKIES
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            context.add_cookies(SESSION_COOKIES)
            page = context.new_page()
            apply_stealth(page)

            page.goto(song_url, wait_until="domcontentloaded", timeout=20000)
            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, "html.parser")
            return select_audio_url_from_soup(
                soup,
                song_url,
                preferred_format=preferred_format,
                allow_fallback=allow_fallback,
            )
    except Exception:
        pass
    return None, None


def worker_download_file(download_url, output_folder):
    """Background thread worker to handle binary download via requests."""
    global SESSION_COOKIES
    try:
        req_cookies = {c["name"]: c["value"] for c in SESSION_COOKIES}
        headers = {"User-Agent": USER_AGENT}

        response = requests.get(
            download_url, headers=headers, cookies=req_cookies, stream=True, timeout=20
        )
        if response.status_code == 200:
            cd = response.headers.get("content-disposition")
            matches = re.findall(r'filename="?([^";]+)"?', cd) if cd else []
            if matches:
                filename = matches[0].strip()
            else:
                filename = os.path.basename(urlparse(download_url).path)

            filename = unquote(unquote(filename))
            filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
            output_path = os.path.join(output_folder, filename)

            if os.path.exists(output_path):
                print(f"[Skipped] File already exists: {filename}")
                return True

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=16384):
                    f.write(chunk)
            print(f"[Downloaded] Saved: {filename}")
            return True
    except Exception as e:
        print(f"Download failed: {download_url} -> {e}")
    return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download album images and audio tracks in a preferred format."
    )
    parser.add_argument("album_url", help="Target album URL")
    parser.add_argument(
        "-f",
        "--format",
        default="mp3",
        help="Preferred audio format (e.g., mp3, flac, ogg, wav). Default: mp3",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Skip tracks that do not offer the requested format instead of falling back.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_url = args.album_url.strip()
    preferred_format = args.format.strip().lower().lstrip(".")
    allow_fallback = not args.no_fallback

    album_folder_name = extract_album_folder_name(target_url)
    album_folder_path = os.path.join(os.getcwd(), "output", album_folder_name)
    image_folder_path = os.path.join(album_folder_path, "album_imgs")

    os.makedirs(album_folder_path, exist_ok=True)
    os.makedirs(image_folder_path, exist_ok=True)
    print(f"Album directory: {album_folder_path}")
    print(f"Images subdirectory: {image_folder_path}")
    print(f"Preferred format: {preferred_format} (Fallback enabled: {allow_fallback})")

    song_pages, album_art_urls = get_auth_session(target_url)
    if not song_pages and not album_art_urls:
        return

    if album_art_urls:
        print(f"\nStarting multi-threaded download for {len(album_art_urls)} high-res images...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            img_futures = [
                executor.submit(worker_download_file, url, image_folder_path)
                for url in album_art_urls
            ]
            for future in as_completed(img_futures):
                future.result()
    else:
        print("Notice: No container elements matching class='albumImage' discovered on page.")

    if song_pages:
        real_audio_urls = []
        print(
            f"\nStarting {MAX_WORKERS} background threads to resolve "
            f"({preferred_format}) audio download URLs..."
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {
                executor.submit(
                    worker_extract_audio_src, url, preferred_format, allow_fallback
                ): url
                for url in song_pages
            }

            for idx, future in enumerate(as_completed(future_to_url), start=1):
                res_url, actual_fmt = future.result()
                if res_url:
                    real_audio_urls.append(res_url)
                    clean_preview = unquote(unquote(os.path.basename(urlparse(res_url).path)))
                    fallback_note = (
                        f" [fallback: {actual_fmt}]"
                        if actual_fmt and actual_fmt != preferred_format
                        else ""
                    )
                    print(f" Parsing [{idx}/{len(song_pages)}] Success -> {clean_preview}{fallback_note}")
                else:
                    print(
                        f" Parsing [{idx}/{len(song_pages)}] Format '{preferred_format}' "
                        f"not found or element missing"
                    )

        total_downloads = len(real_audio_urls)
        print(
            f"\nStarting multi-threaded download of {total_downloads} files "
            f"across {MAX_WORKERS} workers..."
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            audio_futures = [
                executor.submit(worker_download_file, url, album_folder_path)
                for url in real_audio_urls
            ]
            for future in as_completed(audio_futures):
                future.result()

    print(f"\nAll album media processing operations completed successfully inside: {album_folder_path}")


if __name__ == "__main__":
    main()