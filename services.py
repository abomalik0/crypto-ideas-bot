import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from telegram import Bot, ParseMode

import config
from analysis_engine import (
    format_analysis,
    format_market_report,
    format_risk_test,
    format_ai_alert,
    format_ai_alert_details,
    format_weekly_ai_report,
    compute_smart_market_snapshot,
    format_ultra_pro_alert,
)

logger = logging.getLogger(__name__)


# ==============================
#   Helpers: Telegram + HTTP
# ==============================


def _ensure_bot() -> Bot:
    if config.BOT is None:
        config.BOT = Bot(token=config.BOT_TOKEN)
    return config.BOT


def http_get(url: str, timeout: int = 10, **kwargs):
    try:
        r = requests.get(url, timeout=timeout, **kwargs)
        return r
    except Exception as e:
        logger.exception("HTTP GET error: %s", e)
        return None


# ==============================
#   Snapshot Save/Load
# ==============================


def save_snapshot():
    """
    حفظ حالة خفيفة من الكاش والنبض (اختيارى)
    """
    if not config.SNAPSHOT_FILE:
        logger.info("No SNAPSHOT_FILE configured, skip save.")
        return
    try:
        import json

        snapshot = {
            "MARKET_METRICS_CACHE": config.MARKET_METRICS_CACHE,
        }
        with open(config.SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
        logger.info("Snapshot saved to %s", config.SNAPSHOT_FILE)
    except Exception as e:
        logger.exception("Error saving snapshot: %s", e)


def load_snapshot():
    """
    تحميل حالة خفيفة من الكاش والنبض (اختيارى)
    """
    if not config.SNAPSHOT_FILE:
        logger.info("No SNAPSHOT_FILE configured, skipping load.")
        return
    import os
    import json

    if not os.path.exists(config.SNAPSHOT_FILE):
        logger.info("No snapshot file exists: %s", config.SNAPSHOT_FILE)
        return
    try:
        with open(config.SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            config.MARKET_METRICS_CACHE.update(
                data.get("MARKET_METRICS_CACHE", {})
            )
        logger.info("Snapshot loaded from %s", config.SNAPSHOT_FILE)
    except Exception as e:
        logger.exception("Error loading snapshot: %s", e)


# ==============================
#   Cached Response Layer
# ==============================


def _get_cached_response(key: str):
    item = config.RESPONSE_CACHE.get(key)
    if not item:
        return None
    ttl = item.get("ttl", config.DEFAULT_RESPONSE_TTL)
    if time.time() - item["time"] > ttl:
        return None
    return item["data"]


def _set_cached_response(key: str, data: str, ttl: float | None = None):
    if ttl is None:
        ttl = config.DEFAULT_RESPONSE_TTL
    config.RESPONSE_CACHE[key] = {
        "time": time.time(),
        "ttl": ttl,
        "data": data,
    }


def get_cached_response(key: str, builder_func, ttl: float | None = None) -> str:
    """
    كاش بسيط لنصوص التقارير:
      - /market
      - /risk_test
      - /alert (للأدمن)
      - ... إلخ
    """
    cached = _get_cached_response(key)
    if cached:
        return cached

    text = builder_func()
    if isinstance(text, str) and text:
        _set_cached_response(key, text, ttl=ttl)
    return text


# ==============================
#   Broadcast Helper
# ==============================


def broadcast_message_to_group(text: str):
    """
    إرسال رسالة إلى جروب أو قناة محددة من الإعدادات.
    """
    chat_id = config.ALERT_TARGET_CHAT_ID
    if not chat_id:
        logger.warning("No ALERT_TARGET_CHAT_ID configured, skipping broadcast.")
        return

    bot = _ensure_bot()
    try:
        bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info("Broadcast sent to chat_id=%s", chat_id)
    except Exception as e:
        logger.exception("Error broadcasting message: %s", e)


# ==============================
#   Weekly Scheduler (/weekly)
# ==============================


def run_weekly_ai_report():
    """
    إرسال تقرير أسبوعى إلى الجروب/القناة المحددة.
    """
    text = get_cached_response(
        "weekly_report",
        format_weekly_ai_report,
        ttl=config.WEEKLY_REPORT_TTL,
    )
    if not text:
        logger.warning("No weekly report text generated.")
        return

    broadcast_message_to_group(text)


def weekly_scheduler_loop():
    """
    لوب بسيط يشغّل التقرير الأسبوعى فى وقت محدد كل أسبوع.
    """
    logger.info("Weekly scheduler loop started.")
    while True:
        try:
            now = datetime.now(timezone.utc)

            target_weekday = config.WEEKLY_REPORT_WEEKDAY
            target_hour = config.WEEKLY_REPORT_HOUR_UTC

            if now.weekday() == target_weekday and now.hour == target_hour:
                if not config.LAST_WEEKLY_RUN:
                    logger.info("Running weekly report now (first in this window).")
                    run_weekly_ai_report()
                    config.LAST_WEEKLY_RUN = now
                else:
                    delta = now - config.LAST_WEEKLY_RUN
                    if delta.total_seconds() > 23 * 3600:
                        logger.info("Running weekly report (more than 23h since last).")
                        run_weekly_ai_report()
                        config.LAST_WEEKLY_RUN = now
            else:
                config.LAST_WEEKLY_RUN = None

        except Exception as e:
            logger.exception("Error in weekly scheduler loop: %s", e)

        time.sleep(60)


# ==============================
#   Realtime Engine (light) /watch
# ==============================


def get_realtime_snapshot() -> str:
    """
    نص بسيط يعرض Snapshot الحالى للسوق من محرك الذكاء الاصطناعى.
    يستخدم مع أمر مثل /watch أو /status على حسب البوت.
    """
    from analysis_engine import compute_smart_market_snapshot

    snapshot = compute_smart_market_snapshot()
    if not snapshot:
        return (
            "⚠️ تعذّر الحصول على Snapshot ذكى للسوق فى هذه اللحظة.\n"
            "حاول مرة أخرى بعد قليل."
        )

    metrics = snapshot["metrics"]
    risk = snapshot["risk"]
    alert_level = snapshot["alert_level"]
    pulse = snapshot["pulse"]

    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    risk_level = risk["level"]
    risk_emoji = risk["emoji"]

    level = alert_level["level"]
    shock_score = alert_level["shock_score"]

    speed_idx = pulse["speed_index"]
    accel_idx = pulse["accel_index"]
    direction_conf = pulse["direction_confidence"]

    if level is None:
        level_txt = "لا يوجد تحذير حاليًا (Normal)"
    else:
        level_txt = level.upper()

    msg = f"""
📡 <b>Realtime Market Snapshot — IN CRYPTO Ai</b>

💰 <b>سعر البيتكوين الآن:</b> ${price:,.0f}
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
📊 <b>مدى الحركة اليوم:</b> {range_pct:.2f}% — التقلب: {vol:.1f} / 100

⚙️ <b>نظام المخاطر:</b>
- المستوى الحالى: {risk_emoji} <b>{risk_level}</b>
- Shock Score: <b>{shock_score:.1f}</b> / 100
- مستوى التحذير: <b>{level_txt}</b>

📡 <b>Pulse Engine:</b>
- سرعة الزخم: <b>{speed_idx:.1f}</b> / 100
- تسارع الحركة: <b>{accel_idx:.1f}</b>
- ثقة الاتجاه اللحظى: <b>{direction_conf:.1f}%</b>

<b>IN CRYPTO Ai 🤖 — Realtime Engine</b>
""".strip()

    return msg


def realtime_engine_loop():
    """
    لوب خفيف يمكنه تحديث Snapshot أو حفظه لو حابب توسّع لاحقاً.
    حالياً نكتفى بأنه يمرّ من وقت لآخر كى نحافظ على تحديث MARKET_METRICS_CACHE.
    """
    logger.info("Realtime engine loop started.")
    while True:
        try:
            from analysis_engine import get_market_metrics_cached

            metrics = get_market_metrics_cached()
            if metrics:
                logger.debug(
                    "Realtime metrics: price=%s change=%.2f range=%.2f vol=%.1f",
                    metrics["price"],
                    metrics["change_pct"],
                    metrics["range_pct"],
                    metrics["volatility_score"],
                )
        except Exception as e:
            logger.exception("Error in realtime engine loop: %s", e)

        time.sleep(config.REALTIME_ENGINE_INTERVAL)


# ==============================
#   Smart Alert Engine (Auto Alert)
# ==============================


def smart_alert_loop():
    """
    لوب التحذير الذكى:
      - يراقب السوق
      - يقرر هل يرسل تنبيه أم لا
      - يستخدم Ultra PRO Alert للمستخدمين عند تحقق الشروط
    """
    logger.info("Smart alert loop started.")
    bot = _ensure_bot()

    while True:
        try:
            from analysis_engine import (
                compute_smart_market_snapshot,
                evaluate_risk_level,
            )

            snapshot = compute_smart_market_snapshot()
            if not snapshot:
                logger.warning("No smart snapshot available, skip alert cycle.")
                time.sleep(config.SMART_ALERT_BASE_INTERVAL)
                continue

            metrics = snapshot["metrics"]
            risk = snapshot["risk"]
            alert_level = snapshot["alert_level"]
            pulse = snapshot["pulse"]

            price = metrics["price"]
            change = metrics["change_pct"]
            range_pct = metrics["range_pct"]
            vol = metrics["volatility_score"]

            level = alert_level["level"]
            shock_score = alert_level["shock_score"]

            events = snapshot["events"]
            early_signal = None
            try:
                from analysis_engine import detect_early_movement_signal

                early_signal = detect_early_movement_signal(
                    metrics,
                    pulse,
                    events,
                    risk,
                )
            except Exception:
                early_signal = None

            logger.info(
                "SmartAlert snapshot: price=%s chg=%.2f range=%.2f vol=%.1f level=%s shock=%.1f",
                price,
                change,
                range_pct,
                vol,
                level,
                shock_score,
            )

            now_ts = time.time()
            last_alert_ts = config.LAST_SMART_ALERT_TS or 0.0
            last_critical_ts = config.LAST_CRITICAL_ALERT_TS or 0.0

            immediate_or_early = False

            if level in ("critical", "high"):
                immediate_or_early = True
                logger.info(
                    "SmartAlert condition (level=%s shock=%.1f) triggers immediate check.",
                    level,
                    shock_score,
                )

            if not immediate_or_early and early_signal and early_signal.get("active"):
                score = early_signal.get("score", 0.0)
                if score >= config.EARLY_WARNING_THRESHOLD:
                    immediate_or_early = True
                    logger.info(
                        "EarlyWarning active: dir=%s score=%.1f conf=%.1f window=%s",
                        early_signal.get("direction"),
                        score,
                        early_signal.get("confidence"),
                        early_signal.get("window_minutes"),
                    )

            interval = snapshot.get("adaptive_interval", config.SMART_ALERT_BASE_INTERVAL)

            if immediate_or_early:
                min_gap = max(300.0, interval * 60 * 0.6)
                if (now_ts - last_critical_ts) < min_gap:
                    logger.info(
                        "SmartAlert immediate condition but within critical gap (%.1fs), skip.",
                        min_gap,
                    )
                else:
                    # هنا نستخدم الرسالة الاحترافية الجديدة للمستخدمين
                    text = format_ultra_pro_alert()
                    if text:
                        broadcast_message_to_group(text)
                        config.LAST_SMART_ALERT_TS = now_ts
                        config.LAST_CRITICAL_ALERT_TS = now_ts
                        config.ALERT_HISTORY.append(
                            {
                                "time": datetime.utcnow().isoformat(timespec="seconds"),
                                "price": price,
                                "change": change,
                                "level": level,
                                "shock_score": shock_score,
                                "immediate": True,
                                "source": "smart",
                            }
                        )
            else:
                min_gap = max(1800.0, interval * 60 * 0.9)
                if (now_ts - last_alert_ts) >= min_gap and level in (
                    "medium",
                    "high",
                    "critical",
                ):
                    text = format_ultra_pro_alert()
                    if text:
                        broadcast_message_to_group(text)
                        config.LAST_SMART_ALERT_TS = now_ts
                        config.ALERT_HISTORY.append(
                            {
                                "time": datetime.utcnow().isoformat(timespec="seconds"),
                                "price": price,
                                "change": change,
                                "level": level,
                                "shock_score": shock_score,
                                "immediate": False,
                                "source": "smart",
                            }
                        )

            sleep_seconds = interval * 60
            logger.debug("Smart alert loop sleep: %.1fs", sleep_seconds)
            time.sleep(sleep_seconds)

        except Exception as e:
            logger.exception("Error in smart_alert_loop: %s", e)
            time.sleep(60)


# ==============================
#   Risk / Market Public Helpers
# ==============================


def handle_market_command(chat_id: int):
    bot = _ensure_bot()
    text = get_cached_response("market_report", format_market_report)
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def handle_risk_test_command(chat_id: int):
    bot = _ensure_bot()
    text = get_cached_response("risk_test", format_risk_test)
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def handle_coin_command(chat_id: int, symbol: str):
    bot = _ensure_bot()
    text = format_analysis(symbol)
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ==============================
#   Admin /alert, /alert_details, /weekly_now
# ==============================


def handle_admin_alert_command(chat_id: int):
    """
    أمر /alert الرسمى للأدمن فقط (لا يرسل أوتو).
    هنا ممكن تخليه يرسل النسخة الكلاسيك أو يبقى زر اختبار.
    حالياً يبقى كما هو باستخدام format_ai_alert.
    """
    bot = _ensure_bot()
    text = get_cached_response("alert_text", format_ai_alert, ttl=120)
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def handle_admin_alert_details_command(chat_id: int):
    bot = _ensure_bot()
    text = get_cached_response(
        "alert_details",
        format_ai_alert_details,
        ttl=120,
    )
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def handle_admin_weekly_now_command(chat_id: int):
    """
    يسمح للأدمن بإرسال التقرير الأسبوعى فوراً.
    """
    bot = _ensure_bot()
    text = format_weekly_ai_report()
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ==============================
#   Watchdog / Health Check
# ==============================


def watchdog_loop():
    """
    لوب بسيط يراقب الصحة العامة:
      - يحاول يتأكد أن البوت شغال
      - ممكن يضرب Ping على أى Endpoint خارجى لو حابب
    """
    logger.info("Watchdog loop started.")
    while True:
        try:
            bot = _ensure_bot()
            me = bot.get_me()
            logger.debug("Bot is alive as @%s", me.username)
        except Exception as e:
            logger.exception("Watchdog error: %s", e)
        time.sleep(config.WATCHDOG_INTERVAL)


# ==============================
#   Threads Starter
# ==============================


def start_background_threads():
    """
    يشغّل كل اللوپس الخلفية:
      - Weekly Scheduler
      - Realtime Engine
      - Smart Alert
      - Watchdog
    """
    if config.THREADS_STARTED:
        logger.info("Background threads already started, skipping.")
        return

    load_snapshot()

    weekly_thread = threading.Thread(
        target=weekly_scheduler_loop,
        name="weekly_scheduler",
        daemon=True,
    )
    weekly_thread.start()

    realtime_thread = threading.Thread(
        target=realtime_engine_loop,
        name="realtime_engine",
        daemon=True,
    )
    realtime_thread.start()

    smart_thread = threading.Thread(
        target=smart_alert_loop,
        name="smart_alert",
        daemon=True,
    )
    smart_thread.start()

    watchdog_thread = threading.Thread(
        target=watchdog_loop,
        name="watchdog",
        daemon=True,
    )
    watchdog_thread.start()

    config.THREADS_STARTED = True
    logger.info("All background threads started.")
