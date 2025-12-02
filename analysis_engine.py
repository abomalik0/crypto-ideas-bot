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

        if r.status_code != 200:
            config.API_STATUS["binance_ok"] = False
            config.API_STATUS["binance_last_error"] = f"{r.status_code}: {r.text[:120]}"
            config.logger.info(
                "Binance error %s for %s: %s",
                r.status_code,
                symbol,
                r.text,
            )
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
            config.logger.info(
                "KuCoin error %s for %s: %s",
                r.status_code,
                symbol,
                r.text,
            )
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

    cache_key_binance = f"BINANCE:{binance_symbol}"
    cache_key_kucoin = f"KUCOIN:{kucoin_symbol}"

    cached = _get_cached(cache_key_binance)
    if cached:
        return cached

    cached = _get_cached(cache_key_kucoin)
    if cached:
        return cached

    data = fetch_from_binance(binance_symbol)
    if data:
        _set_cached(cache_key_binance, data)
        return data

    data = fetch_from_kucoin(kucoin_symbol)
    if data:
        _set_cached(cache_key_kucoin, data)
        return data

    return None

# ==============================
#  بناء Metrics
# ==============================

def build_symbol_metrics(
    price: float,
    change_pct: float,
    high: float,
    low: float,
) -> dict:
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

    return build_symbol_metrics(
        data["price"],
        data["change_pct"],
        data["high"],
        data["low"],
    )

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
            "المخاطر حاليًا منخفضة نسبيًا، السوق يتحرك بهدوء مع إمكانية "
            "الدخول بشرط الالتزام بمناطق وقف الخسارة."
        )
    elif risk_score < 50:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر حالياً متوسطة، الحركة السعرية بها تقلب واضح، "
            "ويُفضّل تقليل حجم الصفقات واستخدام إدارة مخاطر منضبطة."
        )
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر حالياً مرتفعة، السوق يشهد تقلبات قوية أو هبوط حاد، "
            "ويُفضّل تجنب الدخول العشوائى والتركيز على حماية رأس المال."
        )

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
        "score": risk_score,
    }

def _risk_level_ar(level: str) -> str:
    if level == "low":
        return "منخفض"
    if level == "medium":
        return "متوسط"
    if level == "high":
        return "مرتفع"
    return level

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

    if bias.startswith("strong_bullish") and "الدخول" in liquidity:
        smc_view = "سلوك أقرب لتجميع مؤسسى واضح مع دخول سيولة قوية."
    elif bias.startswith("bullish") and "الدخول" in liquidity:
        smc_view = "السوق يميل لتجميع ذكى هادئ مع تدرج فى بناء المراكز."
    elif bias.startswith("bearish") and "خروج" in liquidity:
        smc_view = "السوق يميل لتوزيع بيعى تدريجى وخروج سيولة من القمم."
    elif bias.startswith("strong_bearish"):
        smc_view = "مرحلة تصفية أو Panic جزئى مع بيع حاد عند الكسر."
    else:
        smc_view = "لا توجد علامة حاسمة على تجميع أو توزيع، الحركة أقرب لتوازن مؤقت."

    if vol < 20 and abs(change) < 1:
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
        f"احتمالات الحركة (24–72 ساعة تقريبية): صعود ~{p_up}٪ / تماسك ~{p_side}٪ / هبوط ~{p_down}٪."
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
#  دالة مساعدة لضبط طول رسالة تيليجرام
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
#   Institutional Smart Pulse Engine
#   (مرحلة C — أقصى مستوى داخل الخطة المجانية)
# ==============================

def _compute_volatility_regime(volatility_score: float, range_pct: float) -> str:
    """
    تصنيف وضع التقلب الحالى إلى:
    calm / normal / expansion / explosion
    """
    if volatility_score < 20 and range_pct < 3:
        return "calm"
    if volatility_score < 40 and range_pct < 5:
        return "normal"
    if volatility_score < 70 and range_pct < 8:
        return "expansion"
    return "explosion"


