import os
import logging
import requests
from bs4 import BeautifulSoup
from telegram.ext import Updater, CommandHandler

# ---------------- إعداد اللوج ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------- التوكن ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --------------------------------------------------------------------
#   جلب أفكار TradingView (Chart Ideas)
# --------------------------------------------------------------------

def fetch_tradingview(limit=5):
    url = "https://www.tradingview.com/ideas/cryptocurrency/"
    ideas = []

    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("div.tv-card-container")
        for card in cards[:limit]:
            title_tag = card.select_one("a.tv-widget-idea__title")
            desc_tag = card.select_one("p.tv-widget-idea__description-row")
            img_tag = card.select_one("img")

            title = title_tag.text.strip() if title_tag else "No Title"
            link = "https://www.tradingview.com" + title_tag["href"] if title_tag else ""
            desc = desc_tag.text.strip() if desc_tag else ""
            img = img_tag["src"] if img_tag else None

            ideas.append({
                "source": "TradingView",
                "title": title,
                "summary": desc,
                "url": link,
                "image": img
            })

    except Exception as e:
        logger.error(f"TradingView error: {e}")

    return ideas


# --------------------------------------------------------------------
#   إرسال نتائج TradingView
# --------------------------------------------------------------------

def send_idea(update, idea):
    chat_id = update.message.chat_id

    # لو فيه صورة – ابعتها
    if idea.get("image"):
        try:
            update.message.bot.send_photo(
                chat_id=chat_id,
                photo=idea["image"],
                caption=f"📊 {idea['title']}\n\n{idea['summary']}\n\n🔗 {idea['url']}"
            )
            return
        except Exception as e:
            logger.warning(f"Image send error: {e}")

    # لو الصورة فشلت أو مش موجودة
    update.message.reply_text(
        f"📊 *{idea['title']}*\n\n"
        f"{idea['summary']}\n\n"
        f"🔗 {idea['url']}",
        parse_mode="Markdown"
    )


# --------------------------------------------------------------------
#  أوامر البوت
# --------------------------------------------------------------------

def start_cmd(update, context):
    update.message.reply_text(
        "أهلاً بك 👋\n\n"
        "أنا بوت يجلب لك أحدث *تحليلات TradingView* فقط.\n\n"
        "استخدم:\n"
        "/ideas — لعرض أفضل 5 تحليلات الآن 🔥"
    )


def ideas_cmd(update, context):
    update.message.reply_text("⏳ جاري جمع أحدث تحليلات TradingView...")

    ideas = fetch_tradingview(limit=5)

    if not ideas:
        update.message.reply_text("⚠️ لا توجد بيانات من TradingView الآن.")
        return

    for idea in ideas:
        try:
            send_idea(update, idea)
        except Exception as e:
            logger.warning(f"Error sending idea: {e}")

    update.message.reply_text("⚠️ التحليلات ليست نصيحة استثمارية.")


# --------------------------------------------------------------------
#   MAIN
# --------------------------------------------------------------------

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
