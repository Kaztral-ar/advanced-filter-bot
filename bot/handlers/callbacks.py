import logging

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config
from bot.database import filters as filters_db
from bot.database.connections import (
    all_connections,
    delete_connection,
    if_active,
    make_active,
    make_inactive,
)
from bot.handlers.utils import is_auth
from bot.messages import Messages

logger = logging.getLogger(__name__)


@Client.on_callback_query()
async def cb_handler(client: Client, query):
    data = query.data

    if data == "start_data":
        await query.answer()
        await query.message.edit_text(
            Messages.START_MSG.format(query.from_user.mention),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Command Help", callback_data="help_data")]]
            ),
            disable_web_page_preview=True,
        )
        return

    if data == "help_data":
        await query.answer()
        await query.message.edit_text(
            Messages.HELP_MSG,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("About Me", callback_data="about_data"),
                    ],
                ]
            ),
            disable_web_page_preview=True,
        )
        return

    if data == "about_data":
        await query.answer()
        await query.message.edit_text(
            Messages.ABOUT_MSG,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("SOURCE CODE", url="https://github.com/Kaztral-ar")],
                    [
                        InlineKeyboardButton("BACK", callback_data="help_data"),
                        InlineKeyboardButton("CLOSE", callback_data="close_data"),
                    ],
                ]
            ),
            disable_web_page_preview=True,
        )
        return

    if data == "close_data":
        await query.message.delete()
        return

    if data.startswith("delallconfirm:"):
        _, grp_id, title = data.split(":", 2)
        grp_id = int(grp_id)
        try:
            member = await client.get_chat_member(grp_id, query.from_user.id)
            authorized = member.status == ChatMemberStatus.OWNER
        except Exception:
            authorized = False
        authorized = authorized or is_auth(query.from_user.id)

        if not authorized:
            await query.answer("You need to be the group owner or an auth user to do that!", show_alert=True)
            return

        count = await filters_db.delete_all_filters(grp_id)
        await query.answer()
        await query.message.edit_text(f"Removed {count} filter(s) from **{title}**", parse_mode="md")
        return

    if data == "delallcancel":
        await query.answer()
        await query.message.delete()
        return

    if data.startswith("groupcb:"):
        await query.answer()
        _, group_id, title, act = data.split(":", 3)
        stat, cb = ("DISCONNECT", "disconnect") if act == "True" else ("CONNECT", "connectcb")

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(stat, callback_data=f"{cb}:{group_id}:{title}"),
                    InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}"),
                ],
                [InlineKeyboardButton("BACK", callback_data="backcb")],
            ]
        )
        await query.message.edit_text(
            f"Group Name : **{title}**\nGroup ID : `{group_id}`", reply_markup=keyboard, parse_mode="md"
        )
        return

    if data.startswith("connectcb:"):
        await query.answer()
        _, group_id, title = data.split(":", 2)
        ok = await make_active(str(query.from_user.id), group_id)
        await query.message.edit_text(
            f"Connected to **{title}**" if ok else "Some error occurred!", parse_mode="md"
        )
        return

    if data.startswith("disconnect:"):
        await query.answer()
        _, group_id, title = data.split(":", 2)
        ok = await make_inactive(str(query.from_user.id))
        await query.message.edit_text(
            f"Disconnected from **{title}**" if ok else "Some error occurred!", parse_mode="md"
        )
        return

    if data.startswith("deletecb:"):
        await query.answer()
        _, group_id = data.split(":", 1)
        ok = await delete_connection(str(query.from_user.id), group_id)
        await query.message.edit_text(
            "Successfully deleted connection" if ok else "Some error occurred!"
        )
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
                # Colons are stripped from the title before embedding it in
                # callback_data: the "act" flag is parsed positionally, so a
                # colon in a group's name could otherwise corrupt the split.
                safe_title = chat.title.replace(":", "")
                active = await if_active(str(query.from_user.id), group_id)
                label = f"{safe_title}{' - ACTIVE' if active else ''}"
                buttons.append(
                    [InlineKeyboardButton(text=label, callback_data=f"groupcb:{group_id}:{safe_title}:{active}")]
                )
            except Exception:
                continue

        if buttons:
            await query.message.edit_text("Your connected group details:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("alrt:"):
        _, index, keyword = data.split(":", 2)
        doc = await filters_db.get_filter(query.message.chat.id, keyword)
        if not doc or not doc.get("alerts"):
            await query.answer("This alert is no longer available.", show_alert=True)
            return
        try:
            alert = doc["alerts"][int(index)]
        except (IndexError, ValueError):
            return
        alert = alert.replace("\\n", "\n").replace("\\t", "\t")
        await query.answer(alert, show_alert=True)
        return
