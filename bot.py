import os
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests
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

# ---------------- توكن البوت ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var not set")

# ---------------- إعدادات TradingView ----------------
TV_BASE = "https://www.tradingview.com"
TV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0 Safari/537.36"
    )
}

# حالة كل شات (الزوج + الأفكار + رقم الفكرة الحالي)
user_state: Dict[int, Dict[str, Any]] = {}


# ---------- جلب اللينكات لكل الأفكار لزوج معيّن ----------
def fetch_symbol_ideas(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    يجلب قائمة أفكار لزوج معيّن من TradingView.
    مثال: https://www.tradingview.com/symbols/BTCUSDT/ideas/
    """
    url = f"{TV_BASE}/symbols/{symbol}/ideas/"
    logger.info("Fetching ideas page: %s", url)
    try:
        resp = requests.get(url, headers=TV_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Error fetching ideas page: %s", e)
        return []

    html = resp.text
    idea_paths: List[str] = []

    # نبحث عن لينكات /chart/xxxxx/slug/
    for match in re.finditer(r'href="(/chart/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/?)"', html):
        path = match.group(1)
        if path not in idea_paths:
            idea_paths.append(path)
        # ناخد شوية زيادة تحسّبًا لو بعض الصفحات فيها مشاكل
        if len(idea_paths) >= limit * 2:
            break

    ideas: List[Dict[str, Any]] = []
    for path in idea_paths:
        full_url = TV_BASE + path
        details = fetch_idea_details(full_url)
        if details:
            ideas.append(details)
        if len(ideas) >= limit:
            break

    return ideas


def _search_meta(content: str, prop: str) -> Optional[str]:
    """مساعدة: نقرأ meta property / name من الـ HTML"""
    # property="..."
    m = re.search(
        rf'<meta\s+[^>]*property=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
        content,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    # name="..."
    m = re.search(
        rf'<meta\s+[^>]*name=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
        content,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def fetch_idea_details(url: str) -> Optional[Dict[str, Any]]:
    """نجيب بيانات فكرة واحدة: العنوان + الصورة + وقت النشر + الكاتب"""
    logger.info("Fetching idea detail: %s", url)
    try:
        resp = requests.get(url, headers=TV_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Error fetching idea detail %s: %s", url, e)
        return None

    html = resp.text

    title = _search_meta(html, "og:title") or _search_meta(html, "twitter:title")
    image = _search_meta(html, "og:image") or _search_meta(html, "twitter:image")
    published_raw = (
        _search_meta(html, "article:published_time")
        or _search_meta(html, "publish_date")
        or ""
    )

    published_dt: Optional[datetime] = None
    if published_raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                published_dt = datetime.strptime(published_raw, fmt)
                break
            except Exception:
                continue

    author = _search_meta(html, "article:author") or ""

    if not title or not image:
        logger.warning("Idea %s missing title or image, skipping", url)
        return None

    return {
        "title": title,
        "image": image,
        "url": url,
        "author": author,
        "published_raw": published_raw,
        "published_dt": published_dt,
    }


# ---------- شكل الكابشن تحت الصورة ----------
def build_caption(symbol: str, idea: Dict[str, Any], index: int, total: int) -> str:
    lines = [f"*{idea['title']}*"]
    if idea.get("author"):
        lines.append(f"✍️ {idea['author']}")
    if idea.get("published_dt"):
        dt = idea["published_dt"].astimezone()
        lines.append("🕒 " + dt.strftime("%Y-%m-%d %H:%M"))
    elif idea.get("published_raw"):
        lines.append(f"🕒 {idea['published_raw']}")
    lines.append("")
    lines.append(f"رمز الزوج: `{symbol}`")
    lines.append(f"الفكرة رقم {index + 1} من {total}")
    lines.append("")
    lines.append(f"[فتح الفكرة على TradingView]({idea['url']})")
    lines.append("")
    lines.append("⚠️ هذه الأفكار من TradingView وليست نصيحة استثمارية.")
    return "\n".join(lines)


# ---------- إرسال / تحديث الكارد ----------
def send_idea(update: Update, context: CallbackContext, symbol: str, move: int = 0) -> None:
    chat_id = update.effective_chat.id
    state = user_state.get(chat_id)

    # أول مرة أو غيّرنا الزوج → نحمّل أفكار جديدة
    if state is None or state.get("symbol") != symbol or not state.get("ideas"):
        msg = update.effective_message.reply_text(
            f"⏳ جاري جلب أحدث أفكار TradingView لزوج `{symbol}` ...",
            parse_mode="Markdown",
        )
        ideas = fetch_symbol_ideas(symbol, limit=10)
        if not ideas:
            msg.edit_text(f"⚠️ لا توجد أفكار متاحة حالياً على TradingView لزوج `{symbol}`.")
            return
        state = {"symbol": symbol, "ideas": ideas, "index": 0, "message_id": None}
        user_state[chat_id] = state
    else:
        # تنقّل بين الأفكار
        state["index"] = (state["index"] + move) % len(state["ideas"])

    ideas = state["ideas"]
    idx = state["index"]
    idea = ideas[idx]
    caption = build_caption(symbol, idea, idx, len(ideas))

    keyboard = [
        [
            InlineKeyboardButton("⬅️ السابق", callback_data=f"prev|{symbol}"),
            InlineKeyboardButton(f"{idx + 1}/{len(ideas)}", callback_data="page"),
            InlineKeyboardButton("التالي ➡️", callback_data=f"next|{symbol}"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    bot: Bot = context.bot
    if state.get("message_id"):
        # نعدّل نفس الرسالة (الصورة + الكابشن + الأزرار)
        try:
            bot.edit_message_media(
                chat_id=chat_id,
                message_id=state["message_id"],
                media=InputMediaPhoto(idea["image"], caption=caption, parse_mode="Markdown"),
                reply_markup=markup,
            )
        except Exception as e:
            logger.warning("Failed to edit message media: %s", e)
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=state["message_id"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup,
            )
    else:
        msg = bot.send_photo(
            chat_id=chat_id,
            photo=idea["image"],
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup,
        )
        state["message_id"] = msg.message_id


# ---------- /start ----------
def start_cmd(update: Update, context: CallbackContext) -> None:
    text = (
        "أهلاً بك 👋\n\n"
        "هذا البوت يعرض لك *أفكار وتحليلات TradingView* لأي زوج كريبتو.\n\n"
        "اكتب اسم الزوج بهذا الشكل:\n"
        "`/BTCUSDT`\n"
        "`/ETHUSDT`\n"
        "`/SOLUSDT`\n"
        "وهكذا...\n\n"
        "سيتم جلب آخر الأفكار مع الصورة، ويمكنك التنقل بينها من خلال أزرار ⬅️ / ➡️.\n"
    )
    update.message.reply_text(text, parse_mode="Markdown")


# ---------- أي كوماند غير /start نعتبره زوج ----------
def generic_pair_cmd(update: Update, context: CallbackContext) -> None:
    cmd = update.message.text.strip()
    symbol = cmd[1:].upper()

    # لو حد كتب /start هنا بالغلط نطنّش
    if symbol in {"START", "HELP"}:
        return

    send_idea(update, context, symbol, move=0)


# ---------- أزرار ⬅️ / ➡️ ----------
def nav_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data or ""
    if data == "page":
        query.answer()
        return

    parts = data.split("|", 1)
    if len(parts) != 2:
        query.answer()
        return
    action, symbol = parts
    query.answer()

    dummy_update = Update(update.update_id, callback_query=query)
    if action == "next":
        send_idea(dummy_update, context, symbol, move=1)
    elif action == "prev":
        send_idea(dummy_update, context, symbol, move=-1)


# ---------- main ----------
def main() -> None:
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CallbackQueryHandler(nav_callback))
    # أي أمر /XXXX نعتبره زوج ونجلب له أفكار
    dp.add_handler(MessageHandler(Filters.command, generic_pair_cmd))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
