import os
import math
import statistics
from flask import Flask, request, jsonify
import requests

# ========= إعدادات أساسية =========

TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
WEBHOOK_BASE_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"
BINANCE_API_URL = "https://api.binance.com"

app = Flask(__name__)

# ========= أدوات مساعدة للتليجرام =========

def send_message(chat_id: int, text: str):
    """إرسال رسالة تليجرام بنمط HTML"""
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[send_message ERROR] {e}", flush=True)


def set_webhook():
    """تعيين الويب هوك تلقائياً عند تشغيل السيرفر"""
    try:
        webhook_url = f"{WEBHOOK_BASE_URL}/webhook"
        r = requests.get(
            f"{TELEGRAM_API_URL}/setWebhook",
            params={"url": webhook_url},
            timeout=10,
        )
        print(f"[set_webhook] status={r.status_code}, resp={r.text}", flush=True)
    except Exception as e:
        print(f"[set_webhook ERROR] {e}", flush=True)

# ========= دوال البيانات من بينانس =========

def get_klines(symbol: str, interval: str = "1d", limit: int = 120):
    """
    جلب شموع من بينانس
    interval = 1d (يومي)
    limit = عدد الشموع (120 كفاية للـ MA و RSI)
    """
    url = f"{BINANCE_API_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_ticker_24h(symbol: str):
    """جلب بيانات التغير 24 ساعة"""
    url = f"{BINANCE_API_URL}/api/v3/ticker/24hr"
    params = {"symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

# ========= حساب المؤشرات الفنية =========

def calc_rsi(closes, period: int = 14):
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
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # اسمول سموثنج باقي البيانات
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def moving_average(values, length: int):
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def classify_trend(price, ma_short, ma_long):
    if ma_short is None or ma_long is None:
        return "البيانات غير كافية لتحديد الاتجاه."

    if price > ma_short > ma_long:
        return "اتجاه صاعد قوي على المدى المتوسط والطويل."
    if price > ma_short and ma_short <= ma_long:
        return "ميل صاعد، لكن لم يثبت بعد على المدى الطويل."
    if price < ma_short < ma_long:
        return "اتجاه هابط واضح على المدى المتوسط والطويل."
    if price < ma_short and ma_short >= ma_long:
        return "ضغط بيعي واضح، مع ضعف في الاتجاه الطويل."
    return "الاتجاه الحالي متذبذب، ولا يوجد اتجاه واضح حتى الآن."


def interpret_rsi(rsi):
    if rsi is None:
        return "لم نتمكن من حساب RSI بشكل موثوق."
    if rsi >= 70:
        return f"العملة في منطقة تشبع شرائي (RSI ≈ {rsi:.1f})، وقد تحتاج إلى تهدئة."
    if rsi <= 30:
        return f"العملة في منطقة تشبع بيعي (RSI ≈ {rsi:.1f})، واحتمال الارتداد قائم."
    if 30 < rsi < 45:
        return f"زخم هابط مسيطر نسبيًا (RSI ≈ {rsi:.1f})، لكن بدون تشبع بيعي حاد."
    if 55 < rsi < 70:
        return f"زخم صاعد جيد (RSI ≈ {rsi:.1f})، ولكن دون تشبع شرائي."
    return f"زخم حيادي تقريبًا (RSI ≈ {rsi:.1f})، ولا يوجد ميل حاد للصعود أو الهبوط."


def detect_support_resistance(highs, lows, lookback: int = 40):
    if len(highs) < lookback or len(lows) < lookback:
        return None, None
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    return recent_low, recent_high


def describe_price_action(closes, highs, lows):
    if len(closes) < 10:
        return "البيانات قليلة نسبيًا لوصف سلوك السعر بدقة."

    last_close = closes[-1]
    prev_close = closes[-2]
    change = (last_close - prev_close) / prev_close * 100

    # تذبذب بسيط باستخدام مدى الحركة
    ranges = [h - l for h, l in zip(highs[-20:], lows[-20:])]
    avg_range = statistics.mean(ranges) if ranges else 0
    last_range = highs[-1] - lows[-1] if highs and lows else 0
    vol_ratio = (last_range / avg_range) if avg_range > 0 else 1

    vol_text = "تذبذب متوسط."
    if vol_ratio > 1.6:
        vol_text = "تذبذب مرتفع نسبيًا حاليًا."
    elif vol_ratio < 0.7:
        vol_text = "تذبذب منخفض وهدوء نسبي في الحركة."

    if change > 3:
        move_text = "اليوم يميل إلى صعود قوي نسبيًا."
    elif change > 0.5:
        move_text = "اليوم يميل إلى صعود هادئ."
    elif change < -3:
        move_text = "اليوم يشهد هبوطًا واضحًا وضغطًا بيعيًا."
    elif change < -0.5:
        move_text = "اليوم يميل إلى هبوط محدود."
    else:
        move_text = "حركة اليوم حتى الآن جانبية تقريبًا."

    return f"{move_text} {vol_text}"


def describe_patterns(closes, highs, lows):
    """
    هنا نخليها بسيطة وخفيفة:
    - لو السعر يتحرك بين نطاق واضح → نقول حركة جانبية (قناة سعرية).
    - غير كدة → نقول لا توجد نماذج واضحة.
    """
    if len(closes) < 30:
        return "لا توجد حاليًا نماذج فنية واضحة بسبب قلة البيانات."

    recent_closes = closes[-30:]
    max_c = max(recent_closes)
    min_c = min(recent_closes)
    width = (max_c - min_c) / max_c if max_c != 0 else 0

    # حركة في قناة سعرية نسبية
    if width < 0.08:
        return "السعر يتحرك داخل نطاق جانبي (قناة سعرية) في الفترة الأخيرة."

    return "لا توجد حاليًا نماذج فنية قوية أو نماذج هارمونيك واضحة على هذا الإطار الزمني."


def ai_summary_text(symbol, trend_desc, rsi, support, resistance):
    parts = []

    # اتجاه
    if "صاعد" in trend_desc:
        parts.append("السوق يميل حاليًا إلى الإيجابية على هذا الزوج.")
    elif "هابط" in trend_desc:
        parts.append("السوق يميل حاليًا إلى السلبية على هذا الزوج.")
    else:
        parts.append("الصورة العامة للسوق على هذا الزوج ما زالت متذبذبة وغير محسومة.")

    # RSI
    if rsi is not None:
        if rsi >= 70:
            parts.append("الأسعار في مناطق مرتفعة نسبيًا، لذا قد يكون الدخول المتأخر أكثر خطورة.")
        elif rsi <= 30:
            parts.append("الأسعار في مناطق منخفضة نسبيًا، لكن ذلك لا يضمن الارتداد فورًا.")
        else:
            parts.append("مستوى الزخم الحالي متوازن نسبيًا، ويمكن متابعة حركة السعر بهدوء.")

    # دعم ومقاومة
    if support and resistance:
        parts.append(
            f"مستوى الدعم حول <b>{support:.4f}</b> والمقاومة بالقرب من <b>{resistance:.4f}</b> "
            "يُعدّان منطقتين مهمتين لمراقبة رد فعل السعر."
        )

    parts.append(
        "هذا التقييم آلي وتعليمي فقط من بوت IN CRYPTO AI، "
        "وليس توصية مباشرة بالشراء أو البيع."
    )

    return " ".join(parts)

# ========= دالة تحليل العملة =========

def analyze_symbol(symbol: str) -> str:
    try:
        # نحاول نحافظ على SYMBOL بالشكل الصحيح
        norm_symbol = symbol.upper().replace("/", "")
        if not norm_symbol.endswith("USDT"):
            norm_symbol = norm_symbol + "USDT"

        # جلب البيانات من بينانس
        klines = get_klines(norm_symbol, interval="1d", limit=120)
        ticker_24h = get_ticker_24h(norm_symbol)

        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]

        last_close = closes[-1]

        # تغيير 24 ساعة من API جاهزة
        change_percent = float(ticker_24h.get("priceChangePercent", 0.0))

        # موفينج أفريج
        ma_short = moving_average(closes, 20)
        ma_long = moving_average(closes, 50)
        trend_desc = classify_trend(last_close, ma_short, ma_long)

        # RSI
        rsi_value = calc_rsi(closes, period=14)
        rsi_text = interpret_rsi(rsi_value)

        # دعم ومقاومة
        support, resistance = detect_support_resistance(highs, lows, lookback=40)

        # سلوك السعر
        price_action = describe_price_action(closes, highs, lows)

        # نماذج فنية بسيطة
        patterns_text = describe_patterns(closes, highs, lows)

        # ملخص الذكاء الاصطناعي
        ai_text = ai_summary_text(norm_symbol, trend_desc, rsi_value, support, resistance)

        # تجهيز نص التغير
        sign = "➕" if change_percent >= 0 else "➖"
        change_line = f"{sign} التغير آخر 24 ساعة: {change_percent:.2f}%"

        # بناء رسالة نهائية
        msg_lines = []

        msg_lines.append(f"📌 <b>تحليل {norm_symbol} على الإطار اليومي</b>\n")
        msg_lines.append(f"💰 السعر الحالي: <b>{last_close:.4f} USDT</b>")
        msg_lines.append(change_line + "\n")

        msg_lines.append("📊 <b>الاتجاه العام (متوسط – طويل المدى)</b>")
        msg_lines.append(f"- ملخص الاتجاه: {trend_desc}")
        if ma_short is not None and ma_long is not None:
            msg_lines.append(f"- متوسط 20 يوم تقريبًا: <b>{ma_short:.4f}</b>")
            msg_lines.append(f"- متوسط 50 يوم تقريبًا: <b>{ma_long:.4f}</b>")
        msg_lines.append("")

        msg_lines.append("📍 <b>الدعوم والمقاومات التقريبية</b>")
        if support is not None and resistance is not None:
            msg_lines.append(f"- دعم رئيسي حول: <b>{support:.4f}</b>")
            msg_lines.append(f"- مقاومة رئيسية حول: <b>{resistance:.4f}</b>")
        else:
            msg_lines.append("- البيانات غير كافية لاستخراج دعوم ومقاومات موثوقة.")
        msg_lines.append("")

        msg_lines.append("🧪 <b>مؤشر القوة النسبية (RSI)</b>")
        msg_lines.append(f"- {rsi_text}\n")

        msg_lines.append("📈 <b>سلوك السعر في الفترة الأخيرة</b>")
        msg_lines.append(f"- {price_action}\n")

        msg_lines.append("🎨 <b>النماذج الفنية</b>")
        msg_lines.append(f"- {patterns_text}\n")

        msg_lines.append("🤖 <b>ملخص الذكاء الاصطناعي للبوت</b>")
        msg_lines.append(f"- {ai_text}\n")

        msg_lines.append("⚠️ <b>تنبيه مهم</b>")
        msg_lines.append(
            "كل ما سبق تحليل آلي وتعليمي فقط من البوت، "
            "ولا يُعتبر نصيحة استثمارية مباشرة. الرجاء إدارة رأس المال بحكمة."
        )

        return "\n".join(msg_lines)

    except requests.HTTPError as e:
        return (
            "⚠️ حدث خطأ أثناء جلب البيانات من المنصة.\n"
            "تأكد أن الرمز مكتوب بشكل صحيح مثل: <b>/coin btcusdt</b>."
        )
    except Exception as e:
        print(f"[analyze_symbol ERROR] {e}", flush=True)
        return "⚠️ حدث خطأ غير متوقع أثناء التحليل. حاول مرة أخرى لاحقًا."