def update_market_pulse(metrics: dict) -> dict:
    """
    تحديث نبض السوق وتخزين آخر القراءات فى PULSE_HISTORY داخل config،
    مع حساب سرعة الحركة، التسارع، وثقة الاتجاه.
    هذه الدالة لا ترسل أى تنبيه، فقط تحضير بيانات للأنظمة الأعلى.
    """
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    regime = _compute_volatility_regime(vol, range_pct)

    # التعامل مع التاريخ المخزن فى config.PULSE_HISTORY بأمان
    history = getattr(config, "PULSE_HISTORY", None)
    if history is None:
        # احتياطى: لو لسبب ما PULSE_HISTORY غير معرف، ننشئ واحد خفيف
        from collections import deque
        history = deque(maxlen=30)
        config.PULSE_HISTORY = history  # type: ignore[assignment]

    # snapshot قبل الإضافة للحصول على النظام السابق
    prev_entry = history[-1] if len(history) > 0 else None
    prev_regime = prev_entry.get("regime") if isinstance(prev_entry, dict) else None

    now = time.time()
    entry = {
        "time": now,
        "price": float(price),
        "change_pct": float(change),
        "volatility_score": float(vol),
        "range_pct": float(range_pct),
        "regime": regime,
    }
    history.append(entry)

    hist_list = list(history)
    n = len(hist_list)

    # سرعة الحركة (Speed Index): متوسط التغير بين القراءات الأخيرة
    if n >= 2:
        diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(1, n)
        ]
        avg_diff = sum(diffs) / len(diffs) if diffs else 0.0
    else:
        avg_diff = 0.0

    # تسارع الحركة (Acceleration Index): الفرق بين آخر جزء وأول جزء من السلسلة
    if n >= 5:
        mid = max(2, n // 2)
        early_diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(1, mid)
        ]
        late_diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(mid, n)
        ]
        early_avg = sum(early_diffs) / len(early_diffs) if early_diffs else 0.0
        late_avg = sum(late_diffs) / len(late_diffs) if late_diffs else 0.0
        accel = late_avg - early_avg
    else:
        accel = 0.0

    # ثقة الاتجاه: نسبة القراءات الأخيرة فى نفس اتجاه التغير الحالى
    if n >= 3:
        recent = hist_list[-6:] if n >= 6 else hist_list
        same_sign_count = 0
        total = len(recent)
        for e in recent:
            c = e["change_pct"]
            if change > 0 and c > 0:
                same_sign_count += 1
            elif change < 0 and c < 0:
                same_sign_count += 1
        direction_confidence = (same_sign_count / total) * 100.0 if total else 0.0
    else:
        direction_confidence = 0.0

    # تقليم القيم لمقياس 0–100
    speed_index = max(0.0, min(100.0, avg_diff * 8.0))
    accel_index = max(-100.0, min(100.0, accel * 10.0))

    pulse = {
        "time": now,
        "price": price,
        "change_pct": change,
        "volatility_score": vol,
        "range_pct": range_pct,
        "regime": regime,
        "prev_regime": prev_regime,
        "speed_index": speed_index,
        "accel_index": accel_index,
        "direction_confidence": direction_confidence,
        "history_len": n,
    }

    return pulse


def detect_institutional_events(pulse: dict, metrics: dict, risk: dict) -> dict:
    """
    كشف الأحداث "المؤسسية" الأساسية على حسب نبض السوق والمخاطر الحالية.
    لا ترجع نصوص، فقط إشارات منطقية (Booleans) + قائمة بأسماء الأحداث النشطة.
    """
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    risk_level = risk["level"]

    speed = pulse["speed_index"]
    accel = pulse["accel_index"]
    regime = pulse["regime"]
    prev_regime = pulse.get("prev_regime")

    events = {
        "vol_explosion": False,
        "momentum_spike_down": False,
        "momentum_spike_up": False,
        "panic_drop": False,
        "liquidity_shock": False,
        "regime_switch": False,
    }

    # انفجار فى التقلب
    if regime == "explosion" or vol >= 75 or range_pct >= 8:
        events["vol_explosion"] = True

    # Momentum Spike لأعلى/لأسفل
    if abs(change) >= 2.5 and speed >= 35:
        if change > 0:
            events["momentum_spike_up"] = True
        else:
            events["momentum_spike_down"] = True

    # Panic Drop – هبوط حاد مع تقلب وخطر مرتفع
    if change <= -4 and (vol >= 55 or risk_level == "high"):
        events["panic_drop"] = True

    # Liquidity Shock – خروج سيولة عنيف تقريباً
    # تقريبية بناء على range + حركة اليوم
    if change <= -2.5 and range_pct >= 6 and vol >= 45:
        events["liquidity_shock"] = True

    # Regime Switch – انتقال واضح بين أوضاع التقلب
    if prev_regime and prev_regime != regime:
        events["regime_switch"] = True

    active_labels: list[str] = []
    if events["vol_explosion"]:
        active_labels.append("انفجار فى التقلب اليومى")
    if events["momentum_spike_down"]:
        active_labels.append("هبوط سريع (Momentum Spike Down)")
    if events["momentum_spike_up"]:
        active_labels.append("اندفاع صاعد قوى (Momentum Spike Up)")
    if events["panic_drop"]:
        active_labels.append("هبوط حاد يشبه Panic Drop")
    if events["liquidity_shock"]:
        active_labels.append("صدمة سيولة (Liquidity Shock)")
    if events["regime_switch"]:
        active_labels.append("تحول فى نمط السوق (Regime Switch)")

    events["active_labels"] = active_labels
    events["active_count"] = len(active_labels)
    return events


