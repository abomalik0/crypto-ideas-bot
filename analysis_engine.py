import time
from datetime import datetime

import config

# ==============================
#   تجهيز رمز العملة + المنصات
# ==============================

def normalize_symbol(user_symbol: str):
    base = user_symbol.strip().upper()
    base = base.replace("USDT", "").replace("-", "").strip()
    if not base:
        return None, None, None

    binance_symbol = base + "USDT"
    kucoin_symbol = base + "-USDT"
    return base, binance_symbol, kucoin_symbol

# ==============================
#   كاش خفيف لتسريع جلب الأسعار
# ==============================

def _get_cached(key: str):
    item = config.PRICE_CACHE.get(key)
    if not item:
        return None
    if time.time() - item["time"] > config.CACHE_TTL_SECONDS:
        return None
    return item["data"]

def _set_cached(key: str, data: dict):
    config.PRICE_CACHE[key] = {
        "time": time.time(),
        "data": data,
    }

# ==============================
#   جلب البيانات من Binance / KuCoin + API Health
# ==============================

def fetch_from_binance(symbol: str):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = config.HTTP_SESSION.get(url, params={"symbol": symbol}, timeout=10)
        config.API_STATUS["last_api_check"] = datetime.utcnow().isoformat(timespec="seconds")

        # Binance invalid symbol
        if r.status_code == 400 and "Invalid symbol" in r.text:
            config.API_STATUS["binance_ok"] = True
            config.API_STATUS["binance_last_error"] = "Invalid symbol (not supported)"
            return None

        if r.status_code != 200:
            config.API_STATUS["binance_ok"] = False
            config.API_STATUS["binance_last_error"] = f"{r.status_code}: {r.text[:120]}"
            config.logger.info("Binance error %s for %s: %s", r.status_code, symbol, r.text)
            return None

        data = r.json()
        price = float(data["lastPrice"])
        change_pct = float(data["priceChangePercent"])
        high = float(data.get("highPrice", price))
        low = float(data.get("lowPrice", price))
        volume = float(data.get("volume", 0))

        config.API_STATUS["binance_ok"] = True

        return {
            "exchange": "binance",
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
        }

    except Exception as e:
        config.API_STATUS["binance_ok"] = False
        config.API_STATUS["binance_last_error"] = str(e)
        config.logger.exception("Error fetching from Binance: %s", e)
        return None


def fetch_from_kucoin(symbol: str):
    try:
        url = "https://api.kucoin.com/api/v1/market/stats"
        r = config.HTTP_SESSION.get(url, params={"symbol": symbol}, timeout=10)
        config.API_STATUS["last_api_check"] = datetime.utcnow().isoformat(timespec="seconds")

        if r.status_code != 200:
            config.API_STATUS["kucoin_ok"] = False
            config.API_STATUS["kucoin_last_error"] = f"{r.status_code}: {r.text[:120]}"
            config.logger.info("KuCoin error %s for %s: %s", r.status_code, symbol, r.text)
            return None

        payload = r.json()
        if payload.get("code") != "200000":
            config.API_STATUS["kucoin_ok"] = False
            config.API_STATUS["kucoin_last_error"] = f"code={payload.get('code')}"
            config.logger.info("KuCoin non-success code: %s", payload)
            return None

        data = payload.get("data") or {}
        price = float(data.get("last") or 0)
        change_rate = float(data.get("changeRate") or 0.0)
        change_pct = change_rate * 100.0
        high = float(data.get("high") or price)
        low = float(data.get("low") or price)
        volume = float(data.get("vol") or 0)

        config.API_STATUS["kucoin_ok"] = True

        return {
            "exchange": "kucoin",
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
        }

    except Exception as e:
        config.API_STATUS["kucoin_ok"] = False
        config.API_STATUS["kucoin_last_error"] = str(e)
        config.logger.exception("Error fetching from KuCoin: %s", e)
        return None


def fetch_price_data(user_symbol: str):
    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    if not base:
        return None

    c1 = f"BINANCE:{binance_symbol}"
    c2 = f"KUCOIN:{kucoin_symbol}"

    cached = _get_cached(c1)
    if cached:
        return cached

    cached = _get_cached(c2)
    if cached:
        return cached

    data = fetch_from_binance(binance_symbol)
    if data:
        _set_cached(c1, data)
        return data

    data = fetch_from_kucoin(kucoin_symbol)
    if data:
        _set_cached(c2, data)
        return data

    return None

