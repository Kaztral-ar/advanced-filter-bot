import re
import time
import logging
from typing import Dict, List, Optional, Tuple

from bot.database.db import filters_col
from bot.handlers.utils import alert_token

logger = logging.getLogger(__name__)

_cache: Dict[int, Tuple[Optional["re.Pattern"], Dict[str, dict]]] = {}


def _invalidate(chat_id: int) -> None:
    _cache.pop(chat_id, None)


async def add_filter(chat_id: int, keyword: str, reply_text: str, buttons: list,
                     file_id: Optional[str], file_type: Optional[str], alerts: list,
                     created_by: int) -> None:
    keyword = keyword.strip().lower()
    doc = {"chat_id": chat_id, "keyword": keyword, "reply_text": reply_text or "",
           "buttons": buttons or [], "file_id": file_id, "file_type": file_type,
           "alerts": alerts or [], "created_by": created_by, "updated_at": time.time()}
    await filters_col.update_one({"chat_id": chat_id, "keyword": keyword}, {"$set": doc}, upsert=True)
    _invalidate(chat_id)


async def get_filter(chat_id: int, keyword: str) -> Optional[dict]:
    return await filters_col.find_one({"chat_id": chat_id, "keyword": keyword.strip().lower()})


async def get_filter_by_alert_token(chat_id: int, token: str) -> Optional[dict]:
    """Find a filter by its stable alert callback token."""
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1, "alerts": 1})
    async for doc in cursor:
        if alert_token(doc.get("keyword", "")) == token:
            return doc
    return None


async def get_all_keywords(chat_id: int) -> List[str]:
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1}).sort("keyword", 1)
    return [doc["keyword"] async for doc in cursor]


async def count_filters(chat_id: int) -> int:
    return await filters_col.count_documents({"chat_id": chat_id})


async def count_new_filters(chat_id: int, keywords: List[str]) -> int:
    """Count requested keywords that do not already exist using one DB query."""
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


async def _build_cache(chat_id: int) -> Tuple[Optional["re.Pattern"], Dict[str, dict]]:
    docs = [doc async for doc in filters_col.find({"chat_id": chat_id})]
    if not docs:
        return None, {}
    by_keyword = {d["keyword"]: d for d in docs}
    ordered = sorted(by_keyword.keys(), key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in ordered)
    pattern = re.compile(r"(?:^|\s|[^\w])(" + alternation + r")(?:$|\s|[^\w])", flags=re.IGNORECASE)
    return pattern, by_keyword


async def match_filter(chat_id: int, text: str) -> Optional[dict]:
    if not text:
        return None
    cached = _cache.get(chat_id)
    if cached is None:
        pattern, by_keyword = await _build_cache(chat_id)
        _cache[chat_id] = (pattern, by_keyword)
    else:
        pattern, by_keyword = cached
    if pattern is None:
        return None
    m = pattern.search(text)
    return by_keyword.get(m.group(1).lower()) if m else None


async def total_stats() -> Tuple[int, int]:
    chats = len(await filters_col.distinct("chat_id"))
    total = await filters_col.count_documents({})
    return chats, total


async def export_filters(chat_id: int) -> List[dict]:
    cursor = filters_col.find({"chat_id": chat_id}, {"_id": 0})
    return [doc async for doc in cursor]


async def import_filters(chat_id: int, docs: List[dict]) -> int:
    """Import filter records with one bulk database write."""
    operations = []
    seen = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        keyword = str(doc.get("keyword", "")).strip().lower()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        operations.append({"update_one": {
            "filter": {"chat_id": chat_id, "keyword": keyword},
            "update": {"$set": {
                "chat_id": chat_id, "keyword": keyword,
                "reply_text": str(doc.get("reply_text", "")),
                "buttons": doc.get("buttons", []), "file_id": doc.get("file_id"),
                "file_type": doc.get("file_type"), "alerts": doc.get("alerts", []),
                "created_by": doc.get("created_by", 0), "updated_at": time.time(),
            }}, "upsert": True,
        }})
    if not operations:
        return 0
    result = await filters_col.bulk_write(operations, ordered=False)
    _invalidate(chat_id)
    return result.upserted_count + result.modified_count + result.matched_count
