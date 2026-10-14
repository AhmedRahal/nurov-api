import json


def user_info(row):
    return {"id": row["id"], "userId": row["id"], "username": row["username"], "image": row["image"]}


def note_out(row):
    return {
        "noteId": row["note_id"],
        "title": row["title"],
        "content": row["content"],
        "tags": json.loads(row["tags"] or "[]"),
        "isPinned": bool(row["is_pinned"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
