import time
from datetime import datetime

from flask import Flask, request, jsonify, Response

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
    _risk_level_ar,
)
import services

app = Flask(__name__)

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

    # حفظ الشات عشان التحذيرات توصل لكل المستخدمين
    try:
        config.KNOWN_CHAT_IDS.add(chat_id)
    except Exception:
        pass

    # /start
    if lower_text == "/start":
        welcome = (
            "👋 أهلاً بك فى <b>IN CRYPTO Ai</b>.\n\n"
            "استخدم الأوامر التالية:\n"
            "• <code>/btc</code> — تحليل البيتكوين\n"
            "• <code>/vai</code> — تحليل VAI\n"
            "• <code>/coin btc</code> — تحليل أى عملة\n\n"
            "تحليل السوق:\n"
            "• <code>/market</code> — نظرة عامة على السوق\n"
            "• <code>/risk_test</code> — اختبار مستوى المخاطر\n"
            "• <code>/alert</code> — تحذير فورى (للأدمن فقط)\n\n"
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
        # أمر يدوى للأدمن – يستخدم نفس نص التحذير الذكى ولكن بدون فلترة
        if chat_id != config.ADMIN_CHAT_ID:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        alert_text = services.get_cached_response("alert_text", format_ai_alert)
        keyboard = {
            "inline_keyboard": [
                [{"text": "عرض التفاصيل 📊", "callback_data": "alert_details"}]
            ]
        }
        send_message_with_keyboard(chat_id, alert_text, keyboard)
        add_alert_history("manual", "Manual /alert command")
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
            risk_text = (
                f"{risk['emoji']} {_risk_level_ar(risk['level'])}" if risk else "N/A"
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

    # رد افتراضى
    send_message(
        chat_id,
        "⚙️ اكتب /start لعرض الأوامر المتاحة.\nمثال: <code>/btc</code> أو <code>/coin btc</code>.",
    )
    return jsonify(ok=True)


# ==============================
#   /auto_alert  (يُستخدم مع cron أو يدوى)
# ==============================


@app.route("/auto_alert", methods=["GET"])
def auto_alert():
    result = services.maybe_send_market_alert(source="cron")
    return jsonify(result), 200


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

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])

    return jsonify(
        ok=True,
        price=metrics["price"],
        change_pct=metrics["change_pct"],
        range_pct=metrics["range_pct"],
        volatility_score=metrics["volatility_score"],
        strength_label=metrics["strength_label"],
        liquidity_pulse=metrics["liquidity_pulse"],
        risk_level=_risk_level_ar(risk["level"]),
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

    return jsonify(ok=True, alerts=list(config.ALERTS_HISTORY))


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
        ok=True, message="تم إرسال التقرير الأسبوعى التجريبى للأدمن فقط."
    )


# ==============================
#   /status API (للمراقبة)
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


# =====================================
# تشغيل البوت — Main Runner
# =====================================


if __name__ == "__main__":
    try:
        config.logger.info("Loading warm-start snapshot...")
        services.load_snapshot()
    except Exception as e:
        config.logger.exception("Snapshot load failed on startup: %s", e)

    try:
        config.logger.info("Setting webhook on startup...")
        setup_webhook()
    except Exception as e:
        config.logger.exception("Webhook setup failed on startup: %s", e)

    try:
        services.start_weekly_scheduler_thread()
    except Exception as e:
        config.logger.exception("Failed to start weekly scheduler thread: %s", e)

    try:
        services.start_realtime_thread()
    except Exception as e:
        config.logger.exception("Failed to start realtime engine thread: %s", e)

    try:
        services.start_watchdog_thread()
    except Exception as e:
        config.logger.exception("Failed to start watchdog thread: %s", e)

    config.logger.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=8080)
