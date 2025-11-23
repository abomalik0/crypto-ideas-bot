import os
import logging
from typing import Dict, Any, List

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

# ---------------- الأفكار (تحط تحليلاتك هنا) ----------------
# تقدر تزود أو تعدل أو تشيل برحتك.
# لو مش عايز صورة، سيب image="" أو امسح السطر، وهيبعت نص بس.
IDEAS: Dict[str, List[Dict[str, Any]]] = {
    "BTCUSDT": [
        {
            "title": "BTC Weekly Key Levels",
            "author": "PUT_AUTHOR_NAME",
            "time": "2025-11-23 13:19",
            "url": "https://www.tradingview.com/chart/BTCUSDT/dNUoRrVU-BTC-Weekly-Key-Levels/",
            "image": "",  # حط هنا رابط صورة التحليل لو عايز
        },
        {
            "title": "Saylor's Master Plan at Risk - MSCI Drops the Hammer",
            "author": "PUT_AUTHOR_NAME",
            "time": "2025-11-23 12:00",
            "url": "https://www.tradingview.com/chart/BTCUSDT.P/fmpxEOpu-Saylor-s-Master-Plan-at-Risk-MSCI-Drops-the-Hammer/",
            "image": "",  # مثال للتحليل اللي انت بعت لي لينكه
        },
        # تقدر تضيف لحد 20 أو 50 فكرة زي ما تحب
    ],

    # مثال لزوج تاني، لو مش محتاجه امسحه
    "ETHUSDT": [
        {
            "title": "ETH Key Resistance & Support",
            "author": "Some_Trader",
            "time": "2025-11-20 09:30",
            "url": "https://www.tradingview.com/chart/ETHUSDT/PUT_ID_HERE/",
            "image": "",
        }
    ],
}

# حالة كل شات (الزوج + رقم الفكرة الحالية + message_id)
USER_STATE: Dict[int, Dict[str, Any]] = {}


def build_caption(symbol: str, idea: Dict[str, Any], index: int, total: int) -> str:
    """يبني الكابشن تحت الصورة/الرسالة."""
    lines = []
    lines.append(f"*{idea.get('title', 'بدون عنوان')}*")
    if idea.get("author"):
        lines.append(f"✍️ {idea['author']}")
    if idea.get("time"):
        lines.append(f"🕒 {idea['time']}")

    lines.append("")
    lines.append(f"زوج العملة: `{symbol}`")
    lines.append(f"الفكرة رقم {index + 1} من {total}")
    lines.append("")

    if idea.get("url"):
        lines.append(f"[فتح الفكرة على TradingView]({idea['url']})")
        lines.append("")

    lines.append("⚠️ هذه التحليلات للمعلومات فقط وليست نصيحة استثمارية.")
    return "\n".join(lines)