def classify_alert_level(
    metrics: dict,
    risk: dict,
    pulse: dict,
    events: dict,
) -> dict:
    """
    يحسب Shock Score (0–100) ومستوى التحذير:
    low / medium / high / critical
    """
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    speed = pulse["speed_index"]
    accel = pulse["accel_index"]
    direction_conf = pulse["direction_confidence"]
    risk_level = risk["level"]

    shock_score = 0.0

    # مساهمة من التقلب والمدى
    shock_score += min(40.0, vol * 0.4)
    shock_score += min(20.0, max(0.0, range_pct - 3.0) * 1.2)

    # مساهمة من التغير اليومى وسرعة الحركة
    shock_score += min(20.0, abs(change) * 2.0)
    shock_score += min(10.0, speed * 0.25)

    # تسارع عالى فى نفس اتجاه الهبوط يزيد الدرجة
    if change < 0 and accel > 0:
        shock_score += min(10.0, accel * 0.5)

    # المخاطر العامة
    if risk_level == "high":
        shock_score += 10.0
    elif risk_level == "medium":
        shock_score += 5.0

    # الأحداث المؤسسية
    if events.get("vol_explosion"):
        shock_score += 10.0
    if events.get("panic_drop"):
        shock_score += 15.0
    if events.get("liquidity_shock"):
        shock_score += 10.0
    if events.get("regime_switch"):
        shock_score += 5.0

    # تقليم
    shock_score = max(0.0, min(100.0, shock_score))

    # تحديد المستوى
    if shock_score >= 80 or events.get("panic_drop"):
        level = "critical"
    elif shock_score >= 60:
        level = "high"
    elif shock_score >= 40:
        level = "medium"
    elif shock_score >= 20:
        level = "low"
    else:
        level = None  # لا يتم إرسال تحذير ذكى فى هذه الحالة

    # ثقة الاتجاه مفيدة لو الهبوط ثابت
    trend_bias = "neutral"
    if direction_conf >= 65 and change < 0:
        trend_bias = "down_strong"
    elif direction_conf >= 65 and change > 0:
        trend_bias = "up_strong"
    elif 45 <= direction_conf < 65 and change != 0:
        trend_bias = "directional_soft"

    return {
        "level": level,
        "shock_score": round(shock_score, 1),
        "trend_bias": trend_bias,
    }


def compute_potential_zones(metrics: dict, pulse: dict, risk: dict) -> dict:
    """
    يحسب مناطق تقريبية محتملة للهبوط/الصعود (مش مستويات سحرية، بل نطاقات تقديرية)،
    لتستخدم فى رسائل التحذير (نازلين لفين / طالعين لفين).
    """
    price = metrics["price"]
    high = metrics["high"]
    low = metrics["low"]
    change = metrics["change_pct"]
    range_abs = max(0.0, high - low)

    # لو البيانات غير منطقية نستخدم مدى افتراضى صغير
    if range_abs <= 0:
        range_abs = price * 0.02  # 2%

    # مدى أساسى للاستخدام
    base_range = range_abs

    # لو التقلب عالى جداً نوسع النطاق
    vol = metrics["volatility_score"]
    if vol >= 70:
        base_range *= 1.2
    elif vol <= 25:
        base_range *= 0.8

    # مناطق هبوط تقديرية
    down_zone_1_low = price - 0.25 * base_range
    down_zone_1_high = price - 0.12 * base_range

    down_zone_2_low = price - 0.60 * base_range
    down_zone_2_high = price - 0.40 * base_range

    # مناطق صعود تقديرية
    up_zone_1_low = price + 0.12 * base_range
    up_zone_1_high = price + 0.25 * base_range

    up_zone_2_low = price + 0.40 * base_range
    up_zone_2_high = price + 0.70 * base_range

    # تحديد السيناريو الغالب
    if change <= -2.0 or risk["level"] == "high":
        dominant_scenario = "downside"
    elif change >= 2.0:
        dominant_scenario = "upside"
    else:
        # لو الحركة متذبذبة نعتبره نطاق جانبى
        dominant_scenario = "balanced"

    return {
        "dominant_scenario": dominant_scenario,
        "downside_zone_1": (round(down_zone_1_low, 2), round(down_zone_1_high, 2)),
        "downside_zone_2": (round(down_zone_2_low, 2), round(down_zone_2_high, 2)),
        "upside_zone_1": (round(up_zone_1_low, 2), round(up_zone_1_high, 2)),
        "upside_zone_2": (round(up_zone_2_low, 2), round(up_zone_2_high, 2)),
    }


