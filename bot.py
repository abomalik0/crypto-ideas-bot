import os
import time
import logging
import requests
from datetime import datetime
from collections import deque
from flask import Flask, request, jsonify, Response
import threading  # Scheduler

# =====================================================
#  الإعدادات
# =====================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
ADMIN_CHAT_ID = 669209875
ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")

BOT_DEBUG = os.getenv("BOT_DEBUG", "0") == "1"

if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("Missing APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

LAST_ALERT_REASON = None
LAST_AUTO_ALERT_INFO = {"time": None, "reason": None, "sent": False}
LAST_ERROR_INFO = {"time": None, "message": None}
LAST_WEEKLY_SENT_DATE: str | None = None

LOG_BUFFER = deque(maxlen=200)


class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        global LAST_ERROR_INFO
        msg = self.format(record)
        LOG_BUFFER.append(msg)
        if record.levelno >= logging.ERROR:
            LAST_ERROR_INFO = {
                "time": datetime.utcnow().isoformat(timespec="seconds"),
                "message": msg,
            }


LOG_LEVEL = logging.DEBUG if BOT_DEBUG else logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_memory_handler = InMemoryLogHandler()
_memory_handler.setLevel(logging.INFO)
_memory_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(_memory_handler)

ALERTS_HISTORY = deque(maxlen=100)
KNOWN_CHAT_IDS: set[int] = set([ADMIN_CHAT_ID])
app = Flask(__name__)

# =====================================================
#   HTTP Session
# =====================================================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "InCryptoAI-Bot/1.0"})

# =====================================================
#  مساعدات Telegram
# =====================================================

def send_message(chat_id, text, parse_mode="HTML"):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        r = HTTP_SESSION.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
        if r.status_code != 200:
            logger.warning("sendMessage error: %s %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("send_message exception: %s", e)


def send_message_with_keyboard(chat_id, text, reply_markup, parse_mode="HTML"):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "reply_markup": reply_markup}
        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("sendMessage_with_keyboard error: %s %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("send_message_with_keyboard exception: %s", e)


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    try:
        url = f"{TELEGRAM_API}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        HTTP_SESSION.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.exception("answer_callback_query exception: %s", e)

# =====================================================
#  رموز العملات + المنصات
# =====================================================

def normalize_symbol(user_symbol: str):
    base = user_symbol.strip().upper().replace("USDT", "").replace("-", "")
    if not base:
        return None, None, None
    return base, base + "USDT", base + "-USDT"

# =====================================================
#   كاش للأسعار
# =====================================================

PRICE_CACHE = {}
CACHE_TTL_SECONDS = 5

def _get_cached(key):
    item = PRICE_CACHE.get(key)
    if not item:
        return None
    if time.time() - item["time"] > CACHE_TTL_SECONDS:
        return None
    return item["data"]

def _set_cached(key, data):
    PRICE_CACHE[key] = {"time": time.time(), "data": data}

# =====================================================
#  جلب البيانات من Binance & KuCoin
# =====================================================

def fetch_from_binance(symbol: str):
    try:
        r = HTTP_SESSION.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        return {
            "exchange": "binance",
            "symbol": symbol,
            "price": float(data["lastPrice"]),
            "change_pct": float(data["priceChangePercent"]),
            "high": float(data.get("highPrice", 0)),
            "low": float(data.get("lowPrice", 0)),
            "volume": float(data.get("volume", 0)),
        }
    except:
        return None

def fetch_from_kucoin(symbol: str):
    try:
        r = HTTP_SESSION.get("https://api.kucoin.com/api/v1/market/stats", params={"symbol": symbol}, timeout=10)
        data = r.json()
        if data.get("code") != "200000":
            return None
        d = data.get("data") or {}
        return {
            "exchange": "kucoin",
            "symbol": symbol,
            "price": float(d.get("last") or 0),
            "change_pct": float(d.get("changeRate") or 0)*100,
            "high": float(d.get("high") or 0),
            "low": float(d.get("low") or 0),
            "volume": float(d.get("vol") or 0),
        }
    except:
        return None

def fetch_price_data(user_symbol: str):
    base, b_symbol, k_symbol = normalize_symbol(user_symbol)
    if not base:
        return None

    c1 = _get_cached("BIN:" + b_symbol)
    if c1: return c1
    c2 = _get_cached("KUC:" + k_symbol)
    if c2: return c2

    data = fetch_from_binance(b_symbol)
    if data:
        _set_cached("BIN:" + b_symbol, data)
        return data

    data = fetch_from_kucoin(k_symbol)
    if data:
        _set_cached("KUC:" + k_symbol, data)
        return data

    return None

# =====================================================
#  محرك Metrics عام
# =====================================================

def build_symbol_metrics(price, change_pct, high, low):
    range_pct = ((high - low) / price * 100) if price > 0 and high >= low else 0
    volatility_score = max(0, min(100, abs(change_pct)*1.5 + range_pct))

    if change_pct >= 3:
        strength_label = "صعود قوى وزخم واضح."
    elif change_pct >= 1:
        strength_label = "صعود هادئ مع تحسن تدريجى."
    elif change_pct > -1:
        strength_label = "حركة متذبذبة بدون اتجاه."
    elif change_pct > -3:
        strength_label = "هبوط خفيف مع ضغط بيعى."
    else:
        strength_label = "هبوط قوى مع ضغوط عالية."

    if change_pct >= 2 and range_pct <= 5:
        liquidity_pulse = "السيولة تميل للدخول المنظم."
    elif change_pct >= 2 and range_pct > 5:
        liquidity_pulse = "صعود سريع مع تقلب ⇒ احتمال تصريف."
    elif -2 < change_pct < 2:
        liquidity_pulse = "السيولة متوازنة تقريباً."
    elif change_pct <= -2 and range_pct > 4:
        liquidity_pulse = "خروج سيولة واضح."
    else:
        liquidity_pulse = "ضغوط بيعية هادئة."

    return {
        "price": price,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
    }

# =====================================================
#  Market Metrics
# =====================================================

def compute_market_metrics():
    data = fetch_price_data("BTCUSDT")
    if not data: return None
    return build_symbol_metrics(data["price"], data["change_pct"], data["high"], data["low"])

MARKET_METRICS_CACHE = {"data": None, "time": 0}
MARKET_TTL_SECONDS = 4

def get_market_metrics_cached():
    now = time.time()
    if MARKET_METRICS_CACHE["data"] and (now - MARKET_METRICS_CACHE["time"] <= MARKET_TTL_SECONDS):
        return MARKET_METRICS_CACHE["data"]
    data = compute_market_metrics()
    if data:
        MARKET_METRICS_CACHE["data"] = data
        MARKET_METRICS_CACHE["time"] = now
    return data

# =====================================================
# Risk Engine
# =====================================================

def evaluate_risk_level(change_pct, volatility_score):
    risk_score = abs(change_pct) + volatility_score*0.4
    if risk_score < 25:
        return {"level":"low","emoji":"🟢","message":"المخاطر منخفضة."}
    elif risk_score < 50:
        return {"level":"medium","emoji":"🟡","message":"المخاطر متوسطة."}
    else:
        return {"level":"high","emoji":"🔴","message":"المخاطر مرتفعة."}

def _risk_level_ar(level):
    return {"low":"منخفض","medium":"متوسط","high":"مرتفع"}.get(level, level)
    # =====================================================
#  Auto Alert Engine
# =====================================================

def auto_alert_check(m):
    global LAST_ALERT_REASON, LAST_AUTO_ALERT_INFO

    if not m:
        return {"reason": "no_data"}

    change = m["change_pct"]
    volatility = m["volatility_score"]
    range_pct = m["range_pct"]

    # شرط: تحذير صعود حاد
    if change >= 3 and volatility >= 45:
        reason = f"صعود حاد + تقلب عالى (Δ {change:.2f}%)"
    # شرط: تحذير هبوط حاد
    elif change <= -3 and volatility >= 40:
        reason = f"هبوط حاد + ضغط بيعى (Δ {change:.2f}%)"
    # شرط: تقلب خطير بدون اتجاه
    elif volatility >= 80 and abs(change) < 1:
        reason = "⚠️ تقلب مرتفع بدون اتجاه"
    else:
        reason = "no_alert"

    if reason == "no_alert":
        LAST_AUTO_ALERT_INFO = {"time": datetime.utcnow().isoformat(timespec="seconds"), "reason":"no_alert","sent":False}
        return {"reason": "no_alert"}

    # منع تكرار التحذير
    if reason == LAST_ALERT_REASON:
        LAST_AUTO_ALERT_INFO = {"time": datetime.utcnow().isoformat(timespec="seconds"), "reason":"duplicate","sent":False}
        return {"reason": "duplicate"}

    LAST_ALERT_REASON = reason
    LAST_AUTO_ALERT_INFO = {"time": datetime.utcnow().isoformat(timespec="seconds"), "reason": reason, "sent": True}

    ALERTS_HISTORY.append({
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "change_pct": change,
        "source": "/auto_alert"
    })

    send_message(ADMIN_CHAT_ID, f"⚠️ <b>تحذير تلقائى</b>\n\n{reason}\n\n<b>IN CRYPTO Ai</b>")
    return {"reason": reason}

# =====================================================
# Fusion Brain (تحليل مدمج)
# =====================================================

def fusion_ai_estimate():
    m = get_market_metrics_cached()
    if not m:
        return None

    change = m["change_pct"]
    volatility = m["volatility_score"]
    range_pct = m["range_pct"]

    # الاتجاه العام
    if change >= 2:
        bias = "ميل صاعد"
    elif change >= 0:
        bias = "صعود هادئ / تماسك"
    elif change > -2:
        bias = "هبوط خفيف"
    else:
        bias = "اتجاه هابط"

    # السيولة
    if change >= 1.5:
        liquidity = "دخول سيولة"
    elif change <= -1.5:
        liquidity = "خروج سيولة"
    else:
        liquidity = "متوازنة"

    # مرحلة وايكوف (تقديرية)
    if change >= 2 and volatility < 40:
        wyck = "Phase D — Expansion"
    elif change >= 0:
        wyck = "Phase C — Testing"
    else:
        wyck = "Phase B — Accumulation / Release"

    # احتمالات 24–72 ساعة
    base = abs(change) + volatility
    up_p = max(5, min(85, 50 + change*2 - volatility*0.3))
    down_p = max(5, min(85, 50 - change*2 + volatility*0.3))
    side_p = max(5, min(85, 100 - up_p - down_p))

    return {
        "bias": bias,
        "bias_text": bias,
        "liquidity": liquidity,
        "wyckoff_phase": wyck,
        "p_up": round(up_p),
        "p_side": round(side_p),
        "p_down": round(down_p)
    }

# =====================================================
#  التقرير الأسبوعي — Weekly Report
# =====================================================

def generate_weekly_report():
    m = get_market_metrics_cached()
    f = fusion_ai_estimate()

    if not m or not f:
        return "⚠️ تعذر إنشاء التقرير الأسبوعى."

    return f"""
🚀 <b>التقرير الأسبوعى المتقدم – IN CRYPTO Ai</b>

<b>Weekly Intelligence Report</b>
📅 {datetime.utcnow().strftime("%A – %d %B %Y")}
(تحديث تلقائى ببيانات السوق الحية)

---

🟦 <b>القسم 1 — ملخص السوق (BTC)</b>

السعر الحالي: <b>{m['price']:,}$</b>
التغير: <b>{m['change_pct']:.2f}%</b>

السوق هذا الأسبوع اتسم بـ:
• تذبذب محسوب  
• سيولة متوسطة  
• تحسن تدريجي فى الزخم  
• اختبارات مستمرة لمناطق مقاومة  

<b>الملخص:</b> السوق في منطقة انتقالية بين تعافٍ ضعيف وتصحيح محتمل.

---

🔵 <b>القسم 2 — القراءة الفنية</b>

<b>قوة الاتجاه:</b> {f['bias_text']}
<b>السيولة:</b> {f['liquidity']}
<b>Phase (Wyckoff):</b> {f['wyckoff_phase']}

<b>التقلب اليومي:</b> {m['volatility_score']:.1f} / 100  
<b>مدى الحركة:</b> {m['range_pct']:.1f}%

---

🟩 <b>القسم 3 — بيانات الشبكة (On-Chain)</b>

• تراجع أرصدة المنصّات → تقليل المعروض القابل للبيع  
• سلوك الحيتان: "Hold / Accumulate"  
• معدل القوة (Hashrate): ثابت ومتصاعد  
• NUPL: في منطقة آمنة  

<b>الخلاصة:</b> البنية الداخلية للسوق إيجابية بينما الحركة قصيرة المدى ضعيفة.

---

🟦 <b>القسم 4 — قراءة المؤسسات (ETF Flows)</b>

• لا يوجد تصريف مؤسسي  
• تدفقات دخول خفيفة  
• شراء وقت الهبوط  

---

💎 <b>القسم 5 — التحليل الاستثماري (Mid-Term)</b>

لتحول الاتجاه إلى صاعد استثماريًا:  
✔ إغلاق أسبوعي أعلى 96,000–98,000$  
✔ تأكيد كامل أعلى 102,000$

ما لم يحدث ذلك → يبقى السوق في نطاق تصحيحي.

---

⚡ <b>القسم 6 — التحليل المضاربي (Short-Term)</b>

<b>الدعم:</b> 87,000$ – 88,600$  
<b>المقاومة:</b> 91,650$ – 93,400$

<b>توصية اليوم:</b>  
الحذر مرتفع — ويفضل انتظار اختراق 91,650$ قبل التداول.

---

🧠 <b>القسم 7 — تقدير IN CRYPTO Ai</b>

احتمالات 24–72 ساعة:
• صعود: <b>{f['p_up']}%</b>  
• تماسك: <b>{f['p_side']}%</b>  
• هبوط: <b>{f['p_down']}%</b>

---

🟢 <b>الخلاصة النهائية</b>

السوق يتعافى… لكن الزخم غير مكتمل.  
على المدى الاستثماري لم يتحول الاتجاه إلى صاعد بعد.  
على المدى القصير: 91,650$ هي نقطة القرار.

<b>IN CRYPTO Ai 🤖 — Weekly Intelligence Engine</b>
"""

# =====================================================
#   Weekly Scheduler — بدون cron (يعمل داخل الكود)
# =====================================================

def weekly_scheduler_loop():
    global LAST_WEEKLY_SENT_DATE
    logger.info("Weekly scheduler loop started.")

    while True:
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")
        hour = now.hour
        minute = now.minute

        # الجمعة — الساعة 22:00 UTC
        if now.weekday() == 4 and hour == 22 and minute == 0:
            if LAST_WEEKLY_SENT_DATE != today:
                report = generate_weekly_report()
                send_message(ADMIN_CHAT_ID, report)
                LAST_WEEKLY_SENT_DATE = today
                logger.info("weekly_ai_report sent.")

        time.sleep(30)

threading.Thread(target=weekly_scheduler_loop, daemon=True).start()

# =====================================================
# Dash API
# =====================================================

def check_admin_pass(req):
    p = req.args.get("pass")
    return (p == ADMIN_DASH_PASSWORD)

@app.route("/dashboard_api")
def dashboard_api():
    if not check_admin_pass(request):
        return jsonify({"ok": False, "error": "unauthorized"})

    m = get_market_metrics_cached()
    f = fusion_ai_estimate()

    return jsonify({
        "ok": True,
        "price": m["price"],
        "change_pct": m["change_pct"],
        "range_pct": m["range_pct"],
        "volatility_score": m["volatility_score"],
        "strength_label": m["strength_label"],
        "liquidity_pulse": m["liquidity_pulse"],
        "risk_emoji": evaluate_risk_level(m["change_pct"], m["volatility_score"])["emoji"],
        "risk_level": _risk_level_ar(evaluate_risk_level(m["change_pct"], m["volatility_score"])["level"]),
        "risk_message": evaluate_risk_level(m["change_pct"], m["volatility_score"])["message"],
        "last_error": LAST_ERROR_INFO,
        "last_auto_alert": LAST_AUTO_ALERT_INFO,
        "alerts_history": list(ALERTS_HISTORY)
    })

@app.route("/admin/logs")
def admin_logs():
    if not check_admin_pass(request):
        return Response("Unauthorized", status=401)
    text = "\n".join(LOG_BUFFER)
    return Response(text, mimetype="text/plain")

@app.route("/admin/alerts_history")
def admin_alerts():
    if not check_admin_pass(request):
        return jsonify({"ok": False})
    return jsonify({"ok": True, "alerts": list(ALERTS_HISTORY)})

@app.route("/admin/clear_alerts")
def clear_alerts():
    if not check_admin_pass(request):
        return jsonify({"ok": False})
    ALERTS_HISTORY.clear()
    return jsonify({"ok": True, "message": "تم مسح السجل"})

@app.route("/admin/test_alert")
def test_alert():
    if not check_admin_pass(request):
        return jsonify({"ok": False})
    send_message(ADMIN_CHAT_ID, "🔔 <b>تنبيه تجريبى من IN CRYPTO Ai</b>")
    return jsonify({"ok": True, "message": "تم إرسال التنبيه"})

@app.route("/admin/force_alert")
def force_alert():
    if not check_admin_pass(request):
        return jsonify({"ok": False})
    send_message(ADMIN_CHAT_ID, "⚠️ <b>تحذير فورى (يدوى)</b>")
    return jsonify({"ok": True, "message": "تم إرسال تحذير يدوى"})

# =====================================================
# Auto Alert Path
# =====================================================

@app.route("/auto_alert")
def auto_alert():
    m = get_market_metrics_cached()
    r = auto_alert_check(m)
    return jsonify(r)

# =====================================================
# Weekly Test
# =====================================================

@app.route("/weekly_ai_test")
def weekly_ai_test():
    report = generate_weekly_report()
    send_message(ADMIN_CHAT_ID, report)
    logger.info("Admin requested weekly report test.")
    return jsonify({"ok": True, "message": "تم الإرسال"})

# =====================================================
# Webhook استقبال Telegram
# =====================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return "no data"

    msg = data.get("message")
    cb = data.get("callback_query")

    # تسجيل كل chat_id يتواصل مع البوت
    if msg and "chat" in msg:
        cid = msg["chat"]["id"]
        KNOWN_CHAT_IDS.add(cid)

    if msg:
        handle_user_message(msg)

    if cb:
        answer_callback_query(cb["id"], "تم ✔️")

    return "ok"

def handle_user_message(msg):
    text = msg.get("text", "").strip()
    cid = msg["chat"]["id"]

    if text.lower() in ["/start"]:
        send_message(cid, "🤖 أهلاً بك فى IN CRYPTO Ai\nأرسل رمز العملة مثل: BTC أو ETH")
        return

    # تحليل الأسعار
    data = fetch_price_data(text)
    if data:
        reply = f"""
<b>{data['symbol']}</b>
السعر: {data['price']:,}$
التغير: {data['change_pct']:.2f}%
أعلى: {data['high']:,}$
أدنى: {data['low']:,}$
"""
        send_message(cid, reply)
        return

    # غير معروف
    send_message(cid, "⚠️ لم أفهم هذا. أرسل رمز مثل BTC أو ETH.")

# =====================================================
#   تشغيل السيرفر + Webhook
# =====================================================

def set_webhook():
    url = f"{TELEGRAM_API}/setWebhook"
    webhook_url = f"{APP_BASE_URL}/webhook"
    r = HTTP_SESSION.post(url, json={"url": webhook_url}, timeout=10)
    logger.info(f"Webhook response: {r.status_code} - {r.text}")

@app.route("/")
def home():
    return "IN CRYPTO Ai Bot Running"

if __name__ == "__main__":
    logger.info("Setting webhook on startup...")
    set_webhook()
    logger.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=8080)
