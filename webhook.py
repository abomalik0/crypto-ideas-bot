# webhook.py
from telegram import Bot

def set_webhook():
    bot = Bot(token="YOUR_BOT_TOKEN")
    webhook_url = "https://your_server_url"
    bot.set_webhook(url=webhook_url)

def handle_webhook(request):
    data = request.get_json()
    # ضع هنا الكود لمعالجة البيانات المرسلة من التليجرام
    return "OK"
