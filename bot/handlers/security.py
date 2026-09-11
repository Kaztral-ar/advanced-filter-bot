import pyrogram
from pyrogram import Client, filters

from bot.database import users as users_db


@Client.on_message(filters.private, group=-10)
async def ban_gate(client: Client, message):
    """Block every private-chat interaction from banned users before other
    handlers get a chance to process it.
    """
    if not message.from_user:
        return
    if await users_db.is_banned(str(message.from_user.id)):
        await message.reply_text("You are banned from using this bot.")
        raise pyrogram.StopPropagation
