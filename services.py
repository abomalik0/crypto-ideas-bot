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
    """تحميل Snapshot خفيف عند بداية السيرفر لتسريع أول رد."""
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
    """حفظ Snapshot خفيف دورى لسرعة الريستارت."""
    global _last_snapshot_save_ts
    now = time.time()
    if now - _last_snapshot_save_ts < 30:
        return  # كل 30 ثانية كحد أدنى

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
#   كاش لرسائل التحليل
# ==============================

def get_cached_response(key: str, builder):
    """
    لو فى رد جاهز حديث فى REALTIME_CACHE → استخدمه.
    لو لأ → ابنِ الرد بالطريقة العادية.
    """
    try:
        now = time.time()
        last_update = config.REALTIME_CACHE.get("last_update")
        cached_value = config.REALTIME_CACHE.get(key)

        ttl = getattr(config, "REALTIME_TTL_SECONDS", 15)

        if cached_value and last_update and (now - last_update) <= ttl:
            return cached_value

        return builder()
    except Exception as e:
        config.logger.exception("get_cached_response error for %s: %s", key, e)
        return builder()


# ==============================
#   محرك Real-Time
# ==============================

def realtime_engine_loop():
    """
    محرك Real-Time:
    - يجدد تحليل BTC / السوق / المخاطر كل عدة ثوانى.
    - يبنى التقرير الأسبوعى بشكل دورى (لمنع الضغط).
    - يبنى نص التحذير الأساسي لاستخدامه بسرعة عند الاستدعاء.
    """
    config.logger.info("Realtime engine loop started.")
    while True:
        try:
            now = time.time()

            # تحليلات أساسية
            btc_msg = format_analysis("BTCUSDT")
            market_msg = format_market_report()
            risk_msg = format_risk_test()

            # تقرير أسبوعى (كل 10 دقائق إعادة بناء)
            weekly_msg = config.REALTIME_CACHE.get("weekly_report")
            last_weekly_build = config.REALTIME_CACHE.get("weekly_built_at") or 0.0
            if not weekly_msg or (now - last_weekly_build) > 600:
                weekly_msg = format_weekly_ai_report()
                config.REALTIME_CACHE["weekly_built_at"] = now

            # نص تحذير أساسى (يستخدمه maybe_send_market_alert)
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

            # لو فى سبب تحذير أو مر وقت طويل → نبنى نص جديد
            if reason or not alert_msg or (now - last_alert_build) > 60:
                # هنا بنستخدم الفورمات المتقدم اللى فى analysis_engine
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
            time.sleep(5)
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(5)


# ==============================
#   إرسال التقرير الأسبوعى
# ==============================

def send_weekly_report_to_all_chats() -> list[int]:
    """
    يبعت التقرير الأسبوعى لكل الشاتات المسجّلة فى KNOWN_CHAT_IDS.
    """
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
#   Helper: تقدير مدى الحركة
# ==============================

def _estimate_expected_move_range(metrics, risk) -> dict:
    """
    تقدير تقريبى (تعليمى) لمدى الهبوط/الصعود المحتمل
    عشان نضيفه فى التحذير (منطقة سعرية تقريبية).
    """
    price = metrics.get("price") or 0
    change = float(metrics.get("change_pct") or 0)
    vol = float(metrics.get("volatility_score") or 0)
    rng = float(metrics.get("range_pct") or 0)

    if price <= 0:
        return {"min_price": None, "max_price": None, "move_dir": "flat"}

    # اتجاه أساسى
    move_dir = "down" if change < 0 else "up" if change > 0 else "flat"

    # severity score تقريبية
    severity_score = abs(change) * 2.0 + vol * 0.5 + rng * 0.7
    level = risk.get("level") if isinstance(risk, dict) else None
    if level == "high":
        severity_score += 15
    elif level == "medium":
        severity_score += 5

    # نحولها لنسبة حركة إضافية محتملة
    base_move = max(0.5, min(15.0, abs(change) * 0.6 + rng * 0.4 + severity_score * 0.05))

    # نحدد نطاق (محافظ شوية)
    if move_dir == "down":
        max_drop = min(30.0, base_move * 1.6)
        min_drop = max(2.0, base_move * 0.6)
        max_price = price * (1 - min_drop / 100.0)
        min_price = price * (1 - max_drop / 100.0)
    elif move_dir == "up":
        max_up = min(30.0, base_move * 1.6)
        min_up = max(2.0, base_move * 0.6)
        min_price = price * (1 + min_up / 100.0)
        max_price = price * (1 + max_up / 100.0)
    else:
        # لو حركة جانبية تقريبًا
        band = min(8.0, rng * 0.8 + 3)
        min_price = price * (1 - band / 100.0)
        max_price = price * (1 + band / 100.0)

    return {
        "min_price": round(min_price),
        "max_price": round(max_price),
        "move_dir": move_dir,
        "severity_score": round(severity_score, 1),
    }


