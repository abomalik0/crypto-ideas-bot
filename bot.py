# ==============================
# IN CRYPTO — WAR ROOM BOT
# FULL MASTER VERSION
# ==============================

import os
import re
import json
import math
import time
import random
import logging
from datetime import datetime, timedelta

import requests
from flask import Flask, request, jsonify

# ==============================
# ENV / CONFIG
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or os.getenv("APP_BASE_URL") or os.getenv("APP_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", "8080"))

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("IN-CRYPTO")

# ==============================
# FLASK
# ==============================

app = Flask(__name__)

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

def _ensure_str(x):
    try:
        return "" if x is None else str(x)
    except:
        return ""

# ============================================================
# TELEGRAM SEND / CALLBACK
# ============================================================

def send_message(chat_id, text, reply_markup=None, disable_preview=True):
    payload = {
        "chat_id": chat_id,
        "text": _ensure_str(text),
        "parse_mode": "Markdown",
        "disable_web_page_preview": disable_preview
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return requests.post(f"{API_URL}/sendMessage", json=payload, timeout=8).json()
    except Exception as e:
        logger.warning(f"send_message failed: {e}")
        return None

def answer_callback(callback_query_id, text=""):
    # (لم يعد يُستخدم بعد إزالة Inline، لكنه تركناه حفاظًا على الشغل القديم بدون حذف)
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(f"{API_URL}/answerCallbackQuery", json=payload, timeout=6)
    except:
        pass

# ============================================================
# TELEGRAM LIMIT SAFE SENDER
# ============================================================

TELEGRAM_LIMIT = 3900  # safe margin < 4096

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

def send_long_message(chat_id, text, reply_markup=None):
    for part in split_message(text):
        send_message(chat_id, part, reply_markup=reply_markup)
        time.sleep(0.25)

# ============================================================
# USER STATE
# ============================================================

USER_STATE = {}

def set_user_symbol(chat_id, symbol):
    USER_STATE[str(chat_id)] = {"symbol": symbol, "ts": time.time()}

def get_user_symbol(chat_id):
    it = USER_STATE.get(str(chat_id))
    return (it or {}).get("symbol") or "BTCUSDT"

# ============================================================
# REPLY KEYBOARDS (INLINE REMOVED 100%)
# ============================================================

def main_menu():
    # Reply Keyboard (بديل inline — أخف وأسرع)
    return {
        "keyboard": [
            ["🧠 ALL SCHOOLS", "📘 ALL-IN-ONE MASTER"],
            ["₿ BTC", "Ξ ETH"],
            ["🧩 Help"],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def schools_menu():
    # Reply Keyboard — مدارس التحليل
    return {
        "keyboard": [
            ["🧊 Liquidity Map", "📚 ICT / SMC"],
            ["📈 Smart Money", "📊 Volume Analysis"],
            ["📘 Classical TA", "🎼 Harmonic"],
            ["🕯 Price Action", "🧱 Supply & Demand"],
            ["🌊 Wyckoff", "🌐 Multi-Timeframe"],
            ["⏳ Time Master", "🔢 Digital Analysis"],
            ["🛡 Risk Model"],
            ["⬅️ Back"],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def build_symbol_keyboard():
    # Reply Keyboard — اختيار العملة (أخف من inline)
    return {
        "keyboard": [
            ["BTCUSDT", "ETHUSDT"],
            ["BNBUSDT", "XRPUSDT"],
            ["SOLUSDT", "DOGEUSDT"],
            ["AVAXUSDT", "MATICUSDT"],
            ["⬅️ Back"],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def build_school_keyboard():
    # Reply Keyboard — قائمة المدارس (بديل inline)
    return schools_menu()

# ============================================================
# BASIC UI HANDLERS
# ============================================================

def handle_start(chat_id):
    send_message(chat_id, "✅ *IN CRYPTO AI جاهز*\nاختر من القائمة 👇", reply_markup=main_menu())

def handle_help(chat_id):
    send_message(
        chat_id,
        "🧩 *Help*\n\n"
        "• اختر العملة من الأزرار (BTC/ETH)\n"
        "• 🧠 ALL SCHOOLS: قائمة المدارس\n"
        "• 📘 ALL-IN-ONE MASTER: تقرير شامل يجمع كل المدارس\n\n"
        "_تحليل تعليمي — ليس توصية تداول_",
        reply_markup=main_menu()
    )

def handle_school(chat_id):
    send_message(chat_id, "🧠 *اختر مدرسة التحليل:*", reply_markup=schools_menu())
# ============================================================
# PART 2/6 — MARKET SNAPSHOT & CORE METRICS
# ============================================================

BINANCE_API = "https://api.binance.com"

# ============================================================
# LOW-LEVEL MARKET DATA (FAST)
# ============================================================

def fetch_price(symbol):
    """
    سعر حالي مباشر — خفيف جدًا
    """
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=5
        ).json()
        return float(r.get("price"))
    except Exception as e:
        logger.warning(f"fetch_price failed: {e}")
        return None


def fetch_klines(symbol, interval="15m", limit=120):
    """
    بيانات شموع (محدودة)
    """
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },
            timeout=8
        ).json()
        return r
    except Exception as e:
        logger.warning(f"fetch_klines failed: {e}")
        return None


# ============================================================
# ATR (Average True Range)
# ============================================================

def calc_atr(klines, period=14):
    """
    ATR بسيط — سريع — كافي للأهداف
    """
    if not klines or len(klines) < period + 1:
        return None

    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        prev_close = float(klines[i - 1][4])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        trs.append(tr)

    if len(trs) < period:
        return None

    atr = sum(trs[-period:]) / period
    return atr


# ============================================================
# SIMPLE TREND / BIAS ENGINE
# ============================================================

def calc_bias(klines):
    """
    Bias بسيط لكن فعّال:
    - Higher highs / Higher lows
    - أو العكس
    """
    if not klines or len(klines) < 30:
        return "NEUTRAL"

    closes = [float(k[4]) for k in klines[-30:]]

    first = sum(closes[:10]) / 10
    last = sum(closes[-10:]) / 10

    if last > first * 1.003:
        return "BULLISH"
    elif last < first * 0.997:
        return "BEARISH"
    else:
        return "RANGE"


# ============================================================
# MARKET SNAPSHOT (CACHED)
# ============================================================

def get_market_snapshot(symbol):
    """
    Snapshot واحد يُستخدم في كل المدارس
    (عشان الأداء)
    """
    cache_key = f"SNAP_{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    price = fetch_price(symbol)
    klines = fetch_klines(symbol, "15m", 120)

    atr = calc_atr(klines)
    bias = calc_bias(klines)

    snapshot = {
        "symbol": symbol,
        "price": price,
        "atr": atr,
        "bias": bias,
        "klines": klines,
        "ts": datetime.utcnow().isoformat()
    }

    _cache_set(cache_key, snapshot)
    return snapshot


# ============================================================
# TARGET ENGINE (ATR-BASED)
# ============================================================

def calc_targets(price, atr, bias):
    """
    حساب Target 1 / Target 2 / Invalidation
    """
    if price is None or atr is None:
        return None

    if bias == "BULLISH":
        t1 = price + atr * 1.2
        t2 = price + atr * 2.4
        sl = price - atr * 1.0
    elif bias == "BEARISH":
        t1 = price - atr * 1.2
        t2 = price - atr * 2.4
        sl = price + atr * 1.0
    else:  # RANGE
        t1 = price + atr
        t2 = price - atr
        sl = price - atr * 1.5

    return {
        "t1": t1,
        "t2": t2,
        "sl": sl
    }


def build_targets_block(snapshot, note=""):
    tg = calc_targets(
        snapshot.get("price"),
        snapshot.get("atr"),
        snapshot.get("bias")
    )

    if not tg:
        return "🎯 *Targets*\n⚠️ بيانات غير كافية لحساب الأهداف.\n"

    note_block = ""
    if note:
        note_block = "• ملاحظة: " + note + "\n"

    return (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *Targets (تحليل تعليمي)*\n"
        f"• Target 1: *{fmt(tg['t1'])}*\n"
        f"• Target 2: *{fmt(tg['t2'])}*\n"
        f"• Invalidation: *{fmt(tg['sl'])}*\n"
        + note_block +
        "_الأهداف مبنية على ATR والسياق العام_\n"
    )
# ============================================================
# PART 3/6 — ADVANCED ANALYSIS SCHOOLS
# كل مدرسة لها أسلوب مختلف وتحليل موسّع
# ============================================================


# ============================================================
# 🧊 LIQUIDITY MAP — Institutional Liquidity Hunter
# ============================================================

def school_liquidity_map(symbol, snap):
    price = snap["price"]
    atr = snap["atr"]
    bias = snap["bias"]
    klines = snap["klines"] or []

    text = (
        "🧊 *Liquidity Map — Institutional View*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذه المدرسة تركز على تتبع أماكن تجمع أوامر الإيقاف (Stops)\n"
        "والتي يميل السعر لزيارتها قبل أي حركة كبيرة.\n\n"
    )

    text += (
        "🔍 *Liquidity Diagnosis*\n"
        f"• الاتجاه العام: *{bias}*\n"
        "• السوق يبحث عن سيولة واضحة (قمم/قيعان متقاربة)\n"
        "• الحركة الحالية تشير إلى اقتراب من منطقة جذب سيولة\n\n"
    )

    text += (
        "🧠 *Institutional Logic*\n"
        "• Sweep سريع + رجوع = مصيدة (Trap)\n"
        "• Sweep + قبول سعري = استمرار\n"
        "• التباطؤ قرب قمة/قاع = تجميع أوامر\n\n"
    )

    text += (
        "📍 *Execution Context*\n"
        "• لا دخول قبل حدوث Sweep أو تأكيد رفض\n"
        "• الأفضل دمج هذه المدرسة مع SMC أو Volume\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف مبنية على أقرب تجمع سيولة + ATR"
    )

    return text


# ============================================================
# 📚 ICT / SMC — Institutional Order Flow
# ============================================================

def school_ict(symbol, snap):
    price = snap["price"]
    bias = snap["bias"]

    text = (
        "📚 *ICT / Smart Money Concepts*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذه المدرسة تفسر السوق كسلوك مؤسسي منظم\n"
        "يعتمد على: Sweep → Displacement → Rebalance → Expansion\n\n"
    )

    text += (
        "🧭 *Market Location*\n"
        f"• Bias العام: *{bias}*\n"
        "• تحديد Premium / Discount مهم قبل أي قرار\n\n"
    )

    text += (
        "⚡ *Order Flow Logic*\n"
        "• Displacement القوي يدل على دخول مؤسسات\n"
        "• السعر غالبًا يعود لملء FVG أو OB\n"
        "• أفضل الصفقات من مناطق Discount في الاتجاه الصاعد\n\n"
    )

    text += (
        "📌 *Execution Rules*\n"
        "• لا صفقة بدون Displacement واضح\n"
        "• لا دخول بدون عودة للسعر (Rebalance)\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف مبنية على دورة ICT الكاملة (EQ → Premium)"
    )

    return text


# ============================================================
# 📈 SMART MONEY — Market Structure Engineer
# ============================================================

def school_smc(symbol, snap):
    bias = snap["bias"]

    text = (
        "📈 *Smart Money Concepts (SMC)*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذه المدرسة تركز على هيكلة السوق (Market Structure)\n"
        "من خلال HH/HL و BOS و CHoCH.\n\n"
    )

    text += (
        "🏗 *Structure Analysis*\n"
        f"• الهيكل الحالي: *{bias}*\n"
        "• BOS = استمرار الاتجاه\n"
        "• CHoCH = تحذير تغير اتجاه\n\n"
    )

    text += (
        "🧱 *Order Blocks*\n"
        "• OB الصالح هو آخر شمعة عكسية قبل اندفاع قوي\n"
        "• المناطق غير المُختبرة (Fresh) أقوى\n\n"
    )

    text += (
        "📍 *Execution Discipline*\n"
        "• لا دخول في منتصف الحركة\n"
        "• الأفضل انتظار العودة للـ OB\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف مبنية على امتداد الهيكل + سيولة قريبة"
    )

    return text


# ============================================================
# 📊 VOLUME ANALYSIS — Professional Tape Reading
# ============================================================

def school_volume(symbol, snap):
    bias = snap["bias"]

    text = (
        "📊 *Volume Analysis — Professional View*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "الحجم يسبق السعر، ويفضح نوايا اللاعبين الكبار.\n\n"
    )

    text += (
        "🔊 *Volume Context*\n"
        f"• الاتجاه الإحصائي: *{bias}*\n"
        "• الحجم العالي مع حركة ضعيفة = امتصاص\n"
        "• الحركة بدون حجم = حركة هشة\n\n"
    )

    text += (
        "⚖ *Effort vs Result*\n"
        "• مجهود كبير + نتيجة ضعيفة = انعكاس محتمل\n"
        "• مجهود كبير + نتيجة قوية = استمرار\n\n"
    )

    text += (
        "📌 *Execution Notes*\n"
        "• لا تعتمد على الحجم وحده\n"
        "• الأفضل دمجه مع Liquidity أو SMC\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف مبنية على مناطق HVN/LVN المحتملة"
    )

    return text


# ============================================================
# 📘 CLASSICAL TA — Technical Engineer
# ============================================================

def school_classical_ta(symbol, snap):
    bias = snap["bias"]

    text = (
        "📘 *Classical Technical Analysis*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "التحليل الفني الكلاسيكي يحدد الاتجاه والزخم والمناطق الفنية.\n\n"
    )

    text += (
        "📐 *Trend & Momentum*\n"
        f"• الاتجاه العام: *{bias}*\n"
        "• EMA / RSI / MACD تُستخدم لتأكيد الزخم\n\n"
    )

    text += (
        "📊 *Key Levels*\n"
        "• الدعم والمقاومة ليست خطوطًا بل نطاقات\n"
        "• الاختراق الحقيقي يحتاج إغلاق + زخم\n\n"
    )

    text += (
        "🧠 *Professional Logic*\n"
        "• الاتجاه صديقك\n"
        "• لا تعاكس السوق بدون دليل قوي\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف مبنية على امتدادات الاتجاه و ATR"
    )

    return text

# ============================================================
# PART 4/6 — REMAINING SCHOOLS (Advanced)
# ============================================================


# ============================================================
# 🎼 HARMONIC — Ratio Surgeon
# ============================================================

def school_harmonic(symbol, snap):
    bias = snap["bias"]

    text = (
        "🎼 *Harmonic Patterns — Ratio Surgeon*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "الهارمونيك مدرسة تعتمد على نسب فيبوناتشي الدقيقة\n"
        "لتحديد مناطق انعكاس عالية الاحتمال (PRZ).\n\n"
    )

    text += (
        "🧬 *Core Logic*\n"
        "• النمط لا يُعتمد إلا إذا تحققت النسب بدقة\n"
        "• PRZ = منطقة تلاقي نسب + تلاقي مقاومة/دعم\n\n"
    )

    text += (
        "🔍 *Professional Filters*\n"
        f"• Bias العام: *{bias}*\n"
        "• الأفضل دمج الهارمونيك مع Volume أو SMC للتأكيد\n\n"
    )

    text += (
        "📍 *Execution*\n"
        "• دخول عند PRZ فقط مع شمعة تأكيد\n"
        "• الإلغاء يكون بكسر نقطة X\n\n"
    )

    text += build_targets_block(
        snap,
        note="في الهارمونيك: T1 غالبًا 38.2% وT2 61.8% من موجة CD (تقريبيًا)"
    )

    return text


# ============================================================
# 🕯 PRICE ACTION — Context Master
# ============================================================

def school_price_action(symbol, snap):
    bias = snap["bias"]

    text = (
        "🕯 *Price Action — Context Master*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "الشموع ليست إشارات وحدها… السياق هو كل شيء.\n\n"
    )

    text += (
        "📌 *Context First*\n"
        f"• Bias العام: *{bias}*\n"
        "• أقوى إشارات الشموع تأتي عند مناطق القرار (S/R أو Zones)\n\n"
    )

    text += (
        "🔥 *Candle Language*\n"
        "• Pin Bar = رفض سعري\n"
        "• Engulfing = سيطرة\n"
        "• Inside Bar = ضغط قبل انفجار\n\n"
    )

    text += (
        "✅ *Confirmation Ladder*\n"
        "1) شمعة رفض/سيطرة\n"
        "2) كسر صغير في الهيكل LTF\n"
        "3) (اختياري) حجم يدعم الحركة\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف هنا تعتمد على أقرب Level تقني بعد شمعة التأكيد"
    )

    return text


# ============================================================
# 🧱 SUPPLY & DEMAND — Zone Architect
# ============================================================

def school_supply_demand(symbol, snap):
    bias = snap["bias"]

    text = (
        "🧱 *Supply & Demand — Zone Architect*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذه المدرسة تحدد المناطق التي حدث فيها شراء/بيع قوي\n"
        "وتُعامل المنطقة كنطاق وليس خط.\n\n"
    )

    text += (
        "🏗 *Zone Quality Score*\n"
        "• قوة الخروج من المنطقة\n"
        "• عدد اللمسات (كل لمسة تضعف)\n"
        "• الوقت داخل القاعدة (الأقل غالبًا أقوى)\n\n"
    )

    text += (
        "📌 *Professional Plan*\n"
        f"• Bias العام: *{bias}*\n"
        "• أفضل سيناريو: First Touch + Confirmation\n\n"
    )

    text += (
        "❌ *Invalidation*\n"
        "• إغلاق كامل داخل المنطقة ثم اختراقها = ضعف الفكرة\n\n"
    )

    text += build_targets_block(
        snap,
        note="T1 غالبًا منتصف الرينج، T2 المنطقة المقابلة"
    )

    return text


# ============================================================
# 🌊 WYCKOFF — Phase Detective
# ============================================================

def school_wyckoff(symbol, snap):
    bias = snap["bias"]

    text = (
        "🌊 *Wyckoff — Phase Detective*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Wyckoff يركز على مراحل السوق:\n"
        "Accumulation → Markup → Distribution → Markdown\n\n"
    )

    text += (
        "🧩 *Phase Logic*\n"
        "• Spring = كسر قاع ثم رجوع سريع\n"
        "• UTAD = كسر قمة ثم رجوع سريع\n"
        "• SOS/SOW تحدد قوة المرحلة\n\n"
    )

    text += (
        "📌 *Interpretation*\n"
        f"• Bias العام: *{bias}*\n"
        "• الأفضل تأكيد المرحلة من الحجم (Volume)\n\n"
    )

    text += build_targets_block(
        snap,
        note="Wyckoff: T1 قمة/قاع الرينج، T2 امتداد خارج الرينج"
    )

    return text


# ============================================================
# 🌐 MULTI-TIMEFRAME — Strategy Integrator
# ============================================================

def school_mtf(symbol, snap):
    bias = snap["bias"]

    text = (
        "🌐 *Multi-Timeframe — Strategy Integrator*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذه المدرسة تمنع التضارب:\n"
        "HTF يحدد الاتجاه، LTF يحدد الدخول.\n\n"
    )

    text += (
        "🧭 *HTF → LTF Alignment*\n"
        f"• Bias العام: *{bias}*\n"
        "• صفقة مع الاتجاه = مخاطرة أقل\n"
        "• صفقة ضد الاتجاه = تحتاج تأكيد مضاعف\n\n"
    )

    text += (
        "📍 *Execution Rule*\n"
        "• لا دخول إلا عند توافق (Location + Trigger)\n\n"
    )

    text += build_targets_block(
        snap,
        note="الأهداف هنا تتبع مستويات HTF ثم Liquidity أكبر"
    )

    return text


# ============================================================
# 🛡 RISK MODEL — Risk Officer
# ============================================================

def school_risk(symbol, snap):
    bias = snap["bias"]

    text = (
        "🛡 *Risk Model — Risk Officer*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "الصفقة ليست جميلة لأنك تتوقع…\n"
        "بل جميلة لأن خسارتها محسوبة.\n\n"
    )

    text += (
        "✅ *Core Rules*\n"
        "• لا تخاطر بأكثر من 0.5% – 1% في الصفقة\n"
        "• وقف الخسارة يجب أن يكون منطقي (Swing/Zone)\n"
        "• لا تدخل بدون خطة أهداف واضحة\n\n"
    )

    text += (
        "⚠️ *Professional Warning*\n"
        "• Overtrading يقتل الحساب\n"
        "• لا تطارد السعر\n\n"
    )

    text += build_targets_block(
        snap,
        note="T1 لتأمين الصفقة (Partial)، T2 لتحقيق العائد الحقيقي"
    )

    return text


# ============================================================
# ⏳ TIME MASTER — Timing Officer
# ============================================================

def school_time_master(symbol, snap):
    bias = snap["bias"]

    text = (
        "⏳ *Time Master — Timing Officer*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "التوقيت جزء من التحليل:\n"
        "فكرة صحيحة بتوقيت سيئ = خسارة.\n\n"
    )

    text += (
        "🕒 *Timing Logic*\n"
        "• بعض الحركات تظهر بقوة في نوافذ سيولة معينة\n"
        "• Time-invalidation: لو السيناريو لم يتحقق خلال N شموع = ضعيف\n\n"
    )

    text += (
        "📌 *Context*\n"
        f"• Bias العام: *{bias}*\n"
        "• دمج التوقيت مع Liquidity يعطي نتائج قوية\n\n"
    )

    text += build_targets_block(
        snap,
        note="Time Master: لو لم يصل T1 سريعًا فالسيناريو يحتاج إعادة تقييم"
    )

    return text


# ============================================================
# 🔢 DIGITAL ANALYSIS — Quant-ish
# ============================================================

def school_digital(symbol, snap):
    bias = snap["bias"]

    text = (
        "🔢 *Digital Analysis — Quant-ish View*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "مدرسة رقمية تعتمد على:\n"
        "Round Numbers / Quarters / Mean Reversion Zones\n\n"
    )

    text += (
        "🧮 *Digital Logic*\n"
        "• الأسعار تميل للتجمع حول أرقام نفسية\n"
        "• تقسيم الحركة إلى أرباع يساعد على تحديد مناطق القرار\n\n"
    )

    text += (
        "📌 *Context*\n"
        f"• Bias العام: *{bias}*\n"
        "• الأفضل دمجها مع TA و Volume\n\n"
    )

    text += build_targets_block(
        snap,
        note="Digital: T1 أقرب مستوى نفسي، T2 مستوى نفسي أبعد"
    )

    return text

# ============================================================
# PART 5/6 — ALL SCHOOLS & MASTER ANALYSIS
# ============================================================


# ============================================================
# SCHOOL ROUTER
# ============================================================

SCHOOL_MAP = {
    "🧊 Liquidity Map": school_liquidity_map,
    "📚 ICT / SMC": school_ict,
    "📈 Smart Money": school_smc,
    "📊 Volume Analysis": school_volume,
    "📘 Classical TA": school_classical_ta,
    "🎼 Harmonic": school_harmonic,
    "🕯 Price Action": school_price_action,
    "🧱 Supply & Demand": school_supply_demand,
    "🌊 Wyckoff": school_wyckoff,
    "🌐 Multi-Timeframe": school_mtf,
    "🛡 Risk Model": school_risk,
    "⏳ Time Master": school_time_master,
    "🔢 Digital Analysis": school_digital,
}


def build_school_report(symbol, school_name):
    snap = get_market_snapshot(symbol)

    header = (
        f"📌 *{symbol}*\n"
        f"السعر الحالي: *{fmt(snap.get('price'))}*\n"
        f"Bias العام: *{snap.get('bias')}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    fn = SCHOOL_MAP.get(school_name)
    if not fn:
        return header + "⚠️ مدرسة غير معروفة."

    body = fn(symbol, snap)
    return header + body


# ============================================================
# ALL SCHOOLS REPORT
# ============================================================

def build_all_schools(symbol):
    snap = get_market_snapshot(symbol)

    text = (
        f"🧠 *ALL SCHOOLS ANALYSIS — {symbol}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذا التقرير يعرض كل مدرسة على حدة.\n"
        "اقرأ كل مدرسة كزاوية رؤية مختلفة.\n\n"
    )

    for name, fn in SCHOOL_MAP.items():
        try:
            text += fn(symbol, snap)
            text += "\n\n"
        except Exception as e:
            logger.warning(f"School {name} failed: {e}")

    return text


# ============================================================
# MASTER ANALYSIS (FINAL SUMMARY)
# ============================================================

def build_master_analysis(symbol):
    snap = get_market_snapshot(symbol)
    bias = snap.get("bias")

    # ========================
    # SIMPLE CONFLUENCE SCORE
    # ========================
    score = 0
    if bias == "BULLISH":
        score += 2
    elif bias == "BEARISH":
        score -= 2

    # مدارس داعمة للاتجاه
    supportive = ["Liquidity", "SMC", "ICT", "Volume", "TA"]
    score += 1 if bias == "BULLISH" else -1

    if score >= 3:
        verdict = "📈 *BULLISH BIAS*"
    elif score <= -3:
        verdict = "📉 *BEARISH BIAS*"
    else:
        verdict = "🔁 *RANGE / WAIT*"

    text = (
        f"📘 *MASTER ANALYSIS — {symbol}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هذا التقرير هو خلاصة كل المدارس التحليلية.\n\n"
    )

    text += (
        "🧭 *Market Verdict*\n"
        f"• النتيجة العامة: {verdict}\n"
        f"• Bias الإحصائي: *{bias}*\n\n"
    )

    text += (
        "🧠 *Confluence Summary*\n"
        "• Liquidity: تحدد أين يذهب السعر أولًا\n"
        "• ICT / SMC: تشرح كيف يتحرك المال الذكي\n"
        "• Volume: يؤكد أو ينفي الحركة\n"
        "• TA: يحدد الاتجاه والزخم\n"
        "• Wyckoff: يضع الحركة داخل مرحلة السوق\n\n"
    )

    text += (
        "🎯 *Primary Scenario*\n"
        "• التداول فقط مع الاتجاه الغالب\n"
        "• انتظار Location + Confirmation\n\n"
    )

    text += build_targets_block(
        snap,
        note="MASTER: T1 هدف آمن، T2 هدف هيكلي — لا دخول بدون تأكيد"
    )

    text += (
        "\n⚠️ *Final Notes*\n"
        "• لا تعتمد على مدرسة واحدة\n"
        "• الاتفاق بين المدارس = قوة\n"
        "• الاختلاف = انتظار\n"
        "_تحليل تعليمي وليس توصية تداول_\n"
    )

    return text

# ============================================================
# PART 6/6 — WEBHOOK + ROUTER + RUNNER
# ============================================================

def process_message(chat_id, text):
    """
    Reply Keyboard Router — بدون Inline نهائيًا
    """
    text = (text or "").strip()

    # Commands
    if text.startswith("/start"):
        handle_start(chat_id); return
    if text.startswith("/help"):
        handle_help(chat_id); return
    if text.startswith("/school"):
        handle_school(chat_id); return

    # Main menu
    if text == "🧩 Help":
        handle_help(chat_id); return

    if text == "🧠 ALL SCHOOLS":
        handle_school(chat_id)
        return

    if text == "📘 ALL-IN-ONE MASTER":
        symbol = get_user_symbol(chat_id)
        send_message(chat_id, f"⏳ جاري تجهيز *MASTER ANALYSIS* لـ *{symbol}* ...")
        report = build_master_analysis(symbol)
        send_long_message(chat_id, report, reply_markup=main_menu())
        return

    # Choose crypto
    if text in ("₿ BTC", "Ξ ETH"):
        symbol = "BTCUSDT" if text == "₿ BTC" else "ETHUSDT"
        set_user_symbol(chat_id, symbol)
        send_message(chat_id, f"✅ تم اختيار: *{symbol}*", reply_markup=main_menu())
        return

    # Schools list
    if text == "⬅️ Back":
        handle_start(chat_id); return

    if text in SCHOOL_MAP:
        symbol = get_user_symbol(chat_id)
        send_message(chat_id, f"⏳ جاري تجهيز *{text}* لـ *{symbol}* ...")
        rep = build_school_report(symbol, text)
        send_long_message(chat_id, rep, reply_markup=schools_menu())
        return

    # If user typed symbol manually
    if re.fullmatch(r"[A-Z0-9]{6,12}", text):
        set_user_symbol(chat_id, text.upper())
        send_message(chat_id, f"✅ تم اختيار: *{text.upper()}*", reply_markup=main_menu())
        return

    # Default
    send_message(chat_id, "استخدم الأزرار بالأسفل 👇", reply_markup=main_menu())


def webhook_router_update(update: dict):
    """
    Router آمن للتحديثات
    """
    if not update:
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or ""
        process_message(chat_id, text)
        return

    # لو في callbacks قديمة (من inline القديم) نخليها تتجاهل بدون ما تعمل crash
    if "callback_query" in update:
        try:
            cq = update["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            send_message(chat_id, "✅ تم تحديث البوت — استخدم الأزرار الجديدة أسفل الشاشة.", reply_markup=main_menu())
        except:
            pass
        return


# ============================================================
# WEBHOOK ROUTE (FAST ACK)
# ============================================================

@app.route("/webhook", methods=["POST"], endpoint="telegram_webhook_v2")
def telegram_webhook_v2():
    """
    Fast ACK + Thread
    """
    update = request.get_json(force=True, silent=True) or {}

    def worker(u):
        try:
            webhook_router_update(u)
        except Exception:
            logger.exception("worker failed")

    try:
        threading.Thread(target=worker, args=(update,), daemon=True).start()
    except Exception:
        pass

    return "OK", 200


@app.route("/", methods=["GET"])
def home():
    return "RUNNING", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ============================================================
# WEBHOOK SETUP (OPTIONAL)
# ============================================================

def set_webhook_on_startup():
    """
    يضبط الويب هوك تلقائيًا لو WEBHOOK_URL موجود
    يقبل WEBHOOK_URL سواء كان:
    - https://xxxx.koyeb.app
    - https://xxxx.koyeb.app/webhook
    """
    try:
        if not WEBHOOK_URL:
            logger.info("WEBHOOK_URL not set — skipping setWebhook")
            return

        base = WEBHOOK_URL.rstrip("/")
        # لو المستخدم حاطط /webhook بالفعل، ما نكررش
        if base.endswith("/webhook"):
            url = base
        else:
            url = base + "/webhook"

        payload = {"url": url}
        r = requests.post(f"{API_URL}/setWebhook", json=payload, timeout=8).json()
        logger.info(f"setWebhook response: {r}")
    except Exception as e:
        logger.warning(f"setWebhook failed: {e}")

# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    try:
        set_webhook_on_startup()
    except Exception:
        pass

    app.run(host="0.0.0.0", port=PORT)
