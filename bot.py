import time
from datetime import datetime

from flask import Flask, request, jsonify, Response
import threading

import config
from config import (
    send_message,
    send_message_with_keyboard,
    answer_callback_query,
    add_alert_history,
    log_cleaned_buffer,
    check_admin_auth,
    HTTP_SESSION,
    TELEGRAM_API,
)
from analysis_engine import (
    format_analysis,
    format_market_report,
    format_risk_test,
    format_ai_alert,
    format_ai_alert_details,
    format_weekly_ai_report,
    get_market_metrics_cached,
    evaluate_risk_level,
    detect_alert_condition,
    compute_smart_market_snapshot,  # Snapshot لـ Smart Alert
)
import services

app = Flask(__name__)


# ==============================
#   Helpers صغيرة لـ Smart Alert Test
# ==============================

def _fmt_price(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _fmt_pct(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):+.2f}%"
    except Exception:
        return str(v)


def _fmt_num(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):.2f}"
    except Exception:
        return str(v)


def _fmt_secs(v):
    try:
        if v is None:
            return "-"
        v = float(v)
        if v < 1:
            return f"{v:.2f} ثانية"
        return f"{v:.1f} ثانية"
    except Exception:
        return str(v) if v is not None else "-"


def _format_smart_snapshot(snapshot: dict, title: str) -> str:
    """
    تنسيق Snapshot الذكى فى رسالة قصيرة للأدمن.
    ما بيغيرش أى حاجة فى المنطق، كله قراءة من dict فقط.
    """
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert_level = snapshot.get("alert_level") or {}
    zones = snapshot.get("zones") or {}
    interval = snapshot.get("adaptive_interval")

    price = metrics.get("price")
    change = metrics.get("change_pct")
    range_pct = metrics.get("range_pct")
    vol = metrics.get("volatility_score")
    strength_label = metrics.get("strength_label")
    liquidity_pulse = metrics.get("liquidity_pulse")

    risk_level = risk.get("level")
    risk_emoji = risk.get("emoji", "")
    try:
        from analysis_engine import _risk_level_ar as _rl_txt
        risk_text = _rl_txt(risk_level) if risk_level else "غير معروف"
    except Exception:
        risk_text = "غير معروف"

    regime = pulse.get("regime")
    speed_index = pulse.get("speed_index")
    direction_conf = pulse.get("direction_confidence")

    shock_score = alert_level.get("shock_score")
    level = alert_level.get("level")
    trend_bias = alert_level.get("trend_bias")

    active_labels = events.get("active_labels") or []

    scenario = zones.get("dominant_scenario")
    downside_1 = zones.get("downside_zone_1")
    downside_2 = zones.get("downside_zone_2")
    upside_1 = zones.get("upside_zone_1")
    upside_2 = zones.get("upside_zone_2")

    lines: list[str] = []

    lines.append(f"🧪 <b>{title}</b>")
    lines.append("")

    if price is not None:
        lines.append(
            f"• السعر الآن: <b>${_fmt_price(price)}</b> ({_fmt_pct(change)})"
        )
    else:
        lines.append("• السعر الآن: غير متوفر")

    lines.append(
        f"• مدى اليوم ≈ {_fmt_num(range_pct)}٪ / التقلب ≈ {_fmt_num(vol)} / 100"
    )
    lines.append(
        f"• قوة السوق: {strength_label or '-'} / نبض السيولة: {liquidity_pulse or '-'}"
    )
    lines.append(
        f"• وضع التقلب: {regime or '-'} / سرعة الحركة ≈ {_fmt_num(speed_index)} / 100"
    )
    if direction_conf is not None:
        lines.append(f"• ثقة اتجاه قصير المدى ≈ {_fmt_num(direction_conf)} / 100")

    lines.append(
        f"• مستوى المخاطر: {risk_emoji} {risk_text} (score ≈ {_fmt_num(risk.get('score'))})"
    )

    lines.append("")
    lines.append(
        f"• Smart Alert Level: {(str(level).upper() if level else 'NONE')} "
        f"/ Shock Score ≈ {_fmt_num(shock_score)} / 100"
    )
    if trend_bias:
        lines.append(f"• اتجاه قصير المدى: {trend_bias}")

    if active_labels:
        labels_text = ", ".join(active_labels)
        lines.append(f"• أحداث نشطة: {labels_text}")
    else:
        lines.append("• لا توجد أحداث مؤسسية قوية جدًا حاليًا حسب Smart Pulse.")

    if interval is not None:
        lines.append(f"• الفحص التالى المقترح بعد: {_fmt_secs(interval)}")

    # مناطق تقديرية "نازلين لفين / طالعين لفين"
    if any([downside_1, downside_2, upside_1, upside_2]):
        lines.append("")
        lines.append("• مناطق حركة تقديرية (تعليمية فقط):")

        def _zone_line(label: str, z):
            if not z or len(z) != 2:
                return None
            low, high = z
            try:
                return (
                    f"  - {label}: تقريبًا بين "
                    f"<b>{float(low):,.0f}$</b> و <b>{float(high):,.0f}$</b>"
                )
            except Exception:
                return None

        z1 = _zone_line("منطقة هبوط 1", downside_1)
        z2 = _zone_line("منطقة هبوط 2", downside_2)
        u1 = _zone_line("منطقة صعود 1", upside_1)
        u2 = _zone_line("منطقة صعود 2", upside_2)

        for ln in (z1, z2, u1, u2):
            if ln:
                lines.append(ln)

    reason = snapshot.get("reason")
    if reason:
        lines.append("")
        lines.append("📌 <b>ملخص سريع من Smart Alert:</b>")
        lines.append(reason)

    return "\n".join(lines)


