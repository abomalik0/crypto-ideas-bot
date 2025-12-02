# ==========================================
#              SERVICES MODULE
#      (Realtime Engine + Weekly + Snapshot)
# ==========================================

import time
import json
import threading
from datetime import datetime

import config
from analysis_engine import (
    format_analysis,
    format_market_report,
    format_risk_test,
    format_weekly_ai_report,
    format_ai_alert,
    get_market_metrics_cached,
    evaluate_risk_level,
    detect_alert_condition,
)

# ==============================
#       Snapshot File
# ==============================

SNAPSHOT_PATH = "snapshot.json"


def load_snapshot():
    """تحميل Warm Start Snapshot عند بداية السيرفر."""
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        mm = data.get("MARKET_METRICS_CACHE")
        if isinstance(mm, dict):
            config.MARKET_METRICS_CACHE.update(mm)

        rt = data.get("REALTIME_CACHE")
        if isinstance(rt, dict):
            for k, v in rt.items():
                # إصلاح الشرط (كان فيه مشكلة أولويات)
                if k in config.REALTIME_CACHE and (isinstance(v, (str, int, float)) or v is None):
                    config.REALTIME_CACHE[k] = v

        config.LAST_ALERT_REASON = data.get("LAST_ALERT_REASON")
        config.LAST_WEEKLY_SENT_DATE = data.get("LAST_WEEKLY_SENT_DATE")

        config.logger.info("Warm-start snapshot loaded successfully.")

    except FileNotFoundError:
        config.logger.info("No snapshot file found, starting cold.")
    except Exception as e:
        config.logger.exception("Failed to load snapshot: %s", e)


_last_snapshot_save_ts = 0.0


def save_snapshot():
    """حفظ Snapshot خفيف لتسريع البوت بعد Restart."""
    global _last_snapshot_save_ts
    now = time.time()
    if now - _last_snapshot_save_ts < 30:
        return

    try:
        snap = {
            "MARKET_METRICS_CACHE": config.MARKET_METRICS_CACHE,
            "REALTIME_CACHE": {
                k: v
                for k, v in config.REALTIME_CACHE.items()
                if isinstance(v, (str, int, float)) or v is None
            },
            "LAST_ALERT_REASON": config.LAST_ALERT_REASON,
            "LAST_WEEKLY_SENT_DATE": config.LAST_WEEKLY_SENT_DATE,
            "time": datetime.utcnow().isoformat(timespec="seconds"),
        }
        with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

        _last_snapshot_save_ts = now

    except Exception as e:
        config.logger.exception("Failed to save snapshot: %s", e)


# ==============================
#      Cached Real-time Builder
# ==============================

def get_cached_response(key: str, builder):
    """استخدام Cache لو صالح – أو إعادة البناء."""
    try:
        now = time.time()
        last_update = config.REALTIME_CACHE.get("last_update")
        cached_value = config.REALTIME_CACHE.get(key)

        if cached_value and last_update and (now - last_update) <= config.REALTIME_TTL_SECONDS:
            return cached_value

        return builder()

    except Exception as e:
        config.logger.exception("get_cached_response error for %s: %s", key, e)
        return builder()


# ==============================
#      Real-time Engine Loop
# ==============================

def realtime_engine_loop():
    """يبنى الردود الجاهزة كل عدة ثوانى."""

    # إصلاح مهم: منع ظهور تحذير الزمن الضخم عند بداية التشغيل
    config.LAST_REALTIME_TICK = time.time()

    config.logger.info("Realtime engine loop started.")
    while True:
        try:
            now = time.time()
            config.LAST_REALTIME_TICK = now

            # ===== بناء الردود =====
            config.REALTIME_CACHE["btc_analysis"] = format_analysis("BTCUSDT")
            config.REALTIME_CACHE["market_report"] = format_market_report()
            config.REALTIME_CACHE["risk_test"] = format_risk_test()
            config.REALTIME_CACHE["weekly_report"] = format_weekly_ai_report()
            config.REALTIME_CACHE["alert_text"] = format_ai_alert()

            config.REALTIME_CACHE["last_update"] = now

            save_snapshot()

            time.sleep(3)

        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(3)


# ==============================
#     Weekly Scheduler Loop
# ==============================

def weekly_scheduler_loop():
    """يرسل التقرير الأسبوعى مرة يوميًا (لو لم يُرسل اليوم)."""
    config.LAST_WEEKLY_TICK = time.time()
    config.logger.info("Weekly scheduler loop started.")

    while True:
        try:
            now = datetime.utcnow().date().isoformat()
            config.LAST_WEEKLY_TICK = time.time()

            if config.LAST_WEEKLY_SENT_DATE != now:
                report = format_weekly_ai_report()
                for chat_id in list(config.KNOWN_CHAT_IDS):
                    try:
                        config.send_message(chat_id, report)
                    except Exception:
                        pass

                config.LAST_WEEKLY_SENT_DATE = now
                save_snapshot()

            time.sleep(30)

        except Exception as e:
            config.logger.exception("Weekly scheduler error: %s", e)
            time.sleep(10)


# ==============================
#      Watchdog Loop (Anti-Freeze)
# ==============================

def watchdog_loop():
    """
    يراقب:
        - Realtime Engine
        - Weekly Scheduler
        - Webhook
    """
    config.logger.info("Watchdog loop started.")

    while True:
        try:
            now = time.time()
            config.LAST_WATCHDOG_TICK = now

            # Realtime Engine
            if config.LAST_REALTIME_TICK:
                rt_delta = now - config.LAST_REALTIME_TICK
                if rt_delta > 30:
                    config.logger.warning("Watchdog: realtime engine seems stalled (%.1f s).", rt_delta)
                    if not any(t.name == "RealtimeEngine" for t in threading.enumerate()):
                        config.logger.warning("Watchdog: restarting realtime engine thread.")
                        start_realtime_thread()

            # Weekly scheduler
            if config.LAST_WEEKLY_TICK:
                ws_delta = now - config.LAST_WEEKLY_TICK
                if ws_delta > 300:
                    config.logger.warning("Watchdog: weekly scheduler seems stalled (%.1f s).", ws_delta)
                    if not any(t.name == "WeeklyScheduler" for t in threading.enumerate()):
                        start_weekly_scheduler_thread()

            # Webhook inactivity
            if config.LAST_WEBHOOK_TICK:
                wh_delta = now - config.LAST_WEBHOOK_TICK
                if wh_delta > 3600:
                    config.logger.info("Watchdog: No webhook activity for %.1f seconds (normal at night).", wh_delta)

            time.sleep(5)

        except Exception as e:
            config.logger.exception("Error in watchdog loop: %s", e)
            time.sleep(5)


# ==============================
#     Thread Starters
# ==============================

def start_realtime_thread():
    t = threading.Thread(target=realtime_engine_loop, daemon=True, name="RealtimeEngine")
    t.start()
    config.logger.info("Realtime engine thread started.")
    return t


def start_weekly_scheduler_thread():
    t = threading.Thread(target=weekly_scheduler_loop, daemon=True, name="WeeklyScheduler")
    t.start()
    config.logger.info("Weekly scheduler thread started.")
    return t


def start_watchdog_thread():
    t = threading.Thread(target=watchdog_loop, daemon=True, name="Watchdog")
    t.start()
    config.logger.info("Watchdog thread started.")
    return t
