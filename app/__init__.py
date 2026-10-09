"""FgChat application factory."""

import os
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import csrf, db, limiter, migrate, socketio

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    default_db = Path(app.instance_path) / "fgchat.sqlite3"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FGCHAT_SECRET_KEY", ""),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", f"sqlite:///{default_db}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FGCHAT_COOKIE_SECURE", "0") == "1",
        SOCKETIO_ASYNC_MODE=os.environ.get("FGCHAT_SOCKETIO_MODE", "threading"),
        SOCKETIO_MESSAGE_QUEUE=os.environ.get("FGCHAT_SOCKETIO_REDIS_URL", ""),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
        RATELIMIT_STORAGE_URI=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        PROXY_FIX_HOPS=int(os.environ.get("FGCHAT_PROXY_FIX_HOPS", "0")),
        TURN_URL=os.environ.get("FGCHAT_TURN_URL", ""),
        TURN_USERNAME=os.environ.get("FGCHAT_TURN_USERNAME", ""),
        TURN_CREDENTIAL=os.environ.get("FGCHAT_TURN_CREDENTIAL", ""),
        TURN_SHARED_SECRET=os.environ.get("FGCHAT_TURN_SHARED_SECRET", ""),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "fgchat-test-key"
        else:
            raise RuntimeError("Set FGCHAT_SECRET_KEY to a random secret before starting FgChat.")

    csrf.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(
        app,
        async_mode=app.config["SOCKETIO_ASYNC_MODE"],
        message_queue=app.config["SOCKETIO_MESSAGE_QUEUE"] or None,
        manage_session=False,
        logger=False,
        engineio_logger=False,
    )
    proxy_hops = app.config["PROXY_FIX_HOPS"]
    if proxy_hops > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_hops,
            x_proto=proxy_hops,
            x_host=proxy_hops,
            x_prefix=proxy_hops,
        )

    from app.auth import auth_bp
    from app.chat import chat_bp
    from app.chat.events import register_socket_events
    from app.models import User

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error="Please sign in to continue."), 401
        return redirect(url_for("auth.login"))

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    register_socket_events(socketio)

    @app.get("/health")
    def health():
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            app.logger.exception("Database health check failed")
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok", database="ok")

    @app.get("/")
    def index():
        from flask_login import current_user

        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return render_template("index.html")

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(self), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; connect-src 'self' ws: wss:; "
            "img-src 'self' data:; media-src 'self' blob:; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        return response

    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf

        return {"csrf_token": generate_csrf}

    return app
