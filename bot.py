import os
import logging
import feedparser
from datetime import datetime
from telegram.ext import Updater, CommandHandler

# ---------------- إعداد اللوج ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------- إعداد التوكن ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ---------------- جلب أفكار TradingView فقط ----------------

def parse_rss(url, source_name, limit=5):
    feed = feedparser.parse(url)
    items = []

    for entry in feed.entries[:limit]:
        title = entry.get("title", "No title")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        published = entry.get("published", "")

        pub_dt = None
        if "published_parsed" in entry and entry.published_parsed:
            pub_dt = datetime(*entry.published_parsed[:6])

        items.append(
            {
                "source": source_name,
                "title": title,
                "summary": summary,
                "url": link,
                "published": published,
                "published_dt": pub_dt,
            }
        )

    return items


def fetch_tradingview_only():
    sources = {
        "TradingView BTC": "https://www.tradingview.com/ideas/bitcoin/rss/",
        "TradingView ETH": "https://www.tradingview.com/ideas/ethereum/rss/",
        "TradingView XRP": "https://www.tradingview.com/ideas/xrp/rss/",
        "TradingView SOL": "https://www.tradingview.com/ideas/solana/rss/",
    }

    items = []
    for name, url in sources.items():
        try:
            items.extend(parse_rss(url, name, limit=3))
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")

    return items


def build_tv_message(items):
    if not items:
        return "⚠️ لا توجد أفكار من TradingView حاليًا."

    # ترتيب حسب التاريخ
    items = sorted(
        items,
        key=lambda x: x.get("published_dt") or datetime.min,
        reverse=True
    )

    lines = ["📊 *أحدث أفكار TradingView:*", ""]

    for idx, it in enumerate(items[:5], start=1):
        title = it["title"]
        src = it["source"]
        url = it["url"]

        pub = it.get("published_dt")
        if pub:
            pub = pub.strftime("%Y-%m-%d %H:%M")
        else:
            pub = it.get("published", "")

        summary = it.get("summary", "")
        summary = summary.replace("<p>", "").replace("</p>", "")

        if len(summary) > 200:
            summary = summary[:200] + "..."

        block = (
            f"{idx}. *{title}*\n"
            f"📍 _{src}_\n"
            f"🕒 {pub}\n"
            f"📝 {summary}\n"
            f"🔗 {url}\n"
        )
        lines.append(block)

    return "\n".join(lines)


# ---------------- أوامر Telegram ----------------

def start_cmd(update, context):
    update.message.reply_text(
        "👋 أهلاً بك!\n"
        "هذا البوت يعرض أحدث *أفكار وتحليلات TradingView* فقط.\n\n"
        "استخدم:\n/ideas – للحصول على آخر الأفكار."
    )


def ideas_cmd(update, context):
    msg = update.message.reply_text("⏳ جاري جلب أحدث أفكار TradingView...")

    items = fetch_tradingview_only()
    text = build_tv_message(items)

    context.bot.edit_message_text(
        chat_id=update.message.chat_id,
        message_id=msg.message_id,
        text=text,
        parse_mode="Markdown",
    )


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