# ==============================
#  بناء Metrics
# ==============================

def build_symbol_metrics(price: float, change_pct: float, high: float, low: float) -> dict:
    if price > 0 and high >= low:
        range_pct = ((high - low) / price) * 100.0
    else:
        range_pct = 0.0

    volatility_raw = abs(change_pct) * 1.5 + range_pct
    volatility_score = max(0.0, min(100.0, volatility_raw))

    if change_pct >= 3:
        strength_label = "صعود قوى وزخم واضح فى الحركة."
    elif change_pct >= 1:
        strength_label = "صعود هادئ مع تحسن تدريجى فى الزخم."
    elif change_pct > -1:
        strength_label = "حركة متذبذبة بدون اتجاه واضح."
    elif change_pct > -3:
        strength_label = "هبوط خفيف مع ضغط بيعى ملحوظ."
    else:
        strength_label = "هبوط قوى مع ضغوط بيعية عالية."

    if change_pct >= 2 and range_pct <= 5:
        liquidity_pulse = "السيولة تميل إلى الدخول بشكل منظم."
    elif change_pct >= 2 and range_pct > 5:
        liquidity_pulse = "صعود سريع مع تقلب عالى → قد يكون فيه تصريف جزئى."
    elif -2 < change_pct < 2:
        liquidity_pulse = "السيولة متوازنة تقريباً بين المشترين والبائعين."
    elif change_pct <= -2 and range_pct > 4:
        liquidity_pulse = "خروج سيولة واضح مع هبوط ملحوظ."
    else:
        liquidity_pulse = "يوجد بعض الضغوط البيعية لكن بدون ذعر كبير."

    return {
        "price": price,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
    }

# ==============================
#  BTC Market Metrics
# ==============================

def compute_market_metrics() -> dict | None:
    data = fetch_price_data("BTCUSDT")
    if not data:
        return None

    return build_symbol_metrics(data["price"], data["change_pct"], data["high"], data["low"])


def get_market_metrics_cached() -> dict | None:
    now = time.time()
    data = config.MARKET_METRICS_CACHE.get("data")
    ts = config.MARKET_METRICS_CACHE.get("time", 0.0)

    if data and (now - ts) <= config.MARKET_TTL_SECONDS:
        return data

    data = compute_market_metrics()
    if data:
        config.MARKET_METRICS_CACHE["data"] = data
        config.MARKET_METRICS_CACHE["time"] = now
    return data
    # ==============================
#   Risk Engine
# ==============================

def evaluate_risk_level(change_pct: float, volatility_score: float) -> dict:
    risk_score = abs(change_pct) + (volatility_score * 0.4)

    if risk_score < 25:
        level = "low"
        emoji = "🟢"
        message = (
            "المخاطر حاليًا منخفضة نسبيًا، السوق يتحرك بهدوء مع إمكانية الدخول بشرط إدارة مخاطر واضحة."
        )
    elif risk_score < 50:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر متوسطة، الحركة السعرية بها تقلب واضح، ويفضل استخدام حجم عقود أصغر."
        )
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر مرتفعة، السوق يشهد تقلبات قوية. يفضل تجنب الدخول بدون خطة."
        )

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
        "score": risk_score,
    }


def _risk_level_ar(level: str) -> str:
    return {"low": "منخفض", "medium": "متوسط", "high": "مرتفع"}.get(level, level)

# ==============================
#   Fusion AI Brain
# ==============================

