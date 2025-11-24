import os
import requests
from flask import Flask, request
from telegram import Bot
from datetime import datetime

# ======================
#   CONFIG
# ======================

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env variable is missing")

bot = Bot(token=TOKEN)

app = Flask(__name__)

BINANCE_API = "https://api.binance.com/api/v3"


# ======================
#   HELPERS
# ======================

def get_candles(symbol: str, interval: str = "1h", limit: int = 200):
    """
    جلب بيانات الشموع من Binance
    """
    url = f"{BINANCE_API}/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)

    if r.status_code != 200:
        raise RuntimeError(f"Binance error: {r.text}")

    data = r.json()
    closes = [float(c[4]) for c in data]
    highs = [float(c[2]) for c in data]
    lows = [float(c[3]) for c in data]
    times = [int(c[0]) for c in data]
    return closes, highs, lows, times


def simple_ma(values, period):
    if len(values) < period:
        period = len(values)
    return sum(values[-period:]) / period


def generate_ideas(symbol: str, closes, highs, lows):
    """
    توليد 10 أفكار آلية من بيانات السعر
    """
    ideas = []

    last_price = closes[-1]
    ma20 = simple_ma(closes, 20)
    ma50 = simple_ma(closes, 50)
    highest_50 = max(highs[-50:])
    lowest_50 = min(lows[-50:])

    change_24 = (closes[-1] - closes[-24]) / closes[-24] * 100 if len(closes) >= 25 else 0

    # 1 - الاتجاه العام
    if ma20 > ma50:
        ideas.append(
            f"الاتجاه العام على المدى القريب صاعد؛ المتوسط المتحرك 20 أعلى من 50. "
            f"السعر الحالى حوالى {last_price:.2f}."
        )
    else:
        ideas.append(
            f"الاتجاه العام على المدى القريب هابط؛ المتوسط المتحرك 20 تحت 50. "
            f"السعر الحالى حوالى {last_price:.2f}."
        )

    # 2 - نطاق دعم / مقاومة
    ideas.append(
        f"نطاق الحركة لآخر 50 شمعة تقريبًا بين دعم قرب {lowest_50:.2f} "
        f"ومقاومة قرب {highest_50:.2f}."
    )

    # 3 - وضع السعر بالنسبة للنطاق
    if last_price > (highest_50 * 0.99):
        ideas.append(
            "السعر حاليًا قريب من قمة النطاق الأخيرة؛ احتمال تصحيح أو كسر لأعلى."
        )
    elif last_price < (lowest_50 * 1.01):
        ideas.append(
            "السعر حاليًا قريب من قاع النطاق الأخيرة؛ منطقة قد تُستخدم كدعم محتمل."
        )
    else:
        ideas.append(
            "السعر يتحرك داخل النطاق الوسط؛ مفيش كسر واضح لدعم أو مقاومة حاليًا."
        )

    # 4 - أداء آخر 24 ساعة تقريبًا (24 شمعة ساعة)
    if change_24 > 3:
        ideas.append(
            f"خلال آخر 24 شمعة، الزوج طالع بحوالى {change_24:.2f}٪؛ موجة صعود قصيرة المدى."
        )
    elif change_24 < -3:
        ideas.append(
            f"خلال آخر 24 شمعة، الزوج نازل بحوالى {abs(change_24):.2f}٪؛ ضغط بيع واضح."
        )
    else:
        ideas.append(
            f"حركة آخر 24 شمعة ضعيفة نسبيًا (التغير حوالى {change_24:.2f}٪)؛ مفيش ترند قوى."
        )

    # 5 - فكرة عن الشراء مع الاتجاه
    if ma20 > ma50 and last_price > ma20:
        ideas.append(
            "استمرار التداول فوق المتوسط 20 فى اتجاه صاعد ممكن يخلى استراتيجيات "
            "الشراء مع الاتجاه (trend following) أكثر منطقية، مع إدارة مخاطرة جيدة."
        )
    else:
        ideas.append(
            "بقاء السعر تحت المتوسط 20 أو وجود تقاطع سلبى بين 20 و 50 يخلّى الشراء مع "
            "الاتجاه محتاج حذر شديد أو انتظار تأكيد انعكاس."
        )

    # 6 - فكرة عن الشراء من الدعوم
    ideas.append(
        "فى حالة رجوع السعر قرب مناطق الدعم (أسفل المتوسطات أو قرب القاع الأخير)، "
        "بعض المتداولين بيستهدفوا صفقات ارتداد (bounce) مع وقف خسارة ضيق تحت الدعم."
    )

    # 7 - فكرة عن البيع من المقاومات
    ideas.append(
        "لو السعر قرّب تانى من مناطق المقاومة أو القمم الأخيرة بدون أحجام كبيرة، "
        "استراتيجيات البيع من المقاومة (mean reversion) بتكون منطقية للبعض."
    )

    # 8 - مدى المخاطرة
    volatility = (highest_50 - lowest_50) / last_price * 100
    ideas.append(
        f"مدى تذبذب آخر 50 شمعة حوالى {volatility:.2f}٪؛ "
        "كل ما التذبذب أعلى زادت المخاطرة وأهمية حجم الصفقة الصغير."
    )

    # 9 - تقسيم المراكز
    ideas.append(
        "تقسيم الدخول والخروج على كذا مستوى سعرى (بدل صفقة واحدة كبيرة) "
        "بيقلل التأثر بأى ذبذبة مفاجئة فى السوق."
    )

    # 10 - تذكير بالمخاطرة
    ideas.append(
        "كل الأفكار دى تحليل آلى تعليمى فقط، ومش نصيحة استثمارية أو مالية. "
        "اعتمد دايمًا على خطتك وإدارة مخاطر تناسب حسابك."
    )

    return ideas