# ==============================
#   مسارات أساسية / Webhook
# ==============================

@app.route("/", methods=["GET"])
def index():
    return "IN CRYPTO Ai bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    config.LAST_WEBHOOK_TICK = time.time()

    if config.BOT_DEBUG:
        config.logger.info("Update: %s", update)
    else:
        config.logger.debug("Update keys: %s", list(update.keys()))

    # callback_query
    if "callback_query" in update:
        cq = update["callback_query"]
        callback_id = cq.get("id")
        data = cq.get("data")
        message = cq.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        from_user = cq.get("from") or {}
        from_id = from_user.get("id")

        if callback_id:
            answer_callback_query(callback_id)

        if data == "alert_details":
            if from_id != config.ADMIN_CHAT_ID:
                if chat_id:
                    send_message(chat_id, "❌ هذا الزر مخصص للإدارة فقط.")
                return jsonify(ok=True)

            details = format_ai_alert_details()
            send_message(chat_id, details)
            return jsonify(ok=True)

        return jsonify(ok=True)

    # رسائل عادية
    if "message" not in update:
        return jsonify(ok=True)

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    lower_text = text.lower()

    try:
        config.KNOWN_CHAT_IDS.add(chat_id)
    except Exception:
        pass

    # /start
    if lower_text == "/start":
        welcome = (
            "👋 أهلاً بك فى <b>IN CRYPTO Ai</b>.\n\n"
            "استخدم الأوامر التالية:\n"
            "• <code>/btc</code> — تحليل BTC\n"
            "• <code>/vai</code> — تحليل VAI\n"
            "• <code>/coin btc</code> — تحليل أى عملة\n\n"
            "تحليل السوق:\n"
            "• <code>/market</code> — نظرة عامة\n"
            "• <code>/risk_test</code> — اختبار مخاطر\n"
            "• <code>/alert</code> — تحذير كامل (للأدمن فقط)\n\n"
            "النظام يجلب البيانات أولاً من Binance ثم KuCoin تلقائيًا."
        )
        send_message(chat_id, welcome)
        return jsonify(ok=True)

    if lower_text == "/btc":
        reply = services.get_cached_response(
            "btc_analysis", lambda: format_analysis("BTCUSDT")
        )
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/market":
        reply = services.get_cached_response("market_report", format_market_report)
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/risk_test":
        reply = services.get_cached_response("risk_test", format_risk_test)
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/alert":
        if chat_id != config.ADMIN_CHAT_ID:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        alert_text = services.get_cached_response("alert_text", format_ai_alert)
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
        send_message_with_keyboard(chat_id, alert_text, keyboard)
        add_alert_history("manual", "Manual /alert command")
        return jsonify(ok=True)

    # ==============================
    #   /test_smart — تشخيص Smart Alert (للأدمن فقط)
    # ==============================
    if lower_text == "/test_smart":
        if chat_id != config.ADMIN_CHAT_ID:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        try:
            snapshot = compute_smart_market_snapshot()
        except Exception as e:
            config.logger.exception("Error in /test_smart snapshot: %s", e)
            send_message(
                chat_id,
                "⚠️ حدث خطأ أثناء بناء Smart Alert Snapshot.\n"
                "راجع لوحة التحكم / اللوج لمزيد من التفاصيل.",
            )
            return jsonify(ok=True)

        if not snapshot:
            send_message(
                chat_id,
                "⚠️ لم أستطع بناء Snapshot للسوق حالياً (قد تكون مشكلة بيانات أو API).",
            )
            return jsonify(ok=True)

        msg_mock = _format_smart_snapshot(snapshot, "Smart Alert — MOCK / DEBUG")
        msg_real = _format_smart_snapshot(snapshot, "Smart Alert — LIVE SNAPSHOT")

        send_message(chat_id, msg_mock)
        send_message(chat_id, msg_real)

        metrics = snapshot.get("metrics") or {}
        add_alert_history(
            "smart_test",
            "Manual /test_smart snapshot",
            price=metrics.get("price"),
            change=metrics.get("change_pct"),
        )

        return jsonify(ok=True)

    if lower_text.startswith("/coin"):
        parts = lower_text.split()
        if len(parts) < 2:
            send_message(
                chat_id,
                "⚠️ استخدم الأمر هكذا:\n"
                "<code>/coin btc</code>\n"
                "<code>/coin btcusdt</code>\n"
                "<code>/coin vai</code>",
            )
        else:
            reply = format_analysis(parts[1])
            send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/status":
        metrics = get_market_metrics_cached()
        if metrics:
            change = metrics["change_pct"]
            vol = metrics["volatility_score"]
            risk = evaluate_risk_level(change, vol)
            from analysis_engine import _risk_level_ar as _rl_txt
            risk_text = (
                f"{risk['emoji']} {_rl_txt(risk['level'])}" if risk else "N/A"
            )
        else:
            risk_text = "N/A"

        msg_status = f"""
🛰 <b>حالة نظام IN CRYPTO Ai</b>

• حالة Binance: {"✅" if config.API_STATUS["binance_ok"] else "⚠️"}
• حالة KuCoin: {"✅" if config.API_STATUS["kucoin_ok"] else "⚠️"}
• آخر فحص API: {config.API_STATUS.get("last_api_check")}

• آخر تحديث Real-Time: {config.REALTIME_CACHE.get("last_update")}
• آخر Webhook: {datetime.utcfromtimestamp(config.LAST_WEBHOOK_TICK).isoformat(timespec="seconds") if config.LAST_WEBHOOK_TICK else "لا يوجد"}

• حالة المخاطر العامة: {risk_text}

• عدد الشاتات المسجلة: {len(config.KNOWN_CHAT_IDS)}
• آخر تقرير أسبوعى مبعوت: {config.LAST_WEEKLY_SENT_DATE}
• آخر Auto Alert: {config.LAST_AUTO_ALERT_INFO.get("time")} ({config.LAST_AUTO_ALERT_INFO.get("reason")})
""".strip()
        send_message(chat_id, msg_status)
        return jsonify(ok=True)

    return jsonify(ok=True)


