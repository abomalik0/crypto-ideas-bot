import os
import requests
from flask import Flask, request
from telegram import Bot
from datetime import datetime
import matplotlib.pyplot as plt
import io

TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_SECRET = "secure123"
bot = Bot(token=TOKEN)

app = Flask(__name__)

# ===========================
# 🔥 GET PRICE (BINANCE API)
# ===========================
def get_price(symbol="BTCUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
    r = requests.get(url).json()
    return float(r["price"])

# ===========================
# 🔥 DRAW DARK PREMIUM CHART
# ===========================
def draw_chart(symbol, price):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(6, 4), facecolor="black")
    ax.set_facecolor("black")

    x = [0, 1, 2, 3, 4]
    y = [price * 0.98, price * 0.99, price, price * 1.01, price * 1.015]

    ax.plot(x, y, linewidth=2)

    ax.set_title(f"{symbol} – Dark Premium", color="cyan")
    ax.set_xlabel("Timeline", color="white")
    ax.set_ylabel("Price", color="white")

    for spine in ax.spines.values():
        spine.set_color("white")

    img = io.BytesIO()
    plt.savefig(img, format="png", dpi=180, bbox_inches="tight")
    img.seek(0)
    plt.close()
    return img

# ===========================
# 🔥 TELEGRAM WEBHOOK
# ===========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()

        if text == "/start":
            bot.send_message(chat_id, "🔥 Bot is online!\nSend any symbol like: BTC")
            return "ok"

        # symbol
        symbol = text.upper() + "USDT"
        price = get_price(symbol)

        # chart
        img = draw_chart(symbol, price)

        bot.send_photo(
            chat_id,
            photo=img,
            caption=f"**{symbol}**\nPrice: {price}$\n\n🔗 TradingView:\nhttps://www.tradingview.com/chart/?symbol={symbol}",
            parse_mode="Markdown"
        )

    return "ok"

# ===========================
# RUN FLASK
# ===========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