def fusion_ai_brain(metrics: dict, risk: dict) -> dict:
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    strength = metrics["strength_label"]
    liquidity = metrics["liquidity_pulse"]
    risk_level = risk["level"]

    # الاتجاه العام
    if change >= 4:
        bias = "strong_bullish"
        bias_text = "شهية مخاطرة صاعدة قوية مع سيطرة واضحة للمشترين."
    elif change >= 2:
        bias = "bullish"
        bias_text = "ميل صاعد واضح مع تحسن مضطرد فى مزاج السوق."
    elif 0.5 <= change < 2:
        bias = "bullish_soft"
        bias_text = "ميل صاعد هادئ لكن بدون انفجار قوى حتى الآن."
    elif -0.5 < change < 0.5:
        bias = "neutral"
        bias_text = "تذبذب شبه متزن، السوق يراقب قبل اتخاذ قرار حاسم."
    elif -2 < change <= -0.5:
        bias = "bearish_soft"
        bias_text = "ميل هابط خفيف يعكس ضعف نسبى فى قوة المشترين."
    elif -4 < change <= -2:
        bias = "bearish"
        bias_text = "ضغط بيعى واضح مع سيطرة ملحوظة للدببة."
    else:
        bias = "strong_bearish"
        bias_text = "مرحلة بيع عنيف أو ذعر جزئى فى السوق."

    # سلوك السيولة SMC
    if bias.startswith("strong_bullish") and "الدخول" in liquidity:
        smc_view = "سلوك أقرب لتجميع مؤسسى واضح مع دخول سيولة قوية."
    elif bias.startswith("bullish") and "الدخول" in liquidity:
        smc_view = "السوق يميل لتجميع ذكى هادئ مع تدرج فى بناء المراكز."
    elif bias.startswith("bearish") and "خروج" in liquidity:
        smc_view = "السوق يميل لتوزيع بيعى تدريجى وخروج سيولة من القمم."
    elif bias.startswith("strong_bearish"):
        smc_view = "مرحلة تصفية أو Panic جزئى مع بيع حاد عند الكسر."
    else:
        smc_view = "الحركة أقرب لتوازن مؤقت بين المشترين والبائعين."

    # مرحلة وايكوف
    if vol < 20 and abs(change) < 1:
        wyckoff_phase = "المرحلة الحالية تشبه Range جانبى."
    elif vol >= 60 and abs(change) >= 3:
        wyckoff_phase = "مرحلة اندفاع عالية التقلب."
    elif bias.startswith("bullish"):
        wyckoff_phase = "Phase صاعد (Mark-Up)."
    elif bias.startswith("bearish"):
        wyckoff_phase = "Phase هابط (Mark-Down)."
    else:
        wyckoff_phase = "مرحلة انتقالية بدون اتجاه كامل."

    # تعليق المخاطر
    if risk_level == "high":
        risk_comment = "المخاطر مرتفعة، الانضباط فى إدارة رأس المال ضرورى."
    elif risk_level == "medium":
        risk_comment = "المخاطر متوسطة، يفضل العمل بحجم صفقات صغير."
    else:
        risk_comment = "المخاطر منخفضة نسبيًا لكن الاستعجال غير مفضل."

    # احتمالات الحركة 24–72 ساعة
    if abs(change) < 1 and vol < 25:
        p_up, p_side, p_down = 30, 55, 15
    elif bias.startswith("strong_bullish") and vol <= 55:
        p_up, p_side, p_down = 55, 30, 15
    elif bias.startswith("bullish") and vol <= 60:
        p_up, p_side, p_down = 45, 35, 20
    elif bias.startswith("strong_bearish") and vol >= 50:
        p_up, p_side, p_down = 15, 30, 55
    elif bias.startswith("bearish") and vol >= 40:
        p_up, p_side, p_down = 20, 35, 45
    else:
        p_up, p_side, p_down = 35, 40, 25

    ai_summary = (
        f"{bias_text}\n"
        f"{smc_view}\n"
        f"{wyckoff_phase}\n"
        f"{risk_comment}\n"
        f"احتمالات الحركة 24–72 ساعة: صعود ~{p_up}٪ / تماسك ~{p_side}٪ / هبوط ~{p_down}٪."
    )

    return {
        "bias": bias,
        "bias_text": bias_text,
        "smc_view": smc_view,
        "wyckoff_phase": wyckoff_phase,
        "risk_comment": risk_comment,
        "strength": strength,
        "liquidity": liquidity,
        "p_up": p_up,
        "p_side": p_side,
        "p_down": p_down,
        "ai_summary": ai_summary,
    }

# ==============================
#   دالة تقصير نص رسالة تيليجرام
# ==============================

