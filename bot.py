import os
import time
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from utils.scraper import get_tv_ideas   # ← أهم تعديل

BOT_TOKEN = os.getenv("BOT_TOKEN")

# منع الاسبام – كل مستخدم لازم ينتظر 4 ثواني
last_call = {}

def rate_limit(user_id):
    now = time.time()
    if user_id in last_call and now - last_call[user_id] < 4:
        return False, int(4 - (now - last_call[user_id]))
    last_call[user_id] = now
    return True, 0


# /start
async def start(update, context):
    text = (
        "أهلاً 👋\n"
        "هذا البوت يجلب لك آخر أفكار TradingView لأي زوج كريبتو أو ذهب.\n\n"
        "استخدم مثلاً:\n"
        "/ideas BTCUSDT\n"
        "أو مباشرة:\n"
        "/BTCUSDT\n\n"
        "سيتم إرسال حتى 10 أفكار في رسائل منفصلة مع العنوان والرابط."
    )
    await update.message.reply_text(text)


# جلب الأفكار
async def ideas(update, context):
    user_id = update.message.from_user.id
    ok, wait_time = rate_limit(user_id)

    if not ok:
        await update.message.reply_text(f"⏳ من فضلك انتظر {wait_time} ثواني قبل طلب جديد 🙂")
        return

    if len(context.args) == 0:
        await update.message.reply_text("❗ مثال:\n/ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⏳ جاري جلب أفكار *{symbol}* من TradingView...", parse_mode="Markdown")

    ideas_list = get_tv_ideas(symbol)

    if not ideas_list:
        await update.message.reply_text("❌ لم يتم العثور على أفكار لهذا الزوج.")
        return

    for idea in ideas_list:
        msg = f"📌 *{idea['title']}*\n🔗 {idea['link']}"
        await update.message.reply_text(msg, parse_mode="Markdown")


# دعم الأوامر مثل /BTCUSDT
async def shortcut(update, context):
    symbol = update.message.text.replace("/", "").upper()

    await ideas(update, context)


# تشغيل البوت
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))
    app.add_handler(MessageHandler(filters.Regex(r"^/[A-Za-z0-9]+$"), shortcut))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