def build_smart_alert_reason(
    metrics: dict,
    risk: dict,
    pulse: dict,
    events: dict,
    alert_level: dict,
    zones: dict,
) -> str:
    """
    يبنى نص مختصر يشرح سبب التحذير الذكى + يدمج الأحداث + المناطق المحتملة.
    هذا النص سيُستخدم داخل ثريد التنبيهات فى services.py.
    """
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]

    shock = alert_level["shock_score"]
    level = alert_level["level"]
    trend_bias = alert_level["trend_bias"]

    active_events = events.get("active_labels", [])
    scenario = zones["dominant_scenario"]

    risk_text = _risk_level_ar(risk["level"])

    # وصف الاتجاه القصير
    if trend_bias == "down_strong":
        trend_line = "الهبوط الحالى مدعوم بزخم هابط متماسك فى القراءات اللحظية."
    elif trend_bias == "up_strong":
        trend_line = "الصعود الحالى مدعوم بزخم إيجابى واضح فى القراءات اللحظية."
    elif trend_bias == "directional_soft":
        trend_line = "يوجد ميل اتجاهى واضح لكنه ما زال تحت الاختبار."
    else:
        trend_line = "قراءات الاتجاه اللحظى ما زالت متوازنة نسبيًا."

    parts: list[str] = []

    parts.append(
        f"مستوى التحذير الحالى: {level.upper()} — Shock Score ~ {shock} / 100."
    )
    parts.append(
        f"تغير البيتكوين خلال 24 ساعة حوالى %{change:+.2f} مع مدى يومى ≈ {range_pct:.2f}% وتقلب مقداره {vol:.1f} / 100."
    )
    parts.append(
        f"مستوى المخاطر العام حسب محرك المخاطر: {risk['emoji']} {risk_text}."
    )
    parts.append(trend_line)

    if active_events:
        parts.append(
            "الأحداث النشطة التى يلتقطها النظام الآن: " + " / ".join(active_events) + "."
        )

    # دمج معلومات المناطق المحتملة
    dz1_low, dz1_high = zones["downside_zone_1"]
    dz2_low, dz2_high = zones["downside_zone_2"]
    uz1_low, uz1_high = zones["upside_zone_1"]
    uz2_low, uz2_high = zones["upside_zone_2"]

    if scenario in ("downside", "balanced"):
        parts.append(
            f"مناطق هبوط تقريبية فى حالة استمرار نفس الزخم:\n"
            f"- منطقة أولى: {dz1_low:,.0f}$ – {dz1_high:,.0f}$\n"
            f"- منطقة ثانية أعمق: {dz2_low:,.0f}$ – {dz2_high:,.0f}$"
        )

    if scenario in ("upside", "balanced"):
        parts.append(
            f"ومناطق صعود تقريبية لو تحوّل الزخم لصالح المشترين:\n"
            f"- منطقة أولى: {uz1_low:,.0f}$ – {uz1_high:,.0f}$\n"
            f"- منطقة ثانية: {uz2_low:,.0f}$ – {uz2_high:,.0f}$"
        )

    parts.append(
        "هذه المستويات تقريبية تعليمية مبنية على حركة اليوم فقط، "
        "وليست توصية مباشرة بالشراء أو البيع."
    )

    return "\n".join(parts)


def compute_adaptive_interval(metrics: dict, pulse: dict, risk: dict) -> float:
    """
    يحسب الفترة المثالية بين فحوصات Smart Alert (بالثوانى)
    داخل الحدود [SMART_ALERT_MIN_INTERVAL, SMART_ALERT_MAX_INTERVAL].
    """
    min_iv = getattr(config, "SMART_ALERT_MIN_INTERVAL", 1.0)
    max_iv = getattr(config, "SMART_ALERT_MAX_INTERVAL", 5.0)

    change = metrics["change_pct"]
    vol = metrics["volatility_score"]
    speed = pulse["speed_index"]

    base_iv = max_iv

    # تقليل الفترة مع زيادة التقلب والسرعة
    if vol >= 75 or abs(change) >= 4:
        base_iv = min_iv
    elif vol >= 55 or abs(change) >= 2.5 or speed >= 40:
        base_iv = min_iv + (max_iv - min_iv) * 0.25  # 25% من المسافة
    elif vol >= 35 or abs(change) >= 1.0 or speed >= 25:
        base_iv = min_iv + (max_iv - min_iv) * 0.5  # 50% من المسافة
    else:
        base_iv = max_iv

    return max(min_iv, min(max_iv, base_iv))


