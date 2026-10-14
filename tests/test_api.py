import io
import json
import os

import pytest
from PIL import Image

from nurov_api import create_app, rate_limit


@pytest.fixture()
def app():
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    rate_limit._attempts.clear()

    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": db_url,
        "CORS_ORIGINS": ["null"],
        "DB_POOL_MIN": 1,
        "DB_POOL_MAX": 2,
    })

    pool = app.extensions["db_pool"]
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE users, notes, user_images RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        pool.putconn(conn)

    yield app

    pool.close()


@pytest.fixture()
def client(app):
    return app.test_client()


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, format="PNG")
    buf.seek(0)
    return buf


def register(client, name="alice", pw="secret1", image=True):
    data = {"username": name, "password": pw}
    if image:
        data["image"] = (png_bytes(), "me.png")
    return client.post("/api/auth/register", data=data, content_type="multipart/form-data")


def auth(token):
    return {"Authorization": f"Bearer {token}"}


NOTE = {"title": "<p>Hello</p>", "content": "<p>World</p>", "tags": ["a", "B"], "isPinned": True}


def test_health(client):
    assert client.get("/api/health").json == {"status": "ok"}


def test_register_login_and_avatar(client):
    r = register(client)
    assert r.status_code == 201 and r.json["success"]
    info = r.json["userInfo"]
    assert info["id"] == info["userId"] and info["image"].endswith(".png")
    assert client.get(f"/api/auth/user_images/{info['image']}").status_code == 200

    ok = client.post("/api/auth/login", json={"username": "ALICE", "password": "secret1"})
    assert ok.status_code == 200 and ok.json["token"]

    bad = client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert bad.status_code == 401 and bad.json["code"] == "INVALID CREDENTIALS"


def test_duplicate_and_validation(client):
    register(client)
    dup = register(client, name="Alice")
    assert dup.status_code == 409 and dup.json["code"] == "USERNAME TAKEN"
    assert register(client, name="a b").json["code"] == "INVALID USERNAME"
    assert register(client, name="bobby", pw="123").json["code"] == "INVALID PASSWORD"


def test_fake_image_rejected(client):
    r = client.post("/api/auth/register", content_type="multipart/form-data", data={
        "username": "mallory", "password": "secret1",
        "image": (io.BytesIO(b"<script>alert(1)</script>"), "x.png"),
    })
    assert r.status_code == 400 and r.json["code"] == "INVALID IMAGE"


def test_image_route_blocks_traversal(client):
    assert client.get("/api/auth/user_images/..%2f..%2fetc%2fpasswd").status_code == 404
    assert client.get("/api/auth/user_images/notmine.png").status_code == 404


def test_notes_crud_and_isolation(client):
    ta = register(client, "alice").json["token"]
    tb = register(client, "bobby").json["token"]

    r = client.post("/api/notes", json=NOTE, headers=auth(ta))
    assert r.status_code == 201
    nid = r.json["noteId"]

    listed = client.get("/api/notes", headers=auth(ta)).json
    assert listed[0]["noteId"] == nid and listed[0]["isPinned"] is True and listed[0]["tags"] == ["a", "B"]
    assert client.get("/api/notes", headers=auth(tb)).json == []

    assert client.put(f"/api/notes/{nid}", json=NOTE, headers=auth(tb)).status_code == 404
    client.delete(f"/api/notes/{nid}", headers=auth(tb))
    assert len(client.get("/api/notes", headers=auth(ta)).json) == 1

    clash = client.post("/api/notes", json={**NOTE, "noteId": nid}, headers=auth(tb))
    assert clash.status_code == 409

    upd = client.put(f"/api/notes/{nid}", json={**NOTE, "title": "<p>New</p>"}, headers=auth(ta))
    assert upd.status_code == 200
    assert "New" in client.get("/api/notes", headers=auth(ta)).json[0]["title"]

    assert client.delete(f"/api/notes/{nid}", headers=auth(ta)).json["success"]
    assert client.delete(f"/api/notes/{nid}", headers=auth(ta)).json["success"]
    assert client.get("/api/notes", headers=auth(ta)).json == []


def test_auth_required_and_bad_tokens(client):
    r = client.get("/api/notes")
    assert r.status_code == 401 and r.json["code"] == "INVALID TOKEN"
    r = client.get("/api/notes", headers=auth("garbage"))
    assert r.status_code == 401 and r.json["code"] == "INVALID TOKEN"


def test_xss_and_empty_rejected(client):
    t = register(client).json["token"]
    r = client.post("/api/notes", headers=auth(t), json={
        "title": "<p>t</p>",
        "content": '<p>hi</p><script>alert(1)</script><img src=x onerror=alert(1)>',
    })
    assert r.status_code == 201
    stored = client.get("/api/notes", headers=auth(t)).json[0]["content"]
    assert "<script" not in stored and "onerror" not in stored
    assert client.post("/api/notes", headers=auth(t), json={"title": "", "content": "x"}).status_code == 400
    assert client.post("/api/notes", headers=auth(t), data="nope", content_type="text/plain").status_code == 400


