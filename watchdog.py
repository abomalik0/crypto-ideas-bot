import time
import logging
from telegram import Bot

logger = logging.getLogger(__name__)

def watchdog_loop():
    """
    Watchdog loop to monitor the health of the bot.
    """
    logger.info("Watchdog loop started.")
    while True:
        try:
            bot = Bot(token=config.BOT_TOKEN)
            me = bot.get_me()
            logger.debug(f"Bot is alive as @{me.username}")
        except Exception as e:
            logger.exception("Watchdog error: %s", e)

        time.sleep(config.WATCHDOG_INTERVAL)
