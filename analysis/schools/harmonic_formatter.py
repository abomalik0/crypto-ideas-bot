# analysis/schools/harmonic_formatter.py

def format_harmonic_telegram(result: dict) -> str:
    """
    يحول ناتج Harmonic Engine إلى رسالة Telegram احترافية
    """

    if not result or not isinstance(result, dict):
        return "❌ Harmonic: لا توجد نتيجة صالحة."

    pattern = result.get("pattern", "Unknown Pattern")
    direction = str(result.get("direction", "neutral")).upper()
    timeframe = result.get("timeframe", "N/A")

    entry = result.get("entry")
    stop = result.get("stop_loss")
    targets = result.get("targets", [])

    rr = result.get("rr_ratio")
    confidence = result.get("confidence", 0)

    notes = result.get("notes", "")
    confluence = result.get("confluence", [])

    emoji_dir = "📈" if direction == "BUY" else "📉" if direction == "SELL" else "⚖️"

    msg = []
    msg.append("━━━━━━━━━━━━━━━━━━")
    msg.append("🧠 **HARMONIC PATTERN DETECTED**")
    msg.append("━━━━━━━━━━━━━━━━━━")
    msg.append(f"{emoji_dir} **Pattern:** `{pattern}`")
    msg.append(f"🕒 **Timeframe:** `{timeframe}`")
    msg.append(f"🎯 **Direction:** **{direction}**")
    msg.append("")

    if entry:
        msg.append(f"🔑 **Entry:** `{entry}`")
    if stop:
        msg.append(f"🛑 **Stop Loss:** `{stop}`")

    if targets:
        msg.append("")
        msg.append("🎯 **Targets:**")
        for i, t in enumerate(targets, 1):
            msg.append(f"  • TP{i}: `{t}`")

    if rr:
        msg.append("")
        msg.append(f"⚖️ **Risk / Reward:** `{rr}`")

    msg.append("")
    msg.append(f"📊 **Confidence:** `{confidence}%`")

    if confluence:
        msg.append("")
        msg.append("🧩 **Confluence:**")
        for c in confluence:
            msg.append(f"  • {c}")

    if notes:
        msg.append("")
        msg.append(f"📝 **Notes:** {notes}")

    msg.append("")
    msg.append("⚠️ *إدارة رأس المال مسؤوليتك*")
    msg.append("━━━━━━━━━━━━━━━━━━")

    return "\n".join(msg)
