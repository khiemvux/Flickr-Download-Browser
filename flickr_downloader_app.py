#!/usr/bin/env python3
"""Local browser app for downloading public Flickr photos and descriptions."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import random
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional


APP_TITLE = "Flickr Photo Downloader"
SAFE_DELAY_RANGE = (3.0, 6.0)
MAX_RETRIES = 5
CHUNK_SIZE = 1024 * 256
EVENT_DONE = "done"
EVENT_ERROR = "error"
EVENT_INFO = "info"
STATUS_PENDING = "Pending"
STATUS_RUNNING = "Running"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"
STATUS_CANCELED = "Canceled"


@dataclass
class DownloadItem:
    media_url: str
    filename: str
    description: str


@dataclass
class CollectionInfo:
    folder_name: str
    title: str
    source_url: str
    owner_name: str
    owner_url: str


@dataclass
class ParsedDownload:
    items: list[DownloadItem]
    collection: CollectionInfo


@dataclass
class QueueJob:
    id: int
    url: str
    destination: Path
    status: str = STATUS_PENDING
    folder: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "destination": str(self.destination),
            "status": self.status,
            "folder": self.folder,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "error": self.error,
        }


def is_probably_flickr_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    return host == "flickr.com" or host.endswith(".flickr.com")


def sanitize_filename(value: Any, fallback: str = "flickr_photo") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return text[:140] or fallback


def filename_from_item(item: dict[str, Any]) -> str:
    media_url = str(item.get("url") or "")
    parsed = urllib.parse.urlparse(media_url)
    suffix = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
    if not suffix or len(suffix) > 8:
        suffix = mimetypes.guess_extension(str(item.get("mime") or "")) or ".jpg"

    photo_id = sanitize_filename(item.get("id"), "unknown")
    title = sanitize_filename(item.get("title"), "")
    base = f"{title}_{photo_id}" if title else f"flickr_{photo_id}"
    return sanitize_filename(base, f"flickr_{photo_id}") + suffix


def description_path_for(image_path: Path) -> Path:
    return image_path.with_suffix(".txt")


def album_folder_name(album: dict[str, Any]) -> str:
    title = sanitize_filename(album.get("title"), "Flickr album")
    album_id = sanitize_filename(album.get("id"), "unknown")
    return sanitize_filename(f"{title} - {album_id}", f"Flickr album - {album_id}")


def fallback_folder_name(url: str, first_item: Optional[dict[str, Any]]) -> str:
    if first_item:
        title = sanitize_filename(first_item.get("title"), "")
        photo_id = sanitize_filename(first_item.get("id"), "unknown")
        if title:
            return sanitize_filename(f"{title} - {photo_id}", f"Flickr link - {photo_id}")
        return sanitize_filename(f"Flickr link - {photo_id}", "Flickr link")
    parsed = urllib.parse.urlparse(url)
    return sanitize_filename(parsed.path.strip("/").replace("/", " - "), "Flickr link")


def owner_from_metadata(meta: dict[str, Any]) -> tuple[str, str]:
    owner = meta.get("user") or meta.get("owner") or {}
    if not isinstance(owner, dict):
        return "Unknown owner", ""
    name = str(owner.get("realname") or owner.get("username") or owner.get("path_alias") or owner.get("nsid") or "")
    alias = str(owner.get("path_alias") or owner.get("nsid") or "").strip()
    url = str(owner.get("photosurl") or "")
    if not url and alias:
        url = f"https://www.flickr.com/photos/{alias}/"
    return name or "Unknown owner", url


def collection_info_from_metadata(url: str, metas: list[dict[str, Any]]) -> CollectionInfo:
    first = metas[0] if metas else {}
    album = first.get("album") if isinstance(first.get("album"), dict) else None
    owner_name, owner_url = owner_from_metadata(first)
    if album:
        title = str(album.get("title") or "Flickr album")
        return CollectionInfo(
            folder_name=album_folder_name(album),
            title=title,
            source_url=url,
            owner_name=owner_name,
            owner_url=owner_url,
        )
    title = str(first.get("title") or "Flickr link")
    return CollectionInfo(
        folder_name=fallback_folder_name(url, first),
        title=title,
        source_url=url,
        owner_name=owner_name,
        owner_url=owner_url,
    )


def render_about_text(info: CollectionInfo) -> str:
    lines = [info.title, f"URL: {info.source_url}"]
    if info.owner_url:
        lines.append(f"by {info.owner_name}: {info.owner_url}")
    else:
        lines.append(f"by {info.owner_name}")
    return "\n".join(lines) + "\n"


def parse_gallery_dl_dump(payload: str, source_url: str = "") -> ParsedDownload:
    data = json.loads(payload)
    metas: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            if len(node) >= 2 and node[0] == 2 and isinstance(node[1], dict):
                metas.append(node[1])
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for child in node.values():
                visit(child)

    visit(data)
    items = [
        DownloadItem(
            media_url=str(meta.get("url") or ""),
            filename=filename_from_item(meta),
            description=str(meta.get("description") or ""),
        )
        for meta in metas
        if str(meta.get("url") or "").startswith(("http://", "https://"))
    ]
    return ParsedDownload(items=items, collection=collection_info_from_metadata(source_url, metas))


def gallery_dl_module_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "gallery_dl", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def collect_flickr_items(url: str) -> ParsedDownload:
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--dump-json",
        "--simulate",
        "--no-colors",
        url,
    ]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "gallery-dl failed").strip()
        raise RuntimeError(message)
    return parse_gallery_dl_dump(result.stdout, url)


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.events: list[dict[str, Any]] = []
        self.jobs: list[QueueJob] = []
        self.next_job_id = 1
        self.running = False
        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None

    def log(self, message: str, event_type: str = EVENT_INFO) -> None:
        with self.condition:
            entry = {
                "id": len(self.events),
                "type": event_type,
                "message": message,
                "time": time.strftime("%H:%M:%S"),
                "running": self.running,
            }
            self.events.append(entry)
            self.condition.notify_all()

    def add_job(self, url: str, destination: Path) -> QueueJob:
        with self.lock:
            job = QueueJob(id=self.next_job_id, url=url, destination=destination)
            self.next_job_id += 1
            self.jobs.append(job)
        self.log(f"Queued job #{job.id}: {url}")
        return job

    def start_queue(self) -> bool:
        with self.lock:
            if self.running:
                return False
            if not any(job.status == STATUS_PENDING for job in self.jobs):
                return False
            self.running = True
            self.cancel_event.clear()
            self.worker = threading.Thread(target=run_queue, args=(self,), daemon=True)
            self.worker.start()
            return True

    def cancel(self) -> None:
        self.cancel_event.set()
        self.log("Cancel requested. Current job will stop; pending jobs will stay in queue.")

    def clear_queue(self) -> None:
        with self.lock:
            self.jobs = []
            self.events = []
            self.next_job_id = 1
        self.log("Queue and log history cleared.")

    def pending_jobs(self) -> list[QueueJob]:
        with self.lock:
            return [job for job in self.jobs if job.status == STATUS_PENDING]

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [job.to_dict() for job in self.jobs]

    def set_running(self, running: bool) -> None:
        with self.condition:
            self.running = running
            self.condition.notify_all()


STATE = AppState()


def write_error_log(destination: Path, source_url: str, message: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    error_log = destination / "flickr_downloader_errors.log"
    with error_log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {source_url}\n")
        handle.write(message.strip() + "\n")


def download_file(item: DownloadItem, image_path: Path, cancel_event: threading.Event) -> None:
    part_path = image_path.with_name(image_path.name + ".part")
    request = urllib.request.Request(item.media_url, headers={"User-Agent": "Mozilla/5.0 FlickrDownloader/1.0"})

    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl._create_unverified_context()

    try:
        response = urllib.request.urlopen(request, timeout=45, context=context)
    except Exception:
        if not isinstance(context, ssl.SSLContext) or context.verify_mode != ssl.CERT_NONE:
            context = ssl._create_unverified_context()
            response = urllib.request.urlopen(request, timeout=45, context=context)
        else:
            raise

    with response, part_path.open("wb") as output:
        while True:
            if cancel_event.is_set():
                raise RuntimeError("Download canceled")
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)

    part_path.replace(image_path)


def run_queue(state: AppState) -> None:
    try:
        state.log("Queue started.")
        while not state.cancel_event.is_set():
            pending = state.pending_jobs()
            if not pending:
                state.log("Queue finished.", EVENT_DONE)
                return
            run_one_job(state, pending[0])
        state.log("Queue stopped. Pending jobs remain in the list.", EVENT_DONE)
    finally:
        state.set_running(False)


def run_one_job(state: AppState, job: QueueJob) -> None:
    job.status = STATUS_RUNNING
    job.error = ""
    prefix = f"Job #{job.id}"
    try:
        state.log(f"{prefix}: reading Flickr metadata.")
        parsed = collect_flickr_items(job.url)
        if not parsed.items:
            raise RuntimeError("No downloadable public media URL was found.")

        folder = unique_folder(job.destination / parsed.collection.folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "about.txt").write_text(render_about_text(parsed.collection), encoding="utf-8")

        job.folder = str(folder)
        job.total = len(parsed.items)
        state.log(f"{prefix}: found {job.total} item(s). Saving to {folder}")

        used_names: set[str] = set()
        for index, item in enumerate(parsed.items, start=1):
            if state.cancel_event.is_set():
                job.status = STATUS_CANCELED
                state.log(f"{prefix}: canceled.", EVENT_DONE)
                return

            filename = unique_filename(item.filename, used_names)
            image_path = folder / filename
            text_path = description_path_for(image_path)
            used_names.add(filename)

            if image_path.exists() and image_path.stat().st_size > 0:
                text_path.write_text(item.description, encoding="utf-8")
                job.completed += 1
                state.log(f"{prefix} [{index}/{job.total}]: skipped existing {filename}; refreshed .txt")
                continue

            state.log(f"{prefix} [{index}/{job.total}]: downloading {filename}")
            try:
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        download_file(item, image_path, state.cancel_event)
                        text_path.write_text(item.description, encoding="utf-8")
                        job.completed += 1
                        state.log(f"{prefix}: saved {filename} and {text_path.name}")
                        break
                    except Exception as exc:
                        if state.cancel_event.is_set():
                            raise
                        if attempt == MAX_RETRIES:
                            raise
                        wait = min(30, attempt * 4)
                        state.log(f"{prefix}: retry {attempt}/{MAX_RETRIES - 1} after error: {exc}. Waiting {wait}s.")
                        time.sleep(wait)
            except Exception as exc:
                if state.cancel_event.is_set():
                    job.status = STATUS_CANCELED
                    state.log(f"{prefix}: canceled.", EVENT_DONE)
                    return
                job.failed += 1
                message = f"Failed {filename}: {exc}"
                write_error_log(folder, item.media_url, message)
                state.log(f"{prefix}: {message}", EVENT_ERROR)

            if index < job.total and not state.cancel_event.is_set():
                delay = random.uniform(*SAFE_DELAY_RANGE)
                state.log(f"{prefix}: waiting {delay:.1f}s before next file.")
                state.cancel_event.wait(delay)

        job.status = STATUS_FAILED if job.failed and not job.completed else STATUS_DONE
        state.log(f"{prefix}: finished. {job.completed} saved/skipped, {job.failed} failed.", EVENT_DONE)
    except Exception as exc:
        job.status = STATUS_FAILED
        job.error = str(exc)
        write_error_log(job.destination, job.url, str(exc))
        state.log(f"{prefix}: error: {exc}", EVENT_ERROR)


def unique_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while candidate in used_names:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def unique_folder(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.name} ({counter})")
        if not candidate.exists():
            return candidate
        counter += 1


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flickr Photo Downloader</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0a84ff;
      --danger: #b42318;
      --ok: #067647;
      --pending: #8a6100;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 16px;
    }
    main { width: min(1080px, calc(100vw - 40px)); margin: 0 auto; padding: 34px 0; }
    h1 { margin: 0 0 6px; font-size: 30px; letter-spacing: 0; }
    .sub { margin: 0 0 22px; color: var(--muted); }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }
    label { display: block; margin: 0 0 7px; font-weight: 650; }
    input {
      width: 100%;
      min-height: 44px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--text);
      background: #fff;
      font: inherit;
    }
    .row { margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; }
    .actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    button {
      min-height: 42px;
      padding: 9px 16px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    #status { margin-left: auto; color: var(--muted); font-weight: 650; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 650; }
    .job-url { word-break: break-word; }
    .Pending { color: var(--pending); }
    .Running { color: var(--accent); }
    .Done { color: var(--ok); }
    .Failed, .Canceled { color: var(--danger); }
    #log {
      height: 300px;
      margin-top: 0;
      padding: 14px;
      overflow: auto;
      white-space: pre-wrap;
      background: #101828;
      color: #e6edf3;
      border-radius: 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.45;
    }
    @media (max-width: 760px) {
      main { width: min(100vw - 24px, 1080px); padding: 20px 0; }
      .grid { grid-template-columns: 1fr; }
      #status { width: 100%; margin-left: 0; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Flickr Photo Downloader</h1>
    <p class="sub">Add multiple Flickr links, then download them one by one into separate folders.</p>

    <section class="panel">
      <div class="grid">
        <div class="row">
          <label for="url">Flickr URL</label>
          <input id="url" placeholder="https://www.flickr.com/photos/...">
        </div>
        <div class="row">
          <label for="destination">Save to folder</label>
          <div style="display: flex; gap: 8px;">
            <input id="destination" value="__DEFAULT_DESTINATION__" style="flex: 1;">
            <button id="browse" style="min-height: 44px; white-space: nowrap;">Browse...</button>
          </div>
        </div>
      </div>
      <div class="actions">
        <button id="add">Add to Queue</button>
        <button class="primary" id="start">Start Queue</button>
        <button id="cancel" disabled>Cancel Current</button>
        <button id="clear" disabled>Clear Queue</button>
        <span id="status">Ready</span>
      </div>
    </section>

    <section class="panel">
      <table>
        <thead>
          <tr>
            <th style="width: 72px;">Job</th>
            <th>URL</th>
            <th style="width: 120px;">Status</th>
            <th style="width: 120px;">Progress</th>
          </tr>
        </thead>
        <tbody id="jobs"><tr><td colspan="4">No jobs queued.</td></tr></tbody>
      </table>
    </section>

    <section class="panel">
      <div id="log">Ready.</div>
    </section>
  </main>
  <script>
    const urlInput = document.querySelector("#url");
    const destinationInput = document.querySelector("#destination");
    const addButton = document.querySelector("#add");
    const startButton = document.querySelector("#start");
    const cancelButton = document.querySelector("#cancel");
    const clearButton = document.querySelector("#clear");
    const browseButton = document.querySelector("#browse");
    const statusText = document.querySelector("#status");
    const log = document.querySelector("#log");
    const jobsBody = document.querySelector("#jobs");

    function appendLog(message, type) {
      if (log.textContent === "Ready.") log.textContent = "";
      const prefix = new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
      log.textContent += `[${prefix}] ${message}\\n`;
      log.scrollTop = log.scrollHeight;
      if (type === "error") statusText.textContent = "Error";
      if (type === "done") statusText.textContent = "Done";
    }

    async function refreshJobs() {
      const response = await fetch("/api/jobs");
      const data = await response.json();
      const jobs = data.jobs || [];
      const running = Boolean(data.running);
      cancelButton.disabled = !running;
      startButton.disabled = running || !jobs.some(job => job.status === "Pending");
      clearButton.disabled = running || !jobs.length;
      statusText.textContent = running ? "Running queue..." : "Ready";
      if (!jobs.length) {
        jobsBody.innerHTML = '<tr><td colspan="4">No jobs queued.</td></tr>';
        return;
      }
      jobsBody.innerHTML = jobs.map(job => `
        <tr>
          <td>#${job.id}</td>
          <td class="job-url">${job.url}${job.folder ? `<br><small>${job.folder}</small>` : ""}</td>
          <td class="${job.status}">${job.status}</td>
          <td>${job.completed}/${job.total || "?"}${job.failed ? `, ${job.failed} failed` : ""}</td>
        </tr>
      `).join("");
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {})
      });
      const data = await response.json();
      if (!response.ok) appendLog(data.error || "Request failed.", "error");
      await refreshJobs();
      return response.ok;
    }

    addButton.addEventListener("click", async () => {
      const ok = await postJson("/api/queue", {url: urlInput.value, destination: destinationInput.value});
      if (ok) urlInput.value = "";
    });
    startButton.addEventListener("click", async () => { await postJson("/api/start", {}); });
    cancelButton.addEventListener("click", async () => { await postJson("/api/cancel", {}); });
    browseButton.addEventListener("click", async () => {
      browseButton.disabled = true;
      try {
        const response = await fetch("/api/browse");
        const data = await response.json();
        if (data.ok && data.directory) {
          destinationInput.value = data.directory;
        }
      } catch (err) {
        console.error(err);
      } finally {
        browseButton.disabled = false;
      }
    });
    clearButton.addEventListener("click", async () => {
      if (confirm("Are you sure you want to clear the queue and log history?")) {
        await postJson("/api/clear", {});
        log.textContent = "Ready.";
      }
    });

    const events = new EventSource("/api/events");
    events.onmessage = async (event) => {
      const data = JSON.parse(event.data);
      appendLog(data.message, data.type);
      await refreshJobs();
    };
    setInterval(refreshJobs, 2000);
    refreshJobs();
  </script>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "FlickrDownloader/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            default_destination = html.escape(str(Path.home() / "Downloads" / "Flickr"), quote=True)
            page = HTML_PAGE.replace("__DEFAULT_DESTINATION__", default_destination)
            self.send_text(page, "text/html; charset=utf-8")
        elif self.path == "/api/events":
            self.stream_events()
        elif self.path == "/api/jobs":
            self.send_json({"jobs": STATE.snapshot(), "running": STATE.running})
        elif self.path == "/api/browse":
            self.browse_directory()
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/queue":
            self.add_to_queue()
        elif self.path == "/api/start":
            self.start_queue()
        elif self.path == "/api/cancel":
            STATE.cancel()
            self.send_json({"ok": True})
        elif self.path == "/api/clear":
            STATE.clear_queue()
            self.send_json({"ok": True})
        elif self.path == "/api/download":
            self.add_to_queue(start=True)
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def add_to_queue(self, start: bool = False) -> None:
        try:
            payload = self.read_json()
            url = str(payload.get("url") or "").strip()
            dest_str = str(payload.get("destination") or "").strip().strip("\u202a\u202b\u202c\u202d\u202e\u200e\u200f\ufeff")
            destination = Path(dest_str).expanduser()
            if not is_probably_flickr_url(url):
                self.send_json({"error": "Please paste a valid public Flickr URL."}, HTTPStatus.BAD_REQUEST)
                return
            if is_probably_flickr_url(dest_str):
                self.send_json({"error": "Save folder cannot be a Flickr URL. Please swap the inputs."}, HTTPStatus.BAD_REQUEST)
                return
            if not str(destination):
                self.send_json({"error": "Please enter a save folder."}, HTTPStatus.BAD_REQUEST)
                return
            if not gallery_dl_module_available():
                self.send_json({"error": "gallery-dl is not installed. Run ./run.sh again."}, HTTPStatus.BAD_REQUEST)
                return
            job = STATE.add_job(url, destination)
            if start:
                STATE.start_queue()
            self.send_json({"ok": True, "job": job.to_dict()})
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def start_queue(self) -> None:
        if STATE.start_queue():
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "No pending jobs to start, or the queue is already running."}, HTTPStatus.CONFLICT)

    def browse_directory(self) -> None:
        try:
            script = (
                "import tkinter as tk\n"
                "from tkinter import filedialog\n"
                "root = tk.Tk()\n"
                "root.withdraw()\n"
                "root.attributes('-topmost', True)\n"
                "print(filedialog.askdirectory(title='Select Destination Folder'), end='')\n"
                "root.destroy()\n"
            )
            result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, check=True)
            directory = result.stdout.strip()
            self.send_json({"ok": True, "directory": directory})
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def stream_events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        index = 0
        try:
            while True:
                with STATE.condition:
                    STATE.condition.wait_for(lambda: index < len(STATE.events), timeout=15)
                    events = STATE.events[index:]
                    index = len(STATE.events)
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                for event in events:
                    payload = json.dumps(event)
                    self.wfile.write(f"id: {event['id']}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_text(self, text: str, content_type: str) -> None:
        data = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_server(port: int, open_browser: bool) -> None:
    address = ("127.0.0.1", port)
    server = ThreadingHTTPServer(address, RequestHandler)
    url = f"http://{address[0]}:{address[1]}"
    print(f"{APP_TITLE} is running at {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", type=int, default=0, help="Local port. Defaults to an available port.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args(argv)

    port = args.port or find_free_port()
    run_server(port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
