import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from telegram import Bot

# ==========================
# TELEGRAM CONFIG
# ==========================

TOKEN = os.environ.get("BOT_TOKEN")
bot = Bot(token=TOKEN)

app = Flask(__name__)


# ==========================
# helpers
# ==========================

def clean_symbol(symbol: str) -> str:
    """تنظيف رمز العملة (BTC / BTCUSDT .. إلخ)"""
    symbol = (symbol or "").upper().strip()
    symbol = symbol.replace("/", "")
    return symbol


def fetch_tradingview_ideas(symbol: str, limit: int = 10):
    """
    يجمع آخر أفكار من صفحة TradingView للرمز
    بيرجع list فيها dict لكل فكرة
    """
    sym = clean_symbol(symbol)
    url = f"https://www.tradingview.com/symbols/{sym}/ideas/"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    ideas = []

    # كروت الأفكار
    for card in soup.select("div.tv-widget-idea"):
        if len(ideas) >= limit:
            break

        title_el = card.select_one("a.tv-widget-idea__title")
        if not title_el or not title_el.get("href"):
            continue

        link = "https://www.tradingview.com" + title_el["href"]
        title = title_el.get_text(strip=True)

        desc_el = card.select_one("p.tv-widget-idea__description")
        description = desc_el.get_text(strip=True) if desc_el else ""

        author_el = card.select_one("a.tv-user-link__name")
        author = author_el.get_text(strip=True) if author_el else ""

        date_el = card.select_one("span.tv-widget-idea__time")
        date = date_el.get_text(strip=True) if date_el else ""

        img_el = card.select_one("img")
        image_url = None
        if img_el and img_el.get("src"):
            image_url = img_el["src"]
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif image_url.startswith("/"):
                image_url = "https://www.tradingview.com" + image_url

        ideas.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "author": author,
                "date": date,
                "image": image_url,
            }
        )

    return ideas


# ==========================
# WEBHOOK
# ==========================

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)

    if "message" not in data:
        return "ok"

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        return "ok"

    # /start
    if text.startswith("/start"):
        bot.send_message(
            chat_id,
            (
                "🔥 البوت شغال!\n\n"
                "اكتب مثلاً:\n"
                "<code>/ideas BTCUSDT</code>\n"
                "علشان أجيبلك آخر 10 أفكار منشورة على TradingView للزوج ده."
            ),
            parse_mode="HTML",
        )
        return "ok"

    # /ideas SYMBOL
    if text.startswith("/ideas"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(
                chat_id,
                "استخدم الأمر بالشكل ده:\n<code>/ideas BTCUSDT</code>",
                parse_mode="HTML",
            )
            return "ok"
        symbol = parts[1].strip()
    else:
        # لو كتب الرمز مباشرة (BTCUSDT أو BTC) نعتبرها طلب أفكار
        symbol = text

    symbol_clean = clean_symbol(symbol)

    bot.send_message(
        chat_id,
        f"⏳ بجمع آخر الأفكار لـ <b>{symbol_clean}</b> من TradingView...",
        parse_mode="HTML",
    )

    try:
        ideas = fetch_tradingview_ideas(symbol_clean, limit=10)
    except Exception:
        bot.send_message(
            chat_id,
            "⚠️ حصل خطأ أثناء الاتصال بـ TradingView.\nحاول تاني بعد شوية.",
            parse_mode="HTML",
        )
        return "ok"

    if not ideas:
        bot.send_message(
            chat_id,
            f"ما لاقيتش أفكار حديثة على TradingView للرمز <b>{symbol_clean}</b>.",
            parse_mode="HTML",
        )
        return "ok"

    # إرسال كل فكرة في رسالة منفصلة
    for idx, idea in enumerate(ideas, start=1):
        title = idea.get("title") or "Idea"
        author = idea.get("author") or "غير مذكور"
        date = idea.get("date") or "غير مذكور"
        description = idea.get("description") or ""
        link = idea.get("link") or ""
        image_url = idea.get("image")

        caption_lines = [
            f"<b>{idx}. {title}</b>",
            f"✍️ الكاتب: {author}",
            f"📅 التاريخ: {date}",
        ]

        if description:
            caption_lines.append("")
            caption_lines.append(description[:400])  # نخليها قصيرة شوية

        if link:
            caption_lines.append("")
            caption_lines.append(f'<a href="{link}">فتح الفكرة على TradingView</a>')

        caption = "\n".join(caption_lines)

        if image_url:
            bot.send_photo(
                chat_id,
                image_url,
                caption=caption,
                parse_mode="HTML",
            )
        else:
            bot.send_message(
                chat_id,
                caption,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

    return "ok"


# ==========================
# LOCAL RUN (Koyeb هيستعمله)
# ==========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
