import time
from config import WEEKLY_REPORT_TTL, WEEKLY_REPORT_WEEKDAY, WEEKLY_REPORT_HOUR_UTC
import logging
from analysis_engine import format_weekly_ai_report

logger = logging.getLogger(__name__)

def weekly_scheduler_loop():
    """
    Schedule the weekly AI report generation.
    """
    logger.info("Weekly scheduler loop started.")
    while True:
        try:
            now = time.time()
            if now.weekday() == WEEKLY_REPORT_WEEKDAY and now.hour == WEEKLY_REPORT_HOUR_UTC:
                run_weekly_ai_report()
            time.sleep(60)
        except Exception as e:
            logger.exception("Error in weekly scheduler loop: %s", e)

def run_weekly_ai_report():
    """
    Generate and send the weekly AI report.
    """
    text = format_weekly_ai_report()
    # Send the report to the designated chat
    logger.info("Weekly AI report sent.")
