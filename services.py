# ==========================================
#              SERVICES MODULE
#      (Realtime Engine + Weekly + Snapshot)
#   + Smart Alert Engine (Institutional-Grade)
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
    compute_smart_market_snapshot,  # ✅ محرك التحليل الذكى الجديد
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

            # ===== بناء الردود الأساسية =====
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
#   Smart Alert Engine Loop
#   (Institutional-Grade + Turbo Mode)
# ==============================

def smart_alert_loop():
    """
    يراقب السوق فى الزمن الحقيقى باستخدام compute_smart_market_snapshot():
        - يجلب Metrics + Risk + Pulse + Events + Zones
        - يحسب مستوى التحذير (low / medium / high / critical)
        - يمنع تكرار نفس التحذير (anti-spam)
        - يرسل تنبيهات مختصرة احترافية لكل KNOWN_CHAT_IDS
        - يستخدم فترة فحص تكيفية (1–5 ثوانى) + Turbo Mode (0.2–0.5 ثانية)
    """
    # عند بدء اللوب نحدث مؤشر الـ Tick
    config.LAST_SMART_ALERT_TICK = time.time()
    config.logger.info("Smart alert loop started.")

    while True:
        try:
            now = time.time()
            config.LAST_SMART_ALERT_TICK = now

            snapshot = compute_smart_market_snapshot()
            if not snapshot:
                # فى حالة فشل جلب البيانات – ننتظر على الفترة القصوى
                config.LAST_SMART_ALERT_INFO = {
                    "time": datetime.utcnow().isoformat(timespec="seconds"),
                    "reason": "metrics_unavailable",
                    "level": None,
                    "shock_score": None,
                    "risk_level": None,
                    "sent_to": 0,
                    "reason_key": None,
                }
                time.sleep(getattr(config, "SMART_ALERT_MAX_INTERVAL", 5.0))
                continue

            metrics = snapshot["metrics"]
            risk = snapshot["risk"]
            pulse = snapshot["pulse"]
            events = snapshot["events"]
            alert_level = snapshot["alert_level"]
            zones = snapshot["zones"]
            base_interval = snapshot.get(
                "adaptive_interval",
                getattr(config, "SMART_ALERT_MAX_INTERVAL", 5.0),
            )
            reason_text = snapshot.get("reason")

            # لا يوجد مستوى تحذير فعّال → فقط نحدّث المعلومات وننام
            if alert_level["level"] is None or not reason_text:
                config.LAST_SMART_ALERT_INFO = {
                    "time": datetime.utcnow().isoformat(timespec="seconds"),
                    "reason": "no_alert",
                    "level": None,
                    "shock_score": alert_level["shock_score"],
                    "risk_level": risk["level"],
                    "sent_to": 0,
                    "reason_key": None,
                }
                time.sleep(base_interval)
                continue

            level = alert_level["level"]
            shock = alert_level["shock_score"]
            change = metrics["change_pct"]
            price = metrics["price"]
            speed = pulse["speed_index"]
            direction_conf = pulse["direction_confidence"]
            scenario = zones["dominant_scenario"]

            active_labels = events.get("active_labels", [])
            key_labels = ", ".join(active_labels[:2]) if active_labels else "none"

            # 🔁 Anti-repeat key → يمنع نفس التحذير (نفس المستوى + نفس الأحداث + نفس السيناريو) من التكرار
            reason_key = f"{level}|{int(shock)}|{scenario}|{key_labels}"

            last_info = getattr(config, "LAST_SMART_ALERT_INFO", None)
            if last_info and last_info.get("reason_key") == reason_key:
                # نفس التحذير سبق إرساله – نكتفى بتحديث الوقت داخليًا
                time.sleep(base_interval)
                continue

            # ==============================
            #   تحديد الـ Emoji + Silent
            # ==============================
            if level == "critical":
                emoji = "🚨"
                silent = False
            elif level == "high":
                emoji = "🔴"
                silent = False
            elif level == "medium":
                emoji = "🟠"
                silent = True
            else:  # low
                emoji = "🟡"
                silent = True

            # ==============================
            #   Turbo Mode Logic
            # ==============================

            turbo_active = False
            effective_interval = base_interval

            # Turbo Mode لو فى Panic Drop / Liquidity Shock / Vol Explosion مع High أو Critical
            if (
                (events.get("panic_drop") or events.get("liquidity_shock") or events.get("vol_explosion"))
                and level in ("high", "critical")
            ):
                turbo_active = True
                # نقلل الفترة ولكن نضمن عدم النزول أقل من 0.2 ثانية – وعدم تجاوز 0.5
                effective_interval = min(base_interval, 0.5)
                if effective_interval < 0.2:
                    effective_interval = 0.2

            # معايير عرض السرعة
            if speed >= 70:
                speed_label = "Very High"
            elif speed >= 40:
                speed_label = "High"
            elif speed >= 20:
                speed_label = "Medium"
            else:
                speed_label = "Low"

            # ==============================
            #   بناء نص الرسالة المختصر
            # ==============================

            dz1_low, dz1_high = zones["downside_zone_1"]
            dz2_low, dz2_high = zones["downside_zone_2"]
            uz1_low, uz1_high = zones["upside_zone_1"]
            uz2_low, uz2_high = zones["upside_zone_2"]

            lines: list[str] = []

            # سطر العنوان
            lines.append(
                f"{emoji} <b>Smart Alert — {level.upper()}</b>"
            )
            lines.append(
                f"BTC ي{'هبط' if change < 0 else 'تحرك بقوة'} بسرعة %{change:+.2f} — Shock {shock:.1f}/100 — Speed: {speed_label}"
            )

            # الأحداث النشطة
            if active_labels:
                lines.append("\n📌 <b>أحداث نشطة:</b>")
                lines.append(" / ".join(active_labels[:3]))

            # مناطق الهبوط/الصعود المحتملة
            if scenario in ("downside", "balanced"):
                lines.append("\n📉 <b>مناطق هبوط محتملة (تقريبية):</b>")
                lines.append(f"• {dz1_low:,.0f} → {dz1_high:,.0f}")
                lines.append(f"• {dz2_low:,.0f} → {dz2_high:,.0f}")

            if scenario in ("upside", "balanced"):
                lines.append("\n📈 <b>مناطق صعود محتملة (تقريبية):</b>")
                lines.append(f"• {uz1_low:,.0f} → {uz1_high:,.0f}")
                lines.append(f"• {uz2_low:,.0f} → {uz2_high:,.0f}")

            # ثقة الاتجاه + Turbo Mode Info
            lines.append(
                f"\n⚡ <b>الاتجاه اللحظى:</b> ثقة ~{direction_conf:.0f}%"
            )
            if turbo_active:
                lines.append(
                    f"⏱ <b>Turbo Mode مفعل</b> (فحص كل {effective_interval:.2f} ثانية)"
                )
            else:
                lines.append(
                    f"⏱ الفحص الدورى الحالى كل ~{effective_interval:.2f} ثانية."
                )

            # تحذير تعليمى بسيط (سطر واحد فقط)
            lines.append(
                "\nℹ️ المستويات تقريبية تعليمية وليست توصية مباشرة بالشراء أو البيع."
            )

            alert_text = "\n".join(lines)

            # ==============================
            #   إرسال التنبيه لكل المستخدمين
            # ==============================

            sent_to = 0
            for chat_id in list(config.KNOWN_CHAT_IDS):
                try:
                    config.send_message(chat_id, alert_text, silent=silent)
                    sent_to += 1
                except Exception as e:
                    config.logger.exception(
                        "Smart alert send failed for chat %s: %s",
                        chat_id,
                        e,
                    )

            # تحديث الحالة العامة للتحذيرات الذكية + LAST_ALERT_REASON
            config.LAST_ALERT_REASON = reason_text
            config.LAST_SMART_ALERT_INFO = {
                "time": datetime.utcnow().isoformat(timespec="seconds"),
                "reason": reason_text,
                "level": level,
                "shock_score": shock,
                "risk_level": risk["level"],
                "sent_to": sent_to,
                "reason_key": reason_key,
            }

            # إضافة للتاريخ
            try:
                config.add_alert_history(
                    "smart",
                    f"{level}: {reason_text}",
                    price=price,
                    change=change,
                )
            except Exception as e:
                config.logger.exception("Failed to add smart alert history: %s", e)

            config.logger.info(
                "Smart alert sent: level=%s shock=%.1f sent_to=%d key=%s",
                level,
                shock,
                sent_to,
                reason_key,
            )

            time.sleep(effective_interval)

        except Exception as e:
            config.logger.exception("Error in smart_alert_loop: %s", e)
            # فى حالة الخطأ، ننتظر الفترة القصوى لتجنب ضغط زائد
            time.sleep(getattr(config, "SMART_ALERT_MAX_INTERVAL", 5.0))