def test_bulk_offline_shape_and_lww(client):
    t = register(client).json["token"]
    row = {"noteId": "11111111-1111-4111-8111-111111111111", "userId": 999, "isDirty": 1,
           "title": "<p>Off</p>", "content": "<p>line</p>", "tags": json.dumps(["x", "X", "y"]),
           "isPinned": 1, "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-02T00:00:00.000Z"}
    r = client.post("/api/notes/bulk", headers=auth(t), json={"notes": [row], "overrideExisting": False})
    assert r.json["saved"] == [row["noteId"]]
    n = client.get("/api/notes", headers=auth(t)).json[0]
    assert n["tags"] == ["x", "y"] and n["isPinned"] is True

    older = {**row, "title": "<p>OLD</p>", "updatedAt": "2026-01-01T12:00:00.000Z"}
    r = client.post("/api/notes/bulk", headers=auth(t), json={"notes": [older], "overrideExisting": False})
    assert r.json["skipped"] == [row["noteId"]]
    assert "Off" in client.get("/api/notes", headers=auth(t)).json[0]["title"]

    r = client.post("/api/notes/bulk", headers=auth(t), json={"notes": [older], "overrideExisting": True})
    assert r.json["saved"] == [row["noteId"]]

    bad = client.post("/api/notes/bulk", headers=auth(t), json={"notes": [{"title": "", "content": ""}, "x"]})
    assert len(bad.json["rejected"]) == 2

    future = {**row, "title": "<p>F</p>", "updatedAt": "2999-01-01T00:00:00Z"}
    client.post("/api/notes/bulk", headers=auth(t), json={"notes": [future]})
    assert client.get("/api/notes", headers=auth(t)).json[0]["updatedAt"] < "2100"


def test_tags_endpoint(client):
    t = register(client).json["token"]
    client.post("/api/notes", json={**NOTE, "tags": ["Zeta", "alpha"]}, headers=auth(t))
    client.post("/api/notes", json={**NOTE, "tags": ["ALPHA", "beta"]}, headers=auth(t))
    assert client.get("/api/notes/tags", headers=auth(t)).json["tags"] == ["alpha", "beta", "Zeta"]


def test_password_change_and_logout_all(client):
    t1 = register(client).json["token"]
    t2 = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"}).json["token"]

    wrong = client.put("/api/auth/profile/password", headers=auth(t1),
                       json={"oldPassword": "bad", "newPassword": "newpass1"})
    assert wrong.json["code"] == "INCORRECT PASSWORD"
    empty = client.put("/api/auth/profile/password", headers=auth(t1), json={"oldPassword": "x"})
    assert empty.json["code"] == "EMPTY FIELDS"

    ok = client.put("/api/auth/profile/password", headers=auth(t1),
                    json={"oldPassword": "secret1", "newPassword": "newpass1"})
    fresh = ok.json["token"]
    assert client.get("/api/notes", headers=auth(t1)).status_code == 401
    assert client.get("/api/notes", headers=auth(t2)).status_code == 401
    assert client.get("/api/notes", headers=auth(fresh)).status_code == 200

    assert client.post("/api/auth/logout-all", headers=auth(fresh)).json["success"]
    assert client.get("/api/notes", headers=auth(fresh)).status_code == 401


def test_profile_update_and_delete_account(client):
    r = register(client)
    t, old_img = r.json["token"], r.json["userInfo"]["image"]
    up = client.put("/api/auth/profile", headers=auth(t), content_type="multipart/form-data",
                    data={"username": "alice2", "image": (png_bytes(), "n.png")})
    info = up.json["userInfo"]
    assert info["username"] == "alice2" and info["image"] != old_img
    assert client.get(f"/api/auth/user_images/{old_img}").status_code == 404

    register(client, "bobby")
    taken = client.put("/api/auth/profile", headers=auth(t), content_type="multipart/form-data",
                       data={"username": "BOBBY"})
    assert taken.json["code"] == "USERNAME TAKEN"

    client.post("/api/notes", json=NOTE, headers=auth(t))
    assert client.delete("/api/auth/profile", headers=auth(t)).json["success"]
    assert client.get("/api/notes", headers=auth(t)).status_code == 401


def test_login_rate_limit(client):
    register(client)
    for _ in range(10):
        client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    r = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
    assert r.status_code == 429 and r.json["code"] == "TOO MANY ATTEMPTS"


def test_cors(client):
    pre = client.open("/api/notes", method="OPTIONS", headers={"Origin": "null"})
    assert pre.status_code == 204 and pre.headers["Access-Control-Allow-Origin"] == "null"
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in evil.headers


def test_sanitizer_rules_pure_python():
    from nurov_api.sanitize import _attr_filter, _safe_style
    assert _safe_style("color: rgb(230, 0, 0); position: fixed; inset: 0") == "color: rgb(230, 0, 0)"
    assert _safe_style("background-color: red; background-image: url(x)") == "background-color: red"
    assert _safe_style("color: red; x: url(javascript:1)") == "color: red"
    assert _attr_filter("span", "class", "ql-align-center modal active") == "ql-align-center"
    assert _attr_filter("div", "class", "modal") is None
    assert _attr_filter("a", "href", "data:text/html;base64,AAAA") is None
    assert _attr_filter("img", "src", "data:text/html;base64,AAAA") is None
    assert _attr_filter("img", "src", "data:image/png;base64,iVBORw0KGgo=") is not None
    assert _attr_filter("a", "href", "https://example.com") == "https://example.com"


def test_sanitizer_with_nh3_if_installed():
    try:
        import nh3  # noqa: F401
    except ImportError:
        return
    from nurov_api.sanitize import sanitize_html
    out = sanitize_html('<p class="ql-align-center x" style="color: red; position:fixed">a</p>'
                        '<a href="javascript:alert(1)">l</a><script>1</script>'
                        '<img src="data:image/png;base64,iVBORw0KGgo=" onerror="1">')
    assert "script" not in out and "javascript:" not in out and "onerror" not in out
    assert "position" not in out and 'class="ql-align-center"' in out and "data:image/png" in out
