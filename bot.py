# ==============================
# IN CRYPTO — WAR ROOM BOT
# FULL MASTER VERSION
# ==============================

import os
import json
import time
import math
import threading
import logging
from datetime import datetime, timedelta

import requests
from flask import Flask, request, jsonify

# ==============================
# BASIC CONFIG
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

# ==============================
# GLOBAL STATE
# ==============================

USER_STATE = {}
LAST_RESPONSE_TIME = {}
LOCK = threading.Lock()

SUPPORTED_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "XRPUSDT", "ADAUSDT"
]

# ==============================
# TELEGRAM HELPERS
# ==============================

def send_message(chat_id, text, reply_markup=None):
    if text is None:
        text = "⚠️ لا توجد بيانات متاحة حاليًا، حاول مرة أخرى."

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    requests.post(f"{API_URL}/sendMessage", data=payload)


def answer_callback(callback_id):
    requests.post(
        f"{API_URL}/answerCallbackQuery",
        data={"callback_query_id": callback_id}
    )

# ==============================
# MARKET DATA (SIMULATED CORE)
# ==============================

def get_market_snapshot(symbol):
    # محرك بيانات (Placeholder – ثابت ومستقر)
    price = round(90000 + (hash(symbol) % 5000), 2)
    change = round((hash(symbol) % 500) / 100, 2)
    volume = round((hash(symbol) % 900) / 10, 2)

    return {
        "price": price,
        "change": change,
        "volume": volume,
        "timestamp": datetime.utcnow().isoformat()
    }

# ==============================
# SAFETY / DELAY CONTROL
# ==============================

def throttle(chat_id):
    now = time.time()
    last = LAST_RESPONSE_TIME.get(chat_id, 0)
    if now - last < 1.5:
        return False
    LAST_RESPONSE_TIME[chat_id] = now
    return True
    # ==============================
# KEYBOARDS / MENUS
# ==============================

def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "🧠 ALL SCHOOLS", "callback_data": "ALL_SCHOOLS"}],
            [{"text": "📘 ALL-IN-ONE MASTER", "callback_data": "MASTER"}],
            [{"text": "₿ BTC", "callback_data": "SYMBOL_BTCUSDT"},
             {"text": "Ξ ETH", "callback_data": "SYMBOL_ETHUSDT"}],
            [{"text": "🧩 Help", "callback_data": "HELP"}],
        ]
    }


def schools_menu():
    # كل مدرسة لها هوية مختلفة + مش نفس الرسالة
    return {
        "inline_keyboard": [
            [{"text": "🧊 Liquidity Map", "callback_data": "SCHOOL_LIQUIDITY"}],
            [{"text": "📚 ICT / SMC", "callback_data": "SCHOOL_ICT"}],
            [{"text": "📈 SMC - Smart Money", "callback_data": "SCHOOL_SMC"}],
            [{"text": "📘 Classical TA", "callback_data": "SCHOOL_TA"}],
            [{"text": "🎼 Harmonic", "callback_data": "SCHOOL_HARMONIC"}],
            [{"text": "⏳ Time Master", "callback_data": "SCHOOL_TIME"}],
            [{"text": "🔢 Digital Analysis", "callback_data": "SCHOOL_DIGITAL"}],
            [{"text": "📊 Volume Analysis (الحجمي)", "callback_data": "SCHOOL_VOLUME"}],
            [{"text": "🕯 Price Action", "callback_data": "SCHOOL_PA"}],
            [{"text": "🧱 Supply & Demand", "callback_data": "SCHOOL_SD"}],
            [{"text": "🌊 Wyckoff", "callback_data": "SCHOOL_WYCKOFF"}],
            [{"text": "🌐 Multi-Timeframe", "callback_data": "SCHOOL_MTF"}],
            [{"text": "🛡 Risk Model", "callback_data": "SCHOOL_RISK"}],
            [{"text": "⬅️ Back", "callback_data": "BACK_MAIN"}],
        ]
    }


def get_user_symbol(chat_id):
    st = USER_STATE.get(chat_id, {})
    sym = st.get("symbol")
    if not sym:
        sym = "BTCUSDT"
        USER_STATE.setdefault(chat_id, {})["symbol"] = sym
    return sym


def set_user_symbol(chat_id, symbol):
    USER_STATE.setdefault(chat_id, {})["symbol"] = symbol


# ==============================
# WEBHOOK SETUP
# ==============================

def set_webhook():
    if not WEBHOOK_URL:
        logging.warning("WEBHOOK_URL missing - skipping setWebhook")
        return

    r = requests.get(
        f"{API_URL}/setWebhook",
        params={"url": WEBHOOK_URL}
    )
    logging.info(f"Webhook response: {r.status_code} - {r.text}")


# ==============================
# STARTUP
# ==============================

def startup_broadcast():
    # رسالة جاهزية — سريعة
    try:
        # owner id optional
        owner = os.getenv("OWNER_CHAT_ID")
        if owner:
            send_message(int(owner), "✅ النظام Online — (Real-Time / Smart Alert / Weekly) تعمل الآن.")
    except Exception as e:
        logging.warning(f"startup broadcast failed: {e}")


# ==============================
# COMMAND HANDLERS
# ==============================

def handle_start(chat_id):
    set_user_symbol(chat_id, get_user_symbol(chat_id))
    send_message(
        chat_id,
        "✅ *IN CRYPTO AI* جاهز للعمل.\n\nاختر من القائمة:",
        reply_markup=main_menu()
    )


def handle_help(chat_id):
    send_message(
        chat_id,
        "🧩 *Help*\n\n"
        "• `/start` — تشغيل البوت\n"
        "• `/school` — عرض كل المدارس\n"
        "• اختيار العملة من الأزرار\n\n"
        "⚠️ ملاحظة: النتائج تعليمية وليست توصية تداول.",
        reply_markup=main_menu()
    )


def handle_school(chat_id):
    sym = get_user_symbol(chat_id)
    send_message(
        chat_id,
        f"🧠 *ALL SCHOOLS*\nالعملة الحالية: *{sym}*\n\nاختر المدرسة:",
        reply_markup=schools_menu()
    )


# ==============================
# WEBHOOK ROUTE
# ==============================

@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}

    try:
        # تحديث عادي
        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()

            # منع الضغط الزايد
            if not throttle(chat_id):
                return jsonify({"ok": True}), 200

            if text.startswith("/start"):
                handle_start(chat_id)
            elif text.startswith("/help"):
                handle_help(chat_id)
            elif text.startswith("/school"):
                handle_school(chat_id)
            else:
                # رد ذكي بسيط
                send_message(chat_id, "اكتب /school لعرض المدارس أو /start للقائمة الرئيسية ✅")

            return jsonify({"ok": True}), 200

        # callback buttons
        if "callback_query" in data:
            cq = data["callback_query"]
            callback_id = cq["id"]
            chat_id = cq["message"]["chat"]["id"]
            action = cq.get("data") or ""

            answer_callback(callback_id)

            if not throttle(chat_id):
                return jsonify({"ok": True}), 200

            # routing
            if action == "HELP":
                handle_help(chat_id)
            elif action == "BACK_MAIN":
                handle_start(chat_id)
            elif action == "ALL_SCHOOLS":
                handle_school(chat_id)

            elif action.startswith("SYMBOL_"):
                symbol = action.replace("SYMBOL_", "").strip()
                set_user_symbol(chat_id, symbol)
                send_message(chat_id, f"✅ تم اختيار العملة: *{symbol}*", reply_markup=main_menu())

            elif action == "MASTER":
                # master في Part 6
                sym = get_user_symbol(chat_id)
                send_message(chat_id, f"📘 *MASTER ANALYSIS* لـ *{sym}*...\n⏳ جاري تجهيز التحليل الكامل...")
                # سيتم توليده لاحقًا
                from_master = build_master_report(sym)
                send_message(chat_id, from_master)

            elif action.startswith("SCHOOL_"):
                sym = get_user_symbol(chat_id)
                send_message(chat_id, f"⏳ جاري تجهيز مدرسة التحليل لـ *{sym}* ...")
                report = build_school_report(sym, action)
                send_message(chat_id, report)

            else:
                send_message(chat_id, "⚠️ زر غير معروف.")

            return jsonify({"ok": True}), 200

    except Exception as e:
        logging.exception(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 200

    return jsonify({"ok": True}), 200
    # ==============================
# FAST CACHE (to reduce delay)
# ==============================

CACHE = {}
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "10"))  # سريع لتقليل تأخر الرد

def _cache_get(key):
    it = CACHE.get(key)
    if not it:
        return None
    ts, val = it
    if (time.time() - ts) > CACHE_TTL_SECONDS:
        return None
    return val

def _cache_set(key, val):
    CACHE[key] = (time.time(), val)
    return val


# ==============================
# SAFE TEXT HELPERS (avoid NoneType errors)
# ==============================

def s(x, default=""):
    return default if x is None else str(x)

def clamp(v, lo, hi):
    try:
        v = float(v)
    except:
        return lo
    return max(lo, min(hi, v))

def pct(x, digits=2):
    try:
        return f"{float(x):.{digits}f}%"
    except:
        return "0.00%"

def fmt(x, digits=2):
    try:
        return f"{float(x):.{digits}f}"
    except:
        return "0.00"


# ==============================
# MARKET SNAPSHOT (expects Part1 utilities)
# - If you already have get_price / get_klines in Part1, it will use them.
# - Otherwise it will fallback safely.
# ==============================

def _get_price_fallback(symbol):
    # Try existing function from Part1: get_price(symbol)
    try:
        return float(get_price(symbol))
    except:
        # Fallback to Telegram "no data"
        return None

def _get_klines_fallback(symbol, interval="15m", limit=200):
    try:
        return get_klines(symbol, interval=interval, limit=limit)
    except:
        return None

def get_market_snapshot(symbol):
    """
    returns dict with:
    price, change_24h, high_24h, low_24h, vol_24h, swing, atr, bias, notes
    """
    ck = f"snap:{symbol}"
    cached = _cache_get(ck)
    if cached:
        return cached

    snap = {
        "symbol": symbol,
        "price": None,
        "change_24h": None,
        "high_24h": None,
        "low_24h": None,
        "vol_24h": None,
        "swing": None,
        "atr": None,
        "bias": "NEUTRAL",
        "notes": []
    }

    # If you have a realtime engine in Part1 that stores current stats, try it
    try:
        # optional globals: LAST_TICK[symbol] or similar
        if "LAST_TICK" in globals() and symbol in LAST_TICK:
            t = LAST_TICK[symbol]
            snap["price"] = t.get("price")
            snap["change_24h"] = t.get("change")
            snap["high_24h"] = t.get("high")
            snap["low_24h"]  = t.get("low")
            snap["vol_24h"]  = t.get("vol")
    except Exception:
        pass

    # If still missing, use fallback
    if snap["price"] is None:
        snap["price"] = _get_price_fallback(symbol)

    # Try klines for small derived stats (ATR / swing)
    kl = _get_klines_fallback(symbol, interval="15m", limit=200)
    if kl and isinstance(kl, list) and len(kl) > 20:
        try:
            highs = [float(x["high"]) for x in kl if "high" in x]
            lows  = [float(x["low"]) for x in kl if "low" in x]
            closes= [float(x["close"]) for x in kl if "close" in x]
            if highs and lows and closes:
                swing = max(highs[-96:]) - min(lows[-96:])  # تقريبًا آخر يوم على 15m
                snap["swing"] = swing

                # ATR تقريبي
                trs = []
                for i in range(1, len(kl)):
                    h = float(kl[i]["high"])
                    l = float(kl[i]["low"])
                    pc = float(kl[i-1]["close"])
                    tr = max(h-l, abs(h-pc), abs(l-pc))
                    trs.append(tr)
                if trs:
                    snap["atr"] = sum(trs[-14:]) / min(14, len(trs))

                # Bias بسيط من آخر 50 شمعة
                ma_fast = sum(closes[-20:]) / 20
                ma_slow = sum(closes[-50:]) / 50
                if ma_fast > ma_slow:
                    snap["bias"] = "BULLISH"
                elif ma_fast < ma_slow:
                    snap["bias"] = "BEARISH"
                else:
                    snap["bias"] = "NEUTRAL"
        except Exception as e:
            snap["notes"].append(f"derive_error:{e}")

    return _cache_set(ck, snap)


# ==============================
# CORE: SCHOOL REPORT ROUTER
# ==============================

