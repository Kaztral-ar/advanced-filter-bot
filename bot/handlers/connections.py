import logging
import re

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config
from bot.database.connections import add_connection, all_connections, delete_connection, if_active
from bot.handlers.utils import is_auth

logger = logging.getLogger(__name__)


_GROUP_REF_RE = re.compile(
    r"^(?:https?://)?t\.me/(?:c/)?([A-Za-z0-9_+-]+)(?:/\d+)?/?$",
    re.IGNORECASE,
)


def _parse_group_reference(value: str):
    """Normalize a Telegram group ID, @username, or t.me reference."""
    value = value.strip()
    if not value:
        return None

    if value.lstrip("-").isdigit():
        return int(value)

    match = _GROUP_REF_RE.fullmatch(value)
    if match:
        value = match.group(1)

    if value.startswith("@"):
        value = value[1:]

    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        return value
    return None


@Client.on_message((filters.private | filters.group) & filters.command(Config.CONNECT_COMMAND))
async def addconnection(client: Client, message):
    user_id = message.from_user.id
    chat_type = message.chat.type

    if chat_type == ChatType.PRIVATE:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply_text(
                "<b>How to connect a group</b>\n\n"
                f"<code>/{Config.CONNECT_COMMAND} -1001234567890</code>\n"
                f"<code>/{Config.CONNECT_COMMAND} @groupusername</code>\n"
                f"<code>/{Config.CONNECT_COMMAND} https://t.me/groupusername</code>\n\n"
                "For private groups, use the numeric group ID.\n"
                "You must be an admin, and I must also be an admin in the group.",
                quote=True,
            )
            return

        group_ref = _parse_group_reference(parts[1])
        if group_ref is None:
            await message.reply_text(
                "Invalid group reference. Use a numeric group ID, @username, or t.me group link.",
                quote=True,
            )
            return
    elif chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        group_ref = message.chat.id
    else:
        return

    try:
        chat = await client.get_chat(group_ref)
        if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await message.reply_text("That chat is not a group or supergroup.", quote=True)
            return
        group_id = chat.id
    except Exception as e:  # noqa: BLE001
        logger.info("connect: unable to resolve %r: %s", group_ref, e)
        await message.reply_text(
            "I couldn't find that group. For a private group, use its numeric ID and make sure I'm already in it.",
            quote=True,
        )
        return

    try:
        member = await client.get_chat_member(group_id, user_id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await message.reply_text(
                "You must be an admin or owner of the group to connect it.", quote=True
            )
            return
    except Exception as e:  # noqa: BLE001
        logger.info("connect: membership check failed for %s: %s", group_id, e)
        await message.reply_text(
            "I can't verify your admin access. Make sure I'm in the group and try again.", quote=True
        )
        return

    try:
        me = await client.get_chat_member(group_id, "me")
        if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await message.reply_text("Add me as an admin in the group first.", quote=True)
            return

        connected = await add_connection(str(group_id), str(user_id))
        if connected:
            await message.reply_text(
                f"Successfully connected to **{chat.title or 'this group'}**\n"
                "Now manage your group from my PM!",
                quote=True,
                parse_mode="md",
            )
            if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
                try:
                    await client.send_message(
                        user_id,
                        f"Connected to **{chat.title or 'this group'}**!",
                        parse_mode="md",
                    )
                except Exception:  # noqa: BLE001
                    await message.reply_text(
                        "I couldn't message you in PM. Start a chat with me first, then use /connections.",
                        quote=True,
                    )
        else:
            await message.reply_text("You're already connected to this chat!", quote=True)
    except Exception as e:  # noqa: BLE001
        logger.error("connect failed: %s", e)
        await message.reply_text("Some error occurred! Try again later.", quote=True)


@Client.on_message((filters.private | filters.group) & filters.command(Config.DISCONNECT_COMMAND))
async def deleteconnection(client: Client, message):
    user_id = message.from_user.id
    chat_type = message.chat.type

    if chat_type == ChatType.PRIVATE:
        await message.reply_text("Run /connections to view or disconnect from groups!", quote=True)
        return

    if chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    group_id = message.chat.id
    member = await client.get_chat_member(group_id, user_id)
    if not (member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) or is_auth(user_id)):
        return

    ok = await delete_connection(str(user_id), str(group_id))
    if ok:
        await message.reply_text("Successfully disconnected from this chat", quote=True)
    else:
        await message.reply_text(f"This chat isn't connected to me!\nDo /{Config.CONNECT_COMMAND} first.", quote=True)


@Client.on_message(filters.private & filters.command("connections"))
async def connections(client: Client, message):
    user_id = message.from_user.id
    group_ids = await all_connections(str(user_id))
    if not group_ids:
        await message.reply_text("There are no active connections! Connect to some groups first.", quote=True)
        return

    buttons = []
    for group_id in group_ids:
        try:
            chat = await client.get_chat(int(group_id))
            active = await if_active(str(user_id), group_id)
            label = f"{chat.title}{' - ACTIVE' if active else ''}"
            # Telegram limits callback_data to 64 bytes. Store only the group
            # id and state; the callback handler fetches the title when needed.
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"groupcb:{group_id}:{active}")]
            )
        except Exception:
            continue

    if buttons:
        await message.reply_text(
            "Your connected group details:", reply_markup=InlineKeyboardMarkup(buttons), quote=True
        )
    else:
        await message.reply_text("None of your connected groups could be loaded right now.", quote=True)
