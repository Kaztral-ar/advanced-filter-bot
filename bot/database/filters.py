import re
import time
import logging
from typing import Dict, List, Optional, Tuple

from bot.database.db import filters_col

logger = logging.getLogger(__name__)

# Per-chat compiled matcher cache: chat_id -> (compiled_pattern | None, {keyword: doc}).
# Rebuilt lazily the next time a message is matched after any write, so the
# hot path (every group text message) does a single regex search instead of
# looping over every stored filter and calling re.search() on each one
# (the original approach), which is O(#filters) per message.
_cache: Dict[int, Tuple[Optional["re.Pattern"], Dict[str, dict]]] = {}


def _invalidate(chat_id: int) -> None:
    _cache.pop(chat_id, None)


async def add_filter(
    chat_id: int,
    keyword: str,
    reply_text: str,
    buttons: list,
    file_id: Optional[str],
    file_type: Optional[str],
    alerts: list,
    created_by: int,
) -> None:
    keyword = keyword.strip().lower()
    doc = {
        "chat_id": chat_id,
        "keyword": keyword,
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


async def get_all_keywords(chat_id: int) -> List[str]:
    cursor = filters_col.find({"chat_id": chat_id}, {"keyword": 1}).sort("keyword", 1)
    return [doc["keyword"] async for doc in cursor]


async def count_filters(chat_id: int) -> int:
    return await filters_col.count_documents({"chat_id": chat_id})


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
    # Longest keyword first so, e.g., "help me" (if ever stored) would take
    # priority over a shorter overlapping "help" -- mirrors the original
    # bot's `reversed(sorted(keywords, key=len))` ordering.
    ordered = sorted(by_keyword.keys(), key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in ordered)
    pattern = re.compile(
        r"(?:^|\s|[^\w])(" + alternation + r")(?:$|\s|[^\w])",
        flags=re.IGNORECASE,
    )
    return pattern, by_keyword


async def match_filter(chat_id: int, text: str) -> Optional[dict]:
    """Return the filter document whose keyword matches `text`, or None."""
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
    if not m:
        return None

    matched = m.group(1).lower()
    return by_keyword.get(matched)


async def total_stats() -> Tuple[int, int]:
    """Returns (number of chats with at least one filter, total filter count)."""
    chats = len(await filters_col.distinct("chat_id"))
    total = await filters_col.count_documents({})
    return chats, total


async def export_filters(chat_id: int) -> List[dict]:
    cursor = filters_col.find({"chat_id": chat_id}, {"_id": 0})
    return [doc async for doc in cursor]


async def import_filters(chat_id: int, docs: List[dict]) -> int:
    imported = 0
    for doc in docs:
        keyword = str(doc.get("keyword", "")).strip().lower()
        if not keyword:
            continue
        await add_filter(
            chat_id=chat_id,
            keyword=keyword,
            reply_text=doc.get("reply_text", ""),
            buttons=doc.get("buttons", []),
            file_id=doc.get("file_id"),
            file_type=doc.get("file_type"),
            alerts=doc.get("alerts", []),
            created_by=doc.get("created_by", 0),
        )
        imported += 1
    return imported
