from flask import jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _payload(code, message):
    return {"success": False, "code": code, "message": message}


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(_payload(err.code, err.message)), err.status

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        code = (err.name or "ERROR").upper()
        return jsonify(_payload(code, err.description)), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        app.logger.exception("Unhandled error")
        return jsonify(_payload("SERVER ERROR", "Something went wrong.")), 500
