from flask import current_app, g
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT NOT NULL,
    username_lc   TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    image         TEXT,
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    note_id    TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '[]',
    is_pinned  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS user_images (
    filename   TEXT PRIMARY KEY,
    data       BYTEA NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(row_factory=dict_row)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def get_db():
    if "db" not in g:
        conn = current_app.extensions["db_pool"].getconn()
        g.db_conn = conn
        g.db = Database(conn)
    return g.db


def close_db(exc=None):
    conn = g.pop("db_conn", None)
    g.pop("db", None)
    if conn is None:
        return
    pool = current_app.extensions["db_pool"]
    try:
        conn.rollback()
    except Exception:
        pass
    pool.putconn(conn)

def init_db(app):
    if not app.config["DATABASE_URL"]:
        raise RuntimeError(
            "DATABASE_URL is required. Example: "
            "postgresql://nurov:nurov@localhost:5432/nurov"
        )

    pool = ConnectionPool(
        conninfo=app.config["DATABASE_URL"],
        min_size=app.config["DB_POOL_MIN"],
        max_size=app.config["DB_POOL_MAX"],
        open=True,
    )
    app.extensions["db_pool"] = pool

    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(727001)")
            try:
                for statement in SCHEMA.split(";"):
                    s = statement.strip()
                    if s:
                        cur.execute(s)
                conn.commit()
            finally:
                cur.execute("SELECT pg_advisory_unlock(727001)")
                conn.commit()
    finally:
        pool.putconn(conn)

    app.teardown_appcontext(close_db)