# ========= الهاندلر الرئيسي للويب هوك =========

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # للتأكد أن التليجرام يشوف إن السيرفر شغال
    if request.method == "GET":
        return "OK", 200

    update = request.get_json(silent=True)
    if not update:
        return "OK", 200

    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return "OK", 200

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            return "OK", 200

        # أوامر البوت
        if text.startswith("/start"):
            welcome = (
                "👋 أهلاً بك في <b>IN CRYPTO AI Bot</b>.\n\n"
                "اكتب أمر مثل:\n"
                "<b>/coin btcusdt</b> أو <b>/coin btc</b>\n"
                "ليقوم البوت بتحليل العملة على الإطار اليومي "
                "باستخدام بيانات بينانس وبعض المؤشرات الفنية.\n\n"
                "⚠️ التحليل تعليمي فقط وليس نصيحة استثمارية."
            )
            send_message(chat_id, welcome)

        elif text.startswith("/coin"):
            parts = text.split()
            if len(parts) < 2:
                send_message(
                    chat_id,
                    "💡 من فضلك اكتب الأمر بهذا الشكل:\n"
                    "<b>/coin btcusdt</b> أو <b>/coin btc</b>."
                )
            else:
                raw_symbol = parts[1]
                analysis = analyze_symbol(raw_symbol)
                send_message(chat_id, analysis)

        else:
            # رد بسيط لو كتب أي حاجة تانية
            send_message(
                chat_id,
                "💡 لاستخدام البوت:\n"
                "- اكتب <b>/start</b> لعرض الشرح.\n"
                "- أو استخدم أمر تحليل عملة مثل:\n"
                "<b>/coin btcusdt</b> أو <b>/coin eth</b>."
            )

    except Exception as e:
        print(f"[webhook ERROR] {e}", flush=True)

    # مهم جداً: دايمًا نرجّع Response عشان مايحصلش TypeError
    return "OK", 200

# ========= تشغيل التطبيق على كوييب =========

if __name__ == "__main__":
    print("Bot is starting with webhook mode...", flush=True)
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