def compute_smart_market_snapshot() -> dict | None:
    """
    الدالة الرئيسية التى سيستخدمها ثريد Smart Alert فى services.py.
    تقوم بـ:
        - جلب بيانات السوق الحالية
        - حساب المخاطر
        - تحديث Pulse
        - كشف الأحداث المؤسسية
        - حساب مستوى التحذير + Shock Score
        - حساب مناطق الهبوط/الصعود المحتملة
        - حساب الفترة التكيفية التالية
        - بناء سبب نصى مختصر للتحذير

    لا ترسل رسائل ولا تتعامل مع تيليجرام مباشرة.
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        return None

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    pulse = update_market_pulse(metrics)
    events = detect_institutional_events(pulse, metrics, risk)
    alert_level = classify_alert_level(metrics, risk, pulse, events)

    # لو مفيش مستوى تحذير (None) → نرجع snapshot لكن من غير سبب تحذير
    zones = compute_potential_zones(metrics, pulse, risk)
    interval = compute_adaptive_interval(metrics, pulse, risk)

    reason_text = None
    if alert_level["level"] is not None:
        reason_text = build_smart_alert_reason(
            metrics,
            risk,
            pulse,
            events,
            alert_level,
            zones,
        )

    snapshot = {
        "metrics": metrics,
        "risk": risk,
        "pulse": pulse,
        "events": events,
        "alert_level": alert_level,
        "zones": zones,
        "adaptive_interval": interval,
        "reason": reason_text,
    }

    return snapshot

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

    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))
    if rsi >= 70:
        rsi_trend = "⬆️ مرتفع (تشبّع شرائى محتمل)"
    elif rsi <= 30:
        rsi_trend = "⬇️ منخفض (تشبّع بيع محتمل)"
    else:
        rsi_trend = "🔁 حيادى نسبياً"

    if change > 2:
        trend_text = "الاتجاه العام يميل إلى الصعود مع زخم إيجابى ملحوظ."
    elif change > 0:
        trend_text = "الاتجاه العام يميل إلى الصعود بشكل هادئ."
    elif change > -2:
        trend_text = "الاتجاه العام يميل إلى الهبوط الخفيف مع بعض التذبذب."
    else:
        trend_text = "الاتجاه العام يميل إلى الهبوط مع ضغوط بيعية واضحة."

    metrics = build_symbol_metrics(price, change, high, low)
    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    fusion = fusion_ai_brain(metrics, risk)

    # 🧨 محرك مخاطر العملات الصغيرة / عالية التقلب
    micro_risks: list[str] = []

    if volume < 50_000:
        micro_risks.append(
            "حجم التداول الحالى منخفض جدًا مقارنة بمعظم العملات → أى صفقة كبيرة قد تحرك السعر بشكل حاد."
        )
    if abs(change) >= 25:
        micro_risks.append(
            "تغير سعرى يومى يتجاوز 25٪ → قد يشير لحركة Pump & Dump أو خبر قصير المدى."
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

    ai_note = (
        "🤖 <b>ملاحظة الذكاء الاصطناعى:</b>\n"
        "هذا التحليل يساعدك على فهم الاتجاه وحركة السعر، "
        "وليس توصية مباشرة بالشراء أو البيع.\n"
        "يُفضّل دائمًا دمج التحليل الفنى مع خطة إدارة مخاطر منضبطة.\n"
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

    risk_level = risk["level"]
    risk_emoji = risk["emoji"]
    risk_message = risk["message"]

    risk_level_text = _risk_level_ar(risk_level)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    fusion_line = (
        f"- قراءة IN CRYPTO Ai: {fusion['bias_text']} | "
        f"{fusion['smc_view']} | {fusion['wyckoff_phase']}"
    )

    report = f"""
✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو (مبنـى على حركة البيتكوين)</b>
📅 <b>التاريخ:</b> {today_str}

🏛 <b>نظرة عامة على البيتكوين:</b>
- السعر الحالى للبيتكوين: <b>${price:,.0f}</b>
- نسبة تغير آخر 24 ساعة: <b>%{change:+.2f}</b>

📈 <b>قوة الاتجاه (Market Strength):</b>
- {strength_label}
- مدى حركة اليوم بالنسبة للسعر: <b>{range_pct:.2f}%</b>
- درجة التقلب (من 0 إلى 100): <b>{volatility_score:.1f}</b>

💧 <b>نبض السيولة (Liquidity Pulse):</b>
- {liquidity_pulse}

🧠 <b>لمحة IN CRYPTO Ai عن السوق:</b>
- {fusion_line}

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- المخاطر حالياً عند مستوى: {risk_emoji} <b>{risk_level_text}</b>
- {risk_message}

📌 <b>تلميحات عامة للتداول:</b>
- ركّز على مناطق الدعم والمقاومة الواضحة بدلاً من مطاردة الحركة.
- فى أوقات التقلب، إدارة رأس المال أهم من عدد الصفقات.

<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return report

# ==============================
#   اختبار المخاطر السريع /risk_test
# ==============================

