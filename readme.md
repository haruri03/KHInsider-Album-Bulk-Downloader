# KHInsider Album Bulk Downloader

A lightweight, multi-threaded Python automation script designed to bypass mass-download restrictions on KHInsider and scrape complete soundtracks in your preferred audio format alongside their high-resolution artwork assets locally.

## Motivation

This script was created to address the site's mass-download limitation for non-donating or non-uploading users, which triggers the following restriction:

> Ooops!
> Unfortunately, due to large server expenses we are no longer able to accomodate mass downloads for all registered users. To be able to use the mass download feature you are now required to give back to the site. This can be done in three ways:
> - Become an uploader! Click here to learn how to become an uploader!
> - Help keep the site alive by giving a small server donation. You can do so here.
> - Refer people to the site!

This script automates the process of entering individual song pages, selecting your preferred audio format, extracting direct media locations, and downloading album components seamlessly in bulk without triggering verification blocks or requiring a paid mass-download account.

## Features

- **Format Selection (`--format` / `-f`)**: Chooses your preferred audio format (such as `mp3`, `flac`, `ogg`, or `wav`) from available song download links on each track page, defaulting to `mp3`.
- **Smart Fallback & Strict Mode (`--no-fallback`)**: Falls back to the first available format when a track lacks your chosen format, or skips mismatched tracks when `--no-fallback` is enabled.
- **Single-Headed Authentication Hook**: Spawns an initial visible browser session for 10 seconds to satisfy Cloudflare checks and capture session access tokens.
- **Parallel Background Execution**: Switches completely to an efficient headless (invisible) state using 16 concurrent background worker threads to scrape direct audio stream positions.
- **Full-Resolution Art Asset Harvesting**: Locates thumbnail images in the album container, strips away compressed variations, and pulls the original source imagery.
- **Dynamic File Structure Allocation**: Automatically establishes an isolated directory under `./output/` utilizing the precise terminal URL identifier, containing a subfolder named `album_imgs` for cover assets.
- **Server Identity Retention**: Decodes complex network encodings and preserves authentic file titles derived from the source infrastructure.
- **Local Cache Check**: Checks the destination path prior to initializing stream operations to skip pre-existing tracks.

## Prerequisites

Ensure you have Python 3.8 or higher installed on your computer.

### Required Dependencies

Install the core web automation, HTML scraping, and network communication libraries:

```bash
pip install playwright beautifulsoup4 requests

```

### Setup Playwright Browsers

Download and configure the browser binaries required by the automation engine:

```bash
playwright install chromium

```

## Usage

Run the script from your terminal or command prompt by passing the target album URL and optional format flags. Wrap the link in double quotes to avoid terminal parsing errors.

### Command Syntax

```bash
python khinsider_dl.py "<TARGET_ALBUM_URL>" [-f FORMAT] [--no-fallback]

```

### Options

* `<TARGET_ALBUM_URL>`: Target KHInsider album URL.
* `-f`, `--format`: Preferred audio format (e.g., `mp3`, `flac`, `ogg`, `wav`). Default: `mp3`.
* `--no-fallback`: Skip tracks that do not offer the requested format instead of falling back to another available format.

### Execution Examples

Download `flac` when available (falling back to another available format on tracks without `flac`):

```bash
python khinsider_dl.py "[https://downloads.khinsider.com/game-soundtracks/album/seiryu-blue-dragon-qwce-00318-2013](https://downloads.khinsider.com/game-soundtracks/album/seiryu-blue-dragon-qwce-00318-2013)" --format flac
```

Download `mp3` strictly without falling back to other formats:

```bash
python khinsider_dl.py "[https://downloads.khinsider.com/game-soundtracks/album/seiryu-blue-dragon-qwce-00318-2013](https://downloads.khinsider.com/game-soundtracks/album/seiryu-blue-dragon-qwce-00318-2013)" -f mp3 --no-fallback

```

## Workflow Overview

1. **Initialization**: The script parses command-line arguments and format preferences, decodes the URL trailing segment, and structures your storage folder layout.
2. **Interactive Window Challenge**: Chromium pops open. Use this brief 10-second gap to solve any "I am human" puzzle if prompted by Cloudflare.
3. **Asset Harvesting**: The application registers valid access credentials, shuts down the visible context, initializes background instances to resolve matching format links, extracts high-res covers into `album_imgs`, and triggers multi-threaded downloads for all selected soundtrack items.