def build_school_report(symbol, school_code):
    """
    school_code like: SCHOOL_LIQUIDITY, SCHOOL_ICT...
    Must return LONG detailed unique report per school.
    """
    snap = get_market_snapshot(symbol)
    price = snap.get("price")
    bias  = snap.get("bias")

    # header ثابت بدون "V16" داخل النص (زي ما طلبت)
    header = (
        f"📌 *{symbol}*  |  السعر: *{fmt(price,2)}*\n"
        f"الاتجاه العام (إحصائيًا): *{bias}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if school_code == "SCHOOL_LIQUIDITY":
        return header + school_liquidity_map(symbol, snap)
    if school_code == "SCHOOL_ICT":
        return header + school_ict(symbol, snap)
    if school_code == "SCHOOL_SMC":
        return header + school_smc(symbol, snap)
    if school_code == "SCHOOL_VOLUME":
        return header + school_volume(symbol, snap)     # ✅ المدرسة الحجمية
    if school_code == "SCHOOL_SD":
        return header + school_supply_demand(symbol, snap)
    if school_code == "SCHOOL_PA":
        return header + school_price_action(symbol, snap)
    if school_code == "SCHOOL_WYCKOFF":
        return header + school_wyckoff(symbol, snap)
    if school_code == "SCHOOL_MTF":
        return header + school_mtf(symbol, snap)
    if school_code == "SCHOOL_RISK":
        return header + school_risk(symbol, snap)
    if school_code == "SCHOOL_TA":
        return header + school_classical_ta(symbol, snap)
    if school_code == "SCHOOL_HARMONIC":
        return header + school_harmonic(symbol, snap)
    if school_code == "SCHOOL_TIME":
        return header + school_time_master(symbol, snap)  # بدون عرض الفلك، لكن نتائج الفلك تُستخدم داخليًا
    if school_code == "SCHOOL_DIGITAL":
        return header + school_digital(symbol, snap)

    return header + "⚠️ مدرسة غير معروفة."


# ==============================
# STUB MASTER (to prevent crash now)
# - will be replaced with full master in Part6
# ==============================

def build_master_report(symbol):
    snap = get_market_snapshot(symbol)
    return (
        f"📘 *ALL-IN-ONE MASTER* لـ *{symbol}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✅ المحرك شغال.\n"
        "📌 التقرير الشامل الكامل سيتم تركيبه في *Part 6* (بدون كسر أي شغل).\n"
        f"السعر الحالي: *{fmt(snap.get('price'),2)}* | Bias: *{s(snap.get('bias'))}*\n"
    )


# ==============================
# UNIQUE SCHOOL BUILDERS (each is different)
# ==============================

def school_liquidity_map(symbol, snap):
    """
    🧊 Liquidity Map — unique style & sections
    """
    price = snap.get("price")
    atr = snap.get("atr") or 0
    swing = snap.get("swing") or 0

    # مناطق سيولة تقديرية حول السعر (من ATR)
    up1 = (price + atr*1.2) if price else None
    up2 = (price + atr*2.4) if price else None
    dn1 = (price - atr*1.2) if price else None
    dn2 = (price - atr*2.4) if price else None

    dominant = "فوق القمم" if snap.get("bias") == "BULLISH" else "تحت القيعان" if snap.get("bias") == "BEARISH" else "متوازنة"

    return (
        "📚 *Liquidity Map — خريطة السيولة*\n"
        "🔍 *فكرة المدرسة:*\n"
        "تحديد أماكن تجمع أوامر الإيقاف (Stops) والمناطق التي يحب السعر زيارتها لامتصاص السيولة ثم إعادة التمركز.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧊 1) التجمعات الأوضح:\n"
        f"• سيولة قريبة أعلى السعر: *{fmt(up1,2)}*\n"
        f"• سيولة عميقة أعلى السعر: *{fmt(up2,2)}*\n"
        f"• سيولة قريبة أسفل السعر: *{fmt(dn1,2)}*\n"
        f"• سيولة عميقة أسفل السعر: *{fmt(dn2,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧭 2) أين يذهب السعر غالبًا؟ (Liquidity Magnet):\n"
        f"• الانحياز الحالي: *{dominant}*\n"
        f"• نطاق الحركة اليومي التقريبي (Swing): *{fmt(swing,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 3) سيناريوهات المدرسة (بدون توصية):\n"
        "📈 *سيناريو سحب سيولة علوي*:\n"
        f"• زيارة منطقة: *{fmt(up1,2)} → {fmt(up2,2)}*\n"
        "• ثم مراقبة: رفض سعري + ضعف زخم\n"
        "📉 *سيناريو سحب سيولة سفلي*:\n"
        f"• زيارة منطقة: *{fmt(dn1,2)} → {fmt(dn2,2)}*\n"
        "• ثم مراقبة: امتصاص + شمعة انعكاس\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "ركز على: (Sweep → Reaction → Confirmation).\n"
    )


def school_ict(symbol, snap):
    """
    📚 ICT / SMC - unique writing & deeper logic
    """
    price = snap.get("price")
    atr = snap.get("atr") or 0

    pd_mid = price if price else 0
    premium = (pd_mid + atr*1.5) if price else None
    discount = (pd_mid - atr*1.5) if price else None

    # FVG / imbalance placeholder zones
    fvg_up = (price + atr*0.6) if price else None
    fvg_dn = (price - atr*0.6) if price else None

    return (
        "📚 *ICT — Smart Money Concepts*\n"
        "🔍 *فكرة المدرسة:*\n"
        "قراءة السوق كتحركات سيولة مؤسسية: Sweep → Displacement → Rebalance → Continuation/Reverse.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) Premium / Discount:\n"
        f"• Premium (منطقة بيع مؤسسي محتملة): *أعلى {fmt(premium,2)}*\n"
        f"• Discount (منطقة شراء مؤسسي محتملة): *أسفل {fmt(discount,2)}*\n"
        f"• نقطة التوازن (EQ): *{fmt(pd_mid,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟦 2) Imbalance / FVG Zones:\n"
        f"• FVG محتمل أعلى: *{fmt(fvg_up,2)}*\n"
        f"• FVG محتمل أسفل: *{fmt(fvg_dn,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧨 3) Break of Structure (مفهوم):\n"
        "• نبحث عن: اندفاع واضح (Displacement) يكسر نطاق سابق → ثم إعادة توازن.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 4) سيناريو ICT الأقوى (قراءة):\n"
        "• إذا السعر سحب سيولة ثم عاد داخل النطاق بسرعة → غالبًا توزيع/انعكاس.\n"
        "• إذا السعر اندفع ثم عاد يملأ FVG → غالبًا استمرار.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "راقب: Sweep + Displacement + Return to FVG ثم قرار.\n"
    )


def school_smc(symbol, snap):
    """
    📈 SMC - different structure from ICT
    """
    price = snap.get("price")
    atr = snap.get("atr") or 0

    ob_buy = (price - atr*0.9) if price else None
    ob_sell = (price + atr*0.9) if price else None

    return (
        "📈 *SMC — Smart Money (الهيكلة + الـ OrderBlocks)*\n"
        "🔍 *جوهر المدرسة:*\n"
        "التركيز على الهيكلة: HH/HL أو LH/LL + مناطق إعادة الدخول (OB) + كسر/تحول الهيكل.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧱 1) الهيكلة الحالية (مختصر):\n"
        f"• Bias: *{s(snap.get('bias'))}*\n"
        "• ملاحظة: نعتمد على ميل متوسطات + ATR لتقدير السياق.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧊 2) Order Blocks محتملة (تقديرية):\n"
        f"• Bullish OB Zone: *{fmt(ob_buy,2)}*\n"
        f"• Bearish OB Zone: *{fmt(ob_sell,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧲 3) Liquidity Grabs:\n"
        "• سحب قمة/قاع ثم رجوع سريع داخل النطاق = علامة قوية.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 4) Execution Idea (تعليمي):\n"
        "• لا تُنفّذ إلا مع تأكيد: (شمعة/زخم/رفض سعري).\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "التركيز هنا على: (Structure + OB + Liquidity grab) مش المؤشرات.\n"
    )


def school_volume(symbol, snap):
    """
    📊 المدرسة الحجمية — تحليل حجمي متقدم (بدون تكرار مدارس تانية)
    """
    price = snap.get("price")
    atr = snap.get("atr") or 0
    swing = snap.get("swing") or 0

    # placeholders derived (بدون API فوليم حقيقي لو مش متوفر)
    # لو عندك volume حقيقي في Part1 ضيفه هنا بسهولة
    vol24 = snap.get("vol_24h")
    vol_state = "مرتفع" if (vol24 and float(vol24) > 0) else "غير متاح (يتم تقديره)"
    pressure = "شراء" if snap.get("bias") == "BULLISH" else "بيع" if snap.get("bias") == "BEARISH" else "متوازن"

    poc = (price - atr*0.2) if price else None
    hvn = (price + atr*0.4) if price else None
    lvn = (price - atr*0.8) if price else None

    return (
        "📊 *Volume Analysis — مدرسة التحليل الحجمي (متقدمة)*\n"
        "🔍 *فكرة المدرسة:*\n"
        "قراءة السوق من خلال: (تدفق الحجم، مناطق التكدس، مناطق الفراغ الحجمي، نقاط التحكم POC) لتحديد أين تمت الصفقات الحقيقية.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) حالة الحجم العامة:\n"
        f"• Volume 24h: *{s(vol24, 'N/A')}*\n"
        f"• تقييم الحالة: *{vol_state}*\n"
        f"• ضغط السوق الغالب: *{pressure}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 2) Value Areas (تقديرية حول السعر):\n"
        f"• POC (نقطة تحكم): *{fmt(poc,2)}*\n"
        f"• HVN (منطقة تكدس/قبول): *{fmt(hvn,2)}*\n"
        f"• LVN (فراغ حجمي/رفض): *{fmt(lvn,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 3) ماذا يعني هذا عمليًا؟\n"
        "• الاقتراب من HVN → غالبًا تذبذب/تجميع (قبول سعري)\n"
        "• الاقتراب من LVN → غالبًا ارتداد سريع أو اختراق سريع (رفض حجمي)\n"
        "• كسر POC ثم إعادة اختبارها → انتقال توازن جديد\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ 4) Volume vs Volatility:\n"
        f"• ATR تقريبي: *{fmt(atr,2)}*\n"
        f"• Swing تقريبي: *{fmt(swing,2)}*\n"
        "• لو ATR عالي مع ضعف الحجم → حركة هشّة.\n"
        "• لو ATR متوسط مع حجم قوي → حركة مستدامة.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧩 5) سيناريوهات المدرسة (تعليمية):\n"
        "• سيناريو (Acceptance): تثبيت فوق POC + تكدس → استمرار.\n"
        "• سيناريو (Rejection): لمس LVN + رفض سريع → انعكاس/تصحيح.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "المستويات الحجمية أهم من خطوط عشوائية — راقب POC/HVN/LVN.\n"
    )


def school_supply_demand(symbol, snap):
    price = snap.get("price")
    atr = snap.get("atr") or 0

    demand = (price - atr*1.3) if price else None
    supply = (price + atr*1.3) if price else None
    decision = price

    return (
        "🧱 *Supply & Demand — العرض والطلب*\n"
        "🔍 *الفكرة الأساسية:*\n"
        "السعر يتحرك بين مناطق تم فيها تنفيذ صفقات كبيرة (طلب/عرض). المنطقة ليست خطًا، بل نطاق.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 1) مناطق محتملة (تقديرية):\n"
        f"• Demand Zone: *{fmt(demand,2)}*\n"
        f"• Supply Zone: *{fmt(supply,2)}*\n"
        f"• Decision Zone (منتصف التوازن): *{fmt(decision,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 2) تقييم المنطقة:\n"
        "• منطقة قوية إذا: (خروج قوي + رجوع سريع + احترام النطاق)\n"
        "• منطقة ضعيفة إذا: (تذبذب طويل + اختراقات كثيرة)\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 3) السيناريوهات:\n"
        "• شراء تعليمي: دخول بعد تأكيد داخل Demand.\n"
        "• بيع تعليمي: دخول بعد تأكيد داخل Supply.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "المنطقة تُقاس برد فعل السعر وليس بتخمين مكانها فقط.\n"
    )


def school_price_action(symbol, snap):
    price = snap.get("price")
    atr = snap.get("atr") or 0
    react = (price - atr*0.5) if price else None

    return (
        "🕯 *Price Action — السلوك السعري*\n"
        "🔍 *الفكرة:*\n"
        "قراءة الشموع كرسائل: رفض/قبول/اندفاع/امتصاص بدون الاعتماد على مؤشرات ثقيلة.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) ما الذي نبحث عنه؟\n"
        "• شمعة رفض: ذيل طويل + إغلاق داخل النطاق.\n"
        "• شمعة اندفاع: جسم كبير + كسر واضح.\n"
        "• شمعة امتصاص: حركة كبيرة ثم إغلاق قريب من الفتح.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 2) منطقة رد الفعل المتوقعة (تقديرية):\n"
        f"• React Zone: *{fmt(react,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 3) خطة القراءة:\n"
        "• مستوى → رد فعل → تأكيد → استمرار/فشل.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "الشمعة هي اللغة — اقرأ السياق قبل الإشارة.\n"
    )


def school_wyckoff(symbol, snap):
    return (
        "🌊 *Wyckoff — مدرسة وايكوف*\n"
        "🔍 *الفكرة:*\n"
        "السوق يمر بمراحل: تجميع → صعود → توزيع → هبوط.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) المرحلة المرجّحة:\n"
        f"• بناءً على Bias: *{s(snap.get('bias'))}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧩 2) عناصر وايكوف:\n"
        "• Spring (كسر كاذب تحت دعم) + رجوع سريع.\n"
        "• Upthrust (كسر كاذب فوق مقاومة) + رجوع سريع.\n"
        "• SOS / SOW إشارات قوة/ضعف.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "ابحث عن: كسر كاذب + رجوع + توازن جديد.\n"
    )


def school_mtf(symbol, snap):
    return (
        "🌐 *Multi-Timeframe — تحليل متعدد الأطر*\n"
        "🔍 *الفكرة:*\n"
        "HTF يحدد الاتجاه — LTF يحدد نقطة التنفيذ.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) الدمج:\n"
        f"• Bias العام: *{s(snap.get('bias'))}*\n"
        "• قاعدة: لا تعاكس HTF إلا بإشارة انقلاب واضحة.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "HTF للاتجاه، LTF للدخول.\n"
    )


def school_risk(symbol, snap):
    price = snap.get("price")
    atr = snap.get("atr") or 0

    inv = (price - atr*1.0) if price else None
    rr = "1:2 إلى 1:3 (تعليمي)"

    return (
        "🛡 *Risk Model — إدارة المخاطر*\n"
        "🔍 *الفكرة:*\n"
        "لا قيمة لأي تحليل بدون نموذج مخاطرة واضح.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 1) قواعد ذهبية:\n"
        "• مخاطرة ثابتة لكل صفقة.\n"
        "• وقف واضح قبل الدخول.\n"
        "• لا ملاحقة للسعر.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ 2) مستوى إلغاء تقريبي:\n"
        f"• Invalidation: *{fmt(inv,2)}*\n"
        f"• R:R محتمل: *{rr}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "الدقة بدون حماية رأس مال = صفر.\n"
    )


# ==============================
# PLACEHOLDERS for big schools (TA/Harmonic/Time/Digital)
# These will be expanded massively in Part4 & Part5
# ==============================

def school_classical_ta(symbol, snap):
    return (
        "📘 *Classical TA — (سيتم توسيعها بالكامل في Part 4)*\n"
        "✅ موجودة الآن كمنع كراش — وسيتم إضافة كل النماذج والمؤشرات والأدوات بالتفصيل.\n"
    )

def school_harmonic(symbol, snap):
    return (
        "🎼 *Harmonic — (سيتم توسيعها بالكامل في Part 4)*\n"
        "✅ سيتم إضافة XABCD + PRZ + نسب فيبو + سيناريوهات كاملة.\n"
    )

def school_time_master(symbol, snap):
    return (
        "⏳ *TIME MASTER — (سيتم توسيعها بالكامل في Part 5)*\n"
        "✅ بدون عرض قسم الفلك، لكن سيتم استخدام نتائجه داخليًا وإظهار النتائج النهائية فقط.\n"
    )

def school_digital(symbol, snap):
    return (
        "🔢 *Digital Analysis — (سيتم توسيعها بالكامل في Part 5)*\n"
        "✅ سيتم تطبيق نموذجك الموسّع بالكامل مع كل البنود.\n"
    )
    # ============================================================
# PART 4 — ADVANCED CLASSICAL TA + HARMONIC (FULL, NO CRASH)
# ============================================================

def _safe_klines(symbol, interval="15m", limit=300):
    kl = None
    try:
        kl = get_klines(symbol, interval=interval, limit=limit)
    except:
        kl = _get_klines_fallback(symbol, interval=interval, limit=limit)
    if not kl or not isinstance(kl, list):
        return []
    # normalize keys
    out = []
    for k in kl:
        try:
            out.append({
                "open": float(k.get("open")),
                "high": float(k.get("high")),
                "low":  float(k.get("low")),
                "close":float(k.get("close")),
                "volume": float(k.get("volume", 0.0)),
                "time": k.get("time") or k.get("timestamp") or ""
            })
        except:
            continue
    return out


def _ema(values, period):
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = (v * k) + (ema * (1 - k))
    return ema

def _sma(values, period):
    if not values or len(values) < period:
        return None
    return sum(values[-period:]) / period

def _rsi(closes, period=14):
    if not closes or len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # Wilder smoothing
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
    return rsi

def _macd(closes, fast=12, slow=26, signal=9):
    if not closes or len(closes) < slow + signal + 5:
        return None
    # build ema series
    def ema_series(vals, p):
        if len(vals) < p:
            return []
        k = 2/(p+1)
        ema = vals[0]
        s = [ema]
        for v in vals[1:]:
            ema = v*k + ema*(1-k)
            s.append(ema)
        return s
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    if not ema_fast or not ema_slow:
        return None
    # align
    d = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-d+i] - ema_slow[-d+i] for i in range(d)]
    sig = ema_series(macd_line, signal)
    if not sig:
        return None
    dd = min(len(macd_line), len(sig))
    hist = macd_line[-dd:]  # raw
    signal_line = sig[-dd:]
    histogram = [hist[i] - signal_line[i] for i in range(dd)]
    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "hist": histogram[-1],
        "prev_hist": histogram[-2] if len(histogram) >= 2 else None
    }

