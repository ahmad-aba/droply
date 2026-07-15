"""Droply — a small self-hosted downloader for media you are allowed to save."""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

DIRECT_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "webp", "gif", "avif", "svg", "bmp",
    "mp3", "m4a", "aac", "wav", "ogg", "flac", "mp4", "webm", "mov", "mkv",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "avif", "svg", "bmp"}
FILE_EXTENSIONS = {"pdf"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

tasks: dict[str, dict[str, Any]] = {}
tasks_lock = threading.Lock()


def valid_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Paste a valid link first.")
    url = value.strip()
    if len(url) > 4096:
        raise ValueError("That link is too long.")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Use a complete http or https link.")

    hostname = parsed.hostname or ""
    if hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local addresses are not supported.")
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Private network addresses are not supported.")
    except ValueError as error:
        if str(error) in {"Private network addresses are not supported."}:
            raise
    return url


def extension_from_url(url: str) -> str:
    return Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")


def title_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    if name:
        return Path(name).stem[:120] or "download"
    return (urlparse(url).hostname or "download").replace("www.", "")


def is_direct_file(url: str) -> bool:
    return extension_from_url(url) in DIRECT_EXTENSIONS


def now() -> float:
    return time.time()


def find_output(task_id: str) -> Path | None:
    matches = [
        path for path in DOWNLOAD_DIR.glob(f"*-{task_id}.*")
        if not path.name.endswith((".part", ".ytdl", ".temp"))
    ]
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "status": task["status"],
        "progress": task["progress"],
        "stage": task["stage"],
        "title": task.get("title", "Preparing download"),
        "error": task.get("error"),
        "filename": task.get("filename"),
        "downloadUrl": (
            url_for("download_result", task_id=task["id"]) if task["status"] == "complete" else None
        ),
    }


def update_task(task_id: str, **changes: Any) -> None:
    with tasks_lock:
        task = tasks.get(task_id)
        if task:
            task.update(changes)


def prune_tasks() -> None:
    with tasks_lock:
        expired = [key for key, value in tasks.items() if now() - value["created_at"] > 6 * 60 * 60]
        for key in expired:
            task = tasks.pop(key)
            file_path = task.get("file_path")
            if file_path:
                Path(file_path).unlink(missing_ok=True)
        if len(tasks) > 60:
            oldest = sorted(tasks.values(), key=lambda item: item["created_at"])[:-60]
            for task in oldest:
                tasks.pop(task["id"], None)


def ytdlp_module():
    try:
        import yt_dlp  # type: ignore
    except ImportError as error:
        raise RuntimeError("The download engine is not installed. Run the setup command in the README.") from error
    return yt_dlp


def inspect_media(url: str) -> dict[str, Any]:
    if is_direct_file(url):
        ext = extension_from_url(url)
        kind = "image" if ext in IMAGE_EXTENSIONS else "document" if ext in FILE_EXTENSIONS else "media"
        return {
            "title": title_from_url(url),
            "thumbnail": None,
            "duration": None,
            "uploader": urlparse(url).hostname,
            "platform": "Direct file",
            "kind": kind,
            "formats": [],
            "direct": True,
        }

    yt_dlp = ytdlp_module()
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "http_headers": {"User-Agent": USER_AGENT},
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = [entry for entry in info.get("entries", []) if entry]
        if not entries:
            raise RuntimeError("This collection does not contain downloadable items.")
        info = entries[0]

    heights = sorted({
        fmt.get("height") for fmt in info.get("formats", [])
        if fmt.get("height") and fmt.get("vcodec") != "none"
    }, reverse=True)
    choices = [height for height in (2160, 1440, 1080, 720, 480, 360) if height in heights]
    return {
        "title": info.get("title") or "Untitled media",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel") or info.get("creator"),
        "platform": info.get("extractor_key", "Media").replace("Youtube", "YouTube"),
        "kind": "media",
        "formats": choices,
        "direct": False,
    }


def run_direct_download(task_id: str, url: str) -> None:
    try:
        update_task(task_id, status="downloading", stage="Downloading file", progress=1)
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30) as response:  # nosec B310 - URL is validated before task creation
            total = int(response.headers.get("Content-Length", 0) or 0)
            suggested = response.headers.get("Content-Disposition", "")
            match = re.search(r"filename\*?=(?:UTF-8''|\")?([^;\"]+)", suggested, re.I)
            filename = unquote(match.group(1)).strip() if match else Path(urlparse(url).path).name
            filename = secure_filename(filename) or f"download-{task_id}{Path(urlparse(url).path).suffix}"
            output = DOWNLOAD_DIR / f"{Path(filename).stem[:150]}-{task_id}{Path(filename).suffix.lower()}"
            received = 0
            with output.open("wb") as file:
                while chunk := response.read(1024 * 256):
                    file.write(chunk)
                    received += len(chunk)
                    progress = min(99, int(received / total * 100)) if total else 50
                    update_task(task_id, progress=progress)
        update_task(task_id, status="complete", stage="Ready to save", progress=100,
                    filename=output.name, file_path=str(output))
    except Exception as error:
        update_task(task_id, status="error", stage="Could not download", error=str(error), progress=0)


