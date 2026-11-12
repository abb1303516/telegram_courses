"""
Telegram Course Downloader — Web Interface
Simplified MVP: one course, clean UI for downloading lectures.
"""

import os
import json
import asyncio
import hmac
import logging
import secrets
import threading
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from downloader import downloader, TelegramDownloader

# -- Setup --

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

Config.validate_security()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=Config.SECRET_KEY,
    MAX_CONTENT_LENGTH=256 * 1024,
    SESSION_COOKIE_NAME="telegram_courses_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=Config.SESSION_COOKIE_SECURE,
    SESSION_COOKIE_PATH=Config.URL_PREFIX or "/",
    TRUSTED_HOSTS=Config.TRUSTED_HOSTS or None,
)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
    headers_enabled=True,
)

if Config.BEHIND_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


# -- Prefix middleware for reverse proxy (/tg/) --

class PrefixMiddleware:
    def __init__(self, wsgi_app, prefix=""):
        self.app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        environ["SCRIPT_NAME"] = self.prefix
        return self.app(environ, start_response)


if Config.URL_PREFIX:
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=Config.URL_PREFIX)


# -- Request security --

def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def validate_csrf():
    """Require a session-bound token for every state-changing request."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    expected = session.get("_csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get(
        "X-CSRF-Token", ""
    )
    if expected and supplied and hmac.compare_digest(expected, supplied):
        return None

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Недействительный защитный токен"}), 403
    return render_template("login.html", error="Сессия устарела. Обновите страницу."), 403


@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if response.mimetype in {"text/html", "application/json"}:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(429)
def rate_limit_exceeded(error):
    if request.endpoint == "login":
        return render_template(
            "login.html",
            error="Слишком много попыток. Подождите и попробуйте снова.",
        ), 429
    return error


# -- Async event loop in background thread --

loop = asyncio.new_event_loop()
threading.Thread(
    target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
    daemon=True,
).start()


def run_async(coro):
    """Run an async coroutine from sync Flask code."""
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=300)


# Keep references to fire-and-forget background tasks so they aren't GC'd
# (Python 3.10 is stricter about this than 3.11+)
_background_futures: set = set()


def run_background(coro):
    """Launch a coroutine in the background loop, keeping a reference to
    prevent garbage collection of the task."""
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    _background_futures.add(fut)
    fut.add_done_callback(_background_futures.discard)
    return fut


# -- Data persistence (JSON) --

def load_data() -> dict:
    if os.path.exists(Config.DATA_FILE):
        with open(Config.DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"courses": {}}


def save_data(data: dict):
    with open(Config.DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_course():
    """Get the first (and typically only) course."""
    data = load_data()
    courses = data.get("courses", {})
    if not courses:
        return None, None, data
    course_id = next(iter(courses))
    return course_id, courses[course_id], data


# -- Auth --

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "5 per minute; 20 per hour",
    methods=["POST"],
    deduct_when=lambda response: response.status_code == 401,
)
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if hmac.compare_digest(password, Config.APP_PASSWORD):
            session.clear()  # gs-lint: ok - Flask session, not a worksheet
            session["logged_in"] = True
            session["_csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("index"))
        error = "Неверный пароль"
        return render_template("login.html", error=error), 401
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()  # gs-lint: ok - Flask session, not a worksheet
    return redirect(url_for("login"))


# -- Pages --

@app.route("/")
@login_required
def index():
    """Main page: file list for the course, or redirect to admin."""
    course_id, course, data = get_course()
    if not course:
        return redirect(url_for("admin"))

    course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
    files = []
    pending_count = 0

    thumbs_dir = os.path.join(course_dir, ".thumbs")
    for f in course.get("files", []):
        # Format date for display (common to all entry types)
        date_str = f.get("date", "")
        date_fmt = ""
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                date_fmt = dt.strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                pass

        # Text-only message — no file on disk, not counted as pending
        if f.get("type") == "text":
            files.append({
                **f,
                "on_server": False,
                "has_thumb": False,
                "date_fmt": date_fmt,
            })
            continue

        filepath = os.path.join(course_dir, f["filename"])
        on_server = os.path.exists(filepath) and os.path.getsize(filepath) > 0
        if not on_server:
            pending_count += 1
        has_thumb = os.path.exists(os.path.join(thumbs_dir, f["filename"] + ".jpg"))
        files.append({
            **f,
            "on_server": on_server,
            "has_thumb": has_thumb,
            "date_fmt": date_fmt,
            "local_size": TelegramDownloader.format_size(
                os.path.getsize(filepath)
            ) if on_server else "",
            "size_fmt": TelegramDownloader.format_size(f.get("size", 0)),
        })

    progress = downloader.progress.get(course_id, {})

    return render_template(
        "main.html",
        course=course,
        course_id=course_id,
        files=files,
        pending_count=pending_count,
        progress=progress,
        tg_connected=downloader.connected,
    )


@app.route("/admin")
@login_required
def admin():
    course_id, course, data = get_course()
    return render_template(
        "admin.html",
        tg_connected=downloader.connected,
        course=course,
        course_id=course_id,
    )


# -- API: Telegram connection --

@app.route("/api/telegram/connect", methods=["POST"])
@login_required
def telegram_connect():
    try:
        result = run_async(downloader.connect())
        if result:
            return jsonify({"ok": True, "status": "connected"})
        phone_code_hash = run_async(downloader.send_code())
        session["phone_code_hash"] = phone_code_hash
        return jsonify({"ok": True, "status": "code_sent"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/telegram/verify", methods=["POST"])
@login_required
def telegram_verify():
    code = request.json.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "Введите код"}), 400
    try:
        run_async(downloader.sign_in(code, session.get("phone_code_hash", "")))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/telegram/status")
@login_required
def telegram_status():
    return jsonify({"connected": downloader.connected})


# -- API: Course --

@app.route("/api/course/add", methods=["POST"])
@login_required
def add_course():
    link = request.json.get("link", "").strip()
    title = request.json.get("title", "").strip()

    if not link:
        return jsonify({"ok": False, "error": "Введите ссылку"}), 400
    if not downloader.connected:
        return jsonify({"ok": False, "error": "Telegram не подключён"}), 400

    try:
        chat_info = run_async(downloader.resolve_chat(link))
        course_id = f"course_{chat_info['id']}"
        data = load_data()
        files = run_async(downloader.scan_chat(chat_info["id"]))

        data["courses"][course_id] = {
            "title": title or chat_info["title"],
            "chat_id": chat_info["id"],
            "chat_link": link,
            "total_files": len(files),
            "files": files,
            "added": datetime.now().isoformat(),
        }
        save_data(data)

        # Download thumbs in background
        course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
        run_background(
            downloader.download_thumbs(chat_info["id"], files, course_dir)
        )

        return jsonify({
            "ok": True,
            "course_id": course_id,
            "total_files": len(files),
        })
    except Exception as e:
        logger.exception("Error adding course")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/course/rescan", methods=["POST"])
@login_required
def rescan_course():
    course_id, course, data = get_course()
    if not course:
        return jsonify({"ok": False, "error": "Курс не найден"}), 404

    try:
        files = run_async(downloader.scan_chat(course["chat_id"]))
        course["files"] = files
        course["total_files"] = len(files)
        save_data(data)

        # Download thumbs in background
        course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
        run_background(
            downloader.download_thumbs(course["chat_id"], files, course_dir)
        )

        return jsonify({"ok": True, "total_files": len(files)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/course/download", methods=["POST"])
@login_required
def download_from_tg():
    """Download files not yet on server from Telegram, one after another.
    Optional JSON {filenames: [...]} limits the run to the selected files."""
    course_id, course, data = get_course()
    if not course:
        return jsonify({"ok": False, "error": "Курс не найден"}), 404
    if downloader.downloading:
        return jsonify({"ok": False, "error": "Загрузка уже идёт"}), 400

    course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
    selected = (request.get_json(silent=True) or {}).get("filenames")
    selected = set(selected) if selected is not None else None

    # Filter to only files not on server (skip text-only entries)
    pending = []
    for f in course["files"]:
        if not f.get("filename"):
            continue
        if selected is not None and f["filename"] not in selected:
            continue
        filepath = os.path.join(course_dir, f["filename"])
        if not (os.path.exists(filepath) and os.path.getsize(filepath) > 0):
            pending.append(f)

    if not pending:
        return jsonify({"ok": False, "error": "Нет новых файлов для скачивания"}), 400

    run_background(
        downloader.download_course(course_id, course["chat_id"], pending, course_dir)
    )
    return jsonify({"ok": True})


@app.route("/api/course/download/cancel", methods=["POST"])
@login_required
def cancel_download():
    """Request cancellation of the current download (bulk or single)."""
    if not downloader.downloading:
        return jsonify({"ok": False, "error": "Нет активной загрузки"}), 400
    downloader.request_cancel()
    return jsonify({"ok": True})


@app.route("/api/file/download-tg", methods=["POST"])
@login_required
def download_single_from_tg():
    """Download a single file from Telegram to server."""
    course_id, course, data = get_course()
    if not course_id:
        return jsonify({"ok": False, "error": "Курс не найден"}), 404
    if downloader.downloading:
        return jsonify({"ok": False, "error": "Загрузка уже идёт"}), 400

    filename = request.json.get("filename", "")
    file_info = None
    for f in course.get("files", []):
        if f.get("filename") == filename:
            file_info = f
            break

    if not file_info:
        return jsonify({"ok": False, "error": "Файл не найден в метаданных"}), 404

    course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
    run_background(
        downloader.download_single(
            course_id, course["chat_id"], file_info["msg_id"],
            filename, file_info.get("size", 0), course_dir
        )
    )
    return jsonify({"ok": True})


@app.route("/api/progress")
@login_required
def progress():
    course_id, course, data = get_course()
    if not course_id:
        return jsonify({"status": "idle"})
    prog = downloader.progress.get(course_id, {"status": "idle", "total": 0, "done": 0})
    return jsonify(prog)


# -- File serving --

@app.route("/download/<filename>")
@login_required
def download_file(filename):
    course_id, course, data = get_course()
    if not course_id:
        return "Курс не найден", 404
    safe_name = os.path.basename(filename)
    filepath = os.path.join(Config.DOWNLOAD_DIR, course_id, safe_name)
    if not os.path.exists(filepath):
        return "Файл не найден", 404
    return send_file(filepath, as_attachment=True, download_name=safe_name)


@app.route("/preview/<filename>")
@login_required
def preview_file(filename):
    """Serve image/video thumbnail for preview."""
    course_id, course, data = get_course()
    if not course_id:
        return "", 404
    safe_name = os.path.basename(filename)
    filepath = os.path.join(Config.DOWNLOAD_DIR, course_id, safe_name)

    # Check for Telegram-generated thumb (for videos and not-yet-downloaded photos)
    thumb_path = os.path.join(Config.DOWNLOAD_DIR, course_id, ".thumbs", safe_name + ".jpg")
    if os.path.exists(thumb_path):
        ext = os.path.splitext(safe_name)[1].lower()
        is_image = ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")
        # For videos always use thumb; for images use thumb only if original not on server
        if not is_image or not os.path.exists(filepath):
            return send_file(thumb_path, mimetype="image/jpeg")

    if not os.path.exists(filepath):
        return "", 404
    ext = os.path.splitext(safe_name)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }
    mime = mime_map.get(ext)
    if not mime:
        return "", 404
    return send_file(filepath, mimetype=mime)


@app.route("/stream/<filename>")
@login_required
def stream_file(filename):
    """Stream video/audio with Range request support."""
    course_id, course, data = get_course()
    if not course_id:
        return "Курс не найден", 404
    safe_name = os.path.basename(filename)
    filepath = os.path.join(Config.DOWNLOAD_DIR, course_id, safe_name)
    if not os.path.exists(filepath):
        return "Файл не найден", 404

    ext = os.path.splitext(safe_name)[1].lower()
    mime_map = {
        ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".m4a": "audio/mp4", ".wav": "audio/wav",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return send_file(filepath, mimetype=mime, conditional=True)


@app.route("/api/file/delete", methods=["POST"])
@login_required
def delete_file():
    course_id, course, data = get_course()
    if not course_id:
        return jsonify({"ok": False, "error": "Курс не найден"}), 404

    filename = request.json.get("filename", "")
    safe_name = os.path.basename(filename)
    filepath = os.path.join(Config.DOWNLOAD_DIR, course_id, safe_name)

    if os.path.exists(filepath):
        os.remove(filepath)
        logger.info(f"Deleted: {filepath}")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Файл не найден"}), 404


# -- Main --

if __name__ == "__main__":
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)

    try:
        run_async(downloader.connect())
        if downloader.connected:
            logger.info("Telegram auto-connected.")
    except Exception as e:
        logger.warning(f"Telegram auto-connect failed: {e}")

    app.run(host=Config.HOST, port=Config.PORT, debug=False)
