# Flickr Photo Downloader

A small local browser app for downloading public Flickr photos in batches and saving each photo description as a matching `.txt` file.

The app uses [`gallery-dl`](https://codeberg.org/mikf/gallery-dl) to read Flickr metadata, then downloads the media files and writes description files locally. Flickr API credentials are not required for public content.

## Features

- Add multiple Flickr links to a queue
- Download queued links one by one
- Save each Flickr album or link into its own folder
- Save every image with a matching `.txt` description file
- Create an `about.txt` file for each album/link folder
- Skip already downloaded files on later runs
- Use slow, sequential downloads to reduce blocking risk

## Quick Start

macOS/Linux:

```bash
./run.sh
```

The script creates a local `.venv`, installs dependencies, starts a local server, and opens the app in your browser.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python flickr_downloader_app.py
```

Windows Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python flickr_downloader_app.py
```

Manual setup on macOS/Linux is also supported:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python flickr_downloader_app.py
```

After startup, the app opens a local browser page.

## How To Use

1. Paste a public Flickr URL.
2. Choose a destination folder.
3. Click **Add to Queue**.
4. Add more links if needed.
5. Click **Start Queue**.

Jobs run one by one. **Cancel Current** stops the active job and leaves pending jobs in the queue.

## Output

Each Flickr album or link is saved inside its own subfolder under the destination folder.

Album folders use this format:

```text
Album title - Album ID
```

For each downloaded image:

```text
photo-name.jpg
photo-name.txt
```

The `.txt` file contains only the Flickr photo description. If no description is available, an empty matching `.txt` file is still created.

Each folder also gets an `about.txt` file:

```text
Saigon markets
URL: https://www.flickr.com/photos/97930879@N02/albums/72157638035079914/
by TommyJapan1: https://www.flickr.com/photos/97930879@N02/
```

## Notes

- The app is designed for public Flickr URLs.
- Downloads are intentionally sequential and paced slowly.
- Existing completed image files are skipped, but matching `.txt` files are refreshed.
- Failed download details are appended to `flickr_downloader_errors.log` in the relevant output folder.

## License And Credits

This project is licensed under GPL-2.0-only.

This app uses [`gallery-dl`](https://codeberg.org/mikf/gallery-dl), developed by Mike Fährmann and contributors, published under GPL-2.0-only.
