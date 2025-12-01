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


# ==============================
# Snapshot (تشغيل أسرع بعد restart)
# ==============================


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


# ==============================
#   Caching helpers
# ==============================


def get_cached_response(key: str, builder):
    """
    لو فى رد جاهز حديث → استخدمه.
    لو لأ → ابنيه بالطريقة العادية.
    """
    try:
        now = time.time()
        last_update = config.REALTIME_CACHE.get("last_update")
        cached_value = config.REALTIME_CACHE.get(key)

        if cached_value and last_update and (
            now - last_update
        ) <= config.REALTIME_TTL_SECONDS:
            return cached_value

        return builder()
    except Exception as e:
        config.logger.exception("get_cached_response error for %s: %s", key, e)
        return builder()


# ==============================
#   محرك Real-Time الرئيسى
# ==============================


def realtime_engine_loop():
    """
    محرك Real-Time:
    - يجدد تحليل BTC / السوق / المخاطر كل 15–20 ثانية.
    - يبنى تقرير أسبوعى مخزن.
    - يحدّث نص التحذير الذكى.
    - يستدعى نظام التحذير الذكى (maybe_send_market_alert) لكن بدون سبام.
    """
    config.logger.info("Realtime engine loop started.")
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

            # نص التحذير العام (يستخدم فى /alert و /auto_alert)
            alert_msg = config.REALTIME_CACHE.get("alert_text")
            last_alert_build = config.REALTIME_CACHE.get("alert_built_at") or 0.0
            if not alert_msg or (now - last_alert_build) > 60:
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

            # تحديث tick
            config.LAST_REALTIME_TICK = now

            # تشغيل نظام التحذير الذكى من جوه الـ loop
            maybe_send_market_alert(source="realtime")

            save_snapshot()
            time.sleep(15)  # مناسب للخطة المجانية
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(10)


# ==============================
#   تقرير أسبوعى لكل الشاتات
# ==============================


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


# ==============================
#   Watchdog لمراقبة الثريدات
# ==============================


def watchdog_loop():
    """
    Anti-Freeze Watchdog:
    - يراقب Real-Time / Weekly / Webhook.
    - لو ثريد وقف أو اتأخر → يحاول يعيده.
    """
    config.logger.info("Watchdog loop started.")
    while True:
        try:
            now = time.time()
            config.LAST_WATCHDOG_TICK = now

            # Realtime Engine
            rt_delta = now - (config.LAST_REALTIME_TICK or 0)
            if rt_delta > 45:
                config.logger.warning(
                    "Watchdog: realtime engine seems stalled (%.1f s).", rt_delta
                )
                if not any(t.name == "RealtimeEngine" for t in threading.enumerate()):
                    config.logger.warning(
                        "Watchdog: restarting realtime engine thread."
                    )
                    start_realtime_thread()

            # Weekly Scheduler
            ws_delta = now - (config.LAST_WEEKLY_TICK or 0)
            if ws_delta > 300:
                config.logger.warning(
                    "Watchdog: weekly scheduler seems stalled (%.1f s).", ws_delta
                )
                if not any(t.name == "WeeklyScheduler" for t in threading.enumerate()):
                    config.logger.warning(
                        "Watchdog: restarting weekly scheduler thread."
                    )
                    start_weekly_scheduler_thread()

            # Webhook monitoring (معلومات فقط)
            wh_delta = now - (config.LAST_WEBHOOK_TICK or 0)
            if config.LAST_WEBHOOK_TICK and wh_delta > 3600:
                config.logger.info(
                    "Watchdog: No webhook activity for %.1f seconds (might be normal).",
                    wh_delta,
                )

            time.sleep(5)
        except Exception as e:
            config.logger.exception("Error in watchdog loop: %s", e)
            time.sleep(5)


# ==============================
#   نظام التحذير الذكى (أساسى)
# ==============================


