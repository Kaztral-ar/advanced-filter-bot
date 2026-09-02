import asyncio
import io
import json
import logging
import os
import time
from typing import Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Config
from bot.database import filters as filters_db, users as users_db
from bot.database.connections import active_connection
from bot.handlers.utils import build_markup, is_chat_admin, parse_buttons, split_quotes

logger = logging.getLogger(__name__)
MEDIA_TYPES = ("document", "video", "photo", "audio", "animation", "sticker", "voice", "video_note")
_last_add_at = {}


async def _resolve_target_chat(client: Client, message: Message) -> Tuple[Optional[int], Optional[str]]:
    chat_type = message.chat.type
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return message.chat.id, message.chat.title
    if chat_type != ChatType.PRIVATE:
        return None, None
    grp_id = await active_connection(str(message.from_user.id))
    if grp_id is None:
        await message.reply_text("I'm not connected to any group! Use /connect groupid, or run this command inside a group.", quote=True)
        return None, None
    try:
        chat = await client.get_chat(grp_id)
    except Exception:
        await message.reply_text("Make sure I'm still a member of that group!", quote=True)
        return None, None
    return grp_id, chat.title


def _extract_media(message: Message) -> Tuple[Optional[str], Optional[str]]:
    for kind in MEDIA_TYPES:
        media = getattr(message, kind, None)
        if media is not None:
            return media.file_id, kind
    return None, None


