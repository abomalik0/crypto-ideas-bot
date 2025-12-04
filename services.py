import logging
import threading
import time
from datetime import datetime, timezone

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

# =====================================================
#   Helpers: Telegram + HTTP
# =====================================================


def _ensure_bot() -> Bot:
    """
    إنشاء / إعادة استخدام إنستانس Bot واحد فقط.
    يستخدم BOT_TOKEN من config (اللى بيساوى TELEGRAM_TOKEN).
    """
    if getattr(config, "BOT", None) is None:
        config.BOT = Bot(token=config.BOT_TOKEN)
    return config.BOT


def http_get(url: str, timeout: int = 10, **kwargs):
    try:
        r = requests.get(url, timeout=timeout, **kwargs)
        return r
    except Exception as e:
        logger.exception("HTTP GET error: %s", e)
        return None


# =====================================================
#   Snapshot Save/Load (اختياري وخفيف)
# =====================================================


def save_snapshot():
    """
    حفظ حالة خفيفة من الكاش (اختياري). مبني على SNAPSHOT_FILE فى config.
    """
    if not getattr(config, "SNAPSHOT_FILE", None):
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
    تحميل حالة خفيفة من الكاش (اختياري).
    """
    if not getattr(config, "SNAPSHOT_FILE", None):
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


# =====================================================
#   Cached Response Layer (للنصوص التقيلة)
# =====================================================


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
      - /alert (Ultra PRO)
      - /weekly_report
      - إلخ
    """
    cached = _get_cached_response(key)
    if cached:
        return cached

    text = builder_func()
    if isinstance(text, str) and text:
        _set_cached_response(key, text, ttl=ttl)
    return text


# =====================================================
#   Broadcast Helper
# =====================================================


def broadcast_message_to_group(text: str):
    """
    إرسال رسالة إلى جروب/قناة التحذيرات.
    يعتمد على ALERT_TARGET_CHAT_ID فى config.
    لو مش موجودة، يستخدم ADMIN_CHAT_ID كـ fallback.
    """
    chat_id = getattr(config, "ALERT_TARGET_CHAT_ID", None) or config.ADMIN_CHAT_ID

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


# =====================================================
#   Weekly Scheduler (تقرير أسبوعى أوتو)
# =====================================================


def run_weekly_ai_report():
    """
    إرسال تقرير أسبوعى إلى الجروب/القناة المحددة.
    """
    text = get_cached_response(
        "weekly_report",
        format_weekly_ai_report,
        ttl=3600,  # نص التقرير يتحدث كل ساعة كحد أقصى
    )
    if not text:
        logger.warning("No weekly report text generated.")
        return

    broadcast_message_to_group(text)


