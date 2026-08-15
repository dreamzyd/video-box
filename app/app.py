import hashlib
import io
import os
import secrets
import sqlite3
import textwrap
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import qrcode
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from db import connect, init_db

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/data/media"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/logs"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
APP_VERSION = os.getenv("APP_VERSION", "1.0").strip() or "1.0"
APP_PASSWORD = (os.getenv("APP_PASSWORD", "").strip() or os.getenv("ADMIN_PASSWORD", "").strip())
APP_SESSION_HOURS = max(1, int(os.getenv("APP_SESSION_HOURS", os.getenv("ADMIN_SESSION_HOURS", "12"))))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_UPLOAD_GB = float(os.getenv("MAX_UPLOAD_GB", "5"))
ORIENTATION_MODES = {"auto", "landscape", "portrait"}

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mts", ".m2ts", ".3gp"
}

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "change-me-now")
app.config["MAX_CONTENT_LENGTH"] = int(MAX_UPLOAD_GB * 1024 * 1024 * 1024)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=APP_SESSION_HOURS)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = COOKIE_SECURE
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


@app.after_request
def security_headers(response):
    if request.path == "/" or request.path.startswith(("/login", "/admin", "/upload", "/manage", "/api/logs", "/qr/")):
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
# Web 进程不负责重排 processing，避免仅重启 Web 时制造重复转码。
init_db(requeue_processing=False)


def row_to_dict(row):
    return dict(row) if row else None


def playback_url(slug):
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/v/{slug}"
    return url_for("watch", slug=slug, _external=True)


def session_authenticated():
    # 兼容开发阶段旧版本已经签发的 admin_authenticated Session。
    return bool(session.get("authenticated") or session.get("admin_authenticated"))


def safe_next(value, fallback="/admin"):
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


def normalized_upload_name(filename):
    """Keep a valid extension even when the visible filename is non-ASCII."""
    raw_name = (filename or "").strip()
    ext = Path(raw_name).suffix.lower()
    stem = secure_filename(Path(raw_name).stem) or "video"
    return f"{stem}{ext}", ext


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session_authenticated():
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf():
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        abort(400, description="CSRF token invalid")


@app.context_processor
def inject_login_context():
    logged_in = session_authenticated()
    return {
        "logged_in": logged_in,
        "admin_logged_in": logged_in,  # 兼容旧模板变量
        "csrf_token": csrf_token if logged_in else (lambda: ""),
        "app_version": APP_VERSION,
    }


def video_log_dir(slug):
    path = LOG_DIR / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_event(slug, message):
    path = video_log_dir(slug) / "events.log"
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    with path.open("a", encoding="utf-8") as fp:
        fp.write(f"[{stamp}] {message}\n")


def save_and_hash(file_storage, destination):
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as fp:
        while True:
            chunk = file_storage.stream.read(1024 * 1024)
            if not chunk:
                break
            fp.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tail_text(path, max_bytes=65536):
    try:
        size = path.stat().st_size
        with path.open("rb") as fp:
            fp.seek(max(0, size - max_bytes))
            data = fp.read()
        return data.decode("utf-8", errors="replace")[-max_bytes:]
    except FileNotFoundError:
        return ""


def parse_progress(text):
    result = {}
    # -progress 会持续输出 key=value；取每个字段最后一次出现的值即可。
    for line in text.replace("\r", "\n").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return {
        "out_time": result.get("out_time", ""),
        "speed": result.get("speed", ""),
        "progress": result.get("progress", ""),
        "frame": result.get("frame", ""),
        "fps": result.get("fps", ""),
    }


def display_width(text):
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F", "A"} else 1
    return width


def wrap_caption(text, limit=28, max_lines=4):
    text = " ".join((text or "").strip().split())
    if not text:
        return []
    lines, current, width = [], "", 0
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in {"W", "F", "A"} else 1
        if current and width + cw > limit:
            lines.append(current)
            current, width = ch, cw
            if len(lines) >= max_lines:
                break
        else:
            current += ch
            width += cw
    if len(lines) < max_lines and current:
        lines.append(current)
    consumed = "".join(lines)
    if len(consumed) < len(text) and lines:
        lines[-1] = lines[-1].rstrip("…") + "…"
    return lines[:max_lines]


