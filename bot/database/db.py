import logging

from motor.motor_asyncio import AsyncIOMotorClient

from bot.config import Config

logger = logging.getLogger(__name__)

# Motor gives us a genuinely async driver so DB calls no longer block the
# asyncio event loop that Pyrogram's handlers run on (the original code used
# synchronous pymongo calls inside `async def` handlers, which stalls every
# other in-flight update while Mongo I/O is pending).
client = AsyncIOMotorClient(Config.DATABASE_URI, serverSelectionTimeoutMS=15000)
db = client[Config.DATABASE_NAME]

filters_col = db["FILTERS"]
connections_col = db["CONNECTIONS"]
users_col = db["USERS"]
banned_col = db["BANNED"]


async def ensure_indexes() -> None:
    """Create indexes required for correctness and performance.

    A single FILTERS collection with a unique (chat_id, keyword) index
    replaces the original design of one Mongo collection per group, which
    doesn't enforce uniqueness, doesn't scale past MongoDB's per-database
    collection limits, and can't be indexed/queried efficiently in aggregate.
    """
    await filters_col.create_index(
        [("chat_id", 1), ("keyword", 1)], unique=True, name="chat_keyword_unique"
    )
    await filters_col.create_index([("chat_id", 1)], name="chat_id_idx")
    await connections_col.create_index([("_id", 1)])
    await banned_col.create_index([("_id", 1)])


async def check_connection() -> bool:
    try:
        await client.admin.command("ping")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("MongoDB connection failed: %s", e)
        return False
