from flask import request


def init_cors(app):
    allowed = set(app.config["CORS_ORIGINS"])

    @app.before_request
    def preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            resp = app.make_response(("", 204))
            return _decorate(resp)

    @app.after_request
    def add_cors(resp):
        return _decorate(resp)

    def _decorate(resp):
        origin = request.headers.get("Origin")
        if origin and origin in allowed and request.path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            resp.headers["Access-Control-Max-Age"] = "600"
        return resp
