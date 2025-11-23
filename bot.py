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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var not set")

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
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                published_dt = datetime.strptime(published_raw, fmt)
                break
            except Exception:
                continue

    if not image:
        # لو مفيش صورة، ممكن نكمّل كنص بس
        logger.info("No image in idea %s", url)

    return {
        "title": title,
        "image": image,
        "author": author,
        "published_raw": published_raw,
        "published_dt": published_dt,
        "url": url,
    }


# --------- جلب 20 فكرة من صفحة /symbols/{symbol}/ideas/ ---------
def fetch_symbol_ideas(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    يبني لينك صفحة الأفكار:
    https://www.tradingview.com/symbols/{symbol}/ideas/
    ويستخرج منها لينكات /chart/... وبعدها يجيب تفاصيل كل لينك.
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

    # نجيب كل لينكات /chart/.../slug/
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


# --------- تجهيز الكابشن ---------
def build_caption(symbol: str, idx: int, total: int, idea: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"*{symbol} — Idea #{idx}*")
    lines.append(f"*{idea.get('title', 'No title')}*")

    if idea.get("author"):
        lines.append(f"✍️ {idea['author']}")

    if idea.get("published_dt"):
        dt = idea["published_dt"].astimezone()
        lines.append("🕒 " + dt.strftime("%Y-%m-%d %H:%M"))
    elif idea.get("published_raw"):
        lines.append(f"🕒 {idea['published_raw']}")

    lines.append("")
    lines.append(f"[فتح الفكرة على TradingView]({idea['url']})")
    lines.append("")
    lines.append("⚠️ هذه التحليلات من TradingView وليست نصيحة استثمارية.")

    return "\n".join(lines)


# --------- أوامر البوت ---------
def start_cmd(update: Update, context: CallbackContext) -> None:
    text = (
        "أهلاً بك 👋\n\n"
        "هذا البوت يجلب لك أحدث *أفكار وتحليلات TradingView* لأي زوج.\n\n"
        "اكتب اسم الزوج كأمر، مثلاً:\n"
        "`/BTCUSDT`\n"
        "`/ETHUSDT`\n"
        "`/SOLUSDT`\n"
        "`/VAIUSDT`\n"
        "وهكذا...\n\n"
        "سيتم جلب حتى 20 فكرة (إذا كانت موجودة) وإرسال كل فكرة في رسالة منفصلة."
    )
    update.message.reply_text(text, parse_mode="Markdown")


def pair_cmd(update: Update, context: CallbackContext) -> None:
    """
    أي أمر غير /start نعتبره اسم زوج: /BTCUSDT, /VAIUSDT ...
    """
    text = (update.message.text or "").strip()
    if not text.startswith("/"):
        return

    cmd = text[1:].upper()
    if cmd in {"START", "HELP"}:
        return

    symbol = cmd
    chat_id = update.message.chat_id

    waiting = update.message.reply_text(
        f"⏳ جاري جلب أحدث 20 فكرة من TradingView لزوج `{symbol}` ...",
        parse_mode="Markdown",
    )

    try:
        ideas = fetch_symbol_ideas(symbol, limit=20)
    except Exception as e:
        logger.exception("Unexpected error while fetching ideas for %s: %s", symbol, e)
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting.message_id,
            text="❌ حدث خطأ أثناء جلب البيانات من TradingView، حاول مرة أخرى لاحقاً.",
        )
        return

    if not ideas:
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=waiting.message_id,
            text=f"⚠️ لا توجد أفكار متاحة حالياً على TradingView لزوج `{symbol}`.",
            parse_mode="Markdown",
        )
        return

    # عدّل رسالة الانتظار
    context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=waiting.message_id,
        text=f"✅ تم جلب {len(ideas)} فكرة من TradingView لزوج `{symbol}`.\n"
             f"سيتم إرسالها الآن واحدة تلو الأخرى.",
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


def main() -> None:
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(MessageHandler(Filters.command, pair_cmd))

    logger.info("Bot is starting polling...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