def weekly_scheduler_loop():
    """
    لوب بسيط يشغّل التقرير الأسبوعى فى وقت محدد كل أسبوع.
    - يستخدم WEEKLY_REPORT_WEEKDAY + WEEKLY_REPORT_HOUR_UTC من config.
    - يتأكد إن التقرير ميتبعتش أكتر من مرة فى نفس اليوم.
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
                    # لو عدى على آخر تشغيل حوالى يوم
                    if delta.total_seconds() > 23 * 3600:
                        logger.info(
                            "Running weekly report (more than 23h since last)."
                        )
                        run_weekly_ai_report()
                        config.LAST_WEEKLY_RUN = now
            else:
                # خارج نافذة الساعة المستهدفة: نسمح بتشغيل جديد فى الأسبوع الجاى
                config.LAST_WEEKLY_RUN = None

        except Exception as e:
            logger.exception("Error in weekly scheduler loop: %s", e)

        time.sleep(60)


# =====================================================
#   Realtime Engine (خفيف) /watch
# =====================================================


def get_realtime_snapshot() -> str:
    """
    نص بسيط يعرض Snapshot الحالى للسوق من محرك الذكاء الاصطناعى.
    يستخدم مع أوامر زى /status لو حبيت.
    """
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
    لوب خفيف يحافظ على تحديث MARKET_METRICS_CACHE كل شوية.
    - ما بيبعّتش رسائل للمستخدم.
    - بس يخلى الكاش دايمًا طازة علشان الأنظمة التانية تعتمد عليه.
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


# =====================================================
#   Smart Alert Engine (Ultra Early Mode)
# =====================================================


def _append_alert_history(price, change, level, shock_score, immediate: bool):
    """
    يسجّل أى تنبيه تم إرساله فى ALERT_HISTORY + config.ALERTS_HISTORY (بتاعة البوت القديم).
    """
    entry = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "price": price,
        "change": change,
        "level": level,
        "shock_score": shock_score,
        "immediate": immediate,
        "source": "smart",
    }
    config.ALERT_HISTORY.append(entry)
    # كمان نضيفه على ALERTS_HISTORY القديم كـ log بسيط
    config.ALERTS_HISTORY.append(
        {
            "time": entry["time"],
            "source": "smart_auto",
            "reason": f"level={level} shock={shock_score}",
            "price": price,
            "change_pct": change,
        }
    )
    logger.info("Smart alert history appended: %s", entry)


def smart_alert_loop():
    """
    لوب التحذير الذكى (Ultra PRO Auto — Ultra Early Mode):

      - يقرأ snapshot من compute_smart_market_snapshot
      - يعتمد على:
          * مستوى التحذير (level)
          * Shock Score
          * Early Signal قبل الحركة
          * سرعة الزخم + التسارع + ثقة الاتجاه
      - بيرسل تنبيه واحد قوى قبل الحركة بدقائق قدر الإمكان
      - بيستخدم فجوات زمنية ذكية لتقليل السبام مع الحفاظ على الحساسية العالية
    """
    logger.info("Smart alert loop started.")
    _ = _ensure_bot()  # بس علشان نتأكد إن الـ Bot جاهز

    while True:
        try:
            snapshot = compute_smart_market_snapshot()
            if not snapshot:
                logger.warning("No smart snapshot available, skip alert cycle.")
                time.sleep(config.SMART_ALERT_BASE_INTERVAL * 60)
                continue

            metrics = snapshot["metrics"]
            risk = snapshot["risk"]
            alert_level = snapshot["alert_level"]
            pulse = snapshot["pulse"]
            events = snapshot.get("events") or {}

            price = metrics["price"]
            change = metrics["change_pct"]
            range_pct = metrics["range_pct"]
            vol = metrics["volatility_score"]

            level = alert_level["level"]       # none / low / medium / high / critical
            shock_score = alert_level.get("shock_score") or 0.0

            speed_idx = pulse.get("speed_index", 0.0)
            accel_idx = pulse.get("accel_index", 0.0)
            direction_conf = pulse.get("direction_confidence", 0.0)

            # نحاول نجيب early_signal لو الدالة موجودة
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
                "SmartAlert snapshot: price=%s chg=%.3f range=%.2f vol=%.1f "
                "level=%s shock=%.1f speed=%.1f accel=%.2f conf=%.1f",
                price,
                change,
                range_pct,
                vol,
                level,
                shock_score,
                speed_idx,
                accel_idx,
                direction_conf,
            )

            # -----------------------------
            #   منطق اتخاذ القرار (Ultra Early)
            # -----------------------------
            now_ts = time.time()
            last_alert_ts = getattr(config, "LAST_SMART_ALERT_TS", 0.0) or 0.0
            last_critical_ts = getattr(config, "LAST_CRITICAL_ALERT_TS", 0.0) or 0.0

            base_interval_min = max(1.0, config.SMART_ALERT_BASE_INTERVAL)  # بالدقايق
            adaptive_interval_min = snapshot.get("adaptive_interval", base_interval_min)

            # 1) حالة حرجة واضحة (level + shock)
            immediate_condition = False
            if level in ("critical", "high") and shock_score >= 55:
                immediate_condition = True

            # 2) Early warning قبل الحركة بدقائق (Ultra Early)
            early_condition = False
            if early_signal and early_signal.get("active"):
                score = float(early_signal.get("score", 0.0))
                conf = float(early_signal.get("confidence", 0.0))
                window = float(early_signal.get("window_minutes", 0.0))

                # Ultra Early: نخفض العتبة شوية عن الافتراضى لكن نحافظ على حد أدنى
                effective_threshold = max(50.0, config.EARLY_WARNING_THRESHOLD - 10.0)

                if (
                    score >= effective_threshold
                    and conf >= 55.0
                    and window <= 30.0
                ):
                    early_condition = True
                    logger.info(
                        "EarlyWarning active: score=%.1f conf=%.1f window=%.1f",
                        score,
                        conf,
                        window,
                    )

            # 3) زخم حركة عنيف (حتى لو level لسه medium)
            momentum_condition = False
            if level in ("medium", "high", "critical"):
                if (
                    abs(change) >= 1.8      # حركة يومية بداية عنف
                    and speed_idx >= 72   # سرعة زخم عالية نسبياً
                    and abs(accel_idx) >= 0.85
                    and direction_conf >= 52.0
                ):
                    momentum_condition = True

            # -----------------------------
            #   تحديد نوع التنبيه + الفجوات الزمنية
            # -----------------------------
            send_immediate = False
            send_normal = False

            # فجوة الحالات الحرجة / المبكرة (أقصر) — بحيث نقدر نلتقط أكتر من حركة فى اليوم
            critical_gap = max(180.0, adaptive_interval_min * 60 * 0.4)  # ~3 دقائق أو أكثر
            # فجوة الحالات العادية (أطول) — علشان نقلل السبام
            normal_gap = max(900.0, adaptive_interval_min * 60 * 0.8)    # ~15 دقيقة أو أكثر

            if immediate_condition or early_condition or momentum_condition:
                # تنبيه قوي/مبكر
                if (now_ts - last_critical_ts) >= critical_gap:
                    send_immediate = True
                else:
                    logger.info(
                        "Immediate/early condition detected but within critical gap (%.1fs), skip.",
                        critical_gap,
                    )
            else:
                # مفيش conditions قوية لكن المستوى العام medium/high
                if level in ("medium", "high", "critical") and (
                    now_ts - last_alert_ts
                ) >= normal_gap:
                    send_normal = True

            # -----------------------------
            #   إرسال التنبيه (Ultra PRO Alert)
            # -----------------------------
            if send_immediate or send_normal:
                text = format_ultra_pro_alert()
                if text:
                    broadcast_message_to_group(text)

                    config.LAST_SMART_ALERT_TS = now_ts
                    if send_immediate:
                        config.LAST_CRITICAL_ALERT_TS = now_ts

                    _append_alert_history(
                        price=price,
                        change=change,
                        level=level,
                        shock_score=shock_score,
                        immediate=send_immediate,
                    )

            # -----------------------------
            #   نوم تكيفى بين الدورات
            # -----------------------------
            if immediate_condition or early_condition or momentum_condition:
                # السوق بيتحرك → نبقى ملزوقين فيه أكتر
                sleep_seconds = max(30.0, adaptive_interval_min * 60 * 0.3)
            else:
                # السوق أهدى → نطول شوية
                sleep_seconds = max(60.0, adaptive_interval_min * 60 * 0.9)

            logger.debug("Smart alert loop sleep: %.1fs", sleep_seconds)
            time.sleep(sleep_seconds)

        except Exception as e:
            logger.exception("Error in smart_alert_loop: %s", e)
            # فى حالة خطأ، نريح شوية وبعدين نرجع نحاول
            time.sleep(60)


# =====================================================
#   Public Command Helpers (/market, /risk_test, /coin)
# =====================================================


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


# =====================================================
#   Admin Helpers (/alert, /alert_details, /weekly_now, /alert_pro)
# =====================================================


def handle_admin_alert_command(chat_id: int):
    """
    أمر /alert الرسمى للأدمن:
      - يستخدم Ultra PRO Alert بدل القديم.
      - يبنى الرسالة فورًا بدون كاش طويل.
    """
    bot = _ensure_bot()
    text = format_ultra_pro_alert()
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    from config import add_alert_history as _add_alert_history

    _add_alert_history(
        "manual_ultra",
        "Manual /alert (Ultra PRO)",
        price=None,
        change=None,
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
    يسمح للأدمن بإرسال التقرير الأسبوعى فوراً (نسخة اختبار / طوارئ).
    """
    bot = _ensure_bot()
    text = format_weekly_ai_report()
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def handle_admin_alert_pro_broadcast(admin_chat_id: int):
    """
    تنفيذ أمر /alert_pro:
    يبنى Ultra PRO Alert ويرسله للجروب المحدد.
    """
    from config import ALERT_TARGET_CHAT_ID, send_message
    from analysis_engine import format_ultra_pro_alert

    # بناء Ultra PRO
    text = format_ultra_pro_alert()
    if not text:
        send_message(
            admin_chat_id,
            "⚠️ لا توجد حركة قوية كافية حالياً لإرسال Ultra PRO Alert.\n"
            "جرّب لاحقاً عند ظهور زخم واضح."
        )
        return

    # إرسال للجروب
    send_message(ALERT_TARGET_CHAT_ID, text)

    # تأكيد للأدمن
    send_message(
        admin_chat_id,
        "✅ تم إرسال Ultra PRO Alert للمستخدمين بنجاح.\n\n"
        "📌 تم الإرسال إلى:\n"
        f"<code>{ALERT_TARGET_CHAT_ID}</code>"
    )

    # تسجيل فى السجل
    from config import add_alert_history
    add_alert_history("broadcast_ultra", "Ultra PRO broadcast via /alert_pro")


# =====================================================
#   Watchdog / Health Check
# =====================================================


def watchdog_loop():
    """
    لوب بسيط يراقب الصحة العامة:
      - يتأكد أن البوت قادر يتواصل مع Telegram API
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


# =====================================================
#   Threads Starter
# =====================================================


def start_background_threads():
    """
    تشغيل كل اللوپس الخلفية:
      - Weekly Scheduler
      - Realtime Engine
      - Smart Alert
      - Watchdog
    """
    if getattr(config, "THREADS_STARTED", False):
        logger.info("Background threads already started, skipping.")
        return

    # تحميل snapshot بسيط لو متوفر
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