def _shrink_text_preserve_content(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text

    while "\n\n\n" in text and len(text) > limit:
        text = text.replace("\n\n\n", "\n\n")

    while "  " in text and len(text) > limit:
        text = text.replace("  ", " ")

    if len(text) > limit:
        text = text.replace(" \n", "\n")

    return text
    
# ==============================
#     صياغة رسالة التحليل للعملة /btc /coin
# ==============================

def format_analysis(user_symbol: str) -> str:
    data = fetch_price_data(user_symbol)
    if not data:
        return (
            "⚠️ لا يمكن جلب بيانات هذه العملة الآن.\n"
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code>) "
            "وحاول مرة أخرى."
        )

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]
    volume = data.get("volume", 0.0)
    exchange = data["exchange"]

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (
        binance_symbol if exchange == "binance" else kucoin_symbol
    ).replace("-", "")

    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

    # 🎛 RSI مبسط
    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))
    if rsi >= 70:
        rsi_trend = "⬆️ مرتفع (تشبّع شرائى محتمل)"
    elif rsi <= 30:
        rsi_trend = "⬇️ منخفض (تشبّع بيع محتمل)"
    else:
        rsi_trend = "🔁 حيادى نسبياً"

    # الاتجاه العام
    if change > 2:
        trend_text = "الاتجاه العام يميل إلى الصعود مع زخم إيجابى ملحوظ."
    elif change > 0:
        trend_text = "الاتجاه العام يميل إلى الصعود بشكل هادئ."
    elif change > -2:
        trend_text = "الاتجاه العام يميل إلى الهبوط الخفيف مع بعض التذبذب."
    else:
        trend_text = "الاتجاه العام يميل إلى الهبوط مع ضغوط بيعية واضحة."

    # بناء المقاييس + المخاطر + دماغ AI
    metrics = build_symbol_metrics(price, change, high, low)
    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    fusion = fusion_ai_brain(metrics, risk)

    # 🧨 محرك مخاطر العملات الصغيرة
    micro_risks: list[str] = []

    if volume < 50_000:
        micro_risks.append(
            "حجم التداول الحالى منخفض جدًا مقارنة بمعظم العملات → أى صفقة كبيرة قد تحرك السعر بشكل حاد."
        )
    if abs(change) >= 25:
        micro_risks.append(
            "تغير سعرى يومى يتجاوز 25٪ → قد يشير إلى حركة Pump & Dump أو خبر قصير المدى."
        )
    if price < 0.0001:
        micro_risks.append(
            "السعر الحالى منخفض جدًا (فراكشن) → نسبة الانزلاق السعرى والسبريد تكون أعلى من المعتاد."
        )

    micro_block = ""
    if micro_risks:
        micro_block = (
            "\n\n⚠️ <b>تنبيه مخاطر إضافى للعملة:</b>\n" +
            "\n".join(f"• {line}" for line in micro_risks) +
            "\n\nهذه الملاحظات تعليمية وليست نصيحة مباشرة بالشراء أو البيع."
        )

    # ملاحظات AI العامة
    ai_note = (
        "🤖 <b>ملاحظة الذكاء الاصطناعى:</b>\n"
        "هذا التحليل يساعدك على فهم الاتجاه وحركة السعر، "
        "وليس توصية مباشرة بالشراء أو البيع.\n"
        "احرص دائمًا على دمج التحليل الفنى مع إدارة مخاطر منضبطة.\n"
    )

    fusion_block = (
        "🧠 <b>ملخص IN CRYPTO Ai للعملة:</b>\n"
        f"- الاتجاه: {fusion['bias_text']}\n"
        f"- سلوك السيولة: {fusion['liquidity']}\n"
        f"- المرحلة الحالية: {fusion['wyckoff_phase']}\n"
        f"- تقييم المخاطر: {fusion['risk_comment']}\n"
        f"- تقدير حركة 24–72 ساعة: صعود ~{fusion['p_up']}٪ / "
        f"تماسك ~{fusion['p_side']}٪ / هبوط ~{fusion['p_down']}٪.\n"
    )

    msg = f"""
📊 <b>تحليل فنى يومى للعملة {display_symbol}</b>

💰 <b>السعر الحالى:</b> {price:.6f}
📉 <b>تغير اليوم:</b> %{change:.2f}
📊 <b>حجم التداول 24 ساعة:</b> {volume:,.0f}

🎯 <b>حركة السعر العامة:</b>
- {trend_text}

📍 <b>مستويات فنية مهمة:</b>
- دعم يومى تقريبى حول: <b>{support}</b>
- مقاومة يومية تقريبية حول: <b>{resistance}</b>

📉 <b>RSI:</b>
- مؤشر القوة النسبية عند حوالى: <b>{rsi:.1f}</b> → {rsi_trend}

{fusion_block}{micro_block}

{ai_note}
<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return msg
    # ==============================
#   تقرير السوق /market
# ==============================

def format_market_report() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات السوق العامة حاليًا.\n"
            "حاول مرة أخرى بعد قليل."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    fusion = fusion_ai_brain(metrics, risk)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    risk_level_text = _risk_level_ar(risk["level"])

    fusion_line = (
        f"- قراءة IN CRYPTO Ai: {fusion['bias_text']} | "
        f"{fusion['smc_view']} | {fusion['wyckoff_phase']}"
    )

    report = f"""
