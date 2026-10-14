from .auth import bp as auth_bp
from .health import bp as health_bp
from .notes import bp as notes_bp


def register_routes(app):
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(notes_bp, url_prefix="/api/notes")
