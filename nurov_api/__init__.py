from flask import Flask

from .config import Config
from .cors import init_cors
from .db import init_db
from .errors import register_error_handlers
from .routes import register_routes


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    if len(app.config["SECRET_KEY"] or "") < 32:
        raise RuntimeError(
            "SECRET_KEY is missing or too short (need 32+ chars). "
            "Generate one: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )

    init_db(app)
    init_cors(app)
    register_error_handlers(app)
    register_routes(app)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if not resp.headers.get("Cache-Control"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