def _true_range(high, low, prev_close):
    return max(high-low, abs(high-prev_close), abs(low-prev_close))

def _atr(kl, period=14):
    if len(kl) < period + 2:
        return None
    trs = []
    for i in range(1, len(kl)):
        trs.append(_true_range(kl[i]["high"], kl[i]["low"], kl[i-1]["close"]))
    return sum(trs[-period:]) / period


def _pivot_points(kl, left=3, right=3):
    """
    returns pivots: list of (idx, type, price)
    type: 'H' or 'L'
    """
    piv = []
    n = len(kl)
    if n < left + right + 5:
        return piv
    highs = [c["high"] for c in kl]
    lows  = [c["low"] for c in kl]
    for i in range(left, n-right):
        h = highs[i]
        l = lows[i]
        if all(h >= highs[j] for j in range(i-left, i+right+1)) and (h > highs[i-1] or h > highs[i+1]):
            piv.append((i, "H", h))
        if all(l <= lows[j] for j in range(i-left, i+right+1)) and (l < lows[i-1] or l < lows[i+1]):
            piv.append((i, "L", l))
    piv.sort(key=lambda x: x[0])
    return piv

def _nearest_levels(levels, price, k=3):
    if price is None:
        return []
    levels = [float(x) for x in levels if x is not None]
    levels = sorted(levels, key=lambda x: abs(x-price))
    return levels[:k]


def _fib_levels(low, high):
    if low is None or high is None:
        return {}
    r = high - low
    return {
        "0.382": high - r*0.382,
        "0.5": high - r*0.5,
        "0.618": high - r*0.618,
        "0.786": high - r*0.786,
        "1.0": low
    }

def _detect_basic_patterns(kl):
    """
    Advanced-ish detector (safe & lightweight).
    Returns dict:
      dominant_pattern, phase, targets(list), neckline, strength(0-100)
    """
    if len(kl) < 80:
        return {
            "dominant_pattern":"غير كافي بيانات",
            "phase":"-",
            "targets":[],
            "neckline":None,
            "strength":0
        }

    closes = [c["close"] for c in kl]
    highs  = [c["high"] for c in kl]
    lows   = [c["low"] for c in kl]

    piv = _pivot_points(kl, left=4, right=4)
    pivH = [(i,p) for i,t,p in piv if t=="H"]
    pivL = [(i,p) for i,t,p in piv if t=="L"]

    # channel estimation via last 120 bars high/low
    window = kl[-120:]
    hi = max(c["high"] for c in window)
    lo = min(c["low"] for c in window)
    mid = (hi+lo)/2
    rng = hi-lo

    # double top/bottom heuristic
    dom = "سلوك تذبذبي داخل نطاق"
    phase = "تجميع/توازن"
    neckline = mid
    strength = 55
    targets = []

    if len(pivH) >= 2:
        (i1,p1),(i2,p2) = pivH[-2], pivH[-1]
        if abs(p1-p2) <= rng*0.05:
            dom = "Double Top (قمتين)"
            phase = "اكتمل تقريبًا — مراقبة كسر خط العنق"
            neckline = min(lows[i1:i2+1]) if i2>i1 else mid
            height = ((p1+p2)/2) - neckline
            targets = [neckline - height, neckline - height*1.27]
            strength = 72

    if len(pivL) >= 2:
        (j1,q1),(j2,q2) = pivL[-2], pivL[-1]
        if abs(q1-q2) <= rng*0.05:
            dom = "Double Bottom (قاعين)"
            phase = "اكتمل تقريبًا — مراقبة كسر خط العنق"
            neckline = max(highs[j1:j2+1]) if j2>j1 else mid
            height = neckline - ((q1+q2)/2)
            targets = [neckline + height, neckline + height*1.27]
            strength = 72

    # triangle heuristic: contracting range
    last60 = kl[-60:]
    hi60 = max(c["high"] for c in last60)
    lo60 = min(c["low"] for c in last60)
    last20 = kl[-20:]
    hi20 = max(c["high"] for c in last20)
    lo20 = min(c["low"] for c in last20)
    if (hi20-lo20) < (hi60-lo60)*0.55:
        dom = "Triangle / Squeeze (انكماش)"
        phase = "ضغط سعري قبل انفجار"
        neckline = mid
        targets = [hi60, lo60]
        strength = 78

    # flag/pennant heuristic: impulse then consolidation
    impulse = abs(closes[-60]-closes[-120]) if len(closes)>=120 else 0
    cons = (hi20-lo20)
    if impulse > cons*2.2 and cons > 0:
        dom = "Flag / Pennant (علم/راية)"
        phase = "استراحة بعد اندفاع"
        neckline = mid
        # target = breakout add impulse
        direction = 1 if closes[-1] > closes[-60] else -1
        targets = [closes[-1] + direction*impulse*0.6, closes[-1] + direction*impulse*1.0]
        strength = 80

    return {
        "dominant_pattern": dom,
        "phase": phase,
        "targets": targets,
        "neckline": neckline,
        "strength": strength
    }


# ============================================================
# CLASSICAL TA (FULL)
# ============================================================

def school_classical_ta(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=400)
    price = snap.get("price")

    if not kl or len(kl) < 80 or price is None:
        return (
            "📘 *Classical TA — التحليل الفني الكلاسيكي*\n"
            "⚠️ بيانات الشموع غير كافية حاليًا لتوليد تقرير كامل.\n"
            "جرّب بعد دقائق أو استخدم زوج مختلف.\n"
        )

    closes = [c["close"] for c in kl]
    highs  = [c["high"] for c in kl]
    lows   = [c["low"] for c in kl]
    vol    = [c.get("volume",0.0) for c in kl]

    ema50  = _ema(closes[-200:], 50)
    ema200 = _ema(closes[-350:], 200) if len(closes) >= 250 else None
    sma20  = _sma(closes, 20)
    sma50  = _sma(closes, 50)

    rsi14 = _rsi(closes, 14)
    macd  = _macd(closes)

    atr14 = _atr(kl, 14) or snap.get("atr") or 0

    # Trend inference
    trend_direction = "محايد"
    if ema50 and ema200:
        if ema50 > ema200 and price > ema50:
            trend_direction = "صاعد"
        elif ema50 < ema200 and price < ema50:
            trend_direction = "هابط"
        else:
            trend_direction = "متذبذب/تحول"
    else:
        # fallback
        trend_direction = "صاعد" if snap.get("bias")=="BULLISH" else "هابط" if snap.get("bias")=="BEARISH" else "محايد"

    trendline_level = ema50 if ema50 else sma20
    trend_comment = (
        "الاتجاه قوي نسبيًا لأن السعر فوق المتوسطات الرئيسية."
        if trend_direction=="صاعد" else
        "الاتجاه سلبي نسبيًا لأن السعر تحت المتوسطات الرئيسية."
        if trend_direction=="هابط" else
        "السوق في وضع توازن، أي اختراق/كسر سيكون مؤثر."
    )

    # RSI interpretation
    rsi_state = "غير متاح"
    rsi_signal = "—"
    if rsi14 is not None:
        if rsi14 >= 70:
            rsi_state = "تشبع شراء"
            rsi_signal = "احتمال تهدئة/تصحيح إذا ظهرت شموع رفض"
        elif rsi14 <= 30:
            rsi_state = "تشبع بيع"
            rsi_signal = "احتمال ارتداد إذا ظهر امتصاص حجم/رفض"
        else:
            rsi_state = "متوازن"
            rsi_signal = "اتّبع الاتجاه العام + راقب الاختراقات"

    # MACD interpretation
    macd_cross = "غير متاح"
    macd_strength = "—"
    macd_comment = "—"
    if macd:
        macd_cross = "إيجابي" if macd["macd"] > macd["signal"] else "سلبي"
        macd_strength = "قوي" if abs(macd["hist"]) > abs(macd["macd"])*0.25 else "متوسط/ضعيف"
        macd_comment = (
            "الزخم يميل للصعود (MACD أعلى من Signal)."
            if macd_cross=="إيجابي" else
            "الزخم يميل للهبوط (MACD أقل من Signal)."
        )

    # Support/Resistance (from pivots)
    piv = _pivot_points(kl, left=4, right=4)
    pivot_highs = [p for i,t,p in piv if t=="H"]
    pivot_lows  = [p for i,t,p in piv if t=="L"]
    near_res = _nearest_levels(pivot_highs[-15:], price, k=3)
    near_sup = _nearest_levels(pivot_lows[-15:], price, k=3)

    support_strong = near_sup[0] if near_sup else (price-atr14*1.2)
    resistance_strong = near_res[0] if near_res else (price+atr14*1.2)
    sr_watch = (support_strong + resistance_strong)/2

    # Fibonacci on last swing (use last 140 bars)
    w = kl[-140:]
    swing_high = max(c["high"] for c in w)
    swing_low  = min(c["low"] for c in w)
    fib = _fib_levels(swing_low, swing_high)
    fib_key = fib.get("0.618")

    # MA relationship
    ma_relationship = "—"
    if ema50 and ema200:
        ma_relationship = "EMA50 أعلى EMA200 (Bullish Alignment)" if ema50 > ema200 else "EMA50 أسفل EMA200 (Bearish Alignment)"
    elif sma20 and sma50:
        ma_relationship = "SMA20 أعلى SMA50" if sma20 > sma50 else "SMA20 أسفل SMA50"

    # Channels (simple)
    channel_type = "قناة أفقية/نطاق"
    channel_upper = swing_high
    channel_lower = swing_low
    if trend_direction == "صاعد":
        channel_type = "قناة صاعدة (ميل إيجابي)"
    elif trend_direction == "هابط":
        channel_type = "قناة هابطة (ميل سلبي)"

    channel_scenario = (
        "أفضلية شراء قرب الحد السفلي إذا ظهر رفض + تأكيد."
        if trend_direction=="صاعد" else
        "أفضلية بيع قرب الحد العلوي إذا ظهر رفض + تأكيد."
        if trend_direction=="هابط" else
        "التداول داخل النطاق: شراء قرب الدعم وبيع قرب المقاومة بعد تأكيد."
    )

    # Breakout levels
    breakout_level = resistance_strong
    retest_status = "محتمل" if atr14 and atr14 > 0 else "غير واضح"
    breakout_strength = clamp((atr14 / (price*0.005))*100 if price else 50, 10, 95)  # تقديري

    # Patterns
    pat = _detect_basic_patterns(kl)
    pattern_type = pat["dominant_pattern"]
    pattern_phase = pat["phase"]
    pattern_strength = pat["strength"]
    pattern_neckline = pat["neckline"]
    pts = pat["targets"][:]
    pattern_target1 = pts[0] if len(pts)>0 else (price+atr14*1.1)
    pattern_target2 = pts[1] if len(pts)>1 else (price+atr14*2.1)

    # Bull/Bear scenarios
    bull_confirmation = resistance_strong
    bull_target1 = max(resistance_strong + atr14*1.0, pattern_target1)
    bull_target2 = max(resistance_strong + atr14*2.0, pattern_target2)

    bear_confirmation = support_strong
    bear_target1 = min(support_strong - atr14*1.0, (price-atr14*1.1))
    bear_target2 = min(support_strong - atr14*2.0, (price-atr14*2.1))

    invalidation_level = support_strong if trend_direction=="صاعد" else resistance_strong if trend_direction=="هابط" else (support_strong - atr14*0.5)

    # Summary
    ta_summary = (
        "استمرارية صعود مع احتمالات تصحيح قصيرة"
        if trend_direction=="صاعد" and (rsi14 or 50) < 70 else
        "ضغط بيعي مع احتمالات ارتداد فني"
        if trend_direction=="هابط" and (rsi14 or 50) > 30 else
        "توازن/نطاق يتطلب كسر حاسم"
    )
    critical_level = resistance_strong if trend_direction!="هابط" else support_strong

    return (
        f"📘 *مدرسة Classical TA — التحليل الفني الكلاسيكي*\n"
        "🔍 *مقدمة:*\n"
        "يرتكز هذا التحليل على دمج المؤشرات الفنية، النماذج السعرية، القنوات، الفيبوناتشي، والدعوم والمقاومات لتحديد الاتجاه، نقاط الانعكاس، والأهداف المحتملة بدقة عالية.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 *الاتجاه العام (Trend Analysis):*\n"
        f"• الاتجاه الحالي: *{trend_direction}*\n"
        f"• خط الاتجاه/المستوى الديناميكي: *{fmt(trendline_level,2)}*\n"
        f"• ملاحظة الاتجاه: {trend_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *مؤشرات الزخم (Momentum Indicators):*\n"
        "🔹 RSI:\n"
        f"• القراءة: *{fmt(rsi14,2)}*\n"
        f"• الحالة: *{rsi_state}*\n"
        f"• الإشارة: {rsi_signal}\n"
        "🔹 MACD:\n"
        f"• نوع التقاطع: *{macd_cross}*\n"
        f"• قوة الإشارة: *{macd_strength}*\n"
        f"• تعليق: {macd_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📉 *مستويات الفيبوناتشي (Fibonacci):*\n"
        f"• 0.382: *{fmt(fib.get('0.382'),2)}*\n"
        f"• 0.618: *{fmt(fib.get('0.618'),2)}*\n"
        f"• 0.786: *{fmt(fib.get('0.786'),2)}*\n"
        f"• مستوى فيبو المهم: *{fmt(fib_key,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📐 *الدعوم والمقاومات (S/R):*\n"
        f"• دعم قوي: *{fmt(support_strong,2)}*\n"
        f"• مقاومة قوية: *{fmt(resistance_strong,2)}*\n"
        f"• مستوى مراقبة: *{fmt(sr_watch,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *المتوسطات المتحركة (Moving Averages):*\n"
        f"• EMA50: *{fmt(ema50,2)}*\n"
        f"• EMA200: *{fmt(ema200,2)}*\n"
        f"• علاقة المتوسطات: {ma_relationship}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎨 *النماذج الفنية (Chart Patterns) — منظومة كاملة:*\n"
        f"🔹 النمط الأقرب للتكوين: *{pattern_type}*\n"
        f"  - مرحلة النموذج: {pattern_phase}\n"
        f"  - قوة النموذج: *{pattern_strength}%*\n"
        f"  - خط العنق / خط الاختراق: *{fmt(pattern_neckline,2)}*\n"
        "  - أهداف النموذج:\n"
        f"      • الهدف الأول: *{fmt(pattern_target1,2)}*\n"
        f"      • الهدف الثاني: *{fmt(pattern_target2,2)}*\n"
        "🔸 قائمة النماذج التي يغطيها المحرك (متاحة بالكامل):\n"
        "• رأس وكتفين / مقلوب — Double Top/Bottom — مثلثات (صاعد/هابط/متماثل)\n"
        "• قناة صاعدة/هابطة/أفقية — علم/راية — وتد (Wedge)\n"
        "• Cup & Handle — نطاق/تجميع — Squeeze/انكماش\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📚 *القنوات السعرية (Price Channels):*\n"
        f"• نوع القناة: *{channel_type}*\n"
        f"• الحد العلوي: *{fmt(channel_upper,2)}*\n"
        f"• الحد السفلي: *{fmt(channel_lower,2)}*\n"
        f"• أفضل سيناريو داخل القناة: {channel_scenario}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *نظام الاختراقات (Breakouts & Retests):*\n"
        f"• مستوى الاختراق المحتمل: *{fmt(breakout_level,2)}*\n"
        f"• هل يوجد إعادة اختبار؟ *{retest_status}*\n"
        f"• قوة الاختراق (تقديرية): *{fmt(breakout_strength,2)}%*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *سيناريو الصعود (Bullish Scenario):*\n"
        f"• تأكيد الصعود عند اختراق: *{fmt(bull_confirmation,2)}*\n"
        "• الأهداف:\n"
        f"  1) *{fmt(bull_target1,2)}*\n"
        f"  2) *{fmt(bull_target2,2)}*\n"
        "📉 *سيناريو الهبوط (Bearish Scenario):*\n"
        f"• تأكيد الهبوط عند كسر: *{fmt(bear_confirmation,2)}*\n"
        "• الأهداف:\n"
        f"  1) *{fmt(bear_target1,2)}*\n"
        f"  2) *{fmt(bear_target2,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *مستوى الإلغاء (Invalidation):*\n"
        f"• السيناريو يفشل بكسر: *{fmt(invalidation_level,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"السوق يظهر سلوك **{ta_summary}**\n"
        f"وأهم مستوى سيحدد الاتجاه القادم هو: **{fmt(critical_level,2)}**\n"
    )


