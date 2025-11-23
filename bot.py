import os
import logging
import requests
from datetime import datetime
from telegram.ext import Updater, CommandHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# API غير رسمي داخل TradingView (يستخدمه الموقع نفسه)
TV_API = "https://www.tradingview.com/ideas-page/?page=1"

def fetch_tv_ideas(limit=5):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tradingview.com/ideas/"
        }
        r = requests.get("https://www.tradingview.com/ideas/", headers=headers)
        if r.status_code != 200:
            return []

        # الأفكار داخل الـ HTML كـ JSON داخل window.__INITIAL_STATE__
        import re, json
        match = re.search(r"\"ideas\":({.*?\"authors\"", r.text)
        if not match:
            return []

        json_data = json.loads(match.group(1)[:-10] + "}")

        ideas = json_data.get("results", [])[:limit]
        return ideas
    except Exception as e:
        logger.error(f"TV Fetch Error: {e}")
        return []

def format_tv_message(idea):
    title = idea.get("title", "")
    desc = idea.get("description", "")
    author = idea.get("author_username", "")
    img = idea.get("thumb_url", "")
    url = "https://www.tradingview.com" + idea.get("short_url", "")
    time = datetime.fromtimestamp(idea.get("published_timestamp")).strftime("%Y-%m-%d %H:%M")

    msg = f"📊 *{title}*\n"
    msg += f"✍️ المحلل: _{author}_\n"
    msg += f"🕒 {time}\n"
    if desc:
        msg += f"📝 {desc[:250]}...\n"
    msg += f"🔗 {url}\n"

    return msg, img

def ideas_cmd(update, context):
    chat_id = update.message.chat_id
    msg = update.message.reply_text("⏳ جاري جلب أحدث أفكار TradingView...")

    ideas = fetch_tv_ideas(limit=5)
    if not ideas:
        update.message.reply_text("⚠ لا يوجد أفكار حالياً.")
        return

    for idea in ideas:
        message, photo = format_tv_message(idea)
        if photo:
            context.bot.send_photo(chat_id=chat_id, photo=photo, caption=message, parse_mode="Markdown")
        else:
            context.bot.send_message(chat_id, message, parse_mode="Markdown")

    context.bot.delete_message(chat_id, msg.message_id)

def start_cmd(update, context):
    update.message.reply_text("أهلاً 👋\nاستخدم /ideas لعرض أحدث أفكار TradingView.")

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN env var not set")

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("ideas", ideas_cmd))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
