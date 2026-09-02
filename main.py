import asyncio
import logging

from pyrogram import Client, idle

from bot.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger("bot")


async def _run_web_server():
    """Bind the optional HTTP health endpoint for hosting platforms."""
    if not Config.ENABLE_WEB_SERVER:
        return None
    try:
        from aiohttp import web
    except ImportError:
        logger.warning("aiohttp not installed; skipping health-check web server.")
        return None

    async def health(_request):
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    logger.info("Health-check web server listening on port %s", Config.PORT)
    return runner


async def main():
    Config.validate()

    from bot.database.db import check_connection, ensure_indexes

    if not await check_connection():
        raise SystemExit("Could not reach MongoDB with the configured DATABASE_URI. Check the connection string.")
    await ensure_indexes()
    logger.info("MongoDB connected and indexes ensured.")

    app = Client(
        "filterbot",
        bot_token=Config.TG_BOT_TOKEN,
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        plugins=dict(root="bot/handlers"),
        workers=Config.WORKERS,
        # Bot sessions do not need a persistent local session file. Keeping the
        # Telegram session in RAM removes unnecessary disk usage and cleanup.
        in_memory=True,
    )

    web_runner = await _run_web_server()

    async with app:
        me = await app.get_me()
        logger.info("Bot started as @%s (id=%s)", me.username, me.id)
        try:
            await idle()
        finally:
            if web_runner:
                await web_runner.cleanup()
            logger.info("Shutting down.")


if __name__ == "__main__":
    asyncio.run(main())
