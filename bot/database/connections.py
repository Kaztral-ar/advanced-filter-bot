import logging
from typing import List, Optional

from bot.database.db import connections_col

logger = logging.getLogger(__name__)


async def add_connection(group_id: str, user_id: str) -> bool:
    doc = await connections_col.find_one({"_id": user_id})
    if doc is not None:
        existing_ids = [g["group_id"] for g in doc.get("group_details", [])]
        if group_id in existing_ids:
            return False

    group_detail = {"group_id": group_id}

    if doc is None:
        try:
            await connections_col.insert_one(
                {"_id": user_id, "group_details": [group_detail], "active_group": group_id}
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("add_connection insert failed: %s", e)
            return False
    else:
        try:
            await connections_col.update_one(
                {"_id": user_id},
                {"$push": {"group_details": group_detail}, "$set": {"active_group": group_id}},
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("add_connection update failed: %s", e)
            return False


async def active_connection(user_id: str) -> Optional[int]:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "group_details": 0})
    if not doc:
        return None
    group_id = doc.get("active_group")
    return int(group_id) if group_id is not None else None


async def all_connections(user_id: str) -> Optional[List[str]]:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "active_group": 0})
    if not doc:
        return None
    return [g["group_id"] for g in doc.get("group_details", [])]


async def if_active(user_id: str, group_id: str) -> bool:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "group_details": 0})
    return bool(doc) and doc.get("active_group") == group_id


async def make_active(user_id: str, group_id: str) -> bool:
    result = await connections_col.update_one(
        {"_id": user_id}, {"$set": {"active_group": group_id}}
    )
    return result.modified_count > 0 or result.matched_count > 0


async def make_inactive(user_id: str) -> bool:
    result = await connections_col.update_one({"_id": user_id}, {"$set": {"active_group": None}})
    return result.modified_count > 0 or result.matched_count > 0


async def delete_connection(user_id: str, group_id: str) -> bool:
    try:
        result = await connections_col.update_one(
            {"_id": user_id}, {"$pull": {"group_details": {"group_id": group_id}}}
        )
        if result.modified_count == 0:
            return False

        doc = await connections_col.find_one({"_id": user_id}, {"_id": 0})
        remaining = doc.get("group_details", []) if doc else []
        if remaining:
            if doc.get("active_group") == group_id:
                fallback = remaining[-1]["group_id"]
                await connections_col.update_one(
                    {"_id": user_id}, {"$set": {"active_group": fallback}}
                )
        else:
            await connections_col.update_one({"_id": user_id}, {"$set": {"active_group": None}})
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("delete_connection failed: %s", e)
        return False