def _build_expected_move_note(metrics, risk) -> str:
    """يبنى نص عربى بسيط من تقدير مدى الحركة."""
    est = _estimate_expected_move_range(metrics, risk)
    if not est["min_price"] or not est["max_price"]:
        return ""

    price = metrics.get("price") or 0
    move_dir = est["move_dir"]
    min_p = f"{est['min_price']:,}"
    max_p = f"{est['max_price']:,}"

    if move_dir == "down":
        return (
            f"\n\n📉 <b>تقدير نطاق الهبوط المحتمل (تعليمى، غير مضمون):</b>\n"
            f"• فى حالة استمرار نفس السلوك البيعى، قد يمتد الهبوط بشكل تقريبى إلى المنطقة بين ~<code>{min_p}$</code> و ~<code>{max_p}$</code>.\n"
            f"• السعر الحالى تقريبًا: <code>{price:,.0f}$</code> — استخدم هذه الأرقام كمرجع تقديرى فقط مع إدارة مخاطر صارمة."
        )
    elif move_dir == "up":
        return (
            f"\n\n📈 <b>تقدير نطاق الصعود المحتمل (تعليمى، غير مضمون):</b>\n"
            f"• فى حالة استمرار الزخم الصاعد، قد يمتد الصعود بشكل تقريبى إلى المنطقة بين ~<code>{min_p}$</code> و ~<code>{max_p}$</code>.\n"
            f"• السعر الحالى تقريبًا: <code>{price:,.0f}$</code> — الأرقام تقريبية وليست ضمانًا."
        )
    else:
        return (
            f"\n\n🔎 <b>نطاق تذبذب تقديرى (تعليمى، غير مضمون):</b>\n"
            f"• السوق قد يتحرك داخل نطاق تقريبى بين ~<code>{min_p}$</code> و ~<code>{max_p}$</code> فى حالة استمرار نفس نمط الحركة.\n"
            f"• يُفضل انتظار كسر واضح خارج هذا النطاق قبل قرارات عدوانية."
        )


# ==============================
#   نظام التحذير الذكى
# ==============================

