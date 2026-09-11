import logging
from typing import List, Optional

from pymongo.errors import DuplicateKeyError

from bot.database.db import connections_col

logger = logging.getLogger(__name__)


async def add_connection(group_id: str, user_id: str) -> bool:
    group_detail = {"group_id": group_id}

    # Atomically add a new group only when it is not already present. The
    # membership predicate prevents concurrent /connect requests from
    # inserting the same group twice.
    try:
        result = await connections_col.update_one(
            {"_id": user_id, "group_details.group_id": {"$ne": group_id}},
            {"$push": {"group_details": group_detail}, "$set": {"active_group": group_id}},
        )
        if result.matched_count:
            return True

        # The user may not have a connection document yet. A concurrent
        # creator can win the insert, so handle that race and retry atomically.
        doc = await connections_col.find_one({"_id": user_id}, {"_id": 1})
        if doc is None:
            try:
                await connections_col.insert_one(
                    {"_id": user_id, "group_details": [group_detail], "active_group": group_id}
                )
                return True
            except DuplicateKeyError:
                pass

        retry = await connections_col.update_one(
            {"_id": user_id, "group_details.group_id": {"$ne": group_id}},
            {"$push": {"group_details": group_detail}, "$set": {"active_group": group_id}},
        )
        return retry.matched_count > 0
    except Exception as e:  # noqa: BLE001
        logger.error("add_connection failed: %s", e)
        return False


async def active_connection(user_id: str) -> Optional[int]:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "group_details": 0})
    if not doc:
        return None
    group_id = doc.get("active_group")
    if group_id is None:
        return None
    try:
        return int(group_id)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed active_group for user %s: %r", user_id, group_id)
        return None


async def all_connections(user_id: str) -> Optional[List[str]]:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "active_group": 0})
    if not doc:
        return None

    group_ids = []
    for group in doc.get("group_details", []):
        if not isinstance(group, dict):
            logger.warning("Ignoring malformed connection entry for user %s: %r", user_id, group)
            continue
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            logger.warning("Ignoring malformed group_id for user %s: %r", user_id, group_id)
            continue
        group_ids.append(group_id)
    return group_ids


async def if_active(user_id: str, group_id: str) -> bool:
    doc = await connections_col.find_one({"_id": user_id}, {"_id": 0, "group_details": 0})
    return bool(doc) and doc.get("active_group") == group_id


async def make_active(user_id: str, group_id: str) -> bool:
    result = await connections_col.update_one(
        {"_id": user_id, "group_details": {"$elemMatch": {"group_id": group_id}}},
        {"$set": {"active_group": group_id}},
    )
    return result.modified_count > 0 or result.matched_count > 0


async def make_inactive(user_id: str) -> bool:
    result = await connections_col.update_one(
        {"_id": user_id, "active_group": {"$ne": None}},
        {"$set": {"active_group": None}},
    )
    return result.modified_count > 0


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
                valid_remaining = [
                    item.get("group_id")
                    for item in remaining
                    if isinstance(item, dict) and isinstance(item.get("group_id"), str) and item.get("group_id")
                ]
                if valid_remaining:
                    await connections_col.update_one(
                        {"_id": user_id}, {"$set": {"active_group": valid_remaining[-1]}}
                    )
                else:
                    await connections_col.update_one(
                        {"_id": user_id}, {"$set": {"active_group": None}
                    )
        else:
            await connections_col.update_one({"_id": user_id}, {"$set": {"active_group": None}})
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("delete_connection failed: %s", e)
        return False
