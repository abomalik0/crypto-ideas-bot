import logging
import threading
import time
from datetime import datetime, timezone

import requests
from telegram import Bot, ParseMode

import config
from config import ADMIN_CHAT_ID
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
#   Startup Broadcast (Auto message after restart)
# =====================================================

# علامة علشان نضمن إن رسالة الـ Startup تتبعت مرة واحدة بس
_STARTUP_BROADCAST_DONE: bool = False

# عدد الثوانى اللى هنستنى قبل إرسال رسالة التشغيل بعد الريستارت
STARTUP_BROADCAST_DELAY_SECONDS: int = 5


def _startup_broadcast_message() -> str:
    """
    نص رسالة الافتتاح اللى هتتبعت للـ OWNER بعد تشغيل السيرفر.
    """
    return (
        "🤖 <b>IN CRYPTO AI عاد للعمل</b>\n"
        "🚀 السيرفر اشتغل وكل المحركات (Real-Time / Smart Alert / Weekly) تعمل الآن.\n"
        "📡 سيتم إرسال التنبيهات تلقائيًا عند ظهور أى حركة قوية فى السوق.\n\n"
        "هذه الرسالة مرسلة للـ Owner فقط كتنبيه بأن النظام Online ✅"
    )


def run_startup_broadcast():
    """
    بعد تشغيل كل الثريدات وخلال أول ثوانى من التشغيل:
      - ننتظر STARTUP_BROADCAST_DELAY_SECONDS
      - نبعت رسالة افتتاحية للـ OWNER فقط (ADMIN_CHAT_ID)
      - من غير أى Broadcast لباقى الشاتات أو الأدمنات الإضافية.
    """
    global _STARTUP_BROADCAST_DONE

    # لو كانت اتبعت قبل كده فى نفس عمر البروسيس → منرجعش نبعتها تانى
    if _STARTUP_BROADCAST_DONE:
        return

    try:
        # تأخير بسيط علشان نتأكد إن كل حاجة اشتغلت (Webhook + Threads)
        time.sleep(STARTUP_BROADCAST_DELAY_SECONDS)

        text = _startup_broadcast_message()

        try:
            config.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=text,
                parse_mode="HTML",
                silent=False,
            )
            logger.info(
                "Startup broadcast sent to OWNER only (chat_id=%s).",
                ADMIN_CHAT_ID,
            )
        except Exception as e:
            logger.exception(
                "Startup broadcast failed for OWNER chat %s: %s",
                ADMIN_CHAT_ID,
                e,
            )

        _STARTUP_BROADCAST_DONE = True

    except Exception as e:
        # حتى لو حصل خطأ، منحبّش نكرر المحاولة بلا نهاية
        _STARTUP_BROADCAST_DONE = True
        logger.exception("Error in run_startup_broadcast: %s", e)


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
    """
    طلب GET مع Retry بسيط علشان Timeouts العشوائية.
    """
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
#   Broadcast Helpers
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


def broadcast_ultra_pro_to_all_chats(text: str, silent: bool = False) -> int:
    """
    إرسال تنبيه Ultra PRO لجميع الشاتات المسجلة + جروب التحذيرات.

    - كل الشاتات (Users + Groups) → نفس نص التحذير.
    - شاتات الأدمن (ADMIN_CHAT_ID + EXTRA_ADMINS) → نفس التحذير لكن مع زر "عرض التفاصيل 📊".
    """
    from config import KNOWN_CHAT_IDS, ALERT_TARGET_CHAT_ID, ADMIN_CHAT_ID

    total = 0

    # مجموعة الأدمنز (المالك + الأدمنات الإضافيين)
    admin_ids = {ADMIN_CHAT_ID}
    try:
        extra_admins = getattr(config, "EXTRA_ADMINS", set())
        if isinstance(extra_admins, (set, list, tuple, set)):
            admin_ids.update(extra_admins)
    except Exception:
        pass

    # الكيبورد الخاص بزر التفاصيل للأدمن فقط
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "عرض التفاصيل 📊",
                    "callback_data": "alert_details",
                }
            ]
        ]
    }

    # الشات الأساسى للتحذيرات (غالباً جروب/قناة)
    target_chat = getattr(config, "ALERT_TARGET_CHAT_ID", None) or ADMIN_CHAT_ID

    # أولاً: إرسال للتحذير الرئيسى (جروب/قناة أو الأدمن)
    try:
        if target_chat in admin_ids:
            # لو الشات الأساسى نفسه أدمن → نفس الرسالة + زر التفاصيل
            config.send_message_with_keyboard(target_chat, text, keyboard)
        else:
            # جروب/قناة للمستخدمين → رسالة عادية بدون زر
            config.send_message(target_chat, text, silent=silent)
        total += 1
    except Exception as e:
        logger.exception("Error sending Ultra PRO to main alert chat: %s", e)

    # ثانياً: إرسال لكل الشاتات المعروفة (Users + Admins)
    for cid in list(KNOWN_CHAT_IDS):
        # نتجنب تكرار الإرسال لنفس الشات
        if cid == target_chat:
            continue
        try:
            if cid in admin_ids:
                # أى أدمن → نفس التحذير + زر التفاصيل
                config.send_message_with_keyboard(cid, text, keyboard)
            else:
                # باقى المستخدمين → نفس التحذير بدون زر
                config.send_message(cid, text, silent=silent)
            total += 1
        except Exception as e:
            logger.exception(
                "Error sending Ultra PRO to chat %s: %s",
                cid,
                e,
            )

    logger.info(
        "Ultra PRO broadcast sent to %d chats (users + main group).",
        total,
    )
    return total