def format_risk_test() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات المخاطر حاليًا من المصدر.\n"
            "حاول مرة أخرى بعد قليل."
        )

    change = metrics["change_pct"]
    volatility_score = metrics["volatility_score"]
    risk = evaluate_risk_level(change, volatility_score)

    level_text = _risk_level_ar(risk["level"])

    msg = f"""
⚙️ <b>اختبار المخاطر السريع</b>

تغير البيتكوين خلال 24 ساعة: <b>%{change:+.2f}</b>
درجة التقلب الحالية: <b>{volatility_score:.1f}</b> / 100
المخاطر الحالية: {risk['emoji']} <b>{level_text}</b>

{risk['message']}

💡 هذه القراءة مبنية بالكامل على حركة البيتكوين الحالية بدون أى مزود بيانات إضافى.

<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return msg

# ==============================
#   نظام التحذير الذكى (Alerts)
# ==============================

def detect_alert_condition(metrics: dict, risk: dict) -> str | None:
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    risk_level = risk["level"]

    reasons = []

    if change <= -3:
        reasons.append("هبوط حاد فى البيتكوين أكبر من -3% خلال 24 ساعة.")
    elif change >= 4:
        reasons.append("صعود قوى وسريع فى البيتكوين أكبر من +4% خلال 24 ساعة.")

    if volatility_score >= 60 or range_pct >= 7:
        reasons.append("درجة التقلب مرتفعة بشكل ملحوظ فى الجلسة الحالية.")

    if risk_level == "high":
        reasons.append("محرك المخاطر يشير إلى مستوى مرتفع حالياً.")

    if not reasons:
        return None

    joined = " ".join(reasons)
    config.logger.info(
        "Alert condition detected: %s | price=%s change=%.2f range=%.2f vol=%.1f",
        joined,
        price,
        change,
        range_pct,
        volatility_score,
    )
    return joined

# ==============================
#   التحذير الموحد - /alert
# ==============================

def format_ai_alert() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        data = fetch_price_data("BTCUSDT")
        if not data:
            return "⚠️ تعذّر جلب بيانات البيتكوين حاليًا. حاول بعد قليل."

        price = data["price"]
        change = data["change_pct"]
        now = datetime.utcnow()
        weekday_names = [
            "الاثنين",
            "الثلاثاء",
            "الأربعاء",
            "الخميس",
            "الجمعة",
            "السبت",
            "الأحد",
        ]
        weekday_name = (
            weekday_names[now.weekday()]
            if 0 <= now.weekday() < len(weekday_names)
            else "اليوم"
        )
        date_part = now.strftime("%Y-%m-%d")

        fallback_text = f"""
⚠️ تنبيه هام — السوق يدخل مرحلة خطر

📅 اليوم: {weekday_name} — {date_part}
📉 البيتكوين الآن: {price:,.0f}$  (تغير 24 ساعة: {change:+.2f}%)

تعذّر جلب قراءات متقدمة للسوق فى هذه اللحظة،
لكن حركة البيتكوين الحالية تشير إلى تقلبات ملحوظة تستدعى الحذر فى القرارات.

<b>IN CRYPTO Ai 🤖</b>
""".strip()
        return fallback_text

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    risk_level_text = _risk_level_ar(risk["level"])
    risk_emoji = risk["emoji"]
    fusion = fusion_ai_brain(metrics, risk)

    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))
    if rsi >= 70:
        rsi_trend = "تشبّع شرائى محتمل"
    elif rsi <= 30:
        rsi_trend = "تشبّع بيع واضح"
    else:
        rsi_trend = "منطقة حيادية نسبياً"

    if change <= -3:
        dir_comment = "الاتجاه العام يميل بوضوح للهبوط مع ضغط بيعى متزايد."
    elif change < 0:
        dir_comment = "الاتجاه يميل للهبوط الهادئ مع ضعف فى المشترين."
    elif change < 2:
        dir_comment = "الاتجاه يتحسن تدريجيًا لكن بدون زخم صاعد قوى بعد."
    else:
        dir_comment = "الاتجاه يميل للصعود بزخم ملحوظ مع نشاط شرائى أعلى من المتوسط."

    intraday_support = round(low * 0.99, 2) if low > 0 else round(price * 0.95, 2)
    intraday_resistance = round(high * 1.01, 2) if high > 0 else round(price * 1.05, 2)
    swing_support = round(low * 0.97, 2) if low > 0 else round(price * 0.9, 2)
    swing_resistance = round(high * 1.03, 2) if high > 0 else round(price * 1.1, 2)

    now = datetime.utcnow()
    weekday_names = [
        "الاثنين",
        "الثلاثاء",
        "الأربعاء",
        "الخميس",
        "الجمعة",
        "السبت",
        "الأحد",
    ]
    weekday_name = (
        weekday_names[now.weekday()]
        if 0 <= now.weekday() < len(weekday_names)
        else "اليوم"
    )
    date_part = now.strftime("%Y-%m-%d")

    ai_summary_bullets = fusion["ai_summary"].split("\n")
    short_ai_summary = " / ".join(ai_summary_bullets[:3])

    alert_text = f"""
