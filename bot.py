import os
import re
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import feedparser
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ---------------- إعداد اللوج ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------- التوكن ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var not set")

# حالة كل شات (الزوج + القائمة + رقم الفكرة الحالية + message_id)
user_state: Dict[int, Dict[str, Any]] = {}


# ---------- دوال مساعدة على RSS / النص ----------
def extract_image(summary_html: str) -> Optional[str]:
    """يحاول يجيب أول صورة من الـ <img src="..."> جوه الملخص"""
    if not summary_html:
        return None
    m = re.search(r'<img[^>]+src="([^"]+)"', summary_html)
    if m:
        return m.group(1)
    return None


def clean_html(text: str) -> str:
    """تنضيف HTML من النص"""
    if not text:
        return ""
    # إزالة التاجات
    text = re.sub(r"<.*?>", "", text)
    # شوية محارف معروفة
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return text.strip()


# ---------- جلب 20 فكرة من TradingView لزوج معين ----------
def fetch_symbol_ideas(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    يجلب حتى 20 فكرة من TradingView لزوج معيّن عن طريق RSS الرسمي:
    https://www.tradingview.com/ideas/{SYMBOL}/rss/
    """
    symbol = symbol.upper()
    url = f"https://www.tradingview.com/ideas/{symbol}/rss/"
    logger.info("Fetching TV RSS for %s: %s", symbol, url)

    feed = feedparser.parse(url)
    ideas: List[Dict[str, Any]] = []

    if not feed.entries:
        logger.warning("No entries in RSS for %s", symbol)
        return ideas

    for entry in feed.entries[:limit]:
        title = entry.get("title", "No title")
        summary_html = entry.get("summary", "") or entry.get("description", "")
        link = entry.get("link", "")
        # بعض الـ RSS فيها author
        author = getattr(entry, "author", "") or ""
        # وقت النشر
        pub_dt = None
        if getattr(entry, "published_parsed", None):
            pub_dt = datetime(*entry.published_parsed[:6])

        img = extract_image(summary_html)
        summary_clean = clean_html(summary_html)
        if len(summary_clean) > 260:
            summary_clean = summary_clean[:260] + "..."

        ideas.append(
            {
                "symbol": symbol,
                "title": title,
                "summary": summary_clean,
                "url": link,
                "author": author,
                "published_dt": pub_dt,
                "image": img,
            }
        )

    # ترتيب الأحدث أولاً
    ideas.sort(
        key=lambda x: x["published_dt"] if x["published_dt"] else datetime.min,
        reverse=True,
    )
    return ideas


# ---------- تجهيز الكابشن تحت الصورة ----------
def build_caption(idea: Dict[str, Any], index: int, total: int) -> str:
    lines = []
    lines.append(f"*{idea['title']}*")

    if idea.get("author"):
        lines.append(f"✍️ {idea['author']}")

    if idea.get("published_dt"):
        dt = idea["published_dt"]
        lines.append("🕒 " + dt.strftime("%Y-%m-%d %H:%M"))

    lines.append("")
    lines.append(f"زوج العملة: `{idea['symbol']}`")
    lines.append(f"الفكرة رقم {index + 1} من {total}")
    lines.append("")
    if idea["summary"]:
        lines.append("📝 " + idea["summary"])
        lines.append("")
    lines.append(f"[فتح الفكرة على TradingView]({idea['url']})")
    lines.append("")
    lines.append("⚠️ هذه الأفكار من TradingView وليست نصيحة استثمارية.")
    return "\n".join(lines)


def build_keyboard(symbol: str, index: int, total: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("⬅️ السابق", callback_data=f"prev|{symbol}"),
            InlineKeyboardButton(f"{index + 1}/{total}", callback_data="page"),
            InlineKeyboardButton("التالي ➡️", callback_data=f"next|{symbol}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------- إرسال أو تحديث الفكرة في الرسالة ----------
def show_idea(update: Update, context: CallbackContext, symbol: str, move: int = 0) -> None:
    chat_id = update.effective_chat.id
    state = user_state.get(chat_id)

    # أول مرة أو غيرنا الزوج → نجيب أفكار جديدة
    if state is None or state.get("symbol") != symbol or not state.get("ideas"):
        msg = update.effective_message.reply_text(
            f"⏳ جاري جلب أحدث 20 فكرة من TradingView لزوج `{symbol}` ...",
            parse_mode="Markdown",
        )
        ideas = fetch_symbol_ideas(symbol, limit=20)
        if not ideas:
            msg.edit_text(
                f"⚠️ لا توجد أفكار متاحة حالياً على TradingView لزوج `{symbol}`.",
                parse_mode="Markdown",
            )
            return
        state = {"symbol": symbol, "ideas": ideas, "index": 0, "message_id": None}
        user_state[chat_id] = state
    else:
        # التنقل بين الأفكار
        state["index"] = (state["index"] + move) % len(state["ideas"])

    ideas = state["ideas"]
    idx = state["index"]
    idea = ideas[idx]
    caption = build_caption(idea, idx, len(ideas))
    markup = build_keyboard(symbol, idx, len(ideas))

    bot: Bot = context.bot
    msg_id = state.get("message_id")
    if msg_id:
        # تحديث نفس الرسالة
        if idea["image"]:
            try:
                bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=msg_id,
                    media=InputMediaPhoto(idea["image"], caption=caption, parse_mode="Markdown"),
                    reply_markup=markup,
                )
            except Exception as e:
                logger.warning("edit_message_media failed: %s", e)
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=msg_id,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
        else:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup,
            )
    else:
        # أول إرسال
        if idea["image"]:
            msg = bot.send_photo(
                chat_id=chat_id,
                photo=idea["image"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        else:
            msg = bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        state["message_id"] = msg.message_id


# ---------- /start ----------
def start_cmd(update: Update, context: CallbackContext) -> None:
    text = (
        "أهلاً بك 👋\n\n"
        "هذا البوت يعرض لك *أفكار وتحليلات TradingView* لأي زوج كريبتو.\n\n"
        "اكتب اسم الزوج بهذا الشكل (كأمر):\n"
        "`/BTCUSDT`\n"
        "`/ETHUSDT`\n"
        "`/SOLUSDT`\n"
        "وهكذا...\n\n"
        "سيتم جلب آخر 20 فكرة (إن وجدت) مع الصورة + العنوان + الكاتب + الوقت،\n"
        "ويمكنك التنقل بينها من خلال أزرار ⬅️ السابق / التالي ➡️."
    )
    update.message.reply_text(text, parse_mode="Markdown")


# ---------- أي أمر /XXXX نعتبره زوج ----------
def pair_command(update: Update, context: CallbackContext) -> None:
    text = update.message.text.strip()
    # مثال: "/BTCUSDT" → "BTCUSDT"
    symbol = text[1:].upper()

    # لو حد كتب /start أو /help ما نعتبره رمز
    if symbol in {"START", "HELP"}:
        return

    show_idea(update, context, symbol, move=0)


# ---------- الكولباك بتاع الأزرار ----------
def nav_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data or ""
    query.answer()

    if data == "page":
        return

    parts = data.split("|", 1)
    if len(parts) != 2:
        return
    action, symbol = parts
    dummy_update = Update(update.update_id, callback_query=query)

    if action == "next":
        show_idea(dummy_update, context, symbol, move=1)
    elif action == "prev":
        show_idea(dummy_update, context, symbol, move=-1)


# ---------- main ----------
def main() -> None:
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CallbackQueryHandler(nav_callback))
    # أي أمر آخر غير /start نعتبره زوج مثل /BTCUSDT
    dp.add_handler(MessageHandler(Filters.command, pair_command))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