def _build_direction_hint(metrics: dict, pulse: dict, events: dict, alert_level: dict) -> str | None:
    """
    إضافة Hint بسيط للمستخدم عن اتجاه الحركة اللحظية (شراء / بيع).
    لا يغيّر من منطق Ultra PRO نفسه، بس يوضّح الإتجاه.
    """
    try:
        change = float(metrics.get("change_pct", 0.0))
    except Exception:
        change = 0.0

    liquidity_pulse = metrics.get("liquidity_pulse", "") or ""
    strength_label = metrics.get("strength_label", "") or ""
    txt = (liquidity_pulse + " " + strength_label).lower()

    speed_idx = float(pulse.get("speed_index", 0.0))
    accel_idx = float(pulse.get("accel_index", 0.0))

    momentum_up = bool(events.get("momentum_spike_up"))
    momentum_down = bool(events.get("momentum_spike_down"))
    panic_drop = bool(events.get("panic_drop"))

    level = alert_level.get("level")

    # منطق بسيط لتحديد الاتجاه الغالب
    direction = None

    # اندفاع بيعي واضح
    if (
        change <= -1.5
        or "هبوط" in txt
        or "خروج سيولة" in txt
        or "ضغوط بيعية" in txt
        or panic_drop
        or momentum_down
    ):
        direction = "sell"

    # اندفاع شرائي واضح
    if (
        change >= 1.5
        or "صعود" in txt
        or "الدخول" in txt
        or "تجميع" in txt
        or momentum_up
    ):
        # لو فى إثنين متعارضين نخلى الأقوى حسب التغير
        if direction is None or change > 2.5:
            direction = "buy"

    # لو مفيش اتجاه واضح أو المستوى None → مانزودش حاجة
    if not direction or level is None:
        return None

    # صياغة الرسالة الإضافية للمستخدم
    if direction == "sell":
        return (
            "📉 🔻 <b>قراءة سريعة للاتجاه اللحظى:</b>\n"
            "- الحركة الحالية تميل إلى <b>اندفاع بيعى</b> مع ضغط واضح على السعر.\n"
            "- يُنصح بالحذر من التسارع الهبوطى المفاجئ فى الفترات القصيرة."
        )

    if direction == "buy":
        return (
            "📈 🔼 <b>قراءة سريعة للاتجاه اللحظى:</b>\n"
            "- الحركة الحالية تميل إلى <b>اندفاع شرائى</b> وزيادة شهية المخاطرة.\n"
            "- يُنصح بالحذر من التقلبات السريعة بعد أى اختراقات رئيسية."
        )

    return None


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
        ttl=config.WEEKLY_REPORT_TTL,
    )
    if not text:
        logger.warning("No weekly report text generated.")
        return

    broadcast_message_to_group(text)


def send_weekly_report_to_all_chats() -> int:
    """
    إرسال التقرير الأسبوعى لكل الشاتات المسجلة (للـ endpoint /weekly_ai_report).
    يحافظ على منطق الشغل القديم + يستخدم الكاش.
    """
    from config import KNOWN_CHAT_IDS, ADMIN_CHAT_ID

    text = get_cached_response(
        "weekly_report",
        format_weekly_ai_report,
        ttl=config.WEEKLY_REPORT_TTL,
    )
    if not text:
        logger.warning("No weekly report text generated for send_weekly_report_to_all_chats.")
        return 0

    sent = 0
    # نرسل للأدمن أولًا (لو مش داخل فى KNOWN_CHAT_IDS)
    try:
        config.send_message(ADMIN_CHAT_ID, text)
        sent += 1
    except Exception as e:
        logger.exception("Failed sending weekly report to admin: %s", e)

    # نرسل لكل الشاتات المسجلة
    for cid in list(KNOWN_CHAT_IDS):
        # نتجنب التكرار لو الأدمن موجود ضمن KNOWN_CHAT_IDS
        if cid == ADMIN_CHAT_ID:
            continue
        try:
            config.send_message(cid, text)
            sent += 1
        except Exception as e:
            logger.exception("Failed sending weekly report to chat %s: %s", cid, e)

    logger.info("Weekly AI report sent to %d chats (admin + users).", sent)
    return sent


