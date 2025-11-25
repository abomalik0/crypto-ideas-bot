import os
import logging
from flask import Flask, request
import requests

# =========================
# إعدادات أساسية
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

# إعداد اللوج
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# إنشاء تطبيق Flask
app = Flask(__name__)


# =========================
# دوال مساعدة
# =========================
def send_message(chat_id: int, text: str, reply_to_message_id: int | None = None):
    """
    إرسال رسالة عادية بتنسيق Markdown.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json=payload,
            timeout=10,
        )
        if not resp.ok:
            logger.error("sendMessage failed: %s - %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending message: %s", e)


def extract_command_and_args(text: str) -> tuple[str, str]:
    """
    يقسم نص الرسالة إلى:
    - command: مثل /coin
    - args: باقي النص بعد الأمر
    """
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", text

    parts = text.split(maxsplit=1)
    command = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    return command.lower(), args.strip()


def build_coin_analysis(symbol: str) -> str:
    """
    يبني رسالة تحليل احترافية (تجريبية) للعملة المطلوبة.
    حالياً لا يعتمد على بيانات سوق حقيقية، فقط قالب احترافي ثابت.
    """
    sym = symbol.upper()

    msg = f"""📊 *تحليل مبدئي – {sym}*

▫️ *الاتجاه العام (تجريبي):*
السوق الحالي يُظهر حركة يمكن اعتبارها *عرضية/يميل للهبوط أو الصعود* بحسب سلوك السعر الأخير، لذا يُفضَّل التعامل بحذر وعدم الاعتماد على حركة واحدة فقط للحكم على الاتجاه.

▫️ *مناطق مهمة للمراقبة:*
• مناطق دعم محتملة لمراقبة أي رد فعل سعري جديد في حال الهبوط.
• مناطق مقاومة محتملة قد يظهر عندها جني أرباح أو تباطؤ في الصعود.

▫️ *سيولة العملة وحركة السوق:*
• يتم التركيز على سلوك السيولة على الفريمات القصيرة لمعرفة إن كان هناك دخول قوي لمراكز جديدة أو خروج تدريجي من السوق.
• أي توسع مفاجئ في السبريد أو حركة سريعة يكون عادةً إشارة على زيادة المخاطر قصيرة المدى.

▫️ *النماذج الفنية / الهارمونيك:*
حتى الآن *لا يوجد نموذج هارمونيك واضح وقوي يتم الاعتماد عليه*، وسيتم متابعة الحركة لاكتشاف أي نموذج متناظر (مثل جارتلي – بات – فراكتر) يمكن الاستفادة منه مستقبلاً.

▫️ *إدارة المخاطر:*
• يُفضَّل استخدام حجم مخاطرة منخفض.
• وضع وقف خسارة يكون:
  – أسفل أقرب منطقة دعم في حالة الشراء.
  – أو أعلى أقرب منطقة مقاومة في حالة البيع.
• تجنّب الدخول بكامل رأس المال في صفقة واحدة.

🧠 *هذا التحليل مبدئي وتجريبي، وليس نصيحة استثمارية مباشرة. القرار النهائي دائماً مسؤوليتك أنت.*

𝗜𝗡 𝗖𝗥𝗬𝗣𝗧𝗢 Ai
"""
    return msg


# =========================
# معالجة الرسائل
# =========================
def handle_message(message: dict):
    """
    يستقبل message من Telegram (من /webhook) ويقرر يرد بإيه.
    """
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text") or ""

    if not chat_id or not text:
        return

    command, args = extract_command_and_args(text)

    # أمر /start
    if command == "/start":
        welcome = (
            "👋 أهلاً بك في *IN CRYPTO Ai Bot*.\n\n"
            "يمكنك طلب تحليل مبدئي لأي عملة عن طريق الأمر:\n"
            "`/coin BTCUSDT`\n"
            "أو مثلاً:\n"
            "`/coin ETHUSDT`\n\n"
            "⚠️ التحليل تجريبي ومبدئي، وليس نصيحة استثمارية مباشرة."
        )
        send_message(chat_id, welcome, reply_to_message_id=message.get("message_id"))
        return

    # أمر /coin
    if command == "/coin":
        if not args:
            help_text = (
                "🧾 *طريقة الاستخدام:*\n\n"
                "اكتب الأمر بهذا الشكل:\n"
                "`/coin BTCUSDT`\n"
                "أو:\n"
                "`/coin ethusdt`\n\n"
                "سيصلك تحليل مبدئي منظم للعملة."
            )
            send_message(chat_id, help_text, reply_to_message_id=message.get("message_id"))
            return

        symbol = args.split()[0].strip().upper()
        analysis = build_coin_analysis(symbol)
        send_message(chat_id, analysis, reply_to_message_id=message.get("message_id"))
        return

    # أي رسالة تانية: نرشده لاستخدام /coin
    if command.startswith("/"):
        unknown = (
            "⚠️ الأمر غير معروف.\n\n"
            "جرّب استخدام:\n"
            "`/coin BTCUSDT`\n"
            "للحصول على تحليل مبدئي للعملة."
        )
        send_message(chat_id, unknown, reply_to_message_id=message.get("message_id"))
    else:
        hint = (
            "💡 إذا أردت تحليل عملة، استخدم:\n"
            "`/coin BTCUSDT`\n"
            "وغيّر `BTCUSDT` لأي عملة أخرى تريدها."
        )
        send_message(chat_id, hint, reply_to_message_id=message.get("message_id"))


# =========================
# مسارات Flask
# =========================
@app.route("/", methods=["GET"])
def index():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    نقطة استقبال التحديثات من Telegram.
    """
    try:
        update = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        logger.exception("Failed to parse incoming update: %s", e)
        return "BAD REQUEST", 400

    message = update.get("message") or update.get("edited_message")
    if message:
        try:
            handle_message(message)
        except Exception as e:
            logger.exception("Error handling message: %s", e)

    return "OK", 200


# =========================
# تشغيل محلي (اختياري)
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting Flask app on port %s ...", port)
    app.run(host="0.0.0.0", port=port)
