import json

from flask import Blueprint, current_app, g, jsonify

from ..db import get_db
from ..errors import ApiError
from ..security import auth_required
from ..serializers import note_out
from ..validators import as_uuid, clean_note, json_body, new_id

bp = Blueprint("notes", __name__)


def _count_notes(db, user_id):
    return db.execute(
        "SELECT COUNT(*) AS c FROM notes WHERE user_id = %s", (user_id,)
    ).fetchone()["c"]


def _insert(db, note_id, user_id, n):
    db.execute(
        "INSERT INTO notes (note_id, user_id, title, content, tags, is_pinned, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (note_id, user_id, n["title"], n["content"], json.dumps(n["tags"]),
         n["is_pinned"], n["created_at"], n["updated_at"]),
    )


def _update(db, note_id, n):
    db.execute(
        "UPDATE notes SET title = %s, content = %s, tags = %s, is_pinned = %s, updated_at = %s "
        "WHERE note_id = %s",
        (n["title"], n["content"], json.dumps(n["tags"]), n["is_pinned"], n["updated_at"], note_id),
    )


def _get_row(db, note_id):
    return db.execute("SELECT * FROM notes WHERE note_id = %s", (note_id,)).fetchone()


def _owned_or_none(row, user_id):
    return row if row is not None and row["user_id"] == user_id else None


@bp.get("")
@auth_required
def list_notes():
    rows = get_db().execute(
        "SELECT * FROM notes WHERE user_id = %s ORDER BY updated_at DESC", (g.user["id"],)
    ).fetchall()
    return jsonify([note_out(r) for r in rows])


@bp.get("/tags")
@auth_required
def list_tags():
    rows = get_db().execute(
        "SELECT tags FROM notes WHERE user_id = %s ORDER BY created_at ASC", (g.user["id"],)
    ).fetchall()
    seen = {}
    for r in rows:
        for tag in json.loads(r["tags"] or "[]"):
            seen.setdefault(tag.lower(), tag)
    return jsonify({"tags": sorted(seen.values(), key=str.lower)})


@bp.post("")
@auth_required
def create_note():
    data = json_body()
    db, user_id = get_db(), g.user["id"]

    note_id = as_uuid(data["noteId"]) if data.get("noteId") else new_id()
    existing = _get_row(db, note_id)
    if existing is not None and existing["user_id"] != user_id:
        raise ApiError("NOTE ID TAKEN", "That note id can't be used.", 409)

    if existing is not None:
        n = clean_note(data, existing_created_at=existing["created_at"])
        _update(db, note_id, n)
        db.commit()
        return jsonify({"success": True, "noteId": note_id})

    if _count_notes(db, user_id) >= current_app.config["MAX_NOTES_PER_USER"]:
        raise ApiError("LIMIT REACHED", "Note limit reached.", 403)

    _insert(db, note_id, user_id, clean_note(data))
    db.commit()
    return jsonify({"success": True, "noteId": note_id}), 201


@bp.put("/<note_id>")
@auth_required
def update_note(note_id):
    try:
        note_id = as_uuid(note_id)
    except ApiError:
        raise ApiError("NOT FOUND", "Note not found.", 404)

    db = get_db()
    row = _owned_or_none(_get_row(db, note_id), g.user["id"])
    if row is None:
        raise ApiError("NOT FOUND", "Note not found.", 404)

    n = clean_note(json_body(), existing_created_at=row["created_at"])
    _update(db, note_id, n)
    db.commit()
    return jsonify({"success": True, "noteId": note_id})


@bp.delete("/<note_id>")
@auth_required
def delete_note(note_id):
    try:
        note_id = as_uuid(note_id)
    except ApiError:
        return jsonify({"success": True})

    db = get_db()
    db.execute("DELETE FROM notes WHERE note_id = %s AND user_id = %s", (note_id, g.user["id"]))
    db.commit()
    return jsonify({"success": True})


@bp.post("/bulk")
@auth_required
def bulk_notes():
    data = json_body()
    notes = data.get("notes")
    override = data.get("overrideExisting") is True
    cfg = current_app.config

    if not isinstance(notes, list):
        raise ApiError("INVALID BODY", "'notes' must be a list.", 400)
    if len(notes) > cfg["MAX_NOTES_PER_BULK"]:
        raise ApiError("TOO MANY NOTES", f"Max {cfg['MAX_NOTES_PER_BULK']} notes per request.", 413)

    db, user_id = get_db(), g.user["id"]
    total = _count_notes(db, user_id)
    saved, skipped, rejected = [], [], []

    for index, raw in enumerate(notes):
        note_id = None
        db.execute("SAVEPOINT bulk_note")
        try:
            note_id = as_uuid(raw.get("noteId")) if isinstance(raw, dict) and raw.get("noteId") else new_id()
            existing = _get_row(db, note_id)

            if existing is not None and existing["user_id"] != user_id:
                raise ApiError("NOTE ID TAKEN", "That note id can't be used.", 409)

            if existing is None:
                if total >= cfg["MAX_NOTES_PER_USER"]:
                    raise ApiError("LIMIT REACHED", "Note limit reached.", 403)
                _insert(db, note_id, user_id, clean_note(raw))
                total += 1
                saved.append(note_id)
            else:
                n = clean_note(raw, existing_created_at=existing["created_at"])
                if override or n["updated_at"] > existing["updated_at"]:
                    _update(db, note_id, n)
                    saved.append(note_id)
                else:
                    skipped.append(note_id)

            db.execute("RELEASE SAVEPOINT bulk_note")

        except ApiError as err:
            db.execute("ROLLBACK TO SAVEPOINT bulk_note")
            rejected.append({"index": index, "noteId": note_id, "code": err.code, "message": err.message})
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT bulk_note")
            current_app.logger.exception("bulk note failed at index %s", index)
            rejected.append({
                "index": index,
                "noteId": note_id,
                "code": "INVALID NOTE",
                "message": "Note could not be processed.",
            })

    db.commit()
    return jsonify({"success": True, "saved": saved, "skipped": skipped, "rejected": rejected})
