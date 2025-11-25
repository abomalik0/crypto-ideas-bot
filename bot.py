import os
import math
import statistics
import requests
from flask import Flask, request, jsonify

# ======================
# إعدادات البوت و السيرفر
# ======================

BOT_TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# عنوان السيرفر على Koyeb مع مسار /webhook
WEBHOOK_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app/webhook"

app = Flask(__name__)


# ======================
# دوال مساعدة للتيليجرام
# ======================

def send_message(chat_id: int, text: str) -> None:
    """إرسال رسالة عادية لتليجرام."""
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"Error sending message: {e}")


def set_webhook() -> None:
    """تحديث / ضبط الـ webhook على عنوان السيرفر."""
    try:
        r = requests.get(
            f"{BASE_URL}/setWebhook",
            params={"url": WEBHOOK_URL},
            timeout=10,
        )
        print("SetWebhook response:", r.text)
    except Exception as e:
        print(f"Error setting webhook: {e}")


# ======================
# جلب البيانات من المنصات
# ======================

def get_binance_klines(symbol: str, limit: int = 200):
    """
    جلب شموع يومية من Binance.
    symbol مثال: BTCUSDT أو CFXUSDT
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"Binance error: {r.text}")
    data = r.json()
    if not data:
        raise ValueError("No kline data from Binance")
    return data


def get_kucoin_klines(symbol: str = "VAI-USDT", limit: int = 200):
    """
    جلب شموع يومية من KuCoin لعملة VAI فقط.
    لو حصل خطأ، هنرمي Exception ويتلَقط فوق.
    """
    url = "https://api.kucoin.com/api/v1/market/candles"
    params = {
        "symbol": symbol,
        "type": "1day",
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"KuCoin error: {r.text}")
    data = r.json()
    if data.get("code") != "200000":
        raise ValueError(f"KuCoin response error: {data}")
    candles = data.get("data", [])
    if not candles:
        raise ValueError("No kline data from KuCoin")
    # KuCoin بترجع من الأحدث للأقدم، هنرجع الترتيب كـ أقدم → أحدث
    candles.reverse()
    # هنحوّلها لصيغة شبه Binance: [open_time, open, high, low, close, volume, ...]
    klines = []
    for c in candles[:limit]:
        # c مثال: [time, open, close, high, low, volume, turnover]
        ts = int(float(c[0])) * 1000  # نخليها ms عشان تبقى شبه Binance
        open_p = c[1]
        close_p = c[2]
        high_p = c[3]
        low_p = c[4]
        vol = c[5]
        klines.append([ts, open_p, high_p, low_p, close_p, vol])
    return klines


# ======================
# حسابات فنية بسيطة
# ======================

def compute_rsi(closes, period: int = 14):
    """حساب RSI بشكل مبسط بدون تعقيد كبير."""
    if len(closes) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-change)

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def detect_trend_and_pattern(closes, highs, lows):
    """
    تحديد الاتجاه العام + شكل سعر بسيط (قناة / حركة جانبية)
    عشان نرجع وصف جاهز.
    """
    last_close = closes[-1]
    # متوسطات بسيطة
    sma_short = statistics.mean(closes[-20:]) if len(closes) >= 20 else statistics.mean(closes)
    sma_med = statistics.mean(closes[-50:]) if len(closes) >= 50 else sma_short
    sma_long = statistics.mean(closes[-100:]) if len(closes) >= 100 else sma_med

    # اتجاه من المتوسطات
    if last_close > sma_med > sma_long:
        trend_text = "الاتجاه العام يميل للصعود على المدى المتوسط والطويل."
        trend_dir = "up"
    elif last_close < sma_med < sma_long:
        trend_text = "الاتجاه العام يميل للهبوط على المدى المتوسط والطويل."
        trend_dir = "down"
    else:
        trend_text = "الاتجاه العام متذبذب ولا توجد سيطرة واضحة للمشترين أو البائعين."
        trend_dir = "side"

    # شكل السعر التقريبى (قناة / جانبي)
    window = min(60, len(closes))
    ref_close = closes[-window]
    price_change = last_close - ref_close
    rel_change = price_change / ref_close if ref_close != 0 else 0

    if rel_change > 0.08:
        shape_text = "حركة السعر حالياً تشبه قناة صاعدة مستقرة نسبيًا."
    elif rel_change < -0.08:
        shape_text = "حركة السعر حالياً تشبه قناة هابطة ويغلب عليها الضغط البيعي."
    else:
        shape_text = "السعر يتحرك في نطاق جانبي محدود بدون اتجاه واضح."

    # دعم ومقاومة بسيطة من آخر 60 شمعة
    recent_high = max(highs[-window:])
    recent_low = min(lows[-window:])
    mid_level = (recent_high + recent_low) / 2

    support_level = recent_low
    resistance_level = recent_high

    levels_text = (
        f"أقرب منطقة دعم رئيسية حول: {support_level:.4f}\n"
        f"أقرب منطقة مقاومة رئيسية حول: {resistance_level:.4f}\n"
        f"منطقة توازن تقريبية بينهما قرب: {mid_level:.4f}"
    )

    return trend_text, shape_text, levels_text, trend_dir


def describe_rsi(rsi_value):
    """تحويل قيمة RSI لنص مفهوم."""
    if rsi_value is None:
        return "لم تتوفر بيانات كافية لقراءة مؤشر القوة النسبية (RSI)."
    rsi = round(rsi_value, 1)
    if rsi >= 70:
        return f"مؤشر القوة النسبية عند حوالي {rsi} → يشير إلى حالة تشبع شرائي واحتمال زيادة ضغط التصحيح."
    elif rsi <= 30:
        return f"مؤشر القوة النسبية عند حوالي {rsi} → يشير إلى حالة تشبع بيعي واحتمال تحسن تدريجي إذا ظهرت سيولة شرائية."
    else:
        return f"مؤشر القوة النسبية عند حوالي {rsi} → وضع حيادي، لا توجد إشارة قوية على تشبع شراء أو بيع."


def ai_comment(volatility_score, trend_dir):
    """
    تعليق قصير من الذكاء الاصطناعي على المخاطر بناءً على
    مدى عنف الحركة + اتجاهها.
    """
    if volatility_score > 0.06:
        mood = "السوق حالياً يميل للعنف وتقلبات ملحوظة، ويُفضَّل تقليل الرافعة أو حجم المخاطرة."
    elif volatility_score > 0.03:
        mood = "السوق يتحرك بتذبذب متوسط؛ يمكن التعامل معه لكن مع مراعاة إيقاف الخسارة والانضباط في إدارة رأس المال."
    else:
        mood = "السوق هادئ نسبيًا من حيث التذبذب، لكن ذلك لا يمنع تغيُّر الحركة بشكل مفاجئ."

    if trend_dir == "up":
        trend_extra = "الاتجاه يميل للصعود، لكن المتابعة المستمرة ضرورية لتفادي أي انعكاس مفاجئ."
    elif trend_dir == "down":
        trend_extra = "الاتجاه يميل للهبوط، ويُفضَّل توخي الحذر في صفقات الشراء والالتزام بمستويات الخروج."
    else:
        trend_extra = "الاتجاه العام غير واضح، مما يجعل قرارات الدخول والخروج تحتاج لمزيد من الانضباط والصبر."

    return f"{mood}\n{trend_extra}"


def build_analysis_text(symbol: str, klines):
    """تحويل بيانات الشموع لتحليل نصى منسق."""

    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    last_close = closes[-1]

    # اتجاه عام + شكل سعر + مستويات
    trend_text, shape_text, levels_text, trend_dir = detect_trend_and_pattern(
        closes, highs, lows
    )

    # RSI
    rsi_value = compute_rsi(closes[-30:])  # نكتفي بآخر 30 قيمة
    rsi_text = describe_rsi(rsi_value)

    # تذبذب (للذكاء الاصطناعي)
    recent_window = min(30, len(closes))
    recent_closes = closes[-recent_window:]
    high_recent = max(recent_closes)
    low_recent = min(recent_closes)
    volatility_score = (high_recent - low_recent) / last_close if last_close != 0 else 0

    ai_text = ai_comment(volatility_score, trend_dir)

    # تجميع الرسالة
    msg_lines = []
    msg_lines.append(f"📊 تحليل يومي لعملة: {symbol.upper()}")
    msg_lines.append(f"السعر الحالي التقريبي: {last_close:.4f}\n")

    msg_lines.append("📌 الاتجاه وسلوك السعر:")
    msg_lines.append(f"- {trend_text}")
    msg_lines.append(f"- {shape_text}\n")

    msg_lines.append("📍 مستويات فنية مهمة:")
    msg_lines.append(levels_text + "\n")

    msg_lines.append("📈 قراءة سريعة لمؤشر القوة النسبية (RSI):")
    msg_lines.append(rsi_text + "\n")

    msg_lines.append("🤖 ملاحظة من نظام الذكاء الاصطناعي:")
    msg_lines.append(ai_text)
    msg_lines.append("\n—\nهذا التحليل آلي وتقريبي، ويُفضَّل استخدامه كنظرة عامة مع دمجه برؤيتك وخطتك الخاصة.")

    return "\n".join(msg_lines)


# ======================
#  Webhook  من تيليجرام
# ======================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True)
        if not update:
            return jsonify({"ok": True})

        message = update.get("message") or update.get("edited_message")
        if not message:
            return jsonify({"ok": True})

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()

        if not text:
            send_message(chat_id, "من فضلك أرسل أمراً نصياً مثل: /coin btcusdt")
            return jsonify({"ok": True})

        # ----- أوامر البوت -----

        if text.startswith("/start"):
            send_message(
                chat_id,
                "أهلاً بك 👋\n\n"
                "أرسل الأمر التالي للحصول على تحليل لأي عملة:\n"
                "`/coin btcusdt`\n"
                "أو فقط اكتُب الرمز بعد /coin مثل:\n"
                "`/coin cfx` أو `/coin eth`",
            )
            return jsonify({"ok": True})

        if text.startswith("/coin"):
            parts = text.split(maxsplit=1)
            if len(parts) == 1:
                send_message(
                    chat_id,
                    "اكتب الأمر بهذا الشكل:\n"
                    "`/coin btcusdt` أو `/coin cfx`",
                )
                return jsonify({"ok": True})

            raw_symbol = parts[1].strip().upper()

            # دعم كتابه مثل: cfx أو cfxusdt
            if raw_symbol == "VAI" or raw_symbol == "VAIUSDT":
                # KuCoin لعملة VAI
                try:
                    klines = get_kucoin_klines("VAI-USDT", limit=200)
                    reply = build_analysis_text("VAIUSDT", klines)
                    send_message(chat_id, reply)
                except Exception as e:
                    print("KuCoin error:", e)
                    send_message(
                        chat_id,
                        "تعذر جلب البيانات لعملة VAI حالياً من KuCoin. يُرجى المحاولة لاحقاً.",
                    )
                return jsonify({"ok": True})

            # باقي العملات من Binance
            if not raw_symbol.endswith("USDT"):
                symbol = raw_symbol + "USDT"
            else:
                symbol = raw_symbol

            try:
                klines = get_binance_klines(symbol, limit=200)
                reply = build_analysis_text(symbol, klines)
                send_message(chat_id, reply)
            except Exception as e:
                print("Binance error:", e)
                send_message(
                    chat_id,
                    "تعذر جلب بيانات هذه العملة من Binance.\n"
                    "تأكد من كتابة الرمز بشكل صحيح مثل: BTCUSDT أو CFXUSDT.",
                )

            return jsonify({"ok": True})

        # لو كتب حاجة تانية غير /start و /coin
        send_message(
            chat_id,
            "لم أفهم الأمر المرسل.\n"
            "استخدم:\n`/coin btcusdt` للحصول على تحليل عملة.",
        )
        return jsonify({"ok": True})

    except Exception as e:
        print("Webhook error:", e)
        # مهم جداً نرجّع Response عشان ميحصلش TypeError 500
        return jsonify({"ok": True})


if __name__ == "__main__":
    # ضبط الـ webhook عند تشغيل السيرفر
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
