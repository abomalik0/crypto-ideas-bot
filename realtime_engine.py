import time
from config import REALTIME_ENGINE_INTERVAL
import logging
from analysis_engine import get_market_metrics_cached

logger = logging.getLogger(__name__)

def realtime_engine_loop():
    """
    Loop for updating the market metrics cache in real-time.
    """
    logger.info("Realtime engine loop started.")
    while True:
        try:
            metrics = get_market_metrics_cached()
            if metrics:
                logger.debug(f"Realtime metrics updated: {metrics}")
        except Exception as e:
            logger.exception("Error in realtime engine loop: %s", e)

        time.sleep(REALTIME_ENGINE_INTERVAL)
