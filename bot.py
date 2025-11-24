import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from scraper import get_ideas

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing!")


WELCOME = (
    "أهلاً 👋\n"
    "استخدم:\n"
    "/ideas BTCUSDT\n"
    "أو مباشرة:\n"
    "/BTCUSDT"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


def extract_symbol(text: str):
    if text.startswith("/ideas"):
        parts = text.split()
        return parts[1].upper() if len(parts) > 1 else None
    if text.startswith("/"):
        return text[1:].upper()
    return None


async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    symbol = extract_symbol(txt)

    if not symbol:
        await update.message.reply_text("اكتب: /ideas BTCUSDT")
        return

    loading = await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} ...")

    ideas = await get_ideas(symbol)

    if not ideas:
        await loading.edit_text(f"❌ لا يوجد أفكار حالياً لـ {symbol}")
        return

    await loading.delete()

    for idea in ideas:
        caption = f"{idea['title']}\n\n🔗 {idea['link']}"
        if idea["image"]:
            try:
                await update.message.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=idea["image"],
                    caption=caption
                )
                continue
            except:
                pass

        await update.message.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption
        )


async def shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ideas_cmd(update, context)


async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^/[A-Za-z0-9]+$"), shortcut))

    logger.info("Starting bot...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
