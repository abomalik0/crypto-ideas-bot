import os
import logging
import asyncio
import httpx
from statistics import mean

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- إعداد اللوجينج ----------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------- روابط المصادر ----------------
TV_RSS = "https://www.tradingview.com/ideas/{symbol}/rss/"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


# ---------------- دوال مساعدة ----------------
def normalize_symbol(text: str) -> str:
    """تنظيف الرمز من المسافات والشرطات وتحويله لحروف كبيرة."""
    symbol = text.strip().upper()
    for ch in [" ", "/", "-", "_"]:
        symbol = symbol.replace(ch, "")
    return symbol


# ---------------- جلب الأفكار من TradingView ----------------
async def fetch_ideas(symbol: str, limit: int = 10):
    url = TV_RSS.format(symbol=symbol)
    ideas: list[tuple[str, str]] = []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            response.raise_for_status()
            content = response.text
    except Exception as e:
        logger.error("Error fetching ideas from TradingView: %s", e)
        return None  # خطأ فى الاتصال

    # parsing بسيط للـ RSS
    try:
        parts = content.split("<item>")[1: limit + 1]
        for item in parts:
            try:
                title = item.split("<title><![CDATA[")[1].split("]]></title>")[0]
                link = item.split("<link><![CDATA[")[1].split("]]></link>")[0]
                ideas.append((title, link))
            except Exception:
                continue
    except Exception as e:
        logger.error("Error parsing TradingView RSS: %s", e)
        return None

    return ideas


# ---------------- جلب بيانات السعر من Binance ----------------
async def fetch_binance_klines(symbol: str, limit: int = 50):
    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(BINANCE_KLINES_URL, params=params)
    except Exception as e:
        logger.error("Error calling Binance: %s", e)
        return None

    if resp.status_code != 200:
        logger.error("Binance response code %s: %s", resp.status_code, resp.text)
        return None

    try:
        data = resp.json()
        # لو رجع رسالة خطأ من نوع {"code":..., "msg":...}
        if isinstance(data, dict) and "code" in data:
            logger.error("Binance error: %s", data)
            return None
        return data
    except Exception as e:
        logger.error("Error parsing Binance JSON: %s", e)
        return None


async def build_analysis(symbol: str) -> str | None:
    """تحليل بسيط جداً بناءً على بيانات Binance."""
    klines = await fetch_binance_klines(symbol)
    if not klines:
        return None

    closes = [float(k[4]) for k in klines]  # سعر الإغلاق
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    last_close = closes[-1]
    ma10 = mean(closes[-10:])
    ma20 = mean(closes[-20:])

    highest = max(highs)
    lowest = min(lows)

    # اتجاه بسيط
    if ma10 > ma20:
        trend = "📈 الاتجاه العام قصير المدى صاعد."
    elif ma10 < ma20:
        trend = "📉 الاتجاه العام قصير المدى هابط."
    else:
        trend = "〽️ الاتجاه حالياً متذبذب بدون اتجاه واضح."

    position_parts = []
    if last_close > ma10 and last_close > ma20:
        position_parts.append("السعر حالياً أعلى من المتوسطات المتحركة.")
    elif last_close < ma10 and last_close < ma20:
        position_parts.append("السعر حالياً أسفل من المتوسطات المتحركة.")
    else:
        position_parts.append("السعر حالياً بين المتوسطات المتحركة.")

    # قرب السعر من أعلى/أقل سعر فى الفترة
    dist_high = (highest - last_close) / highest * 100 if highest else 0
    dist_low = (last_close - lowest) / lowest * 100 if lowest else 0

    if dist_low < 5:
        position_parts.append("السعر قريب من قاعه فى الفترة الأخيرة (مستوى دعم محتمل).")
    elif dist_high < 5:
        position_parts.append("السعر قريب من قمته فى الفترة الأخيرة (مستوى مقاومة محتمل).")

    txt = (
        f"📊 *تحليل مبسط لزوج* `{symbol}`\n\n"
        f"• آخر سعر: `{last_close:.4f}`\n"
        f"• متوسط 10 شموع: `{ma10:.4f}`\n"
        f"• متوسط 20 شمعة: `{ma20:.4f}`\n"
        f"• أعلى سعر فى الفترة: `{highest:.4f}`\n"
        f"• أقل سعر فى الفترة: `{lowest:.4f}`\n\n"
        f"{trend}\n"
        f"{' '.join(position_parts)}\n\n"
        "⚠️ *تنبيه هام:* هذا تحليل آلى مبسط للتجربة والتعليم فقط، "
        "وليس نصيحة استثمارية أو مالية."
    )
    return txt