⚠️ <b>تنبيه هام — السوق يدخل منطقة حساسة</b>

📅 <b>اليوم:</b> {weekday_name} — {date_part}
📉 <b>البيتكوين الآن:</b> ${price:,.0f}  (تغير 24 ساعة: {change:+.2f}%)

🧭 <b>ملخص سريع لوضع السوق:</b>
• {dir_comment}
• {strength_label}
• مدى حركة اليوم بالنسبة للسعر: حوالى <b>{range_pct:.2f}%</b>
• درجة التقلب الحالية: <b>{volatility_score:.1f}</b> / 100
• نبض السيولة: {liquidity_pulse}
• مستوى المخاطر: {risk_emoji} <b>{risk_level_text}</b>

📉 <b>المؤشرات الفنية المختصرة:</b>
• قراءة RSI التقديرية: <b>{rsi:.1f}</b> → {rsi_trend}
• السعر يتحرك داخل نطاق يومى متقلب نسبياً.
• لا توجد إشارة انعكاس مكتملة حتى الآن، لكن الزخم يتغير بسرعة مع الأخبار والسيولة.

⚡️ <b>منظور مضارِبى (قصير المدى):</b>
• دعم حالي محتمل حول: <b>{intraday_support}$</b>
• مقاومة قريبة محتملة حول: <b>{intraday_resistance}$</b>
• الأفضل حاليًا: أحجام عقود صغيرة + وقف خسارة واضح أسفل مناطق الدعم.

💎 <b>منظور استثمارى (مدى متوسط):</b>
• السوق يتحرك داخل: <b>{fusion['wyckoff_phase']}</b>
• منطقة دعم عميقة تقريبية: قرب <b>{swing_support}$</b>
• تأكيد سيناريو صاعد أقوى يكون مع إغلاق أعلى من حوالى: <b>{swing_resistance}$</b>

🤖 <b>خلاصة IN CRYPTO Ai (نظرة مركزة):</b>
• الاتجاه العام: {fusion['bias_text']}
• سلوك السيولة: {fusion['smc_view']}
• ملخص الحالة الحالية: {short_ai_summary}
• تقدير حركة 24–72 ساعة:
  - صعود محتمل: ~<b>{fusion['p_up']}%</b>
  - تماسك جانبى: ~<b>{fusion['p_side']}%</b>
  - هبوط محتمل: ~<b>{fusion['p_down']}%</b>

🏁 <b>التوصية العامة من IN CRYPTO Ai:</b>
• ركّز على حماية رأس المال أولاً قبل البحث عن الفرص.
• تجنب القرارات الانفعالية وقت الأخبار أو حركات الشموع الكبيرة.
• انتظر اختراق أو كسر واضح لمناطق السعر الرئيسية قبل أى دخول عدوانى.

<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return alert_text

# ==============================
#   التحذير الموسع للأدمن
# ==============================

