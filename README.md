# Flickr Photo Downloader

A small Mac-first browser app for downloading public Flickr photos and saving each photo description as a matching `.txt` file.

The app uses [`gallery-dl`](https://codeberg.org/mikf/gallery-dl) for Flickr extraction metadata. Flickr API credentials are not required for public content.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python flickr_downloader_app.py
```

Or run:

```bash
./run.sh
```

`run.sh` creates `.venv`, installs dependencies, starts a local server, and opens the app in your browser.

## Batch Downloads

Paste a Flickr URL, choose a destination folder, and click **Add to Queue**. Add as many links as needed, then click **Start Queue**.

Jobs run one by one. **Cancel Current** stops the active job and leaves pending jobs in the queue so they can be started later.

## What It Saves

For each downloaded image:

- `photo-name.jpg`
- `photo-name.txt`

The `.txt` file contains only the Flickr photo description when available. If no description is available, the app still creates an empty matching `.txt` file.

Each Flickr album or link is saved inside its own subfolder under the destination folder. Album folders use:

```text
Album title - Album ID
```

Each folder also gets an `about.txt` file with the album/link title, source URL, and Flickr owner URL when available.

Example:

```text
Saigon markets
URL: https://www.flickr.com/photos/97930879@N02/albums/72157638035079914/
by TommyJapan1: https://www.flickr.com/photos/97930879@N02/
```

## Notes

- Version 1 is for public Flickr URLs.
- Downloads are intentionally paced slowly to reduce blocking risk.
- Cancel is supported. True pause/resume is approximated by canceling and starting again; existing downloaded files are skipped on the next run.
- Failed run details are appended to `flickr_downloader_errors.log` in the selected destination folder.

## License And Credits

This project is licensed under GPL-2.0-only.

This project is not a fork of `gallery-dl`; it is a small browser app that depends on `gallery-dl` through `requirements.txt`. `gallery-dl` is developed by Mike Fährmann and contributors, hosted at <https://codeberg.org/mikf/gallery-dl>, and published under GPL-2.0-only.

If this project later copies or modifies `gallery-dl` source code directly, treat that as derivative/fork-like work and keep the GPL obligations intact. This is engineering guidance, not legal advice.

## Publishing To GitHub

Create an empty GitHub repository in your browser, then run these commands from this folder:

```bash
git init
git add .
git commit -m "Initial Flickr downloader app"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```