def weekly_scheduler_loop():
    """
    لوب بسيط يشغّل التقرير الأسبوعى فى وقت محدد كل أسبوع.
    - يستخدم WEEKLY_REPORT_WEEKDAY + WEEKLY_REPORT_HOUR_UTC من config.
    - يتأكد إن التقرير ميتبعتش أكتر من مرة فى نفس اليوم.
    """
    logger.info("Weekly scheduler loop started.")
    while True:
        try:
            config.LAST_WEEKLY_TICK = time.time()

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
            config.LAST_REALTIME_TICK = time.time()

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
#   Smart Alert Engine (Auto Ultra PRO) — V11
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
    لوب التحذير الذكى (Ultra PRO Auto) — V11 ULTRA:
      - مبنى على منطق V3/V10 + طبقة "Voting Engine V11".
      - محرّكات التصويت:
          * shock / speed / risk / early / momentum / direction_conf / real_move
          * harmonic / wave / ict (لو متاحة من snapshot)
      - لو فى توافق ≥ 3 محركات قوية → Alert حتى لو level = None.
      - إضافة Failsafe لحركة فعلية عنيفة (change كبير + مدى كبير).
    """
    logger.info("Smart alert loop started (V11 ULTRA).")
    _ = _ensure_bot()  # نتأكد إن البوت جاهز

    while True:
        try:
            # علامة نبض للـ Watchdog والـ /status
            config.LAST_SMART_ALERT_TICK = time.time()

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

            # إشارات إضافية (هارمونيك / موجى / ICT) لو التحليل بيطلّعها
            harmonic = (
                snapshot.get("harmonic")
                or snapshot.get("harmonic_signal")
                or {}
            )
            wave = (
                snapshot.get("wave")
                or snapshot.get("wave_signal")
                or snapshot.get("elliott")
                or {}
            )
            ict = (
                snapshot.get("ict")
                or snapshot.get("ict_signal")
                or {}
            )

            price = metrics["price"]
            change = metrics["change_pct"]
            range_pct = metrics["range_pct"]
            vol = metrics["volatility_score"]

            level = alert_level["level"]       # none / low / medium / high / critical
            shock_score = float(alert_level.get("shock_score") or 0.0)

            speed_idx = float(pulse.get("speed_index", 0.0))
            accel_idx = float(pulse.get("accel_index", 0.0))
            direction_conf = float(pulse.get("direction_confidence", 0.0))

            risk_score = float(risk.get("score") or 0.0)
            structural_risk = float(risk.get("structural_risk", 0.0) or 0.0)

            logger.info(
                "SmartAlert V11 snapshot: price=%s chg=%.3f range=%.2f vol=%.1f "
                "level=%s shock=%.1f speed=%.1f accel=%.2f conf=%.1f "
                "risk_score=%.1f structural_risk=%.1f",
                price,
                change,
                range_pct,
                vol,
                level,
                shock_score,
                speed_idx,
                accel_idx,
                direction_conf,
                risk_score,
                structural_risk,
            )

            # -----------------------------
            #   V11: composite & move intensity
            # -----------------------------
            composite_intensity = (
                0.4 * shock_score
                + 0.3 * speed_idx
                + 0.3 * abs(accel_idx) * 100.0 / 3.0
            )

            # مؤشر "حركة فعلية" من التغير + مدى اليوم
            move_intensity = (
                abs(change) * 8.0  # مثلا 2% → 16 نقطة
                + max(range_pct, 0.1) * 2.0
            )

            # ====== FORCE TEST ULTRA PRO (One-Shot, Full Path) ======
            if getattr(config, "FORCE_TEST_ULTRA_PRO", False):
                try:
                    text = format_ultra_pro_alert()
                    if text:
                        # Hint للاتجاه
                        try:
                            hint = _build_direction_hint(metrics, pulse, events, alert_level)
                            if hint:
                                text = f"{text}\n\n{hint}"
                        except Exception:
                            pass

                        # فى test mode نبعت بصوت واضح (بدون Silent)
                        sent_count = broadcast_ultra_pro_to_all_chats(text, silent=False)

                        now_ts = time.time()
                        now_iso = datetime.utcnow().isoformat(timespec="seconds")

                        config.LAST_SMART_ALERT_TS = now_ts
                        config.LAST_CRITICAL_ALERT_TS = now_ts

                        _append_alert_history(
                            price=price,
                            change=change,
                            level=level,
                            shock_score=shock_score,
                            immediate=True,
                        )

                        try:
                            config.LAST_SMART_ALERT_INFO = {
                                "time": now_iso,
                                "reason": "force_test",
                                "level": level or "TEST",
                                "shock_score": shock_score,
                                "risk_level": risk.get("level"),
                                "sent_to": getattr(config, "ALERT_TARGET_CHAT_ID", 0),
                                "sent_to_count": sent_count,
                            }
                        except Exception:
                            pass

                        logger.info(
                            "FORCE_TEST_ULTRA_PRO: sent test Ultra PRO alert to %s chats",
                            sent_count,
                        )
                finally:
                    try:
                        config.FORCE_TEST_ULTRA_PRO = False
                    except Exception:
                        pass

                time.sleep(config.SMART_ALERT_BASE_INTERVAL * 60)
                continue
            # ================================================================

            # -----------------------------
            #   منطق اتخاذ القرار الأساسى (زى V10 تقريبًا)
            # -----------------------------
            now_ts = time.time()
            last_alert_ts = getattr(config, "LAST_SMART_ALERT_TS", 0.0) or 0.0
            last_critical_ts = getattr(config, "LAST_CRITICAL_ALERT_TS", 0.0) or 0.0

            base_interval_min = max(0.5, float(config.SMART_ALERT_BASE_INTERVAL))  # بالدقايق
            adaptive_interval_min = float(
                snapshot.get("adaptive_interval", base_interval_min)
            )
            adaptive_interval_min = max(0.5, adaptive_interval_min)

            # 1) super_critical: حالة انهيار/اندفاع عنيف جدًا
            super_critical = (
                level in ("high", "critical")
                and shock_score >= 85
                and speed_idx >= 70
                and abs(accel_idx) >= 0.9
            )

            # 2) حالة حرجة قوية لكن ليست قصوى
            immediate_condition = (
                level in ("high", "critical")
                and composite_intensity >= 70
            ) or (
                risk_score >= 75
                and shock_score >= 60
                and speed_idx >= 60
            )

            # 3) Early warning قوى قبل الحركة بدقائق
            early_signal = None
            early_condition = False
            try:
                from analysis_engine import detect_early_movement_signal

                early_signal = detect_early_movement_signal(
                    metrics,
                    pulse,
                    events,
                    risk,
                )
                if (
                    early_signal
                    and early_signal.get("active")
                    and float(early_signal.get("score", 0.0)) >= config.EARLY_WARNING_THRESHOLD
                ):
                    early_condition = True
            except Exception:
                early_signal = None
                early_condition = False

            # 4) نبض حركة عنيفة حتى لو level لسه medium
            momentum_condition = False
            if (
                level in ("medium", "high", "critical")
                and abs(change) >= 1.2
                and speed_idx >= 55
                and abs(accel_idx) >= 0.6
                and vol >= 3.0
            ):
                momentum_condition = True

            # -----------------------------
            #   V11 Voting Engine — Harmonic / Wave / ICT + باقى المحركات
            # -----------------------------
            # Harmonic vote
            harmonic_active = False
            try:
                h_score = float(harmonic.get("score", 0.0) or 0.0)
                harmonic_active = bool(harmonic.get("active")) or h_score >= 70.0
            except Exception:
                harmonic_active = False

            # Wave / Elliott vote
            wave_active = False
            try:
                w_score = float(wave.get("score", 0.0) or 0.0)
                wave_active = bool(wave.get("active")) or w_score >= 70.0
            except Exception:
                wave_active = False

            # ICT vote (killzones / liquidity zones / displacement)
            ict_active = False
            try:
                i_score = float(ict.get("score", 0.0) or 0.0)
                ict_active = (
                    bool(ict.get("active"))
                    or bool(ict.get("killzone_alert"))
                    or i_score >= 65.0
                )
            except Exception:
                ict_active = False

            v11_votes = {
                "shock": shock_score >= 60,
                "speed": (speed_idx >= 55 and abs(accel_idx) >= 0.6),
                "risk": risk_score >= 70 or structural_risk >= 60,
                "early": early_condition,
                "momentum": momentum_condition,
                "direction_conf": abs(direction_conf) >= 65.0,
                # حركة فعلية أعلى من threshold محترم
                "real_move": (move_intensity >= 25.0),
                "harmonic": harmonic_active,
                "wave": wave_active,
                "ict": ict_active,
            }
            v11_agree_count = sum(1 for v in v11_votes.values() if v)

            # -----------------------------
            #   تحديد نوع التنبيه + الفجوة الزمنية
            # -----------------------------
            send_immediate = False
            send_normal = False
            alert_flavor = None  # super_critical / immediate / early / momentum / normal / v11_consensus / failsafe_move

            # الفاصل الزمني للحالات الحرجة (أقصر)
            critical_gap = max(180.0, adaptive_interval_min * 60 * 0.4)  # ~3 دقائق كحد أدنى
            # الفاصل الزمني للحالات العادية (أطول)
            normal_gap = max(1200.0, adaptive_interval_min * 60 * 0.8)  # ~20 دقيقة كحد أدنى

            # super_critical يغلب على أى شىء
            if super_critical:
                if (now_ts - last_critical_ts) >= critical_gap / 2:
                    send_immediate = True
                    alert_flavor = "super_critical"
                else:
                    logger.info(
                        "Super-critical condition detected but still inside hard gap (%.1fs), skip.",
                        critical_gap / 2,
                    )
            else:
                if immediate_condition:
                    if (now_ts - last_critical_ts) >= critical_gap:
                        send_immediate = True
                        alert_flavor = "immediate"
                    else:
                        logger.info(
                            "Immediate condition detected but within critical gap (%.1fs), skip.",
                            critical_gap,
                        )
                elif early_condition:
                    # إنذار مبكر → نسمح بفاصل أقل لكن مع Silent
                    if (now_ts - last_alert_ts) >= critical_gap / 1.5:
                        send_immediate = True
                        alert_flavor = "early"
                    else:
                        logger.info(
                            "Early warning detected but within early gap (%.1fs), skip.",
                            critical_gap / 1.5,
                        )
                elif momentum_condition:
                    if (now_ts - last_alert_ts) >= normal_gap / 2:
                        send_immediate = True
                        alert_flavor = "momentum"
                    else:
                        logger.info(
                            "Momentum condition detected but within momentum gap (%.1fs), skip.",
                            normal_gap / 2,
                        )
                else:
                    # مفيش conditions قوية لكن المستوى العام medium/high
                    if level in ("medium", "high", "critical") and (
                        now_ts - last_alert_ts
                    ) >= normal_gap:
                        send_normal = True
                        alert_flavor = "normal"

            # 👇 V11: توافق عالى بين المحركات حتى لو level = None
            if not (send_immediate or send_normal):
                if v11_agree_count >= 3 and (composite_intensity >= 60 or move_intensity >= 30):
                    # نمنع السبام برضه بفاصل زمنى معقول
                    if (now_ts - last_alert_ts) >= normal_gap / 2:
                        send_immediate = True
                        alert_flavor = "v11_consensus"
                        logger.info(
                            "V11 consensus alert fired: votes=%d, composite=%.1f, move_intensity=%.1f",
                            v11_agree_count,
                            composite_intensity,
                            move_intensity,
                        )
                    else:
                        logger.info(
                            "V11 consensus detected but within gap (%.1fs), skip.",
                            normal_gap / 2,
                        )

            # 👇 failsafe: لو الحركة عنيفة جداً بغض النظر عن level
            if not (send_immediate or send_normal):
                if abs(change) >= 3.0 and move_intensity >= 35.0:
                    if (now_ts - last_alert_ts) >= normal_gap:
                        send_immediate = True
                        alert_flavor = "failsafe_move"
                        logger.info(
                            "Failsafe move alert fired: change=%.2f move_intensity=%.1f",
                            change,
                            move_intensity,
                        )

            # -----------------------------
            #   إرسال التنبيه (Ultra PRO Alert)
            # -----------------------------
            reason_text = None
            sent_count = 0

            if send_immediate or send_normal:
                text = format_ultra_pro_alert()
                if text:
                    # Header حسب نوع التحذير
                    header_lines = []
                    if alert_flavor == "super_critical":
                        header_lines.append(
                            "☠️🔥 <b>تحذير حرج جدًا — حركة عنيفة محتملة على البيتكوين</b>\n"
                            "⚠️ هذا النوع من التحذيرات نادر ويعبر عن <b>احتمال عالى لانفجار سعرى</b>."
                        )
                    elif alert_flavor == "immediate":
                        header_lines.append(
                            "🚨 <b>تحذير قوى من IN CRYPTO Ai</b>\n"
                            "السوق يظهر <b>زخمًا حادًا</b> واحتمال حركة كبيرة فى وقت قصير."
                        )
                    elif alert_flavor == "early":
                        header_lines.append(
                            "⚠️ <b>إنذار مبكر — السوق يجهّز لحركة قوية محتملة</b>\n"
                            "هذه إشارة استباقية قبل اكتمال الانفجار، الهدف منها التنبيه المبكر فقط."
                        )
                    elif alert_flavor == "momentum":
                        header_lines.append(
                            "🔥 <b>زخم قوى جارٍ الآن فى السوق</b>\n"
                            "هناك اندفاع واضح على البيتكوين قد يتطور لحركة أكبر."
                        )
                    elif alert_flavor == "normal":
                        header_lines.append(
                            "📡 <b>تنبيه من IN CRYPTO Ai — السوق نشط حاليًا</b>"
                        )
                    elif alert_flavor == "v11_consensus":
                        header_lines.append(
                            "🧠⚡ <b>تحذير V11 — توافق قوى بين محرّكات الذكاء الاصطناعى</b>\n"
                            "أكثر من محرّك داخلى متفق على وجود حركة خطرة تستحق التنبيه الآن."
                        )
                    elif alert_flavor == "failsafe_move":
                        header_lines.append(
                            "🚨 <b>تحذير تلقائى — حركة سعرية عنيفة مكتملة</b>\n"
                            "تم تفعيل هذا التحذير لأن الحركة الحالية على البيتكوين تعدّت حدود الأمان الفعلية "
                            "حتى لو مؤشرات أخرى ماكتملتش بالكامل."
                        )

                    # Hint للاتجاه (شراء/بيع)
                    try:
                        hint = _build_direction_hint(metrics, pulse, events, alert_level)
                        if hint:
                            header_lines.append(hint)
                    except Exception:
                        pass

                    # بلوك إضافى للإنذار المبكر لو موجود
                    if alert_flavor == "early" and early_signal:
                        try:
                            e_dir = early_signal.get("direction")
                            if e_dir == "down":
                                dir_txt = "هبوط حاد محتمل"
                                emoji = "🔻"
                            elif e_dir == "up":
                                dir_txt = "اندفاع صاعد محتمل"
                                emoji = "🔼"
                            else:
                                dir_txt = "حركة قوية محتملة"
                                emoji = "⚠️"

                            e_score = float(early_signal.get("score", 0.0))
                            e_conf = float(early_signal.get("confidence", 0.0))
                            e_win = int(early_signal.get("window_minutes") or 10)
                            e_reason = early_signal.get("reason") or "إشارة مبكرة لحركة قوية."

                            early_block = (
                                f"{emoji} <b>تفاصيل الإنذار المبكر:</b>\n"
                                f"- الاتجاه المرجح: <b>{dir_txt}</b>\n"
                                f"- قوة الإشارة: <b>{e_score:.1f}/100</b>\n"
                                f"- درجة الثقة: <b>{e_conf:.1f}%</b>\n"
                                f"- نافذة زمنية تقديرية: خلال ~<b>{e_win} دقيقة</b>\n"
                                f"- سبب الإشارة: {e_reason}"
                            )
                            header_lines.append(early_block)
                        except Exception:
                            pass

                    # V11: نعرض المحركات اللى كانت On فى اللوج للمستخدم
                    try:
                        active_engines = [k for k, v in v11_votes.items() if v]
                        if active_engines:
                            engines_txt = ", ".join(active_engines)
                            header_lines.append(
                                f"🧪 <b>المحرّكات المتفقة فى هذا التحذير:</b> {engines_txt}"
                            )
                    except Exception:
                        pass

                    if header_lines:
                        header_text = "\n\n".join(header_lines)
                        text = f"{header_text}\n\n━━━━━━━━━━\n{text}"

                    # تحديد Silent أو لا حسب نوع التحذير
                    if alert_flavor in ("super_critical", "immediate", "v11_consensus", "failsafe_move"):
                        silent_flag = False
                    elif alert_flavor in ("early", "momentum", "normal"):
                        silent_flag = True
                    else:
                        silent_flag = True

                    # إرسال للجروب + كل المستخدمين المسجلين (مع زر للأدمن)
                    sent_count = broadcast_ultra_pro_to_all_chats(text, silent=silent_flag)

                    config.LAST_SMART_ALERT_TS = now_ts
                    if alert_flavor in ("super_critical", "immediate", "v11_consensus", "failsafe_move"):
                        config.LAST_CRITICAL_ALERT_TS = now_ts

                    if alert_flavor is None:
                        reason_text = "unknown"
                    else:
                        reason_text = alert_flavor

                    _append_alert_history(
                        price=price,
                        change=change,
                        level=level,
                        shock_score=shock_score,
                        immediate=(alert_flavor in ("super_critical", "immediate", "v11_consensus", "failsafe_move")),
                    )

                    # تحديث حالة LAST_SMART_ALERT_INFO للـ dashboard
                    try:
                        config.LAST_SMART_ALERT_INFO = {
                            "time": datetime.utcnow().isoformat(timespec="seconds"),
                            "reason": reason_text,
                            "level": level,
                            "shock_score": shock_score,
                            "risk_level": risk.get("level"),
                            "sent_to": getattr(config, "ALERT_TARGET_CHAT_ID", 0),
                            "sent_to_count": sent_count,
                            "votes": v11_votes,
                            "composite_intensity": composite_intensity,
                            "move_intensity": move_intensity,
                            "structural_risk": structural_risk,
                        }
                    except Exception:
                        pass

            # -----------------------------
            #   نوم تكيفى بين الدورات
            # -----------------------------
            if (
                super_critical
                or immediate_condition
                or early_condition
                or momentum_condition
                or (v11_agree_count >= 3)
            ):
                # فى الأجواء الساخنة أو توافق محركات عالى نتابع أسرع
                sleep_seconds = max(15.0, adaptive_interval_min * 60 * 0.3)
            else:
                sleep_seconds = max(60.0, adaptive_interval_min * 60 * 0.7)

            logger.debug("Smart alert V11 loop sleep: %.1fs", sleep_seconds)
            time.sleep(sleep_seconds)

        except Exception as e:
            logger.exception("Error in smart_alert_loop (V11): %s", e)
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
#   System Status (/status)
# =====================================================


def handle_admin_status_command(chat_id: int):
    bot = _ensure_bot()
    text = get_system_status()
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def get_system_status() -> str:
    now = time.time()

    def fmt(seconds):
        if seconds <= 0:
            return "❓ لا يوجد بيانات"
        mins = seconds / 60
        if mins < 1:
            return f"{int(seconds)} ثانية"
        return f"{mins:.1f} دقيقة"

    rt = now - (getattr(config, "LAST_REALTIME_TICK", 0) or 0)
    sa = now - (getattr(config, "LAST_SMART_ALERT_TICK", 0) or 0)
    wd = now - (getattr(config, "LAST_WATCHDOG_TICK", 0) or 0)
    wk = now - (getattr(config, "LAST_WEEKLY_TICK", 0) or 0)
    ka = now - (getattr(config, "LAST_KEEP_ALIVE_OK", 0) or 0)

    return f"""
