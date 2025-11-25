import os
import math
import statistics as stats
import requests
from flask import Flask, request, jsonify

# ================== إعدادات أساسية ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

app = Flask(__name__)


# ================== دوال مساعدَة ==================
def send_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """إرسال رسالة لتليجرام."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print("Error sending message:", e)


def get_daily_klines(symbol: str, limit: int = 200):
    """
    تجيب بيانات شموع يومية من Binance.
    """
    params = {
        "symbol": symbol.upper(),
        "interval": "1d",
        "limit": limit,
    }
    r = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Binance error: {r.text}")
    data = r.json()
    if not data:
        raise RuntimeError("No kline data received from Binance")
    return data


def calc_rsi(closes, period: int = 14):
    """حساب RSI بسيط."""
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

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # نكمّل لباقي البيانات (مش مهم قوي للدقة العالية هنا)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss == 0:
            rs = float("inf")
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

    return rsi


def interpret_rsi(rsi: float) -> str:
    """رجّع جملة تشرح حالة RSI."""
    if rsi is None:
        return "غير متوفر"

    if rsi >= 70:
        return "في منطقة *تشبّع شرائي* (احتمال تصحيح هابط وارد)."
    elif rsi <= 30:
        return "في منطقة *تشبّع بيعي* (احتمال ارتداد صاعد وارد)."
    elif 45 <= rsi <= 55:
        return "في منطقة *حيادية تقريبًا*، مفيش ميل قوي للصعود أو الهبوط."
    elif rsi > 55:
        return "يميل إلى *قوة شرائية* بسيطة."
    else:  # rsi < 45
        return "يميل إلى *ضغط بيعي* بسيط."


def build_coin_report(symbol: str) -> str:
    """
    يبني تقرير كامل عن العملة المطلوبة.
    الإطار الزمني: يومي.
    """
    klines = get_daily_klines(symbol, limit=200)

    closes = [float(k[4]) for k in klines]   # سعر الإغلاق
    volumes = [float(k[5]) for k in klines]  # حجم التداول

    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else last_close

    last_volume = volumes[-1]
    recent_volumes_20 = volumes[-20:] if len(volumes) >= 20 else volumes
    avg_vol_20 = stats.mean(recent_volumes_20)

    # دعم / مقاومة تقريبية من آخر 60 يوم مثلا
    window = closes[-60:] if len(closes) >= 60 else closes
    support_level = min(window)
    resistance_level = max(window)

    # التغيّر اليومي كنسبة
    daily_change_perc = ((last_close - prev_close) / prev_close) * 100 if prev_close != 0 else 0

    # RSI
    rsi_value = calc_rsi(closes)
    rsi_text = interpret_rsi(rsi_value)

    # الاتجاه العام البسيط باستخدام MA20
    recent_20 = closes[-20:] if len(closes) >= 20 else closes
    ma20 = stats.mean(recent_20)
    if last_close > ma20 * 1.01:
        trend_dir = "صاعد"
        trend_strength = "قوي نسبيًا"
    elif last_close < ma20 * 0.99:
        trend_dir = "هابط"
        trend_strength = "واضح نسبيًا"
    else:
        trend_dir = "جانبي"
        trend_strength = "ضعيف / متذبذب"

    # نمط الحركة (قناة صاعدة / هابطة / جانبية) بناءً على آخر 30 يوم
    lookback = 30 if len(closes) >= 30 else len(closes) - 1
    if lookback <= 1:
        pattern_text = "البيانات قليلة لقراءة نمط الحركة."
    else:
        old_price = closes[-lookback]
        slope_perc = ((last_close - old_price) / old_price) * 100 if old_price != 0 else 0
        mid_price = (support_level + resistance_level) / 2

        if slope_perc > 5:
            channel = "قناة صاعدة"
        elif slope_perc < -5:
            channel = "قناة هابطة"
        else:
            channel = "قناة عرضية"

        # موقع السعر داخل النطاق
        if last_close >= resistance_level * 0.99:
            zone = "قرب *الحد العلوي* للنطاق (منطقة مقاومة)."
        elif last_close <= support_level * 1.01:
            zone = "قرب *الحد السفلي* للنطاق (منطقة دعم)."
        elif last_close >= mid_price:
            zone = "في *النصف العلوي* من النطاق السعري."
        else:
            zone = "في *النصف السفلي* من النطاق السعري."

        pattern_text = f"السعر يتحرك داخل *{channel}*، و{zone}"

    # سيولة
    vol_ratio = last_volume / avg_vol_20 if avg_vol_20 != 0 else 1
    if vol_ratio > 1.5:
        volume_label = "سيولة مرتفعة مقارنة بالمتوسط."
    elif vol_ratio < 0.7:
        volume_label = "سيولة ضعيفة مقارنة بالمتوسط."
    else:
        volume_label = "سيولة قريبة من المتوسط."

    # صياغة الأرقام بشكل ألطف
    def fmt_price(x):
        if x >= 1:
            return f"{x:,.2f}"
        else:
            return f"{x:.6f}"

    def fmt_big_number(x):
        # تحويل لحجم تقريبًا بملايين لو رقم كبير
        if x >= 1_000_000:
            return f"{x / 1_000_000:.2f}M"
        return f"{x:,.0f}"

    price_str = fmt_price(last_close)
    support_str = fmt_price(support_level)
    resistance_str = fmt_price(resistance_level)
    vol_str = fmt_big_number(last_volume)
    avg_vol_str = fmt_big_number(avg_vol_20)

    # ===== نص التقرير =====
    report = f"""📌 **تحليل {symbol.upper()}**  
