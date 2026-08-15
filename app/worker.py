import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from db import connect, init_db

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/data/media"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/logs"))
KEEP_ORIGINAL = os.getenv("KEEP_ORIGINAL", "false").lower() in {"1", "true", "yes", "on"}
FFMPEG_THREADS = max(1, int(os.getenv("FFMPEG_THREADS", "1")))
VIDEO_CRF = os.getenv("VIDEO_CRF", "24")
VIDEO_PRESET = os.getenv("VIDEO_PRESET", "veryfast")

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
# 只有 worker 启动时才恢复因 worker/整机重启而中断的 processing 任务。
init_db(requeue_processing=True)


def log_event(slug, message):
    root = LOG_DIR / slug
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    with (root / "events.log").open("a", encoding="utf-8") as fp:
        fp.write(f"[{stamp}] {message}\n")


def claim_job():
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM videos WHERE status='queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            conn.commit()
            return None
        updated = conn.execute(
            "UPDATE videos SET status='processing', error=NULL, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='queued'",
            (row["id"],),
        ).rowcount
        conn.commit()
        return dict(row) if updated else None


def video_filter(mode):
    if mode == "landscape":
        return (
            "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
        )
    if mode == "portrait":
        return (
            "scale='min(720,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black"
        )
    return (
        "scale="
        "w='if(gte(iw,ih),-2,trunc(min(720,iw)/2)*2)':"
        "h='if(gte(iw,ih),trunc(min(720,ih)/2)*2,-2)'"
    )


def run_ffmpeg(job, output):
    slug = job["slug"]
    src = Path(job["input_path"])
    orientation = job.get("orientation") or "auto"
    if orientation not in {"auto", "landscape", "portrait"}:
        orientation = "auto"

    root = LOG_DIR / slug
    root.mkdir(parents=True, exist_ok=True)
    ffmpeg_log = root / "ffmpeg.log"
    progress_log = root / "progress.log"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "info", "-nostats", "-stats_period", "5",
        "-i", str(src),
        "-vf", video_filter(orientation),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", VIDEO_CRF,
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart", "-threads", str(FFMPEG_THREADS),
        "-progress", "pipe:1",
        str(output),
    ]

    log_event(slug, "FFmpeg 开始转码")
    log_event(slug, "命令：" + " ".join(cmd))
    with ffmpeg_log.open("w", encoding="utf-8") as err_fp, progress_log.open("w", encoding="utf-8") as out_fp:
        subprocess.run(cmd, check=True, timeout=24 * 3600, stdout=out_fp, stderr=err_fp)
    log_event(slug, "FFmpeg 主视频转码完成")


def transcode(job):
    slug = job["slug"]
    src = Path(job["input_path"])
    out_dir = MEDIA_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "video.mp4"
    poster = out_dir / "poster.jpg"

    run_ffmpeg(job, output)

    root = LOG_DIR / slug
    poster_log = root / "poster.log"
    poster_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-ss", "1", "-i", str(output), "-frames:v", "1", "-q:v", "3", str(poster),
    ]
    try:
        with poster_log.open("w", encoding="utf-8") as fp:
            subprocess.run(poster_cmd, check=True, timeout=120, stdout=fp, stderr=subprocess.STDOUT)
        poster_rel = f"/media/{slug}/poster.jpg"
        log_event(slug, "封面生成完成")
    except Exception as exc:
        poster_rel = None
        log_event(slug, f"封面生成失败（不影响视频播放）：{exc}")

    if not KEEP_ORIGINAL:
        try:
            src.unlink(missing_ok=True)
            log_event(slug, "已按 KEEP_ORIGINAL=false 删除原始上传文件")
        except Exception as exc:
            log_event(slug, f"删除原文件失败：{exc}")

    with connect() as conn:
        conn.execute(
            "UPDATE videos SET status='ready', output_path=?, poster_path=?, error=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (f"/media/{slug}/video.mp4", poster_rel, job["id"]),
        )
        conn.commit()
    log_event(slug, "任务完成：ready")


def fail(job, exc):
    msg = str(exc)[-3000:]
    log_event(job["slug"], f"任务失败：{msg}")
    with connect() as conn:
        conn.execute(
            "UPDATE videos SET status='error', error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (msg, job["id"]),
        )
        conn.commit()


if __name__ == "__main__":
    print("video worker started; concurrency=1", flush=True)
    while True:
        job = claim_job()
        if not job:
            time.sleep(2)
            continue
        print(
            f"processing {job['slug']} / {job['original_name']} / orientation={job.get('orientation', 'auto')}",
            flush=True,
        )
        log_event(job["slug"], "Worker 领取任务，状态 processing")
        try:
            transcode(job)
            print(f"ready {job['slug']}", flush=True)
        except Exception as exc:
            print(f"failed {job['slug']}: {exc}", flush=True)
            fail(job, exc)