<b>🛰 نظام مراقبة البوت — IN CRYPTO Ai</b>

<b>⏱ آخر نشاط للأنظمة:</b>
🔹 Realtime: <code>{fmt(rt)}</code>
🔹 Smart Alert: <code>{fmt(sa)}</code>
🔹 Watchdog: <code>{fmt(wd)}</code>
🔹 Weekly Scheduler: <code>{fmt(wk)}</code>
🔹 Keep-Alive: <code>{fmt(ka)}</code>

<b>📌 الحالة العامة:</b>
- Realtime: {"🟢 شغال" if rt < 120 else "🔴 متوقف"}
- Smart Alert: {"🟢 شغال" if sa < 180 else "🔴 متوقف"}
- Watchdog: {"🟢 متوقف" if wd > 180 else "🟢 شغال"}
- Keep-Alive: {"🟢 نشط" if ka < 600 else "🔴 قد يكون معطل"}

<b>⚙️ Supervisor:</b> 🟢 يعمل بشكل دائم

<b>IN CRYPTO AI — System Status</b>
""".strip()


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
    config.add_alert_history(
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
    from config import ALERT_TARGET_CHAT_ID, send_message as _send

    # بناء Ultra PRO
    text = format_ultra_pro_alert()
    if not text:
        _send(
            admin_chat_id,
            "⚠️ لا توجد حركة قوية كافية حالياً لإرسال Ultra PRO Alert.\n"
            "جرّب لاحقاً عند ظهور زخم واضح."
        )
        return

    # إرسال للجروب
    _send(ALERT_TARGET_CHAT_ID, text)

    # تأكيد للأدمن
    _send(
        admin_chat_id,
        "✅ تم إرسال Ultra PRO Alert للمستخدمين بنجاح.\n\n"
        "📌 تم الإرسال إلى:\n"
        f"<code>{ALERT_TARGET_CHAT_ID}</code>"
    )

    # تسجيل فى السجل
    config.add_alert_history("broadcast_ultra", "Ultra PRO broadcast via /alert_pro")


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
            config.LAST_WATCHDOG_TICK = time.time()

            bot = _ensure_bot()
            me = bot.get_me()
            logger.debug("Bot is alive as @%s", me.username)
        except Exception as e:
            logger.exception("Watchdog error: %s", e)
        time.sleep(config.WATCHDOG_INTERVAL)


# =====================================================
#   Anti-Sleep / Keep-Alive Loop
# =====================================================


def keep_alive_loop():
    """
    لوب بسيط لمنع السيرفر (Koyeb) من الدخول فى حالة Sleep:
      - بيعمل Ping كل شوية على نفس التطبيق.
      - يعتمد على:
        * config.KEEP_ALIVE_URL  لو موجودة
        * وإلا يستخدم URL الافتراضى لتطبيقك على Koyeb
      - يكتب آخر نجاح فى config.LAST_KEEP_ALIVE_OK (اختيارى)
    """
    logger.info("Keep-alive loop started.")

    # تقدر تغير الـ URL من config لو حابب:
    default_url = "https://dizzy-bab-incrypto-free-258377c4.koyeb.app/"
    url = getattr(config, "KEEP_ALIVE_URL", default_url)

    # الفاصل الزمنى بين كل Ping (ثوانى) - تقدر تعدله من config
    interval_seconds = getattr(config, "KEEP_ALIVE_INTERVAL", 240)

    while True:
        try:
            config.LAST_KEEP_ALIVE_TICK = time.time()

            resp = http_get(url, timeout=10)
            if resp is not None:
                logger.debug(
                    "Keep-alive ping OK: %s %s",
                    resp.status_code,
                    url,
                )
                try:
                    # نخزن آخر وقت نجاح بشكل اختيارى
                    config.LAST_KEEP_ALIVE_OK = time.time()
                except Exception:
                    pass
            else:
                logger.warning("Keep-alive ping failed (no response object).")
        except Exception as e:
            logger.exception("Error in keep_alive_loop: %s", e)

        time.sleep(interval_seconds)


# =====================================================
#   Supervisor Loop (IMMORTAL MODE)
# =====================================================


def supervisor_loop():
    """
    لوب مراقبة مركزى:
      - يتابع نبض كل اللوپس (Ticks)
      - لو فيه Loop واقف (مفيش Heartbeat) → يسجل تحذير واضح فى اللوج.
    """
    logger.info("Supervisor loop started.")
    # thresholds بالثوانى (قيمة عالية شوية علشان مايبقاش Aggressive قوى)
    REALTIME_TIMEOUT = 60.0        # لو مفيش نبض من realtime لمدة دقيقة
    SMART_ALERT_TIMEOUT = 300.0    # لو مفيش نبض من smart alert دقيقتين
    WATCHDOG_TIMEOUT = 90.0        # لو مفيش نبض من watchdog دقيقة ونص
    WEEKLY_TIMEOUT = 3600.0 * 8    # 8 ساعات (كافى جداً)
    KEEPALIVE_TIMEOUT = 600.0      # 10 دقايق

    while True:
        try:
            now = time.time()

            # RealTime
            rt = getattr(config, "LAST_REALTIME_TICK", 0.0) or 0.0
            if rt and (now - rt) > REALTIME_TIMEOUT:
                logger.warning(
                    "Supervisor: Realtime engine tick stale (%.1fs).",
                    now - rt,
                )

            # Smart Alert
            sa = getattr(config, "LAST_SMART_ALERT_TICK", 0.0) or 0.0
            if sa and (now - sa) > SMART_ALERT_TIMEOUT:
                logger.warning(
                    "Supervisor: Smart alert loop tick stale (%.1fs).",
                    now - sa,
                )

            # Watchdog
            wd = getattr(config, "LAST_WATCHDOG_TICK", 0.0) or 0.0
            if wd and (now - wd) > WATCHDOG_TIMEOUT:
                logger.warning(
                    "Supervisor: Watchdog loop tick stale (%.1fs).",
                    now - wd,
                )

            # Weekly
            wk = getattr(config, "LAST_WEEKLY_TICK", 0.0) or 0.0
            if wk and (now - wk) > WEEKLY_TIMEOUT:
                logger.warning(
                    "Supervisor: Weekly scheduler tick stale (%.1fs).",
                    now - wk,
                )

            # Keep-Alive
            ka = getattr(config, "LAST_KEEP_ALIVE_OK", 0.0) or 0.0
            if ka and (now - ka) > KEEPALIVE_TIMEOUT:
                logger.warning(
                    "Supervisor: Keep-alive last OK stale (%.1fs).",
                    now - ka,
                )

        except Exception as e:
            logger.exception("Error in supervisor_loop: %s", e)

        # Military Mode لكن بدون استهلاك مبالغ فيه
        time.sleep(30.0)


# =====================================================
#   Threads Starter
# =====================================================


def start_background_threads(force: bool = False):
    """
    تشغيل كل اللوپس الخلفية:
      - Weekly Scheduler
      - Realtime Engine
      - Smart Alert (V11)
      - Watchdog
      - Keep-Alive (Anti-Sleep)
      - Supervisor (IMMORTAL MODE)
      - Startup Broadcast (رسالة افتتاح بعد الريستارت — OWNER فقط)
    """
    if getattr(config, "THREADS_STARTED", False) and not force:
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

    # 🔥 ثريد منع الـ Sleep
    keep_alive_thread = threading.Thread(
        target=keep_alive_loop,
        name="keep_alive",
        daemon=True,
    )
    keep_alive_thread.start()

    # 🔥 Supervisor المركزى
    supervisor_thread = threading.Thread(
        target=supervisor_loop,
        name="supervisor",
        daemon=True,
    )
    supervisor_thread.start()

    # 🔔 Startup broadcast بعد تشغيل كل الثريدات (يتبعت مرة واحدة بس بعد ثوانى) — OWNER فقط
    startup_thread = threading.Thread(
        target=run_startup_broadcast,
        name="startup_broadcast",
        daemon=True,
    )
    startup_thread.start()

    config.THREADS_STARTED = True
    logger.info("All background threads started (including keep-alive, supervisor & startup broadcast).")
# ==============================
#   SCHOOL CACHE (60s)
# ==============================
import time
from typing import Callable, Any

# كاش مستقل للمدارس
SCHOOL_RESPONSE_CACHE: dict = {}
SCHOOL_CACHE_TTL: float = 60.0  # ثانية


def _now_ts() -> float:
    return time.time()


def _school_cache_get(key: str) -> str | None:
    """
    جلب نتيجة مدرسة من الكاش لو صالحة
    """
    try:
        item = SCHOOL_RESPONSE_CACHE.get(key)
        if not item:
            return None

        text, ts = item
        if (_now_ts() - ts) <= SCHOOL_CACHE_TTL:
            return text

        # انتهت الصلاحية
        SCHOOL_RESPONSE_CACHE.pop(key, None)
        return None
    except Exception:
        return None


def _school_cache_set(key: str, text: str):
    """
    تخزين نتيجة مدرسة في الكاش
    """
    try:
        SCHOOL_RESPONSE_CACHE[key] = (text, _now_ts())
    except Exception:
        pass


def get_school_cached_response(
    school_name: str,
    symbol: str,
    generator: Callable[[], str],
) -> str:
    """
    Wrapper عام لكل مدارس التحليل + ALL SCHOOLS
    """
    cache_key = f"school:{school_name}:{symbol}"

    cached = _school_cache_get(cache_key)
    if cached:
        return cached

    # توليد جديد
    text = generator()
    if text:
        _school_cache_set(cache_key, text)

    return text
# =====================================================
#   SCHOOL 1: Classical TA — ULTRA
# =====================================================

def generate_classical_ta_school(symbol: str, timeframe: str) -> str:
    """
    Classical Technical Analysis — Ultra Expanded
    يعتمد على الاتجاه، الزخم، المتوسطات، الدعوم والمقاومات، النماذج.
    """
    try:
        from analysis_engine import get_market_metrics_cached

        metrics = get_market_metrics_cached(symbol=symbol, timeframe=timeframe)
        if not metrics:
            return "⚠️ تعذّر جلب بيانات التحليل الفني الكلاسيكي حاليًا."

        trend = metrics.get("trend", "غير واضح")
        price = metrics.get("price")
        change = metrics.get("change_pct")

        ema50 = metrics.get("ema50")
        ema200 = metrics.get("ema200")
        rsi = metrics.get("rsi")
        macd = metrics.get("macd_signal")

        support = metrics.get("support")
        resistance = metrics.get("resistance")

        trend_comment = (
            "اتجاه صاعد" if ema50 and ema200 and ema50 > ema200 else
            "اتجاه هابط" if ema50 and ema200 and ema50 < ema200 else
            "اتجاه عرضي"
        )

        rsi_state = (
            "تشبع شرائي" if rsi and rsi >= 70 else
            "تشبع بيعي" if rsi and rsi <= 30 else
            "حيادي"
        )

        macd_state = "إيجابي" if macd == "bullish" else "سلبي" if macd == "bearish" else "محايد"

        return f"""
