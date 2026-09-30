import io
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file
import qrcode
import qrcode.image.svg
from werkzeug.exceptions import HTTPException

from .domain import RuleError, mutate, new_tournament, validate_snapshot, view
from .storage import Conflict, Store
from .network import sharing_url


def create_app(data_dir=None):
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    store = Store(data_dir or os.environ.get("TOURNAMENT_DATA_DIR", root / "data"))
    app.extensions["store"] = store

    def current():
        state, revision = store.read()
        return view(state, revision)

    @app.before_request
    def guard_writes():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not request.is_json or request.headers.get("X-Tournament-Request") != "1":
                return jsonify(error="Use the tournament app to submit changes."), 403
            origin = request.headers.get("Origin")
            if request.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and urlsplit(origin).netloc != request.host):
                return jsonify(error="Changes must come from this tournament website."), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(RuleError)
    def rule_error(error):
        status = 409 if isinstance(error, Conflict) or error.affected else 400
        return jsonify(error=str(error), affected=error.affected, **({"latest": current()} if isinstance(error, Conflict) else {})), status

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def state():
        return jsonify(current())

    @app.get("/api/history")
    def history():
        return jsonify(entries=store.history())

    @app.get("/api/export")
    def export():
        state, _ = store.read()
        if state is None:
            raise RuleError("There is no tournament to export.")
        return send_file(io.BytesIO(json.dumps(state, ensure_ascii=False, indent=2).encode()),
                         mimetype="application/json", as_attachment=True, download_name="tournament-backup.json")

    @app.get("/api/share")
    def share():
        return jsonify(url=sharing_url(request.host_url))

    @app.get("/api/qr.svg")
    def qr():
        target = sharing_url(request.host_url)
        output = io.BytesIO()
        qrcode.make(target, image_factory=qrcode.image.svg.SvgPathImage).save(output)
        return send_file(io.BytesIO(output.getvalue()), mimetype="image/svg+xml")

    @app.post("/api/change")
    def change():
        data = request.get_json()
        if not isinstance(data, dict) or not isinstance(data.get("action"), dict):
            raise RuleError("Invalid change request.")
        action = data["action"]
        kind = action.get("type")

        def apply(old):
            if kind == "create":
                if old is not None:
                    raise RuleError("A tournament already exists. Export and reset it before creating another.")
                return new_tournament(action.get("tournament"))
            if kind == "restore":
                if action.get("confirmation") != "REPLACE":
                    raise RuleError("Confirm replacement before restoring a backup.")
                return validate_snapshot(action.get("snapshot"))
            if kind == "reset":
                if action.get("confirmation") != "RESET":
                    raise RuleError("Confirm reset before clearing the tournament.")
                return None
            if old is None:
                raise RuleError("Create a tournament first.")
            mutate(old, action)
            return old

        store.change(data.get("revision"), data.get("operation_id"), action, apply,
                     backup=kind in ("restore", "reset"))
        return jsonify(current())

    return app
