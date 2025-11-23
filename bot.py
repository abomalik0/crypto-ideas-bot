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

# ---------------- دوال جلب أفكار TradingView فقط ----------------

def parse_rss(url, source_name, limit=3):
    """
    يقرأ RSS منTradingView  ويرجع list فيها الأفكار
    """
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


def fetch_tradingview_ideas():
    """
    نجمع أفكار / chart ideas من TradingView بس
    تقدر تزود أو تعدل اللينكات تحت لو حابب عملات معينة
    """
    items = []

    tv_feeds = {
        "TradingView BTC": "https://www.tradingview.com/ideas/bitcoin/rss/",
        "TradingView ETH": "https://www.tradingview.com/ideas/ethereum/rss/",
        # لو عايز تضيف عملات تانية:
        # "TradingView XRP": "https://www.tradingview.com/ideas/xrp/rss/",
    }

    for name, url in tv_feeds.items():
        try:
            items.extend(parse_rss(url, name, limit=3))
        except Exception as e:
            logger.warning(f"TradingView RSS error for {name}: {e}")

    return items


def build_ideas_message(items, limit=5):
    """
    يجهز رسالة تيليجرام من أفكار TradingView
    """
    items_with_dt = [i for i in items if i.get("published_dt")]
    items_without_dt = [i for i in items if not i.get("published_dt")]

    items_with_dt.sort(key=lambda x: x["published_dt"], reverse=True)
    ordered = items_with_dt + items_without_dt
    ordered = ordered[:limit]

    if not ordered:
        return "لا توجد أفكار متاحة الآن من TradingView، حاول مرة أخرى لاحقاً."

    lines = ["📊 *أحدث أفكار وتحليلات TradingView (Chart Ideas):*", ""]
    for idx, it in enumerate(ordered, start=1):
        title = it["title"]
        src = it["source"]
        url = it["url"]
        published = it.get("published_dt") or it.get("published") or ""
        if isinstance(published, datetime):
            published_str = published.strftime("%Y-%m-%d %H:%M")
        else:
            published_str = str(published)[:19]

        summary = it.get("summary", "")
        if summary:
            summary_clean = (
                summary.replace("<p>", "")
                .replace("</p>", "")
                .replace("<br>", " ")
                .replace("<br/>", " ")
            )
            if len(summary_clean) > 220:
                summary_clean = summary_clean[:220] + "..."
        else:
            summary_clean = ""

        block = f"{idx}. *{title}*\n" \
                f"📍 المصدر: _{src}_\n" \
                f"🕒 {published_str}\n"
        if summary_clean:
            block += f"📝 {summary_clean}\n"
        block += f"🔗 {url}\n"
        lines.append(block)

    lines.append("\n⚠️ هذه التحليلات للمعلومات فقط وليست نصيحة استثمارية.")
    return "\n".join(lines)


# ---------------- أوامر البوت ----------------

def start_cmd(update, context):
    text = (
        "أهلاً بك 👋\n\n"
        "أنا بوت يعرض لك أفكار وتحليلات الكريبتو من TradingView (Chart Ideas).\n\n"
        "الأوامر المتاحة:\n"
        "/ideas - عرض أحدث أفكار TradingView على عملات مثل BTC و ETH.\n"
        "\nالبوت يستخدم روابط علنية من TradingView فقط، وليست نصيحة استثمارية."
    )
    update.message.reply_text(text)


def ideas_cmd(update, context):
    chat_id = update.message.chat_id
    msg = update.message.reply_text("⏳ جاري جمع أحدث أفكار TradingView...")

    tv_items = fetch_tradingview_ideas()
    text = build_ideas_message(tv_items, limit=5)

    try:
        # نخلي Telegram يعمل preview للصورة من لينك TradingView
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )
    except Exception as e:
        logger.warning(f"Edit message error: {e}")
        update.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=False,
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
