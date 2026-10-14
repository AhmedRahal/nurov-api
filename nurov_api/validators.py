import datetime as dt
import json
import re
import unicodedata
import uuid

from flask import current_app, request

from .errors import ApiError
from .moderation import check_text
from .sanitize import sanitize_html, strip_to_text

USERNAME_RE = re.compile(r"^[A-Za-z0-9]{3,20}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("INVALID BODY", "Expected a JSON object.", 400)
    return data


def as_str(value, field, *, required=True, max_len=10_000):
    if value is None or value == "":
        if required:
            raise ApiError("EMPTY FIELDS", f"'{field}' is required.", 400)
        return ""
    if not isinstance(value, str):
        raise ApiError("INVALID FIELD", f"'{field}' must be text.", 400)
    if len(value) > max_len:
        raise ApiError("INVALID FIELD", f"'{field}' is too long.", 400)
    return value


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def as_uuid(value, field="noteId"):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ApiError("INVALID ID", f"'{field}' is not a valid id.", 400)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def clean_timestamp(value, *, fallback=None, strict=False):
    fallback = fallback or now_iso()
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        if strict:
            raise ApiError("INVALID FIELD", "Dates must be ISO strings.", 400)
        return fallback
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        if strict:
            raise ApiError("INVALID FIELD", "Invalid date format.", 400)
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    parsed = parsed.astimezone(dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    if parsed > now:
        parsed = now
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def valid_username(value):
    username = as_str(value, "username", max_len=50).strip()
    if not USERNAME_RE.match(username):
        raise ApiError("INVALID USERNAME", "Username must be 3-20 letters or numbers.", 400)
    return username


def valid_password(value, field="password"):
    password = as_str(value, field, max_len=256)
    if len(password) < 6 or len(password) > 128 or not password.strip():
        raise ApiError("INVALID PASSWORD", "Password must be 6-128 characters.", 400)
    return password


def clean_tags(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = []
    if not isinstance(value, list):
        return []

    cfg = current_app.config
    out, seen = [], set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        tag = _CONTROL_CHARS.sub("", unicodedata.normalize("NFC", raw)).strip()
        tag = tag.replace("<", "").replace(">", "")
        tag = tag[: cfg["MAX_TAG_CHARS"]]
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
        if len(out) >= cfg["MAX_TAGS_PER_NOTE"]:
            break
    return out


def clean_note(data, *, existing_created_at=None):
    if not isinstance(data, dict):
        raise ApiError("INVALID NOTE", "Note must be an object.", 400)

    cfg = current_app.config
    title_raw = as_str(data.get("title"), "title", max_len=cfg["MAX_TITLE_CHARS"] * 20)
    content_raw = as_str(data.get("content"), "content", max_len=cfg["MAX_CONTENT_CHARS"] * 2)

    title = sanitize_html(title_raw)
    content = sanitize_html(content_raw)

    title_text, content_text = strip_to_text(title), strip_to_text(content)
    has_image = "<img" in content
    if not title_text:
        raise ApiError("INVALID NOTE", "Title cannot be empty.", 400)
    if not content_text and not has_image:
        raise ApiError("INVALID NOTE", "Content cannot be empty.", 400)
    if len(title_text) > cfg["MAX_TITLE_CHARS"] or len(content) > cfg["MAX_CONTENT_CHARS"]:
        raise ApiError("INVALID NOTE", "Note is too long.", 413)

    check_text(f"{title_text}\n{content_text}")

    now = now_iso()
    created = existing_created_at or clean_timestamp(data.get("createdAt"), fallback=now, strict=True)
    updated = clean_timestamp(data.get("updatedAt"), fallback=now, strict=True)
    if updated < created:
        updated = created

    return {
        "title": title,
        "content": content,
        "tags": clean_tags(data.get("tags")),
        "is_pinned": 1 if as_bool(data.get("isPinned")) else 0,
        "created_at": created,
        "updated_at": updated,
    }
