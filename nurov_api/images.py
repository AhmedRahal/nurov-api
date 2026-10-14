import io
import secrets

from flask import current_app
from PIL import Image, UnidentifiedImageError

from .db import get_db
from .errors import ApiError
from .moderation import check_image
from .validators import now_iso

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
AVATAR_SIZE = 256
Image.MAX_IMAGE_PIXELS = 20_000_000


def process_and_save_avatar(file_storage):
    raw = file_storage.read(current_app.config["MAX_AVATAR_BYTES"] + 1)
    if not raw:
        raise ApiError("INVALID IMAGE", "Empty image upload.", 400)
    if len(raw) > current_app.config["MAX_AVATAR_BYTES"]:
        raise ApiError("INVALID IMAGE", "Image is too large (max 2 MB).", 413)

    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ApiError("INVALID IMAGE", "Unsupported image type.", 400)
        img.load()
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError("INVALID IMAGE", "That file isn't a valid image.", 400)

    check_image(raw)

    img = img.convert("RGBA")
    img.thumbnail((AVATAR_SIZE, AVATAR_SIZE))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    filename = f"{secrets.token_hex(16)}.png"
    get_db().execute(
        "INSERT INTO user_images (filename, data, created_at) VALUES (%s, %s, %s)",
        (filename, data, now_iso()),
    )
    return filename


def delete_avatar(filename):
    if not filename:
        return
    get_db().execute("DELETE FROM user_images WHERE filename = %s", (filename,))


def load_avatar(filename):
    row = get_db().execute(
        "SELECT data FROM user_images WHERE filename = %s", (filename,)
    ).fetchone()
    return bytes(row["data"]) if row else None