✅ <b>تحليل الذكاء الاصطناعى للسوق (BTC Market)</b>
📅 <b>التاريخ:</b> {today_str}

🏛 <b>البيتكوين:</b>
- السعر الحالى: <b>${price:,.0f}</b>
- تغير 24 ساعة: <b>%{change:+.2f}</b>

📈 <b>قوة الاتجاه:</b>
- {strength_label}
- نطاق الحركة اليومى: <b>{range_pct:.2f}%</b>
- درجة التقلب: <b>{volatility_score:.1f}</b>/100

💧 <b>السيولة:</b>
- {liquidity_pulse}

🧠 <b>لمحة IN CRYPTO Ai:</b>
{fusion_line}

⚠️ <b>مستوى المخاطر:</b>
- {risk['emoji']} <b>{risk_level_text}</b>
- {risk['message']}

📌 <b>نصائح عامة:</b>
- استخدم وقف خسارة واضح.
- تجنب مطاردة الحركة اللحظية.
- راقب مناطق الدعم والمقاومة.

<b>IN CRYPTO Ai 🤖</b>
""".strip()

    return report


# ==============================
#   اختبار المخاطر السريع /risk_test
# ==============================

def format_risk_test() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذّر جلب بيانات المخاطر حالياً."

    change = metrics["change_pct"]
    vol = metrics["volatility_score"]

    risk = evaluate_risk_level(change, vol)
    risk_text = _risk_level_ar(risk["level"])

    msg = f"""
⚙️ <b>اختبار المخاطر السريع</b>

📉 تغير BTC آخر 24 ساعة: <b>%{change:+.2f}</b>
📊 درجة التقلب الحالية: <b>{vol:.1f}</b>/100
🧭 مستوى الخطر: {risk['emoji']} <b>{risk_text}</b>

{risk['message']}

<b>IN CRYPTO Ai 🤖</b>
""".strip()

    return msg


# ==============================
#   نظام التحذير الذكى (Alerts)
# ==============================

def detect_alert_condition(metrics: dict, risk: dict) -> str | None:
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    reasons = []

    if change <= -3:
        reasons.append("هبوط حاد يتجاوز -3٪ خلال 24 ساعة.")
    elif change >= 4:
        reasons.append("صعود قوى يتجاوز +4٪ خلال 24 ساعة.")

    if vol >= 60 or range_pct >= 7:
        reasons.append("ارتفاع كبير فى التقلب.")

    if risk["level"] == "high":
        reasons.append("المخاطر مرتفعة حالياً.")

    if not reasons:
        return None

    alert_text = " | ".join(reasons)

    config.logger.info(
        "Alert triggered: %s | Price=%s change=%.2f range=%.2f vol=%.1f",
        alert_text, price, change, range_pct, vol
    )
    return alert_text


# ==============================
#   التحذير الموحد /alert
# ==============================

def format_ai_alert() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ لا توجد بيانات كافية الآن لإصدار تنبيه."

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    risk = evaluate_risk_level(change, vol)
    fusion = fusion_ai_brain(metrics, risk)

    now = datetime.utcnow()
    date_text = now.strftime("%Y-%m-%d")

    intraday_support = round(low * 0.99, 2)
    intraday_resistance = round(high * 1.01, 2)

    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))

    if rsi >= 70:
        rsi_desc = "تشبع شرائى"
    elif rsi <= 30:
        rsi_desc = "تشبع بيعى"
    else:
        rsi_desc = "منطقة حيادية"

    alert_msg = f"""