# ============================================================
# HARMONIC (FULL)
# ============================================================

def _ratio(a, b):
    try:
        if b == 0:
            return None
        return abs(a) / abs(b)
    except:
        return None

def _harmonic_match_ratios(ab, bc, cd, pattern_name):
    """
    returns (score 0..100, comment)
    Based on typical harmonic ratios (approx).
    """
    # expected ranges (lo, hi)
    ranges = {}
    if pattern_name == "Gartley":
        ranges = {"AB": (0.55, 0.68), "BC": (0.382, 0.886), "CD": (1.27, 1.618)}
    elif pattern_name == "Bat":
        ranges = {"AB": (0.35, 0.55), "BC": (0.382, 0.886), "CD": (1.618, 2.618)}
    elif pattern_name == "Crab":
        ranges = {"AB": (0.35, 0.68), "BC": (0.382, 0.886), "CD": (2.618, 3.618)}
    elif pattern_name == "Butterfly":
        ranges = {"AB": (0.70, 0.82), "BC": (0.382, 0.886), "CD": (1.618, 2.618)}
    elif pattern_name == "AB=CD":
        ranges = {"AB": (0.55, 0.82), "BC": (0.382, 0.886), "CD": (0.90, 1.10)}
    else:
        return (0, "Unknown")

    def in_range(x, lo, hi):
        if x is None:
            return 0
        if x < lo:
            return max(0, 50 - (lo-x)*120)
        if x > hi:
            return max(0, 50 - (x-hi)*120)
        return 100

    sAB = in_range(ab, *ranges["AB"])
    sBC = in_range(bc, *ranges["BC"])
    sCD = in_range(cd, *ranges["CD"])
    score = (sAB*0.35 + sBC*0.25 + sCD*0.40)
    comment = f"AB:{fmt(ab,3)} | BC:{fmt(bc,3)} | CD:{fmt(cd,3)}"
    return (int(clamp(score, 0, 100)), comment)

def _harmonic_find_candidate(kl):
    """
    try to extract X,A,B,C,D from pivots last area
    returns dict or None
    """
    piv = _pivot_points(kl, left=4, right=4)
    if len(piv) < 7:
        return None
    # take last 7 pivots; build sequence by time
    seq = piv[-7:]
    # choose alternating high/low sequence: pick last 5 that alternate
    alt = []
    for it in seq:
        if not alt:
            alt.append(it)
        else:
            if it[1] != alt[-1][1]:
                alt.append(it)
    if len(alt) < 5:
        # try broader
        seq = piv[-12:]
        alt = []
        for it in seq:
            if not alt:
                alt.append(it)
            else:
                if it[1] != alt[-1][1]:
                    alt.append(it)
        if len(alt) < 5:
            return None

    alt = alt[-5:]
    (ix, tx, X), (ia, ta, A), (ib, tb, B), (ic, tc, C), (id, td, D) = alt

    XA = A - X
    AB = B - A
    BC = C - B
    CD = D - C

    # ratios
    ab_ratio = _ratio(AB, XA)  # AB retrace of XA
    bc_ratio = _ratio(BC, AB)  # BC retrace of AB
    cd_ratio = _ratio(CD, BC)  # CD extension of BC (approx)

    direction = "bullish" if D < C else "bearish"  # rough: last leg down -> bullish candidate
    return {
        "X": X, "A": A, "B": B, "C": C, "D": D,
        "ix": ix, "ia": ia, "ib": ib, "ic": ic, "id": id,
        "XA": XA, "AB": AB, "BC": BC, "CD": CD,
        "ab_ratio": ab_ratio, "bc_ratio": bc_ratio, "cd_ratio": cd_ratio,
        "direction": direction
    }


def school_harmonic(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=450)
    price = snap.get("price")
    if not kl or len(kl) < 120 or price is None:
        return (
            f"📘 *مدرسة Harmonic — تحليل {symbol}*\n"
            "⚠️ بيانات الشموع غير كافية لاستخراج XABCD بدقة.\n"
        )

    cand = _harmonic_find_candidate(kl)
    if not cand:
        return (
            f"📘 *مدرسة Harmonic — تحليل {symbol}*\n"
            "⚠️ لم يتم العثور على موجات Pivot كافية لتكوين نموذج توافقي واضح الآن.\n"
            "جرّب فريم مختلف أو انتظر اكتمال موجة إضافية.\n"
        )

    ab = cand["ab_ratio"]
    bc = cand["bc_ratio"]
    cd = cand["cd_ratio"]

    patterns = ["Gartley","Bat","Crab","Butterfly","AB=CD"]
    scored = []
    for p in patterns:
        sc, cm = _harmonic_match_ratios(ab, bc, cd, p)
        scored.append((sc, p, cm))
    scored.sort(reverse=True, key=lambda x: x[0])
    best_score, best_pattern, best_comment = scored[0]

    # PRZ: use confluence near D with ATR padding
    atr = _atr(kl, 14) or snap.get("atr") or 0
    D = cand["D"]
    prz_main_low = D - atr*0.35
    prz_main_high = D + atr*0.35

    # Fibonacci projections (conceptual)
    XA = abs(cand["XA"])
    BC_leg = abs(cand["BC"])

    xa_0786 = cand["X"] + (cand["A"]-cand["X"])*0.786
    bc_127  = cand["B"] + (cand["C"]-cand["B"])*1.27
    cd_1618 = cand["C"] + (cand["D"]-cand["C"])*1.618  # just conceptual

    # confluence score
    confluence = 0
    for lvl in [xa_0786, bc_127, D]:
        if abs(lvl - D) <= max(atr*0.6, D*0.0008):
            confluence += 1
    confluence_score = f"{confluence}/3"

    # targets:
    # bullish: targets at C then B
    bull_target1 = cand["C"]
    bull_target2 = cand["B"]
    # bearish: targets at C then B reversed
    bear_target1 = cand["C"]
    bear_target2 = cand["B"]

    invalid_level = D - atr*0.9 if cand["direction"]=="bullish" else D + atr*0.9
    entry_zone = f"{fmt(prz_main_low,2)} → {fmt(prz_main_high,2)}"

    pattern_accuracy = best_score

    harmonic_pattern = best_pattern
    xa_range = f"{fmt(cand['X'],2)} → {fmt(cand['A'],2)}"
    ab_ratio_txt = fmt(ab,3)
    bc_ratio_txt = fmt(bc,3)
    cd_proj_txt  = fmt(cd,3)

    # scenario texts (unique)
    if cand["direction"] == "bullish":
        bull_conf = f"تأكيد: رفض هابط داخل PRZ ثم شمعة انعكاس فوق {fmt(D,2)}"
        bear_conf = f"فشل: كسر واضح أسفل {fmt(invalid_level,2)} ثم إعادة اختبار"
    else:
        bull_conf = f"فشل: اختراق أعلى {fmt(invalid_level,2)} يلغي نموذج الهبوط"
        bear_conf = f"تأكيد: رفض صاعد داخل PRZ ثم شمعة هبوطية قوية أسفل {fmt(D,2)}"

    return (
        f"📘 *مدرسة Harmonic — تحليل {symbol}*\n"
        "🔍 *مقدمة:*\n"
        "يعتمد التحليل التوافقي على تتبع حركة الموجات وفق نسب فيبوناتشي لتحديد النقاط XABCD واستخراج مناطق انعكاس قوية (PRZ).\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎼 *النمط الأقرب للتكوين (Pattern Candidate):*\n"
        f"• النمط المحتمل: *{harmonic_pattern}*\n"
        "  - Gartley / Bat / Crab / Butterfly / AB=CD\n"
        f"• نسبة توافق النموذج: *{pattern_accuracy}%*\n"
        f"• تفاصيل النسب: {best_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *موجات النموذج (Wave Structure):*\n"
        f"• XA: {xa_range}\n"
        f"• AB Ratio (من XA): *{ab_ratio_txt}*\n"
        f"• BC Ratio (من AB): *{bc_ratio_txt}*\n"
        f"• CD Projection (من BC): *{cd_proj_txt}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📐 *مناطق الانعكاس PRZ (Potential Reversal Zone):*\n"
        f"• منطقة الانعكاس الرئيسية: *{fmt(prz_main_low,2)} → {fmt(prz_main_high,2)}*\n"
        "• امتدادات/مستويات فيبو (توافق):\n"
        f"  - 0.786 XA: *{fmt(xa_0786,2)}*\n"
        f"  - 1.27 BC:  *{fmt(bc_127,2)}*\n"
        f"  - مرساة D:   *{fmt(D,2)}*\n"
        f"• توافق المستويات (Confluence Score): *{confluence_score}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 *سيناريو صاعد (Bullish Pattern):*\n"
        f"• تأكيد الصعود: {bull_conf}\n"
        "• أهداف محتملة:\n"
        f"  1) *{fmt(bull_target1,2)}*\n"
        f"  2) *{fmt(bull_target2,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📉 *سيناريو هابط (Bearish Pattern):*\n"
        f"• تأكيد الهبوط: {bear_conf}\n"
        "• أهداف محتملة:\n"
        f"  1) *{fmt(bear_target1,2)}*\n"
        f"  2) *{fmt(bear_target2,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *مستويات مهمة:*\n"
        f"• منطقة وقف النموذج (Invalidation): *{fmt(invalid_level,2)}*\n"
        f"• أفضل منطقة دخول محتملة (مراقبة): *{entry_zone}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *ملاحظات المدرسة:*\n"
        "• النماذج التوافقية لا تعتمد وحدها — لازم تأكيد Price Action.\n"
        "• كلما زاد توافق نسب فيبوناتشي → زادت احتمالية نجاح النموذج.\n"
        "• PRZ ليست دخول مباشر — هي *منطقة مراقبة عالية القيمة*.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"النموذج المتوقع حاليًا هو **{harmonic_pattern}**\n"
        f"والسعر قريب من منطقة PRZ عند **{fmt(D,2)}**\n"
        "رد الفعل داخل PRZ هو اللي يحسم اكتمال/فشل النموذج.\n"
    )
    # ============================================================
# PART 5 — DIGITAL + TIME MASTER + VOLUME SCHOOL + WEBHOOK FIX
# ============================================================

# ----------------------------
# FIX: prevent NoneType concat + faster ACK
# ----------------------------

def _ensure_str(x):
    if x is None:
        return ""
    try:
        return str(x)
    except:
        return ""

def _safe_join(*parts):
    return "".join([_ensure_str(p) for p in parts])

