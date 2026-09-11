import logging

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import filters as filters_db
from bot.database.connections import all_connections, delete_connection, if_active, make_active, make_inactive
from bot.handlers.utils import is_auth
from bot.messages import Messages

logger = logging.getLogger(__name__)


async def _owns_connection(user_id: int, group_id: str) -> bool:
    """Verify that a callback targets a group actually connected by this user."""
    try:
        return str(group_id) in (await all_connections(str(user_id)) or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("connection ownership check failed: %s", e)
        return False


async def _group_title(client: Client, group_id: str) -> str:
    """Fetch a display-safe group title instead of embedding it in callback data."""
    try:
        chat = await client.get_chat(int(group_id))
        return chat.title or "Connected group"
    except Exception:
        return "Connected group"


@Client.on_callback_query()
async def cb_handler(client: Client, query):
    data = query.data

    if data == "start_data":
        await query.answer()
        await query.message.edit_text(Messages.START_MSG.format(query.from_user.mention),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Command Help", callback_data="help_data")]]),
            disable_web_page_preview=True)
        return

    if data == "help_data":
        await query.answer()
        await query.message.edit_text(Messages.HELP_MSG,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("About Me", callback_data="about_data")]]),
            disable_web_page_preview=True)
        return

    if data == "about_data":
        await query.answer()
        await query.message.edit_text(Messages.ABOUT_MSG,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("SOURCE CODE", url="https://github.com/Kaztral-ar")],
                [InlineKeyboardButton("BACK", callback_data="help_data"), InlineKeyboardButton("CLOSE", callback_data="close_data")],
            ]), disable_web_page_preview=True)
        return

    if data == "close_data":
        await query.message.delete()
        return

    if data.startswith("delallconfirm:"):
        _, group_id = data.split(":", 1)
        try:
            group_id_int = int(group_id)
        except ValueError:
            await query.answer("Invalid group.", show_alert=True)
            return
        if not await _owns_connection(query.from_user.id, group_id):
            await query.answer("This connection is not yours or is no longer available.", show_alert=True)
            return
        try:
            member = await client.get_chat_member(group_id_int, query.from_user.id)
            authorized = member.status == ChatMemberStatus.OWNER
        except Exception:
            authorized = False
        if not (authorized or is_auth(query.from_user.id)):
            await query.answer("You need to be the group owner or an auth user to do that!", show_alert=True)
            return
        count = await filters_db.delete_all_filters(group_id_int)
        title = await _group_title(client, group_id)
        await query.answer()
        await query.message.edit_text(f"Removed {count} filter(s) from **{title}**", parse_mode="md")
        return

    if data == "delallcancel":
        await query.answer()
        await query.message.delete()
        return

    if data.startswith("groupcb:"):
        try:
            _, group_id, act = data.split(":", 2)
        except ValueError:
            await query.answer("Invalid connection button.", show_alert=True)
            return
        if not await _owns_connection(query.from_user.id, group_id):
            await query.answer("This connection is not yours or is no longer available.", show_alert=True)
            return
        title = await _group_title(client, group_id)
        stat, cb = ("DISCONNECT", "disconnect") if act == "True" else ("CONNECT", "connectcb")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(stat, callback_data=f"{cb}:{group_id}"), InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")],
            [InlineKeyboardButton("BACK", callback_data="backcb")],
        ])
        await query.answer()
        await query.message.edit_text(f"Group Name : **{title}**\nGroup ID : `{group_id}`", reply_markup=keyboard, parse_mode="md")
        return

    if data.startswith("connectcb:"):
        _, group_id = data.split(":", 1)
        if not await _owns_connection(query.from_user.id, group_id):
            await query.answer("This connection is not yours or is no longer available.", show_alert=True)
            return
        await query.answer()
        ok = await make_active(str(query.from_user.id), group_id)
        title = await _group_title(client, group_id)
        await query.message.edit_text(f"Connected to **{title}**" if ok else "Some error occurred!", parse_mode="md")
        return

    if data.startswith("disconnect:"):
        _, group_id = data.split(":", 1)
        if not await _owns_connection(query.from_user.id, group_id):
            await query.answer("This connection is not yours or is no longer available.", show_alert=True)
            return
        await query.answer()
        ok = await make_inactive(str(query.from_user.id))
        title = await _group_title(client, group_id)
        await query.message.edit_text(f"Disconnected from **{title}**" if ok else "Some error occurred!", parse_mode="md")
        return

    if data.startswith("deletecb:"):
        _, group_id = data.split(":", 1)
        if not await _owns_connection(query.from_user.id, group_id):
            await query.answer("This connection is not yours or is no longer available.", show_alert=True)
            return
        await query.answer()
        ok = await delete_connection(str(query.from_user.id), group_id)
        await query.message.edit_text("Successfully deleted connection" if ok else "Some error occurred!")
        return

    if data == "backcb":
        await query.answer()
        group_ids = await all_connections(str(query.from_user.id))
        if not group_ids:
            await query.message.edit_text("There are no active connections! Connect to some groups first.")
            return
        buttons = []
        for group_id in group_ids:
            try:
                chat = await client.get_chat(int(group_id))
                active = await if_active(str(query.from_user.id), group_id)
                label = f"{chat.title}{' - ACTIVE' if active else ''}"
                buttons.append([InlineKeyboardButton(text=label, callback_data=f"groupcb:{group_id}:{active}")])
            except Exception:
                continue
        if buttons:
            await query.message.edit_text("Your connected group details:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("alrt:"):
        try:
            _, index_text, token = data.split(":", 2)
            index = int(index_text)
        except (ValueError, AttributeError):
            await query.answer("Invalid alert button.", show_alert=True)
            return
        doc = await filters_db.get_filter_by_alert_token(query.message.chat.id, token)
        if not doc or not doc.get("alerts"):
            await query.answer("This alert is no longer available.", show_alert=True)
            return
        try:
            alert = doc["alerts"][index]
        except (IndexError, TypeError, ValueError):
            await query.answer("This alert is no longer available.", show_alert=True)
            return
        alert = str(alert).replace("\\n", "\n").replace("\\t", "\t")
        await query.answer(alert, show_alert=True)
        return