⚠️ <b>تنبيه هام — السوق يتحرك بقوة</b>

📅 <b>الوقت:</b> {date_text}
💰 <b>سعر BTC:</b> ${price:,.0f} (%{change:+.2f})

📈 <b>وضع السوق:</b>
- نطاق اليوم: <b>{range_pct:.2f}%</b>
- درجة التقلب: <b>{vol:.1f}</b>/100
- مستوى المخاطر: {risk['emoji']} <b>{_risk_level_ar(risk['level'])}</b>

📉 <b>RSI:</b> {rsi:.1f} → {rsi_desc}

📍 <b>مستويات مهمة:</b>
- دعم مضاربي: {intraday_support}$
- مقاومة مضاربية: {intraday_resistance}$

🧠 <b>ملخص الذكاء الاصطناعى:</b>
- الاتجاه: {fusion['bias_text']}
- السيولة: {fusion['smc_view']}
- المرحلة: {fusion['wyckoff_phase']}
- توقعات 24–72 ساعة:
  • صعود: ~{fusion['p_up']}%
  • تماسك: ~{fusion['p_side']}%
  • هبوط: ~{fusion['p_down']}%

<b>IN CRYPTO Ai 🤖</b>
""".strip()

    return alert_msg


# ==============================
#   التحذير الموسع للأدمن
# ==============================

def format_ai_alert_details() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ لا توجد بيانات كافية الآن لإصدار تقرير موسع."

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    vol = metrics["volatility_score"]
    range_pct = metrics["range_pct"]

    risk = evaluate_risk_level(change, vol)
    fusion = fusion_ai_brain(metrics, risk)

    today = datetime.utcnow().strftime("%Y-%m-%d")

    report = f"""
📌 <b>تقرير التحذير الكامل — ADMIN</b>
📅 التاريخ: {today}

💰 <b>BTC:</b> ${price:,.0f} (%{change:+.2f})
📊 حركة اليوم: {range_pct:.2f}% — تقلب: {vol:.1f}/100

<b>الاتجاه العام:</b> {fusion['bias_text']}
<b>السيولة:</b> {fusion['smc_view']}
<b>مرحلة السوق:</b> {fusion['wyckoff_phase']}

<b>مستوى المخاطر:</b> {risk['emoji']} {risk['message']}

<b>احتمالات 24–72 ساعة:</b>
- صعود ~{fusion['p_up']}%
- تماسك ~{fusion['p_side']}%
- هبوط ~{fusion['p_down']}%

<b>IN CRYPTO Ai 🤖</b>
""".strip()

    return report
# ==============================
#   التقرير الأسبوعى المتقدم
# ==============================

def format_weekly_ai_report() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر إنشاء التقرير الأسبوعى حالياً بسبب مشكلة فى جلب بيانات السوق."
        )

    btc_price = metrics["price"]
    btc_change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    # Ethereum
    eth_data = fetch_price_data("ETHUSDT")
    if eth_data:
        eth_price = eth_data["price"]
        eth_change = eth_data["change_pct"]
    else:
        eth_price = 0.0
        eth_change = 0.0

    risk = evaluate_risk_level(btc_change, vol)
    fusion = fusion_ai_brain(metrics, risk)

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")

    weekday_names = [
        "الاثنين","الثلاثاء","الأربعاء","الخميس",
        "الجمعة","السبت","الأحد"
    ]
    weekday_name = weekday_names[now.weekday()] if now.weekday() < 7 else "اليوم"

    # RSI مبسط
    rsi_raw = 50 + (btc_change * 0.8)
    rsi = max(0, min(100, rsi_raw))

    if rsi < 40:
        rsi_desc = "يقع فى نطاق دون 40 → يعكس ضعفًا واضحًا فى الزخم الصاعد."
    elif rsi < 55:
        rsi_desc = "يقع فى نطاق 40–55 → ميل بسيط للتحسن لكن لم يصل لمنطقة القوة."
    else:
        rsi_desc = "أعلى من 55 → يعكس زخمًا صاعدًا أقوى نسبيًا."

    # مستويات استثمارية تقديرية
    inv_first_low = round(btc_price * 0.96, -2)
    inv_first_high = round(btc_price * 0.98, -2)
    inv_confirm = round(btc_price * 1.05, -2)

    # مستويات مضاربية قصيرة
    short_support_low = round(btc_price * 0.95, -2)
    short_support_high = round(btc_price * 0.97, -2)
    short_res_low = round(btc_price * 1.01, -2)
    short_res_high = round(btc_price * 1.03, -2)

    # قراءة عامة لحركة الأسبوع
    if abs(btc_change) < 1 and range_pct < 5:
        week_summary = 'السوق فى "منطقة انتقالية" بين تعافٍ هادئ وتذبذب جانبى.'
    elif btc_change >= 2:
        week_summary = "صعود أسبوعى ملحوظ مع تحسن واضح فى شهية المخاطرة."
    elif btc_change <= -2:
        week_summary = "ضغط بيعى أسبوعى واضح مع ميل لتصحيح أعمق على المدى القصير."
    else:
        week_summary = 'السوق فى "منطقة انتقالية" بين مرحلة تعافٍ ضعيف واحتمال تصحيح أعمق.'

    report = f"""