# ---------------- أوامر البوت ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 أهلاً بيك فى بوت *Crypto Ideas Bot*.\n\n"
        "استخدم الأوامر:\n"
        "• `/ideas SYMBOL` للحصول على أفكار من TradingView (مثال: `/ideas BTCUSDT`).\n"
        "• `/analysis SYMBOL` لتحليل سعر بسيط من بيانات Binance (مثال: `/analysis BTCUSDT`).\n"
        "• `/all SYMBOL` للحصول على الأفكار + التحليل فى نفس الوقت.\n\n"
        "تقدر كمان تبعت الرمز مباشرة بدون أى أمر (مثال: `BTCUSDT`) "
        "وساعتها البوت هيجيب لك الأفكار فقط تلقائياً.\n\n"
        "✅ البوت للتجربة والتعليم فقط، مش نصيحة استثمارية."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ استخدم الأمر كده: `/ideas BTCUSDT`", parse_mode="Markdown")
        return

    symbol = normalize_symbol(" ".join(context.args))
    waiting = await update.message.reply_text(
        f"⏳ جارى جلب أفكار `{symbol}` من TradingView...",
        parse_mode="Markdown",
    )

    ideas = await fetch_ideas(symbol)
    if ideas is None:
        await waiting.edit_text(
            f"❌ حدث خطأ أثناء الاتصال بـ TradingView لزوج `{symbol}`.",
            parse_mode="Markdown",
        )
        return

    if not ideas:
        await waiting.edit_text(
            f"❌ لا يوجد أفكار متاحة حالياً لهذا الزوج `{symbol}` أو الرمز غير صحيح.",
            parse_mode="Markdown",
        )
        return

    await waiting.edit_text(
        f"✅ تم العثور على {len(ideas)} فكرة لزوج `{symbol}` من TradingView.\n"
        "سيتم إرسالها فى رسائل منفصلة.",
        parse_mode="Markdown",
    )

    for title, link in ideas:
        text = f"💡 *{title}*\n🔗 {link}"
        await update.message.reply_text(text, parse_mode="Markdown")


async def analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ استخدم الأمر كده: `/analysis BTCUSDT`", parse_mode="Markdown")
        return

    symbol = normalize_symbol(" ".join(context.args))
    waiting = await update.message.reply_text(
        f"⏳ جارى عمل تحليل مبسط لزوج `{symbol}` من بيانات Binance...",
        parse_mode="Markdown",
    )

    analysis = await build_analysis(symbol)
    if analysis is None:
        await waiting.edit_text(
            f"❌ لم أتمكن من جلب بيانات `{symbol}` من Binance.\n"
            "🔎 تأكد إن الرمز صحيح وموجود على Binance (مثال: BTCUSDT، ETHUSDT).",
            parse_mode="Markdown",
        )
        return

    await waiting.edit_text(analysis, parse_mode="Markdown")


async def all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ استخدم الأمر كده: `/all BTCUSDT`", parse_mode="Markdown")
        return

    symbol = normalize_symbol(" ".join(context.args))
    waiting = await update.message.reply_text(
        f"⏳ جارى جلب الأفكار + التحليل لزوج `{symbol}`...",
        parse_mode="Markdown",
    )

    ideas_task = asyncio.create_task(fetch_ideas(symbol))
    analysis_task = asyncio.create_task(build_analysis(symbol))

    ideas = await ideas_task
    analysis = await analysis_task

    # رسالة أولى ملخص
    await waiting.edit_text(
        f"✅ تم تجهيز البيانات لزوج `{symbol}`.\n"
        "⬇️ سيتم إرسال النتائج بالتفصيل.",
        parse_mode="Markdown",
    )

    # أولاً: التحليل
    if analysis:
        await update.message.reply_text(analysis, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❌ لم أتمكن من عمل تحليل آلى لهذا الزوج (مش موجود على Binance غالباً).",
            parse_mode="Markdown",
        )

    # ثانياً: الأفكار
    if ideas is None:
        await update.message.reply_text(
            "❌ حدث خطأ أثناء الاتصال بـ TradingView لجلب الأفكار.",
            parse_mode="Markdown",
        )
    elif not ideas:
        await update.message.reply_text(
            "ℹ️ لا يوجد أفكار متاحة حالياً لهذا الزوج على TradingView.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"💡 أفكار TradingView لزوج `{symbol}`:",
            parse_mode="Markdown",
        )
        for title, link in ideas:
            text = f"• *{title}*\n🔗 {link}"
            await update.message.reply_text(text, parse_mode="Markdown")


# لو المستخدم بعت رمز بس من غير أمر – نعامله كأمر /ideas
async def symbol_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    symbol = normalize_symbol(text)

    # لو مش حروف/أرقام معقولة، تجاهل
    if not symbol or len(symbol) < 3:
        return

    # نستخدم نفس منطق /ideas
    waiting = await update.message.reply_text(
        f"⏳ جارى جلب أفكار `{symbol}` من TradingView...",
        parse_mode="Markdown",
    )

    ideas = await fetch_ideas(symbol)
    if ideas is None:
        await waiting.edit_text(
            f"❌ حدث خطأ أثناء الاتصال بـ TradingView لزوج `{symbol}`.",
            parse_mode="Markdown",
        )
        return

    if not ideas:
        await waiting.edit_text(
            f"❌ لا يوجد أفكار متاحة حالياً لهذا الزوج `{symbol}` أو الرمز غير صحيح.",
            parse_mode="Markdown",
        )
        return

    await waiting.edit_text(
        f"✅ تم العثور على {len(ideas)} فكرة لزوج `{symbol}`.\n"
        "سيتم إرسالها فى رسائل منفصلة.",
        parse_mode="Markdown",
    )

    for title, link in ideas:
        text = f"💡 *{title}*\n🔗 {link}"
        await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- main ----------------
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("❌ BOT_TOKEN مفقود من الـ Environment Variables فى Koyeb.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_command))
    app.add_handler(CommandHandler("analysis", analysis_command))
    app.add_handler(CommandHandler("all", all_command))

    # أى رسالة نصية مش أمر -> نعتبرها رمز
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, symbol_message))

    logger.info("Bot is running in POLLING mode...")
    app.run_polling()


if __name__ == "__main__":
    main()
