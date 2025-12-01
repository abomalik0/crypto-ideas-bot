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
            # بس الحقول البسيطة
            for k, v in rt.items():
                if k in config.REALTIME_CACHE and (
                    isinstance(v, (str, int, float)) or v is None
                ):
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


def _auto_alert_from_loop(metrics: dict | None, risk: dict | None, reason: str | None, now: float) -> None:
    """
    تنفيذ إرسال التحذير من داخل الـ realtime loop بدون Cron خارجى.
    - يحترم LAST_ALERT_REASON حتى لا يكرر نفس السبب.
    - يحترم كول داون مبنى على مستوى المخاطر.
    """
    try:
        if not metrics or not risk or not reason:
            # لو مفيش سبب حالياً، نرجّع الحالة للطبيعى
            if config.LAST_ALERT_REASON is not None:
                config.logger.info("auto_alert_loop: market back to normal → reset alert state.")
                config.LAST_ALERT_REASON = None
                config.LAST_AUTO_ALERT_INFO = {
                    "time": datetime.utcnow().isoformat(timespec="seconds"),
                    "reason": "no_alert",
                    "sent": False,
                    "ts": now,
                }
            return

        # نفس السبب بالظبط؟ نطبّق كول داون فقط
        last_info = config.LAST_AUTO_ALERT_INFO or {}
        last_ts = last_info.get("ts") or 0.0

        # كول داون حسب مستوى المخاطر
        if risk["level"] == "high":
            cooldown = 30  # ثانية
        elif risk["level"] == "medium":
            cooldown = 60
        else:
            cooldown = 120

        same_reason = (reason == config.LAST_ALERT_REASON)
        delta = now - last_ts

        if same_reason and delta < cooldown:
            # تحذير مكرر ولسه فى فترة الكول داون → لا نرسل
            return

        # نبنى نص التحذير مع دمج التحليل المتقدم
        alert_text = format_ai_alert()
        silent = risk["level"] != "high"  # المخاطر العالية فقط بصوت، غير كده صامت

        config.send_message(config.ADMIN_CHAT_ID, alert_text, silent=silent)

        config.LAST_ALERT_REASON = reason
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": reason,
            "sent": True,
            "ts": now,
        }
        config.add_alert_history(
            "auto_loop",
            reason,
            price=metrics.get("price"),
            change=metrics.get("change_pct"),
        )
        config.logger.info(
            "auto_alert_loop: NEW alert sent! reason=%s, risk=%s, cooldown=%s",
            reason,
            risk["level"],
            cooldown,
        )
    except Exception as e:
        config.logger.exception("auto_alert_loop failed: %s", e)


def realtime_engine_loop():
    """
    محرك Real-Time:
    - يجدد تحليل BTC / السوق / المخاطر بشكل دورى.
    - التقرير الأسبوعى يُبنى فى الكاش كل فترة بدون إرسال.
    - التحذير يتم فحصه باستمرار من هنا (بدون Cron خارجى).
    - يحفظ Snapshot دورى.
    - زمن التكرار (sleep) ديناميكى حسب حالة المخاطر (High/Medium/Low).
    """
    config.logger.info("Realtime engine loop started.")
    while True:
        try:
            now = time.time()

            # 1) بناء التحليلات الأساسية وتخزينها فى الكاش
            btc_msg = format_analysis("BTCUSDT")
            market_msg = format_market_report()
            risk_msg = format_risk_test()

            # 2) بناء التقرير الأسبوعى فى الكاش كل 10 دقائق (بدون إرسال)
            weekly_msg = config.REALTIME_CACHE.get("weekly_report")
            last_weekly_build = config.REALTIME_CACHE.get("weekly_built_at") or 0.0
            if not weekly_msg or (now - last_weekly_build) > 600:  # 10 دقائق
                weekly_msg = format_weekly_ai_report()
                config.REALTIME_CACHE["weekly_built_at"] = now

            # 3) قراءة متركس السوق وتقييم المخاطر + شرط التحذير
            metrics = get_market_metrics_cached()
            risk = None
            reason = None
            if metrics:
                risk = evaluate_risk_level(
                    metrics["change_pct"], metrics["volatility_score"]
                )
                reason = detect_alert_condition(metrics, risk)

            # 4) تحديث نص alert_text فى الكاش فقط (للوحة التحكم + /alert)
            alert_msg = config.REALTIME_CACHE.get("alert_text")
            last_alert_build = config.REALTIME_CACHE.get("alert_built_at") or 0.0
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

            # 5) تشغيل نظام التحذير الأوتوماتيك من داخل اللوب
            _auto_alert_from_loop(metrics, risk, reason, now)

            # 6) تحديث health + snapshot
            config.LAST_REALTIME_TICK = now
            save_snapshot()

            # 7) زمن النوم الديناميكى حسب المخاطر (مناسب للخطة المجانية)
            sleep_seconds = 15.0  # افتراضى
            if risk:
                if risk["level"] == "high":
                    sleep_seconds = 5.0
                elif risk["level"] == "medium":
                    sleep_seconds = 10.0
                else:
                    sleep_seconds = 20.0
            else:
                sleep_seconds = 20.0

            time.sleep(sleep_seconds)
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            # لو حصل مشكلة، ننام شوية ونرجع نحاول
            time.sleep(10)


def send_weekly_report_to_all_chats() -> list[int]:
    """يبعت التقرير الأسبوعى لكل الشاتات."""
    report = get_cached_response("weekly_report", format_weekly_ai_report)
    sent_to: list[int] = []

    for cid in list(config.KNOWN_CHAT_IDS):
        try:
            config.send_message(cid, report)
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
                    config.logger.info(
                        "Weekly scheduler: sending weekly_ai_report automatically."
                    )
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
            if rt_delta > 30:
                config.logger.warning(
                    "Watchdog: realtime engine seems stalled (%.1f s).", rt_delta
                )
                # لو مفيش ثريد باسمه → نحاول نخلق واحد جديد
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
                    config.logger.warning(
                        "Watchdog: restarting weekly scheduler thread."
                    )
                    start_weekly_scheduler_thread()

            # Webhook monitoring
            wh_delta = now - (config.LAST_WEBHOOK_TICK or 0)
            if config.LAST_WEBHOOK_TICK and wh_delta > 3600:  # ساعة بدون webhook
                config.logger.info(
                    "Watchdog: No webhook activity for %.1f seconds (might be normal at night).",
                    wh_delta,
                )

            time.sleep(5)
        except Exception as e:
            config.logger.exception("Error in watchdog loop: %s", e)
            time.sleep(5)


def start_realtime_thread():
    t_rt = threading.Thread(
        target=realtime_engine_loop, daemon=True, name="RealtimeEngine"
    )
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
