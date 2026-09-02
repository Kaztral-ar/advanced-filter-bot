import logging
import re
import time
from collections import OrderedDict
from typing import List, Optional, Tuple

from bot.config import Config
from bot.database.db import filters_col
from bot.handlers.utils import alert_token

logger = logging.getLogger(__name__)

# Cache only compiled matchers, never full filter documents. LRU eviction
# prevents memory growing forever as the bot joins more groups.
_cache: "OrderedDict[int, Optional[re.Pattern]]" = OrderedDict()


def _invalidate(chat_id: int) -> None:
    _cache.pop(chat_id, None)


def _remember(chat_id: int, pattern: Optional[re.Pattern]) -> None:
    _cache[chat_id] = pattern
    _cache.move_to_end(chat_id)
    while len(_cache) > Config.FILTER_CACHE_CHATS:
        _cache.popitem(last=False)


async def add_filter(chat_id: int, keyword: str, reply_text: str, buttons: list,
                     file_id: Optional[str], file_type: Optional[str], alerts: list,
                     created_by: int) -> None:
    keyword = keyword.strip().lower()
    doc = {
        "chat_id": chat_id,
        "keyword": keyword,
        "alert_token": alert_token(keyword),
        "reply_text": reply_text or "",
        "buttons": buttons or [],
        "file_id": file_id,
        "file_type": file_type,
        "alerts": alerts or [],
        "created_by": created_by,
        "updated_at": time.time(),
    }
    await filters_col.update_one(
        {"chat_id": chat_id, "keyword": keyword}, {"$set": doc}, upsert=True
    )
    _invalidate(chat_id)


async def get_filter(chat_id: int, keyword: str) -> Optional[dict]:
    return await filters_col.find_one({"chat_id": chat_id, "keyword": keyword.strip().lower()})


async def get_filter_by_alert_token(chat_id: int, token: str) -> Optional[dict]:
    doc = await filters_col.find_one({"chat_id": chat_id, "alert_token": token}, {"alerts": 1})
    if doc:
        return doc
    # Backward compatibility for filters created before alert_token was stored.
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1, "alerts": 1})
    async for old_doc in cursor:
        if alert_token(old_doc.get("keyword", "")) == token:
            return old_doc
    return None


async def get_all_keywords(chat_id: int) -> List[str]:
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1}).sort("keyword", 1)
    return [doc["keyword"] async for doc in cursor]


async def count_filters(chat_id: int) -> int:
    return await filters_col.count_documents({"chat_id": chat_id})


async def count_new_filters(chat_id: int, keywords: List[str]) -> int:
    normalized = list(dict.fromkeys(k.strip().lower() for k in keywords if k.strip()))
    if not normalized:
        return 0
    existing = await filters_col.count_documents({"chat_id": chat_id, "keyword": {"$in": normalized}})
    return len(normalized) - existing


async def delete_filter(chat_id: int, keyword: str) -> bool:
    result = await filters_col.delete_one({"chat_id": chat_id, "keyword": keyword.strip().lower()})
    _invalidate(chat_id)
    return result.deleted_count > 0


async def delete_all_filters(chat_id: int) -> int:
    result = await filters_col.delete_many({"chat_id": chat_id})
    _invalidate(chat_id)
    return result.deleted_count


async def _build_cache(chat_id: int) -> Optional[re.Pattern]:
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1})
    keywords = [doc["keyword"] async for doc in cursor if doc.get("keyword")]
    if not keywords:
        return None
    ordered = sorted(set(keywords), key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in ordered)
    return re.compile(
        r"(?:^|\s|[^\w])(" + alternation + r")(?:$|\s|[^\w])",
        flags=re.IGNORECASE,
    )


async def match_filter(chat_id: int, text: str) -> Optional[dict]:
    if not text:
        return None
    pattern = _cache.get(chat_id)
    if pattern is None and chat_id not in _cache:
        pattern = await _build_cache(chat_id)
        _remember(chat_id, pattern)
    else:
        _cache.move_to_end(chat_id)
    if pattern is None:
        return None
    match = pattern.search(text)
    if not match:
        return None
    # Only the matched response is loaded; media/replies for other filters stay in MongoDB.
    return await filters_col.find_one({"chat_id": chat_id, "keyword": match.group(1).lower()})


async def total_stats() -> Tuple[int, int]:
    # Count chats on MongoDB instead of materializing every distinct chat id in Python.
    result = await filters_col.aggregate([
        {"$group": {"_id": "$chat_id"}},
        {"$count": "chats"},
    ]).to_list(length=1)
    chats = result[0]["chats"] if result else 0
    total = await filters_col.count_documents({})
    return chats, total


async def export_filters(chat_id: int) -> List[dict]:
    cursor = filters_col.find({"chat_id": chat_id}, {"_id": 0})
    return [doc async for doc in cursor]


async def import_filters(chat_id: int, docs: List[dict]) -> int:
    operations = []
    seen = set()
    now = time.time()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        keyword = str(doc.get("keyword", "")).strip().lower()
        if not keyword or keyword in seen or len(keyword) > 256:
            continue
        buttons = doc.get("buttons", [])
        alerts = doc.get("alerts", [])
        if not isinstance(buttons, list) or not isinstance(alerts, list):
            continue
        seen.add(keyword)
        operations.append({"update_one": {
            "filter": {"chat_id": chat_id, "keyword": keyword},
            "update": {"$set": {
                "chat_id": chat_id,
                "keyword": keyword,
                "alert_token": alert_token(keyword),
                "reply_text": str(doc.get("reply_text", ""))[:4096],
                "buttons": buttons[:100],
                "file_id": doc.get("file_id"),
                "file_type": doc.get("file_type"),
                "alerts": [str(x)[:1024] for x in alerts[:100]],
                "created_by": doc.get("created_by", 0),
                "updated_at": now,
            }},
            "upsert": True,
        }})
    if not operations:
        return 0
    await filters_col.bulk_write(operations, ordered=False)
    _invalidate(chat_id)
    return len(operations)
