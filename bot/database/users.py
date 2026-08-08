from typing import List, Optional, Tuple

from bot.database.db import users_col, banned_col


async def add_user(user_id: str, username: str, name: str, dc_id: str) -> None:
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"username": username, "name": name, "dc_id": dc_id}},
        upsert=True,
    )


async def all_users() -> int:
    # pymongo/motor's Collection.count() was removed years ago in favor of
    # count_documents(); the original code called .count() which raises
    # AttributeError on any modern pymongo/motor version.
    return await users_col.count_documents({})


async def all_user_ids() -> List[str]:
    return [doc["_id"] async for doc in users_col.find({}, {"_id": 1})]


async def find_user(user_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    doc = await users_col.find_one({"_id": user_id})
    if not doc:
        return None, None, None
    return doc.get("name"), doc.get("username"), doc.get("dc_id")


async def ban_user(user_id: str, reason: str = "") -> None:
    await banned_col.update_one({"_id": user_id}, {"$set": {"reason": reason}}, upsert=True)


async def unban_user(user_id: str) -> bool:
    result = await banned_col.delete_one({"_id": user_id})
    return result.deleted_count > 0


async def is_banned(user_id: str) -> bool:
    return await banned_col.find_one({"_id": user_id}) is not None
