import os
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests
from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ ERROR: BOT_TOKEN env var not set")

# ---------------- إعداد TradingView ----------------
TV_BASE = "https://www.tradingview.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0 Safari/537.36"
    )
}

# --------- دوال مساعدة لاستخراج الميتا من HTML ---------
def find_meta(html: str, key: str) -> Optional[str]:
    """
    يحاول يلاقي <meta property="..." content="..."> أو name="..."
    ويرجع قيمة content.
    """
    # property=...
    pattern_prop = rf'<meta\s+[^>]*property=["\']{re.escape(key)}["\'][^>]*content=["\']([^"\']+)["\']'
    m = re.search(pattern_prop, html, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    # name=...
    pattern_name = rf'<meta\s+[^>]*name=["\']{re.escape(key)}["\'][^>]*content=["\']([^"\']+)["\']'
    m = re.search(pattern_name, html, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    return None


# --------- جلب تفاصيل فكرة واحدة من صفحة /chart/... ---------
def fetch_idea_details(url: str) -> Optional[Dict[str, Any]]:
    """
    يأخذ لينك فكرة TradingView (chart/...) ويرجع:
    العنوان، الصورة، الكاتب، وقت النشر، الرابط.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Error fetching idea detail %s: %s", url, e)
        return None

    html = resp.text

    title = (
        find_meta(html, "og:title")
        or find_meta(html, "twitter:title")
        or "No title"
    )
    image = find_meta(html, "og:image") or find_meta(html, "twitter:image") or ""
    author = find_meta(html, "article:author") or ""
    published_raw = (
        find_meta(html, "article:published_time")
        or find_meta(html, "publish_date")
        or ""
    )

    published_dt = None
    if published_raw:
        # نحاول أكثر من فورمات للتايم
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                published_dt = datetime.strptime(published_raw, fmt)
                break
            except Exception:
                continue

    if not image:
        logger.info("No image in idea %s", url)

    return {
        "title": title,
        "image": image,
        "author": author,
        "published_raw": published_raw,
        "published_dt": published_dt,
        "url": url,
    }


# --------- جلب أفكار من صفحة Chart Ideas للرمز ---------
def fetch_symbol_ideas(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    يبني لينك صفحة الأفكار:
    https://www.tradingview.com/symbols/{symbol}/ideas/
    يستخرج منها لينكات /chart/... ويجيب تفاصيل كل لينك.
    هذا يعتمد على قسم Chart Ideas في TradingView.
    """
    symbol = symbol.upper()
    ideas_page = f"{TV_BASE}/symbols/{symbol}/ideas/"

    logger.info("Fetching ideas page for %s: %s", symbol, ideas_page)

    try:
        resp = requests.get(ideas_page, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Error fetching ideas page for %s: %s", symbol, e)
        return []

    html = resp.text

    # نجيب كل لينكات /chart/.../slug/ من الصفحة
    chart_paths = []
    for m in re.finditer(r'href="(/chart/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/?)"', html):
        path = m.group(1)
        if path not in chart_paths:
            chart_paths.append(path)
        if len(chart_paths) >= limit * 3:
            # ناخد شوية أكتر من المطلوب تحسّبًا لو بعضها فاسد
            break

    if not chart_paths:
        logger.warning("No chart links found on ideas page for %s", symbol)
        return []

    ideas: List[Dict[str, Any]] = []
    for path in chart_paths:
        full_url = TV_BASE + path
        detail = fetch_idea_details(full_url)
        if detail:
            ideas.append(detail)
        if len(ideas) >= limit:
            break

    # ترتيب حسب أحدث وقت نشر
    with_dt = [i for i in ideas if i.get("published_dt")]
    without_dt = [i for i in ideas if not i.get("published_dt")]

    with_dt.sort(key=lambda x: x["published_dt"], reverse=True)
    ordered = with_dt + without_dt

    return ordered[:limit]


# --------- تجهيز الكابشن (عربي + إنجليزي) ---------
def build_caption(symbol: str, idx: int, total: int, idea: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"*Idea #{idx} / {total} — {symbol}*")
    lines.append(f"*{idea.get('title', 'No title')}*")

    if idea.get("author"):
        lines.append(f"✍️ الكاتب / Author: {idea['author']}")

    if idea.get("published_dt"):
        dt = idea["published_dt"].astimezone()
        lines.append("🕒 التاريخ / Time: " + dt.strftime("%Y-%m-%d %H:%M"))
    elif idea.get("published_raw"):
        lines.append(f"🕒 {idea['published_raw']}")

    lines.append("")
    lines.append(f"[فتح الفكرة على TradingView / Open on TradingView]({idea['url']})")
    lines.append("")
    lines.append("⚠️ هذه التحليلات مأخوذة من TradingView وليست نصيحة استثمارية.\n"
                 "This is not financial advice, ideas are from TradingView authors.")

    return "\n".join(lines)


# --------- أوامر البوت ---------
def start_cmd(update: Update, context: CallbackContext) -> None:
    text = (
        "👋 أهلاً بك!\n\n"
        "📈 هذا البوت يجلب لك أحدث *أفكار وتحليلات TradingView (Chart Ideas)* لأي زوج كريبتو أو عملات أو ذهب...\n\n"
        "📝 الطريقة الأولى (مفضّلة):\n"
        "`/ideas BTCUSDT`\n"
        "`/ideas BTCUSD`\n"
        "`/ideas ETHUSDT`\n"
        "`/ideas GOLD`\n\n"
        "📝 الطريقة الثانية:\n"
        "اكتب اسم الزوج كأمر مباشرة، مثلاً:\n"
        "`/BTCUSDT`\n"
        "`/BTCUSD`\n"
        "`/ETHUSDT`\n"
        "`/GOLD`\n\n"
        "سيتم جلب حتى 20 فكرة (إذا كانت موجودة) وإرسال كل فكرة في رسالة منفصلة مع الصورة والعنوان.\n\n"
        "English:\n"
        "Send `/ideas SYMBOL` like `/ideas BTCUSDT` and I'll fetch the latest TradingView chart ideas "
        "with image, title, author and link. "
        "You can also send `/BTCUSDT` directly."
    )
    update.message.reply_text(text, parse_mode="Markdown")


def send_ideas_for_symbol(update: Update, context: CallbackContext, symbol: str) -> None:
    chat_id = update.effective_chat.id

    waiting = update.message.reply_text(
        f"⏳ جاري جلب أحدث الأفكار لـ `{symbol}` من TradingView (Chart Ideas)...\n"
        f"Fetching latest TradingView chart ideas for `{symbol}`...",
        parse_mode="Markdown",
    )

    try:
        ideas = fetch_symbol_ideas(symbol, limit=20)
    except Exception as e:
        logger.exception("Unexpected error while fetching ideas for %s: %s", symbol, e)
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting.message_id,
            text=(
                "❌ حدث خطأ أثناء جلب البيانات من TradingView.\n"
                "An error occurred while fetching data from TradingView. Please try again later."
            ),
        )
        return

    if not ideas:
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting.message_id,
            text=(
                f"⚠️ لا توجد أفكار متاحة حاليًا على TradingView للزوج `{symbol}`.\n"
                f"No ideas found on TradingView right now for `{symbol}`."
            ),
            parse_mode="Markdown",
        )
        return

    # عدّل رسالة الانتظار
    context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=waiting.message_id,
        text=(
            f"✅ تم جلب {len(ideas)} فكرة من TradingView لزوج `{symbol}`.\n"
            f"✅ Fetched {len(ideas)} ideas from TradingView for `{symbol}`.\n"
            "سيتم إرسالها الآن واحدة تلو الأخرى..."
        ),
        parse_mode="Markdown",
    )

    # ابعت كل فكرة في رسالة منفصلة
    for idx, idea in enumerate(ideas, start=1):
        caption = build_caption(symbol, idx, len(ideas), idea)
        img = idea.get("image") or ""
        try:
            if img:
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img,
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
            logger.warning("Error sending idea #%s for %s: %s", idx, symbol, e)


def ideas_cmd(update: Update, context: CallbackContext) -> None:
    """
    /ideas BTCUSDT
    """
    if not context.args:
        update.message.reply_text(
            "❗ استخدم الأمر بهذا الشكل:\n"
            "`/ideas BTCUSDT`\n\n"
            "Use: `/ideas SYMBOL` like `/ideas BTCUSDT`.",
            parse_mode="Markdown",
        )
        return

    symbol = context.args[0].upper()
    send_ideas_for_symbol(update, context, symbol)


def pair_cmd(update: Update, context: CallbackContext) -> None:
    """
    أي أمر غير /start و /ideas نعتبره اسم زوج: /BTCUSDT, /ETHUSD ...
    """
    text = (update.message.text or "").strip()
    if not text.startswith("/"):
        return

    cmd = text[1:].upper()
    if cmd in {"START", "HELP", "IDEAS"}:
        return

    symbol = cmd
    send_ideas_for_symbol(update, context, symbol)


# --------- تشغيل البوت ---------
def main() -> None:
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("ideas", ideas_cmd))
    dp.add_handler(MessageHandler(Filters.command, pair_cmd))

    logger.info("🚀 Bot is starting polling...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
