import os

from .errors import ApiError

_BLOCKLIST = [w.strip().lower() for w in os.environ.get("BLOCKED_WORDS", "").split(",") if w.strip()]


def check_text(text):
    lowered = (text or "").lower()
    for word in _BLOCKLIST:
        if word in lowered:
            raise ApiError("CONTENT REJECTED", "This content isn't allowed.", 422)


def check_image(image_bytes):
    return None
