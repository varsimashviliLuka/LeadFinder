"""Access from other devices (your phone).

Requests from this computer are always allowed. Anything else needs APP_PASSWORD
(and a real SECRET_KEY) in .env, and signing in once on that device.
"""

import hmac
import time
from collections import defaultdict, deque

from flask import current_app, jsonify, redirect, render_template, request, session, url_for

LOCAL_ADDRESSES = {"127.0.0.1", "::1"}
WEAK_SECRET_KEYS = {"", "dev-secret-key", "change-me"}
MAX_FAILURES = 8
FAILURE_WINDOW_S = 15 * 60
_failures = defaultdict(deque)


def is_local_request():
    return request.remote_addr in LOCAL_ADDRESSES


def remote_access_ready(config):
    return bool(config.get("APP_PASSWORD")) and config.get("SECRET_KEY", "") not in WEAK_SECRET_KEYS


def _blocked_response(status, message, template, **context):
    if request.path.startswith("/api/"):
        return jsonify({"message": message}), status
    return render_template(template, message=message, **context), status


def _disabled_response():
    return _blocked_response(
        403,
        "Opening the app from another device is turned off. Set APP_PASSWORD and SECRET_KEY in .env, then restart.",
        "access_disabled.html",
    )


def check_access():
    """before_request hook."""
    if is_local_request() or request.endpoint in ("web.login", "web.static", "static"):
        return None
    if not remote_access_ready(current_app.config):
        return _disabled_response()
    if session.get("signed_in"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"message": "Sign in first"}), 401
    return redirect(url_for("web.login", next=request.full_path if request.query_string else request.path))


def _too_many_failures(address):
    attempts = _failures[address]
    while attempts and attempts[0] < time.monotonic() - FAILURE_WINDOW_S:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


def login_view():
    if is_local_request() or session.get("signed_in"):
        return redirect(url_for("web.dashboard"))
    if not remote_access_ready(current_app.config):
        return _disabled_response()
    error = None
    if request.method == "POST":
        address = request.remote_addr
        if _too_many_failures(address):
            error = "Too many wrong passwords. Wait 15 minutes and try again."
        elif hmac.compare_digest(request.form.get("password", "").encode(), current_app.config["APP_PASSWORD"].encode()):
            _failures.pop(address, None)
            session.clear()
            session["signed_in"] = True
            session.permanent = True
            target = request.args.get("next") or ""
            return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("web.dashboard"))
        else:
            _failures[address].append(time.monotonic())
            error = "Wrong password"
    return render_template("login.html", error=error), 401 if error else 200


def logout_view():
    session.clear()
    return redirect(url_for("web.login"))
