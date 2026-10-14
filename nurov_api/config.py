import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
    TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", "72"))
    MAX_NOTES_PER_BULK = int(os.environ.get("MAX_NOTES_PER_BULK", "500"))
    MAX_NOTES_PER_USER = int(os.environ.get("MAX_NOTES_PER_USER", "5000"))
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    MAX_AVATAR_BYTES = 2 * 1024 * 1024
    MAX_TITLE_CHARS = 500
    MAX_CONTENT_CHARS = 200_000
    MAX_TAGS_PER_NOTE = 20
    MAX_TAG_CHARS = 30
