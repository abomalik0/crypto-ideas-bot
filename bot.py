import os
import feedparser
from telegram.ext import Application, CommandHandler, MessageHandler, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

def get_ideas(symbol):
    url = f"https://www.tradingview.com/ideas/{symbol}/rss/"
    feed = feedparser.parse(url)

    ideas = []
    for entry in feed.entries[:10]:
        ideas.append({
            "title": entry.title,
            "link": entry.link
        })
    return ideas


async def start(update, context):
    text = (
        "👋 أهلاً!\n"
        "هذا البوت يجلب لك آخر أفكار TradingView.\n\n"
        "استخدم مثلاً:\n"
        "/ideas BTCUSDT\n"
        "أو مباشرة:\n"
        "/BTCUSDT"
    )
    await update.message.reply_text(text)


async def ideas_cmd(update, context):
    if len(context.args) == 0:
        await update.message.reply_text("❗ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol}...")

    ideas = get_ideas(symbol)

    if not ideas:
        await update.message.reply_text("❌ لا توجد أفكار متاحة حالياً.")
        return

    for idea in ideas:
        msg = f"📌 *{idea['title']}*\n🔗 {idea['link']}"
        await update.message.reply_text(msg, parse_mode="Markdown")


async def shortcut(update, context):
    symbol = update.message.text.replace("/", "").upper()
    context.args = [symbol]
    await ideas_cmd(update, context)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"/[A-Za-z0-9]+"), shortcut))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