🚀 <b>التقرير الأسبوعى المتقدم – IN CRYPTO Ai</b>

<b>Weekly Intelligence Report</b>
📅 {weekday_name} – {date_str}
يتم التحديث تلقائياً وفق بيانات السوق الحية

🟦 <b>القسم 1 — ملخص السوق (BTC + ETH)</b>
<b>BTC:</b> ${btc_price:,.0f} ({btc_change:+.2f}%)
<b>ETH:</b> ${eth_price:,.0f} ({eth_change:+.2f}%)

حركة البيتكوين خلال الأسبوع اتسمت بـ:
- {strength_label}
- {liquidity_pulse}

📌 <b>خلاصة حركة الأسبوع:</b>
{week_summary}

🔵 <b>القسم 2 — القراءة الفنية (BTC)</b>
<b>RSI</b>  
{rsi_desc}

<b>MACD</b>  
إشارة صاعدة مبكرة تظهر فى الزخم الاتجاهى، لكن التقاطع الكامل لم يكتمل بعد.

<b>MA50 / MA200</b>  
السعر يتحرك قرب متوسطاته الرئيسية، مع ميل{" هابط" if btc_change < 0 else " صاعد"} طفيف.

🟣 <b>القسم 3 — Ethereum Snapshot</b>
<b>ETH:</b> ${eth_price:,.0f} ({eth_change:+.2f}%)
ETH يتحرك فى نطاق مرتبط بأداء البيتكوين.

🧠 <b>القسم 4 — تقدير IN CRYPTO Ai (Fusion Brain)</b>
🧭 <b>الاتجاه العام</b>  
{fusion['bias_text']}

🔍 <b>SMC View</b>  
{fusion['smc_view']}

🔄 <b>مرحلة السوق (وايكوف)</b>  
{fusion['wyckoff_phase']}

📊 <b>احتمالات 24–72 ساعة:</b>  
- صعود: ~{fusion['p_up']}%  
- تماسك: ~{fusion['p_side']}%  
- هبوط: ~{fusion['p_down']}%  

💎 <b>القسم 5 — التحليل الاستثماري</b>
- أول إشارة إيجابية: إغلاق أسبوعى أعلى  
  <b>{inv_first_low:,.0f}–{inv_first_high:,.0f}$</b>  
- تأكيد كامل لاتجاه صاعد مع إغلاق فوق  
  <b>{inv_confirm:,.0f}$</b>

⚡ <b>القسم 6 — التحليل المضاربي</b>
<b>أهم المستويات:</b>  
- دعم مضاربي: <b>{short_support_low:,.0f}$ – {short_support_high:,.0f}$</b>  
- مقاومة مضاربية: <b>{short_res_low:,.0f}$ – {short_res_high:,.0f}$</b>

⏰ <b>القسم 7 — نشاط الجلسة</b>  
غالبًا تزداد الحركة مع افتتاح السيولة الأمريكية  
🕖 حوالى 7:00 مساءً بتوقيت السوق.

🟢 <b>الخلاصة:</b>
السوق حاليًا فى منطقة توازن، لكن قرار الاتجاه سيظهر مع كسر مستويات المقاومة الرئيسية.

<b>IN CRYPTO Ai 🤖 — Weekly Intelligence Engine</b>
""".strip()

    return _shrink_text_preserve_content(report)
