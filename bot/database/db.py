import logging

from motor.motor_asyncio import AsyncIOMotorClient

from bot.config import Config

logger = logging.getLogger(__name__)

# Small, lazy Mongo pool: suitable for a single Telegram bot on low-RAM hosts.
# minPoolSize=0 means idle connections are not kept just to reserve memory.
client = AsyncIOMotorClient(
    Config.DATABASE_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000,
    maxPoolSize=Config.MONGO_MAX_POOL_SIZE,
    minPoolSize=Config.MONGO_MIN_POOL_SIZE,
    maxConnecting=Config.MONGO_MAX_CONNECTING,
)
db = client[Config.DATABASE_NAME]

filters_col = db["FILTERS"]
connections_col = db["CONNECTIONS"]
users_col = db["USERS"]
banned_col = db["BANNED"]


async def ensure_indexes() -> None:
    # One compound index covers normal filter lookup and the keyword list.
    # The separate chat_id index was redundant because chat_id is the prefix.
    await filters_col.create_index(
        [("chat_id", 1), ("keyword", 1)], unique=True, name="chat_keyword_unique"
    )
    await filters_col.create_index(
        [("chat_id", 1), ("alert_token", 1)], name="chat_alert_token_idx"
    )
    # _id is automatically indexed by MongoDB; do not create duplicate _id indexes.


async def check_connection() -> bool:
    try:
        await client.admin.command("ping")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("MongoDB connection failed: %s", e)
        return False