# ==============================
#   /auto_alert Endpoint
# ==============================

@app.route("/auto_alert", methods=["GET"])
def auto_alert():
    metrics = get_market_metrics_cached()
    if not metrics:
        config.logger.warning("auto_alert: metrics is None")
        return jsonify(ok=False, error="metrics_failed"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])

    reason = detect_alert_condition(metrics, risk)
    if not reason:
        config.logger.info("auto_alert: no condition met.")
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_condition",
            "sent": False,
        }
        return jsonify(ok=True, alert_sent=False, reason="no_condition"), 200

    if config.LAST_ALERT_REASON == reason:
        config.logger.info("auto_alert: same reason as last alert, skip.")
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "duplicate_reason",
            "sent": False,
        }
        return (
            jsonify(ok=True, alert_sent=False, reason="duplicate_reason"),
            200,
        )

    text = format_ai_alert()
    send_message(config.ADMIN_CHAT_ID, text)

    config.LAST_ALERT_REASON = reason
    config.LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True,
    }
    config.logger.info("auto_alert: NEW alert sent! reason=%s", reason)

    add_alert_history(
        "auto",
        reason,
        price=metrics["price"],
        change=metrics["change_pct"],
    )

    return jsonify(ok=True, alert_sent=True, reason="sent"), 200