(إطار زمني: يومي – بيانات من Binance)

💰 **السعر الحالي**
• السعر التقريبي الآن: *{price_str}$*
• التغيّر اليومي: *{daily_change_perc:+.2f}%*

📉 **الاتجاه العام**
• الاتجاه العام: *{trend_dir}*
• قوة الاتجاه: *{trend_strength}*

📊 **مؤشر RSI**
• قيمة RSI التقريبية: *{rsi_value:.2f}*  
• الحالة: {rsi_text}

📈 **نمط الحركة السعري**
• {pattern_text}

💦 **السيولة (آخر 24 ساعة تقريبًا)**
• حجم تداول آخر يوم: *{vol_str}*  
• متوسط حجم آخر 20 يوم: *{avg_vol_str}*  
• قراءة السيولة: *{volume_label}*

🎯 **مستويات مهمة للمراقبة (ليست توصية)**
• الدعم التقريبي: *{support_str}$*  
• المقاومة التقريبية: *{resistance_str}$*

📝 **الملخص**
• الاتجاه العام: *{trend_dir}*  
• قوة الاتجاه: *{trend_strength}*  
• حالة RSI: {rsi_text}

⚠️ *تنبيه مهم:* ده تحليل آلي تعليمي مبني على بيانات تاريخية فقط،  
مش نصيحة شراء أو بيع. دايمًا استخدم إدارة مخاطر تناسب حسابك.
"""
    return report


# ================== هاندلر الويب هوك ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True)
    # debug بسيط
    # print(update)

    if "message" not in update:
        return jsonify({"ok": True})

    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "") or ""

    text_lower = text.strip().lower()

    if text_lower.startswith("/start"):
        reply = (
            "💎 أهلاً بيك!\n"
            "لتحليل أي عملة أرسل:\n"
            "`/coin BTCUSDT`\n\n"
            "الإطار الزمني المستخدم: *يومي* مبني على بيانات Binance."
        )
        send_message(chat_id, reply, parse_mode="Markdown")
        return jsonify({"ok": True})

    if text_lower.startswith("/coin"):
        parts = text.strip().split()
        if len(parts) < 2:
            send_message(chat_id, "اكتب بالشكل ده:\n`/coin BTCUSDT`", parse_mode="Markdown")
            return jsonify({"ok": True})

        symbol = parts[1].upper()
        waiting = f"⏳ يتم تحليل {symbol} آليًا..."
        send_message(chat_id, waiting)

        try:
            report = build_coin_report(symbol)
            send_message(chat_id, report, parse_mode="Markdown")
        except Exception as e:
            print("Error in /coin:", e)
            send_message(
                chat_id,
                "⚠️ حصل خطأ أثناء جلب بيانات العملة.\n"
                "اتأكد إن الرمز مكتوب صح (مثال: BTCUSDT).",
            )

        return jsonify({"ok": True})

    # أي رسائل أخرى
    send_message(chat_id, "مش فاهم الأمر.\nجرب تكتب: `/start`", parse_mode="Markdown")
    return jsonify({"ok": True})


# ================== تشغيل Flask على كوييب ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