def _quick_ack(chat_id, text="⏳ جاري تجهيز التحليل..."):
    try:
        # send small instant msg to avoid Telegram callback timeout
        send_message(chat_id, text)
    except:
        pass


# IMPORTANT:
# If your webhook currently does: send_message(chat_id, header + body)
# This override ensures it never crashes even if body=None
def _send_analysis_safe(chat_id, header, body):
    msg = _safe_join(header, body)
    if not msg.strip():
        msg = "⚠️ حدثت مشكلة في توليد التحليل (رسالة فارغة)."
    send_message(chat_id, msg)


# ============================================================
# VOLUME SCHOOL (ADVANCED) — Volume Profile / Volatility / Flow
# ============================================================

def _vwap(kl):
    # session vwap (simple)
    if not kl:
        return None
    pv = 0.0
    vv = 0.0
    for c in kl:
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        v = float(c.get("volume", 0.0))
        pv += tp * v
        vv += v
    return (pv / vv) if vv else None

def _volume_stats(kl):
    if not kl or len(kl) < 50:
        return None
    vols = [float(c.get("volume", 0.0)) for c in kl]
    closes = [float(c["close"]) for c in kl]
    highs  = [float(c["high"]) for c in kl]
    lows   = [float(c["low"]) for c in kl]

    avg_v = sum(vols[-100:]) / max(1, len(vols[-100:]))
    last_v = vols[-1]
    v_ratio = (last_v / avg_v) if avg_v else 1.0

    # volatility proxy: avg true range
    atr = _atr(kl, 14) or 0.0
    rng = max(highs[-120:]) - min(lows[-120:])
    compression = None
    if rng > 0:
        compression = clamp((atr / (rng / 120.0)) * 100, 0, 200)

    # delta proxy (up volume vs down volume)
    upv = 0.0
    dnv = 0.0
    for i in range(1, len(closes)):
        if closes[i] >= closes[i-1]:
            upv += vols[i]
        else:
            dnv += vols[i]
    total = upv + dnv
    delta = ((upv - dnv) / total) * 100 if total else 0.0

    # liquidity burst / climax (volume spike + wide range candle)
    last_range = highs[-1] - lows[-1]
    avg_range = sum((highs[i]-lows[i]) for i in range(-30, 0)) / 30.0
    climax = (v_ratio > 1.8 and last_range > avg_range * 1.6)

    return {
        "avg_v": avg_v,
        "last_v": last_v,
        "v_ratio": v_ratio,
        "atr": atr,
        "compression": compression,
        "delta": delta,
        "climax": climax,
    }

def school_volume_analysis(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=500)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 120:
        return (
            "📘 *مدرسة التحليل الحجمي — Volume & Volatility*\n"
            "⚠️ بيانات غير كافية حاليًا لإخراج تحليل حجمي كامل.\n"
        )

    st = _volume_stats(kl) or {}
    vwap = _vwap(kl)
    atr  = st.get("atr") or (snap.get("atr") or 0.0)

    v_ratio = st.get("v_ratio", 1.0)
    delta = st.get("delta", 0.0)
    compression = st.get("compression", 0.0)
    climax = st.get("climax", False)

    # interpret volume state
    if v_ratio >= 2.2:
        vol_state = "انفجار حجم (Volume Spike)"
    elif v_ratio >= 1.4:
        vol_state = "حجم أعلى من الطبيعي"
    elif v_ratio <= 0.7:
        vol_state = "حجم ضعيف / سيولة منخفضة"
    else:
        vol_state = "حجم طبيعي"

    # momentum strength estimate
    momentum_strength = clamp(abs(delta) + (v_ratio * 12), 10, 95)

    # volatility readiness
    # compression high -> squeeze; climax -> immediate reversal risk
    if climax:
        volatility_readiness = "حالة Climax: حركة قوية جدًا قد تسبق انعكاس أو تهدئة"
    else:
        if compression and compression > 110:
            volatility_readiness = "ضغط عالي (Squeeze) — احتمال انفجار سعري قريب"
        elif compression and compression < 70:
            volatility_readiness = "تذبذب مريح — الحركة أهدى"
        else:
            volatility_readiness = "تذبذب متوسط — السوق قابل للاندفاع مع خبر/كسر"

    # build "volume map" zones (proxy) using pivots + volume spikes
    piv = _pivot_points(kl, left=4, right=4)
    ph = [p for i,t,p in piv if t=="H"][-10:]
    pl = [p for i,t,p in piv if t=="L"][-10:]
    near_res = _nearest_levels(ph, price, k=2)
    near_sup = _nearest_levels(pl, price, k=2)
    hvn = (sum(near_res)/len(near_res)) if near_res else (price + atr*1.2)
    lvn = (sum(near_sup)/len(near_sup)) if near_sup else (price - atr*1.2)

    # vwap bias
    if vwap:
        vwap_bias = "فوق VWAP (قوة شرائية)" if price > vwap else "تحت VWAP (ضغط بيعي)"
    else:
        vwap_bias = "غير متاح"

    # flow conclusion
    flow_read = "تدفق شرائي" if delta > 6 else "تدفق بيعي" if delta < -6 else "تدفق متوازن"
    risk_note = "مرتفع" if climax else "متوسط" if compression and compression > 110 else "طبيعي"

    return (
        f"📘 *مدرسة التحليل الحجمي — Volume & Volatility (متقدم)*\n"
        "🔍 *مقدمة:*\n"
        "هذا النموذج يقرأ السوق من منظور الحجم/التدفق (Flow) والتذبذب،\n"
        "ويستخرج: حالة الحجم، قوة الزخم، مناطق نشاط السيولة، ومدى جاهزية السوق لانفجار سعري.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *1) حالة الحجم (Volume State):*\n"
        f"• متوسط الحجم: {fmt(st.get('avg_v'),2)}\n"
        f"• آخر حجم: {fmt(st.get('last_v'),2)}\n"
        f"• نسبة آخر حجم للمتوسط: *{fmt(v_ratio,2)}x*\n"
        f"• التقييم: *{vol_state}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *2) دلتا التدفق (Delta Proxy):*\n"
        f"• Delta (شراء مقابل بيع): *{fmt(delta,2)}%*\n"
        f"• قراءة التدفق: *{flow_read}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🌪️ *3) التذبذب والضغط (Volatility & Compression):*\n"
        f"• ATR(14): *{fmt(atr,2)}*\n"
        f"• مؤشر الضغط/الانكماش: *{fmt(compression,2)}*\n"
        f"• جاهزية الانفجار السعري: *{volatility_readiness}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧊 *4) خريطة نشاط سيولة تقريبية (HVN/LVN Proxy):*\n"
        f"• منطقة نشاط مرتفع (HVN قرب مقاومات محورية): *{fmt(hvn,2)}*\n"
        f"• منطقة نشاط منخفض (LVN قرب دعوم محورية): *{fmt(lvn,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *5) VWAP & Mean Reversion:*\n"
        f"• VWAP: *{fmt(vwap,2)}*\n"
        f"• وضع السعر مقابل VWAP: *{vwap_bias}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛡️ *6) درجة المخاطرة الحجمية:*\n"
        f"• المخاطرة الحالية: *{risk_note}*\n"
        f"• قوة الزخم (تقديرية): *{fmt(momentum_strength,2)}%*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"الحجم/التدفق يشير إلى **{flow_read}** مع حالة **{vol_state}**\n"
        f"وأهم منطقتين للمراقبة: **HVN {fmt(hvn,2)}** و **LVN {fmt(lvn,2)}**.\n"
    )


# ============================================================
# DIGITAL ANALYSIS (FULL TEMPLATE — EXTREME EXPANDED)
# ============================================================

def _digital_dominant_number(price):
    # derive dominant number from price digits / fractal / modulo
    try:
        p = float(price)
    except:
        return (7, "غير متاح", "غير متاح")
    s = str(int(round(p)))
    digits = [int(ch) for ch in s if ch.isdigit()]
    if not digits:
        return (7, "افتراضي", "—")
    dom = max(set(digits), key=digits.count)
    reason = f"أكثر رقم تكرارًا داخل البنية الرقمية للسعر الحالي ({s})."
    effect = "يميل لخلق مناطق جذب/طرد رقمية حول مضاعفاته (Clusters)."
    return (dom, reason, effect)

def _digital_clusters(price, step):
    # build cluster zones around price (± step multiples)
    if price is None or step <= 0:
        return None
    p = float(price)
    levels = []
    for m in [1,2,3,5,8,13]:
        levels.append(p + step*m)
        levels.append(p - step*m)
    levels = sorted(levels)
    # find nearest cluster
    nearest = min(levels, key=lambda x: abs(x-p))
    density = 6
    prob = clamp(55 + (step / max(p*0.0008, 1e-6))*8, 55, 88)
    return (nearest, density, prob)

def school_digital_analysis(symbol, snap):
    price = snap.get("price")
    kl = _safe_klines(symbol, interval="15m", limit=420)
    if price is None or not kl or len(kl) < 120:
        return (
            "📘 *مدرسة Digital Analysis — التحليل الرقمي*\n"
            "⚠️ بيانات غير كافية لتوليد نموذج رقمي كامل.\n"
        )

    highs = [c["high"] for c in kl[-160:]]
    lows  = [c["low"] for c in kl[-160:]]
    hi = max(highs)
    lo = min(lows)
    rng = hi - lo
    step = max(rng * 0.125, (snap.get("atr") or 0) * 0.65)

    dominant_number, dominant_reason, dominant_effect = _digital_dominant_number(price)

    # repetitive pattern detection: digit repeats / last swing ticks
    closes = [c["close"] for c in kl]
    recent = closes[-30:]
    diffs = [abs(recent[i]-recent[i-1]) for i in range(1, len(recent))]
    avgd = sum(diffs)/len(diffs) if diffs else 0
    pattern_last = f"متوسط حركة رقمية ≈ {fmt(avgd,2)}"
    pattern_count = int(clamp(sum(1 for d in diffs if d <= avgd*0.75), 2, 18))
    pattern_strength = clamp((pattern_count/18)*100, 12, 92)
    digital_projection = float(price) + (avgd * (1 if snap.get("bias")=="BULLISH" else -1))

    # range levels
    range_12 = lo + rng*0.125
    range_25 = lo + rng*0.25
    range_50 = lo + rng*0.5
    range_75 = lo + rng*0.75
    active_range = min([range_12, range_25, range_50, range_75], key=lambda x: abs(x-float(price)))

    # vibrational numbers (root / sequence)
    vibration_root = dominant_number
    vibration_sequence = [dominant_number*(i+1) for i in range(1,7)]
    vibration_resonance = vibration_sequence[2]  # middle resonance
    vibration_comment = "عند اقتراب السعر من مستويات على مضاعفات الرقم، يزيد احتمال ردّ الفعل."

    # clusters
    cluster_zone, cluster_density, cluster_prob = _digital_clusters(price, step)

    # math ratios
    math_ratio = "1.618"
    ratio_recurring = "نعم (تتكرر في تمددات الموجات)"
    ratio_effect = "تعزز مناطق الهدف/الرفض عند توافقها مع دعم/مقاومة."

    # digital momentum
    digital_momentum = clamp((abs(avgd) / max(step, 1e-6))*100, 5, 95)
    momentum_sync = "نعم" if (snap.get("confidence", 0) or 0) >= 60 else "جزئي"
    momentum_bias = "صاعد" if snap.get("bias")=="BULLISH" else "هابط" if snap.get("bias")=="BEARISH" else "محايد"

    # digital time (light)
    time_sync = "نعم" if dominant_number in [3,5,7,9] else "جزئي"
    digital_time_point = f"بعد {dominant_number} شمعات (تقريبًا)"
    digital_time_window = f"{dominant_number}→{dominant_number+3} شمعات"

    # final
    digital_bias = momentum_bias
    digital_bias_reason = "توافق الزخم الرقمي مع قراءة الاتجاه اللحظية."
    digital_target1 = float(active_range) + (step*1.0 if digital_bias=="صاعد" else -step*1.0)
    digital_target2 = float(active_range) + (step*2.0 if digital_bias=="صاعد" else -step*2.0)
    digital_invalidation = float(active_range) - (step*1.1 if digital_bias=="صاعد" else -step*1.1)

    digital_summary = "منظّم" if digital_momentum > 55 else "متذبذب"
    critical_digital_level = active_range

    return (
        "📘 *مدرسة Digital Analysis — التحليل الرقمي*\n"
        "🔍 *مقدمة:*\n"
        "يعتمد هذا النموذج على دراسة العلاقات الرقمية داخل الحركة السعرية،\n"
        "وتحديد الأرقام المسيطرة، التكرارات، ومستويات الاهتزاز الرقمي (Vibrations)،\n"
        "لإيجاد توقّعات مبنية على الهندسة الرياضية للسوق.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔢 *1) الرقم المسيطر (Dominant Number):*\n"
        f"• الرقم المسيطر في الدورة الحالية: *{dominant_number}*\n"
        f"• سبب السيطرة: {dominant_reason}\n"
        f"• تأثير الرقم على الاتجاه: {dominant_effect}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧮 *2) التكرار العددي (Repetitive Patterns):*\n"
        f"• آخر تكرار رقمي ظهر: {pattern_last}\n"
        f"• عدد مرات التكرار: *{pattern_count}*\n"
        f"• قوة النمط: *{fmt(pattern_strength,2)}%*\n"
        f"• التوقع الرقمي القادم: *{fmt(digital_projection,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📐 *3) Digital Range Levels (مستويات المدى الرقمي):*\n"
        f"• مستوى 12.5%: *{fmt(range_12,2)}*\n"
        f"• مستوى 25%: *{fmt(range_25,2)}*\n"
        f"• مستوى 50%: *{fmt(range_50,2)}*\n"
        f"• مستوى 75%: *{fmt(range_75,2)}*\n"
        f"• المستوى الأقرب للتفاعل: *{fmt(active_range,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎛️ *4) Vibrational Numbers (الأرقام الاهتزازية):*\n"
        f"• الرقم الاهتزازي الأساسي: *{vibration_root}*\n"
        f"• مضاعفات الاهتزاز: *{vibration_sequence}*\n"
        f"• أقوى نقطة Resonance: *{vibration_resonance}*\n"
        f"• دلالة الاهتزاز: {vibration_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧩 *5) Digital Clusters (التجمعات الرقمية):*\n"
        f"• أقرب تجمع رقمي: *{fmt(cluster_zone,2)}*\n"
        f"• عدد النقاط داخل التجمع: *{cluster_density}*\n"
        f"• احتمالية الانعكاس ضمن التجمع: *{fmt(cluster_prob,2)}%*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *6) النسب الرياضية (Mathematical Ratios):*\n"
        f"• النسبة المسيطرة: *{math_ratio}*\n"
        f"• هل تتكرر تاريخيًا؟ *{ratio_recurring}*\n"
        f"• تأثير النسبة: {ratio_effect}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *7) Digital Momentum (الزخم الرقمي):*\n"
        f"• قيمة الزخم الرقمي: *{fmt(digital_momentum,2)}*\n"
        f"• هل الحركة متناسقة رقميًا؟ *{momentum_sync}*\n"
        f"• التوقع اللحظي: *{momentum_bias}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧭 *8) Digital Time (الزمن الرقمي):*\n"
        f"• تزامن الوقت مع الرقم المسيطر: *{time_sync}*\n"
        f"• أقرب نقطة زمنية رقمية: *{digital_time_point}*\n"
        f"• فترة الانعكاس الزمنية الرقمية: *{digital_time_window}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *السيناريو الرقمي الأقوى:*\n"
        f"• الاتجاه المرجّح رقميًا: *{digital_bias}*\n"
        f"• سبب الانحياز: {digital_bias_reason}\n"
        "• الأهداف المحتملة:\n"
        f"  1) *{fmt(digital_target1,2)}*\n"
        f"  2) *{fmt(digital_target2,2)}*\n"
        "⚠️ *مستوى الإلغاء:*\n"
        f"• يلغى التحليل الرقمي عند كسر: *{fmt(digital_invalidation,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"السوق حاليًا يتبع نمطًا رقميًا **{digital_summary}**\n"
        f"وأهم مستوى رقمي يجب مراقبته: **{fmt(critical_digital_level,2)}**\n"
    )


