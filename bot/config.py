import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_set(key: str) -> set:
    raw = os.environ.get(key, "")
    return {x.strip() for x in raw.replace(",", " ").split() if x.strip()}


class Config(object):
    TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
    API_ID = _env_int("API_ID", 0)
    API_HASH = os.environ.get("API_HASH", "")

    DATABASE_URI = os.environ.get("DATABASE_URI", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "FilterBot")

    AUTH_USERS = _env_set("AUTH_USERS")
    OWNER_ID = _env_int("OWNER_ID", 0)

    SAVE_USER = _env_bool("SAVE_USER", False)
    MAX_FILTERS_PER_CHAT = _env_int("MAX_FILTERS_PER_CHAT", 0)
    FILTER_COOLDOWN_SECONDS = _env_int("FILTER_COOLDOWN_SECONDS", 2)

    HEROKU_API_KEY = os.environ.get("HEROKU_API_KEY", "")
    LOG_CHANNEL = _env_int("LOG_CHANNEL", 0)

    PORT = _env_int("PORT", 8080)
    ENABLE_WEB_SERVER = _env_bool("ENABLE_WEB_SERVER", True)

    ADD_FILTER_CMD = os.environ.get("ADD_FILTER_CMD", "add")
    DELETE_FILTER_CMD = os.environ.get("DELETE_FILTER_CMD", "del")
    DELETE_ALL_CMD = os.environ.get("DELETE_ALL_CMD", "delall")
    CONNECT_COMMAND = os.environ.get("CONNECT_COMMAND", "connect")
    DISCONNECT_COMMAND = os.environ.get("DISCONNECT_COMMAND", "disconnect")

    # Conservative defaults for small hosting plans. All are configurable.
    WORKERS = max(1, _env_int("WORKERS", 8))
    MONGO_MAX_POOL_SIZE = max(1, _env_int("MONGO_MAX_POOL_SIZE", 10))
    MONGO_MIN_POOL_SIZE = max(0, _env_int("MONGO_MIN_POOL_SIZE", 0))
    MONGO_MAX_CONNECTING = max(1, _env_int("MONGO_MAX_CONNECTING", 2))
    FILTER_CACHE_CHATS = max(1, _env_int("FILTER_CACHE_CHATS", 16))
    BOT_START_TIME = time.time()

    @classmethod
    def validate(cls):
        missing = []
        if not cls.TG_BOT_TOKEN:
            missing.append("TG_BOT_TOKEN")
        if not cls.API_ID:
            missing.append("API_ID")
        if not cls.API_HASH:
            missing.append("API_HASH")
        if not cls.DATABASE_URI:
            missing.append("DATABASE_URI")
        if missing:
            raise SystemExit(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"See .env.sample for the full list."
            )
