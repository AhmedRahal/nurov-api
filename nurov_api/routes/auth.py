import re

import psycopg
from flask import Blueprint, Response, current_app, g, jsonify, request

from .. import rate_limit
from ..db import get_db
from ..errors import ApiError
from ..images import delete_avatar, load_avatar, process_and_save_avatar
from ..security import (
    auth_required,
    burn_password_check,
    create_token,
    hash_password,
    verify_password,
)
from ..serializers import user_info
from ..validators import as_str, json_body, now_iso, valid_password, valid_username

bp = Blueprint("auth", __name__)

_IMAGE_NAME_RE = re.compile(r"^[a-f0-9]{32}\.png$")


def _username_taken(db, username_lc, *, except_id=None):
    row = db.execute("SELECT id FROM users WHERE username_lc = %s", (username_lc,)).fetchone()
    return bool(row) and row["id"] != except_id


@bp.post("/register")
def register():
    username = valid_username(request.form.get("username"))
    password = valid_password(request.form.get("password"))
    db = get_db()

    if _username_taken(db, username.lower()):
        raise ApiError("USERNAME TAKEN", "Username is already taken.", 409)

    avatar_name = None
    image = request.files.get("image")
    if image and image.filename:
        avatar_name = process_and_save_avatar(image)

    try:
        row = db.execute(
            "INSERT INTO users (username, username_lc, password_hash, image, created_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (username, username.lower(), hash_password(password), avatar_name, now_iso()),
        ).fetchone()
        db.commit()
    except psycopg.errors.UniqueViolation:
        db.rollback()
        raise ApiError("USERNAME TAKEN", "Username is already taken.", 409)

    user = db.execute("SELECT * FROM users WHERE id = %s", (row["id"],)).fetchone()
    return jsonify({
        "success": True,
        "token": create_token(user["id"], user["token_version"]),
        "userInfo": user_info(user),
    }), 201


@bp.post("/login")
def login():
    data = json_body()
    username = as_str(data.get("username"), "username", max_len=50).strip()
    password = as_str(data.get("password"), "password", max_len=256)

    key = f"{request.remote_addr}:{username.lower()}"
    rate_limit.check(key)

    user = get_db().execute(
        "SELECT * FROM users WHERE username_lc = %s", (username.lower(),)
    ).fetchone()

    if user is None:
        burn_password_check(password)
        ok = False
    else:
        ok = verify_password(user["password_hash"], password)

    if not ok:
        rate_limit.record_failure(key)
        raise ApiError("INVALID CREDENTIALS", "Invalid username or password.", 401)

    rate_limit.clear(key)
    return jsonify({
        "success": True,
        "token": create_token(user["id"], user["token_version"]),
        "userInfo": user_info(user),
    })


@bp.put("/profile")
@auth_required
def update_profile():
    db, user = get_db(), g.user
    updates, params = [], []
    old_avatar, new_avatar = user["image"], None

    new_username = request.form.get("username")
    if new_username and new_username != user["username"]:
        new_username = valid_username(new_username)
        if _username_taken(db, new_username.lower(), except_id=user["id"]):
            raise ApiError("USERNAME TAKEN", "Username is already taken.", 409)
        updates += ["username = %s", "username_lc = %s"]
        params += [new_username, new_username.lower()]

    image = request.files.get("image")
    if image and image.filename:
        new_avatar = process_and_save_avatar(image)
        updates.append("image = %s")
        params.append(new_avatar)

    if updates:
        try:
            db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", (*params, user["id"]))
            if new_avatar and old_avatar:
                db.execute("DELETE FROM user_images WHERE filename = %s", (old_avatar,))
            db.commit()
        except psycopg.errors.UniqueViolation:
            db.rollback()
            raise ApiError("USERNAME TAKEN", "Username is already taken.", 409)

    fresh = db.execute("SELECT * FROM users WHERE id = %s", (user["id"],)).fetchone()
    return jsonify({"success": True, "userInfo": user_info(fresh)})


@bp.put("/profile/password")
@auth_required
def change_password():
    data = json_body()
    old_pw = data.get("oldPassword")
    new_pw = data.get("newPassword")
    if not old_pw or not new_pw:
        raise ApiError("EMPTY FIELDS", "Both old and new passwords are required.", 400)
    if not isinstance(old_pw, str) or not isinstance(new_pw, str):
        raise ApiError("INVALID FIELD", "Passwords must be text.", 400)

    new_pw = valid_password(new_pw, "newPassword")
    user, db = g.user, get_db()

    if not verify_password(user["password_hash"], old_pw):
        raise ApiError("INCORRECT PASSWORD", "Incorrect old password.", 403)

    new_version = user["token_version"] + 1
    db.execute(
        "UPDATE users SET password_hash = %s, token_version = %s WHERE id = %s",
        (hash_password(new_pw), new_version, user["id"]),
    )
    db.commit()
    return jsonify({"success": True, "token": create_token(user["id"], new_version)})


@bp.post("/logout-all")
@auth_required
def logout_all():
    db = get_db()
    db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = %s", (g.user["id"],))
    db.commit()
    return jsonify({"success": True})


@bp.delete("/profile")
@auth_required
def delete_account():
    db, user = get_db(), g.user
    delete_avatar(user["image"])
    db.execute("DELETE FROM users WHERE id = %s", (user["id"],))
    db.commit()
    return jsonify({"success": True})


@bp.get("/user_images/<filename>")
def user_image(filename):
    if not _IMAGE_NAME_RE.match(filename):
        raise ApiError("NOT FOUND", "Image not found.", 404)
    data = load_avatar(filename)
    if data is None:
        raise ApiError("NOT FOUND", "Image not found.", 404)
    resp = Response(data, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