def build_keyboard(symbol: str, index: int, total: int) -> InlineKeyboardMarkup:
    """يبني الكيبورد (الأزرار) تحت الرسالة."""
    keyboard = [
        [
            InlineKeyboardButton("⬅️ السابق", callback_data=f"prev|{symbol}"),
            InlineKeyboardButton(f"{index + 1}/{total}", callback_data="page"),
            InlineKeyboardButton("التالي ➡️", callback_data=f"next|{symbol}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def show_idea_for_chat(chat_id: int, context: CallbackContext, move: int = 0) -> None:
    """يعدل الرسالة الحالية ويعرض الفكرة المناسبة حسب move (التالي/السابق)."""
    state = USER_STATE.get(chat_id)
    if not state:
        return

    symbol = state["symbol"]
    ideas = state["ideas"]
    if not ideas:
        return

    # تحديث رقم الفكرة
    state["index"] = (state["index"] + move) % len(ideas)
    idx = state["index"]
    idea = ideas[idx]

    caption = build_caption(symbol, idea, idx, len(ideas))
    markup = build_keyboard(symbol, idx, len(ideas))

    bot: Bot = context.bot
    msg_id = state.get("message_id")

    # لو في صورة
    image_url = idea.get("image") or ""

    if msg_id:
        if image_url:
            try:
                bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=msg_id,
                    media=InputMediaPhoto(image_url, caption=caption, parse_mode="Markdown"),
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
            # مفيش صورة، نعدل الكابشن/النص فقط
            try:
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=msg_id,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
            except Exception:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=caption,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )


def send_first_idea(update: Update, context: CallbackContext, symbol: str) -> None:
    """إرسال أول فكرة لزوج معيّن."""
    chat_id = update.effective_chat.id
    ideas = IDEAS.get(symbol.upper(), [])

    if not ideas:
        update.message.reply_text(
            f"⚠️ لا توجد أفكار محفوظة حالياً لزوج `{symbol}`.\n"
            f"يمكنك إضافتها داخل الكود في قاموس IDEAS.",
            parse_mode="Markdown",
        )
        return

    USER_STATE[chat_id] = {
        "symbol": symbol,
        "ideas": ideas,
        "index": 0,
        "message_id": None,
    }

    idx = 0
    idea = ideas[idx]
    caption = build_caption(symbol, idea, idx, len(ideas))
    markup = build_keyboard(symbol, idx, len(ideas))

    image_url = idea.get("image") or ""

    if image_url:
        msg = update.message.reply_photo(
            photo=image_url,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup,
        )
    else:
        msg = update.message.reply_text(
            text=caption,
            parse_mode="Markdown",
            reply_markup=markup,
        )

    USER_STATE[chat_id]["message_id"] = msg.message_id


# ---------- أوامر البوت ----------

def start_cmd(update: Update, context: CallbackContext) -> None:
    supported_pairs = ", ".join(f"/{p}" for p in IDEAS.keys())
    text = (
        "أهلاً بك 👋\n\n"
        "هذا البوت يعرض *تحليلات TradingView محفوظة يدويًا* لكل زوج.\n\n"
        "الأزواج المتاحة حالياً:\n"
        f"{supported_pairs}\n\n"
        "مثال:\n"
        "/BTCUSDT\n"
        "/ETHUSDT\n\n"
        "يمكنك تعديل قائمة التحليلات من داخل الكود (قاموس IDEAS)."
    )
    update.message.reply_text(text, parse_mode="Markdown")


def pair_cmd(update: Update, context: CallbackContext) -> None:
    """أي أمر /XXXX نعتبره زوج ونشوف له أفكار في IDEAS."""
    text = (update.message.text or "").strip()
    if not text.startswith("/"):
        return

    cmd = text[1:].upper()  # "/BTCUSDT" -> "BTCUSDT"

    if cmd in {"START", "HELP"}:
        return

    if cmd not in IDEAS:
        supported_pairs = ", ".join(f"/{p}" for p in IDEAS.keys())
        update.message.reply_text(
            "❌ هذا الزوج غير مضاف حالياً في البوت.\n"
            "الأزواج المتاحة:\n"
            f"{supported_pairs}\n\n"
            "لو حابب تضيفه، عدّل قاموس IDEAS في bot.py.",
            parse_mode="Markdown",
        )
        return

    send_first_idea(update, context, cmd)


def nav_callback(update: Update, context: CallbackContext) -> None:
    """التعامل مع أزرار ⬅️ السابق / التالي ➡️."""
    query = update.callback_query
    data = query.data or ""
    chat_id = query.message.chat_id

    if data == "page":
        query.answer()
        return

    parts = data.split("|", 1)
    if len(parts) != 2:
        query.answer()
        return

    action, symbol = parts
    query.answer()

    if action == "next":
        show_idea_for_chat(chat_id, context, move=1)
    elif action == "prev":
        show_idea_for_chat(chat_id, context, move=-1)


def main() -> None:
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CallbackQueryHandler(nav_callback))
    dp.add_handler(MessageHandler(Filters.command, pair_cmd))

    logger.info("Bot started. Polling updates...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