# ==============================
#   مسارات اختبار / Admin / Dashboard
# ==============================

@app.route("/test_alert", methods=["GET"])
def test_alert():
    try:
        alert_message = (
            "🚨 *تنبيه تجريبي من السيرفر*\n"
            "تم إرسال هذا التنبيه لاختبار النظام.\n"
            "كل شيء شغال بنجاح 👍"
        )
        send_message(config.ADMIN_CHAT_ID, alert_message)
        return {"ok": True, "sent": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/dashboard_api", methods=["GET"])
def dashboard_api():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    metrics = get_market_metrics_cached()
    if not metrics:
        return jsonify(ok=False, error="metrics_failed"), 200

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    from analysis_engine import _risk_level_ar as _rl_txt

    return jsonify(
        ok=True,
        price=metrics["price"],
        change_pct=metrics["change_pct"],
        range_pct=metrics["range_pct"],
        volatility_score=metrics["volatility_score"],
        strength_label=metrics["strength_label"],
        liquidity_pulse=metrics["liquidity_pulse"],
        risk_level=_rl_txt(risk["level"]),
        risk_emoji=risk["emoji"],
        risk_message=risk["message"],
        last_auto_alert=config.LAST_AUTO_ALERT_INFO,
        last_error=config.LAST_ERROR_INFO,
        last_weekly_sent=config.LAST_WEEKLY_SENT_DATE,
        known_chats=len(config.KNOWN_CHAT_IDS),
        api_status=config.API_STATUS,
        last_realtime_tick=config.LAST_REALTIME_TICK,
        last_weekly_tick=config.LAST_WEEKLY_TICK,
        last_webhook_tick=config.LAST_WEBHOOK_TICK,
        last_watchdog_tick=config.LAST_WATCHDOG_TICK,
    )


@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if not check_admin_auth(request):
        return Response("Unauthorized", status=401)

    try:
        with open("dashboard.html", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h1>dashboard.html غير موجود فى نفس مجلد bot.py</h1>"

    return Response(html, mimetype="text/html")


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    if not check_admin_auth(request):
        return Response("Unauthorized", status=401)
    content = log_cleaned_buffer()
    return Response(content, mimetype="text/plain")


@app.route("/admin/alerts_history", methods=["GET"])
def admin_alerts_history():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    return jsonify(
        ok=True,
        alerts=list(config.ALERTS_HISTORY),
    )


@app.route("/admin/clear_alerts", methods=["GET"])
def admin_clear_alerts():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    config.ALERTS_HISTORY.clear()
    config.logger.info("Admin cleared alerts history from dashboard.")
    return jsonify(ok=True, message="تم مسح سجل التحذيرات.")


@app.route("/admin/force_alert", methods=["GET"])
def admin_force_alert():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    text = format_ai_alert()
    send_message(config.ADMIN_CHAT_ID, text)
    add_alert_history("force", "Force alert from admin dashboard")
    config.logger.info("Admin forced alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال التحذير الفورى للأدمن.")


@app.route("/admin/test_alert", methods=["GET"])
def admin_test_alert():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    test_msg = (
        "🧪 <b>تنبيه تجريبى من لوحة التحكم</b>\n"
        "هذا التنبيه للتأكد من أن نظام الإشعارات يعمل بشكل سليم."
    )
    send_message(config.ADMIN_CHAT_ID, test_msg)
    config.logger.info("Admin sent test alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال تنبيه تجريبى للأدمن.")


@app.route("/weekly_ai_report", methods=["GET"])
def weekly_ai_report():
    sent_to = services.send_weekly_report_to_all_chats()
    return jsonify(ok=True, sent_to=sent_to)


@app.route("/admin/weekly_ai_test", methods=["GET"])
def admin_weekly_ai_test():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    report = services.get_cached_response("weekly_report", format_weekly_ai_report)
    send_message(config.ADMIN_CHAT_ID, report)
    config.logger.info("Admin requested weekly AI report test.")
    return jsonify(
        ok=True,
        message="تم إرسال التقرير الأسبوعى التجريبى للأدمن فقط.",
    )


# ==============================
#   /status API (للإدارة أو للمراقبة)
# ==============================

@app.route("/status", methods=["GET"])
def status_api():
    import threading as _th

    threads = [t.name for t in _th.enumerate()]

    return jsonify(
        ok=True,
        api_status=config.API_STATUS,
        realtime_last_tick=config.LAST_REALTIME_TICK,
        weekly_last_tick=config.LAST_WEEKLY_TICK,
        webhook_last_tick=config.LAST_WEBHOOK_TICK,
        watchdog_last_tick=config.LAST_WATCHDOG_TICK,
        cache_last_update=config.REALTIME_CACHE.get("last_update"),
        last_auto_alert=config.LAST_AUTO_ALERT_INFO,
        last_weekly_sent=config.LAST_WEEKLY_SENT_DATE,
        known_chats=len(config.KNOWN_CHAT_IDS),
        threads=threads,
    )


# ==============================
#       تفعيل الـ Webhook
# ==============================

def setup_webhook():
    webhook_url = f"{config.APP_BASE_URL}/webhook"
    try:
        r = HTTP_SESSION.get(
            f"{TELEGRAM_API}/setWebhook",
            params={"url": webhook_url},
            timeout=10,
        )
        config.logger.info("Webhook response: %s - %s", r.status_code, r.text)
    except Exception as e:
        config.logger.exception("Error while setting webhook: %s", e)


# 🔥 مهم جداً — Alias علشان الـ main يشتغل بدون خطأ
def set_webhook_on_startup():
    setup_webhook()


# =====================================
# تشغيل البوت — Main Runner
# =====================================

if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # تحميل السناك شوت (لو متفعّل)
    try:
        services.load_snapshot()
    except Exception as e:
        logging.exception("Snapshot load failed on startup: %s", e)

    # ضبط الويب هوك
    try:
        set_webhook_on_startup()
    except Exception as e:
        logging.exception("Failed to set webhook on startup: %s", e)

    # هنا التعديل المهم: تشغيل كل الثريدات من دالة واحدة
    try:
        services.start_background_threads()
    except Exception as e:
        logging.exception("Failed to start background threads: %s", e)

    # تشغيل Flask
    app.run(host="0.0.0.0", port=8080)
