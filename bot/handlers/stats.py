import time

from pyrogram import Client, filters

from bot.config import Config
from bot.database import filters as filters_db
from bot.handlers.utils import hhmmss, is_auth


@Client.on_message(filters.command("stats") & (filters.private | filters.group))
async def stats(client, message):
    """Show a compact filter-bot statistics dashboard."""
    if not is_auth(message.from_user.id):
        return

    chats, total_filters = await filters_db.total_stats()
    uptime = hhmmss(time.time() - Config.BOT_START_TIME)

    await message.reply_text(
        "**📊 Filter Bot Stats**\n\n"
        f"• Filters: **{total_filters}**\n"
        f"• Chats: **{chats}**\n"
        f"• Uptime: **{uptime}**\n"
        f"• Workers: **{Config.WORKERS}**\n"
        f"• Cache chats: **{Config.FILTER_CACHE_CHATS}**",
        quote=True,
        parse_mode="md",
    )
