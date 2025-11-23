import os
import re
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

# ---------------- توابع مساعدة ----------------

def extract_img_url(summary_html: str):
    """
    تحاول تلتقط أول صورة <img> من الملخص (لو موجودة)
    عشان نستخدمها كصورة للرسالة في تيليجرام.
    """
    if not summary_html:
        return None
    match = re.search(r'<img[^>]+src="([^"]+)"', summary_html)
    if match:
        return match.group(1)
    return None


def clean_html(raw_html: str) -> str:
    """إزالة التاجات HTML من النص."""
    if not raw_html:
        return ""
    # إزالة التاجات
    text = re.sub(r"<.*?>", "", raw_html)
    # شوية وحدات مشهورة
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return text.strip()


# ---------------- دوال جلب الأخبار والأفكار ----------------

def parse_rss(url, source_name, limit=3):
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

        image_url = extract_img_url(summary)

        items.append(
            {
                "source": source_name,
                "title": title,
                "summary_html": summary,
                "summary": clean_html(summary),
                "url": link,
                "published": published,
                "published_dt": pub_dt,
                "image_url": image_url,
            }
        )
    return items


def fetch_tradingview_ideas():
    """
    نجمع أفكار من TradingView على عملات مختلفة.
    (اللينكات دي بتعتمد على وجود RSS عند TradingView،
     لو واحد منهم عمل مشكلة ممكن تشيله عادي)
    """
    items = []
    tv_feeds = {
        "TradingView BTC": "https://www.tradingview.com/ideas/bitcoin/rss/",
        "TradingView ETH": "https://www.tradingview.com/ideas/ethereum/rss/",
        # لو حابب تسيبهم أو تجربهم:
        # "TradingView Crypto": "https://www.tradingview.com/ideas/crypto/rss/",
        # "TradingView Altcoins": "https://www.tradingview.com/ideas/altcoin/rss/",
    }
    for name, url in tv_feeds.items():
        try:
            items.extend(parse_rss(url, name, limit=3))
        except Exception as e:
            logger.warning(f"TradingView feed error [{name}]: {e}")
    return items


def fetch_news_sources():
    sources = {
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "NewsBTC": "https://www.newsbtc.com/feed/",
    }
    items = []
    for name, url in sources.items():
        try:
            items.extend(parse_rss(url, name, limit=2))
        except Exception as e:
            logger.warning(f"News feed error [{name}]: {e}")
    return items


def sort_and_pick(items, limit=5):
    """
    ترتيب كل العناصر حسب التاريخ (الأحدث أولاً)
    وأخذ أول limit عنصر.
    """
    items_with_dt = [i for i in items if i.get("published_dt")]
    items_without_dt = [i for i in items if not i.get("published_dt")]

    items_with_dt.sort(key=lambda x: x["published_dt"], reverse=True)
    ordered = items_with_dt + items_without_dt
    return ordered[:limit]


def format_idea_caption(it, idx=None):
    """
    تجهيز الكابشن اللي هينزل تحت الصورة في تيليجرام.
    """
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
        if len(summary) > 220:
            summary = summary[:220] + "..."

    index_prefix = f"{idx}. " if idx is not None else ""

    caption = f"{index_prefix}*{title}*\n" \
              f"📍 المصدر: _{src}_\n" \
              f"🕒 {published_str}\n"
    if summary:
        caption += f"📝 {summary}\n"
    caption += f"🔗 {url}\n"
    caption += "\n⚠️ هذه الأخبار والتحليلات للمعلومات فقط وليست نصيحة استثمارية."
    return caption


# ---------------- أوامر البوت ----------------

def start_cmd(update, context):
    text = (
        "أهلاً بك 👋\n\n"
        "أنا بوت يجمع لك أهم أفكار وتحليلات الكريبتو (TradingView + أخبار كريبتو).\n\n"
        "الأوامر المتاحة:\n"
        "/ideas - عرض أحدث الأفكار والتحليلات بشكل بطاقات (صورة + عنوان).\n"
        "\nالبوت يعمل على بيانات علنية (RSS) فقط، وليس نصيحة استثمارية."
    )
    update.message.reply_text(text)


def ideas_cmd(update, context):
    chat_id = update.message.chat_id
    waiting_msg = update.message.reply_text("⏳ جاري جمع أحدث الأفكار والتحليلات...")

    all_items = []

    # أولاً: نحاول نجيب أفكار TradingView
    try:
        all_items.extend(fetch_tradingview_ideas())
    except Exception as e:
        logger.warning(f"TradingView error: {e}")

    # ثانياً: نضيف أخبار الكريبتو لو حابب يبقى في خليط
    try:
        all_items.extend(fetch_news_sources())
    except Exception as e:
        logger.warning(f"News sources error: {e}")

    if not all_items:
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting_msg.message_id,
            text="❌ لم أستطع جلب أفكار أو أخبار حالياً، حاول مرة أخرى لاحقاً.",
        )
        return

    top_items = sort_and_pick(all_items, limit=5)

    # نمسح رسالة الانتظار
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=waiting_msg.message_id)
    except Exception:
        pass

    # نرسل كل فكرة في رسالة منفصلة (صورة + كابشن) زي ما تحب
    for idx, it in enumerate(top_items, start=1):
        caption = format_idea_caption(it, idx=idx)
        image_url = it.get("image_url")

        try:
            if image_url:
                # لو فيه صورة في الـ RSS نستخدمها
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            else:
                # لو مفيش صورة نبعت الرسالة نص فقط
                context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    disable_web_page_preview=False,
                )
        except Exception as e:
            logger.warning(f"Error sending idea #{idx}: {e}")


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
