import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"

MAX_DOWNLOAD_SECONDS = int(os.getenv("MAX_DOWNLOAD_SECONDS", "900"))
MAX_FILE_SIZE = os.getenv("MAX_FILE_SIZE", "2000M")
X_TWITTER_IMPERSONATE = os.getenv("X_TWITTER_IMPERSONATE", "false")

SUPPORTED_HOSTS = {
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
    "x/twitter": ("x.com", "twitter.com"),
    "tiktok": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
    "instagram": ("instagram.com", "instagr.am"),
}


class LinkRequest(BaseModel):
    url: str


app = FastAPI(title="Snaggle")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def detect_platform(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    host = parsed.hostname.lower() if parsed.hostname else ""
    host = host.removeprefix("www.").removeprefix("m.").removeprefix("mobile.")

    for platform, suffixes in SUPPORTED_HOSTS.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return platform
    return None


def display_platform(platform: str | None) -> str:
    names = {
        "facebook": "Facebook",
        "x/twitter": "X/Twitter",
        "tiktok": "TikTok",
        "instagram": "Instagram",
    }
    return names.get(platform or "", "")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/detect")
def detect(payload: LinkRequest) -> dict[str, str | bool]:
    platform = detect_platform(payload.url)
    return {
        "supported": platform is not None,
        "platform": display_platform(platform),
    }


@app.post("/api/download")
def download(payload: LinkRequest, background_tasks: BackgroundTasks) -> FileResponse:
    platform = detect_platform(payload.url)
    if platform is None:
        raise HTTPException(
            status_code=400,
            detail="Use a supported Facebook, X/Twitter, TikTok, or Instagram link.",
        )

    work_dir = Path(tempfile.mkdtemp(prefix="snaggle-"))
    background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--restrict-filenames",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "--max-filesize",
        MAX_FILE_SIZE,
        "--paths",
        str(work_dir),
        "--output",
        "%(title).120B-%(id)s.%(ext)s",
    ]
    if platform == "x/twitter" and X_TWITTER_IMPERSONATE.lower() not in {"", "false"}:
        command.extend(["--impersonate", X_TWITTER_IMPERSONATE])
    command.append(payload.url.strip())

    try:
        completed = subprocess.run(
            command,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=MAX_DOWNLOAD_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Download timed out.") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()[-1:] or ["Download failed."]
        raise HTTPException(status_code=422, detail=message[0])

    files = [
        item
        for item in work_dir.iterdir()
        if item.is_file() and not item.name.endswith((".part", ".ytdl", ".json"))
    ]
    if not files:
        raise HTTPException(status_code=500, detail="No downloadable file was created.")

    video = max(files, key=lambda item: item.stat().st_mtime)
    return FileResponse(
        video,
        media_type="application/octet-stream",
        filename=video.name,
        background=background_tasks,
    )
