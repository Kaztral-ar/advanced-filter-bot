import io
import logging
import time
from typing import Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Config
from bot.database import filters as filters_db, users as users_db
from bot.database.connections import active_connection
from bot.handlers.utils import (
    CALLBACK_DATA_MAX_BYTES,
    build_markup,
    is_chat_admin,
    parse_buttons,
    split_quotes,
)

logger = logging.getLogger(__name__)

MEDIA_TYPES = ("document", "video", "photo", "audio", "animation", "sticker", "voice", "video_note")

# Very small per-chat cooldown so a misconfigured script (or a rogue admin)
# can't hammer /add and blow through Mongo's write capacity. Not meant to
# replace real rate limiting, just a sane floor.
_last_add_at = {}


async def _resolve_target_chat(client: Client, message: Message) -> Tuple[Optional[int], Optional[str]]:
    """Work out which group a command should apply to, handling the
    PM-via-/connect flow as well as direct group usage. Returns
    (chat_id, chat_title) or (None, None) if it already replied with an error.
    """
    chat_type = message.chat.type
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return message.chat.id, message.chat.title

    if chat_type != ChatType.PRIVATE:
        return None, None

    grp_id = await active_connection(str(message.from_user.id))
    if grp_id is None:
        await message.reply_text(
            "I'm not connected to any group! Use /connect groupid, or run this command inside a group.",
            quote=True,
        )
        return None, None
    try:
        chat = await client.get_chat(grp_id)
    except Exception:
        await message.reply_text("Make sure I'm still a member of that group!", quote=True)
        return None, None
    return grp_id, chat.title


def _extract_media(message: Message) -> Tuple[Optional[str], Optional[str]]:
    """Return (file_id, file_type) for the first media kind found on message, or (None, None)."""
    for kind in MEDIA_TYPES:
        media = getattr(message, kind, None)
        if media is not None:
            return media.file_id, kind
    return None, None


