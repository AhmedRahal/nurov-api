# Nurov API

Flask REST API for the Nurov desktop app. Handles accounts, notes, avatars, tags, and offline sync.

## Stack

- Python 3.10+
- Flask
- PostgreSQL 13+
- psycopg 3 (with connection pool)
- PyJWT for auth
- Pillow for avatar processing
- nh3 for HTML sanitizing

## Local setup

1. Start Postgres with Docker:  docker compose up -d db
2. Create a virtualenv:  python -m venv .venv
3. Activate it:  source .venv/bin/activate  (Windows: .venv\Scripts\activate)
4. Install deps:  pip install -r requirements.txt
5. Copy .env.example to .env and set SECRET_KEY and DATABASE_URL
6. Run:  python run.py

Health check: GET [https://nurov-api-hosted.onrender.com/api/health](https://nurov-api-hosted.onrender.com/api/health)

## Environment variables

- SECRET_KEY           required, 32+ chars, JWT signing key
- DATABASE_URL         required, postgres connection string
- DB_POOL_MIN          default 1
- DB_POOL_MAX          default 10
- TOKEN_TTL_HOURS      default 72
- MAX_NOTES_PER_BULK   default 500
- MAX_NOTES_PER_USER   default 5000
- CORS_ORIGINS         comma-separated, add "null" for packaged Electron
- BLOCKED_WORDS        comma-separated moderation blocklist
- FLASK_DEBUG          default 0
- PORT                 default 5000

## Testing

Set TEST_DATABASE_URL to a Postgres DB and run pytest.

  export TEST_DATABASE_URL="postgresql://nurov:nurov@localhost:5432/nurov_test"
  pytest -q

Tests skip if TEST_DATABASE_URL is not set.

## API

Health
- GET  /api/health

Auth
- POST   /api/auth/register              multipart: username, password, optional image
- POST   /api/auth/login                 json: username, password
- PUT    /api/auth/profile               multipart: optional username, optional image
- PUT    /api/auth/profile/password      json: oldPassword, newPassword
- POST   /api/auth/logout-all
- DELETE /api/auth/profile
- GET    /api/auth/user_images/<filename>

Notes
- GET    /api/notes
- GET    /api/notes/tags
- POST   /api/notes
- PUT    /api/notes/<note_id>
- DELETE /api/notes/<note_id>
- POST   /api/notes/bulk                 json: { notes: [...], overrideExisting: bool }

Error shape: { "success": false, "code": "...", "message": "..." }

## Deploy

Render: build "pip install -r requirements.txt", start
"gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60"
Add a Postgres instance, copy its URL into DATABASE_URL, set SECRET_KEY and CORS_ORIGINS.

Railway: deploy from GitHub, add Postgres plugin, set DATABASE_URL, SECRET_KEY, CORS_ORIGINS.

Fly.io: fly launch; fly postgres create; fly postgres attach <pg>; fly secrets set SECRET_KEY=... CORS_ORIGINS=...; fly deploy.

Docker: docker build -t nurov-api . ; docker run -p 5000:5000 -e SECRET_KEY=... -e DATABASE_URL=... nurov-api

## Electron notes

- Point the app at the deployed URL.
- Packaged Electron (file://) sends Origin: null, so add "null" to CORS_ORIGINS.
- Avatars are stored in Postgres as BYTEA, so they survive redeploys.

## Security

- SECRET_KEY must be 32+ chars or the app refuses to boot.
- Tokens carry a tv claim. Password change and /logout-all bump it, killing old tokens.
- Avatars are re-encoded to PNG server-side, stripping EXIF and polyglot payloads.
- HTML is sanitized server-side.
- Login failures are rate-limited per IP + username.
- Note ownership is checked at query time; other users' notes return 404.

## Known limitations

- Rate limiting is in-memory; per-worker. Use Redis if you scale out.
- Moderation is a simple env blocklist.
- Sync is last-write-wins on updated_at, not a CRDT.
