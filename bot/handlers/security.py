import pyrogram
from pyrogram import Client, filters

from bot.database import users as users_db


@Client.on_message(filters.private & filters.regex(r"^/"), group=-10)
async def ban_gate(client: Client, message):
    """Runs before every other private-chat command handler (group=-10 sorts
    first). Banned users get a single notice and nothing else executes.
    """
    if not message.from_user:
        return
    if await users_db.is_banned(str(message.from_user.id)):
        await message.reply_text("You are banned from using this bot.")
        raise pyrogram.StopPropagation
