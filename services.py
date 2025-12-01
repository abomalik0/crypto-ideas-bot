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
#   Snapshot (Warm Start)
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


# ==============================
#   Cache Helper
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

        if cached_value and last_update and (now - last_update) <= config.REALTIME_TTL_SECONDS:
            return cached_value

        return builder()
    except Exception as e:
        config.logger.exception("get_cached_response error for %s: %s", key, e)
        return builder()


# ==============================
#   Realtime Engine Loop
# ==============================

def realtime_engine_loop():
    """
    محرك Real-Time:
    - يجدد تحليل BTC / السوق / المخاطر كل 5 ثوانى.
    - التقرير الأسبوعى كل 10 دقائق فقط (Smart-Diff).
    - نص التحذير يتم بناؤه هنا أيضاً ويُستخدم فى البوت + البث الجماعى.
    - يحفظ Snapshot دورى.
    """
    config.logger.info("Realtime engine loop started.")
    while True:
        try:
            now = time.time()

            # تحليلات رئيسية سريعة
            btc_msg = format_analysis("BTCUSDT")
            market_msg = format_market_report()
            risk_msg = format_risk_test()

            # تقرير أسبوعى (نبنيه كل 10 دقائق كحد أقصى)
            weekly_msg = config.REALTIME_CACHE.get("weekly_report")
            last_weekly_build = config.REALTIME_CACHE.get("weekly_built_at") or 0.0
            if not weekly_msg or (now - last_weekly_build) > 600:
                weekly_msg = format_weekly_ai_report()
                config.REALTIME_CACHE["weekly_built_at"] = now

            # نص التحذير الأساسى (يستخدم مع /alert و /auto_alert)
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

            # لو فى وضع Alert أو النص قديم → نبنى نص تحذير جديد
            if reason or not alert_msg or (now - last_alert_build) > 60:
                alert_msg = format_ai_alert()
                config.REALTIME_CACHE["alert_built_at"] = now

            # تحديث الكاش
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


# ==============================
#   Smart Auto-Alert Broadcaster
# ==============================

def _get_min_interval_for_level(level: str) -> int:
    """
    نحدد أقل وقت بين تحذير وتحذير حسب مستوى المخاطر:
    - Low   → 20 دقيقة
    - Medium→ 10 دقائق
    - High  → 5 دقائق
    - Extreme / Very High → 2 دقيقة
    """
    lvl = (level or "").lower()
    if "extreme" in lvl or "very" in lvl or "شديد" in lvl:
        return 2 * 60
    if "high" in lvl or "مرتفع" in lvl:
        return 5 * 60
    if "medium" in lvl or "متوسط" in lvl:
        return 10 * 60
    return 20 * 60  # low / غير معروف


def maybe_send_market_alert(source: str = "cron") -> dict:
    """
    محرك التحذير الذكى:
    - يقرأ بيانات السوق والمخاطر.
    - يقرر هل يرسل تحذير جديد أم لا.
    - يبعت مرة واحدة للجميع، مع منع التكرار المزعج.
    - يرجع dict فيها تفاصيل اللى حصل.
    """
    now = time.time()
    metrics = get_market_metrics_cached()

    if not metrics:
        config.logger.warning("maybe_send_market_alert: metrics_failed")
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "metrics_failed",
            "sent": False,
            "source": source,
        }
        return {
            "ok": False,
            "alert_sent": False,
            "reason": "metrics_failed",
        }

    # تقييم المخاطر + سبب الدخول فى وضع alert (لو موجود)
    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    reason = detect_alert_condition(metrics, risk)

    if not risk:
        level = "unknown"
    else:
        level = risk.get("level") or "unknown"

    # لو مفيش Alert condition → نسجّل إنه عادى ونرجع
    if not reason:
        config.logger.info("maybe_send_market_alert: no_alert condition.")
        config.LAST_ALERT_REASON = None
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_alert",
            "sent": False,
            "level": level,
            "source": source,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": "no_alert",
            "risk_level": level,
        }

    # --- منطق منع التكرار المزعج ---
    last_reason = getattr(config, "LAST_ALERT_REASON", None)
    last_ts = getattr(config, "LAST_ALERT_TS", 0.0)

    min_interval = _get_min_interval_for_level(level)
    too_soon = (now - last_ts) < min_interval

    if last_reason == reason and too_soon:
        # نفس السبب ولسه بدري على تحذير جديد
        config.logger.info(
            "maybe_send_market_alert: duplicate alert skipped. reason=%s, dt=%.1f < %d",
            reason,
            now - last_ts,
            min_interval,
        )
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "duplicate",
            "sent": False,
            "level": level,
            "min_interval": min_interval,
            "source": source,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": "duplicate",
            "risk_level": level,
        }

    # --- هنا هنرسل تحذير جديد ---
    alert_text = format_ai_alert()  # الرسالة المتعوب عليها اللى فيها كل التفاصيل
    # لو المخاطر مش High أو Extreme → نخليها Silent (بدون صوت للموبايل)
    lvl_lower = (level or "").lower()
    silent = not ("high" in lvl_lower or "مرتفع" in lvl_lower or "extreme" in lvl_lower or "شديد" in lvl_lower)

    sent_to = []
    failed_to = []

    for cid in list(config.KNOWN_CHAT_IDS):
        try:
            config.send_message(cid, alert_text, silent=silent)
            sent_to.append(cid)
        except Exception as e:
            failed_to.append(cid)
            config.logger.exception("maybe_send_market_alert: error sending alert to %s: %s", cid, e)

    # تحديث الحالة العامة
    config.LAST_ALERT_REASON = reason
    config.LAST_ALERT_TS = now
    config.LAST_ALERT_LEVEL = level
    config.LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True if sent_to else False,
        "level": level,
        "silent": silent,
        "source": source,
        "targets": len(sent_to),
        "failed": len(failed_to),
    }

    # لو عندك وظيفة add_alert_history فى config استخدمها للتسجيل فى اللوحة
    try:
        if hasattr(config, "add_alert_history"):
            config.add_alert_history(
                "auto",
                reason,
                price=metrics["price"],
                change=metrics["change_pct"],
            )
    except Exception as e:
        config.logger.exception("add_alert_history failed in maybe_send_market_alert: %s", e)

    config.logger.info(
        "maybe_send_market_alert: NEW alert sent. reason=%s, level=%s, sent_to=%d, silent=%s",
        reason,
        level,
        len(sent_to),
        silent,
    )

    return {
        "ok": True,
        "alert_sent": True if sent_to else False,
        "reason": reason,
        "risk_level": level,
        "silent": silent,
        "targets": len(sent_to),
        "sent_to": sent_to,
        "failed_to": failed_to,
    }


# ==============================
#   Watchdog
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
                    config.logger.warning("Watchdog: restarting weekly scheduler thread.")
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