# ==============================
#      Watchdog Loop (Anti-Freeze)
# ==============================

def watchdog_loop():
    """
    يراقب:
        - Realtime Engine
        - Weekly Scheduler
        - Smart Alert Loop
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
                    config.logger.warning(
                        "Watchdog: realtime engine seems stalled (%.1f s).",
                        rt_delta,
                    )
                    if not any(t.name == "RealtimeEngine" for t in threading.enumerate()):
                        config.logger.warning(
                            "Watchdog: restarting realtime engine thread."
                        )
                        start_realtime_thread()

            # Weekly scheduler
            if config.LAST_WEEKLY_TICK:
                ws_delta = now - config.LAST_WEEKLY_TICK
                if ws_delta > 300:
                    config.logger.warning(
                        "Watchdog: weekly scheduler seems stalled (%.1f s).",
                        ws_delta,
                    )
                    if not any(t.name == "WeeklyScheduler" for t in threading.enumerate()):
                        config.logger.warning(
                            "Watchdog: restarting weekly scheduler thread."
                        )
                        start_weekly_scheduler_thread()

            # Smart Alert loop
            if getattr(config, "LAST_SMART_ALERT_TICK", 0.0):
                sa_delta = now - config.LAST_SMART_ALERT_TICK
                if sa_delta > 30:
                    config.logger.warning(
                        "Watchdog: smart alert loop seems stalled (%.1f s).",
                        sa_delta,
                    )
                    if not any(t.name == "SmartAlert" for t in threading.enumerate()):
                        config.logger.warning(
                            "Watchdog: restarting smart alert thread."
                        )
                        start_smart_alert_thread()

            # Webhook inactivity (ليس خطأ، للمعلومات فقط)
            if config.LAST_WEBHOOK_TICK:
                wh_delta = now - config.LAST_WEBHOOK_TICK
                if wh_delta > 3600:
                    config.logger.info(
                        "Watchdog: No webhook activity for %.1f seconds (normal at night).",
                        wh_delta,
                    )

            time.sleep(5)

        except Exception as e:
            config.logger.exception("Error in watchdog loop: %s", e)
            time.sleep(5)


# ==============================
#     Thread Starters
# ==============================

def start_realtime_thread():
    t = threading.Thread(
        target=realtime_engine_loop,
        daemon=True,
        name="RealtimeEngine",
    )
    t.start()
    config.logger.info("Realtime engine thread started.")
    return t


def start_weekly_scheduler_thread():
    t = threading.Thread(
        target=weekly_scheduler_loop,
        daemon=True,
        name="WeeklyScheduler",
    )
    t.start()
    config.logger.info("Weekly scheduler thread started.")
    return t


def start_smart_alert_thread():
    """
    تشغيل ثريد Smart Alert المستقل.
    """
    t = threading.Thread(
        target=smart_alert_loop,
        daemon=True,
        name="SmartAlert",
    )
    t.start()
    config.logger.info("Smart alert thread started.")
    return t


def start_watchdog_thread():
    t = threading.Thread(
        target=watchdog_loop,
        daemon=True,
        name="Watchdog",
    )
    t.start()
    config.logger.info("Watchdog thread started.")
    return t
