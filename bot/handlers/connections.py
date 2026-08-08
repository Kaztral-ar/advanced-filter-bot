import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config
from bot.database.connections import add_connection, all_connections, delete_connection, if_active
from bot.handlers.utils import is_auth

logger = logging.getLogger(__name__)


@Client.on_message((filters.private | filters.group) & filters.command(Config.CONNECT_COMMAND))
async def addconnection(client: Client, message):
    user_id = message.from_user.id
    chat_type = message.chat.type

    if chat_type == ChatType.PRIVATE:
        try:
            _, group_id = message.text.split(" ", 1)
            group_id = group_id.strip()
        except ValueError:
            await message.reply_text(
                "<b>Enter in correct format!</b>\n\n"
                f"<code>/{Config.CONNECT_COMMAND} groupid</code>\n\n"
                "<i>Get your Group id by adding this bot to your group and using <code>/id</code></i>",
                quote=True,
            )
            return
        if not (group_id.lstrip("-").isdigit()):
            await message.reply_text("That doesn't look like a valid group ID.", quote=True)
            return
        group_id = int(group_id)
    elif chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        group_id = message.chat.id
    else:
        return

    try:
        member = await client.get_chat_member(group_id, user_id)
        if not (member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) or is_auth(user_id)):
            await message.reply_text("You should be an admin in the given group!", quote=True)
            return
    except Exception as e:  # noqa: BLE001
        logger.info("connect: membership check failed for %s: %s", group_id, e)
        await message.reply_text(
            "Invalid Group ID!\n\nIf correct, make sure I'm present in your group!!", quote=True
        )
        return

    try:
        me = await client.get_chat_member(group_id, "me")
        if me.status != ChatMemberStatus.ADMINISTRATOR:
            await message.reply_text("Add me as an admin in the group first.", quote=True)
            return

        chat = await client.get_chat(group_id)
        connected = await add_connection(str(group_id), str(user_id))
        if connected:
            await message.reply_text(
                f"Successfully connected to **{chat.title}**\nNow manage your group from my PM!",
                quote=True,
                parse_mode="md",
            )
            if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
                try:
                    await client.send_message(user_id, f"Connected to **{chat.title}**!", parse_mode="md")
                except Exception:  # noqa: BLE001
                    await message.reply_text(
                        "I couldn't message you in PM -- start a chat with me first (tap my name and hit Start).",
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
            safe_title = chat.title.replace(":", "")
            active = await if_active(str(user_id), group_id)
            label = f"{safe_title}{' - ACTIVE' if active else ''}"
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"groupcb:{group_id}:{safe_title}:{active}")]
            )
        except Exception:
            continue

    if buttons:
        await message.reply_text(
            "Your connected group details:", reply_markup=InlineKeyboardMarkup(buttons), quote=True
        )
    else:
        await message.reply_text("None of your connected groups could be loaded right now.", quote=True)
