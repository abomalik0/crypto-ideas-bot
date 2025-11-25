import os
import requests
from flask import Flask, request
from telegram import Bot

# =========================
# إعداد التوكن والبوت
# =========================
TOKEN = os.environ.get("BOT_TOKEN")
bot = Bot(token=TOKEN)

app = Flask(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


# =========================
# دوال مساعدة
# =========================

def get_market_data(symbol: str):
    """
    بيجيب آخر 200 شمعة ساعة من Binance
    ويرجع شوية أرقام جاهزة للتحليل.
    """
    params = {
        "symbol": symbol.upper(),
        "interval": "1h",
        "limit": 200,
    }

    try:
        r = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
    except Exception:
        return None

    if r.status_code != 200:
        return None

    data = r.json()
    if not data:
        return None

    closes = [float(k[4]) for k in data]
    highs = [float(k[2]) for k in data]
    lows = [float(k[3]) for k in data]
    volumes = [float(k[5]) for k in data]

    current_price = closes[-1]
    high_200 = max(highs)
    low_200 = min(lows)

    price_range = high_200 - low_200
    if price_range > 0:
        pos_in_range = (current_price - low_200) / price_range * 100
    else:
        pos_in_range = 50.0

    # تغير آخر 24 ساعة (تقريبى من آخر 24 شمعة ساعة)
    if len(closes) >= 25:
        prev_24 = closes[-25]
        change_24h = (current_price - prev_24) / prev_24 * 100
    else:
        change_24h = 0.0

    # اتجاه تقريبى من مقارنة السعر دلوقتى بسعر من 3 أيام تقريبًا (72 ساعة)
    if len(closes) >= 72:
        old_price = closes[-72]
        diff_pct = (current_price - old_price) / old_price * 100
    else:
        old_price = closes[0]
        diff_pct = (current_price - old_price) / old_price * 100

    if diff_pct > 1.5:
        trend = "صاعد"
        trend_comment = "السعر مايل للصعود على المدى القصير."
    elif diff_pct < -1.5:
        trend = "هابط"
        trend_comment = "السعر تحت ضغط هابط قصير المدى."
    else:
        trend = "عرضى"
        trend_comment = "الحركة أقرب للتجميع أو التذبذب الجانبي."

    # تقلب تقريبى
    volatility = (price_range / current_price) * 100 if current_price > 0 else 0.0

    # مقارنة حجم آخر شمعة بمتوسط آخر 24 شمعة
    if len(volumes) >= 24:
        avg_vol_24 = sum(volumes[-24:]) / 24
    else:
        avg_vol_24 = sum(volumes) / len(volumes)

    last_vol = volumes[-1]
    if avg_vol_24 > 0:
        volume_ratio = last_vol / avg_vol_24
    else:
        volume_ratio = 1.0

    if volume_ratio > 1.5:
        volume_comment = "حجم تداول أعلى من المعتاد؛ فيه اهتمام واضح على الزوج."
    elif volume_ratio < 0.7:
        volume_comment = "حجم تداول ضعيف نسبيًا؛ السيولة أقل من المتوسط."
    else:
        volume_comment = "حجم تداول قريب من المتوسط؛ السوق هادى نسبيًا."

    # مستويات دعم/مقاومة بسيطة من حدود النطاق
    support = low_200
    resistance = high_200

    return {
        "symbol": symbol.upper(),
        "current_price": current_price,
        "high_200": high_200,
        "low_200": low_200,
        "pos_in_range": pos_in_range,
        "change_24h": change_24h,
        "trend": trend,
        "trend_comment": trend_comment,
        "volatility": volatility,
        "volume_ratio": volume_ratio,
        "volume_comment": volume_comment,
        "support": support,
        "resistance": resistance,
    }


def build_analysis_message(info: dict) -> str:
    """
    بيحول الأرقام اللى فوق لرسالة عربية احترافية ومضغوطة.
    """
    symbol = info["symbol"]
    p = info["current_price"]
    high_200 = info["high_200"]
    low_200 = info["low_200"]
    pos = info["pos_in_range"]
    ch24 = info["change_24h"]
    trend = info["trend"]
    trend_comment = info["trend_comment"]
    vol = info["volatility"]
    vr = info["volume_ratio"]
    v_comment = info["volume_comment"]
    support = info["support"]
    resistance = info["resistance"]

    lines = []

    lines.append(f"🧭 تقرير آلى سريع لزوج {symbol}")
    lines.append("الإطار الزمنى: ساعة – بيانات من Binance\n")

    lines.append(f"💰 السعر الحالى تقريبًا: {p:,.4f} $")

    lines.append("\n📌 حركة السعر:")
    lines.append(f"- الاتجاه القصير: {trend} – {trend_comment}")
    lines.append(
        f"- نطاق آخر 200 شمعة: بين حوالى {low_200:,.4f} $ و {high_200:,.4f} $"
    )
    lines.append(f"- السعر حاليًا فى حدود {pos:.1f}% من النطاق ده (من القاع إلى القمة).")

    lines.append("\n📊 السيولة والتقلب:")
    lines.append(f"- التغير التقريبى خلال آخر 24 ساعة: {ch24:+.2f}%")
    lines.append(f"- درجة التقلب فى آخر 200 شمعة: حوالى {vol:.2f}% من السعر الحالى.")
    lines.append(
        f"- حجم آخر شمعة حوالى {vr:.1f}x من متوسط حجم آخر 24 شمعة → {v_comment}"
    )

    lines.append("\n🎯 مستويات فنية للمراقبة (مش توصية):")
    lines.append(f"- دعم محتمل قريب من: {support:,.4f} $")
    lines.append(f"- مقاومة محتملة قرب: {resistance:,.4f} $")

    lines.append(
        "\n⚠️ تنبيه هام: ده تحليل آلى تعليمى مبنى على بيانات تاريخية، "
        "مش نصيحة شراء أو بيع. دايمًا استخدم إدارة مخاطر تناسب حسابك."
    )

    return "\n".join(lines)


# =========================
# Telegram Webhook
# =========================

@app.route("/", methods=["GET"])
def index():
    return "Crypto Ideas Bot is running."


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" not in data:
        return "ok"

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        return "ok"

    # أمر /start
    if text.startswith("/start"):
        welcome = (
            "🔥 أهلاً بيك فى بوت أفكار الكريبتو.\n\n"
            "اكتب مثلاً:\n"
            "/coin BTCUSDT\n\n"
            "عشان أطلعلك تحليل آلى مبنى على بيانات السوق من Binance "
            "لفريم الساعة للزوج اللى تطلبه."
        )
        bot.send_message(chat_id, welcome)
        return "ok"

    # أمر /coin SYMBOL
    if text.startswith("/coin"):
        parts = text.split()
        if len(parts) < 2:
            bot.send_message(
                chat_id,
                "اكتب الأمر بالشكل ده:\n/coin BTCUSDT",
            )
            return "ok"

        symbol = parts[1].upper()

        bot.send_message(
            chat_id,
            f"⏳ بيتم تحليل {symbol} آليًا بناءً على آخر بيانات متاحة من Binance...",
        )

        info = get_market_data(symbol)
        if info is None:
            bot.send_message(
                chat_id,
                "❌ مش قادر أوصل لبيانات موثوقة للزوج ده دلوقتى.\n"
                "اتأكد إن الرمز صحيح على Binance (زى BTCUSDT، ETHUSDT) وحاول تانى.",
            )
            return "ok"

        msg = build_analysis_message(info)
        bot.send_message(chat_id, msg)
        return "ok"

    # أى رسالة تانية
    bot.send_message(
        chat_id,
        "لو حابب تحليل لعملة، استخدم الصيغة دى:\n/coin BTCUSDT",
    )
    return "ok"


# =========================
# تشغيل Flask (Koyeb)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