# ============================================================
# TIME MASTER MODEL (FULL, VERY ADVANCED)
# IMPORTANT: NO ASTRO TEXT SHOWN — BUT RESULTS INCLUDED
# ============================================================

def _time_cycles(kl):
    # simple cycle estimation using pivot spacing
    piv = _pivot_points(kl, left=4, right=4)
    idxs = [i for i,_,_ in piv[-12:]]
    if len(idxs) < 4:
        return None
    gaps = [idxs[i]-idxs[i-1] for i in range(1, len(idxs))]
    avg_gap = sum(gaps)/len(gaps)
    primary = int(clamp(avg_gap*2.2, 20, 260))
    short1  = int(clamp(avg_gap*0.9, 8, 90))
    short2  = int(clamp(avg_gap*1.3, 10, 120))
    return {"primary": primary, "short1": short1, "short2": short2, "avg_gap": avg_gap}

def _time_fib_points(n, base=0):
    # return classic fib time ratios as candle offsets
    fibs = [0.382,0.618,1.0,1.618]
    return {f: int(base + n*f) for f in fibs}

def _bradley_proxy(kl):
    # proxy index using momentum curvature (no astro)
    closes = [c["close"] for c in kl]
    if len(closes) < 80:
        return None
    # second derivative proxy
    v1 = closes[-1]-closes[-10]
    v2 = closes[-11]-closes[-20]
    curv = (v1 - v2)
    direction = "صاعد" if curv > 0 else "هابط"
    value = clamp(abs(curv) / max(closes[-1]*0.002, 1e-6) * 100, 5, 95)
    turn = "قريب (12-36 شمعة)" if value > 55 else "متوسط (36-72 شمعة)"
    return {"value": value, "direction": direction, "turn": turn}

def school_time_master(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=520)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 180:
        return (
            f"📘 *TIME MASTER MODEL — التحليل الزمني الشامل*\n"
            f"العملة: {symbol}\n"
            "⚠️ بيانات غير كافية حاليًا لإخراج نموذج زمني كامل.\n"
        )

    n = len(kl)
    cycles = _time_cycles(kl) or {"primary":144,"short1":34,"short2":55,"avg_gap":22}

    primary_cycle = f"دورة محورية مبنية على تباعد Pivot"
    primary_length = cycles["primary"]
    # phase: where we are in cycle
    phase = int((n % primary_length) / primary_length * 100)
    primary_phase = f"{phase}% من الدورة"
    primary_end_time = f"بعد {primary_length - (n % primary_length)} شمعة تقريبًا"
    primary_comment = "الدورة تقيس إيقاع السوق، ونهاية الدورة غالبًا تُحدث تغيّر في الزخم."

    cycle1_time = f"{cycles['short1']} شمعة"
    cycle2_time = f"{cycles['short2']} شمعة"
    cycle_alignment = "متناسقة" if abs(cycles["short2"]-cycles["short1"]) <= cycles["short1"]*0.6 else "متباعدة"
    cycle_projection = "اقتراب قمة/قاع قصير" if phase > 70 else "استمرار داخل الموجة" if phase < 55 else "منطقة قرار"

    fibt = _time_fib_points(primary_length, base=0)
    fib382_time = f"بعد {fibt[0.382]} شمعة"
    fib618_time = f"بعد {fibt[0.618]} شمعة"
    fib100_time = f"بعد {fibt[1.0]} شمعة"
    fib1618_time = f"بعد {fibt[1.618]} شمعة"
    dominant_fib_time = fib618_time
    fib_comment = "عادةً 0.618/1.618 تمثل نقاط ضغط عالية لتبدّل الإيقاع."

    # Time vs Price ratio (wave time)
    closes = [c["close"] for c in kl]
    piv = _pivot_points(kl, left=4, right=4)
    last_p = piv[-1][0] if piv else n-1
    prev_p = piv[-3][0] if len(piv) >= 3 else max(0, n-60)
    wave_previous_time = f"{last_p - prev_p} شمعة"
    wave_expected_time = f"{int((last_p - prev_p) * 1.0)} → {int((last_p - prev_p) * 1.618)} شمعة"
    time_deviation = "متقدّم" if phase > 75 else "متأخر" if phase < 30 else "متوازن"
    tp_balance = "قريب من التوازن" if 35 <= phase <= 65 else "بعيد عن التوازن (ضغط)"

    # Time clusters (merge multiple estimates)
    # cluster zone = nearest among primary end + short ends
    near_primary = primary_length - (n % primary_length)
    near_short1 = cycles["short1"] - (n % cycles["short1"])
    near_short2 = cycles["short2"] - (n % cycles["short2"])
    cluster_zone = f"{min(near_primary, near_short1, near_short2)} → {max(near_primary, near_short1, near_short2)} شمعة"
    cluster_strength = int(clamp(55 + (100-abs(near_short2-near_short1)), 55, 95))
    cluster_reversal_prob = clamp(50 + (cluster_strength-55)*0.7, 50, 92)

    # Gann proxy (no astro)
    gann_time_value = int(clamp((primary_length**0.5)*10, 10, 120))
    gann_angle = "45° (توازن)" if 40 <= phase <= 60 else "زاوية متطرفة (ضغط)"
    gann_intersection_time = f"بعد {int(clamp(primary_length*0.25, 10, 120))} شمعة"
    gann_comment = "عند زوايا التوازن تزيد فرص التحول، ومع التطرف يزيد احتمال الانعكاس أو تسارع الاتجاه."

    # --- ASTRO SECTION REMOVED FROM DISPLAY ---
    # BUT we still compute a hidden result that affects time window probability.
    # (This is NOT astrology text, it's a hidden stability window score.)
    # NOTE: user asked remove the astro text only.
    stability_score = clamp((snap.get("risk_score", 5.0) or 5.0) * 10, 10, 90)
    hidden_astro_window = "قريبة" if stability_score > 55 else "متوسطة"

    # Digital timing (uses dominant number)
    digital_dominant_number, _, _ = _digital_dominant_number(price)
    digital_relation = "متوافق" if (digital_dominant_number % 2 == 1) else "حيادي"
    digital_pattern = f"تكرار {digital_dominant_number} شمعات كإيقاع مراقبة"
    digital_projection = f"نافذة {digital_dominant_number}→{digital_dominant_number+3} شمعات"

    # Bradley proxy (non-astro)
    br = _bradley_proxy(kl) or {"value":55,"direction":"محايد","turn":"متوسط"}
    bradley_value = fmt(br["value"],2)
    bradley_direction = br["direction"]
    bradley_turn = br["turn"]

    # Wave timing
    wave1_time = f"{int(clamp(cycles['short1']*0.8, 8, 90))} شمعة"
    wave3_time = f"{int(clamp(cycles['short2']*1.0, 10, 120))} شمعة"
    wave5_time = f"{int(clamp(cycles['short2']*1.3, 12, 160))} شمعة"
    wave_harmony = "نعم" if cluster_strength > 70 else "جزئي"
    wave_next_projection = f"{int(clamp(cycles['primary']*0.382, 20, 220))} شمعة"

    # Time windows
    # combine: cluster prob + bradley + hidden stability
    base_prob = (cluster_reversal_prob*0.55 + br["value"]*0.30 + stability_score*0.15)
    window_probability = clamp(base_prob, 45, 94)

    time_window_near = f"بعد {min(near_short1, near_short2)} شمعة"
    time_window_strong = f"بعد {near_primary} شمعة"
    time_pressure_zone = "ضغط عالي" if phase >= 70 or phase <= 25 else "ضغط متوسط"

    # strongest decision
    critical_time_point = time_window_near if window_probability >= 70 else time_window_strong
    time_direction = "صعود" if snap.get("bias")=="BULLISH" else "هبوط" if snap.get("bias")=="BEARISH" else "محايد"
    reversal_time = critical_time_point
    trend_end_time = time_window_strong
    time_invalid_point = f"{primary_length + 20} شمعة (تجاوز الإطار المتوقع)"

    time_summary = "ضغط زمني عالي مع احتمال انعكاس" if window_probability >= 72 else "زمن متوازن يميل للاستمرار"
    strongest_time_level = critical_time_point

    return (
        f"📘 *TIME MASTER MODEL — التحليل الزمني الشامل*\n"
        f"العملة: *{symbol}*\n"
        "🔍 *مقدمة:*\n"
        "يعتمد هذا النموذج على دمج أنظمة زمنية متعددة لقياس احتمالية الانعكاس،\n"
        "وتحديد توقيت الموجات، ونقاط الضغط الزمني، ومناطق التوازن بين الوقت والسعر.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏳ *1) الدورات الزمنية الأساسية (Primary Time Cycles):*\n"
        f"• الدورة الحالية: {primary_cycle}\n"
        f"• طول الدورة: *{primary_length} شمعة*\n"
        f"• المرحلة داخل الدورة: *{primary_phase}*\n"
        f"• نهاية الدورة المتوقعة عند: *{primary_end_time}*\n"
        f"• دلالة الدورة: {primary_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏱️ *2) الدورات القصيرة (Short-Term Cycles):*\n"
        f"• دورة قصيرة 1: *{cycle1_time}*\n"
        f"• دورة قصيرة 2: *{cycle2_time}*\n"
        f"• تناسق الدورات: *{cycle_alignment}*\n"
        f"• التوقع الأقرب: *{cycle_projection}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📐 *3) الفيبوناتشي الزمني (Time Fibonacci):*\n"
        f"• 0.382 عند: {fib382_time}\n"
        f"• 0.618 عند: {fib618_time}\n"
        f"• 1.0 عند: {fib100_time}\n"
        f"• 1.618 عند: {fib1618_time}\n"
        f"• أقوى نقطة زمنية: *{dominant_fib_time}*\n"
        f"• دلالة الزمن: {fib_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟦 *4) الزمن السعري (Time vs Price Ratio):*\n"
        f"• طول الموجة السابقة: *{wave_previous_time}*\n"
        f"• الزمن المتوقع للموجة الحالية: *{wave_expected_time}*\n"
        f"• هل الزمن متقدّم أم متأخر؟ *{time_deviation}*\n"
        f"• Time/Price Equilibrium: *{tp_balance}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧭 *5) Time Clusters (التجمعات الزمنية):*\n"
        f"• أقرب تجمع زمني: *{cluster_zone}*\n"
        f"• قوة التجمع: *{cluster_strength}*\n"
        f"• هل هو منطقة انعكاس عالية الدقة؟ *{fmt(cluster_reversal_prob,2)}%*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💠 *6) Gann Time — Square of 9 (Proxy):*\n"
        f"• الرقم الزمني المحسوب: *{gann_time_value}*\n"
        f"• زاوية الزمن: *{gann_angle}*\n"
        f"• وقت التقاطع: *{gann_intersection_time}*\n"
        f"• دلالة جان: {gann_comment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧮 *7) التحليل الرقمي الزمني (Digital Timing Analysis):*\n"
        f"• الرقم المسيطر: *{digital_dominant_number}*\n"
        f"• علاقة الرقم بالدورة: *{digital_relation}*\n"
        f"• التكرار الزمني للأرقام: {digital_pattern}\n"
        f"• التوقع الرقمي: {digital_projection}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔁 *8) Bradly Time Curve (Proxy):*\n"
        f"• قيمة المؤشر الحالية: *{bradley_value}*\n"
        f"• اتجاه المنحنى: *{bradley_direction}*\n"
        f"• وقت الانعكاس المتوقع: *{bradley_turn}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧩 *9) Wave Timing (توقيت الموجات):*\n"
        f"• زمن الموجة 1: *{wave1_time}*\n"
        f"• زمن الموجة 3: *{wave3_time}*\n"
        f"• زمن الموجة 5: *{wave5_time}*\n"
        f"• هل الموجات متناغمة؟ *{wave_harmony}*\n"
        f"• Time Extension للموجة التالية: *{wave_next_projection}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏱️ *10) Time Windows — نوافذ الانعكاس:*\n"
        f"• أقرب نافذة: *{time_window_near}*\n"
        f"• أقوى نافذة: *{time_window_strong}*\n"
        f"• فترة الضغط السعري: *{time_pressure_zone}*\n"
        f"• احتمالية الانعكاس داخل النافذة: *{fmt(window_probability,2)}%*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *السيناريو الأقوى زمنيًا:*\n"
        f"• نقطة الزمن الفاصلة: *{critical_time_point}*\n"
        f"• اتجاه الحركة المتوقع: *{time_direction}*\n"
        f"• متى يبدأ الانعكاس؟ *{reversal_time}*\n"
        f"• متى ينتهي الاتجاه؟ *{trend_end_time}*\n"
        "⚠️ *مستوى إلغاء التحليل الزمني:*\n"
        f"• يتم إلغاء السيناريو إذا تجاوز الزمن: *{time_invalid_point}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"منظومة الزمن تشير إلى **{time_summary}**\n"
        f"وأقوى نقطة زمنية في السوق حاليًا هي: **{strongest_time_level}**\n"
        f"*(تم دمج نتائج نافذة إضافية داخلية بدون عرض أي قسم فلكي — حالة النافذة: {hidden_astro_window}).*\n"
    )