def maybe_send_market_alert(source: str = "cron") -> dict:
    """
    نظام تحذير ذكى:
    - يقرأ بيانات السوق من الكاش.
    - يحدد هل فى وضع حساس فعلاً ولا لأ (detect_alert_condition).
    - يمنع التكرار المزعج (cooldown حسب شدة الوضع).
    - لو فى تحذير جديد → يبعت للأدمن وكل الشاتات المسجلة.
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        reason = "metrics_failed"
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        config.LAST_AUTO_ALERT_INFO = {
            "time": now_iso,
            "reason": reason,
            "sent": False,
            "source": source,
        }
        config.logger.warning("maybe_send_market_alert: cannot fetch metrics")
        return {
            "ok": False,
            "alert_sent": False,
            "reason": reason,
        }

    change = float(metrics.get("change_pct") or 0)
    vol = float(metrics.get("volatility_score") or 0)
    rng = float(metrics.get("range_pct") or 0)

    risk = evaluate_risk_level(change, vol)
    reason = detect_alert_condition(metrics, risk)

    now = time.time()
    now_iso = datetime.utcnow().isoformat(timespec="seconds")

    if not reason:
        # مفيش وضع غير طبيعى → reset
        if config.LAST_ALERT_REASON is not None:
            config.logger.info("maybe_send_market_alert: market normal again → reset alert state.")
        config.LAST_ALERT_REASON = None
        config.LAST_AUTO_ALERT_INFO = {
            "time": now_iso,
            "reason": "no_alert",
            "sent": False,
            "source": source,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": "no_alert",
        }

    # حساب شدة الوضع لتحديد الـ cooldown
    severity_score = abs(change) * 2.0 + vol * 0.6 + rng * 0.8
    level = risk.get("level")
    if level == "high":
        severity_score += 20
    elif level == "medium":
        severity_score += 8

    # throttle / cooldown
    if severity_score >= 90:
        cooldown = 5 * 60    # عنيف جدًا → ممكن تنبيه كل 5 دقائق
    elif severity_score >= 65:
        cooldown = 10 * 60   # قوى
    elif severity_score >= 40:
        cooldown = 20 * 60   # متوسط
    else:
        cooldown = 40 * 60   # ضعيف → نخفّف التنبيهات

    last_info = config.LAST_AUTO_ALERT_INFO or {}
    last_reason = config.LAST_ALERT_REASON
    last_ts = float(last_info.get("ts") or 0)

    if last_reason == reason and (now - last_ts) < cooldown:
        # نفس السبب ولسه فى فترة الـ cooldown → منبعتش تانى
        remaining = int(cooldown - (now - last_ts))
        config.logger.info(
            "maybe_send_market_alert: throttled duplicate alert. reason=%s remaining=%ss",
            reason,
            remaining,
        )
        config.LAST_AUTO_ALERT_INFO = {
            "time": now_iso,
            "reason": "duplicate",
            "sent": False,
            "source": source,
            "ts": now,
            "cooldown": cooldown,
            "severity_score": round(severity_score, 1),
            "base_reason": reason,
        }
        return {
            "ok": True,
            "alert_sent": False,
            "reason": "duplicate",
            "cooldown_remaining": remaining,
        }

    # وصلنا هنا → لازم نبعت تحذير جديد فعلاً
    base_alert = config.REALTIME_CACHE.get("alert_text") or format_ai_alert()
    extra_note = _build_expected_move_note(metrics, risk)
    final_alert_text = base_alert + extra_note

    sent_to = []

    # نتأكد الأدمن ضمن القائمة
    all_chats = set(config.KNOWN_CHAT_IDS)
    all_chats.add(config.ADMIN_CHAT_ID)

    for cid in list(all_chats):
        try:
            # ممكن نخلى غير الأدمن silent لو المخاطرة مش high
            silent = (cid != config.ADMIN_CHAT_ID and level != "high")
            config.send_message(cid, final_alert_text, silent=silent)
            sent_to.append(cid)
        except Exception as e:
            config.logger.exception("Error sending auto alert to %s: %s", cid, e)

    config.LAST_ALERT_REASON = reason
    config.LAST_AUTO_ALERT_INFO = {
        "time": now_iso,
        "reason": reason,
        "sent": True,
        "source": source,
        "ts": now,
        "cooldown": cooldown,
        "severity_score": round(severity_score, 1),
        "sent_to": sent_to,
        "price": metrics.get("price"),
        "change_pct": change,
        "range_pct": rng,
        "volatility_score": vol,
        "risk_level": level,
    }
    config.logger.info(
        "maybe_send_market_alert: NEW alert sent! reason=%s severity=%.1f to=%s",
        reason,
        severity_score,
        sent_to,
    )

    # تاريخ التحذيرات (للوحة التحكم)
    try:
        config.add_alert_history(
            source or "auto",
            reason,
            price=metrics.get("price"),
            change=change,
        )
    except Exception:
        # لو الدالة موجودة فى config أو util تانى
        try:
            from config import add_alert_history as _add_hist  # type: ignore
            _add_hist(
                source or "auto",
                reason,
                price=metrics.get("price"),
                change=change,
            )
        except Exception as e:
            config.logger.exception("Failed to add alert history: %s", e)

    return {
        "ok": True,
        "alert_sent": True,
        "reason": "sent",
        "sent_to": sent_to,
        "severity_score": round(severity_score, 1),
        "cooldown": cooldown,
    }


# ==============================
#   Scheduler الأسبوعى
# ==============================

def weekly_scheduler_loop():
    """
    Scheduler داخلى:
    - كل 60 ثانية يشيك اليوم / الساعة (UTC).
    - لو جمعة 11:00 ولسه مبعتش النهاردة → يبعت التقرير الأسبوعى.
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
#   Watchdog مضاد للتجمد
# ==============================

def watchdog_loop():
    """
    Anti-Freeze Watchdog:
    - يراقب:
        * Realtime engine
        * Weekly scheduler
        * webhook (نشاط تيليجرام)
    - لو tick متأخر جدًا → يكتب تحذير ويحاول يعيد تشغيل الثريد لو مش موجود.
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


# ==============================
#   دوال تشغيل الثريدات
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
