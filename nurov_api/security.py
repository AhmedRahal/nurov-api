import datetime as dt
from functools import wraps

import jwt
from flask import current_app, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .errors import ApiError


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    return check_password_hash(stored_hash, password)


_DUMMY_HASH = generate_password_hash("not-a-real-password")


def burn_password_check(password):
    check_password_hash(_DUMMY_HASH, password)


def create_token(user_id, token_version):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "iat": now,
        "exp": now + dt.timedelta(hours=current_app.config["TOKEN_TTL_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _decode(token):
    try:
        return jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "tv"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError("TOKEN EXPIRED", "Your session has expired.", 401)
    except jwt.PyJWTError:
        raise ApiError("INVALID TOKEN", "Invalid session.", 401)


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise ApiError("INVALID TOKEN", "Missing credentials.", 401)

        claims = _decode(token.strip())
        try:
            user_id = int(claims["sub"])
        except (TypeError, ValueError):
            raise ApiError("INVALID TOKEN", "Invalid session.", 401)

        user = get_db().execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        if user is None or user["token_version"] != claims["tv"]:
            raise ApiError("INVALID TOKEN", "Invalid session.", 401)

        g.user = user
        return fn(*args, **kwargs)

    return wrapper