@Client.on_message(filters.command(Config.ADD_FILTER_CMD))
async def addfilter(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return

    if not await is_chat_admin(client, grp_id, message.from_user.id):
        return

    now = time.time()
    if now - _last_add_at.get(grp_id, 0) < Config.FILTER_COOLDOWN_SECONDS:
        await message.reply_text("Slow down a little, try again in a second.", quote=True)
        return
    _last_add_at[grp_id] = now

    args = message.text.html.split(None, 1)
    if len(args) < 2:
        await message.reply_text(
            f"Command incomplete. Usage:\n<code>/{Config.ADD_FILTER_CMD} keyword reply text</code>\n"
            f"or reply to a message with <code>/{Config.ADD_FILTER_CMD} keyword</code>",
            quote=True,
        )
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
        caption_or_text = reply.caption.html if (fid and reply.caption) else (
            reply.text.html if reply.text else ""
        )
        source_text = caption_or_text or (extracted[1] if len(extracted) >= 2 else "")

        if reply.reply_markup and getattr(reply.reply_markup, "inline_keyboard", None):
            # Copying an existing message's own inline keyboard: preserve URL
            # buttons as-is; alert-style buttons can't be reconstructed from
            # a rendered keyboard, so plain text buttons are dropped rather
            # than silently producing broken callback_data.
            buttons = [
                [{"text": b.text, "url": b.url} for b in row if b.url]
                for row in reply.reply_markup.inline_keyboard
            ]
            buttons = [row for row in buttons if row]
            reply_text = source_text
        else:
            reply_text, buttons, alerts = parse_buttons(source_text)

        file_id, file_type = fid, ftype
    else:
        reply_text, buttons, alerts = parse_buttons(extracted[1])
        if not reply_text and not buttons:
            await message.reply_text(
                "You cannot have buttons alone, give some text to go with it!", quote=True
            )
            return

    # Alert-button callback_data is `alrt:{i}:{keyword}` -- refuse keywords
    # that would blow the 64-byte Telegram limit instead of silently
    # truncating and creating a button that fires the wrong alert.
    if alerts:
        for kw in [k.strip() for k in raw_keywords.split("|") if k.strip()]:
            if len(f"alrt:{len(alerts) - 1}:{kw}".encode()) > CALLBACK_DATA_MAX_BYTES:
                await message.reply_text(
                    f"Keyword `{kw}` is too long to use with alert buttons. "
                    "Use a shorter keyword or a URL button instead.",
                    quote=True,
                    parse_mode="md",
                )
                return

    keywords = [k.strip() for k in raw_keywords.split("|") if k.strip()]
    if not keywords:
        await message.reply_text("Give at least one keyword!", quote=True)
        return

    if Config.MAX_FILTERS_PER_CHAT:
        existing = await filters_db.count_filters(grp_id)
        new_count = sum(1 for k in keywords if not await filters_db.get_filter(grp_id, k))
        if existing + new_count > Config.MAX_FILTERS_PER_CHAT:
            await message.reply_text(
                f"This chat has hit its limit of {Config.MAX_FILTERS_PER_CHAT} filters.",
                quote=True,
            )
            return

    for kw in keywords:
        await filters_db.add_filter(
            chat_id=grp_id,
            keyword=kw,
            reply_text=reply_text,
            buttons=buttons,
            file_id=file_id,
            file_type=file_type,
            alerts=alerts,
            created_by=message.from_user.id,
        )

    added = ", ".join(f"`{k}`" for k in keywords)
    await message.reply_text(f"Filter {added} added in **{title}**", quote=True, parse_mode="md")


@Client.on_message(filters.command("viewfilters"))
async def get_all(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return

    if not await is_chat_admin(client, grp_id, message.from_user.id):
        return

    keywords = await filters_db.get_all_keywords(grp_id)
    count = len(keywords)

    if not count:
        await message.reply_text(f"There are no active filters in **{title}**", quote=True, parse_mode="md")
        return

    filterlist = f"Total number of filters in **{title}** : {count}\n\n"
    filterlist += "\n".join(f" × `{k}`" for k in keywords)

    if len(filterlist) > 4096:
        with io.BytesIO(filterlist.replace("`", "").encode()) as f:
            f.name = "keywords.txt"
            await message.reply_document(document=f, quote=True)
        return

    await message.reply_text(text=filterlist, quote=True, parse_mode="md")


@Client.on_message(filters.command(Config.DELETE_FILTER_CMD))
async def deletefilter(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return

    if not await is_chat_admin(client, grp_id, message.from_user.id):
        return

    try:
        _, text = message.text.split(" ", 1)
    except ValueError:
        await message.reply_text(
            "<i>Mention the filter name(s) to delete, space-separated.</i>\n\n"
            f"<code>/{Config.DELETE_FILTER_CMD} filtername</code>\n\n"
            "Use /viewfilters to see all available filters",
            quote=True,
        )
        return

    keywords = [k.strip().lower() for k in text.split() if k.strip()]
    deleted, missing = [], []
    for kw in keywords:
        if await filters_db.delete_filter(grp_id, kw):
            deleted.append(kw)
        else:
            missing.append(kw)

    parts = []
    if deleted:
        parts.append("Deleted: " + ", ".join(f"`{k}`" for k in deleted))
    if missing:
        parts.append("Not found: " + ", ".join(f"`{k}`" for k in missing))
    await message.reply_text("\n".join(parts) or "Nothing to delete.", quote=True, parse_mode="md")


@Client.on_message(filters.command(Config.DELETE_ALL_CMD))
async def delallconfirm(client: Client, message: Message):
    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return

    is_creator = False
    try:
        member = await client.get_chat_member(grp_id, message.from_user.id)
        is_creator = member.status == ChatMemberStatus.OWNER
    except Exception:
        pass

    if is_creator or str(message.from_user.id) in Config.AUTH_USERS:
        await message.reply_text(
            f"This will delete all filters from '{title}'.\nDo you want to continue?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text="YES", callback_data=f"delallconfirm:{grp_id}:{title}")],
                    [InlineKeyboardButton(text="CANCEL", callback_data="delallcancel")],
                ]
            ),
            quote=True,
        )


@Client.on_message(filters.group & filters.text)
async def give_filter(client: Client, message: Message):
    group_id = message.chat.id
    doc = await filters_db.match_filter(group_id, message.text)

    if doc:
        reply_text = (doc.get("reply_text") or "").replace("\\n", "\n").replace("\\t", "\t")
        markup = build_markup(doc.get("buttons") or [], group_id, doc["keyword"])
        try:
            if doc.get("file_id"):
                await message.reply_cached_media(
                    doc["file_id"], caption=reply_text, reply_markup=markup, quote=True
                )
            elif reply_text:
                await message.reply_text(
                    reply_text, disable_web_page_preview=True, reply_markup=markup, quote=True
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to deliver filter '%s' in %s: %s", doc["keyword"], group_id, e)

    if Config.SAVE_USER:
        try:
            await users_db.add_user(
                str(message.from_user.id),
                str(message.from_user.username),
                f"{message.from_user.first_name} {(message.from_user.last_name or '')}".strip(),
                str(message.from_user.dc_id),
            )
        except Exception:  # noqa: BLE001
            pass


@Client.on_message(filters.command("exportfilters"))
async def export_cmd(client: Client, message: Message):
    import json

    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return
    if not await is_chat_admin(client, grp_id, message.from_user.id):
        return

    docs = await filters_db.export_filters(grp_id)
    if not docs:
        await message.reply_text("No filters to export.", quote=True)
        return

    data = json.dumps(docs, indent=2, default=str).encode()
    with io.BytesIO(data) as f:
        f.name = f"filters_{grp_id}.json"
        await message.reply_document(
            f, caption=f"Exported {len(docs)} filter(s) from **{title}**", quote=True, parse_mode="md"
        )


@Client.on_message(filters.command("importfilters"))
async def import_cmd(client: Client, message: Message):
    import json
    import os

    grp_id, title = await _resolve_target_chat(client, message)
    if grp_id is None:
        return
    if not await is_chat_admin(client, grp_id, message.from_user.id):
        return

    if not (message.reply_to_message and message.reply_to_message.document):
        await message.reply_text(
            "Reply to a filters JSON file (from /exportfilters) with /importfilters.", quote=True
        )
        return

    doc = message.reply_to_message.document
    if doc.file_size and doc.file_size > 5 * 1024 * 1024:
        await message.reply_text("File too large (max 5 MB).", quote=True)
        return

    path = await client.download_media(doc)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, list):
            raise ValueError("Expected a JSON list of filter objects")
        count = await filters_db.import_filters(grp_id, payload)
        await message.reply_text(f"Imported {count} filter(s) into **{title}**", quote=True, parse_mode="md")
    except Exception as e:  # noqa: BLE001
        await message.reply_text(f"Import failed: {e}", quote=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
