"""
Telegram Course Downloader — Web Interface
Simplified MVP: one course, clean UI for downloading lectures.
"""

import os
import json
import asyncio
import logging
import threading
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file,
)

from config import Config
from downloader import downloader, TelegramDownloader

# -- Setup --

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY


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


# -- Async event loop in background thread --

loop = asyncio.new_event_loop()
threading.Thread(
    target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
    daemon=True,
).start()


def run_async(coro):
    """Run an async coroutine from sync Flask code."""
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=300)


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
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == Config.APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
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

    for f in course.get("files", []):
        filepath = os.path.join(course_dir, f["filename"])
        on_server = os.path.exists(filepath) and os.path.getsize(filepath) > 0
        if not on_server:
            pending_count += 1
        files.append({
            **f,
            "on_server": on_server,
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
        return jsonify({"ok": True, "total_files": len(files)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/course/download", methods=["POST"])
@login_required
def download_from_tg():
    course_id, course, data = get_course()
    if not course:
        return jsonify({"ok": False, "error": "Курс не найден"}), 404
    if downloader.downloading:
        return jsonify({"ok": False, "error": "Загрузка уже идёт"}), 400

    course_dir = os.path.join(Config.DOWNLOAD_DIR, course_id)
    asyncio.run_coroutine_threadsafe(
        downloader.download_course(course_id, course["chat_id"], course["files"], course_dir),
        loop,
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
