import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from db import connect, init_db

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/data/media"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/logs"))
KEEP_ORIGINAL = os.getenv("KEEP_ORIGINAL", "false").lower() in {"1", "true", "yes", "on"}
KEEP_DOCUMENT_ORIGINAL = os.getenv("KEEP_DOCUMENT_ORIGINAL", "true").lower() in {"1", "true", "yes", "on"}
FFMPEG_THREADS = max(1, int(os.getenv("FFMPEG_THREADS", "1")))
VIDEO_CRF = os.getenv("VIDEO_CRF", "24")
VIDEO_PRESET = os.getenv("VIDEO_PRESET", "veryfast")
DOCUMENT_RENDER_DPI = max(72, min(220, int(os.getenv("DOCUMENT_RENDER_DPI", "120"))))
DOCUMENT_JPEG_QUALITY = max(55, min(95, int(os.getenv("DOCUMENT_JPEG_QUALITY", "82"))))

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
    """Claim the oldest queued item across the legacy videos table and the new documents table."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        video = conn.execute(
            "SELECT * FROM videos WHERE status='queued' ORDER BY created_at ASC, id ASC LIMIT 1"
        ).fetchone()
        document = conn.execute(
            "SELECT * FROM documents WHERE status='queued' ORDER BY created_at ASC, id ASC LIMIT 1"
        ).fetchone()

        candidates = []
        if video:
            candidates.append((video["created_at"], 0, video["id"], "video", video))
        if document:
            candidates.append((document["created_at"], 1, document["id"], "document", document))
        if not candidates:
            conn.commit()
            return None

        _, _, _, kind, row = min(candidates, key=lambda item: item[:3])
        table = "videos" if kind == "video" else "documents"
        updated = conn.execute(
            f"UPDATE {table} SET status='processing', error=NULL, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='queued'",
            (row["id"],),
        ).rowcount
        conn.commit()
        if not updated:
            return None
        job = dict(row)
        job["_kind"] = kind
        return job


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


def transcode_video(job):
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


def run_logged(cmd, log_path, timeout):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fp:
        fp.write("COMMAND: " + " ".join(str(x) for x in cmd) + "\n\n")
        fp.flush()
        subprocess.run(cmd, check=True, timeout=timeout, stdout=fp, stderr=subprocess.STDOUT)


def convert_office_to_pdf(job, src, output_pdf, work_dir):
    slug = job["slug"]
    root = LOG_DIR / slug
    profile = work_dir / "libreoffice-profile"
    profile_uri = profile.resolve().as_uri()
    cmd = [
        "libreoffice",
        "-env:UserInstallation=" + profile_uri,
        "--headless", "--nologo", "--nodefault", "--nofirststartwizard", "--nolockcheck",
        "--convert-to", "pdf",
        "--outdir", str(work_dir),
        str(src),
    ]
    log_event(slug, f"LibreOffice 开始转换 {job['document_type']} → PDF")
    run_logged(cmd, root / "convert.log", 30 * 60)

    generated = work_dir / f"{src.stem}.pdf"
    if not generated.exists():
        pdfs = sorted(work_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not pdfs:
            raise RuntimeError("LibreOffice 未生成 PDF 文件，请查看 convert.log")
        generated = pdfs[0]
    shutil.move(str(generated), str(output_pdf))
    shutil.rmtree(profile, ignore_errors=True)
    log_event(slug, "Office 文档已转换为 PDF")


def render_pdf_pages(job, output_pdf, pages_dir):
    slug = job["slug"]
    root = LOG_DIR / slug
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    prefix = pages_dir / "page"
    cmd = [
        "pdftoppm",
        "-jpeg",
        "-r", str(DOCUMENT_RENDER_DPI),
        "-jpegopt", f"quality={DOCUMENT_JPEG_QUALITY},progressive=y,optimize=y",
        str(output_pdf),
        str(prefix),
    ]
    log_event(slug, f"开始生成手机阅读页（{DOCUMENT_RENDER_DPI} DPI）")
    run_logged(cmd, root / "render.log", 60 * 60)
    pages = sorted(pages_dir.glob("page-*.jpg"), key=lambda p: int(p.stem.split("-")[-1]))
    if not pages:
        raise RuntimeError("PDF 页面渲染失败，未生成任何页面图片，请查看 render.log")
    log_event(slug, f"手机阅读页生成完成，共 {len(pages)} 页")
    return len(pages)


def convert_document(job):
    slug = job["slug"]
    src = Path(job["input_path"])
    if not src.exists():
        raise FileNotFoundError(f"待处理文件不存在：{src}")

    out_dir = MEDIA_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / ".work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    output_pdf = out_dir / "document.pdf"
    pages_dir = out_dir / "pages"
    original_ext = (job.get("original_ext") or src.suffix or "").lower()
    original_media = out_dir / f"original{original_ext}"

    try:
        if job["document_type"] == "pdf":
            log_event(slug, "检测为 PDF，无需 Office 转换")
            shutil.copy2(src, output_pdf)
        else:
            convert_office_to_pdf(job, src, output_pdf, work_dir)

        page_count = render_pdf_pages(job, output_pdf, pages_dir)

        # 文档默认保留原件；即使全局关闭，只要此资源允许下载也必须保留。
        keep_source = KEEP_DOCUMENT_ORIGINAL or bool(job.get("allow_download"))
        original_rel = None
        if keep_source:
            shutil.copy2(src, original_media)
            original_rel = f"/media/{slug}/{original_media.name}"
            log_event(slug, f"已保留原始文件：{original_media.name}")
        else:
            log_event(slug, "KEEP_DOCUMENT_ORIGINAL=false，未保留原始 Office/PDF 文件")

        try:
            src.unlink(missing_ok=True)
        except Exception as exc:
            log_event(slug, f"清理 uploads 原文件失败：{exc}")

        with connect() as conn:
            conn.execute(
                "UPDATE documents SET status='ready', output_path=?, original_path=?, page_count=?, "
                "error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (f"/media/{slug}/document.pdf", original_rel, page_count, job["id"]),
            )
            conn.commit()
        log_event(slug, "文档任务完成：ready")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def fail(job, exc):
    msg = str(exc)[-3000:]
    log_event(job["slug"], f"任务失败：{msg}")
    table = "videos" if job.get("_kind") == "video" else "documents"
    with connect() as conn:
        conn.execute(
            f"UPDATE {table} SET status='error', error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (msg, job["id"]),
        )
        conn.commit()


if __name__ == "__main__":
    print("resource worker started; concurrency=1; video+document", flush=True)
    while True:
        job = claim_job()
        if not job:
            time.sleep(2)
            continue
        kind = job.get("_kind", "video")
        print(f"processing {kind} {job['slug']} / {job['original_name']}", flush=True)
        log_event(job["slug"], f"Worker 领取{('视频' if kind == 'video' else '文档')}任务，状态 processing")
        try:
            if kind == "video":
                transcode_video(job)
            else:
                convert_document(job)
            print(f"ready {kind} {job['slug']}", flush=True)
        except Exception as exc:
            print(f"failed {kind} {job['slug']}: {exc}", flush=True)
            fail(job, exc)
