import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests

MAX_WORKERS = 16  
SESSION_COOKIES = []
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

def apply_stealth(page):
    """Removes automation flags to mimic real user behavior."""
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

def extract_album_folder_name(url):
    """Parses the URL to find the last valid segment for the folder name."""
    parsed = urlparse(url)
    path_segments = [seg for seg in parsed.path.split('/') if seg]
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
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 720})
        page = context.new_page()
        apply_stealth(page)
        
        page.goto(album_url, wait_until="load", timeout=60000)
        
        print("Please complete the Cloudflare verification if it appears.")
        print("The script will save credentials and close this window in 10 seconds...")
        time.sleep(10)
        
        SESSION_COOKIES = context.cookies()
        html = page.content()
        browser.close()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract and convert ALL thumbnail URLs to original full-resolution image URLs
        album_art_urls = []
        album_img_containers = soup.find_all(class_='albumImage')
        for container in album_img_containers:
            img_tags = container.find_all('img')
            for img in img_tags:
                if img.get('src'):
                    thumb_url = urljoin(album_url, img.get('src'))
                    original_url = thumb_url.replace('/thumbs/', '/')
                    if original_url not in album_art_urls:
                        album_art_urls.append(original_url)
        
        # Extract song pages from table
        table = soup.find('table', id='songlist')
        if not table:
            print("Error: Authentication failed or could not find table with id='songlist'.")
            return [], []
            
        song_links = []
        td_elements = table.find_all('td', class_='playlistDownloadSong')
        for td in td_elements:
            a_tag = td.find('a')
            if a_tag and a_tag.get('href'):
                song_links.append(urljoin(album_url, a_tag.get('href')))
                
        print(f"Authentication successful. Extracted {len(song_links)} song pages and {len(album_art_urls)} image links.")
        return song_links, album_art_urls

def worker_extract_audio_src(song_url):
    """Background thread worker to resolve the final audio file source."""
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
            
            soup = BeautifulSoup(html, 'html.parser')
            audio_tag = soup.find('audio', id='audio')
            if audio_tag:
                src = audio_tag.get('src') or (audio_tag.find('source').get('src') if audio_tag.find('source') else None)
                if src:
                    return urljoin(song_url, src)
    except Exception:
        pass
    return None

def worker_download_file(download_url, output_folder):
    """Background thread worker to handle binary download via requests."""
    global SESSION_COOKIES
    try:
        req_cookies = {c['name']: c['value'] for c in SESSION_COOKIES}
        headers = {"User-Agent": USER_AGENT}
        
        response = requests.get(download_url, headers=headers, cookies=req_cookies, stream=True, timeout=20)
        if response.status_code == 200:
            cd = response.headers.get('content-disposition')
            if cd and 'filename=' in cd:
                filename = re.findall('filename=(.+)', cd).strip('" ')
            else:
                filename = os.path.basename(urlparse(download_url).path)
            
            filename = unquote(unquote(filename))
            filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
            output_path = os.path.join(output_folder, filename)
            
            if os.path.exists(output_path):
                print(f"[Skipped] File already exists: {filename}")
                return True
                
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=16384):
                    f.write(chunk)
            print(f"[Downloaded] Saved: {filename}")
            return True
    except Exception as e:
        print(f"Download failed: {download_url} -> {e}")
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python khinsider_dl.py <TARGET_ALBUM_URL>")
        print("Example: python khinsider_dl.py \"https://downloads.khinsider.com/game-soundtracks/album/seiryu-blue-dragon-qwce-00318-2013\"")
        sys.exit(1)
        
    # Fixed: Extracting string index from list before calling string methods
    target_url = sys.argv[1].strip()
    
    album_folder_name = extract_album_folder_name(target_url)
    album_folder_path = os.path.join(os.getcwd(), album_folder_name)
    image_folder_path = os.path.join(album_folder_path, "album_imgs")
    
    os.makedirs(album_folder_path, exist_ok=True)
    os.makedirs(image_folder_path, exist_ok=True)
    print(f"Album directory: {album_folder_path}")
    print(f"Images subdirectory: {image_folder_path}")
    
    song_pages, album_art_urls = get_auth_session(target_url)
    if not song_pages and not album_art_urls:
        return
        
    if album_art_urls:
        print(f"\nStarting multi-threaded download for {len(album_art_urls)} high-res images...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            img_futures = [executor.submit(worker_download_file, url, image_folder_path) for url in album_art_urls]
            for future in as_completed(img_futures):
                pass
    else:
        print("Notice: No container elements matching class='albumImage' discovered on page.")
        
    if song_pages:
        real_audio_urls = []
        print(f"\nStarting {MAX_WORKERS} background threads to resolve direct audio download URLs...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(worker_extract_audio_src, url): url for url in song_pages}
            
            for idx, future in enumerate(as_completed(future_to_url), start=1):
                res_url = future.result()
                if res_url:
                    real_audio_urls.append(res_url)
                    clean_preview = unquote(unquote(os.path.basename(urlparse(res_url).path)))
                    print(f" Parsing [{idx}/{len(song_pages)}] Success -> {clean_preview}")
                else:
                    print(f" Parsing [{idx}/{len(song_pages)}] Failed or element not found")

        total_downloads = len(real_audio_urls)
        print(f"\nStarting multi-threaded download of {total_downloads} files across {MAX_WORKERS} workers...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            audio_futures = [executor.submit(worker_download_file, url, album_folder_path) for url in real_audio_urls]
            for future in as_completed(audio_futures):
                pass
        
    print(f"\nAll album media processing operations completed successfully inside: {album_folder_path}")

if __name__ == "__main__":
    main()