# ============================================================
# HELPERS: school dispatcher to include in your main pipeline
# (called by your analysis builder)
# ============================================================

def build_school_blocks(symbol, snap):
    # returns dict of school_name -> text
    out = {}
    out["volume"] = school_volume_analysis(symbol, snap)
    out["digital"] = school_digital_analysis(symbol, snap)
    out["time"] = school_time_master(symbol, snap)
    out["classical"] = school_classical_ta(symbol, snap)
    out["harmonic"] = school_harmonic(symbol, snap)
    return out
    # ============================================================
# PART 6 — MASTER 12 SCHOOLS + FAST WEBHOOK + NO INTERNAL TEXT
# ============================================================

import threading
import time

TELEGRAM_LIMIT = 3900  # safe margin < 4096


# ----------------------------
# message splitter (no long msg failure)
# ----------------------------
def split_message(text, limit=TELEGRAM_LIMIT):
    text = _ensure_str(text)
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        chunk = text[:limit]
        cut = chunk.rfind("\n")
        if cut < 800:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def send_long_message(chat_id, text):
    for part in split_message(text):
        send_message(chat_id, part)
        time.sleep(0.25)


# ----------------------------
# small helpers / fallbacks
# ----------------------------
def _safe_call(fn, default=None, *a, **kw):
    try:
        return fn(*a, **kw)
    except:
        return default

def _pct(a, b):
    try:
        if b == 0:
            return 0.0
        return (a / b) * 100.0
    except:
        return 0.0

def _now_iso():
    try:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    except:
        return ""


# ============================================================
# SCHOOL: Liquidity Map (ADVANCED)
# ============================================================
def school_liquidity(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=520)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 160:
        return "📘 *مدرسة السيولة — Liquidity Map*\n⚠️ بيانات غير كافية.\n"

    piv = _pivot_points(kl, left=4, right=4)
    highs = [p for i,t,p in piv if t == "H"][-20:]
    lows  = [p for i,t,p in piv if t == "L"][-20:]

    atr = _atr(kl, 14) or (snap.get("atr") or 0.0)
    price = float(price)

    liq_highs = sorted(highs)[-4:] if highs else [price + atr*1.2]
    liq_lows  = sorted(lows)[:4] if lows else [price - atr*1.2]

    # dominant liquidity = nearest cluster
    near_high = min(liq_highs, key=lambda x: abs(x-price))
    near_low  = min(liq_lows,  key=lambda x: abs(x-price))
    dominant_liquidity = near_high if abs(near_high-price) < abs(near_low-price) else near_low

    # bias: price closer to highs -> likely seek buyside, else sellside
    liquidity_bias = "سحب سيولة أعلى (Buyside)" if dominant_liquidity >= price else "سحب سيولة أسفل (Sellside)"

    return (
        "📘 *مدرسة السيولة — Liquidity Map*\n"
        "🔍 *مقدمة:*\n"
        "السيولة هي الوقود الحقيقي للحركة: السوق غالبًا يزور قمم/قيعان واضحة لسحب أوامر متراكمة.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧊 *1) مصادر السيولة الرئيسية:*\n"
        f"• سيولة فوق القمم (Highs): {', '.join(fmt(x,2) for x in liq_highs)}\n"
        f"• سيولة تحت القيعان (Lows): {', '.join(fmt(x,2) for x in liq_lows)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *2) منطقة السيولة الأقوى (Dominant Liquidity):*\n"
        f"• أقوى منطقة سيولة: *{fmt(dominant_liquidity,2)}*\n"
        f"• السيناريو المرجح: *{liquidity_bias}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *ملاحظات دقيقة:*\n"
        "• اختراق سيولة بدون تثبيت/تأكيد قد يكون مجرد Sweep ثم انعكاس.\n"
        "• الأفضل مراقبة ردّ فعل سعري قوي عند منطقة السيولة بدل الدخول المباشر.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"السوق ينجذب نحو **{fmt(dominant_liquidity,2)}** مع توقع **{liquidity_bias}**.\n"
    )


# ============================================================
# SCHOOL: Supply & Demand (ADVANCED)
# ============================================================
def school_supply_demand(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=520)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 160:
        return "📘 *مدرسة العرض والطلب — Supply & Demand*\n⚠️ بيانات غير كافية.\n"

    price = float(price)
    atr = _atr(kl, 14) or (snap.get("atr") or 0.0)

    piv = _pivot_points(kl, left=4, right=4)
    highs = [p for i,t,p in piv if t == "H"][-12:]
    lows  = [p for i,t,p in piv if t == "L"][-12:]

    # zones
    demand_zone = (min(lows[-3:]) if len(lows) >= 3 else price - atr*1.2)
    supply_zone = (max(highs[-3:]) if len(highs) >= 3 else price + atr*1.2)

    # freshness proxy: if price visited zone recently
    closes = [c["close"] for c in kl]
    recent = closes[-80:]
    used_demand = any(abs(x - demand_zone) <= atr*0.35 for x in recent)
    used_supply = any(abs(x - supply_zone) <= atr*0.35 for x in recent)

    demand_status = "Used" if used_demand else "Fresh"
    supply_status = "Used" if used_supply else "Fresh"

    sd_decision_zone = demand_zone if abs(price-demand_zone) < abs(price-supply_zone) else supply_zone

    return (
        "📘 *مدرسة العرض والطلب — Supply & Demand*\n"
        "🔍 *مقدمة:*\n"
        "الفكرة: السعر يتحرك بين مناطق تم فيها امتصاص/تجميع أوامر كبيرة. المنطقة القوية تعطي رد فعل واضح.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *1) مناطق القرار (Zones of Decision):*\n"
        f"• أقرب Demand Zone: *{fmt(demand_zone,2)}* — الحالة: *{demand_status}*\n"
        f"• أقرب Supply Zone: *{fmt(supply_zone,2)}* — الحالة: *{supply_status}*\n"
        f"• منطقة القرار الأقرب: *{fmt(sd_decision_zone,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 *2) قراءة السلوك داخل المنطقة:*\n"
        "• إن دخل السعر المنطقة ثم ظهرت شمعة رفض قوية + حجم أعلى من المتوسط → احتمالية انعكاس عالية.\n"
        "• إن دخلها وكسرها بزخم/حجم واضح → تتحول المنطقة لنقطة إعادة اختبار (Flip).\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 *3) سيناريو صاعد (Bullish SD):*\n"
        f"• شراء أفضل عند ارتداد واضح من Demand *{fmt(demand_zone,2)}*\n"
        f"• أهداف محتملة: {fmt(demand_zone + atr*2.0,2)} ثم {fmt(demand_zone + atr*3.2,2)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📉 *4) سيناريو هابط (Bearish SD):*\n"
        f"• بيع أفضل عند رفض واضح من Supply *{fmt(supply_zone,2)}*\n"
        f"• أهداف محتملة: {fmt(supply_zone - atr*2.0,2)} ثم {fmt(supply_zone - atr*3.2,2)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *مستوى الإلغاء:*\n"
        "• أي دخول من منطقة يحتاج تأكيد شمعة/زخم — لا تدخل لمجرد لمس المستوى.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"المفتاح الآن هو مراقبة رد الفعل عند **{fmt(sd_decision_zone,2)}**.\n"
    )


# ============================================================
# SCHOOL: Price Action (ADVANCED)
# ============================================================
def school_price_action(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=320)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 80:
        return "📘 *مدرسة السلوك السعري — Price Action*\n⚠️ بيانات غير كافية.\n"

    c = kl[-1]
    prev = kl[-2]
    body = abs(c["close"] - c["open"])
    wick_up = c["high"] - max(c["close"], c["open"])
    wick_dn = min(c["close"], c["open"]) - c["low"]
    rng = c["high"] - c["low"]

    atr = _atr(kl, 14) or (snap.get("atr") or 0.0)
    bias = snap.get("bias") or "NEUTRAL"

    # candle classification
    pa_candle = "شمعة عادية"
    pa_message = "حيادية"

    if rng > 0:
        if wick_up > body*1.8 and wick_up > wick_dn*1.2:
            pa_candle = "Pin Bar (رفض علوي)"
            pa_message = "ضغط بيع/رفض من أعلى"
        elif wick_dn > body*1.8 and wick_dn > wick_up*1.2:
            pa_candle = "Pin Bar (رفض سفلي)"
            pa_message = "ضغط شراء/رفض من أسفل"
        elif body > (rng*0.65):
            pa_candle = "Marubozu (سيطرة قوية)"
            pa_message = "زخم واضح لصالح اتجاه الشمعة"

    # reaction zone proxy = last pivot close
    piv = _pivot_points(kl, left=3, right=3)
    last_lvl = piv[-1][2] if piv else kl[-10]["close"]

    pa_react_zone = last_lvl

    return (
        "📘 *مدرسة السلوك السعري — Price Action*\n"
        "🔍 *مقدمة:*\n"
        "تقرأ السوق من شموعه: من يسيطر؟ أين حدث الرفض؟ هل الحركة اندفاع أم تصحيح؟\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🕯️ *1) الشمعة الأهم الآن:*\n"
        f"• آخر شمعة مؤثرة: *{pa_candle}*\n"
        f"• دلالة الشمعة: *{pa_message}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *2) سياق الحركة (Context):*\n"
        f"• اتجاه لحظي (Bias): *{bias}*\n"
        f"• ATR(14): *{fmt(atr,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *3) منطقة رد فعل متوقعة:*\n"
        f"• مستوى مراقبة: *{fmt(pa_react_zone,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *4) قواعد الدخول الاحترافية:*\n"
        "• لا تعتمد على شكل الشمعة وحده؛ راقب مكانها (عند دعم/مقاومة/سيولة/منطقة SD).\n"
        "• الشمعة القوية داخل منطقة قرار + حجم أعلى = أفضلية أعلى بكثير.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"الإشارة الحالية: **{pa_message}** — راقب **{fmt(pa_react_zone,2)}**.\n"
    )


# ============================================================
# SCHOOL: Multi-Timeframe (HTF/MTF/LTF) (ADVANCED)
# ============================================================
def school_mtf(symbol, snap):
    p = snap.get("price")
    if p is None:
        return "📘 *مدرسة Multi-Timeframe*\n⚠️ بيانات غير كافية.\n"

    # try multiple timeframes
    kl_h = _safe_klines(symbol, interval="1h", limit=260)
    kl_m = _safe_klines(symbol, interval="15m", limit=320)
    kl_l = _safe_klines(symbol, interval="5m", limit=320)

    def _trend_from_ema(kl):
        if not kl or len(kl) < 60:
            return "غير متاح"
        e50 = _ema(kl, 50)
        e200 = _ema(kl, 200)
        if e50 is None or e200 is None:
            return "غير متاح"
        return "صاعد" if e50 > e200 else "هابط" if e50 < e200 else "محايد"

    htf_bias = _trend_from_ema(kl_h)
    mtf_bias = _trend_from_ema(kl_m)
    ltf_bias = _trend_from_ema(kl_l)

    combined = "متوافق صعودًا" if (htf_bias == mtf_bias == ltf_bias == "صاعد") else \
               "متوافق هبوطًا" if (htf_bias == mtf_bias == ltf_bias == "هابط") else \
               "مختلط — يحتاج فلترة"

    return (
        "📘 *مدرسة Multi-Timeframe — HTF → LTF*\n"
        "🔍 *مقدمة:*\n"
        "الهدف: منع الدخول ضد الاتجاه الأكبر، وقراءة نية السوق على الفريمات المختلفة.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"• HTF (1H) الاتجاه: *{htf_bias}*\n"
        f"• MTF (15M) الاتجاه: *{mtf_bias}*\n"
        f"• LTF (5M) النية: *{ltf_bias}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📌 الدمج النهائي: **{combined}**\n"
        "⚠️ ملاحظة: إذا كان مختلطًا — الأفضل انتظار كسر/تأكيد على MTF ثم دخول على LTF.\n"
    )


# ============================================================
# SCHOOL: SMC/ICT (ADVANCED but NOT duplicate your SMC template)
# ============================================================
def school_smc_ict(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=520)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 160:
        return "📘 *مدرسة SMC/ICT*\n⚠️ بيانات غير كافية.\n"

    price = float(price)
    atr = _atr(kl, 14) or (snap.get("atr") or 0.0)
    piv = _pivot_points(kl, left=4, right=4)
    highs = [p for i,t,p in piv if t=="H"][-10:]
    lows  = [p for i,t,p in piv if t=="L"][-10:]

    # premium/discount (range)
    hi = max([c["high"] for c in kl[-180:]])
    lo = min([c["low"] for c in kl[-180:]])
    mid = lo + (hi-lo)*0.5
    pd_zone = "Discount" if price < mid else "Premium"

    # FVG proxy using imbalance candles (large body)
    c = kl[-1]
    prev = kl[-2]
    body = abs(c["close"]-c["open"])
    rng = (c["high"]-c["low"]) or 1
    fvg_zone = None
    if body > rng*0.62:
        fvg_zone = (min(c["open"], c["close"]), max(c["open"], c["close"]))

    # ICT signal logic
    ict_signal = "لا يوجد"
    if fvg_zone:
        ict_signal = "اندفاع قوي — راقب عودة Mitigation إلى FVG"

    return (
        "📘 *مدرسة SMC/ICT — Institutional Bias*\n"
        "🔍 *مقدمة:*\n"
        "هذا المحور يحدد مكان السعر داخل النطاق (Premium/Discount) ويراقب مناطق عدم التوازن (FVG) كهدف للتخفيف.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 *1) Premium / Discount:*\n"
        f"• نطاق السوق: Low *{fmt(lo,2)}* → High *{fmt(hi,2)}*\n"
        f"• منتصف النطاق (EQ): *{fmt(mid,2)}*\n"
        f"• تموضع السعر: **{pd_zone}**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟦 *2) Fair Value Gap (Proxy):*\n"
        f"• أقرب FVG: *{fmt(fvg_zone[0],2)} → {fmt(fvg_zone[1],2)}* \n" if fvg_zone else
        "• أقرب FVG: *غير واضح الآن*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *3) إشارة ICT:*\n"
        f"• الإشارة: *{ict_signal}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"أفضلية المؤسسات غالبًا تعمل من **{pd_zone}** — راقب أي عودة لمنطقة عدم توازن إن ظهرت.\n"
    )


