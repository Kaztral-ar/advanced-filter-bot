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
    # --- Core Telegram credentials (required) ---
    TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
    API_ID = _env_int("API_ID", 0)
    API_HASH = os.environ.get("API_HASH", "")

    # --- Database ---
    DATABASE_URI = os.environ.get("DATABASE_URI", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "FilterBot")

    # --- Access control ---
    # IDs of users who can manage filters/settings anywhere, run /broadcast, /ban, etc.
    AUTH_USERS = _env_set("AUTH_USERS")
    # Optional: primary bot owner, gets every AUTH_USER permission plus /leave, /shell (if enabled)
    OWNER_ID = _env_int("OWNER_ID", 0)

    # --- Behaviour toggles ---
    SAVE_USER = _env_bool("SAVE_USER", False)
    MAX_FILTERS_PER_CHAT = _env_int("MAX_FILTERS_PER_CHAT", 0)  # 0 = unlimited
    FILTER_COOLDOWN_SECONDS = _env_int("FILTER_COOLDOWN_SECONDS", 2)  # anti-spam per chat

    # --- Optional integrations ---
    HEROKU_API_KEY = os.environ.get("HEROKU_API_KEY", "")
    LOG_CHANNEL = _env_int("LOG_CHANNEL", 0)  # chat id to receive error/join/leave logs

    # --- Web service (Render/Heroku web dynos need an open port) ---
    PORT = _env_int("PORT", 8080)
    ENABLE_WEB_SERVER = _env_bool("ENABLE_WEB_SERVER", True)

    # --- Command aliases ---
    ADD_FILTER_CMD = os.environ.get("ADD_FILTER_CMD", "add")
    DELETE_FILTER_CMD = os.environ.get("DELETE_FILTER_CMD", "del")
    DELETE_ALL_CMD = os.environ.get("DELETE_ALL_CMD", "delall")
    CONNECT_COMMAND = os.environ.get("CONNECT_COMMAND", "connect")
    DISCONNECT_COMMAND = os.environ.get("DISCONNECT_COMMAND", "disconnect")

    # --- Runtime ---
    WORKERS = _env_int("WORKERS", 24)
    BOT_START_TIME = time.time()

    @classmethod
    def validate(cls):
        """Fail fast with a clear message instead of an opaque crash mid-startup."""
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