📘 <b>Classical TA — التحليل الفني الكلاسيكي (Ultra)</b>
━━━━━━━━━━━━━━━━━━
🔍 <b>العملة:</b> {symbol}
⏱ <b>الإطار الزمني:</b> {timeframe}

📈 <b>الاتجاه العام:</b>
• الاتجاه: <b>{trend}</b>
• توصيف الاتجاه: <b>{trend_comment}</b>

📊 <b>الزخم:</b>
• RSI: <b>{rsi}</b> ({rsi_state})
• MACD: <b>{macd_state}</b>

📐 <b>المتوسطات المتحركة:</b>
• EMA50: {ema50}
• EMA200: {ema200}

📉 <b>الدعوم والمقاومات:</b>
• دعم مهم: <b>{support}</b>
• مقاومة مهمة: <b>{resistance}</b>

⚠️ <b>ملاحظة:</b>
التحليل الكلاسيكي يعتمد على السياق العام ويُفضّل دمجه مع مدارس أخرى.

📌 <b>IN CRYPTO AI — Classical TA Engine</b>
""".strip()

    except Exception as e:
        logger.exception("Error in Classical TA school: %s", e)
        return "⚠️ حدث خطأ أثناء توليد التحليل الفني الكلاسيكي."


def get_classical_ta_school(symbol: str, timeframe: str) -> str:
    """
    واجهة الكاش لمدرسة Classical TA
    """
    return get_school_cached_response(
        school_name="classical_ta",
        symbol=f"{symbol}:{timeframe}",
        generator=lambda: generate_classical_ta_school(symbol, timeframe),
)