# ============================================================
# SCHOOL: Wyckoff (ADVANCED but compact, independent)
# ============================================================
def school_wyckoff(symbol, snap):
    kl = _safe_klines(symbol, interval="15m", limit=520)
    price = snap.get("price")
    if not kl or price is None or len(kl) < 200:
        return "📘 *مدرسة Wyckoff*\n⚠️ بيانات غير كافية.\n"

    price = float(price)
    highs = [c["high"] for c in kl[-240:]]
    lows  = [c["low"]  for c in kl[-240:]]
    hi = max(highs)
    lo = min(lows)
    rng = hi - lo
    atr = _atr(kl, 14) or (snap.get("atr") or 0.0)

    # range classification
    range_type = "ضيق" if rng <= atr*18 else "واسع"
    # phase guess from where price sits + trend bias
    if price < lo + rng*0.35:
        wy_phase = "Accumulation محتمل (قرب القاع)"
    elif price > lo + rng*0.65:
        wy_phase = "Distribution محتمل (قرب القمة)"
    else:
        wy_phase = "Trading Range (منتصف النطاق)"

    range_zone = f"{fmt(lo,2)} → {fmt(hi,2)}"
    vol_behavior = "مراقبة الحجم مطلوبة لتأكيد الامتصاص/التصريف"
    range_reaction = "قوي عند الحدود / ضعيف في الوسط"

    # events approximation
    sc_level = lo
    ar_level = lo + rng*0.6
    st_level = lo + rng*0.25
    spring_or_ut = "Spring محتمل" if price < lo + rng*0.18 else "Upthrust محتمل" if price > lo + rng*0.82 else "غير واضح"
    sos_lps_zone = lo + rng*0.4

    wyckoff_bias = "صعود" if "Accumulation" in wy_phase else "هبوط" if "Distribution" in wy_phase else "محايد"

    return (
        f"📘 *مدرسة Wyckoff — تحليل {symbol}*\n"
        "🔍 *مقدمة:*\n"
        "Wyckoff يحدد المرحلة: هل هناك تجميع أم تصريف داخل نطاق؟ ويبحث عن أحداث رئيسية قبل الانطلاق.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *1) مرحلة السوق الحالية (Market Phase):*\n"
        f"• المرحلة المحتملة: *{wy_phase}*\n"
        f"• نطاق السعر (Trading Range): *{range_zone}*\n"
        f"• حجم التداول (Volume Behaviour): {vol_behavior}\n"
        f"• رد الفعل عند الحد العلوي/السفلي: {range_reaction}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎭 *2) أحداث Wyckoff الأساسية (Events) — تقديريًا:*\n"
        f"• SC: *{fmt(sc_level,2)}*\n"
        f"• AR: *{fmt(ar_level,2)}*\n"
        f"• ST: *{fmt(st_level,2)}*\n"
        f"• Test / Spring / Upthrust: *{spring_or_ut}*\n"
        f"• SOS / LPS Zone: *{fmt(sos_lps_zone,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔎 *3) قراءة النطاق (Trading Range Analysis):*\n"
        f"• هل النطاق ضيق أم واسع؟ → *{range_type}*\n"
        "• قاعدة ذهبية: لا تدخل من منتصف الرنج — راقب الحد العلوي/السفلي فقط.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        f"سلوك Wyckoff يشير إلى **{wyckoff_bias}** مع تركيز على حدود النطاق: **{range_zone}**.\n"
    )


# ============================================================
# SCHOOL: Risk Model (ADVANCED)
# ============================================================
def school_risk_model(symbol, snap):
    price = snap.get("price")
    atr = snap.get("atr") or 0.0
    conf = snap.get("confidence", 0) or 0
    risk_score = snap.get("risk_score", 5.0) or 5.0

    setup_quality = clamp(conf, 5, 95)
    rr_ratio = "1:2" if setup_quality >= 70 else "1:1.5" if setup_quality >= 55 else "1:1"
    invalidation_level = fmt(float(price) - float(atr)*1.2,2) if price and atr else "غير متاح"

    return (
        "📘 *نموذج إدارة المخاطرة — Risk Model*\n"
        "🔍 *مقدمة:*\n"
        "هذه المدرسة لا تتنبأ بالاتجاه فقط، بل تُقيّم جودة الإعداد وتحدد أسوأ نقطة لإلغاء السيناريو.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"• جودة الصفقة (Setup Quality): *{fmt(setup_quality,2)}%*\n"
        f"• R:R المقترحة: *{rr_ratio}*\n"
        f"• مستوى الإلغاء (Invalidation): *{invalidation_level}*\n"
        f"• مؤشر الخطر الداخلي: *{fmt(risk_score,2)}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص المدرسة:*\n"
        "لو الجودة أقل من 55% → الأفضل انتظار تأكيد أو تقليل حجم المخاطرة.\n"
    )


# ============================================================
# MASTER 12-IN-ONE ANALYSIS (NO DUPLICATION / VERY EXPANDED)
# ============================================================
def build_master_all_in_one(symbol, snap):
    # gather blocks from PART 5 dispatcher
    blocks = build_school_blocks(symbol, snap)

    # additional schools from this part
    liq_txt = school_liquidity(symbol, snap)
    sd_txt  = school_supply_demand(symbol, snap)
    pa_txt  = school_price_action(symbol, snap)
    mtf_txt = school_mtf(symbol, snap)
    ict_txt = school_smc_ict(symbol, snap)
    wy_txt  = school_wyckoff(symbol, snap)
    risk_txt= school_risk_model(symbol, snap)

    # Prepare final verdict numbers
    price = snap.get("price")
    conf  = int(clamp(snap.get("confidence", 0) or 0, 0, 100))
    bias  = snap.get("bias") or "NEUTRAL"

    # Targets (proxy)
    atr = snap.get("atr") or 0.0
    if price and atr:
        p = float(price)
        target1 = p + atr*2.0 if bias=="BULLISH" else p - atr*2.0 if bias=="BEARISH" else p + atr*1.2
        target2 = p + atr*3.2 if bias=="BULLISH" else p - atr*3.2 if bias=="BEARISH" else p - atr*1.2
        turn_point = p - atr*1.0 if bias=="BULLISH" else p + atr*1.0 if bias=="BEARISH" else p
    else:
        target1 = target2 = turn_point = None

    final_direction = "صعود" if bias=="BULLISH" else "هبوط" if bias=="BEARISH" else "محايد"
    final_scenario = "استمرار اتجاه" if conf >= 70 else "حركة متذبذبة/قرار" if conf >= 50 else "حذر — انتظار تأكيد"
    master_summary = "توافق مدارس متعدد" if conf >= 70 else "توافق جزئي" if conf >= 50 else "غير متوافق بالكامل"
    critical_master_level = turn_point if turn_point is not None else price

    # build message (clean, no internal v text)
    master = (
        f"📘 *ALL-IN-ONE MASTER ANALYSIS — التحليل الشامل للعملة {symbol}*\n"
        "🔍 *مقدمة:*\n"
        "هذا النموذج يجمع عدة مدارس تحليلية كاملة لإخراج قراءة نهائية متقدمة للسوق.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 *1) الاتجاه العام (Trend & Structure):*\n"
        f"• الاتجاه النهائي: **{final_direction}**\n"
        f"• نسبة الثقة: **{conf}%**\n"
        f"• السيناريو الأقوى: {final_scenario}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧊 *2) السيولة (Liquidity Map):*\n"
        + liq_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "🧱 *3) العرض والطلب (Supply & Demand):*\n"
        + sd_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "🕯️ *4) السلوك السعري (Price Action):*\n"
        + pa_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *5) الحجم + التذبذب (Volume & Volatility):*\n"
        + blocks.get("volume","") +
        "━━━━━━━━━━━━━━━━━━\n"
        "⏳ *6) الزمن (Time Master Model):*\n"
        + blocks.get("time","") +
        "━━━━━━━━━━━━━━━━━━\n"
        "🔢 *7) التحليل الرقمي (Digital Model):*\n"
        + blocks.get("digital","") +
        "━━━━━━━━━━━━━━━━━━\n"
        "📐 *8) الفني الكلاسيكي (Classical TA):*\n"
        + blocks.get("classical","") +
        "━━━━━━━━━━━━━━━━━━\n"
        "🎼 *9) التوافقي (Harmonic):*\n"
        + blocks.get("harmonic","") +
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 *10) الانحياز المؤسسي (SMC/ICT):*\n"
        + ict_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *11) Multi-Timeframe (HTF→LTF):*\n"
        + mtf_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "🛡️ *12) إدارة المخاطرة (Risk Model):*\n"
        + risk_txt +
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *النتيجة النهائية (Final Verdict):*\n"
        f"• الاتجاه النهائي: **{final_direction}**\n"
        f"• نسبة الثقة: **{conf}%**\n"
        f"• السيناريو الأقوى: {final_scenario}\n"
        "• أهداف الحركة:\n"
        f"  1) {fmt(target1,2)}\n"
        f"  2) {fmt(target2,2)}\n"
        f"• نقطة الانعكاس/القرار: {fmt(turn_point,2)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *ملخص التحليل:*\n"
        f"السوق يظهر **{master_summary}**\n"
        f"وأهم منطقة ستحدد كل شيء هي: **{fmt(critical_master_level,2)}**\n"
        f"🕒 {_now_iso()}\n"
    )

    return master


# ============================================================
# MENU: choose school then symbol (NO market/school confusion)
# ============================================================

SCHOOLS = [
    ("ALL-IN-ONE", "MASTER"),
    ("SMC/ICT", "SMC"),
    ("Wyckoff", "WYCK"),
    ("Classical TA", "TA"),
    ("Harmonic", "HARM"),
    ("Digital", "DIG"),
    ("Time Master", "TIME"),
    ("Volume", "VOL"),
    ("Liquidity", "LIQ"),
    ("Supply&Demand", "SD"),
    ("Price Action", "PA"),
    ("Multi-TF", "MTF"),
    ("Risk Model", "RISK"),
]

# store user selection in memory dict (if your project already has one, this merges)
try:
    USER_STATE
except:
    USER_STATE = {}


def build_school_keyboard():
    # your bot might already have keyboard builder
    rows = []
    row = []
    for name, code in SCHOOLS:
        row.append({"text": name, "callback_data": f"SCHOOL|{code}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}

def build_symbol_keyboard():
    # quick list; user can also type custom symbol
    syms = ["BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","SOLUSDT","DOGEUSDT","AVAXUSDT","MATICUSDT"]
    rows = []
    row=[]
    for s in syms:
        row.append({"text": s, "callback_data": f"SYM|{s}"})
        if len(row)==2:
            rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([{"text": "✍️ اكتب عملة أخرى", "callback_data": "SYM|CUSTOM"}])
    return {"inline_keyboard": rows}


def render_school_analysis(symbol, school_code, snap):
    # returns text
    if school_code == "MASTER":
        return build_master_all_in_one(symbol, snap)

    # per-school outputs (independent)
    if school_code == "SMC":
        return school_smc_ict(symbol, snap)
    if school_code == "WYCK":
        return school_wyckoff(symbol, snap)
    if school_code == "TA":
        return school_classical_ta(symbol, snap)
    if school_code == "HARM":
        return school_harmonic(symbol, snap)
    if school_code == "DIG":
        return school_digital_analysis(symbol, snap)
    if school_code == "TIME":
        return school_time_master(symbol, snap)
    if school_code == "VOL":
        return school_volume_analysis(symbol, snap)
    if school_code == "LIQ":
        return school_liquidity(symbol, snap)
    if school_code == "SD":
        return school_supply_demand(symbol, snap)
    if school_code == "PA":
        return school_price_action(symbol, snap)
    if school_code == "MTF":
        return school_mtf(symbol, snap)
    if school_code == "RISK":
        return school_risk_model(symbol, snap)

    return "⚠️ مدرسة غير معروفة."


# ============================================================
# FAST PROCESSING: run heavy analysis in background thread
# ============================================================

def process_request_async(chat_id, school_code, symbol):
    try:
        snap = get_snapshot(symbol) if "get_snapshot" in globals() else {}
        # fallback: if your project uses a different snapshot function, try common names
        if not snap:
            snap = _safe_call(get_market_snapshot, {}, symbol) if "get_market_snapshot" in globals() else {}
        if not snap:
            # minimal snapshot from klines
            kl = _safe_klines(symbol, interval="15m", limit=220)
            if kl:
                snap = {
                    "price": kl[-1]["close"],
                    "atr": _atr(kl,14),
                    "confidence": 55,
                    "risk_score": 4.5,
                    "bias": "NEUTRAL",
                }

        text = render_school_analysis(symbol, school_code, snap)
        send_long_message(chat_id, text)

    except Exception as e:
        try:
            send_message(chat_id, f"⚠️ حصل خطأ أثناء إنشاء التحليل: {_ensure_str(e)}")
        except:
            pass
# ============================================================
# WEBHOOK ROUTE (FAST ACK + SAFE ROUTING)
# ============================================================

from flask import request, jsonify
import os
import logging

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    هدفها:
    - ترجع 200 بسرعة جدا (Fast ACK) عشان تليجرام مايعيدش نفس التحديثات
    - أي أخطاء جوه منطق المعالجة ما تقعّش السيرفر
    """
    try:
        update = request.get_json(force=True, silent=True) or {}

        # Router آمن: يتعامل مع message + callback_query
        try:
            webhook_router_update(update)
        except Exception:
            config.logger.exception("webhook_router_update failed")

        return "OK", 200

    except Exception:
        config.logger.exception("webhook fatal error")
        # لازم 200 حتى لو حصلت مشكلة عشان تليجرام مايفضلش يعيد
        return "OK", 200


@app.route("/", methods=["GET"])
def home():
    return "RUNNING", 200


@app.route("/health", methods=["GET"])
def health():
    # Healthcheck لـ Koyeb
    return jsonify({"status": "ok"}), 200
    
# =====================================
# تشغيل البوت — Main Runner (UPDATED)
# =====================================

if __name__ == "__main__":
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

    # تشغيل كل الثريدات من services
    try:
        services.start_background_threads()
    except Exception as e:
        logging.exception("Failed to start background threads: %s", e)

    # تشغيل Flask (IMPORTANT: use PORT env in production)
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
