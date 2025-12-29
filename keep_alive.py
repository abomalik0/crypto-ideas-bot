import time
import logging
import requests
from config import KEEP_ALIVE_URL, KEEP_ALIVE_INTERVAL

logger = logging.getLogger(__name__)

def keep_alive_loop():
    """
    Ping the server to prevent it from going to sleep.
    """
    logger.info("Keep-alive loop started.")
    while True:
        try:
            resp = requests.get(KEEP_ALIVE_URL, timeout=10)
            if resp.status_code == 200:
                logger.debug("Keep-alive ping successful.")
            else:
                logger.warning("Keep-alive ping failed.")
        except Exception as e:
            logger.exception("Keep-alive error: %s", e)

        time.sleep(KEEP_ALIVE_INTERVAL)
