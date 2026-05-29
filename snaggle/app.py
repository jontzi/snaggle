import json
import os
import re
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
X_TWITTER_IMPERSONATE_TARGETS = os.getenv(
    "X_TWITTER_IMPERSONATE_TARGETS",
    "chrome,chrome:windows-10,false",
)
X_TWITTER_API_TARGETS = os.getenv("X_TWITTER_API_TARGETS", "syndication,graphql,legacy")
X_TWITTER_FORCE_IPV4 = os.getenv("X_TWITTER_FORCE_IPV4", "true").lower() != "false"
X_TWITTER_FX_FALLBACK = os.getenv("X_TWITTER_FX_FALLBACK", "true").lower() != "false"
FXTWITTER_API_BASE = os.getenv("FXTWITTER_API_BASE", "https://api.fxtwitter.com").rstrip("/")
FXTWITTER_API_PATHS = os.getenv(
    "FXTWITTER_API_PATHS",
    "/2/status/{id},/status/{id},/{id}",
)
HTTP_USER_AGENT = os.getenv(
    "SNAGGLE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
)

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


def extract_tweet_id(url: str) -> str | None:
    match = re.search(r"/status(?:es)?/(\d{2,20})", urlparse(url).path)
    return match.group(1) if match else None


def run_curl(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    command = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "2",
        "--connect-timeout",
        "30",
        "--max-time",
        str(timeout),
        "--user-agent",
        HTTP_USER_AGENT,
        *args,
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def request_json(url: str) -> dict:
    completed = run_curl(
        ["--header", "Accept: application/json", url],
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "curl request failed")
    return json.loads(completed.stdout)


def download_direct_file(url: str, destination: Path) -> Path:
    completed = run_curl(
        ["--output", str(destination), url],
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "curl download failed")
    return destination


def find_video_urls(value: object) -> list[str]:
    urls = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and ".mp4" in item:
                urls.append(item)
            else:
                urls.extend(find_video_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(find_video_urls(item))
    return urls


def download_twitter_via_fxtwitter(url: str, work_dir: Path) -> Path:
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        raise ValueError("Could not find a tweet ID in the X/Twitter link.")

    errors = []
    data = None
    for path_template in FXTWITTER_API_PATHS.split(","):
        path = path_template.strip().format(id=tweet_id)
        try:
            data = request_json(f"{FXTWITTER_API_BASE}{path}")
            break
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

    if data is None:
        raise ValueError("; ".join(errors) or "FxTwitter request failed.")

    if data.get("code") != 200:
        raise ValueError(data.get("message") or "FxTwitter could not resolve this post.")

    status = data.get("status") or {}
    media = status.get("media") or {}
    candidates = [video for video in media.get("videos") or [] if video.get("url")]

    external = media.get("external") or {}
    if external.get("url"):
        candidates.append(external)

    recursive_urls = find_video_urls(data)
    if not candidates and not recursive_urls:
        raise ValueError("FxTwitter did not find a downloadable video for this post.")

    if candidates:
        selected = max(candidates, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))
        media_url = selected["url"]
    else:
        media_url = sorted(recursive_urls)[-1]

    extension = Path(urlparse(media_url).path).suffix or ".mp4"
    return download_direct_file(media_url, work_dir / f"x-twitter-{tweet_id}{extension}")


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

    fallback_error = None
    if platform == "x/twitter" and X_TWITTER_FX_FALLBACK:
        try:
            video = download_twitter_via_fxtwitter(payload.url.strip(), work_dir)
            return FileResponse(
                video,
                media_type="application/octet-stream",
                filename=video.name,
                background=background_tasks,
            )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            fallback_error = f"FxTwitter fallback failed: {exc}"

    base_command = [
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

    attempts = [base_command]
    if platform == "x/twitter":
        attempts = []
        apis = [
            api.strip()
            for api in X_TWITTER_API_TARGETS.split(",")
            if api.strip()
        ]
        targets = [
            target.strip()
            for target in X_TWITTER_IMPERSONATE_TARGETS.split(",")
            if target.strip()
        ]
        for api in apis:
            for target in targets:
                command = [*base_command, "--extractor-args", f"twitter:api={api}"]
                if X_TWITTER_FORCE_IPV4:
                    command.append("--force-ipv4")
                if target.lower() != "false":
                    command.extend(["--impersonate", target])
                attempts.append(command)

    completed = None
    errors = []
    try:
        for command in attempts:
            completed = subprocess.run(
                [*command, payload.url.strip()],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=MAX_DOWNLOAD_SECONDS,
                check=False,
            )
            if completed.returncode == 0:
                break
            stderr = completed.stderr.strip()
            if stderr:
                errors.append(stderr.splitlines()[-1])
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Download timed out.") from exc

    if completed is None:
        raise HTTPException(status_code=500, detail="Download failed.")

    if completed.returncode != 0:
        message = errors[-1:] or ["Download failed."]
        if fallback_error:
            message[0] = f"{fallback_error}; yt-dlp fallback failed: {message[0]}"
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
