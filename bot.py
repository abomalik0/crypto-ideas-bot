import os
import logging
import re
from datetime import datetime

import feedparser
import requests
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
)

# ---------------- الإعدادات العامة ----------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# عدد الأفكار لكل طلب
MAX_IDEAS_PER_PAIR = 20

# ماب بين الأزواج و الـ RSS في TradingView
PAIR_FEEDS = {
    "BTCUSDT": [
        "https://www.tradingview.com/ideas/bitcoin/rss/",
        "https://www.tradingview.com/ideas/btcusd/rss/",
    ],
    "ETHUSDT": [
        "https://www.tradingview.com/ideas/ethereum/rss/",
        "https://www.tradingview.com/ideas/ethusd/rss/",
    ],
    "BNBUSDT": [
        "https://www.tradingview.com/ideas/bnbusdt/rss/",
        "https://www.tradingview.com/ideas/binancecoin/rss/",
    ],
    "SOLUSDT": [
        "https://www.tradingview.com/ideas/solusdt/rss/",
        "https://www.tradingview.com/ideas/solana/rss/",
    ],
    "XRPUSDT": [
        "https://www.tradingview.com/ideas/xrpusdt/rss/",
        "https://www.tradingview.com/ideas/ripple/rss/",
    ],
}


# ---------------- دوال TradingView ----------------


def fetch_tv_ideas_for_pair(pair: str, max_ideas: int = MAX_IDEAS_PER_PAIR):
    """
    يرجّع ليست بالأفكار (entries) من TradingView لزوج معين.
    نعتمد على RSS لأكثر من فيد لكل زوج، ونجمعهم ونرتّبهم بالأحدث.
    """
    urls = PAIR_FEEDS.get(pair.upper(), [])
    if not urls:
        return []

    all_entries = []

    headers = {
        # User-Agent عادي عشان TradingView ما يرفضش الطلبات
        "User-Agent": "Mozilla/5.0 (compatible; CryptoIdeasBot/1.0)",
    }

    for url in urls:
        try:
            logger.info("Fetching TV RSS for %s: %s", pair, url)
            resp = requests.get(url, timeout=15, headers=headers)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            logger.error("TV Fetch Error for %s from %s: %s", pair, url, e)
            continue

        if not feed.entries:
            logger.warning("No entries in RSS for %s from %s", pair, url)
            continue

        all_entries.extend(feed.entries)

    # مفيش أي حاجة
    if not all_entries:
        return []

    # إزالة التكرار باللينك
    unique_entries = []
    seen_links = set()
    for e in all_entries:
        link = e.get("link", "")
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        unique_entries.append(e)

    # ترتيب حسب التاريخ
    with_dt = []
    without_dt = []
    for e in unique_entries:
        published_dt = None
        if getattr(e, "published_parsed", None):
            published_dt = datetime(*e.published_parsed[:6])
        if published_dt:
            with_dt.append((published_dt, e))
        else:
            without_dt.append((None, e))

    with_dt.sort(key=lambda x: x[0], reverse=True)
    ordered = [e for _, e in with_dt] + [e for _, e in without_dt]

    return ordered[:max_ideas]


def extract_image_from_entry(entry) -> str:
    """
    نحاول نطلع صورة الفكرة من الـ summary أو أي ميديا في الفيد.
    """
    # من media_content إن وجدت
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if media and isinstance(media, list):
        url = media[0].get("url")
        if url:
            return url

    summary = entry.get("summary", "") or entry.get("description", "")
    if summary:
        m = re.search(r'<img[^>]+src="([^"]+)"', summary)
        if m:
            return m.group(1)

    return ""


def build_caption(pair: str, idx: int, entry) -> str:
    title = entry.get("title", "No title")
    link = entry.get("link", "")
    author = entry.get("author", "")
    published_str = ""

    if getattr(entry, "published_parsed", None):
        dt = datetime(*entry.published_parsed[:6])
        published_str = dt.strftime("%Y-%m-%d %H:%M")
    else:
        published_str = (entry.get("published") or "")[:19]

    caption_lines = [
        f"*{pair} — Idea #{idx}*",
        f"*{title}*",
    ]

    if author:
        caption_lines.append(f"✍️ {author}")
    if published_str:
        caption_lines.append(f"🕒 {published_str}")

    if link:
        caption_lines.append(f"\n[فتح الفكرة على TradingView]({link})")

    caption_lines.append(
        "\n⚠️ هذه الأفكار والتحليلات للمعلومات فقط وليست نصيحة استثمارية."
    )

    return "\n".join(caption_lines)


# ---------------- أوامر البوت ----------------


def start_cmd(update, context):
    text = (
        "أهلاً بك 👋\n\n"
        "هذا البوت يعرض لك *أفكار وتحليلات TradingView* لعدة أزواج كريبتو.\n\n"
        "اكتب اسم الزوج على شكل أمر، مثلاً:\n"
        "`/BTCUSDT`\n"
        "`/ETHUSDT`\n"
        "`/BNBUSDT`\n"
        "`/SOLUSDT`\n"
        "`/XRPUSDT`\n\n"
        "وسيتم عرض آخر الأفكار المتاحة (حتى 20 فكرة) مع الصورة والرابط.\n"
        "كل ما عليك إنك تكتب الأمر فقط 👇"
    )
    update.message.reply_text(text, parse_mode="Markdown")


def pair_ideas_cmd(update, context):
    """
    أي أمر غير معروف هنعتبره اسم زوج: /BTCUSDT مثلاً.
    """
    text = (update.message.text or "").strip()
    if not text.startswith("/"):
        return

    command = text[1:]  # شيل /
    pair = command.upper()

    if pair not in PAIR_FEEDS:
        supported = ", ".join(f"/{p}" for p in PAIR_FEEDS.keys())
        update.message.reply_text(
            "❌ الزوج غير مدعوم حالياً.\n"
            f"الأزواج المتاحة:\n{supported}"
        )
        return

    chat_id = update.message.chat_id
    waiting_msg = update.message.reply_text(
        f"⏳ جاري جلب أحدث أفكار TradingView لزوج {pair}..."
    )

    try:
        ideas = fetch_tv_ideas_for_pair(pair)
    except Exception as e:
        logger.exception("Unexpected error while fetching ideas for %s: %s", pair, e)
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting_msg.message_id,
            text="❌ حدث خطأ أثناء جلب الأفكار من TradingView، حاول مرة أخرى لاحقاً.",
        )
        return

    if not ideas:
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting_msg.message_id,
            text=f"⚠️ لا توجد أفكار متاحة حالياً على TradingView لزوج {pair}.",
        )
        return

    # عدّل رسالة الانتظار
    context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=waiting_msg.message_id,
        text=f"✅ تم جلب {len(ideas)} فكرة من TradingView لزوج {pair}.",
    )

    # ابعت كل فكرة كصورة + كابشن
    for idx, entry in enumerate(ideas, start=1):
        try:
            photo_url = extract_image_from_entry(entry)
            caption = build_caption(pair, idx, entry)

            if photo_url:
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption,
                    parse_mode="Markdown",
                )
            else:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.warning("Error sending idea #%s for %s: %s", idx, pair, e)


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN env var not set")

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # /start
    dp.add_handler(CommandHandler("start", start_cmd))

    # أي أمر تاني هنعتبره اسم زوج
    dp.add_handler(MessageHandler(Filters.command, pair_ideas_cmd))

    logger.info("Bot is starting polling...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