def format_ai_alert_details() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات السوق حالياً من المزود.\n"
            "حاول مرة أخرى بعد قليل."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    risk_level = risk["level"]
    risk_emoji = risk["emoji"]
    risk_message = risk["message"]

    fusion = fusion_ai_brain(metrics, risk)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    intraday_support = round(low * 0.99, 2) if low > 0 else round(price * 0.95, 2)
    intraday_resistance = round(high * 1.01, 2) if high > 0 else round(price * 1.05, 2)

    details = f"""
📌 <b>تقرير التحذير الكامل — /alert (IN CRYPTO Ai)</b>
📅 <b>التاريخ:</b> {today_str}
💰 <b>سعر البيتكوين الحالى:</b> ${price:,.0f}  (تغير 24 ساعة: % {change:+.2f})
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {volatility_score:.1f} / 100

1️⃣ <b>السوق العام</b>
- {strength_label}
- {liquidity_pulse}
- مستوى الخطر: {risk_emoji} <b>{_risk_level_ar(risk_level)}</b>
- {risk_message}

2️⃣ <b>ملخص الأسعار</b>
- أعلى سعر اليوم: <b>${high:,.0f}</b>
- أقل سعر اليوم: <b>${low:,.0f}</b>
- دعم يومى تقريبى: <b>{intraday_support}$</b>
- مقاومة يومية تقريبية: <b>{intraday_resistance}$</b>

3️⃣ <b>ملخص IN CRYPTO Ai (Fusion Brain)</b>
- الاتجاه: {fusion['bias_text']}
- SMC: {fusion['smc_view']}
- مرحلة السوق: {fusion['wyckoff_phase']}
- احتمالات 24–72 ساعة: صعود ~{fusion['p_up']}٪ / تماسك ~{fusion['p_side']}٪ / هبوط ~{fusion['p_down']}٪.

🧠 <b>خلاصة إدارية:</b>
- السوق غير مريح للمخاطرة العالية بدون خطة واضحة.
- الأفضل حالياً التركيز على مراقبة مناطق السعر الأساسية وإدارة رأس المال.

<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return details

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
        "الاثنين",
        "الثلاثاء",
        "الأربعاء",
        "الخميس",
        "الجمعة",
        "السبت",
        "الأحد",
    ]
    weekday_name = (
        weekday_names[now.weekday()]
        if 0 <= now.weekday() < len(weekday_names)
        else "اليوم"
    )

    rsi_raw = 50 + (btc_change * 0.8)
    rsi = max(0, min(100, rsi_raw))

    if rsi < 40:
        rsi_desc = "يقع فى نطاق دون 40 → يعكس ضعفًا واضحًا فى الزخم الصاعد."
    elif rsi < 55:
        rsi_desc = "يقع فى نطاق 40–55 → ميل بسيط للتحسن لكن لم يصل لمنطقة القوة."
    else:
        rsi_desc = "أعلى من 55 → يعكس زخمًا صاعدًا أقوى نسبيًا."

    inv_first_low = round(btc_price * 0.96, -2)
    inv_first_high = round(btc_price * 0.98, -2)
    inv_confirm = round(btc_price * 1.05, -2)

    short_support_low = round(btc_price * 0.95, -2)
    short_support_high = round(btc_price * 0.97, -2)
    short_res_low = round(btc_price * 1.01, -2)
    short_res_high = round(btc_price * 1.03, -2)

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
ظهور مبكر لهيستوجرام أخضر فى الزخم الاتجاهى، لكن التقاطع الصاعد الكامل لم يكتمل بعد.

<b>MA50 / MA200</b>
السعر يتحرك قريبًا من متوسطاته المتحركة الرئيسية، مع ميل قصير المدى نحو{" الهبوط" if btc_change < 0 else " الصعود الهادئ"}.

<b>السيولة</b>
خروج سيولة من القمم، ودخول متوسط من القيعان → سوق مضاربي أكثر منه استثمارى.

🟣 <b>القسم 3 — Ethereum Snapshot</b>
<b>ETH:</b> ${eth_price:,.0f} ({eth_change:+.2f}%)
ETH يتحرك فى اتجاه جانبى مرتبط بدرجة كبيرة بحركة البيتكوين.

🧠 <b>القسم 4 — تقدير IN CRYPTO Ai (Fusion Brain)</b>
🧭 <b>الاتجاه العام</b>
{fusion['bias_text']}

🔍 <b>SMC View</b>
{fusion['smc_view']}

🔄 <b>المرحلة الحالية (وايكوف)</b>
{fusion['wyckoff_phase']}

📊 <b>احتمالات 24–72 ساعة</b>
- صعود: ~{fusion['p_up']}%
- تماسك: ~{fusion['p_side']}%
- هبوط: ~{fusion['p_down']}%

💎 <b>القسم 5 — التحليل الاستثماري (Mid-Term)</b>
لكى يتحول الاتجاه إلى صاعد استثماريًا، يجب:
- إغلاق أسبوعى أعلى <b>{inv_first_low:,.0f}–{inv_first_high:,.0f}$</b> → إشارة إيجابية أولية.
- إغلاق واضح أعلى <b>{inv_confirm:,.0f}$</b> → تأكيد كامل للتحول الصاعد.

⚡ <b>القسم 6 — التحليل المضاربي (Short-Term)</b>
<b>أهم المستويات:</b>
- دعم مضاربي: <b>{short_support_low:,.0f}$ – {short_support_high:,.0f}$</b>
- مقاومة مضاربية: <b>{short_res_low:,.0f}$ – {short_res_high:,.0f}$</b>

<b>منظور المضاربين:</b>
- السوق ضعيف زخمًا نسبيًا.
- الدخول الأفضل بعد تأكيد اختراق <b>{short_res_low:,.0f}$</b>.

⏰ <b>القسم 7 — نشاط الجلسة</b>
من المتوقع زيادة حركة السعر خلال افتتاح السيولة الأمريكية
🕖 حوالى الساعة 7:00 مساءً بتوقيت السوق.

🟢 <b>الخلاصة النهائية</b>
- البيتكوين يتحرك عند <b>{btc_price:,.0f}$</b> قرب منطقة مقاومة حاسمة حول <b>{short_res_low:,.0f}$</b>.
- السوق يتعافى فنيًا… لكن الزخم غير مكتمل بعد.

<b>IN CRYPTO Ai 🤖 — Weekly Intelligence Engine</b>
""".strip()

    report = _shrink_text_preserve_content(report)
    return report