def run_media_download(task_id: str, url: str, output_type: str, quality: str) -> None:
    try:
        yt_dlp = ytdlp_module()
        has_ffmpeg = bool(shutil.which("ffmpeg"))

        def progress_hook(data: dict[str, Any]) -> None:
            if data.get("status") == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes", 0)
                percent = min(99, int(downloaded / total * 100)) if total else 8
                speed = data.get("_speed_str", "")
                update_task(task_id, status="downloading", stage=f"Downloading {speed}".strip(), progress=percent)
            elif data.get("status") == "finished":
                update_task(task_id, status="processing", stage="Finalizing file", progress=99)

        output_template = str(DOWNLOAD_DIR / f"%(title).160B-{task_id}.%(ext)s")
        options: dict[str, Any] = {
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "progress_hooks": [progress_hook],
            "http_headers": {"User-Agent": USER_AGENT},
        }

        if output_type == "file":
            # Preserve the source's best directly downloadable stream without conversion.
            options["format"] = "best"
        elif output_type == "audio":
            options["format"] = "bestaudio[ext=m4a]/bestaudio"
            if has_ffmpeg:
                options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
                options["postprocessor_args"] = {"FFmpegExtractAudio": ["-vn"]}
        else:
            allowed_heights = {"2160", "1440", "1080", "720", "480", "360"}
            if has_ffmpeg:
                if quality in allowed_heights:
                    options["format"] = f"bestvideo*[height<={quality}]+bestaudio/best[height<={quality}]"
                else:
                    options["format"] = "bestvideo*+bestaudio/best"
                options["merge_output_format"] = "mp4"
            else:
                # A progressive stream remains playable without requiring an FFmpeg installation.
                options["format"] = f"best[height<={quality}]/best" if quality in allowed_heights else "best"

        update_task(task_id, status="downloading", stage="Connecting to source", progress=1)
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        output = find_output(task_id)
        if not output:
            raise RuntimeError("The source did not return a downloadable file.")
        update_task(task_id, status="complete", stage="Ready to save", progress=100,
                    filename=output.name, file_path=str(output))
    except Exception as error:
        message = str(error).replace("ERROR: ", "")
        update_task(task_id, status="error", stage="Could not download", error=message, progress=0)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "engine": "yt-dlp"})


@app.post("/api/inspect")
def inspect():
    try:
        url = valid_url((request.get_json(silent=True) or {}).get("url"))
        return jsonify({"ok": True, "media": inspect_media(url)})
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 400


@app.post("/api/download")
def start_download():
    try:
        payload = request.get_json(silent=True) or {}
        url = valid_url(payload.get("url"))
        output_type = payload.get("type", "video")
        quality = str(payload.get("quality", "best"))
        if output_type not in {"video", "audio", "file"}:
            raise ValueError("Choose video, audio, or original file.")
        if quality not in {"best", "2160", "1440", "1080", "720", "480", "360"}:
            quality = "best"

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id, "status": "queued", "progress": 0, "stage": "Preparing download",
            "title": title_from_url(url), "error": None, "filename": None, "file_path": None,
            "created_at": now(),
        }
        with tasks_lock:
            tasks[task_id] = task
        prune_tasks()

        if is_direct_file(url):
            worker = threading.Thread(target=run_direct_download, args=(task_id, url), daemon=True)
        else:
            worker = threading.Thread(target=run_media_download, args=(task_id, url, output_type, quality), daemon=True)
        worker.start()
        return jsonify({"ok": True, "task": compact_task(task)})
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 400


@app.get("/api/tasks/<task_id>")
def task_status(task_id: str):
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            abort(404)
        return jsonify({"ok": True, "task": compact_task(task)})


@app.get("/api/downloads/<task_id>")
def download_result(task_id: str):
    with tasks_lock:
        task = tasks.get(task_id)
        if not task or task["status"] != "complete" or not task.get("file_path"):
            abort(404)
        path = Path(task["file_path"])
    if not path.is_file() or path.parent != DOWNLOAD_DIR:
        abort(404)
    return send_file(path, as_attachment=True, download_name=task.get("filename") or path.name, max_age=0)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=True)