def build_qr_svg(url, caption):
    # 二维码本体尽量撑满卡片；保留 3 个 module 的安静区，兼顾紧凑与扫码可靠性。
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)

    canvas = 360
    qr_size = 336
    cell = qr_size / n
    x0 = (canvas - qr_size) / 2
    y0 = 10
    lines = wrap_caption(caption, limit=26, max_lines=4)

    # 文字紧贴二维码；无文字时卡片也不会额外留大块空白。
    caption_gap = 2
    line_height = 32
    font_size = 26
    base_y = y0 + qr_size + caption_gap + font_size
    bottom_pad = 8
    height = int((base_y + (len(lines) - 1) * line_height + bottom_pad) if lines else (y0 + qr_size + 10))

    rects = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                rects.append(
                    f'<rect x="{x0 + x * cell:.3f}" y="{y0 + y * cell:.3f}" '
                    f'width="{cell + 0.12:.3f}" height="{cell + 0.12:.3f}" fill="#000"/>'
                )

    text_nodes = []
    for i, line in enumerate(lines):
        text_nodes.append(
            f'<text x="180" y="{base_y + i * line_height:.1f}" text-anchor="middle" '
            f'font-size="{font_size}" fill="#111">{escape(line)}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{canvas}" height="{height}" viewBox="0 0 {canvas} {height}">
<rect width="100%" height="100%" rx="10" fill="#fff"/>
<g shape-rendering="crispEdges">{''.join(rects)}</g>
<style>text{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-weight:700}}</style>
{''.join(text_nodes)}
</svg>'''


@app.get("/")
@login_required
def index():
    return render_template(
        "upload.html",
        upload_request_id=secrets.token_urlsafe(18),
    )


@app.route("/login", methods=["GET", "POST"])
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    target = safe_next(request.values.get("next"), "/admin")
    if session_authenticated():
        return redirect(target)

    error = ""
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if not APP_PASSWORD:
            error = "服务器尚未设置 APP_PASSWORD，请先修改 .env 后重启服务。"
        elif secrets.compare_digest(supplied, APP_PASSWORD):
            session.clear()
            session["authenticated"] = True
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(target)
        else:
            error = "登录口令不正确。"
    return render_template("login.html", error=error, app_session_hours=APP_SESSION_HOURS, next_url=target)


@app.post("/logout")
@app.post("/admin/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin")
@login_required
def admin_dashboard():
    with connect() as conn:
        rows = conn.execute(
            "SELECT slug,title,description,original_name,orientation,status,error,created_at,views,access_enabled "
            "FROM videos ORDER BY id DESC"
        ).fetchall()
    videos = [row_to_dict(x) for x in rows]
    for video in videos:
        video["share_url"] = playback_url(video["slug"])
    summary = {
        "total": len(videos),
        "ready": sum(1 for v in videos if v["status"] == "ready"),
        "processing": sum(1 for v in videos if v["status"] in {"uploading", "queued", "processing"}),
        "paused": sum(1 for v in videos if not v["access_enabled"]),
    }
    return render_template(
        "index.html",
        videos=videos,
        summary=summary,
        public_base_url=PUBLIC_BASE_URL,
    )


@app.post("/upload")
@login_required
def upload():
    require_csrf()
    f = request.files.get("video")
    if not f or not f.filename:
        flash("请选择视频文件。", "error")
        return redirect(url_for("index"))

    original_name, ext = normalized_upload_name(f.filename)
    if ext not in ALLOWED_EXTENSIONS:
        flash(f"暂不接受该扩展名：{ext or '(无扩展名)'}", "error")
        return redirect(url_for("index")), 400

    request_id = (request.form.get("request_id") or "").strip()[:100]
    if not request_id:
        request_id = secrets.token_urlsafe(18)

    title = (request.form.get("title") or Path(original_name).stem).strip()[:200] or "未命名视频"
    description = (request.form.get("description") or "").strip()[:1000]
    orientation = (request.form.get("orientation") or "auto").strip().lower()
    if orientation not in ORIENTATION_MODES:
        orientation = "auto"

    slug = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
    stored_name = f"{slug}{ext}"
    input_path = UPLOAD_DIR / stored_name

    # 先用 request_id 占位。双击按钮/浏览器重复提交同一表单时，第二个请求不会再创建新任务。
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO videos(slug,request_id,title,description,original_name,input_path,orientation,status) "
                "VALUES(?,?,?,?,?,?,?,'uploading')",
                (slug, request_id, title, description, original_name, str(input_path), orientation),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        with connect() as conn:
            old = conn.execute("SELECT slug FROM videos WHERE request_id=?", (request_id,)).fetchone()
        if old:
            flash("检测到重复提交，已自动使用第一次上传的任务。", "ok")
            return redirect(url_for("admin_dashboard"))
        raise

    log_event(slug, f"开始接收上传：{original_name}，方向={orientation}")
    try:
        sha256, size = save_and_hash(f, input_path)
        log_event(slug, f"上传完成：{size} bytes，sha256={sha256}")

        # 内容级防重复：同一个文件 + 同一个输出方向重复上传，只保留最早一条有效任务。
        duplicate = None
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT id,slug,status FROM videos WHERE id<>(SELECT id FROM videos WHERE slug=?) "
                "AND content_sha256=? AND orientation=? AND status IN ('uploading','queued','processing','ready') "
                "ORDER BY id ASC LIMIT 1",
                (slug, sha256, orientation),
            ).fetchone()
            if duplicate:
                conn.execute("DELETE FROM videos WHERE slug=?", (slug,))
            else:
                conn.execute(
                    "UPDATE videos SET content_sha256=?, status='queued', updated_at=CURRENT_TIMESTAMP WHERE slug=?",
                    (sha256, slug),
                )
            conn.commit()

        if duplicate:
            input_path.unlink(missing_ok=True)
            log_event(slug, f"检测到相同内容，取消重复任务，复用 {duplicate['slug']}")
            flash("检测到相同视频已经上传过，已自动打开已有任务，不会重复转码。", "ok")
            return redirect(url_for("admin_dashboard"))

        log_event(slug, "任务进入转码队列")
        return redirect(url_for("admin_dashboard"))
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        with connect() as conn:
            conn.execute(
                "UPDATE videos SET status='error', error=?, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
                (str(exc)[-3000:], slug),
            )
            conn.commit()
        log_event(slug, f"上传失败：{exc}")
        raise


@app.get("/v/<slug>")
def watch(slug):
    with connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE slug=?", (slug,)).fetchone()
        if not row:
            abort(404)
        if not row["access_enabled"]:
            return render_template("watch_disabled.html"), 403
        if row["status"] == "ready":
            conn.execute("UPDATE videos SET views=views+1 WHERE slug=?", (slug,))
            conn.commit()
            row = conn.execute("SELECT * FROM videos WHERE slug=?", (slug,)).fetchone()
    return render_template("watch.html", video=row_to_dict(row))


@app.get("/stream/<slug>")
def stream_video(slug):
    # 应用只做权限判断；真正的大文件仍由 Nginx 通过 X-Accel-Redirect 高效发送。
    with connect() as conn:
        row = conn.execute(
            "SELECT status,access_enabled,output_path FROM videos WHERE slug=?", (slug,)
        ).fetchone()
    if not row:
        abort(404)
    if not row["access_enabled"]:
        abort(403)
    if row["status"] != "ready" or not row["output_path"]:
        abort(404)
    response = Response(status=200, mimetype="video/mp4")
    response.headers["X-Accel-Redirect"] = f"/_protected_media/{slug}/video.mp4"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/poster/<slug>")
def poster(slug):
    with connect() as conn:
        row = conn.execute(
            "SELECT access_enabled,poster_path FROM videos WHERE slug=?", (slug,)
        ).fetchone()
    if not row:
        abort(404)
    if not row["access_enabled"] or not row["poster_path"]:
        abort(404)
    response = Response(status=200, mimetype="image/jpeg")
    response.headers["X-Accel-Redirect"] = f"/_protected_media/{slug}/poster.jpg"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@app.get("/manage/<slug>")
@login_required
def manage(slug):
    with connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE slug=?", (slug,)).fetchone()
    if not row:
        abort(404)
    video = row_to_dict(row)
    video["share_url"] = playback_url(slug)
    return render_template("manage.html", video=video)


@app.post("/manage/<slug>/access")
@login_required
def update_access(slug):
    require_csrf()
    action = (request.form.get("action") or "").strip().lower()
    if action not in {"enable", "disable"}:
        abort(400)
    enabled = 1 if action == "enable" else 0
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM videos WHERE slug=?", (slug,)).fetchone()
        if not row:
            abort(404)
        conn.execute(
            "UPDATE videos SET access_enabled=?, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
            (enabled, slug),
        )
        conn.commit()
    log_event(slug, "恢复了外部访问" if enabled else "暂停了外部访问")
    flash("已恢复访问；原播放链接和原二维码立即重新有效。" if enabled else "已暂停访问；播放页和视频直链都会被阻止。", "ok")
    if (request.form.get("return_to") or "").strip() == "dashboard":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("manage", slug=slug))


@app.post("/manage/<slug>")
@login_required
def update_manage(slug):
    require_csrf()
    title = (request.form.get("title") or "").strip()[:200] or "未命名视频"
    description = (request.form.get("description") or "").strip()[:1000]
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM videos WHERE slug=?", (slug,)).fetchone()
        if not row:
            abort(404)
        conn.execute(
            "UPDATE videos SET title=?, description=?, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
            (title, description, slug),
        )
        conn.commit()
    log_event(slug, "更新了标题/简介")
    flash("已保存。", "ok")
    return redirect(url_for("manage", slug=slug))


@app.get("/api/status/<slug>")
def status(slug):
    with connect() as conn:
        row = conn.execute("SELECT status,access_enabled FROM videos WHERE slug=?", (slug,)).fetchone()
    if not row:
        abort(404)
    progress_text = tail_text(video_log_dir(slug) / "progress.log", 32768)
    return {
        "status": row["status"],
        "access_enabled": bool(row["access_enabled"]),
        "progress": parse_progress(progress_text),
    }


@app.get("/api/logs/<slug>")
@login_required
def video_logs(slug):
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM videos WHERE slug=?", (slug,)).fetchone()
    if not exists:
        abort(404)
    root = video_log_dir(slug)
    progress = tail_text(root / "progress.log", 32768)
    return jsonify(
        events=tail_text(root / "events.log", 65536),
        ffmpeg=tail_text(root / "ffmpeg.log", 131072),
        progress=parse_progress(progress),
    )


@app.get("/qr/<slug>.svg")
@login_required
def qr_svg(slug):
    with connect() as conn:
        row = conn.execute("SELECT title,description FROM videos WHERE slug=?", (slug,)).fetchone()
    if not row:
        abort(404)
    caption = request.args.get("caption")
    if caption is None:
        caption = row["description"] or row["title"]
    caption = caption.strip()[:160]
    svg = build_qr_svg(playback_url(slug), caption)
    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = f'inline; filename="{slug}-qr.svg"'
    return response


@app.get("/qr/external.svg")
@login_required
def qr_external_svg():
    target = (request.args.get("url") or "").strip()[:2048]
    caption = (request.args.get("caption") or "").strip()[:160]
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        abort(400, description="URL 必须是完整的 http:// 或 https:// 地址")
    svg = build_qr_svg(target, caption)
    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'inline; filename="external-qr.svg"'
    return response


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.errorhandler(413)
def too_large(_):
    return f"文件超过当前 {MAX_UPLOAD_GB:g} GB 上传限制。", 413
