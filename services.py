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
#   Snapshot للحالة بين الريستارتات
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
            # نخلى بس القيم البسيطة
            for k, v in rt.items():
                if (k in config.REALTIME_CACHE) and (
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
        # منمنع الحفظ كل شوية
        return

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
#   Cache helper
# ==============================

def get_cached_response(key: str, builder):
    """
    لو فى رد جاهز حديث → استخدمه.
    لو مفيش → ابنيه بالطريقة العادية.
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
#   Smart Auto-Alert Engine (Pro)
# ==============================

def _ensure_alert_state_defaults():
    """يتأكد إن متغيرات الحالة موجودة فى config (لأول تشغيل)."""
    if not hasattr(config, "LAST_ALERT_AT"):
        config.LAST_ALERT_AT = 0.0
    if not hasattr(config, "LAST_ALERT_PRICE"):
        config.LAST_ALERT_PRICE = None
    if not hasattr(config, "LAST_ALERT_BROADCAST_AT"):
        config.LAST_ALERT_BROADCAST_AT = 0.0
    if not hasattr(config, "LAST_AUTO_ALERT_INFO"):
        config.LAST_AUTO_ALERT_INFO = {
            "time": None,
            "reason": None,
            "sent": False,
        }


def _broadcast_alert_to_all_chats(text: str, *, silent: bool = True) -> list[int]:
    """
    يبعت التحذير لكل الشاتات اللى استخدمت البوت (مع استثناء الأدمن
    لأن الأدمن بياخد الرسالة الكاملة لوحده).
    """
    sent_to: list[int] = []

    for cid in list(config.KNOWN_CHAT_IDS):
        if cid == config.ADMIN_CHAT_ID:
            continue
        try:
            config.send_message(cid, text, silent=silent)
            sent_to.append(cid)
            # تهدئة بسيطة علشان ما نزعّقش لتليجرام
            time.sleep(0.05)
        except Exception as e:
            config.logger.exception("Error broadcasting alert to %s: %s", cid, e)

    return sent_to


def smart_auto_alert_decision(metrics: dict, risk: dict | None, *, source: str = "engine"):
    """
    أقوى نظام تحذير:

    • يحدد إذا كان فى موجة هبوط/خطر حقيقى ولا لأ (عن طريق detect_alert_condition)
    • تحكم ذكى:
        - إنذار واحد لكل موجة (reason جديد)
        - تكرار محدود جداً لنفس السبب لو الهبوط كمل بشكل عنيف
        - كول داون زمنى + فرق سعر لازم يتحقق
    • لو الخطر High أو Extreme → يبعت لكل المستخدمين مرة واحدة.
    """

    _ensure_alert_state_defaults()

    now = time.time()
    price = metrics["price"]
    change_pct = metrics["change_pct"]

    # هل فى سبب أساساً للتحذير؟
    reason = detect_alert_condition(metrics, risk)
    if not reason:
        # السوق رجع هادى → نرجّع الحالة للطبيعى
        if config.LAST_ALERT_REASON is not None:
            config.logger.info("auto_alert: market normal again → reset alert state.")
        config.LAST_ALERT_REASON = None
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_alert",
            "sent": False,
            "source": source,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": "no_alert",
        }

    last_reason = config.LAST_ALERT_REASON
    last_at = config.LAST_ALERT_AT or 0.0
    last_price = config.LAST_ALERT_PRICE

    # إعدادات (ممكن نغير قيمها فى config.py بعدين)
    new_reason_min_interval = getattr(
        config, "ALERT_NEW_REASON_MIN_INTERVAL", 15 * 60
    )  # 15 دقيقة
    same_reason_min_interval = getattr(
        config, "ALERT_SAME_REASON_MIN_INTERVAL", 2 * 60 * 60
    )  # ساعتين
    same_reason_min_move_pct = getattr(
        config, "ALERT_SAME_REASON_MIN_MOVE_PCT", 4.0
    )  # لازم يتحرك 4% تانى عشان نحذر تانى
    broadcast_levels = getattr(
        config, "ALERT_BROADCAST_LEVELS", {"high", "extreme"}
    )

    is_new_reason = reason != last_reason

    # ----- منطق الكول داون -----
    can_alert = False
    cooldown_reason = None

    if is_new_reason:
        # سبب مختلف → مسموح لو مر وقت كافى من آخر تحذير
        if (now - last_at) >= new_reason_min_interval:
            can_alert = True
        else:
            cooldown_reason = "cooldown_new_reason"
    else:
        # نفس السبب → لازم وقت كبير + حركة سعر محترمة
        time_ok = (now - last_at) >= same_reason_min_interval
        move_pct = 0.0
        if last_price:
            move_pct = abs(price - last_price) / max(price, 1) * 100.0

        if time_ok and move_pct >= same_reason_min_move_pct:
            can_alert = True
        else:
            cooldown_reason = "cooldown_same_reason"

    if not can_alert:
        # مش هيبعت تحذير لكن يسجل فى الحالة إيه اللى حصل
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": cooldown_reason or "cooldown",
            "sent": False,
            "source": source,
            "active_reason": reason,
            "price": price,
            "change_pct": change_pct,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": cooldown_reason or "cooldown",
        }

    # ----- هنا فعلاً هنرسل التحذير -----
    alert_text = format_ai_alert()  # بيبنى الرسالة الكاملة مع كل التفاصيل

    # ١) نبعته للأدمن دائماً
    try:
        config.send_message(config.ADMIN_CHAT_ID, alert_text, silent=False)
    except Exception as e:
        config.logger.exception("Error sending alert to admin: %s", e)

    # ٢) هل نبعته لكل المستخدمين؟
    level = (risk or {}).get("level")
    broadcast_to: list[int] = []
    if level in broadcast_levels:
        broadcast_to = _broadcast_alert_to_all_chats(
            alert_text,
            silent=False,  # تنبيه بصوت لأنه نادر ومهم
        )

    # تحديث حالة النظام
    config.LAST_ALERT_REASON = reason
    config.LAST_ALERT_AT = now
    config.LAST_ALERT_PRICE = price
    config.LAST_ALERT_BROADCAST_AT = now if broadcast_to else config.LAST_ALERT_BROADCAST_AT

    config.LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True,
        "source": source,
        "risk_level": level,
        "price": price,
        "change_pct": change_pct,
        "broadcast_to": broadcast_to,
    }

    config.logger.info(
        "Smart auto alert sent. reason=%s level=%s price=%.2f broadcast_to=%s",
        reason,
        level,
        price,
        broadcast_to,
    )

    return {
        "ok": True,
        "alert_sent": True,
        "reason": reason,
        "risk_level": level,
        "broadcast_to": broadcast_to,
    }


# ==============================
#   محرك الـ Real-Time
# ==============================

def realtime_engine_loop():
    """
    محرك Real-Time (قلب المنظومة):

    - يجدد تحليل BTC / السوق / المخاطر باستمرار.
    - يبنى تقرير أسبوعى مبدئى.
    - يبنى رسالة التحذير الكاملة.
    - يشغّل Smart Auto-Alert من غير Cron-Job خارجى.
    """
    config.logger.info("Realtime engine loop started.")
    while True:
        try:
            now = time.time()

            # تحليلات أساسية جاهزة كـ Cache
            btc_msg = format_analysis("BTCUSDT")
            market_msg = format_market_report()
            risk_msg = format_risk_test()

            # تقرير أسبوعى: نحدّثه كل 10 دقائق فقط
            weekly_msg = config.REALTIME_CACHE.get("weekly_report")
            last_weekly_build = config.REALTIME_CACHE.get("weekly_built_at") or 0.0
            if not weekly_msg or (now - last_weekly_build) > 600:  # 10 دقائق
                weekly_msg = format_weekly_ai_report()
                config.REALTIME_CACHE["weekly_built_at"] = now

            # بيانات السوق الخام
            metrics = get_market_metrics_cached()
            risk = None
            if metrics:
                risk = evaluate_risk_level(
                    metrics["change_pct"], metrics["volatility_score"]
                )

            # رسالة التحذير الكاملة (تستخدمها الأوامر + البرودكاست)
            alert_msg = config.REALTIME_CACHE.get("alert_text")
            last_alert_build = config.REALTIME_CACHE.get("alert_built_at") or 0.0

            if metrics:
                # لو مفيش alert msg أو بقاله كتير → نعيد بناء الرسالة
                if (not alert_msg) or ((now - last_alert_build) > 60):
                    alert_msg = format_ai_alert()
                    config.REALTIME_CACHE["alert_built_at"] = now

            # تحديث الكاش العام
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

            # نخلى Realtime loop مسؤول كمان عن تشغيل Smart Auto-Alert
            if metrics and risk:
                try:
                    smart_auto_alert_decision(metrics, risk, source="engine")
                except Exception as e:
                    config.logger.exception("Smart auto alert from engine failed: %s", e)

            config.LAST_REALTIME_TICK = now
            save_snapshot()

            time.sleep(5)
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(5)


# ==============================
#   Weekly Report Broadcaster
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


# ==============================
#   Weekly Scheduler Loop
# ==============================

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
#   Watchdog Loop
# ==============================

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
                if not any(t.name == "RealtimeEngine" for t in threading.enumerate()):
                    config.logger.warning(
                        "Watchdog: restarting realtime engine thread."
                    )
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


# ==============================
#   Thread Starters
# ==============================

def start_realtime_thread():
    t_rt = threading.Thread(
        target=realtime_engine_loop,
        daemon=True,
        name="RealtimeEngine",
    )
    t_rt.start()
    config.logger.info("Realtime engine thread started.")
    return t_rt


def start_weekly_scheduler_thread():
    t_weekly = threading.Thread(
        target=weekly_scheduler_loop,
        daemon=True,
        name="WeeklyScheduler",
    )
    t_weekly.start()
    config.logger.info("Weekly scheduler thread started.")
    return t_weekly


def start_watchdog_thread():
    t_wd = threading.Thread(
        target=watchdog_loop,
        daemon=True,
        name="Watchdog",
    )
    t_wd.start()
    config.logger.info("Watchdog thread started.")
    return t_wd
