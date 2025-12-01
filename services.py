# services.py
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

SNAPSHOT_PATH = "snapshot.json"


def load_snapshot():
    """Warm-Start Snapshot عند بداية السيرفر."""
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        mm = data.get("MARKET_METRICS_CACHE")
        if isinstance(mm, dict):
            config.MARKET_METRICS_CACHE.update(mm)

        rt = data.get("REALTIME_CACHE")
        if isinstance(rt, dict):
            for k, v in rt.items():
                if (k in config.REALTIME_CACHE) and (isinstance(v, (str, int, float)) or v is None):
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
    """يحفظ Snapshot خفيف لكى يكون الرد الأول أسرع بعد restart."""
    global _last_snapshot_save_ts
    now = time.time()
    if now - _last_snapshot_save_ts < 30:
        return  # نحفظ كل 30 ثانية كحد أدنى

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
    try:
        with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        _last_snapshot_save_ts = now
    except Exception as e:
        config.logger.exception("Failed to save snapshot: %s", e)


def get_cached_response(key: str, builder):
    """لو فى رد جاهز حديث → استخدمه. لو لأ → ابنيه بالطريقة العادية."""
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


def realtime_engine_loop():
    """
    محرك Real-Time:
    - يجدد تحليل BTC / السوق / المخاطر كل X ثانية (مناسب للخطة المجانية).
    - التقرير الأسبوعى يبنى كل 10 دقائق فقط.
    - نص التحذير يبنى حسب الحاجة أو كل 60 ثانية.
    - يحفظ Snapshot دورى.
    """
    config.logger.info("Realtime engine loop started.")
    SLEEP_SECONDS = 15  # توازن بين سرعة التحديث واستهلاك API

    while True:
        try:
            now = time.time()

            btc_msg = format_analysis("BTCUSDT")
            market_msg = format_market_report()
            risk_msg = format_risk_test()

            weekly_msg = config.REALTIME_CACHE.get("weekly_report")
            last_weekly_build = config.REALTIME_CACHE.get("weekly_built_at") or 0.0
            if not weekly_msg or (now - last_weekly_build) > 600:  # 10 دقائق
                weekly_msg = format_weekly_ai_report()
                config.REALTIME_CACHE["weekly_built_at"] = now

            alert_msg = config.REALTIME_CACHE.get("alert_text")
            last_alert_build = config.REALTIME_CACHE.get("alert_built_at") or 0.0

            metrics = get_market_metrics_cached()
            if metrics:
                risk = evaluate_risk_level(
                    metrics["change_pct"], metrics["volatility_score"]
                )
                reason = detect_alert_condition(metrics, risk)
            else:
                risk = None
                reason = None

            # نبنى التحذير من جديد لو فى سبب أو كل 60 ثانية
            if reason or not alert_msg or (now - last_alert_build) > 60:
                alert_msg = format_ai_alert()
                config.REALTIME_CACHE["alert_built_at"] = now

            config.REALTIME_CACHE.update(
                {
                    "btc_analysis": btc_msg,
                    "market_report": market_msg,
                    "risk_test": risk_msg,
                    "weekly_report": weekly_msg,
                    "alert_text": alert_msg,
                    "last_update": now,
                }
            )

            config.LAST_REALTIME_TICK = now
            save_snapshot()
            time.sleep(SLEEP_SECONDS)
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(SLEEP_SECONDS)


def send_weekly_report_to_all_chats() -> list[int]:
    """يبعت التقرير الأسبوعى لكل الشاتات."""
    from config import send_message  # import هنا عشان نتجنب circular import

    report = get_cached_response("weekly_report", format_weekly_ai_report)
    sent_to: list[int] = []

    for cid in list(config.KNOWN_CHAT_IDS):
        try:
            send_message(cid, report)
            sent_to.append(cid)
        except Exception as e:
            config.logger.exception("Error sending weekly report to %s: %s", cid, e)

    config.logger.info("weekly_ai_report sent to chats: %s", sent_to)
    return sent_to


def weekly_scheduler_loop():
    """
    Scheduler داخلى:
    - كل 60 ثانية يشيك اليوم / الساعة (UTC).
    - لو جمعة 11:00 ولسه مبعتش النهاردة → يبعت التقرير.
    """
    config.logger.info("Weekly scheduler loop started.")
    while True:
        try:
            now = datetime.utcnow()
            config.LAST_WEEKLY_TICK = time.time()
            today_str = now.strftime("%Y-%m-%d")

            if now.weekday() == 4 and now.hour == 11:
                if config.LAST_WEEKLY_SENT_DATE != today_str:
                    config.logger.info("Weekly scheduler: sending weekly_ai_report automatically.")
                    send_weekly_report_to_all_chats()
                    config.LAST_WEEKLY_SENT_DATE = today_str
            time.sleep(60)
        except Exception as e:
            config.logger.exception("Error in weekly scheduler loop: %s", e)
            time.sleep(60)


def watchdog_loop():
    """
    Anti-Freeze Watchdog:
    - يراقب:
        * Realtime engine
        * Weekly scheduler
        * webhook
    - لو tick متأخر جداً → يكتب تحذير ويحاول يعيد تشغيل الثريد لو مش موجود.
    """
    config.logger.info("Watchdog loop started.")
    while True:
        try:
            now = time.time()
            config.LAST_WATCHDOG_TICK = now

            # Realtime Engine monitoring
            rt_delta = now - (config.LAST_REALTIME_TICK or 0)
            if rt_delta > 60:
                config.logger.warning(
                    "Watchdog: realtime engine seems stalled (%.1f s).", rt_delta
                )
                if not any(t.name == "RealtimeEngine" for t in threading.enumerate()):
                    config.logger.warning("Watchdog: restarting realtime engine thread.")
                    start_realtime_thread()

            # Weekly Scheduler monitoring
            ws_delta = now - (config.LAST_WEEKLY_TICK or 0)
            if ws_delta > 300:  # 5 دقائق
                config.logger.warning(
                    "Watchdog: weekly scheduler seems stalled (%.1f s).", ws_delta
                )
                if not any(t.name == "WeeklyScheduler" for t in threading.enumerate()):
                    config.logger.warning("Watchdog: restarting weekly scheduler thread.")
                    start_weekly_scheduler_thread()

            # Webhook monitoring
            wh_delta = now - (config.LAST_WEBHOOK_TICK or 0)
            if config.LAST_WEBHOOK_TICK and wh_delta > 3600:
                config.logger.info(
                    "Watchdog: No webhook activity for %.1f seconds (might be normal at night).",
                    wh_delta,
                )

            time.sleep(5)
        except Exception as e:
            config.logger.exception("Error in watchdog loop: %s", e)
            time.sleep(5)


def start_realtime_thread():
    t_rt = threading.Thread(target=realtime_engine_loop, daemon=True, name="RealtimeEngine")
    t_rt.start()
    config.logger.info("Realtime engine thread started.")
    return t_rt


def start_weekly_scheduler_thread():
    t_weekly = threading.Thread(
        target=weekly_scheduler_loop, daemon=True, name="WeeklyScheduler"
    )
    t_weekly.start()
    config.logger.info("Weekly scheduler thread started.")
    return t_weekly


def start_watchdog_thread():
    t_wd = threading.Thread(target=watchdog_loop, daemon=True, name="Watchdog")
    t_wd.start()
    config.logger.info("Watchdog thread started.")
    return t_wd
