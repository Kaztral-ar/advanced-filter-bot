import asyncio
import logging
import math
import shutil
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config
from bot.database import filters as filters_db, users as users_db
from bot.handlers.utils import hhmmss, humanbytes, is_auth
from bot.messages import Messages

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("id") & (filters.private | filters.group))
async def showid(client: Client, message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(f"Your ID : `{message.chat.id}`", parse_mode="md", quote=True)
        return

    reply_id = ""
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_id = f"Replied User ID : `{message.reply_to_message.from_user.id}`"

    await message.reply_text(
        f"Your ID : `{message.from_user.id}`\nThis Group ID : `{message.chat.id}`\n\n{reply_id}",
        parse_mode="md",
        quote=True,
    )


@Client.on_message(filters.command("info") & (filters.private | filters.group))
async def showinfo(client: Client, message):
    target_id = None
    parts = message.text.split(" ", 1)
    if len(parts) > 1 and parts[1].strip():
        # Any integer is a potentially valid Telegram user id -- the original
        # code rejected ids that weren't exactly 9-10 digits, which breaks on
        # both small legacy ids and the newer, longer ids Telegram now issues.
        try:
            target_id = int(parts[1].strip())
        except ValueError:
            await message.reply_text("__Enter a valid USER ID__", quote=True, parse_mode="md")
            return

    if target_id is not None:
        name = username = dcid = None
        if Config.SAVE_USER:
            name, username, dcid = await users_db.find_user(str(target_id))
        if not name:
            try:
                user = await client.get_users(target_id)
                name = f"{user.first_name}{(user.last_name or '')}"
                username = user.username
                dcid = user.dc_id
            except Exception:
                await message.reply_text("__User details not found!__", quote=True, parse_mode="md")
                return
        uid = target_id
    elif message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        name = f"{u.first_name}{(u.last_name or '')}"
        uid, username, dcid = u.id, u.username, u.dc_id
    else:
        u = message.from_user
        name = f"{u.first_name}{(u.last_name or '')}"
        uid, username, dcid = u.id, u.username, u.dc_id

    user_name = f"@{username}" if username else "none"

    await message.reply_text(
        f"<b>Name</b> : {name}\n\n"
        f"<b>User ID</b> : <code>{uid}</code>\n\n"
        f"<b>Username</b> : {user_name}\n\n"
        f"<b>Permanent link</b> : <a href='tg://user?id={uid}'>Click here!</a>\n\n"
        f"<b>DC ID</b> : {dcid}\n\n",
        quote=True,
        parse_mode="html",
    )


@Client.on_message((filters.private | filters.group) & filters.command("status"))
async def bot_status(client: Client, message):
    if not is_auth(message.from_user.id):
        return

    chats, total_filters = await filters_db.total_stats()

    userstats = ""
    if Config.SAVE_USER:
        users = await users_db.all_users()
        userstats = f"> __**{users} users have interacted with your bot!**__\n\n"

    quota_details = ""
    if Config.HEROKU_API_KEY:
        quota_details = await _heroku_quota()

    uptime = hhmmss(time.time() - Config.BOT_START_TIME)

    disk = ""
    try:
        t, u, f = shutil.disk_usage(".")
        disk = (
            "\n**Disk Details**\n\n"
            f"> USED  :  {humanbytes(u)} / {humanbytes(t)}\n"
            f"> FREE  :  {humanbytes(f)}\n\n"
        )
    except Exception:
        pass

    await message.reply_text(
        "**Current status of your bot!**\n\n"
        f"> __**{total_filters}** filters across **{chats}** chats__\n\n"
        f"{userstats}"
        f"> __BOT Uptime__ : **{uptime}**\n\n"
        f"{quota_details}"
        f"{disk}",
        quote=True,
        parse_mode="md",
    )


async def _heroku_quota() -> str:
    try:
        import heroku3
        import requests

        server = heroku3.from_key(Config.HEROKU_API_KEY)
        account_id = server.account().id
        headers = {
            "Authorization": f"Bearer {Config.HEROKU_API_KEY}",
            "Accept": "application/vnd.heroku+json; version=3.account-quotas",
        }
        resp = await asyncio.to_thread(
            requests.get,
            f"https://api.heroku.com/accounts/{account_id}/actions/get-quota",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        result = resp.json()
        total_quota, quota_used = result["account_quota"], result["quota_used"]
        quota_left = total_quota - quota_used
        total_h = math.floor(total_quota / 3600)
        used_h = math.floor(quota_used / 3600)
        left_h = math.floor(quota_left / 3600)
        days = math.floor(left_h / 24)
        used_pct = math.floor(quota_used / total_quota * 100)
        left_pct = math.floor(quota_left / total_quota * 100)
        return (
            "\n**Heroku Account Status**\n\n"
            f"> __{total_h} hours of free dyno quota each month.__\n"
            f"> Used: **{used_h} hours** ({used_pct}%)\n"
            f"> Remaining: **{left_h} hours** ({left_pct}%) -- approx **{days} days**\n\n"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Heroku quota check failed: %s", e)
        return ""


@Client.on_message(filters.command("start") & filters.private)
async def start(client: Client, message):
    await message.reply_text(
        text=Messages.START_MSG.format(message.from_user.mention),
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Command Help", callback_data="help_data")]]),
        quote=True,
    )
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


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message):
    await message.reply_text(
        text=Messages.HELP_MSG,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("About Me", callback_data="about_data"),
                ],
            ]
        ),
        quote=True,
    )


@Client.on_message(filters.command("about") & filters.private)
async def about(client: Client, message):
    await message.reply_text(
        text=Messages.ABOUT_MSG,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("SOURCE CODE", url="https://github.com/Kaztral-ar")],
                [
                    InlineKeyboardButton("BACK", callback_data="help_data"),
                    InlineKeyboardButton("CLOSE", callback_data="close_data"),
                ],
            ]
        ),
        quote=True,
    )


@Client.on_message(filters.command("ban") & filters.private)
async def ban_cmd(client: Client, message):
    if not is_auth(message.from_user.id):
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.reply_text("Usage: `/ban user_id [reason]`", quote=True, parse_mode="md")
        return
    uid, reason = parts[1].strip(), (parts[2].strip() if len(parts) > 2 else "")
    await users_db.ban_user(uid, reason)
    await message.reply_text(f"Banned `{uid}` from using this bot.", quote=True, parse_mode="md")


@Client.on_message(filters.command("unban") & filters.private)
async def unban_cmd(client: Client, message):
    if not is_auth(message.from_user.id):
        return
    parts = message.text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.reply_text("Usage: `/unban user_id`", quote=True, parse_mode="md")
        return
    uid = parts[1].strip()
    ok = await users_db.unban_user(uid)
    await message.reply_text(
        f"Unbanned `{uid}`." if ok else f"`{uid}` wasn't banned.", quote=True, parse_mode="md"
    )


@Client.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client: Client, message):
    if not is_auth(message.from_user.id):
        return
    if not Config.SAVE_USER:
        await message.reply_text("Enable SAVE_USER to collect a user list before broadcasting.", quote=True)
        return
    if not message.reply_to_message:
        await message.reply_text("Reply to the message you want to broadcast with /broadcast.", quote=True)
        return

    user_ids = await users_db.all_user_ids()
    status = await message.reply_text(f"Broadcasting to {len(user_ids)} users...", quote=True)

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await message.reply_to_message.copy(int(uid))
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # stay well under Telegram's flood limits

    await status.edit_text(f"Broadcast complete.\nSent: {sent}\nFailed: {failed}")