def parse_symbol_from_text(text: str) -> str:
    """
    استخراج الرمز من أمر /ideas
    """
    parts = text.strip().split()
    if len(parts) == 2:
        return parts[1].upper()
    return ""


# ======================
#   FLASK WEBHOOK
# ======================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}

    if "message" not in data:
        return "ok"

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    # /start
    if text == "/start":
        bot.send_message(
            chat_id,
            "🔥 أهلاً بيك فى بوت أفكار الكريبتو.\n"
            "اكتب مثلاً:\n"
            "/ideas BTCUSDT\n"
            "عشان أطلعلك 10 أفكار آلية مبنية على بيانات السوق من Binance "
            "للزوج ده (الإطار الزمنى: ساعة).",
        )
        return "ok"

    # /ideas SYMBOL
    if text.startswith("/ideas"):
        symbol = parse_symbol_from_text(text)
        if not symbol:
            bot.send_message(
                chat_id,
                "اكتب الأمر بالشكل ده:\n/ideas BTCUSDT",
            )
            return "ok"

        bot.send_message(
            chat_id,
            f"⏳ بجمع أفكار آلية لـ {symbol} من بيانات Binance...",
        )

        try:
            closes, highs, lows, times = get_candles(symbol)
        except Exception as e:
            bot.send_message(
                chat_id,
                f"❌ ماقدرتش أوصل لبيانات {symbol} من Binance.\n"
                f"السبب المحتمل: الرمز غلط أو السيرفر مش متاح حاليًا.",
            )
            return "ok"

        ideas = generate_ideas(symbol, closes, highs, lows)

        header = (
            f"💡 أفكار آلية مبنية على بيانات ساعة لآخر {len(closes)} شمعة لـ {symbol}:\n\n"
        )
        body_lines = []
        for i, idea in enumerate(ideas, start=1):
            body_lines.append(f"{i}. {idea}")

        bot.send_message(chat_id, header + "\n\n".join(body_lines))
        return "ok"

    # أى رسالة تانية
    bot.send_message(
        chat_id,
        "اكتب /start عشان تشوف طريقة الاستخدام.\n"
        "مثال: /ideas BTCUSDT",
    )

    return "ok"


# ======================
#   RUN FLASK (KOYEB)
# ======================

if __name__ == "__main__":
    # Koyeb بيشغل البورت من المتغير PORT لو موجود
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
