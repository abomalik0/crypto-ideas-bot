import requests
import logging
from config import ADMIN_CHAT_ID
from telegram import Bot, ParseMode
import time
import config

logger = logging.getLogger(__name__)

# =====================================================
#   Webhook Setup and Response
# =====================================================

def setup_webhook():
    bot = Bot(token=config.BOT_TOKEN)
    webhook_url = config.WEBHOOK_URL
    try:
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    except Exception as e:
        logger.exception(f"Error setting webhook: {e}")

def handle_webhook(request):
    """
    Handle the webhook request and process incoming messages.
    """
    try:
        # Process incoming request and send responses if needed
        data = request.json
        chat_id = data["message"]["chat"]["id"]
        message_text = data["message"]["text"]
        
        bot = Bot(token=config.BOT_TOKEN)
        bot.send_message(chat_id=chat_id, text="Received your message")
        
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