def _compute_alert_snapshot():
    """
    يرجّع (metrics, risk, reason) أو None لو مفيش بيانات.
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        return None

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )
    reason = detect_alert_condition(metrics, risk)
    return metrics, risk, reason


def _broadcast_alert(text: str, silent: bool):
    """
    يرسل التحذير لكل المستخدمين + الأدمن.
    """
    targets = set(config.KNOWN_CHAT_IDS)
    targets.add(config.ADMIN_CHAT_ID)

    for cid in list(targets):
        try:
            config.send_message(cid, text, silent=silent)
        except Exception as e:
            config.logger.exception("Error broadcasting alert to %s: %s", cid, e)


def maybe_send_market_alert(source: str = "auto") -> dict:
    """
    قلب نظام التحذير:
    - يحسب حالة السوق.
    - يقرر هل لازم يبعت تحذير جديد ولا لأ.
    - يمنع السبام باستخدام:
        * سبب التحذير LAST_ALERT_REASON
        * فرق السعر عن آخر تحذير LAST_ALERT_PRICE
        * زمن أدنى بين التحذيرات ALERT_MIN_INTERVAL_SEC
    """
    snap = _compute_alert_snapshot()
    if not snap:
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "metrics_failed",
            "sent": False,
        }
        return {"ok": False, "alert_sent": False, "reason": "metrics_failed"}

    metrics, risk, reason = snap
    now = time.time()

    if not reason:
        # السوق رجع هادى → نرجّع الحالة
        if config.LAST_ALERT_REASON is not None:
            config.logger.info("auto_alert: market normal again → reset alert state.")
        config.LAST_ALERT_REASON = None
        config.LAST_ALERT_PRICE = None
        config.LAST_ALERT_AT = 0.0
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_alert",
            "sent": False,
        }
        return {"ok": True, "alert_sent": False, "reason": "no_alert"}

    price = metrics["price"]
    last_reason = config.LAST_ALERT_REASON
    last_price = config.LAST_ALERT_PRICE
    last_at = config.LAST_ALERT_AT or 0.0

    allow = False
    reason_text = "new"

    # أول مرة
    if last_reason is None:
        allow = True
        reason_text = "first_time"
    else:
        dt = now - last_at
        price_drop_pct = 0.0
        if last_price:
            price_drop_pct = (last_price - price) / last_price * 100.0

        # تحذير جديد مختلف (مثلاً panic بعد dump)
        if reason != last_reason:
            allow = True
            reason_text = "new_reason"
        # نفس السبب لكن هبوط إضافى قوى
        elif price_drop_pct >= config.ALERT_PRICE_STEP_PCT:
            allow = True
            reason_text = f"extra_drop_{price_drop_pct:.1f}%"
        # أو مر وقت كافى
        elif dt >= config.ALERT_MIN_INTERVAL_SEC:
            allow = True
            reason_text = f"time_cooldown_{dt:.0f}s"

    if not allow:
        config.logger.info(
            "auto_alert: skipped duplicate alert (reason=%s, source=%s).", reason, source
        )
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "duplicate",
            "sent": False,
        }
        return {"ok": True, "alert_sent": False, "reason": "duplicate"}

    # بناء نص التحذير باستخدام القالب الإحترافى
    alert_text = format_ai_alert(metrics=metrics, risk=risk, reason=reason)

    # لو المخاطر مش high نخلى التنبيه صامت
    silent = risk["level"] != "high"
    _broadcast_alert(alert_text, silent=silent)

    config.LAST_ALERT_REASON = reason
    config.LAST_ALERT_PRICE = price
    config.LAST_ALERT_AT = now
    config.LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True,
        "source": source,
        "price": price,
        "change": metrics["change_pct"],
    }

    config.add_alert_history(
        "auto",
        reason,
        price=metrics["price"],
        change=metrics["change_pct"],
    )

    config.logger.info(
        "auto_alert: NEW alert sent! reason=%s source=%s (%s)", reason, source, reason_text
    )

    return {"ok": True, "alert_sent": True, "reason": reason}


# ==============================
#   Thread helpers
# ==============================


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
