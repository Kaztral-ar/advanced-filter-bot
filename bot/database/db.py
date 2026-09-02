import logging

from motor.motor_asyncio import AsyncIOMotorClient

from bot.config import Config

logger = logging.getLogger(__name__)

# Keep Mongo's socket pool deliberately small for low-RAM hosts. Motor/PyMongo
# otherwise permits a much larger pool than a small bot needs.
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
    await filters_col.create_index(
        [("chat_id", 1), ("keyword", 1)], unique=True, name="chat_keyword_unique"
    )
    # Token lookup makes alert-button callbacks O(log n) instead of scanning
    # every filter in a chat.
    await filters_col.create_index(
        [("chat_id", 1), ("alert_token", 1)], name="chat_alert_token_idx"
    )
    await connections_col.create_index([("_id", 1)])
    await banned_col.create_index([("_id", 1)])


async def check_connection() -> bool:
    try:
        await client.admin.command("ping")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("MongoDB connection failed: %s", e)
        return False
