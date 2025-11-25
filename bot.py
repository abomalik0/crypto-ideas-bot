import requests
from flask import Flask, request

# ============ إعداد البوت ==============
TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
BOT_URL = f"https://api.telegram.org/bot{TOKEN}/"

app = Flask(__name__)

# ============ دوال مساعدة ==============

def send_message(chat_id, text):
    url = BOT_URL + "sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)


def get_klines(symbol, interval="1d", limit=300):
    """جلب بيانات الشموع من Binance"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    res = requests.get(url, params=params)
    if res.status_code != 200:
        return None
    return res.json()


# ============ دالة التحليل الرئيسية ==============

def analyze_symbol(symbol):
    data = get_klines(symbol)
    if data is None:
        return "❌ العملة غير صحيحة أو Binance لا يستجيب الآن."

    closes = [float(x[4]) for x in data]
    highs  = [float(x[2]) for x in data]
    lows   = [float(x[3]) for x in data]
    vols   = [float(x[5]) for x in data]

    last_close = closes[-1]

    # ——— الاتجاه العام ———
    ma20 = sum(closes[-20:]) / 20
    trend = "صاعد" if last_close > ma20 else "هابط"
    trend_text = f"الاتجاه العام: *{trend}* — السعر أعلى من MA20" if last_close > ma20 \
                 else f"الاتجاه العام: *هبوط* — السعر تحت MA20"

    # ——— نطاق آخر 200 شمعة ———
    low_200 = min(lows[-200:])
    high_200 = max(highs[-200:])
    range_perc = ((high_200 - low_200) / last_close) * 100

    # ——— موقع السعر الحالي ———
    if last_close <= low_200 + (high_200 - low_200) * 0.25:
        position_text = "في *المنطقة السفلية* (ضغط بيعي)."
    elif last_close >= high_200 - (high_200 - low_200) * 0.25:
        position_text = "في *المنطقة العلوية* (ضغط شرائي)."
    else:
        position_text = "في *المنتصف* (حيادي)."

    # ——— التقلب والزخم ———
    change_24 = ((closes[-1] - closes[-2]) / closes[-2]) * 100
    volatility_200 = (high_200 - low_200) / last_close * 100

    if volatility_200 < 2:
        volatility_label = "ضعيف"
    elif volatility_200 < 5:
        volatility_label = "متوسط"
    else:
        volatility_label = "مرتفع"

    # ——— حجم التداول ———
    avg_vol_20 = sum(vols[-20:]) / 20
    vol_ratio = vols[-1] / avg_vol_20

    if vol_ratio > 1.4:
        volume_label = "حجم تداول عالي"
    elif vol_ratio > 0.7:
        volume_label = "حجم تداول طبيعي"
    else:
        volume_label = "سيولة ضعيفة"

    # ——— الدعم والمقاومة ———
    support_level = low_200
    resistance_level = high_200

    # ============ نص التقرير =============
    report = f"""📌 *تقرير آلي سريع لزوج* `{symbol.upper()}`  
الإطار الزمني: *يومي* — بيانات من Binance.

💰 *السعر الحالي تقريبًا:* `{last_close:,.4f}` $

📍 *حركة السعر:*
- {trend_text}
- نطاق آخر 200 شمعة بين: `{low_200:,.4f}` و `{high_200:,.4f}` (≈ {range_perc:.2f}% من السعر الحالي).
- السعر حاليًا {position_text}

📊 *التقلب والزخم:*
- التقلب العام خلال الفترة: *{volatility_label}* (حوالي {volatility_200:.2f}% من السعر).
- التغير التقريبي لآخر يوم: `{change_24:+.2f}%` مقارنة باليوم السابق.

💧 *حجم التداول / السيولة:*
- متوسط حجم آخر 20 شمعة: `{avg_vol_20:,.0f}`
- حجم آخر شمعة ≈ `{vol_ratio:.2f}x` من المتوسط → {volume_label}

🎯 *مستويات فنية قريبة (ليست توصية):*
- دعم محتمل قرب: `{support_level:,.4f}`
- مقاومة محتملة قرب: `{resistance_level:,.4f}`

⚠️ *تنبيه مهم:*  
ده تحليل آلي تعليمي مبني على بيانات تاريخية فقط،  
ومش نصيحة شراء أو بيع.  
استخدم إدارة مخاطر تناسب حسابك دائمًا.
"""
    return report


# ============ استقبال التحديثات ==============

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text.startswith("/start"):
            send_message(chat_id,
"""🔥 أهلاً بيك في بوت أفكار الكريبتو.

اكتب:
`/coin BTCUSDT`
وهيجيلك تقرير يومي محترف مبني على بيانات Binance.""")

        elif text.startswith("/coin"):
            parts = text.split()
            if len(parts) < 2:
                send_message(chat_id, "❌ من فضلك اكتب العملة مثل:\n/coin BTCUSDT")
            else:
                symbol = parts[1].upper()
                send_message(chat_id, f"⏳ يتم تحليل `{symbol}` آليًا...")
                report = analyze_symbol(symbol)
                send_message(chat_id, report)

        else:
            send_message(chat_id, "❌ أمر غير معروف.")

    return "OK", 200


# ============ تشغيل السيرفر ==============
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