@Client.on_message(filters.command(Config.ADD_FILTER_CMD))
async def addfilter(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None or not await is_chat_admin(client, grp_id, message.from_user.id):
        return
    now = time.time()
    if now - _last_add_at.get(grp_id, 0) < Config.FILTER_COOLDOWN_SECONDS:
        await message.reply_text("Slow down a little, try again in a second.", quote=True)
        return
    _last_add_at[grp_id] = now
    args = message.text.html.split(None, 1)
    if len(args) < 2:
        await message.reply_text(f"Command incomplete. Usage:\n<code>/{Config.ADD_FILTER_CMD} keyword reply text</code>\nor reply to a message with <code>/{Config.ADD_FILTER_CMD} keyword</code>", quote=True)
        return
    extracted = split_quotes(args[1])
    raw_keywords = extracted[0].lower()
    if not message.reply_to_message and len(extracted) < 2:
        await message.reply_text("Add some content to save your filter!", quote=True)
        return
    reply_text, buttons, alerts, file_id, file_type = "", [], [], None, None
    if message.reply_to_message:
        reply = message.reply_to_message
        fid, ftype = _extract_media(reply)
        caption_or_text = reply.caption.html if (fid and reply.caption) else (reply.text.html if reply.text else "")
        source_text = caption_or_text or (extracted[1] if len(extracted) >= 2 else "")
        if reply.reply_markup and getattr(reply.reply_markup, "inline_keyboard", None):
            buttons = [[{"text": b.text, "url": b.url} for b in row if b.url] for row in reply.reply_markup.inline_keyboard]
            buttons = [row for row in buttons if row]
            reply_text = source_text
        else:
            reply_text, buttons, alerts = parse_buttons(source_text)
        file_id, file_type = fid, ftype
    else:
        reply_text, buttons, alerts = parse_buttons(extracted[1])
        if not reply_text and not buttons:
            await message.reply_text("You cannot have buttons alone, give some text to go with it!", quote=True)
            return
    keywords = [k.strip() for k in raw_keywords.split("|") if k.strip()]
    if not keywords:
        await message.reply_text("Give at least one keyword!", quote=True)
        return
    if Config.MAX_FILTERS_PER_CHAT:
        existing = await filters_db.count_filters(grp_id)
        new_count = await filters_db.count_new_filters(grp_id, keywords)
        if existing + new_count > Config.MAX_FILTERS_PER_CHAT:
            await message.reply_text(f"This chat has hit its limit of {Config.MAX_FILTERS_PER_CHAT} filters.", quote=True)
            return
    for kw in keywords:
        await filters_db.add_filter(grp_id, kw, reply_text, buttons, file_id, file_type, alerts, message.from_user.id)
    await message.reply_text(f"Filter {', '.join(f'`{k}`' for k in keywords)} added in **{title}**", quote=True, parse_mode="md")


@Client.on_message(filters.command("viewfilters"))
async def get_all(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None or not await is_chat_admin(client, grp_id, message.from_user.id): return
    keywords = await filters_db.get_all_keywords(grp_id)
    if not keywords:
        await message.reply_text(f"There are no active filters in **{title}**", quote=True, parse_mode="md")
        return
    filterlist = f"Total number of filters in **{title}** : {len(keywords)}\n\n" + "\n".join(f" × `{k}`" for k in keywords)
    if len(filterlist) > 4096:
        with io.BytesIO(filterlist.replace("`", "").encode()) as f:
            f.name = "keywords.txt"
            await message.reply_document(document=f, quote=True)
    else:
        await message.reply_text(filterlist, quote=True, parse_mode="md")


@Client.on_message(filters.command(Config.DELETE_FILTER_CMD))
async def deletefilter(client: Client, message: Message):
    grp_id, _ = await _resolve_target_chat(client, message)
    if grp_id is None or not await is_chat_admin(client, grp_id, message.from_user.id): return
    try:
        _, text = message.text.split(" ", 1)
    except ValueError:
        await message.reply_text("<i>Mention the filter name(s) to delete, space-separated.</i>\n\n" f"<code>/{Config.DELETE_FILTER_CMD} filtername</code>\n\nUse /viewfilters to see all available filters", quote=True)
        return
    deleted, missing = [], []
    for kw in [k.strip().lower() for k in text.split() if k.strip()]:
        if await filters_db.delete_filter(grp_id, kw): deleted.append(kw)
        else: missing.append(kw)
    parts = []
    if deleted: parts.append("Deleted: " + ", ".join(f"`{k}`" for k in deleted))
    if missing: parts.append("Not found: " + ", ".join(f"`{k}`" for k in missing))
    await message.reply_text("\n".join(parts) or "Nothing to delete.", quote=True, parse_mode="md")


@Client.on_message(filters.command(Config.DELETE_ALL_CMD))
async def delallconfirm(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None: return
    try:
        member = await client.get_chat_member(grp_id, message.from_user.id)
        is_creator = member.status == ChatMemberStatus.OWNER
    except Exception:
        is_creator = False
    if is_creator or str(message.from_user.id) in Config.AUTH_USERS:
        await message.reply_text(f"This will delete all filters from '{title}'.\nDo you want to continue?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="YES", callback_data=f"delallconfirm:{grp_id}:{title}")], [InlineKeyboardButton(text="CANCEL", callback_data="delallcancel")]]), quote=True)


@Client.on_message(filters.group & filters.text)
async def give_filter(client: Client, message: Message):
    doc = await filters_db.match_filter(message.chat.id, message.text)
    if doc:
        reply_text = (doc.get("reply_text") or "").replace("\\n", "\n").replace("\\t", "\t")
        markup = build_markup(doc.get("buttons") or [], message.chat.id, doc["keyword"])
        try:
            if doc.get("file_id"):
                await message.reply_cached_media(doc["file_id"], caption=reply_text, reply_markup=markup, quote=True)
            elif reply_text:
                await message.reply_text(reply_text, disable_web_page_preview=True, reply_markup=markup, quote=True)
        except Exception as e:
            logger.warning("Failed to deliver filter '%s' in %s: %s", doc["keyword"], message.chat.id, e)
    if Config.SAVE_USER:
        try:
            await users_db.add_user(str(message.from_user.id), str(message.from_user.username), f"{message.from_user.first_name} {(message.from_user.last_name or '')}".strip(), str(message.from_user.dc_id))
        except Exception:
            pass


@Client.on_message(filters.command("exportfilters"))
async def export_cmd(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None or not await is_chat_admin(client, grp_id, message.from_user.id): return
    docs = await filters_db.export_filters(grp_id)
    if not docs:
        await message.reply_text("No filters to export.", quote=True); return
    data = json.dumps(docs, indent=2, default=str).encode()
    with io.BytesIO(data) as f:
        f.name = f"filters_{grp_id}.json"
        await message.reply_document(f, caption=f"Exported {len(docs)} filter(s) from **{title}**", quote=True, parse_mode="md")


@Client.on_message(filters.command("importfilters"))
async def import_cmd(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None or not await is_chat_admin(client, grp_id, message.from_user.id): return
    if not (message.reply_to_message and message.reply_to_message.document):
        await message.reply_text("Reply to a filters JSON file (from /exportfilters) with /importfilters.", quote=True); return
    doc = message.reply_to_message.document
    if doc.file_size and doc.file_size > 5 * 1024 * 1024:
        await message.reply_text("File too large (max 5 MB).", quote=True); return
    path = await client.download_media(doc)
    try:
        def read_json_file(p):
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        payload = await asyncio.to_thread(read_json_file, path)
        if not isinstance(payload, list):
            raise ValueError("Expected a JSON list of filter objects")
        if Config.MAX_FILTERS_PER_CHAT:
            candidates = [str(x.get("keyword", "")).strip().lower() for x in payload if isinstance(x, dict)]
            candidates = list(dict.fromkeys(k for k in candidates if k))
            existing = await filters_db.count_filters(grp_id)
            new_count = await filters_db.count_new_filters(grp_id, candidates)
            if existing + new_count > Config.MAX_FILTERS_PER_CHAT:
                await message.reply_text(f"Import would exceed this chat's limit of {Config.MAX_FILTERS_PER_CHAT} filters.", quote=True)
                return
        count = await filters_db.import_filters(grp_id, payload)
        await message.reply_text(f"Imported {count} filter(s) into **{title}**", quote=True, parse_mode="md")
    except Exception as e:
        logger.warning("Filter import failed in %s: %s", grp_id, e)
        await message.reply_text("Import failed: invalid or unsupported filter JSON.", quote=True)
    finally:
        if path:
            try: os.remove(path)
            except OSError: pass
