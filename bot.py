import os
import math
import requests
from flask import Flask, request, jsonify

# =========================
# إعدادات البوت
# =========================

# تقدر تخلي التوكن من المتغيرات البيئية لو حابب بعدين
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# =========================
# دوال مساعدة عامة
# =========================

def send_message(chat_id: int, text: str) -> None:
    """إرسال رسالة عادية لتليجرام (بدون Markdown لتجنب مشاكل الفورمات)."""
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        # لو حصل أي خطأ فى الإرسال نتجاهله عشان البوت ما يقعش
        pass


def safe_mean(values):
    return sum(values) / len(values) if values else 0.0


def compute_rsi(closes, period: int = 14):
    """حساب RSI بسيط من قائمة أسعار الإغلاق."""
    if len(closes) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-change)

    avg_gain = safe_mean(gains)
    avg_loss = safe_mean(losses)

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


# =========================
# جلب البيانات من Binance
# =========================

def fetch_binance_daily_candles(symbol: str, limit: int = 200):
    """
    جلب شمعات يومية من Binance.
    symbol مثال: BTCUSDT
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1d",
        "limit": limit,
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    # لو Binance رجعت خطأ
    if isinstance(data, dict) and data.get("code") is not None:
        raise ValueError(f"Binance error for symbol {symbol}: {data.get('msg')}")

    candles = []
    for item in data:
        # ترتيب الحقول فى klines:
        # 0: open time, 1: open, 2: high, 3: low, 4: close, 5: volume, ...
        candles.append(
            {
                "close": float(item[4]),
                "high": float(item[2]),
                "low": float(item[3]),
                "volume": float(item[5]),
            }
        )
    return candles


# =========================
# جلب البيانات من KuCoin (VAI فقط)
# =========================

def fetch_kucoin_daily_candles(symbol_pair: str = "VAI-USDT", limit: int = 200):
    """
    جلب شمعات يومية من KuCoin.
    symbol_pair مثال: VAI-USDT
    """
    url = "https://api.kucoin.com/api/v1/market/candles"
    params = {
        "type": "1day",        # إطار زمني يومي
        "symbol": symbol_pair, # VAI-USDT
    }
    resp = requests.get(url, params=params, timeout=10)
    j = resp.json()

    data = j.get("data", [])
    if not data:
        raise ValueError("No candles returned from KuCoin")

    # بيانات KuCoin بترجع من الأحدث للأقدم → نعكسها
    data_sorted = sorted(data, key=lambda x: float(x[0]))

    candles = []
    for item in data_sorted[-limit:]:
        # ترتيب الحقول فى KuCoin:
        # [ time, open, close, high, low, volume, turnover ]
        _, open_, close, high, low, volume, turnover = item
        candles.append(
            {
                "close": float(close),
                "high": float(high),
                "low": float(low),
                "volume": float(volume),
            }
        )
    return candles


# =========================
# اختيار المصدر المناسب (Binance / KuCoin)
# =========================

def fetch_daily_candles_for_symbol(user_symbol: str):
    """
    يحدد المنصة المناسبة ويعيد:
    (candles, symbol_pretty, source_name)
    """
    clean = user_symbol.upper().strip().replace(" ", "")

    # لو مفيش USDT نضيفها تلقائيًا
    if not clean.endswith("USDT"):
        clean = clean + "USDT"

    base = clean[:-4]  # الجزء قبل USDT

    # حالة خاصة: VAI من KuCoin
    if base == "VAI":
        candles = fetch_kucoin_daily_candles("VAI-USDT")
        return candles, "VAIUSDT", "KuCoin"

    # باقي العملات من Binance
    candles = fetch_binance_daily_candles(clean)
    return candles, clean, "Binance"


# =========================
# تحليل العملة وبناء التقرير
# =========================

def build_coin_report(user_symbol: str) -> str:
    try:
        candles, symbol, source_name = fetch_daily_candles_for_symbol(user_symbol)
    except Exception:
        return "⚠️ مش قادر أجيب بيانات للسوق للرمز ده. تأكد إنك كاتبه بالشكل الصحيح، مثال:\n/coin BTCUSDT أو /coin ETHUSDT أو /coin VAIUSDT"

    if len(candles) < 20:
        return "⚠️ البيانات المتاحة قليلة جدًا للتحليل."

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    last_close = closes[-1]
    prev_close = closes[-2]
    daily_change_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0

    # متوسطات متحركة (قصير / طويل)
    ma20 = safe_mean(closes[-20:])
    ma50 = safe_mean(closes[-50:]) if len(closes) >= 50 else ma20

    # اتجاه عام
    if last_close > ma20 and ma20 > ma50:
        trend_dir = "صاعد"
        trend_strength = "قوي"
    elif last_close < ma20 and ma20 < ma50:
        trend_dir = "هابط"
        trend_strength = "قوي"
    elif abs(last_close - ma20) / ma20 < 0.01:
        trend_dir = "جانبي"
        trend_strength = "ضعيف"
    elif last_close > ma20:
        trend_dir = "صاعد"
        trend_strength = "متوسط"
    elif last_close < ma20:
        trend_dir = "هابط"
        trend_strength = "متوسط"
    else:
        trend_dir = "جانبي"
        trend_strength = "متوسط"

    # RSI
    rsi = compute_rsi(closes[-30:])
    if rsi is None:
        rsi_text = "غير متاح"
        rsi_state = "لا توجد قراءة كافية حاليًا."
    else:
        if rsi >= 70:
            rsi_state = "تشبع شرائي (احتمال تصحيح هابط)."
        elif rsi <= 30:
            rsi_state = "تشبع بيعي (احتمال ارتداد لأعلى)."
        elif 45 <= rsi <= 55:
            rsi_state = "حالة حيادية تقريبًا."
        elif rsi > 55:
            rsi_state = "ميل صعودي خفيف."
        else:
            rsi_state = "ميل هبوطي خفيف."
        rsi_text = f"{rsi:.2f}"

    # نمط الحركة السعري (موقع السعر داخل النطاق)
    high_200 = max(c["high"] for c in candles)
    low_200 = min(c["low"] for c in candles)
    price_range = max(high_200 - low_200, 1e-8)
    pos = (last_close - low_200) / price_range  # من 0 إلى 1

    if pos >= 0.8:
        position_text = "السعر يتحرك قرب الحد العلوي من نطاق التداول؛ منطقة مقاومة محتملة."
    elif pos <= 0.2:
        position_text = "السعر يتحرك قرب الحد السفلي من نطاق التداول؛ منطقة دعم محتملة."
    else:
        position_text = "السعر في منتصف نطاق التداول تقريبًا؛ الحركة أقرب للجانية."

    # السيولة
    last_vol = volumes[-1]
    avg_vol_20 = safe_mean(volumes[-20:])
    vol_ratio = last_vol / avg_vol_20 if avg_vol_20 else 1.0

    if vol_ratio >= 1.3:
        volume_label = "سيولة مرتفعة نسبيًا."
    elif vol_ratio <= 0.7:
        volume_label = "سيولة ضعيفة مقارنة بالمعدل."
    else:
        volume_label = "سيولة متوسطة قريبة من المعتاد."

    # مستويات دعم / مقاومة بسيطة من آخر 30 يوم
    recent_closes = closes[-30:]
    support_level = min(recent_closes)
    resistance_level = max(recent_closes)

    # ملخص AI بسيط مبني على المؤشرات
    if trend_dir == "صاعد" and "مرتفع" in volume_label and rsi and rsi < 70:
        ai_comment = (
            "التجميع بين اتجاه صاعد وسيولة جيدة مع RSI غير متشبع شرائيًا "
            "يشير إلى سوق إيجابي نسبيًا، لكن يفضَّل انتظار مناطق دخول مناسبة."
        )
    elif trend_dir == "هابط" and rsi and rsi < 40:
        ai_comment = (
            "الاتجاه الهابط مع ميل RSI للضغط البيعي يعكس سوقًا ضعيفًا حاليًا، "
            "والتعامل معه يحتاج حذرًا شديدًا."
        )
    elif "ضعيفة" in volume_label:
        ai_comment = (
            "ضعف السيولة يجعل الحركة الحالية أقل موثوقية، وغالبًا ما تكون "
            "الاختراقات الكاذبة أكثر تكرارًا في مثل هذه الفترات."
        )
    else:
        ai_comment = (
            "قراءة المؤشرات الحالية تشير إلى سوق متوازن نسبيًا، "
            "بدون إشارات حادة قويّة في أي اتجاه."
        )

    source_text = "KuCoin" if source_name == "KuCoin" else "Binance"

    # =========================
    # تجميع نص التقرير
    # =========================

    report_lines = []

    report_lines.append(f"📌 *تحليل {symbol}* (إطار زمني: يومي – بيانات من {source_text})")
    report_lines.append("")
    report_lines.append("💰 السعر الحالي:")
    report_lines.append(f"- السعر التقريبي الآن: {last_close:,.2f} $")
    report_lines.append(f"- التغيّر اليومي التقريبي: {daily_change_pct:+.2f}٪")
    report_lines.append("")
    report_lines.append("📊 الاتجاه العام:")
    report_lines.append(f"- الاتجاه: {trend_dir}")
    report_lines.append(f"- قوة الاتجاه: {trend_strength}")
    report_lines.append("")
    report_lines.append("📈 مؤشر RSI:")
    report_lines.append(f"- قيمة RSI التقريبية: {rsi_text}")
    report_lines.append(f"- الحالة: {rsi_state}")
    report_lines.append("")
    report_lines.append("📉 نمط الحركة السعري:")
    report_lines.append(f"- {position_text}")
    report_lines.append("")
    report_lines.append("💧 السيولة (آخر 24 ساعة):")
    report_lines.append(f"- حجم تداول آخر يوم: {last_vol:,.0f}")
    report_lines.append(f"- متوسط حجم آخر 20 يومًا: {avg_vol_20:,.0f}")
    report_lines.append(f"- قراءة السيولة: {volume_label}")
    report_lines.append("")
    report_lines.append("🎯 مستويات مهمة للمراقبة (ليست توصية):")
    report_lines.append(f"- دعم رئيسي تقريبي: {support_level:,.4f} $")
    report_lines.append(f"- مقاومة رئيسية تقريبية: {resistance_level:,.4f} $")
    report_lines.append("")
    report_lines.append("🤖 قراءة سريعة من نظام الذكاء الاصطناعي للبوت:")
    report_lines.append(f"- {ai_comment}")
    report_lines.append("")
    report_lines.append("⚠️ *تنبيه مهم:* ده تحليل آلي تعليمي مبني على بيانات تاريخية فقط،")
    report_lines.append("مش نصيحة شراء أو بيع. دايمًا استخدم إدارة مخاطر تناسب حسابك.")

    # نرجع النص كله (من غير parse_mode هنشيل النجوم عشان ما تلخبطش)
    text = "\n".join(report_lines)
    # بما إننا ما بنستخدمش Markdown فعليًا، نشيل النجوم للتنسيق البسيط
    return text.replace("*", "")


# =========================
# Handlers للأوامر
# =========================

def handle_start(chat_id: int):
    msg = (
        "💎 أهلاً بيك!\n"
        "لتحليل أي عملة اكتب الأمر بهذا الشكل:\n"
        "/coin BTCUSDT\n\n"
        "مثال لعملة من KuCoin (VAI):\n"
        "/coin VAIUSDT"
    )
    send_message(chat_id, msg)


def handle_coin(chat_id: int, text: str):
    parts = text.strip().split()
    if len(parts) < 2:
        send_message(chat_id, "❗ اكتب الأمر هكذا:\n/coin BTCUSDT")
        return

    symbol = parts[1]
    waiting = f"⏳ يتم تحليل {symbol.upper()} آليًا..."
    send_message(chat_id, waiting)

    report = build_coin_report(symbol)
    send_message(chat_id, report)


# =========================
# Flask Webhook
# =========================

@app.route("/", methods=["GET"])
def index():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}

    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "") or ""

    if text.startswith("/start"):
        handle_start(chat_id)
    elif text.lower().startswith("/coin"):
        handle_coin(chat_id, text)
    else:
        send_message(
            chat_id,
            "❗ الأمر غير معروف.\n"
            "استخدم:\n"
            "/start لعرض طريقة الاستخدام\n"
            "/coin BTCUSDT لتحليل أي عملة."
        )

    return jsonify({"ok": True})


# =========================
# تشغيل التطبيق
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    # host 0.0.0.0 عشان Koyeb يقدر يوصل للتطبيق
    app.run(host="0.0.0.0", port=port)
