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
#   (اتجاه + سيولة + Wyckoff + مخاطر)
# ==============================

def fusion_ai_brain(metrics: dict, risk: dict) -> dict:
    """
    يجمع بين:
      - الاتجاه (Bullish/Bearish)
      - سلوك السيولة
      - مرحلة وايكوف تقريبية
      - مستوى المخاطر
      - تقدير احتمالات السيناريوهات 24–72 ساعة
    """
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    strength = metrics["strength_label"]
    liquidity = metrics["liquidity_pulse"]
    risk_level = risk["level"]

    # -------- تحديد الاتجاه (Bias) --------
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

    # -------- سلوك السيولة (SMC View) --------
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

    # -------- مرحلة وايكوف تقريبية (Wyckoff Phase) --------
    abs_change = abs(change)

    if vol < 20 and abs_change < 1 and range_pct < 3:
        wyckoff_phase = "مرحلة تجميع / إعادة تجميع فى نطاق جانبى (Accumulation / Re-Accumulation)."
    elif vol >= 60 and abs_change >= 3 and range_pct >= 6:
        wyckoff_phase = "مرحلة اندفاع عالية التقلب (Impulse / Shakeout) مع حركات حادة فى الاتجاه."
    elif bias.startswith("strong_bullish") or (bias.startswith("bullish") and change >= 2):
        wyckoff_phase = "Phase صاعد (Mark-Up) مع غلبة واضحة للمشترين."
    elif bias.startswith("bullish"):
        wyckoff_phase = "انتقال صاعد / بداية Mark-Up بعد فترة تجميع."
    elif bias.startswith("strong_bearish") or (bias.startswith("bearish") and change <= -2):
        wyckoff_phase = "مرحلة هبوط / تصحيح ممتد (Mark-Down) مع ضغط بيعى واضح."
    elif bias.startswith("bearish"):
        wyckoff_phase = "مرحلة توزيع / تصحيح هابط (Distribution / Early Mark-Down)."
    else:
        wyckoff_phase = "منطقة انتقالية بين الصعود والهبوط بدون اتجاه مكتمل (Transitional Range)."

    # -------- تعليق المخاطر (Risk Comment) --------
    if risk_level == "high":
        risk_comment = (
            "مستوى المخاطر مرتفع، أى قرارات بدون خطة صارمة ومحددات وقف خسارة واضحة "
            "قد تكون مكلفة على المدى القصير."
        )
    elif risk_level == "medium":
        risk_comment = (
            "المخاطر متوسطة، يمكن العمل لكن بأحجام عقود محسوبة "
            "والالتزام التام بإدارة رأس المال."
        )
    else:
        risk_comment = (
            "المخاطر حاليًا أقرب للنطاق المنخفض، لكن يبقى الانضباط "
            "فى إدارة الصفقات أمرًا أساسيًا."
        )

    # -------- تقدير احتمالات السيناريوهات 24–72 ساعة --------
    if abs_change < 1 and vol < 25:
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
# ==============================

def _compute_volatility_regime(volatility_score: float, range_pct: float) -> str:
    if volatility_score < 20 and range_pct < 3:
        return "calm"
    if volatility_score < 40 and range_pct < 5:
        return "normal"
    if volatility_score < 70 and range_pct < 8:
        return "expansion"
    return "explosion"


def update_market_pulse(metrics: dict) -> dict:
    """
    تحديث نبض السوق وتخزين آخر القراءات فى PULSE_HISTORY داخل config
    مع حساب إحصائيات تاريخية (متوسط + انحراف معيارى + percentiles)
    لاستخدامها فى بناء قراءات ديناميكية أدق.
    """
    price = float(metrics["price"])
    change = float(metrics["change_pct"])
    range_pct = float(metrics["range_pct"])
    vol = float(metrics["volatility_score"])

    regime = _compute_volatility_regime(vol, range_pct)

    # -------- تهيئة / استخدام تاريخ النبض --------
    history = getattr(config, "PULSE_HISTORY", None)
    if history is None:
        from collections import deque
        maxlen = getattr(config, "PULSE_HISTORY_MAXLEN", 120)
        history = deque(maxlen=maxlen)
        config.PULSE_HISTORY = history  # type: ignore[assignment]

    prev_entry = history[-1] if len(history) > 0 else None
    prev_regime = prev_entry.get("regime") if isinstance(prev_entry, dict) else None

    now = time.time()
    entry = {
        "time": now,
        "price": price,
        "change_pct": change,
        "volatility_score": vol,
        "range_pct": range_pct,
        "regime": regime,
    }
    history.append(entry)

    hist_list = list(history)
    n = len(hist_list)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _std(values: list[float], m: float) -> float:
        if not values:
            return 0.0
        var = sum((v - m) ** 2 for v in values) / max(1, len(values) - 1)
        return var ** 0.5

    # -------- سرعة الحركة & التسارع مثل الإصدار القديم --------
    if n >= 2:
        diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(1, n)
        ]
        avg_diff = _mean(diffs)
    else:
        avg_diff = 0.0

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
        early_avg = _mean(early_diffs)
        late_avg = _mean(late_diffs)
        accel = late_avg - early_avg
    else:
        accel = 0.0

    # -------- ثقة الاتجاه من التاريخ القريب --------
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
        direction_conf = (same_sign_count / total) * 100.0 if total else 0.0
    else:
        direction_conf = 0.0

    # -------- baseline ديناميكى (متوسط + std + percentiles) --------
    if n >= 10:
        changes = [float(e["change_pct"]) for e in hist_list]
        vols = [float(e["volatility_score"]) for e in hist_list]
        ranges = [float(e["range_pct"]) for e in hist_list]

        mean_change = _mean(changes)
        std_change = _std(changes, mean_change)

        mean_vol = _mean(vols)
        std_vol = _std(vols, mean_vol)

        mean_range = _mean(ranges)
        std_range = _std(ranges, mean_range)

        sorted_vols = sorted(vols)
        rank = sum(1 for v in sorted_vols if v <= vol)
        vol_percentile = (rank / len(sorted_vols)) * 100.0 if sorted_vols else 0.0

        sorted_ranges = sorted(ranges)
        rank_r = sum(1 for v in sorted_ranges if v <= range_pct)
        range_percentile = (
            (rank_r / len(sorted_ranges)) * 100.0 if sorted_ranges else 0.0
        )
    else:
        mean_change = std_change = 0.0
        mean_vol = std_vol = 0.0
        mean_range = std_range = 0.0
        vol_percentile = range_percentile = 0.0

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
        "direction_confidence": direction_conf,
        "history_len": n,
        "mean_change": mean_change,
        "std_change": std_change,
        "mean_vol": mean_vol,
        "std_vol": std_vol,
        "mean_range": mean_range,
        "std_range": std_range,
        "vol_percentile": vol_percentile,
        "range_percentile": range_percentile,
    }

    return pulse


def detect_institutional_events(pulse: dict, metrics: dict, risk: dict) -> dict:
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

    if regime == "explosion" or vol >= 75 or range_pct >= 8:
        events["vol_explosion"] = True

    if abs(change) >= 2.5 and speed >= 35:
        if change > 0:
            events["momentum_spike_up"] = True
        else:
            events["momentum_spike_down"] = True

    if change <= -4 and (vol >= 55 or risk_level == "high"):
        events["panic_drop"] = True

    if change <= -2.5 and range_pct >= 6 and vol >= 45:
        events["liquidity_shock"] = True

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
    تصنيف مستوى التحذير بناءً على Shock Score ديناميك
    يعتمد على:
      - التقلب والمدى والتغير
      - سرعة الحركة
      - percentiles
      - الأحداث المؤسسية
      - مستوى المخاطر العام
    """
    change = float(metrics["change_pct"])
    range_pct = float(metrics["range_pct"])
    vol = float(metrics["volatility_score"])

    speed = float(pulse.get("speed_index", 0.0))
    accel = float(pulse.get("accel_index", 0.0))
    direction_conf = float(pulse.get("direction_confidence", 0.0))
    risk_level = risk["level"]

    vol_pct = float(pulse.get("vol_percentile", 0.0))
    range_pctile = float(pulse.get("range_percentile", 0.0))

    shock_score = 0.0

    shock_score += min(35.0, vol * 0.35)
    shock_score += min(20.0, max(0.0, range_pct - 3.0) * 1.2)
    shock_score += min(20.0, abs(change) * 2.0)
    shock_score += min(10.0, speed * 0.25)

    if vol_pct >= 80 or range_pctile >= 80:
        shock_score += 10.0

    if change < 0 and accel > 0:
        shock_score += min(10.0, accel * 0.5)

    if risk_level == "high":
        shock_score += 10.0
    elif risk_level == "medium":
        shock_score += 5.0

    if events.get("vol_explosion"):
        shock_score += 10.0
    if events.get("panic_drop"):
        shock_score += 15.0
    if events.get("liquidity_shock"):
        shock_score += 10.0
    if events.get("regime_switch"):
        shock_score += 5.0

    shock_score = max(0.0, min(100.0, shock_score))

    if shock_score >= 80 or events.get("panic_drop"):
        level = "critical"
    elif shock_score >= 60:
        level = "high"
    elif shock_score >= 40:
        level = "medium"
    elif shock_score >= 20:
        level = "low"
    else:
        level = None

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
    حساب مناطق الهبوط والصعود التقريبية بناءً على:
      - مدى اليوم الحالى (High-Low)
      - نظام التقلب (calm / normal / expansion / explosion)
      - مستوى المخاطر العام
    """
    price = float(metrics["price"])
    high = float(metrics["high"])
    low = float(metrics["low"])
    change = float(metrics["change_pct"])

    if price <= 0:
        price = max(1.0, abs(high) or abs(low) or 1.0)

    range_abs = max(0.0, high - low)
    if range_abs <= 0:
        range_abs = price * 0.02

    base_range = range_abs

    vol = float(metrics["volatility_score"])
    regime = pulse.get("regime")
    risk_level = risk["level"]

    if regime == "explosion" or vol >= 70:
        base_range *= 1.3
    elif regime == "expansion" or vol >= 50:
        base_range *= 1.1
    elif regime == "calm" and vol <= 20:
        base_range *= 0.8
    else:
        base_range *= 1.0

    if risk_level == "high":
        base_range *= 1.15
    elif risk_level == "low":
        base_range *= 0.9

    down_zone_1_low = price - 0.25 * base_range
    down_zone_1_high = price - 0.12 * base_range

    down_zone_2_low = price - 0.60 * base_range
    down_zone_2_high = price - 0.40 * base_range

    up_zone_1_low = price + 0.12 * base_range
    up_zone_1_high = price + 0.25 * base_range

    up_zone_2_low = price + 0.40 * base_range
    up_zone_2_high = price + 0.70 * base_range

    if change <= -2.0 or risk["level"] == "high":
        dominant_scenario = "downside"
    elif change >= 2.0:
        dominant_scenario = "upside"
    else:
        dominant_scenario = "balanced"

    return {
        "dominant_scenario": dominant_scenario,
        "downside_zone_1": (round(down_zone_1_low, 2), round(down_zone_1_high, 2)),
        "downside_zone_2": (round(down_zone_2_low, 2), round(down_zone_2_high, 2)),
        "upside_zone_1": (round(up_zone_1_low, 2), round(up_zone_1_high, 2)),
        "upside_zone_2": (round(up_zone_2_low, 2), round(up_zone_2_high, 2)),
        "downside_mid_1": round((down_zone_1_low + down_zone_1_high) / 2, 2),
        "downside_mid_2": round((down_zone_2_low + down_zone_2_high) / 2, 2),
        "upside_mid_1": round((up_zone_1_low + up_zone_1_high) / 2, 2),
        "upside_mid_2": round((up_zone_2_low + up_zone_2_high) / 2, 2),
    }

# ==============================
#   Early Movement Detector (UEWS Lite)
# ==============================

def detect_early_movement_signal(
    metrics: dict,
    pulse: dict,
    events: dict,
    risk: dict,
) -> dict | None:
    """
    رصد مبكر لحركة قوية محتملة (هبوط / صعود) قبل اكتمال الانفجار الكامل.
    الإصدار المحسّن يعتمد على:
      - Z-Score للتغير اليومى مقابل المتوسط التاريخى
      - Z-Score للتقلب والمدى
      - سرعة وتَسارع الحركة
      - أحداث مؤسسية
      - مستوى المخاطر العام
    """
    change = float(metrics["change_pct"])
    vol = float(metrics["volatility_score"])
    range_pct = float(metrics["range_pct"])
    risk_level = risk["level"]

    speed = float(pulse.get("speed_index", 0.0))
    accel = float(pulse.get("accel_index", 0.0))
    regime = pulse.get("regime")
    direction_conf = float(pulse.get("direction_confidence", 0.0))

    mean_change = float(pulse.get("mean_change", 0.0))
    std_change = float(pulse.get("std_change", 0.0)) or 0.0
    mean_vol = float(pulse.get("mean_vol", 0.0))
    std_vol = float(pulse.get("std_vol", 0.0)) or 0.0
    mean_range = float(pulse.get("mean_range", 0.0))
    std_range = float(pulse.get("std_range", 0.0)) or 0.0

    def _z(v: float, m: float, s: float) -> float:
        if s <= 0:
            return 0.0
        return (v - m) / s

    z_change = _z(change, mean_change, std_change)
    z_vol = _z(vol, mean_vol, std_vol)
    z_range = _z(range_pct, mean_range, std_range)

    score = 0.0
    direction: str | None = None
    reasons: list[str] = []

    if abs(z_change) >= 2.5:
        score += 25.0
        reasons.append("تغير يومى خارج النطاق المعتاد تاريخيًا (حركة شاذة قوية).")
    elif abs(z_change) >= 1.5:
        score += 15.0
        reasons.append("تغير يومى أعلى من المتوسط التاريخى بصورة واضحة.")

    if z_vol >= 2.0 or z_range >= 2.0:
        score += 20.0
        reasons.append("تقلب ومدى يومى أعلى بكثير من النمط المعتاد.")
    elif z_vol >= 1.0 or z_range >= 1.0:
        score += 10.0
        reasons.append("ارتفاع ملحوظ فى التقلب مقارنة بالقراءات السابقة.")

    if speed >= 40:
        score += 20.0
        reasons.append("زيادة واضحة فى سرعة الحركة اللحظية.")
    elif speed >= 25:
        score += 10.0
        reasons.append("سرعة الحركة فوق المتوسط بقليل.")

    if abs(accel) >= 10:
        score += 15.0
        reasons.append("تسارع حاد فى تغير الحركة خلال آخر قراءات.")
    elif abs(accel) >= 5:
        score += 8.0
        reasons.append("تسارع ملحوظ فى تغير الحركة.")

    if events.get("panic_drop"):
        score += 25.0
        direction = "down"
        reasons.append("إشارات Panic Drop مبكرة على البيتكوين.")
    if events.get("liquidity_shock"):
        score += 15.0
        reasons.append("صدمة سيولة محتملة تؤثر على الاستقرار.")
    if events.get("momentum_spike_down"):
        score += 15.0
        direction = "down"
        reasons.append("هبوط لحظى سريع (Momentum Spike Down).")
    if events.get("momentum_spike_up"):
        score += 15.0
        if direction is None:
            direction = "up"
        reasons.append("اندفاع صاعد سريع (Momentum Spike Up).")

    if direction is None:
        if change <= -1.5 and direction_conf >= 55:
            direction = "down"
        elif change >= 1.5 and direction_conf >= 55:
            direction = "up"

    if risk_level == "high":
        score += 10.0
    elif risk_level == "medium":
        score += 5.0

    if regime == "explosion":
        score += 5.0

    score = max(0.0, min(100.0, score))

    if score < 45.0 or direction is None:
        return None

    if score >= 80:
        window_minutes = 5
    elif score >= 65:
        window_minutes = 10
    else:
        window_minutes = 15

    confidence = min(100.0, score + (direction_conf * 0.25))
    reason_text = " ".join(reasons) if reasons else "إشارة مبكرة لحركة قوية محتملة."

    return {
        "active": True,
        "direction": direction,
        "score": round(score, 1),
        "confidence": round(confidence, 1),
        "window_minutes": window_minutes,
        "reason": reason_text,
    }

# ==============================
#   بناء النص التقليدى للتحذير (Smart Alert v1)
# ==============================

def build_smart_alert_reason(
    metrics: dict,
    risk: dict,
    pulse: dict,
    events: dict,
    alert_level: dict,
    zones: dict,
) -> str:
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
    min_iv = getattr(config, "SMART_ALERT_MIN_INTERVAL", 1.0)
    max_iv = getattr(config, "SMART_ALERT_MAX_INTERVAL", 5.0)

    change = metrics["change_pct"]
    vol = metrics["volatility_score"]
    speed = pulse["speed_index"]

    base_iv = max_iv

    if vol >= 75 or abs(change) >= 4:
        base_iv = min_iv
    elif vol >= 55 or abs(change) >= 2.5 or speed >= 40:
        base_iv = min_iv + (max_iv - min_iv) * 0.25
    elif vol >= 35 or abs(change) >= 1.0 or speed >= 25:
        base_iv = min_iv + (max_iv - min_iv) * 0.5
    else:
        base_iv = max_iv

    return max(min_iv, min(max_iv, base_iv))


def compute_smart_market_snapshot() -> dict | None:
    metrics = get_market_metrics_cached()
    if not metrics:
        return None

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    pulse = update_market_pulse(metrics)
    events = detect_institutional_events(pulse, metrics, risk)
    alert_level = classify_alert_level(metrics, risk, pulse, events)

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
#   Ultra Smart Snapshot + Message
# ==============================

def compute_ultra_smart_market_snapshot() -> dict | None:
    """
    نسخة موسعة من snapshot تشمل:
      - early_signal
      - fusion
      - نفس باقى العناصر
    لا تستبدل النسخة القديمة، بل تشتغل جنبًا إلى جنب.
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        return None

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    pulse = update_market_pulse(metrics)
    events = detect_institutional_events(pulse, metrics, risk)
    alert_level = classify_alert_level(metrics, risk, pulse, events)
    zones = compute_potential_zones(metrics, pulse, risk)
    interval = compute_adaptive_interval(metrics, pulse, risk)
    early_signal = detect_early_movement_signal(metrics, pulse, events, risk)
    fusion = fusion_ai_brain(metrics, risk)

    return {
        "metrics": metrics,
        "risk": risk,
        "pulse": pulse,
        "events": events,
        "alert_level": alert_level,
        "zones": zones,
        "adaptive_interval": interval,
        "early_signal": early_signal,
        "fusion": fusion,
    }


def format_ultra_smart_alert_from_snapshot(snapshot: dict) -> str:
    """
    صياغة رسالة التنبيه الاحترافية الواضحة للمستخدم العادى،
    مع التركيز على:
      - الاتجاه الأقوى الآن
      - الأهداف القادمة (هبوط/صعود) بأرقام مباشرة
      - درجة الاحتمال
      - ملخص بسيط للزخم والسيولة
    """
    metrics = snapshot.get("metrics", {})
    risk = snapshot.get("risk", {})
    pulse = snapshot.get("pulse", {})
    zones = snapshot.get("zones", {})
    fusion = snapshot.get("fusion") or fusion_ai_brain(metrics, risk)
    early = snapshot.get("early_signal")

    price = metrics.get("price", 0.0)
    change = metrics.get("change_pct", 0.0)
    volatility = metrics.get("volatility_score", 0.0)

    speed_index = pulse.get("speed_index", 0.0)
    liquidity_text = metrics.get("liquidity_pulse", "")

    if "خروج" in liquidity_text or "تصريف" in liquidity_text:
        liquidity_pressure = 75.0
    elif "الدخول" in liquidity_text or "تجميع" in liquidity_text:
        liquidity_pressure = 60.0
    elif "متوازنة" in liquidity_text:
        liquidity_pressure = 40.0
    else:
        liquidity_pressure = 50.0

    dz1_low, dz1_high = zones.get("downside_zone_1", (price * 0.97, price * 0.99))
    dz2_low, dz2_high = zones.get("downside_zone_2", (price * 0.94, price * 0.97))
    uz1_low, uz1_high = zones.get("upside_zone_1", (price * 1.01, price * 1.03))
    uz2_low, uz2_high = zones.get("upside_zone_2", (price * 1.03, price * 1.06))

    d1_mid = zones.get("downside_mid_1") or round((dz1_low + dz1_high) / 2, 2)
    d2_mid = zones.get("downside_mid_2") or round((dz2_low + dz2_high) / 2, 2)
    u1_mid = zones.get("upside_mid_1") or round((uz1_low + uz1_high) / 2, 2)
    u2_mid = zones.get("upside_mid_2") or round((uz2_low + uz2_high) / 2, 2)

    prob_up = fusion.get("p_up", 0)
    prob_down = fusion.get("p_down", 0)
    prob_side = fusion.get("p_side", 0)

    direction_final = "تذبذب / حركة جانبية"
    expected_direction_strong = "السوق يميل إلى حركة جانبية مع احتمالات خداع فى الاتجاهين."
    dominant_prob = max(prob_up, prob_down, prob_side)

    if prob_down >= prob_up + 10 and prob_down >= prob_side:
        direction_final = "هبوط"
        expected_direction_strong = "السوق يميل بوضوح إلى سيناريو هابط إذا استمر نفس الزخم."
        dominant_prob = prob_down
    elif prob_up >= prob_down + 10 and prob_up >= prob_side:
        direction_final = "صعود"
        expected_direction_strong = "السوق يميل إلى سيناريو صاعد مع تحسن ملحوظ فى الزخم."
        dominant_prob = prob_up

    direction_reason_line = fusion.get("bias_text", "")

    if early and early.get("active"):
        dir_ar = "هابط" if early["direction"] == "down" else "صاعد"
        direction_reason_line = (
            f"نظام التحذير المبكر يلتقط إشارة {dir_ar} بدرجة ثقة تقارب "
            f"{early['confidence']:.0f}/100 خلال {early['window_minutes']} دقيقة قادمة. "
            f"{early['reason']}"
        )
        if early["direction"] == "down" and direction_final != "صعود":
            direction_final = "هبوط"
            dominant_prob = max(dominant_prob, prob_down, 70)
        elif early["direction"] == "up" and direction_final != "هبوط":
            direction_final = "صعود"
            dominant_prob = max(dominant_prob, prob_up, 70)

    momentum_note = metrics.get("strength_label", "")
    liquidity_note = liquidity_text
    trend_sentence = fusion.get("bias_text", "")

    prob_up_int = int(round(prob_up))
    prob_down_int = int(round(prob_down))
    dominant_prob_int = int(round(dominant_prob))

    msg = f"""
🚨 <b>تنبيه فورى — اتجاه واضح يتكوّن الآن</b>

💰 <b>السعر الحالى:</b> {price:,.0f}$
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
⚡ <b>قوة التقلب:</b> {volatility:.1f} / 100
🏃 <b>سرعة الزخم:</b> {speed_index:.1f} / 100
💧 <b>ضغط السيولة (تقديرى):</b> {liquidity_pressure:.1f} / 100

🎯 <b>الخلاصة المباشرة — السوق رايح على فين؟</b>
• الاتجاه الأقوى الآن: <b>{direction_final}</b>
• السبب الرئيسى: {direction_reason_line}
• قوة هذا السيناريو حاليًا: <b>~{dominant_prob_int}%</b>

📉 <b>لو السوق كمل هبوط:</b>
• الهدف الأول: <b>{d1_mid:,.0f}$</b>
• الهدف الثانى: <b>{d2_mid:,.0f}$</b>
• احتمال سيناريو الهبوط: <b>~{prob_down_int}%</b>

📈 <b>لو حصل انعكاس وصعود:</b>
• الهدف الأول: <b>{u1_mid:,.0f}$</b>
• الهدف الثانى: <b>{u2_mid:,.0f}$</b>
• احتمال سيناريو الصعود: <b>~{prob_up_int}%</b>

🧠 <b>ملخص IN CRYPTO Ai:</b>
• الاتجاه العام: {trend_sentence}
• قوة الحركة اللحظية: {momentum_note}
• وضع السيولة: {liquidity_note}
• حركة 1–3 ساعات القادمة (تقديرية): {expected_direction_strong}

⚠️ <b>تنويه:</b>
هذا تنبيه ذكاء اصطناعى لحظى يوضح السيناريو الأقوى والأهداف المتوقعة بشكل مباشر،
وليس توصية صريحة بالشراء أو البيع.

<b>IN CRYPTO Ai 🤖 — Ultra Smart Alert Engine</b>
""".strip()

    return _shrink_text_preserve_content(msg)

# ==============================
#     صياغة رسالة التحليل /coin
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
        f"- المرحلة الحالية (وايكوف): {fusion['wyckoff_phase']}\n"
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
#   نظام التحذير الذكى (Alerts) /alert
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
#   التحذير الموحد /alert
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
• السوق يتحرك داخل: {fusion['wyckoff_phase']}
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
- تعليق المخاطر: {fusion['risk_comment']}
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

# ==============================
#   Hybrid PRO Direction Engine
# ==============================

def compute_hybrid_pro_core() -> dict | None:
    """
    نواة التحليل المؤسسى الاحترافى:
      - دمج Smart Snapshot + Fusion AI + Pulse Engine + Zones
      - استخراج اتجاه واضح + أهداف هبوط/صعود + نسب احتمالات
      - إدماج نظام التحذير المبكر Early Warning داخل القرار
    """
    snapshot = compute_smart_market_snapshot()
    if not snapshot:
        return None

    metrics = snapshot["metrics"]
    risk = snapshot["risk"]
    pulse = snapshot["pulse"]
    events = snapshot["events"]
    zones = snapshot["zones"]
    alert_level = snapshot["alert_level"]

    fusion = fusion_ai_brain(metrics, risk)

    price = float(metrics["price"])
    change = float(metrics["change_pct"])
    range_pct = float(metrics["range_pct"])
    vol = float(metrics["volatility_score"])
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    speed_index = float(pulse.get("speed_index", 0.0))
    accel_index = float(pulse.get("accel_index", 0.0))
    direction_conf = float(pulse.get("direction_confidence", 0.0))

    level = alert_level.get("level")
    shock_score = float(alert_level.get("shock_score", 0.0))
    trend_bias = alert_level.get("trend_bias", "neutral")

    liquidity_pressure = 50.0
    lp = (liquidity_pulse or "") + " " + (strength_label or "")

    if "خروج" in lp or "هبوط" in lp or "ضغوط بيعية" in lp:
        liquidity_pressure = 70.0
    if "تصريف" in lp or "Panic" in lp or "تصفية" in lp:
        liquidity_pressure = 85.0
    if "الدخول" in lp or "تجميع" in lp:
        liquidity_pressure = 65.0
    if "متوازنة" in lp:
        liquidity_pressure = 50.0

    if change < 0:
        liquidity_pressure += 5.0
    elif change > 0:
        liquidity_pressure -= 3.0

    liquidity_pressure = max(0.0, min(100.0, liquidity_pressure))

    p_up = fusion["p_up"]
    p_down = fusion["p_down"]
    p_side = fusion["p_side"]

    if trend_bias == "down_strong" or (change <= -2.0 and p_down >= p_up):
        trend_word = "هبوط"
    elif trend_bias == "up_strong" or (change >= 2.0 and p_up >= p_down):
        trend_word = "صعود"
    else:
        trend_word = "تماسك / حركة جانبية"

    events_labels = events.get("active_labels", []) or []
    if events_labels:
        reason_short = "النظام يلتقط حالياً: " + " / ".join(events_labels)
    else:
        if vol >= 60 and abs(change) >= 3:
            reason_short = "زيادة قوية فى التقلب مع حركة سعرية حادة."
        elif liquidity_pressure >= 70:
            reason_short = "خروج سيولة ملحوظ من السوق مع ضعف المشترين."
        elif liquidity_pressure <= 40:
            reason_short = "دخول سيولة ملحوظ يدعم الاتجاه الحالى."
        else:
            reason_short = "توازن نسبى فى السيولة مع مراقبة حذرة للاتجاه."

    if speed_index >= 60 and abs(accel_index) >= 10:
        momentum_note = "الحركة الحالية سريعة ومُتسارعة بشكل واضح (Momentum عالى)."
    elif speed_index >= 35:
        momentum_note = "يوجد زخم نشط فى الحركة لكن ليس عند أقصى درجات السرعة."
    elif speed_index <= 15:
        momentum_note = "سرعة الحركة ضعيفة نسبياً والزخم منخفض."
    else:
        momentum_note = "سرعة الحركة متوسطة مع زخم قابل للتغير سريعاً."

    if liquidity_pressure >= 75:
        liquidity_note = "ضغط سيولة هابط واضح (خروج أموال من السوق)."
    elif liquidity_pressure >= 60:
        liquidity_note = "ميل واضح لخروج السيولة أكثر من دخولها."
    elif liquidity_pressure <= 35:
        liquidity_note = "ميل واضح لدخول سيولة جديدة تدعم الاتجاه الصاعد."
    elif liquidity_pressure <= 50:
        liquidity_note = "السيولة متوازنة نسبياً بين المشترين والبائعين."
    else:
        liquidity_note = "لا يوجد حتى الآن انحراف حاد فى سلوك السيولة."

    if trend_word == "هبوط":
        expected_direction_strong = (
            "القراءات الحالية ترجّح سيناريو هبوط قادم أو استمرار للضغط البيعى "
            "مع احتمالية زيارة مستويات أدنى قبل أى تعافٍ واضح."
        )
    elif trend_word == "صعود":
        expected_direction_strong = (
            "القراءات الحالية ترجّح سيناريو صعود أو استمرار زخم شرائى "
            "مع استهداف مستويات أعلى إذا استمر نفس الإيقاع."
        )
    else:
        expected_direction_strong = (
            "السوق يميل إلى حركة جانبية/تماسك مع غياب اتجاه حاسم، "
            "وأى كسر واضح لأحد الأطراف قد يفتح حركة قوية فى نفس الاتجاه."
        )

    early = detect_early_movement_signal(metrics, pulse, events, risk)
    if early and early.get("active"):
        try:
            dir_txt = "هابط" if early["direction"] == "down" else "صاعد"
            expected_direction_strong = (
                f"⚠️ نظام التحذير المبكر يلتقط حالياً إشارة {dir_txt} قوية "
                f"بدرجة ثقة تقارب {early['confidence']:.0f}/100 خلال "
                f"{early['window_minutes']} دقيقة قادمة. {early['reason']}"
            )
            if early["direction"] == "down":
                trend_word = "هبوط"
            elif early["direction"] == "up":
                trend_word = "صعود"
        except Exception:
            pass
    else:
        early = None

    dz1_low, dz1_high = zones["downside_zone_1"]
    dz2_low, dz2_high = zones["downside_zone_2"]
    uz1_low, uz1_high = zones["upside_zone_1"]
    uz2_low, uz2_high = zones["upside_zone_2"]

    core = {
        "price": round(price, 2),
        "change": round(change, 2),
        "range_pct": round(range_pct, 2),
        "volatility_score": round(vol, 1),
        "shock_score": shock_score,
        "level": level,
        "trend_bias": trend_bias,
        "trend_word": trend_word,
        "expected_direction_strong": expected_direction_strong,
        "prob_up": p_up,
        "prob_down": p_down,
        "prob_side": p_side,
        "speed_index": round(speed_index, 1),
        "accel_index": round(accel_index, 1),
        "liquidity_pressure": round(liquidity_pressure, 1),
        "liquidity_note": liquidity_note,
        "momentum_note": momentum_note,
        "trend_sentence": fusion["bias_text"],
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
        "reason_short": reason_short,
        "down_zone_1": (dz1_low, dz1_high),
        "down_zone_2": (dz2_low, dz2_high),
        "up_zone_1": (uz1_low, uz1_high),
        "up_zone_2": (uz2_low, uz2_high),
        "early_signal": early,
    }

    return core

# ==============================
#   C-Level Institutional Block
# ==============================

def build_c_level_institutional_block(core: dict) -> str:
    price = core.get("price", 0.0)
    change = core.get("change", 0.0)
    vol = core.get("volatility_score", 0.0)
    shock = core.get("shock_score", 0.0)
    level = core.get("level")
    trend_word = core.get("trend_word", "غير محدد")
    trend_sentence = core.get("trend_sentence", "")
    liquidity_note = core.get("liquidity_note", "")
    momentum_note = core.get("momentum_note", "")
    prob_up = core.get("prob_up", 0)
    prob_down = core.get("prob_down", 0)
    prob_side = core.get("prob_side", 0)

    if level == "critical":
        level_label = "حرِج جدًا"
    elif level == "high":
        level_label = "مرتفع"
    elif level == "medium":
        level_label = "متوسط"
    elif level == "low":
        level_label = "مراقبة هادئة"
    else:
        level_label = "طبيعى"

    block = (
        "🏛 <b>ملخص مؤسسى (C-Level View):</b>\n"
        f"• وضع البيتكوين الآن: <b>{price:,.0f}$</b> | تغير 24 ساعة: <b>%{change:+.2f}</b>\n"
        f"• تصنيف حالة السوق: <b>{level_label}</b> "
        f"(Shock Score ≈ {shock:.1f} / 100 ، تقلب ≈ {vol:.1f} / 100)\n"
        f"• الاتجاه السائد: <b>{trend_word}</b> — {trend_sentence}\n"
        f"• السيولة والزخم: {liquidity_note} / {momentum_note}\n"
        f"• توزيع الاحتمالات 24–72 ساعة: صعود ~{prob_up}% / "
        f"تماسك ~{prob_side}% / هبوط ~{prob_down}%"
    )
    return block

# ==============================
#   بلوك الأهداف المبكر
# ==============================

def _build_directional_targets_block(core: dict) -> str:
    try:
        price = float(core.get("price") or 0.0)
        trend_word = core.get("trend_word") or "غير محدد"
        range_pct = float(core.get("range_pct") or 0.0)
        vol = float(core.get("volatility_score") or 0.0)
        shock = float(core.get("shock_score") or 0.0)
        speed_idx = float(core.get("speed_index") or 0.0)
        accel_idx = float(core.get("accel_index") or 0.0)
        prob_up = float(core.get("prob_up") or 0.0)
        prob_down = float(core.get("prob_down") or 0.0)
        prob_side = float(core.get("prob_side") or 0.0)
        liquidity_note = core.get("liquidity_note") or ""
        momentum_note = core.get("momentum_note") or ""
        reason_short = core.get("reason_short") or ""
        early = core.get("early_signal")
    except Exception:
        return ""

    if price <= 0:
        return ""

    dz1_low, dz1_high = core.get("down_zone_1", (price * 0.97, price * 0.99))
    dz2_low, dz2_high = core.get("down_zone_2", (price * 0.94, price * 0.97))
    uz1_low, uz1_high = core.get("up_zone_1", (price * 1.01, price * 1.03))
    uz2_low, uz2_high = core.get("up_zone_2", (price * 1.03, price * 1.06))

    d1_mid = round((dz1_low + dz1_high) / 2, 2)
    d2_mid = round((dz2_low + dz2_high) / 2, 2)
    u1_mid = round((uz1_low + uz1_high) / 2, 2)
    u2_mid = round((uz2_low + uz2_high) / 2, 2)

    direction = None

    if prob_down >= prob_up + 10 and prob_down >= prob_side:
        direction = "down"
    elif prob_up >= prob_down + 10 and prob_up >= prob_side:
        direction = "up"
    else:
        if "هبوط" in trend_word:
            direction = "down"
        elif "صعود" in trend_word:
            direction = "up"

    if early and early.get("active"):
        try:
            if early["direction"] == "down":
                direction = "down"
            elif early["direction"] == "up":
                direction = "up"
        except Exception:
            pass

    if not direction:
        return ""

    intensity = (
        abs(core.get("change", 0.0)) * 0.7
        + vol * 0.5
        + speed_idx * 0.4
        + abs(accel_idx) * 0.8
        + shock * 0.3 / 10.0
    )

    if early and early.get("active"):
        window = int(early.get("window_minutes", 15))
        if window <= 10:
            time_hint = (
                f"⏱ الإطار الزمنى المرجّح: خلال <b>{window} دقيقة تقريبًا</b> "
                "لو استمر نفس الزخم الحالى."
            )
        else:
            time_hint = (
                f"⏱ الإطار الزمنى المرجّح: خلال <b>{window}–30 دقيقة</b> "
                "مع مراقبة تغير سرعة الحركة."
            )
    else:
        if intensity >= 30 or speed_idx >= 70 or abs(accel_idx) >= 10:
            time_hint = (
                "⏱ الإطار الزمنى المرجّح: خلال <b>دقائق إلى ساعة</b> فى حال استمرار نفس الزخم."
            )
        elif intensity >= 18:
            time_hint = (
                "⏱ الإطار الزمنى المرجّح: خلال <b>1 – 3 ساعات</b> القادمة."
            )
        else:
            time_hint = (
                "⏱ الإطار الزمنى المرجّح: خلال <b>جلسة اليوم</b> ما لم يهدأ الزخم."
            )

    reasons_lines: list[str] = []
    if reason_short:
        reasons_lines.append(reason_short)
    if liquidity_note:
        reasons_lines.append(f"سلوك السيولة: {liquidity_note}")
    if momentum_note:
        reasons_lines.append(f"سلوك الزخم: {momentum_note}")
    if early and early.get("active"):
        try:
            dir_ar = "هابط" if early["direction"] == "down" else "صاعد"
            reasons_lines.append(
                f"إضافة إلى ذلك، نظام التحذير المبكر يلتقط إشارة {dir_ar} "
                f"بدرجة ثقة ~{early['confidence']:.0f}/100."
            )
        except Exception:
            pass

    if not reasons_lines:
        reasons_lines.append(
            "لا توجد إشارة واحدة مسيطرة، لكن تداخل السيولة والزخم يعطى هذا الاتجاه أفضلية نسبية."
        )

    dir_txt = "🔻 <b>سيناريو هبوط متوقع</b>" if direction == "down" else "🔼 <b>سيناريو صعود متوقع</b>"

    lines = [
        "🎯 <b>أهداف الحركة المتوقعة (قراءة مبكرة دقيقة)</b>",
        "",
        dir_txt,
        f"- السعر الحالى تقريباً: <code>{price:,.0f}$</code>",
    ]

    if direction == "down":
        lines.append(
            f"- الهدف الأول الأقرب: <b>{d1_mid:,.0f}$</b>  (منطقة {dz1_low:,.0f}$ – {dz1_high:,.0f}$)"
        )
        lines.append(
            f"- الهدف الثانى الأعمق: <b>{d2_mid:,.0f}$</b>  (منطقة {dz2_low:,.0f}$ – {dz2_high:,.0f}$)"
        )
    else:
        lines.append(
            f"- الهدف الأول الأقرب: <b>{u1_mid:,.0f}$</b>  (منطقة {uz1_low:,.0f}$ – {uz1_high:,.0f}$)"
        )
        lines.append(
            f"- الهدف الثانى الأوسع: <b>{u2_mid:,.0f}$</b>  (منطقة {uz2_low:,.0f}$ – {uz2_high:,.0f}$)"
        )

    lines.append(time_hint)

    lines.append("")
    lines.append("📌 <b>سبب الحركة من منظور IN CRYPTO Ai:</b>")
    for r in reasons_lines:
        lines.append(f"- {r}")

    lines.append("")
    lines.append(
        "⚠️ هذه الأهداف تعليمية مبنية على بيانات البيتكوين اللحظية "
        "وليست توصية مباشرة بالدخول أو الخروج."
    )

    return "\n".join(lines)

# ==============================
#   Ultra PRO Alert
# ==============================

def format_ultra_pro_alert():
    core = compute_hybrid_pro_core()
    if not core:
        return (
            "⚠️ تعذّر إنشاء Ultra PRO Alert حاليًا بسبب مشكلة فى جلب بيانات السوق.\n"
            "حاول مرة أخرى بعد قليل."
        )

    try:
        price = core.get("price", 0.0)
        change = core.get("change", 0.0)
        range_pct = core.get("range_pct", 0.0)
        vol = core.get("volatility_score", 0.0)
        shock = core.get("shock_score", 0.0)
        level = core.get("level")

        trend_word = core.get("trend_word", "غير محدد")
        trend_sentence = core.get("trend_sentence", "")

        momentum_note = core.get("momentum_note", "")
        liquidity_note = core.get("liquidity_note", "")
        liquidity_pressure = core.get("liquidity_pressure", 0.0)

        speed_idx = core.get("speed_index", 0.0)
        accel_idx = core.get("accel_index", 0.0)

        strength_label = core.get("strength_label", "")
        liquidity_pulse = core.get("liquidity_pulse", "")
        reason_short = core.get("reason_short", "")
        expected_direction_strong = core.get("expected_direction_strong", "")

        prob_up = int(round(core.get("prob_up", 0)))
        prob_down = int(round(core.get("prob_down", 0)))
        prob_side = int(round(core.get("prob_side", 0)))

        dz1_low, dz1_high = core.get("down_zone_1", (price * 0.97, price * 0.99))
        dz2_low, dz2_high = core.get("down_zone_2", (price * 0.94, price * 0.97))
        uz1_low, uz1_high = core.get("up_zone_1", (price * 1.01, price * 1.03))
        uz2_low, uz2_high = core.get("up_zone_2", (price * 1.03, price * 1.06))

        d1_mid = round((dz1_low + dz1_high) / 2, 2)
        d2_mid = round((dz2_low + dz2_high) / 2, 2)
        u1_mid = round((uz1_low + uz1_high) / 2, 2)
        u2_mid = round((uz2_low + uz2_high) / 2, 2)

        if level == "critical":
            level_label = "حرِج جدًا"
        elif level == "high":
            level_label = "مرتفع"
        elif level == "medium":
            level_label = "متوسط"
        elif level == "low":
            level_label = "مراقبة هادئة"
        else:
            level_label = "طبيعى"

        c_level_block = build_c_level_institutional_block(core)

        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        msg = f"""
🚨 <b>تنبيه فورى — اندفاع {trend_word} قوى يتفعّل الآن!</b>

📅 <b>التاريخ:</b> {today_str}
💰 <b>السعر الحالى:</b> {price:,.0f}$
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {vol:.1f} / 100
⚡ <b>سرعة الزخم اللحظى:</b> {speed_idx:.1f} / 100
🏃 <b>تسارع الحركة:</b> {accel_idx:.1f}
💧 <b>ضغط السيولة التقديرى:</b> {liquidity_pressure:.1f} / 100

<b>🎯 الخلاصة المباشرة:</b>
• الاتجاه الأقوى الآن: <b>{trend_word}</b>
• السبب الرئيسى: {reason_short}
• مستوى حالة السوق: <b>{level_label}</b> (Shock Score ≈ {shock:.1f}/100)

━━━━━━━━━━━━━━━━━━
📉 <b>لو استمر سيناريو الهبوط:</b>
• الهدف الأول: <b>{d1_mid:,.0f}$</b>
• الهدف الثانى: <b>{d2_mid:,.0f}$</b>
• نطاق الهبوط المتوقع: {dz1_low:,.0f}$ → {dz2_high:,.0f}$

📈 <b>لو حدث انعكاس وصعود:</b>
• الهدف الأول: <b>{u1_mid:,.0f}$</b>
• الهدف الثانى: <b>{u2_mid:,.0f}$</b>
• نطاق الصعود المتوقع: {uz1_low:,.0f}$ → {uz2_high:,.0f}$

━━━━━━━━━━━━━━━━━━
📊 <b>توزيع الاحتمالات (24–72 ساعة):</b>
• صعود: <b>{prob_up}%</b>
• تماسك: <b>{prob_side}%</b>
• هبوط: <b>{prob_down}%</b>

━━━━━━━━━━━━━━━━━━
🧠 <b>قراءة IN CRYPTO Ai:</b>
• قوة الحركة: {strength_label}
• نبض السيولة: {liquidity_pulse}
• تحليل السيولة: {liquidity_note}
• تحليل الزخم: {momentum_note}

<b>🔍 توقع الذكاء الاصطناعى:</b>
{expected_direction_strong}

━━━━━━━━━━━━━━━━━━
{c_level_block}
━━━━━━━━━━━━━━━━━━

⚠️ <b>ملاحظة:</b>
هذا التحذير تعليمى يعتمد على الذكاء الاصطناعى وليس توصية تداول مباشرة.

<b>IN CRYPTO Ai 🤖 — Ultra PRO Alert Engine</b>
""".strip()

        targets_block = _build_directional_targets_block(core)
        if targets_block:
            msg = msg + "\n━━━━━━━━━━━━━━━━━━\n" + targets_block

        return _shrink_text_preserve_content(msg, limit=3800)

    except Exception as e:
        return f"⚠️ حدث خطأ أثناء إنشاء Ultra PRO Alert: {e}"


# ==============================
#   Ultra Market Engine V12 – Multi-Timeframe & Advanced Structure
# ==============================

def _fetch_binance_klines(symbol: str, interval: str, limit: int = 120):
    """
    جلب شموع من باينانس لرمز وفريم محدد.
    نستخدمها فى:
      - Multi-Timeframe Context
      - كشف الشمعات
      - ICT / Harmonic / Elliott / Liquidity Map (بشكل مبسط)
    """
    try:
        url = "https://api.binance.com/api/v3/klines"
        r = config.HTTP_SESSION.get(
            url,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        if r.status_code != 200:
            config.logger.info(
                "Binance kline error %s for %s@%s: %s",
                r.status_code,
                symbol,
                interval,
                r.text[:200],
            )
            return []

        raw = r.json()
        klines = []
        for k in raw:
            # kline format:
            # [0 open time, 1 open, 2 high, 3 low, 4 close, 5 volume, ...]
            try:
                klines.append(
                    {
                        "time": float(k[0]) / 1000.0,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                )
            except Exception:
                continue
        return klines
    except Exception as e:
        config.logger.exception("Error fetching klines from Binance: %s", e)
        return []


def _compute_trend_from_klines(klines):
    """
    تحديد اتجاه بسيط من الشموع:
      - نقارن آخر إغلاق بمتوسط إغلاقات آخر 20 شمعة.
    """
    if not klines or len(klines) < 10:
        return {
            "trend": "neutral",
            "change_pct": 0.0,
        }

    closes = [k["close"] for k in klines]
    last = closes[-1]
    ref_len = min(20, len(closes))
    ref = sum(closes[-ref_len:]) / ref_len
    if ref <= 0:
        ref = last or 1.0
    diff_pct = ((last - ref) / ref) * 100.0

    if diff_pct >= 1.2:
        trend = "strong_up"
    elif diff_pct >= 0.4:
        trend = "up"
    elif diff_pct <= -1.2:
        trend = "strong_down"
    elif diff_pct <= -0.4:
        trend = "down"
    else:
        trend = "sideways"

    return {
        "trend": trend,
        "change_pct": round(diff_pct, 2),
    }


def _detect_candle_patterns_simple(klines):
    """
    كشف مبسط لأشهر نماذج الشموع على آخر 3 شموع من الفريم.
    الهدف: رسالة واضحة فقط، مش تحليل احترافى كامل.
    """
    patterns = []
    if not klines or len(klines) < 3:
        return patterns

    last3 = klines[-3:]
    o1, h1, l1, c1 = last3[0]["open"], last3[0]["high"], last3[0]["low"], last3[0]["close"]
    o2, h2, l2, c2 = last3[1]["open"], last3[1]["high"], last3[1]["low"], last3[1]["close"]
    o3, h3, l3, c3 = last3[2]["open"], last3[2]["high"], last3[2]["low"], last3[2]["close"]

    # أحجام الأجساد والذيول
    body2 = abs(c2 - o2)
    range2 = h2 - l2
    body3 = abs(c3 - o3)
    range3 = h3 - l3

    # Bullish Engulfing
    if c2 < o2 and c3 > o3 and body3 > body2 * 1.1 and o3 <= c2 and c3 >= o2:
        patterns.append("ابتلاع شرائى (Bullish Engulfing)")

    # Bearish Engulfing
    if c2 > o2 and c3 < o3 and body3 > body2 * 1.1 and o3 >= c2 and c3 <= o2:
        patterns.append("ابتلاع بيعى (Bearish Engulfing)")

    # Pin Bar صاعد
    upper3 = h3 - max(c3, o3)
    lower3 = min(c3, o3) - l3
    if lower3 > body3 * 2 and upper3 < body3 and c3 > o3:
        patterns.append("شمعة بن بار صاعدة (Bullish Pin Bar)")

    # Pin Bar هابط
    if upper3 > body3 * 2 and lower3 < body3 and c3 < o3:
        patterns.append("شمعة بن بار هابطة (Bearish Pin Bar)")

    # Inside Bar (شمعة داخلية)
    if h3 < h2 and l3 > l2:
        patterns.append("شمعة داخلية (Inside Bar)")

    return patterns


def _detect_ict_signals_basic(klines):
    """
    كشف مبسط لأفكار ICT على الفريم (مثل 1H / 4H):
      - مساواة قمم/قيعان (Equal Highs/Lows)
      - كسر قمة/قاع ورجوع (Liquidity Grab)
      - فجوة سعرية بسيطة (Fair Value Gap تقريبى)
    """
    signals = []
    if not klines or len(klines) < 10:
        return signals

    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]

    # مساواة قمم أو قيعان قريبة
    tolerance = 0.001  # نسبى تقريبا 0.1%
    for i in range(len(highs) - 3, len(highs) - 1):
        if i <= 0:
            continue
        h_prev = highs[i - 1]
        h_cur = highs[i]
        if h_prev and abs(h_cur - h_prev) / h_prev < tolerance:
            signals.append("مساواة قمم قريبة (Buy-Side Liquidity فوق هذه المنطقة).")
            break

    for i in range(len(lows) - 3, len(lows) - 1):
        if i <= 0:
            continue
        l_prev = lows[i - 1]
        l_cur = lows[i]
        if l_prev and abs(l_cur - l_prev) / l_prev < tolerance:
            signals.append("مساواة قيعان قريبة (Sell-Side Liquidity أسفل هذه المنطقة).")
            break

    # Liquidity Grab مبسط: شمعة اخترقت قمة ثم أغلقت داخل النطاق السابق
    for i in range(2, len(klines)):
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        k = klines[i]
        if k["high"] > prev_high and k["close"] < prev_high and k["close"] > prev_low:
            signals.append("احتمال Liquidity Grab أعلى القمة الأخيرة (Stop Run على المشترين).")
            break
        if k["low"] < prev_low and k["close"] > prev_low and k["close"] < prev_high:
            signals.append("احتمال Liquidity Grab أسفل القاع الأخير (Stop Run على البائعين).")
            break

    # Fair Value Gap تقريبى: ثلاثة شموع متتالية بفجوة واضحة بين high و low
    for i in range(2, len(klines)):
        k1 = klines[i - 2]
        k2 = klines[i - 1]
        k3 = klines[i]
        if k2["low"] > k1["high"] and k2["low"] > k3["high"]:
            signals.append("فجوة سعرية صاعدة (Fair Value Gap) قد تُعاد زيارتها.")
            break
        if k2["high"] < k1["low"] and k2["high"] < k3["low"]:
            signals.append("فجوة سعرية هابطة (Fair Value Gap) قد تُعاد زيارتها.")
            break

    return signals


def _detect_basic_harmonic_abcd(klines):
    """
    هارمونيك مبسط جدًا: نموذج ABCD على آخر 4 نقاط إغلاق.
    لا يعتبر ماسح احترافى، لكنه يعطى فكرة عامة فقط.
    """
    if not klines or len(klines) < 4:
        return None

    closes = [k["close"] for k in klines]
    c1, c2, c3, c4 = closes[-4], closes[-3], closes[-2], closes[-1]

    ab = c2 - c1
    bc = c3 - c2
    cd = c4 - c3

    def _ratio(a, b):
        if b == 0:
            return 0.0
        return abs(a / b)

    # نموذج ABCD صاعد: up → down → up
    if ab > 0 and bc < 0 and cd > 0 and abs(ab) > 0 and _ratio(cd, ab) >= 0.7 and _ratio(cd, ab) <= 1.3:
        return "نموذج ABCD صاعد (احتمالى) قيد التكوين."

    # نموذج ABCD هابط: down → up → down
    if ab < 0 and bc > 0 and cd < 0 and abs(ab) > 0 and _ratio(cd, ab) >= 0.7 and _ratio(cd, ab) <= 1.3:
        return "نموذج ABCD هابط (احتمالى) قيد التكوين."

    return None


def _detect_basic_elliott_wave(klines):
    """
    كشف مبسط للغاية لموجة دافعة (5 موجات) تقريبية:
      - ننظر لاتجاه الإغلاقات الأخيرة وهل معظمها صعود أو هبوط.
    """
    if not klines or len(klines) < 7:
        return "لا توجد قراءة موجية واضحة الآن."

    closes = [k["close"] for k in klines]
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ups = sum(1 for d in diffs if d > 0)
    downs = sum(1 for d in diffs if d < 0)

    if ups >= len(diffs) * 0.7:
        return "حركة تشبه موجة دافعة صاعدة (إليوت) على هذا الفريم."
    if downs >= len(diffs) * 0.7:
        return "حركة تشبه موجة دافعة هابطة (إليوت) على هذا الفريم."
    return "الحركة الحالية أقرب لموجة تصحيحية/جانبية من منظور إليوت."


def _build_liquidity_map_basic(klines):
    """
    Liquidity Map مبسط:
      - أعلى 3 قمم قريبة فوق السعر الحالى → مقاومات + سيولة مشترين.
      - أدنى 3 قيعان قريبة تحت السعر الحالى → دعوم + سيولة بائعين.
    """
    if not klines:
        return {"above": [], "below": []}

    highs = [(k["high"], k.get("time", idx)) for idx, k in enumerate(klines)]
    lows = [(k["low"], k.get("time", idx)) for idx, k in enumerate(klines)]
    last_price = klines[-1]["close"]

    above = sorted([h for h in highs if h[0] > last_price], key=lambda x: x[0])[:3]
    below = sorted([l for l in lows if l[0] < last_price], key=lambda x: x[0], reverse=True)[:3]

    above_levels = [round(x[0], 2) for x in above]
    below_levels = [round(x[0], 2) for x in below]

    return {
        "above": above_levels,
        "below": below_levels,
        "last_price": round(last_price, 2),
    }


def compute_multi_timeframe_structure(symbol: str = "BTCUSDT"):
    """
    Ultra Market Engine V12 – Multi-Timeframe Structure Core
    يشمل:
      - 1m / 5m / 15m / 1h / 4h / 1d
      - كشف شمعات مبسط
      - ICT Basic Signals
      - Harmonic ABCD بسيط
      - Elliott Waves Basic
      - Liquidity Map
    """
    try:
        tf_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
        }

        all_data = {}
        for tf_name, interval in tf_map.items():
            kl = _fetch_binance_klines(symbol, interval, limit=120)
            if not kl:
                all_data[tf_name] = {
                    "trend": "unknown",
                    "change_pct": 0.0,
                    "patterns": [],
                }
                continue

            trend_info = _compute_trend_from_klines(kl)
            patterns = _detect_candle_patterns_simple(kl)

            tf_entry = {
                "klines": kl,
                "trend": trend_info["trend"],
                "change_pct": trend_info["change_pct"],
                "patterns": patterns,
            }

            # نضيف ICT / Harmonic / Elliott / Liquidity على الفريمات الأكبر
            if tf_name in ("1h", "4h", "1d"):
                tf_entry["ict_signals"] = _detect_ict_signals_basic(kl)
                tf_entry["harmonic"] = _detect_basic_harmonic_abcd(kl)
                tf_entry["elliott"] = _detect_basic_elliott_wave(kl)
                tf_entry["liquidity_map"] = _build_liquidity_map_basic(kl)

            all_data[tf_name] = tf_entry

        return all_data
    except Exception as e:
        config.logger.exception("Error in compute_multi_timeframe_structure: %s", e)
        return None


def format_multi_timeframe_block(symbol: str = "BTCUSDT") -> str:
    """
    صياغة بلوك نصى مختصر لـ Multi-Timeframe Engine
    يُستخدم داخل Ultra PRO Alert V12.
    """
    data = compute_multi_timeframe_structure(symbol)
    if not data:
        return "تعذّر جلب قراءة الــ Multi-Timeframe من المزود فى هذه اللحظة."

    def _trend_label(trend: str) -> str:
        if trend == "strong_up":
            return "صعود قوى"
        if trend == "up":
            return "صعود"
        if trend == "strong_down":
            return "هبوط قوى"
        if trend == "down":
            return "هبوط"
        if trend == "sideways":
            return "تذبذب جانبى"
        return "غير واضح"

    # نفصلها لثلاث طبقات: Intraday / Session / Higher Timeframe
    intraday_tfs = ["1m", "5m", "15m"]
    session_tfs = ["1h", "4h"]
    higher_tfs = ["1d"]

    def _summarise_group(tfs):
        trends = []
        texts = []
        for tf in tfs:
            tf_data = data.get(tf) or {}
            t = tf_data.get("trend", "unknown")
            trends.append(t)
            patterns = tf_data.get("patterns") or []
            if patterns:
                texts.append(f"{tf}: " + "، ".join(patterns))
        # شوف أكتر ترند متكرر
        if not trends:
            return "لا توجد بيانات كافية.", "لا توجد أنماط شموع مميزة."
        main_trend = max(set(trends), key=trends.count)
        trend_text = _trend_label(main_trend)
        patterns_text = " / ".join(texts) if texts else "لا توجد نماذج شموع قوية واضحة."
        return trend_text, patterns_text

    intraday_trend, intraday_patterns = _summarise_group(intraday_tfs)
    session_trend, session_patterns = _summarise_group(session_tfs)
    higher_trend, higher_patterns = _summarise_group(higher_tfs)

    # ICT / Harmonic / Elliott / Liquidity من 1H/4H/1D
    ict_notes = []
    harmonic_notes = []
    elliott_notes = []
    liq_notes = []

    for tf in ("1h", "4h", "1d"):
        tf_data = data.get(tf) or {}
        ict = tf_data.get("ict_signals") or []
        if ict:
            ict_notes.append(f"{tf}: " + " / ".join(ict))

        harm = tf_data.get("harmonic")
        if harm:
            harmonic_notes.append(f"{tf}: {harm}")

        ell = tf_data.get("elliott")
        if ell:
            elliott_notes.append(f"{tf}: {ell}")

        lmap = tf_data.get("liquidity_map")
        if lmap and isinstance(lmap, dict):
            above = lmap.get("above") or []
            below = lmap.get("below") or []
            if above or below:
                liq_notes.append(
                    f"{tf}: سيولة فوق الأسعار حوالى: {', '.join(str(x) for x in above) if above else 'لا يوجد'} | "
                    f"سيولة أسفل الأسعار حوالى: {', '.join(str(x) for x in below) if below else 'لا يوجد'}"
                )

    ict_text = " / ".join(ict_notes) if ict_notes else "لا توجد إشارات ICT قوية مكتملة حاليًا على الفريمات الكبيرة."
    harmonic_text = " / ".join(harmonic_notes) if harmonic_notes else "لا يوجد نموذج هارمونيك مكتمل واضح حاليًا، فقط حركات نسبية عادية."
    elliott_text = " / ".join(elliott_notes) if elliott_notes else "لا توجد موجة إليوت دافعة مكتملة بوضوح الآن، الحركة أقرب لتصحيح/تذبذب."
    liq_text = " / ".join(liq_notes) if liq_notes else "خريطة السيولة لا تُظهر تجمعات استثنائية قريبة جدًا من السعر الحالى."

    block = f"""
🧭 <b>Ultra Market Engine V12 – Multi-Timeframe View ({symbol})</b>

<b>Intraday (1m–5m–15m):</b>
• الاتجاه الغالب: <b>{intraday_trend}</b>
• نماذج الشموع الأهم: {intraday_patterns}

<b>Session (1H–4H):</b>
• الاتجاه الغالب: <b>{session_trend}</b>
• نماذج الشموع الأهم: {session_patterns}

<b>Higher Timeframe (1D):</b>
• الاتجاه الغالب: <b>{higher_trend}</b>
• نماذج الشموع الأهم: {higher_patterns}

<b>ICT Models (أسواق السيولة والمؤسسات):</b>
{ict_text}

<b>Harmonic Scanner (ABCD Basic):</b>
{harmonic_text}

<b>Elliott Waves (Basic Detection):</b>
{elliott_text}

<b>Liquidity Map (خريطة السيولة):</b>
{liq_text}
""".strip()

    return block


# ==============================
#   Ultra PRO Alert V12 (Final)
# ==============================

def format_ultra_pro_alert():
    """
    النسخة النهائية من Ultra PRO Alert ضمن Ultra Market Engine V12.
    تعتمد على:
      - Hybrid PRO Core (الاتجاه + الأهداف + الاحتمالات)
      - Multi-Timeframe Engine (1m–1D)
      - ICT / Harmonic / Elliott / Liquidity Map (مبسّط)
      - Institutional C-Level Block
      - Directional Targets Block
    """
    core = compute_hybrid_pro_core()
    if not core:
        return (
            "⚠️ تعذّر إنشاء Ultra PRO Alert حاليًا بسبب مشكلة فى جلب بيانات السوق.\n"
            "حاول مرة أخرى بعد قليل."
        )

    try:
        price = core.get("price", 0.0)
        change = core.get("change", 0.0)
        range_pct = core.get("range_pct", 0.0)
        vol = core.get("volatility_score", 0.0)
        shock = core.get("shock_score", 0.0)
        level = core.get("level")

        trend_word = core.get("trend_word", "غير محدد")
        trend_sentence = core.get("trend_sentence", "")

        momentum_note = core.get("momentum_note", "")
        liquidity_note = core.get("liquidity_note", "")
        liquidity_pressure = core.get("liquidity_pressure", 0.0)

        speed_idx = core.get("speed_index", 0.0)
        accel_idx = core.get("accel_index", 0.0)

        strength_label = core.get("strength_label", "")
        liquidity_pulse = core.get("liquidity_pulse", "")
        reason_short = core.get("reason_short", "")
        expected_direction_strong = core.get("expected_direction_strong", "")

        prob_up = int(round(core.get("prob_up", 0)))
        prob_down = int(round(core.get("prob_down", 0)))
        prob_side = int(round(core.get("prob_side", 0)))

        dz1_low, dz1_high = core.get("down_zone_1", (price * 0.97, price * 0.99))
        dz2_low, dz2_high = core.get("down_zone_2", (price * 0.94, price * 0.97))
        uz1_low, uz1_high = core.get("up_zone_1", (price * 1.01, price * 1.03))
        uz2_low, uz2_high = core.get("up_zone_2", (price * 1.03, price * 1.06))

        d1_mid = round((dz1_low + dz1_high) / 2, 2)
        d2_mid = round((dz2_low + dz2_high) / 2, 2)
        u1_mid = round((uz1_low + uz1_high) / 2, 2)
        u2_mid = round((uz2_low + uz2_high) / 2, 2)

        if level == "critical":
            level_label = "حرِج جدًا"
        elif level == "high":
            level_label = "مرتفع"
        elif level == "medium":
            level_label = "متوسط"
        elif level == "low":
            level_label = "مراقبة هادئة"
        else:
            level_label = "طبيعى"

        c_level_block = build_c_level_institutional_block(core)
        multi_tf_block = format_multi_timeframe_block("BTCUSDT")

        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        msg = f"""
🚨 <b>Ultra Market Engine V12 — Final Ultra PRO Alert</b>

📅 <b>التاريخ:</b> {today_str}
💰 <b>السعر الحالى للبيتكوين:</b> {price:,.0f}$
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {vol:.1f} / 100
⚡ <b>سرعة الزخم اللحظى:</b> {speed_idx:.1f} / 100
🏃 <b>تسارع الحركة:</b> {accel_idx:.1f}
💧 <b>ضغط السيولة التقديرى:</b> {liquidity_pressure:.1f} / 100

<b>🎯 الخلاصة المباشرة:</b>
• الاتجاه الأقوى الآن: <b>{trend_word}</b>
• السبب الرئيسى: {reason_short}
• مستوى حالة السوق: <b>{level_label}</b> (Shock Score ≈ {shock:.1f}/100)

━━━━━━━━━━━━━━━━━━
📉 <b>لو استمر سيناريو الهبوط:</b>
• الهدف الأول: <b>{d1_mid:,.0f}$</b>
• الهدف الثانى: <b>{d2_mid:,.0f}$</b>
• نطاق الهبوط المتوقع: {dz1_low:,.0f}$ → {dz2_high:,.0f}$

📈 <b>لو حدث انعكاس وصعود:</b>
• الهدف الأول: <b>{u1_mid:,.0f}$</b>
• الهدف الثانى: <b>{u2_mid:,.0f}$</b>
• نطاق الصعود المتوقع: {uz1_low:,.0f}$ → {uz2_high:,.0f}$

━━━━━━━━━━━━━━━━━━
📊 <b>توزيع الاحتمالات (24–72 ساعة):</b>
• صعود: <b>{prob_up}%</b>
• تماسك: <b>{prob_side}%</b>
• هبوط: <b>{prob_down}%</b>

━━━━━━━━━━━━━━━━━━
🧠 <b>قراءة IN CRYPTO Ai:</b>
• قوة الحركة: {strength_label}
• نبض السيولة: {liquidity_pulse}
• تحليل السيولة: {liquidity_note}
• تحليل الزخم: {momentum_note}

<b>🔍 توقع الذكاء الاصطناعى:</b>
{expected_direction_strong}

━━━━━━━━━━━━━━━━━━
{c_level_block}
━━━━━━━━━━━━━━━━━━
{multi_tf_block}
━━━━━━━━━━━━━━━━━━

⚠️ <b>ملاحظة:</b>
هذا التحذير تعليمى يعتمد على الذكاء الاصطناعى (V12 Multi-Timeframe + ICT + Harmonic + Elliott + Liquidity Map)
وليس توصية تداول مباشرة.

<b>IN CRYPTO Ai 🤖 — Ultra Market Engine V12</b>
""".strip()

        targets_block = _build_directional_targets_block(core)
        if targets_block:
            msg = msg + "\n━━━━━━━━━━━━━━━━━━\n" + targets_block

        return _shrink_text_preserve_content(msg, limit=3800)

    except Exception as e:
        config.logger.exception("Error in Ultra PRO Alert V12: %s", e)
        return f"⚠️ حدث خطأ أثناء إنشاء Ultra PRO Alert V12: {e}"



# ============================================================
#   V14 Ultra Market Engine — Multi-School + Multi-Timeframe
#   (بناء على BTCUSDT من Binance فقط)
# ============================================================

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

def _fetch_binance_klines(symbol: str, interval: str, limit: int = 200):
    """
    جلب شموع من باينانس لفريم محدد.
    نستخدمها لبناء:
      - نماذج الشموع
      - ICT / SMC / Wyckoff / Harmonic / Elliott
    """
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = config.HTTP_SESSION.get(BINANCE_KLINES_URL, params=params, timeout=10)
        if r.status_code != 200:
            config.logger.info(
                "Binance klines error %s for %s@%s: %s",
                r.status_code,
                symbol,
                interval,
                r.text[:120],
            )
            return []
        raw = r.json()
        candles = []
        for c in raw:
            # [ open_time, open, high, low, close, volume, close_time, ... ]
            o = float(c[1]); h = float(c[2]); l = float(c[3]); cl = float(c[4])
            v = float(c[5])
            candles.append(
                {
                    "open_time": int(c[0]) // 1000,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": v,
                }
            )
        return candles
    except Exception as e:
        config.logger.exception("Error fetching klines %s@%s: %s", symbol, interval, e)
        return []


def get_btc_multi_timeframes() -> dict:
    """
    BTCUSDT multi-timeframe snapshot:
      1m – 5m – 15m – 1H – 4H – 1D
    نستخدم عدد شموع محدود (100) لكل فريم لتخفيف الحمل.
    """
    tf_map = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }
    result: dict[str, list] = {}
    symbol = "BTCUSDT"
    for tf, binance_tf in tf_map.items():
        candles = _fetch_binance_klines(symbol, binance_tf, limit=120)
        if candles:
            result[tf] = candles
    return result


# ------------------------------
#   أدوات مساعدة للشموع
# ------------------------------

def _body_size(c):
    return abs(c["close"] - c["open"])

def _candle_range(c):
    return c["high"] - c["low"]

def _is_bull(c):
    return c["close"] > c["open"]

def _is_bear(c):
    return c["close"] < c["open"]


def detect_candle_patterns_for_tf(candles: list) -> list[str]:
    """
    كشف سريع عن أشهر نماذج الشموع:
      - Pin Bar
      - Engulfing
      - Inside Bar
      - Marubozu
    نركّز على آخر 3–5 شموع للفريم.
    """
    patterns: list[str] = []
    if len(candles) < 3:
        return patterns

    last = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]

    rng = _candle_range(last) or 1e-6
    body = _body_size(last)
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]

    # Pin bar (ذيل طويل)
    if upper_wick >= 2 * body and upper_wick >= 0.6 * rng:
        patterns.append("شمعة Pin Bar علوية (رفض أسعار أعلى)")
    if lower_wick >= 2 * body and lower_wick >= 0.6 * rng:
        patterns.append("شمعة Pin Bar سفلية (رفض أسعار أدنى)")

    # Engulfing
    if _is_bull(last) and _is_bear(prev):
        if last["close"] >= prev["open"] and last["open"] <= prev["close"]:
            patterns.append("نموذج ابتلاع شرائى (Bullish Engulfing)")
    if _is_bear(last) and _is_bull(prev):
        if last["close"] <= prev["open"] and last["open"] >= prev["close"]:
            patterns.append("نموذج ابتلاع بيعى (Bearish Engulfing)")

    # Inside Bar
    if last["high"] <= prev["high"] and last["low"] >= prev["low"]:
        patterns.append("نموذج Inside Bar (تجميع حركة داخل شمعة سابقة)")

    # Marubozu تقريبى
    if body >= 0.8 * rng:
        if _is_bull(last):
            patterns.append("شمعة Marubozu صاعدة قوية (هيمنة مشترين)")
        elif _is_bear(last):
            patterns.append("شمعة Marubozu هابطة قوية (هيمنة بائعين)")

    # استمرار/انعكاس بسيط من آخر 3 شموع
    dir_sum = 0
    for c in (last, prev, prev2):
        if _is_bull(c):
            dir_sum += 1
        elif _is_bear(c):
            dir_sum -= 1
    if dir_sum >= 2:
        patterns.append("سلوك شموع متتالية صاعدة (زخم قصير المدى لأعلى)")
    elif dir_sum <= -2:
        patterns.append("سلوك شموع متتالية هابطة (زخم قصير المدى لأسفل)")

    return patterns


def detect_candle_patterns_multi_tf(mtf: dict) -> dict:
    return {tf: detect_candle_patterns_for_tf(c) for tf, c in mtf.items()}


# ------------------------------
#   ICT / SMC / Liquidity Map
# ------------------------------

def _find_relative_highs_lows(candles: list, lookback: int = 2):
    """
    استخراج High/Low محلية لاستخدامها فى:
      - مفهوم Liquidity (وقف خسارة فوق القمم وتحت القيعان)
      - ICT / SMC
    """
    highs = []
    lows = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        h = candles[i]["high"]
        l = candles[i]["low"]
        if all(h >= candles[j]["high"] for j in range(i - lookback, i + lookback + 1)):
            highs.append((i, h))
        if all(l <= candles[j]["low"] for j in range(i - lookback, i + lookback + 1)):
            lows.append((i, l))
    return highs, lows


def build_liquidity_map(mtf: dict) -> dict:
    """
    Liquidity Map مبسط:
      - مناطق سيولة أعلى القمم وأدنى القيعان على أكثر من فريم.
    """
    liq_map: dict[str, dict] = {}
    for tf, candles in mtf.items():
        if len(candles) < 20:
            continue
        highs, lows = _find_relative_highs_lows(candles, lookback=2)
        liq_map[tf] = {
            "swing_highs": highs[-8:],
            "swing_lows": lows[-8:],
        }
    return liq_map


def analyze_smc_and_ict(mtf: dict, metrics: dict) -> dict:
    """
    قراءة مبسطة لمدرسة SMC + ICT:
      - هل يوجد Sweep لقمم أو قيعان أخيرة؟
      - هل السعر الحالى يتحرك داخل Range واضح؟
    """
    result = {
        "smc_view": "",
        "ict_view": "",
    }
    if "1h" not in mtf:
        return result

    htf = mtf["1h"]
    if len(htf) < 30:
        return result

    highs, lows = _find_relative_highs_lows(htf, lookback=3)
    last_close = htf[-1]["close"]
    text_smc = []
    text_ict = []

    if highs:
        last_high_idx, last_high_val = highs[-1]
        if last_close < last_high_val and htf[-2]["high"] > last_high_val:
            text_ict.append(
                "احتمال حدوث Liquidity Grab أعلى آخر قمة مهمة على فريم 1H (تطبيق مفهوم ICT الكلاسيكى)."
            )
    if lows:
        last_low_idx, last_low_val = lows[-1]
        if last_close > last_low_val and htf[-2]["low"] < last_low_val:
            text_ict.append(
                "احتمال حدوث Liquidity Grab أسفل آخر قاع مهم على فريم 1H (فخ بيع محتمل)."
            )

    recent_closes = [c["close"] for c in htf[-20:]]
    hi = max(recent_closes)
    lo = min(recent_closes)
    rng = hi - lo or 1e-6
    pos = (last_close - lo) / rng * 100.0

    if pos < 25:
        text_smc.append(
            "السعر يتمركز حاليًا قرب قاع نطاق تذبذب واضح على 1H → منطقة تخزين سيولة شراء محتملة."
        )
    elif pos > 75:
        text_smc.append(
            "السعر يتمركز قرب قمة نطاق تذبذب على 1H → منطقة تخزين سيولة بيع محتملة."
        )
    else:
        text_smc.append(
            "السعر فى منتصف Range واضح على فريم 1H، أى كسر حاسم لأحد الأطراف يعنى حركة قوية لاحقًا."
        )

    if not text_ict:
        text_ict.append(
            "لا يوجد حتى الآن نمط ICT مكتمل (Sweep واضح + عودة داخل النطاق)، لكن مراقبة القمم/القيعان الأخيرة ضرورية."
        )

    result["smc_view"] = " ".join(text_smc)
    result["ict_view"] = " ".join(text_ict)
    return result


# ------------------------------
#   Harmonic / Elliott (Basic)
# ------------------------------

def _approx_swing_points(closes: list[float], depth: int = 4) -> list[tuple[int, float]]:
    """
    استخراج نقاط تأرجح بسيطة من سلسلة أسعار.
    لاستخدامها فى تقدير أنماط Harmonic / Elliott بشكل مبسط.
    """
    if len(closes) < depth * 5:
        return []
    pts: list[tuple[int, float]] = []
    step = max(1, len(closes) // (depth * 2))
    for i in range(step, len(closes) - step, step):
        slice_ = closes[i - step : i + step]
        c = closes[i]
        if c == max(slice_):
            pts.append((i, c))
        elif c == min(slice_):
            pts.append((i, c))
    pts = sorted(set(pts), key=lambda x: x[0])
    return pts[-8:]


def analyze_harmonic_basic(candles: list) -> str:
    """
    كشف تقريبى لأنماط ABCD/Gartley-like:
      - نعتمد على آخر 4–5 نقاط تأرجح.
      - هذه ليست أداة احتراف Harmonic كاملة، لكنها تعطيك تنبيه أولى فقط.
    """
    closes = [c["close"] for c in candles]
    swings = _approx_swing_points(closes, depth=4)
    if len(swings) < 4:
        return "لا يوجد حالياً نمط هارمونيك واضح مكتمل، الحركة أقرب لتذبذب عام."

    (iA, A), (iB, B), (iC, C), (iD, D) = swings[-4:]
    def _ratio(a, b):
        if b == 0:
            return 0.0
        return abs(a / b)

    AB = B - A
    BC = C - B
    CD = D - C

    ab_bc = _ratio(BC, AB)
    bc_cd = _ratio(CD, BC)

    if 0.5 <= ab_bc <= 0.9 and 1.0 <= bc_cd <= 1.6:
        if A < B and C > B and D < C:
            return (
                "احتمال وجود نموذج ABCD هابط تقريبى (هارمونيك مبسط) → قد يكون هناك تصحيح هابط بعد آخر موجة."
            )
        if A > B and C < B and D > C:
            return (
                "احتمال وجود نموذج ABCD صاعد تقريبى (هارمونيك مبسط) → قد يكون هناك استمرار صاعد بعد آخر تصحيح."
            )

    return "لا يوجد تطابق قوى مع نسب الهارمونيك الكلاسيكية، لكن سلوك الموجات يشير لحركة تناوبية عادية."


def analyze_elliott_basic(candles: list) -> str:
    """
    قراءة بسيطة لمفهوم Elliott:
      - نحاول التعرف هل السوق فى موجة إندفاعية أو تصحيحية عبر عدد الضربات فى نفس الاتجاه.
    """
    if len(candles) < 40:
        return "البيانات الحالية غير كافية لاستخراج نمط إليوت واضح (نحتاج عدد أكبر من الشموع)."

    closes = [c["close"] for c in candles[-60:]]
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    direction = 1 if diffs[-1] > 0 else -1
    streak = 0
    for d in reversed(diffs):
        if d * direction > 0:
            streak += 1
        else:
            break

    if streak >= 5 and direction > 0:
        return (
            "السوق يظهر سلوك موجة دافعة إيجابية (Impulse Up) وفق إليوت بشكل مبسط، "
            "قد نكون فى موجة 3 أو 5 على فريم 1H/4H تقريبًا."
        )
    if streak >= 5 and direction < 0:
        return (
            "السوق يظهر سلوك موجة دافعة هابطة (Impulse Down) وفق إليوت بشكل مبسط، "
            "قد نكون فى موجة 3 أو 5 هابطة."
        )

    return (
        "سلوك الموجات الحالى أقرب لموجة تصحيحية أو تذبذب جانبي وفق إليوت "
        "ولا يظهر نمط دافع قوى واضح."
    )


# ------------------------------
#   Price Action / Supply-Demand / Classical
# ------------------------------

def analyze_price_action_and_zones(mtf: dict, metrics: dict) -> dict:
    """
    دمج:
      - سلوك السعر (برايس أكشن)
      - مناطق عرض وطلب تقريبية
      - قراءة كلاسيكية (ترند + قنوات بسيطة)
    نعتمد أساساً على فريمات 15m و 1H و 4H.
    """
    result = {
        "price_action": "",
        "supply_demand": "",
        "classical": "",
    }

    price = metrics.get("price", 0.0)

    tf_mid = mtf.get("15m") or mtf.get("5m") or []
    tf_htf = mtf.get("1h") or []
    tf_4h = mtf.get("4h") or []

    pa_lines = []
    sd_lines = []
    cl_lines = []

    if tf_mid:
        last = tf_mid[-1]
        prev = tf_mid[-2]
        if _is_bull(last) and last["low"] > prev["low"]:
            pa_lines.append("على فريم 15m السعر يشكّل قيعان صاعدة متتالية → برايس أكشن إيجابى قصير المدى.")
        if _is_bear(last) and last["high"] < prev["high"]:
            pa_lines.append("على فريم 15m السعر يشكّل قمم هابطة متتالية → برايس أكشن سلبى قصير المدى.")

    if tf_htf:
        closes = [c["close"] for c in tf_htf[-50:]]
        hi = max(closes); lo = min(closes)
        mid = (hi + lo) / 2
        if price <= mid:
            sd_lines.append(
                f"منطقة {lo:,.0f}$ – {mid:,.0f}$ تُعتبر نطاق طلب متوسط الأجل تقريبياً (1H)."
            )
        else:
            sd_lines.append(
                f"منطقة {mid:,.0f}$ – {hi:,.0f}$ تُعتبر نطاق عرض/توزيع متوسط الأجل تقريبياً (1H)."
            )

    if tf_4h:
        first = tf_4h[-40]
        last = tf_4h[-1]
        if last["close"] > first["close"]:
            cl_lines.append("الاتجاه الكلاسيكى على فريم 4H يميل للصعود (قمم وقيعان أعلى).")
        elif last["close"] < first["close"]:
            cl_lines.append("الاتجاه الكلاسيكى على فريم 4H يميل للهبوط (قمم وقيعان أدنى).")
        else:
            cl_lines.append("الاتجاه الكلاسيكى على فريم 4H جانبى تقريبًا بدون ميل واضح.")

    if not pa_lines:
        pa_lines.append("لا يوجد نموذج برايس أكشن حاد واضح الآن، الحركة أقرب لتذبذب داخل نطاق متوسط.")
    if not sd_lines:
        sd_lines.append("مناطق العرض والطلب الحالية ليست حادة بما يكفى، النطاق متوسط متوازن نسبيًا.")
    if not cl_lines:
        cl_lines.append("القراءة الكلاسيكية لا تميل بوضوح لصعود أو هبوط على الفريمات الكبيرة.")

    result["price_action"] = " ".join(pa_lines)
    result["supply_demand"] = " ".join(sd_lines)
    result["classical"] = " ".join(cl_lines)
    return result


# ------------------------------
#   مؤشرات فنية أساسية (Pack)
# ------------------------------

def compute_indicator_pack(candles: list) -> dict:
    """
    حزمة مبسطة من المؤشرات الفنية:
      - EMA20 / EMA50
      - ATR
      - Stoch-like overbought/oversold
    """
    closes = [c["close"] for c in candles]
    if len(closes) < 50:
        return {}

    def ema(values, period):
        k = 2 / (period + 1)
        ema_val = values[0]
        for v in values[1:]:
            ema_val = v * k + ema_val * (1 - k)
        return ema_val

    ema20 = ema(closes[-60:], 20)
    ema50 = ema(closes[-60:], 50)

    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    atr14 = sum(trs[-14:]) / 14 if len(trs) >= 14 else 0.0

    last_close = closes[-1]
    if last_close > ema20 > ema50:
        trend_signal = "السعر أعلى EMA20 و EMA50 → اتجاه صاعد صحى."
    elif last_close < ema20 < ema50:
        trend_signal = "السعر أسفل EMA20 و EMA50 → اتجاه هابط واضح."
    else:
        trend_signal = "السعر يتذبذب حول المتوسطات → اتجاه جانبى / غير حاسم."

    hh = max(closes[-14:])
    ll = min(closes[-14:])
    k_like = 0.0
    if hh != ll:
        k_like = (last_close - ll) / (hh - ll) * 100.0
    if k_like >= 80:
        stoch_state = "منطقة تشبع شرائى نسبياً (Overbought) على المدى القصير."
    elif k_like <= 20:
        stoch_state = "منطقة تشبع بيعى نسبياً (Oversold) على المدى القصير."
    else:
        stoch_state = "قراءة متوسطة لمؤشر التذبذب، لا تشبع واضح حالياً."

    return {
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "atr14": round(atr14, 2),
        "trend_signal": trend_signal,
        "stoch_state": stoch_state,
    }


# ------------------------------
#   V14 Ultra Multi-School Snapshot
# ------------------------------

def compute_v14_ultra_snapshot() -> dict | None:
    """
    لقطة متقدمة تجمع:
      - V11 Smart/Ultra/Hybrid core
      - Multi-Timeframe Candles
      - Candle Patterns
      - ICT + SMC + Wyckoff (من fusion + multi-TF)
      - Harmonic + Elliott (basic)
      - Price Action + Supply/Demand + Classical
      - Indicator Pack
      - Liquidity Map
    """
    core = compute_hybrid_pro_core()
    if not core:
        return None

    metrics = get_market_metrics_cached() or {}
    mtf = get_btc_multi_timeframes()
    candle_patterns = detect_candle_patterns_multi_tf(mtf) if mtf else {}
    liq_map = build_liquidity_map(mtf) if mtf else {}
    smc_ict = analyze_smc_and_ict(mtf, metrics) if mtf else {"smc_view": "", "ict_view": ""}

    harmonic_text = ""
    elliott_text = ""
    indicator_pack = {}
    if "1h" in mtf:
        harmonic_text = analyze_harmonic_basic(mtf["1h"])
        elliott_text = analyze_elliott_basic(mtf["1h"])
        indicator_pack = compute_indicator_pack(mtf["1h"])
    elif "4h" in mtf:
        harmonic_text = analyze_harmonic_basic(mtf["4h"])
        elliott_text = analyze_elliott_basic(mtf["4h"])
        indicator_pack = compute_indicator_pack(mtf["4h"])

    pa_sd_classical = analyze_price_action_and_zones(mtf, metrics) if mtf else {
        "price_action": "",
        "supply_demand": "",
        "classical": "",
    }

    snapshot = {
        "core": core,
        "mtf": mtf,
        "candle_patterns": candle_patterns,
        "liquidity_map": liq_map,
        "smc_view": smc_ict.get("smc_view", ""),
        "ict_view": smc_ict.get("ict_view", ""),
        "harmonic": harmonic_text,
        "elliott": elliott_text,
        "indicator_pack": indicator_pack,
        "price_action": pa_sd_classical.get("price_action", ""),
        "supply_demand": pa_sd_classical.get("supply_demand", ""),
        "classical": pa_sd_classical.get("classical", ""),
    }
    return snapshot


def format_v14_ultra_alert() -> str:
    """
    رسالة تنبيه V14 النهائية (تُستخدم داخل /alert أو للأدمن):
      - تعتمد على نواة Ultra PRO الحالية
      - وتضيف لها مدارس:
        * Multi-Timeframe + Candles
        * ICT / SMC / Liquidity Map
        * Harmonic + Elliott
        * Price Action + Supply/Demand + Classical + Indicators
    """
    snapshot = compute_v14_ultra_snapshot()
    if not snapshot:
        return (
            "⚠️ تعذّر إنشاء V14 Ultra Alert حاليًا بسبب مشكلة فى جلب بيانات السوق أو الشموع.\n"
            "حاول مرة أخرى بعد قليل."
        )

    core = snapshot["core"]
    candle_patterns = snapshot["candle_patterns"]
    smc_view = snapshot["smc_view"]
    ict_view = snapshot["ict_view"]
    harmonic = snapshot["harmonic"]
    elliott = snapshot["elliott"]
    indicator_pack = snapshot["indicator_pack"]
    pa = snapshot["price_action"]
    sd = snapshot["supply_demand"]
    classical = snapshot["classical"]

    price = core.get("price", 0.0)
    change = core.get("change", 0.0)
    range_pct = core.get("range_pct", 0.0)
    vol = core.get("volatility_score", 0.0)
    level = core.get("level")
    shock = core.get("shock_score", 0.0)
    trend_word = core.get("trend_word", "غير محدد")
    trend_sentence = core.get("trend_sentence", "")
    prob_up = int(round(core.get("prob_up", 0)))
    prob_down = int(round(core.get("prob_down", 0)))
    prob_side = int(round(core.get("prob_side", 0)))

    dz1_low, dz1_high = core.get("down_zone_1", (price * 0.97, price * 0.99))
    dz2_low, dz2_high = core.get("down_zone_2", (price * 0.94, price * 0.97))
    uz1_low, uz1_high = core.get("up_zone_1", (price * 1.01, price * 1.03))
    uz2_low, uz2_high = core.get("up_zone_2", (price * 1.03, price * 1.06))

    d1_mid = round((dz1_low + dz1_high) / 2, 2)
    d2_mid = round((dz2_low + dz2_high) / 2, 2)
    u1_mid = round((uz1_low + uz1_high) / 2, 2)
    u2_mid = round((uz2_low + uz2_high) / 2, 2)

    if level == "critical":
        level_label = "حرِج جدًا"
    elif level == "high":
        level_label = "مرتفع"
    elif level == "medium":
        level_label = "متوسط"
    elif level == "low":
        level_label = "مراقبة هادئة"
    else:
        level_label = "طبيعى"

    # تلخيص سريع لأهم نماذج الشموع على الفريمات
    patterns_lines: list[str] = []
    for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
        arr = candle_patterns.get(tf) or []
        if arr:
            patterns_lines.append(f"- فريم {tf}: " + " / ".join(arr[:3]))
    if not patterns_lines:
        patterns_lines.append("لا توجد حالياً نماذج شموع حادة متكررة على الفريمات المتابعة.")

    ind_block = ""
    if indicator_pack:
        ind_block = (
            f"• EMA20 ≈ {indicator_pack.get('ema20')}, EMA50 ≈ {indicator_pack.get('ema50')}.\n"
            f"• ATR14 ≈ {indicator_pack.get('atr14')}.\n"
            f"• اتجاه المتوسطات: {indicator_pack.get('trend_signal')} \n"
            f"• حالة التشبع: {indicator_pack.get('stoch_state')}"
        )
    else:
        ind_block = "البيانات الحالية غير كافية لحساب حزمة المؤشرات الفنية بشكل موثوق (نقص عدد الشموع)."

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    msg = f"""
🚨 <b>IN CRYPTO Ai — V14 Ultra Multi-School Alert</b>

📅 <b>التاريخ:</b> {today_str}
💰 <b>سعر البيتكوين الحالى:</b> {price:,.0f}$
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {vol:.1f} / 100
⚙️ <b>تصنيف حالة السوق (Shock Engine):</b> {level_label} (≃ {shock:.1f}/100)

🎯 <b>الخلاصة المباشرة:</b>
• الاتجاه الأقوى الآن: <b>{trend_word}</b>
• قراءة الاتجاه: {trend_sentence}
• توزيع الاحتمالات (24–72 ساعة): صعود ~{prob_up}% / تماسك ~{prob_side}% / هبوط ~{prob_down}%

━━━━━━━━━━━━━━━━━━
📉 <b>سيناريو الهبوط المحتمل:</b>
• الهدف الأول: <b>{d1_mid:,.0f}$</b>  (منطقة {dz1_low:,.0f}$ – {dz1_high:,.0f}$)
• الهدف الثانى: <b>{d2_mid:,.0f}$</b>  (منطقة {dz2_low:,.0f}$ – {dz2_high:,.0f}$)

📈 <b>سيناريو الصعود المحتمل:</b>
• الهدف الأول: <b>{u1_mid:,.0f}$</b>  (منطقة {uz1_low:,.0f}$ – {uz1_high:,.0f}$)
• الهدف الثانى: <b>{u2_mid:,.0f}$</b>  (منطقة {uz2_low:,.0f}$ – {uz2_high:,.0f}$)

━━━━━━━━━━━━━━━━━━
🕯 <b>قراءة الشموع Multi-Timeframe:</b>
""" + "\n".join(patterns_lines) + f"""

━━━━━━━━━━━━━━━━━━
📚 <b>مدارس ICT + SMC + Wyckoff (موسع):</b>
• SMC View: {smc_view}
• ICT View: {ict_view}
• Harmonic View: {harmonic}
• Elliott Waves View: {elliott}

━━━━━━━━━━━━━━━━━━
📊 <b>برايس أكشن + عرض وطلب + كلاسيكى:</b>
• Price Action: {pa}
• Supply & Demand: {sd}
• Classical Trend: {classical}

━━━━━━━━━━━━━━━━━━
📈 <b>حزمة المؤشرات الفنية (Indicator Pack):</b>
{ind_block}

⚠️ <b>تنبيه مهم:</b>
هذه القراءة تعليمية متقدمة تجمع أكثر من مدرسة تحليل (زمنى، هارمونيك، موجى، SMC، ICT، كلاسيكى، سلوك سعر، مؤشرات)،
وتهدف لتوضيح الصورة الكاملة للسوق. لا تُعتبر نصيحة استثمارية مباشرة، والقرار النهائى للتداول مسؤوليتك بالكامل.

<b>IN CRYPTO Ai 🤖 — V14 Ultra Multi-School Market Engine</b>
""".strip()

    return _shrink_text_preserve_content(msg, limit=3800)



# ==============================
#   V16 - Time School & per‑school reports
# ==============================

def _compute_time_school_view(symbol: str = "BTCUSDT") -> dict:
    """
    مدرسة زمنية مبسطة:
    - تقسيم اليوم إلى جلسات (آسيا، تداخلات، نيويورك، آخر اليوم).
    - حساب متوسط الحركة والتذبذب لكل جلسة من آخر 4–5 أيام تقريباً.
    - قراءة سريعة لاتجاه ومدى الحركة على أطر 24h / 3d / 1w / 1m.
    - إحصائيات بسيطة لأيام الأسبوع من بيانات الإغلاق اليومية.
    """
    try:
        kl_1h = _fetch_binance_klines(symbol, "1h", limit=120)
        kl_4h = _fetch_binance_klines(symbol, "4h", limit=90)
        kl_1d = _fetch_binance_klines(symbol, "1d", limit=60)
    except Exception as e:
        logger.exception("Error in _compute_time_school_view: %s", e)
        return {"error": str(e)}

    if not kl_1h or not kl_4h or not kl_1d:
        return {"error": "no_klines"}

    def _session_for_hour(h: int) -> str:
        # تقسيم تقريبى حسب UTC
        if 0 <= h < 7:
            return "asia"
        if 7 <= h < 12:
            return "asia_london"
        if 12 <= h < 16:
            return "london_newyork"
        if 16 <= h < 21:
            return "newyork"
        return "late_us"

    # إحصائيات الجلسات من فريم الساعة
    session_stats: dict = {}
    for k in kl_1h:
        ts_raw = k.get("time", 0)
        if ts_raw > 10**12:
            ts_raw = ts_raw / 1000.0
        try:
            ts = datetime.utcfromtimestamp(ts_raw)
        except Exception:
            continue
        h = ts.hour
        sess = _session_for_hour(h)
        try:
            o = float(k["open"])
            c = float(k["close"])
            hi = float(k["high"])
            lo = float(k["low"])
        except Exception:
            continue
        if o <= 0:
            continue
        move = abs(c - o) / o * 100.0
        vol = (hi - lo) / o * 100.0
        st = session_stats.setdefault(sess, {"count": 0, "move": 0.0, "vol": 0.0})
        st["count"] += 1
        st["move"] += move
        st["vol"] += vol

    for st in session_stats.values():
        if st["count"]:
            st["move_avg"] = st["move"] / st["count"]
            st["vol_avg"] = st["vol"] / st["count"]
        else:
            st["move_avg"] = 0.0
            st["vol_avg"] = 0.0

    # الشمعة الحالية على فريم الساعة
    current_info = {}
    last = kl_1h[-1] if kl_1h else None
    if last:
        ts_raw = last.get("time", 0)
        if ts_raw > 10**12:
            ts_raw = ts_raw / 1000.0
        try:
            ts = datetime.utcfromtimestamp(ts_raw)
            h = ts.hour
            sess = _session_for_hour(h)
        except Exception:
            h = None
            sess = None
        try:
            o = float(last["open"])
            c = float(last["close"])
            hi = float(last["high"])
            lo = float(last["low"])
        except Exception:
            o = c = hi = lo = 0.0
        move = abs(c - o) / o * 100.0 if o > 0 else 0.0
        vol = (hi - lo) / o * 100.0 if o > 0 else 0.0
        current_info = {
            "hour": h,
            "session": sess,
            "move": move,
            "vol": vol,
        }

    def _swing_stats(kl, window: int):
        if not kl or len(kl) < window:
            return None
        sub = kl[-window:]
        try:
            closes = [float(k["close"]) for k in sub]
            highs = [float(k["high"]) for k in sub]
            lows = [float(k["low"]) for k in sub]
        except Exception:
            return None
        hi = max(highs)
        lo = min(lows)
        mid = (hi + lo) / 2.0 if hi + lo != 0 else 0.0
        rng_pct = (hi - lo) / mid * 100.0 if mid > 0 else 0.0
        drift = closes[-1] - closes[0]
        if drift > 0:
            bias = "bullish"
        elif drift < 0:
            bias = "bearish"
        else:
            bias = "sideways"
        return {
            "range_pct": rng_pct,
            "bias": bias,
            "start": closes[0],
            "end": closes[-1],
        }

    swings = {
        "24h": _swing_stats(kl_1h, 24),
        "3d": _swing_stats(kl_4h, 18),
        "1w": _swing_stats(kl_4h, 42),
        "1m": _swing_stats(kl_1d, 30),
    }

    # إحصائيات بسيطة لأيام الأسبوع من بيانات اليومى
    dow_stats: dict = {}
    for k in kl_1d:
        ts_raw = k.get("time", 0)
        if ts_raw > 10**12:
            ts_raw = ts_raw / 1000.0
        try:
            ts = datetime.utcfromtimestamp(ts_raw)
        except Exception:
            continue
        dow = ts.weekday()  # 0 = Monday
        try:
            o = float(k["open"])
            c = float(k["close"])
            hi = float(k["high"])
            lo = float(k["low"])
        except Exception:
            continue
        if o <= 0:
            continue
        rng = (hi - lo) / o * 100.0
        st = dow_stats.setdefault(dow, {"count": 0, "up": 0, "down": 0, "rng": 0.0})
        st["count"] += 1
        if c > o:
            st["up"] += 1
        elif c < o:
            st["down"] += 1
        st["rng"] += rng

    for st in dow_stats.values():
        if st["count"]:
            st["rng_avg"] = st["rng"] / st["count"]
        else:
            st["rng_avg"] = 0.0

    return {
        "session_stats": session_stats,
        "current": current_info,
        "swings": swings,
        "dow_stats": dow_stats,
    }


def format_time_school_report(symbol: str = "BTCUSDT") -> str:
    """
    تقرير مستقل للمدرسة الزمنية (نسخة متقدمة).
    يعتمد على إحصائيات الجلسات، تذبذب 24h/3d/1w/1m،
    وسلوك أيام الأسبوع، لتكوين رؤية زمنية عميقة.
    """
    tv = _compute_time_school_view(symbol)
    if not tv or tv.get("error"):
        return (
            "⏱ <b>المدرسة الزمنية (Time Analysis)</b>\n"
            "⚠️ تعذّر حساب التحليل الزمنى حالياً (بيانات غير كافية أو خطأ فى الاتصال)."
        )

    session_stats = tv.get("session_stats") or {}
    current = tv.get("current") or {}
    swings = tv.get("swings") or {}
    dow_stats = tv.get("dow_stats") or {}

    # قراءة حالية مبسطة
    cur_session = current.get("session") or "غير معروفة"
    cur_vol = current.get("volatility") or "غير معروف"
    cur_bias = current.get("bias") or "غير محدد"
    cur_range = float(current.get("range_pct") or 0.0)

    lines: list[str] = []
    lines.append("⏱ <b>المدرسة الزمنية المتقدمة – Time Analysis</b>")
    lines.append("")
    lines.append(
        f"🔸 العملة محل الدراسة (محرك داخلى): <b>{symbol}</b>\n"
        f"🔸 الجلسة الحالية تقريباً: <b>{cur_session}</b> – التقلب: <b>{cur_vol}</b> – الانحياز اللحظى: <b>{cur_bias}</b>."
    )
    lines.append(
        f"🔹 متوسط مدى الحركة فى آخر 24 ساعة ≈ <b>{cur_range:.2f}%</b> (مؤشر على قوة/ضعف اليوم الحالى)."
    )

    # 1) دورات زمنية بسيطة من 24h / 3d / 1w / 1m
    lines.append("")
    lines.append("📆 <b>1) دورات الحركة الزمنية (Swings & Cycles)</b>")
    swing_labels = {
        "24h": "آخر 24 ساعة",
        "3d": "آخر 3 أيام",
        "1w": "آخر أسبوع",
        "1m": "آخر شهر",
    }
    for key, label in swing_labels.items():
        sw = (swings or {}).get(key) or {}
        rng = float(sw.get("range_pct") or 0.0)
        bias = sw.get("bias") or "غير واضح"
        start_p = sw.get("start")
        end_p = sw.get("end")
        if rng <= 0:
            continue
        if start_p and end_p:
            lines.append(
                f"• {label}: مدى تقريبي ≈ <b>{rng:.2f}%</b> – انحياز: <b>{bias}</b> "
                f"(من ~{start_p:,.0f}$ إلى ~{end_p:,.0f}$)."
            )
        else:
            lines.append(
                f"• {label}: مدى تقريبي ≈ <b>{rng:.2f}%</b> – انحياز: <b>{bias}</b>."
            )

    # 2) تحليلات الجلسات الآسيوية / الأوروبية / الأمريكية
    if session_stats:
        lines.append("")
        lines.append("⏳ <b>2) إيقاع الجلسات (Asia / Europe / US)</b>")
        session_names = {
            "asia": "جلسة آسيا (طوكيو / هونج كونج)",
            "asia_london": "تداخل آسيا + لندن",
            "london_newyork": "تداخل لندن + نيويورك",
            "newyork": "جلسة نيويورك",
        }
        for key, title in session_names.items():
            st = session_stats.get(key) or {}
            cnt = int(st.get("count") or 0)
            if not cnt:
                continue
            avg_rng = float(st.get("avg_range") or 0.0)
            avg_vol = float(st.get("avg_volatility") or 0.0)
            b = st.get("bias") or "غير محدد"
            lines.append(
                f"• {title}: تكرار ≈ <b>{cnt}</b> يوم، مدى متوسط ≈ <b>{avg_rng:.2f}%</b>، "
                f"تذبذب متوسط ≈ <b>{avg_vol:.1f}/10</b>، وانحياز غالب: <b>{b}</b>."
            )

    # 3) سلوك أيام الأسبوع
    if dow_stats:
        lines.append("")
        lines.append("📅 <b>3) سلوك أيام الأسبوع (Daily Behaviour)</b>")
        dow_labels = {
            0: "الإثنين",
            1: "الثلاثاء",
            2: "الأربعاء",
            3: "الخميس",
            4: "الجمعة",
            5: "السبت",
            6: "الأحد",
        }
        for dow in sorted(dow_stats.keys()):
            st = dow_stats[dow]
            c = int(st.get("count") or 0)
            if not c:
                continue
            up = int(st.get("up") or 0)
            down = int(st.get("down") or 0)
            rng = float(st.get("rng_avg") or 0.0)
            label = dow_labels.get(dow, str(dow))
            lines.append(
                f"• {label}: صعود {up} يوم / هبوط {down} يوم / مدى متوسط ≈ <b>{rng:.2f}%</b>."
            )

    # 4) نافذة الزمن الحرجة (Time Window) – تقدير تعليمى مبسط
    # نختار النافذة كـ: أقرب تقاطع بين مدى 24h و3d وانحياز الجلسة الحالية.
    lines.append("")
    lines.append("🕰 <b>4) نافذة زمنية حرجة (Time Window)</b>")
    sw_24 = (swings or {}).get("24h") or {}
    sw_3d = (swings or {}).get("3d") or {}
    rng24 = float(sw_24.get("range_pct") or 0.0)
    rng3d = float(sw_3d.get("range_pct") or 0.0)
    if rng24 and rng3d:
        # مجرد قراءة تقريبية: إذا كان مدى 3 أيام أكبر بكثير من 24h → نتوقع توسع قريب
        ratio = rng3d / max(rng24, 1e-9)
        if ratio >= 2.0:
            window_comment = (
                "يوجد ضغط زمنى واضح؛ مدى 3 أيام أكبر بكثير من مدى 24h، "
                "ما يرجّح حركة أقوى خلال الجلسات القادمة."
            )
        elif ratio <= 1.0:
            window_comment = (
                "إيقاع 24h و 3d متقارب؛ السوق قد يستمر فى نفس النمط بدون انفجار زمنى كبير قريباً."
            )
        else:
            window_comment = (
                "إيقاع 3d أعلى من 24h لكن ليس بشكل مبالغ؛ قد نرى حركة متوسطة القوة "
                "فى الجلسة أو اليوم التالى."
            )
        lines.append(
            f"• مقارنة المدى 24h / 3d تعطى نسبة ≈ <b>{ratio:.2f}x</b>."
        )
        lines.append(f"• قراءة زمنية: {window_comment}")
    else:
        lines.append(
            "• لم تتوفر بيانات كافية لبناء نافذة زمنية دقيقة، لكن يمكن الاعتماد على سلوك الجلسات أعلاه."
        )

    # 5) خلاصة تعليمية – كيف تستخدم المدرسة الزمنية
    lines.append("")
    lines.append("🧠 <b>5) كيف تستفيد من التحليل الزمنى؟</b>")
    lines.append(
        "- استخدم أشد الجلسات تذبذباً (حسب النقاط أعلاه) لتوقيت الدخول "
        "مع توافقها مع مدارس الاتجاه (ICT / SMC / Wyckoff / الكلاسيكى...)."
    )
    lines.append(
        "- تجاهل الإشارات الضعيفة فى فترات الهدوء الزمنى (مدى يومى ضعيف + تذبذب منخفض)."
    )
    lines.append(
        "- إذا تزامن مدى قوى على 3d أو 1w مع جلسة عالية التذبذب، يكون احتمالية الانفجار السعري أعلى."
    )
    lines.append("")
    lines.append(
        "⚠️ <i>تنبيه تعليمى:</i> التحليل الزمنى لا يقدّم سعر دخول بمفرده، لكنه يخبرك "
        "متى يكون السوق أكثر حساسية للحركة. ادمجه دائماً مع إدارة مخاطر جيدة "
        "ومدرسة اتجاه (ICT / SMC / Wyckoff / Harmonic / Elliott / الكلاسيكى)."
    )

    return "\n".join(lines)




# ==============================
#   V16 – Per‑School Detailed Report
# ==============================

def format_school_report(code: str, symbol: str = "BTCUSDT") -> str:
    """
    يولّد تقرير مفصل لمدرسة واحدة بناءً على محركات V14/V16:
      - يستخدم:
        * get_market_metrics_cached / evaluate_risk_level
        * fusion_ai_brain (اتجاه + وايكوف + SMC + مخاطر)
        * compute_smart_market_snapshot / compute_v14_ultra_snapshot
        * update_market_pulse / _compute_volatility_regime
      - مع تخصيص كامل لنص كل مدرسة.
    """
    code = (code or "").strip().lower()

    # حالياً كل المدارس مبنية على BTCUSDT كمحرك رئيسى
    # يمكن لاحقاً توسيعها لرموز أخرى لو تم دعمها على مستوى المحرك نفسه.
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر توليد تحليل المدرسة حاليًا بسبب مشكلة فى جلب بيانات السوق.\n"
            "حاول مرة أخرى بعد دقائق قليلة."
        )

    # نأخذ لقطة ذكية + لقطة V14 المتقدمة إن أمكن
    snapshot = compute_smart_market_snapshot() or {}
    v14 = compute_v14_ultra_snapshot()

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    fusion = fusion_ai_brain(metrics, risk)
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert_level = snapshot.get("alert_level") or {}
    zones = snapshot.get("zones") or {}

    # لو لقطة V14 جاهزة نستخدمها كمصدر إضافى غنى
    core = None
    smc_view = ""
    ict_view = ""
    harmonic_text = ""
    elliott_text = ""
    pa_text = ""
    sd_text = ""
    classical_text = ""
    indicator_pack = None
    liq_map = None
    mtf = None

    if v14:
        core = v14.get("core") or {}
        smc_view = v14.get("smc_view") or ""
        ict_view = v14.get("ict_view") or ""
        harmonic_text = v14.get("harmonic") or ""
        elliott_text = v14.get("elliott") or ""
        pa_text = v14.get("price_action") or ""
        sd_text = v14.get("supply_demand") or ""
        classical_text = v14.get("classical") or ""
        indicator_pack = v14.get("indicator_pack") or None
        liq_map = v14.get("liquidity_map") or None
        mtf = v14.get("mtf") or None

    # لو core مش متاح من V14 نعيد بناءه بشكل مبسط من metrics
    if not core:
        price = float(metrics["price"])
        change = float(metrics["change_pct"])
        range_pct = float(metrics["range_pct"])
        vol = float(metrics["volatility_score"])
        risk_level = risk["level"]
        trend_word = "تماسك / حركة جانبية"
        if change >= 2:
            trend_word = "اتجاه صاعد واضح"
        elif change <= -2:
            trend_word = "اتجاه هابط واضح"
        elif change >= 0.5:
            trend_word = "ميل صاعد هادئ"
        elif change <= -0.5:
            trend_word = "ميل هابط هادئ"
        core = {
            "price": price,
            "change": change,
            "range_pct": range_pct,
            "volatility_score": vol,
            "level": alert_level.get("level"),
            "shock_score": float(alert_level.get("shock_score", 0.0)),
            "trend_word": trend_word,
            "trend_sentence": fusion.get("summary", ""),
            "prob_up": fusion.get("prob_up", 33.3),
            "prob_down": fusion.get("prob_down", 33.3),
            "prob_side": fusion.get("prob_side", 33.3),
            "down_zone_1": zones.get("down_zone_1") or (price * 0.97, price * 0.99),
            "down_zone_2": zones.get("down_zone_2") or (price * 0.94, price * 0.97),
            "up_zone_1": zones.get("up_zone_1") or (price * 1.01, price * 1.03),
            "up_zone_2": zones.get("up_zone_2") or (price * 1.03, price * 1.06),
        }

    # ------------------ Core مشترك لكل المدارس ------------------
    price = float(core.get("price", metrics["price"]))
    change = float(core.get("change", metrics["change_pct"]))
    range_pct = float(core.get("range_pct", metrics["range_pct"]))
    vol_score = float(core.get("volatility_score", metrics["volatility_score"]))
    level = core.get("level")
    shock_score = float(core.get("shock_score", 0.0))
    trend_word = core.get("trend_word") or "غير محدد"
    prob_up = int(round(core.get("prob_up", 0)))
    prob_down = int(round(core.get("prob_down", 0)))
    prob_side = int(round(core.get("prob_side", 0)))

    strength_label = metrics.get("strength_label", "")
    liquidity_pulse = metrics.get("liquidity_pulse", "")
    wyckoff_phase = fusion.get("wyckoff_phase", "")
    smc_view_fusion = fusion.get("smc_view", smc_view)
    risk_comment = fusion.get("risk_comment", risk.get("message", ""))

    regime = pulse.get("regime") or _compute_volatility_regime(vol_score, range_pct)
    direction_conf = float(pulse.get("direction_confidence", 0.0))
    speed_index = float(pulse.get("speed_index", 0.0))
    accel_index = float(pulse.get("accel_index", 0.0))
    vol_percentile = float(pulse.get("vol_percentile", 0.0))
    range_percentile = float(pulse.get("range_percentile", 0.0))

    dz1_low, dz1_high = core.get("down_zone_1", (price * 0.97, price * 0.99))
    dz2_low, dz2_high = core.get("down_zone_2", (price * 0.94, price * 0.97))
    uz1_low, uz1_high = core.get("up_zone_1", (price * 1.01, price * 1.03))
    uz2_low, uz2_high = core.get("up_zone_2", (price * 1.03, price * 1.06))

    # عنوان مشترك بسيط عن حالة السوق الحالية
    header_lines: list[str] = []
    header_lines.append(
        f"💰 <b>السعر الحالى (BTCUSDT):</b> {price:,.0f}$ — تغير 24 ساعة: %{change:+.2f}"
    )
    header_lines.append(
        f"📊 <b>مدى اليوم:</b> ~{range_pct:.2f}% — <b>مؤشر التقلب:</b> {vol_score:.1f}/100 ({regime})"
    )
    header_lines.append(
        f"🧠 <b>اتجاه الأساس:</b> {trend_word} — "
        f"احتمالات 24–72 ساعة (صعود {prob_up}٪ / تماسك {prob_side}٪ / هبوط {prob_down}٪)."
    )

    base_header = "\n".join(header_lines) + "\n\n"

    # ------------------ مدارس متخصصة ------------------

    def _ict_block() -> str:
        lines: list[str] = []
        lines.append("📘 <b>مدرسة ICT – الذكاء المؤسسى</b>")
        lines.append("")
        # Dealing Range تقديرى من مدى اليوم
        mid_label = "فى منتصف النطاق اليومى تقريبًا"
        if change > 0 and range_pct > 0:
            # تقريب بسيط: لو الحركة الصاعدة قرب القمة
            mid_label = "يميل للتحرك فى النصف العلوى من النطاق (Premium Zone)"
        if change < 0 and range_pct > 0:
            mid_label = "يميل للتحرك فى النصف السفلى من النطاق (Discount Zone)"

        lines.append("1️⃣ <b>Dealing Range & Premium / Discount</b>")
        lines.append(
            f"- السوق حالياً {mid_label} مع قراءة قوة: {strength_label or 'غير محددة'}."
        )
        lines.append(
            f"- نبض السيولة: {liquidity_pulse or 'لم يتم التقاط نمط سيولة واضح بعد.'}"
        )
        lines.append("")

        lines.append("2️⃣ <b>السيولة (Liquidity Pools & Stops)</b>")
        liq_view = fusion.get("liquidity_view") or ict_view or ""
        if not liq_view:
            liq_view = (
                "السوق يتحرك من منطقة سيولة لأخرى؛ توجد تجمعات أوامر أعلى القمم القريبة "
                "وأسفل القيعان الأخيرة، وأى اختراق حاد لها يُعد غالباً حركة لالتقاط السيولة."
            )
        lines.append(f"- {liq_view}")
        lines.append("")

        lines.append("3️⃣ <b>FVG / Order Blocks / PD Arrays</b>")
        lines.append(
            "من منظور ICT نركز على مناطق Fair Value Gaps (فجوات القيمة العادلة) "
            "ومناطق الـ Order Blocks المتوافقة مع الاتجاه الحالى. "
            "أى عودة منظمة لمناطق خصم (Discount) داخل بلوك طلب معتبر تُعتبر فرصة المؤسسى."
        )
        lines.append(
            f"- أقرب مناطق خصم تقريبية (Zones Down): [{dz1_low:,.0f}$ → {dz1_high:,.0f}$] "
            f"ثم [{dz2_low:,.0f}$ → {dz2_high:,.0f}$]."
        )
        lines.append(
            f"- أقرب مناطق علاوة (Zones Up): [{uz1_low:,.0f}$ → {uz1_high:,.0f}$] "
            f"ثم [{uz2_low:,.0f}$ → {uz2_high:,.0f}$]."
        )
        lines.append("")

        lines.append("4️⃣ <b>Killzones & Manipulation</b>")
        if direction_conf >= 60:
            lines.append(
                f"- اتجاه الحركة الأخيرة مدعوم بتناسق {direction_conf:.0f}٪ تقريباً بين الشمعات، "
                "ما يرجّح أن جزءًا كبيرًا من الحركة مؤسسى وليس ضوضاء عشوائية."
            )
        else:
            lines.append(
                "- ثقة الاتجاه على المدى القصير ليست عالية، ما يعنى أن الحركات الحالية قد تكون "
                "إعادة تموضع وليست اتجاهًا متماسكًا."
            )
        lines.append("")

        lines.append("5️⃣ <b>خلاصة مدرسة ICT</b>")
        lines.append(f"- {fusion.get('summary', 'قراءة ICT مدمجة مع باقى المحركات').strip()}")
        lines.append(f"- تعليق المخاطر: {risk_comment}")
        return "\n".join(lines)

    def _smc_block() -> str:
        lines: list[str] = []
        lines.append("🎯 <b>مدرسة SMC Pro – Smart Money Concepts</b>")
        lines.append("")
        lines.append("1️⃣ <b>هيكل السوق (Market Structure)</b>")
        lines.append(
            f"- من زاوية الهيكل العام: {wyckoff_phase or 'الهيكل الحالى يميل لاتجاه/نطاق انتقالى.'}"
        )
        lines.append(
            "- نراقب آخر قمم وقيعان مكسورة كـ BOS / CHoCH لتأكيد استمرار الاتجاه "
            "أو تحوله."
        )
        lines.append("")
        lines.append("2️⃣ <b>سلوك السيولة والمؤسسات (SMC View)</b>")
        lines.append(f"- {smc_view_fusion or smc_view or 'لا توجد إشارة SMC حادة حالياً.'}")
        lines.append(f"- نبض السيولة العام: {liquidity_pulse or 'غير متاح حالياً.'}")
        lines.append("")
        lines.append("3️⃣ <b>مناطق اهتمام (POI / Zones)</b>")
        lines.append(
            f"- مناطق الطلب المحتملة: [{dz1_low:,.0f}$ → {dz1_high:,.0f}$] ثم [{dz2_low:,.0f}$ → {dz2_high:,.0f}$]."
        )
        lines.append(
            f"- مناطق العرض المحتملة: [{uz1_low:,.0f}$ → {uz1_high:,.0f}$] ثم [{uz2_low:,.0f}$ → {uz2_high:,.0f}$]."
        )
        lines.append("")
        lines.append("4️⃣ <b>خلاصة SMC</b>")
        lines.append(f"- {fusion.get('summary', '').strip() or 'لا توجد قراءة حاسمة، النطاق أقرب لتوازن نسبى.'}")
        lines.append(f"- تعليق المخاطر: {risk_comment}")
        return "\n".join(lines)

    def _wyckoff_block() -> str:
        lines: list[str] = []
        lines.append("📚 <b>مدرسة Wyckoff – مراحل السوق</b>")
        lines.append("")
        lines.append("1️⃣ <b>المرحلة الحالية (Phase)</b>")
        lines.append(
            f"- تقدير تقريبى: {wyckoff_phase or 'لم تتكون حتى الآن مرحلة وايكوف واضحة (تجميع/تصريف).'}"
        )
        lines.append("")
        lines.append("2️⃣ <b>العلاقة بين السعر والحجم</b>")
        lines.append(
            "- ندمج قوة الحركة اليومية مع نطاق التذبذب لتقدير إن كان هناك دخول قوى للمشترين "
            "أو خروج ملحوظ للبائعين، مع اعتبار حركات التوسع/الانكماش فى المدى اليومى."
        )
        lines.append("")
        lines.append("3️⃣ <b>سلوك السيولة</b>")
        lines.append(
            f"- {liquidity_pulse or 'لا توجد إشارة واضحة على تجميع أو تصريف فى هذه اللحظة.'}"
        )
        lines.append("")
        lines.append("4️⃣ <b>خلاصة Wyckoff</b>")
        lines.append(f"- {fusion.get('summary', '').strip() or 'مرحلة انتقالية بين التجميع والتصريف.'}")
        lines.append(f"- تعليق المخاطر: {risk_comment}")
        return "\n".join(lines)

    def _harmonic_block() -> str:
        lines: list[str] = []
        lines.append("🌀 <b>مدرسة Harmonic – النماذج التوافقية</b>")
        lines.append("")
        if harmonic_text:
            lines.append(harmonic_text.strip())
        else:
            lines.append(
                "لا توجد حالياً إشارة Harmonic حادة من النموذج التقريبى، "
                "لكن تراقب المدرسة تكوين موجات متناسقة يمكن أن تتطور إلى ABCD أو نماذج أكبر."
            )
        lines.append("")
        lines.append("🧠 <b>ملاحظة:</b> قراءة الهارمونيك هنا تقريبية تعليمية، ولا تُغنى عن أدوات رسم متقدمة "
                     "أو فحص يدوى للنماذج على الشارت.")
        return "\n".join(lines)

    def _elliott_block() -> str:
        lines: list[str] = []
        lines.append("🌊 <b>مدرسة Elliott Waves – موجات إليوت</b>")
        lines.append("")
        if elliott_text:
            lines.append(elliott_text.strip())
        else:
            lines.append(
                "لم يتم التقاط عد موجى واضح من المحرك التقريبى، "
                "لكن يمكن اعتبار الحركة الحالية جزءًا من موجة دافعة أو تصحيحية حسب سياق الفريمات الأكبر."
            )
        lines.append("")
        lines.append(
            "🧠 هذه القراءة موجية تقريبية، الهدف منها إعطاء إحساس بمكاننا داخل الدورة الموجية "
            "وليست عدًا موجيًا كاملاً بالمعنى الكلاسيكى."
        )
        return "\n".join(lines)

    def _time_block() -> str:
        # نعيد استخدام المدرسة الزمنية الكاملة
        return format_time_school_report(symbol=symbol)

    def _price_action_block() -> str:
        lines: list[str] = []
        lines.append("📈 <b>مدرسة Price Action – سلوك السعر</b>")
        lines.append("")
        if pa_text:
            lines.append(pa_text.strip())
        else:
            lines.append(
                "لا توجد حالياً نماذج برايس أكشن حادة (مثل ابتلاع قوى أو كسر كاذب واضح) "
                "على الفريمات الرئيسية المتابعة."
            )
        lines.append("")
        lines.append(
            "تركّز هذه المدرسة على شكل الشموع عند مستويات الدعم والمقاومة، "
            "وعلى وجود شموع رفض/ابتلاع/ضغط تزودنا بإشارات دخول أو خروج تعليمية."
        )
        return "\n".join(lines)

    def _sd_block() -> str:
        lines: list[str] = []
        lines.append("📦 <b>مدرسة Supply & Demand – العرض والطلب</b>")
        lines.append("")
        if sd_text:
            lines.append(sd_text.strip())
        else:
            lines.append(
                "لا تظهر حالياً مناطق عرض وطلب حادة للغاية؛ الحركة أقرب إلى توازن نسبى "
                "مع وجود مناطق متوسطة القوة يمكن أن يتفاعل معها السعر."
            )
        lines.append("")
        lines.append(
            f"مناطق الهبوط المحتملة (POI هابطة): [{dz1_low:,.0f}$ → {dz1_high:,.0f}$] / [{dz2_low:,.0f}$ → {dz2_high:,.0f}$]."
        )
        lines.append(
            f"ومناطق الصعود المحتملة (POI صاعدة): [{uz1_low:,.0f}$ → {uz1_high:,.0f}$] / [{uz2_low:,.0f}$ → {uz2_high:,.0f}$]."
        )
        return "\n".join(lines)

    def _classic_block() -> str:
        lines: list[str] = []
        lines.append("🏛 <b>المدرسة الكلاسيكية – مؤشرات وترندات</b>")
        lines.append("")
        if classical_text:
            lines.append(classical_text.strip())
            lines.append("")
        if indicator_pack:
            lines.append(
                f"• EMA20 ≈ {indicator_pack.get('ema20')}, EMA50 ≈ {indicator_pack.get('ema50')}."
            )
            lines.append(f"• ATR14 ≈ {indicator_pack.get('atr14')}.")
            lines.append(f"• اتجاه المتوسطات: {indicator_pack.get('trend_signal')}.")
            lines.append(f"• حالة التشبع: {indicator_pack.get('stoch_state')}.")
        else:
            lines.append(
                "لم يتم حساب حزمة المؤشرات الفنية الكاملة (EMA / ATR / Oscillators)، "
                "ربما لنقص بيانات الفريمات."
            )
        return "\n".join(lines)

    def _liquidity_block() -> str:
        lines: list[str] = []
        lines.append("💧 <b>Liquidity Map – خريطة السيولة</b>")
        lines.append("")
        if liq_map and isinstance(liq_map, dict):
            above = liq_map.get("above") or []
            below = liq_map.get("below") or []
            lp = liq_map.get("last_price", price)
            if above:
                lines.append(
                    f"- مناطق سيولة مشترين محتملة (أعلى السعر الحالى ~{lp:,.0f}$): "
                    + " / ".join(f"{lvl:,.0f}$" for lvl in above)
                )
            if below:
                lines.append(
                    f"- مناطق سيولة بائعين محتملة (أسفل السعر الحالى ~{lp:,.0f}$): "
                    + " / ".join(f"{lvl:,.0f}$" for lvl in below)
                )
        else:
            lines.append(
                "لم يتم بناء خريطة سيولة مفصلة حاليًا، لكن يمكن افتراض تجمعات أوامر "
                "أعلى القمم الواضحة وأسفل القيعان الحديثة."
            )
        lines.append("")
        lines.append(
            f"نبض السيولة العام من المحرك الرئيسى: {liquidity_pulse or 'غير متوفر حالياً.'}"
        )
        return "\n".join(lines)

    def _structure_block() -> str:
        lines: list[str] = []
        lines.append("🧬 <b>Market Structure – هيكل السوق</b>")
        lines.append("")
        lines.append(
            f"- الهيكل الحالى وفقًا للمحرك الرئيسى: {wyckoff_phase or 'نطاق انتقالى بدون اتجاه مكتمل.'}"
        )
        lines.append(
            "- نراقب تكوين قمم وقيعان أعلى/أدنى (HH/HL/LH/LL) على الفريمات المتوسطة لتأكيد الاتجاه."
        )
        lines.append(
            f"- ثقة الاتجاه الحالية (من نبض السوق): ~{direction_conf:.0f}٪."
        )
        return "\n".join(lines)

    def _mtf_block() -> str:
        lines: list[str] = []
        lines.append("🧭 <b>Multi‑Timeframe – تعدد الفريمات</b>")
        lines.append("")
        if not mtf:
            lines.append(
                "لم يتم تحميل بيانات كافية لبناء صورة متعددة الفريمات، "
                "لكن يمكن الاعتماد على القراءة اليومية/الربعية فقط."
            )
            return "\n".join(lines)

        lines.append(
            "الفكرة الأساسية هنا: هل الفريمات الكبيرة (4H / 1D) متوافقة مع الفريمات القصيرة "
            "(15m / 1H) أم متعارضة؟"
        )
        lines.append("")
        # تبسيط شديد: نستخدم اتجاه trend_word وتقلب اليوم كمؤشر توافق عام
        if abs(change) >= 2 and direction_conf >= 60:
            lines.append(
                "- الفريمات الكبيرة والصغيرة على الأغلب متوافقة مع الاتجاه الرئيسى الحالى، "
                "ما يقوّى أى سيناريو استمرار للترند."
            )
        else:
            lines.append(
                "- توجد درجة من التعارض بين قراءات المدى القصير والمدى المتوسط، "
                "ما يعنى أن التداول ضد الاتجاه العام يحمل مخاطرة أعلى."
            )
        return "\n".join(lines)

    def _time_school_summary_block() -> str:
        tv = _compute_time_school_view(symbol)
        if not tv or tv.get("error"):
            return (
                "⏱ تعذّر تحديث المدرسة الزمنية داخل التحليل المجمع، "
                "لكن يمكنك طلبها مباشرة عبر المدرسة الزمنية."
            )
        cur = tv.get("current") or {}
        sess = cur.get("session") or "unknown"
        volatility = cur.get("volatility") or "unknown"
        bias = cur.get("bias") or "غير محدد"
        return (
            f"⏱ <b>المدرسة الزمنية (ملخص):</b> الجلسة الحالية تميل إلى {volatility} "
            f"مع انحياز زمنى عام نحو {bias}."
        )

    def _volume_volatility_block() -> str:
        lines: list[str] = []
        lines.append("📊 <b>Volume / Volatility School – مدرسة الحجم والتقلب</b>")
        lines.append("")
        lines.append(
            f"- مؤشر التقلب الكلى: {vol_score:.1f}/100 → نظام تقلب: <b>{regime}</b> "
            f"(percentile التقلب ≈ {vol_percentile:.0f}٪ / مدى اليوم ≈ {range_percentile:.0f}٪)."
        )
        lines.append(
            f"- سرعة الحركة (Speed Index): {speed_index:.1f} / تسارع الحركة (Accel Index): {accel_index:.1f}."
        )
        lines.append(
            "- كلما ارتفعت هذه المؤشرات معًا كان السوق أقرب لحالة اندفاعية قد "
            "تنتج عنها انفجارات سعرية أو انعكاسات حادة."
        )
        lines.append("")
        lines.append(
            "🧪 <b>قراءة عامة:</b> "
            + strength_label
        )
        lines.append(
            "💡 المدرسة هنا لا تقول لك صعود أو هبوط صريح، لكنها تقول: "
            "هل التوقيت مناسب لحجم صفقة كبير أم الأفضل تخفيف المخاطرة وانتظار هدوء."
        )
        lines.append(f"🔔 تعليق المخاطر: {risk_comment}")
        return "\n".join(lines)

    def _risk_position_block() -> str:
        lines: list[str] = []
        lines.append("🧮 <b>Risk & Position School – مدرسة المخاطر وحجم الصفقة</b>")
        lines.append("")
        level_ar = _risk_level_ar(risk["level"])
        lines.append(
            f"- مستوى المخاطر العام حالياً: <b>{level_ar}</b> ({risk['emoji']}) — {risk['message']}"
        )
        lines.append(
            f"- التقلب {vol_score:.1f}/100 مع مدى يومى ≈ {range_pct:.2f}٪ "
            "يعنى أن حجم الخطأ فى التوقيت يمكن أن يكون كبيراً إذا لم يتم ضبط وقف الخسارة."
        )
        lines.append("")
        lines.append("📐 <b>إرشادات تعليمية لحجم الصفقة (Position Sizing):</b>")
        if risk["level"] == "high":
            lines.append(
                "• يفضّل تقليل حجم الصفقة إلى أقل من 25٪ من الحجم المعتاد، أو الاكتفاء بالمراقبة. "
                "• تجنب استخدام رافعة مالية عالية، وأى صفقة تكون بهدف قصير وواضح."
            )
        elif risk["level"] == "medium":
            lines.append(
                "• يمكن التداول بحجم متوسط (حتى 50–60٪ من الحجم المعتاد) مع التزام صارم بوقف الخسارة. "
                "• التركيز يكون على الفرص ذات R/R عالى فقط."
            )
        else:
            lines.append(
                "• يمكن زيادة الحجم تدريجيًا ولكن ضمن حدود إدارة رأس المال (1–2٪ من رأس المال لكل صفقة). "
                "• لا يُنصح أبدًا بالمخاطرة بكل الرأس المال حتى مع هدوء السوق."
            )
        lines.append("")
        lines.append("🧠 <b>تعليق نهائى:</b>")
        lines.append(
            risk_comment
            + " هذه المدرسة تعليمية فقط لمساعدتك على التفكير فى حجم المخاطرة، "
              "وليست نصيحة استثمارية أو إدارية مباشرة."
        )
        return "\n".join(lines)
def _digital_block() -> str:
    lines: list[str] = []
    lines.append("🧮 <b>مدرسة Digital Analysis – التحليل الرقمى</b>")
    lines.append("")
    # معلومات أساسية من Core
    try:
        price_val = float(price)
    except Exception:
        price_val = 0.0
    try:
        change_val = float(change)
    except Exception:
        change_val = 0.0
    try:
        vol_val = float(vol_score)
    except Exception:
        vol_val = 0.0

    # رقم مسيطر تقريبى من تركيب السعر
    dominant_digit = None
    if price_val > 0:
        digits = [d for d in str(int(round(price_val))) if d.isdigit()]
        if digits:
            dominant_digit = max(set(digits), key=digits.count)

    lines.append(
        f"• السعر التقريبى الحالى: <b>{price_val:,.0f}$</b> – التغير اليومى ≈ <b>{change_val:+.2f}%</b>."
    )
    lines.append(
        f"• درجة نشاط السوق رقمياً (من حيث المدى والتذبذب): ≈ <b>{vol_val:.1f}/100</b>."
    )
    lines.append("")

    lines.append("🔢 <b>1) الرقم المسيطر (Dominant Number)</b>")
    if dominant_digit is not None:
        lines.append(
            f"- الرقم <b>{dominant_digit}</b> يتكرر بقوة فى تركيب السعر الحالى، "
            "وهو يُستخدم تعليمياً كرقم «مسيطر» فى هذه الدورة."
        )
    else:
        lines.append(
            "- تعذّر استخراج رقم مسيطر بشكل واضح من السعر الحالى، "
            "لكن ما زالت القراءة الرقمية العامة صالحة كتوضيح تعليمى."
        )

    lines.append("")
    lines.append("🧮 <b>2) النِسَب والشرائح السعرية (Digital Ranges)</b>")
    if price_val > 0:
        r12 = price_val * 1.0125
        r25 = price_val * 1.025
        r50 = price_val * 1.05
        r75 = price_val * 1.075
        lines.append(f"- شريحة +12.5٪ التقريبية: ~<b>{r12:,.0f}$</b>.")
        lines.append(f"- شريحة +25٪ التقريبية: ~<b>{r25:,.0f}$</b>.")
        lines.append(f"- شريحة +50٪ التقريبية: ~<b>{r50:,.0f}$</b>.")
        lines.append(f"- شريحة +75٪ التقريبية: ~<b>{r75:,.0f}$</b>.")
    else:
        lines.append("- لم تتوفر بيانات سعرية كافية لحساب الشرائح الرقمية بدقة.")
    lines.append("")

    lines.append("📊 <b>3) الزخم الرقمى (Digital Momentum)</b>")
    if abs(change_val) < 0.5:
        dmood = "زخم رقمى ضعيف – السوق يتحرك فى نطاق ضيق عدديّاً."
    elif abs(change_val) < 2.0:
        dmood = "زخم رقمى متوسط – الحركة اليومية نشطة لكن ليست عنيفة."
    else:
        dmood = "زخم رقمى قوى – السوق يعيش موجة عددية حادة (اندفاع أو هبوط قوى)."
    lines.append(f"- التوصيف التعليمى: {dmood}")

    lines.append("")
    lines.append("🎯 <b>4) السيناريو الرقمى الأقرب</b>")
    if change_val >= 0:
        bias = "انحياز رقمى مائل للصعود على المدى القصير."
    else:
        bias = "انحياز رقمى مائل للهبوط على المدى القصير."
    lines.append(f"- {bias}")
    lines.append(
        "- هذه القراءة رقمية/إحصائية تعليمية وليست إشارة دخول أو خروج مباشرة، "
        "ويُفضّل دمجها مع المدارس الأخرى (الاتجاه، السيولة، الزمن، المخاطرة)."
    )

    return "\n".join(lines)

    def _all_schools_block() -> str:
        lines: list[str] = []
        lines.append("🧠 <b>ALL SCHOOLS – ملخص المدارس الرئيسية</b>")
        lines.append("")
        lines.append(f"• ICT: {ict_view or fusion.get('liquidity_view') or 'لا توجد إشارة ICT حادة حالياً.'}")
        lines.append(f"• SMC: {smc_view_fusion or smc_view or 'لا توجد قراءة SMC حاسمة.'}")
        lines.append(f"• Wyckoff: {wyckoff_phase or 'مرحلة انتقالية تقريبية.'}")
        lines.append(f"• Harmonic: {harmonic_text or 'لا توجد إشارة نموذج توافقى قوى واضح.'}")
        lines.append(f"• Elliott: {elliott_text or 'قراءة موجية تقريبية بدون نموذج مكتمل.'}")
        lines.append(f"• Price Action: {pa_text or 'لا توجد أنماط برايس أكشن حادة واضحة.'}")
        lines.append(f"• Supply & Demand: {sd_text or 'مناطق عرض وطلب متوازنة نسبياً.'}")
        lines.append(f"• Classical TA: {classical_text or 'المدرسة الكلاسيكية لا ترجّح اتجاهاً قوياً منفرداً.'}")
        lines.append("")
        lines.append(_time_school_summary_block())
        lines.append("")
        lines.append(
            "💡 هذه الخلاصة تجمع بين عدة مدارس لكن لا تعطى إشارة دخول/خروج مباشرة، "
            "بل تساعدك على رؤية التوافق أو التعارض بين مدارس التحليل المختلفة."
        )
        return "\n".join(lines)

    # اختيار المدرسة المطلوبة
    if code in ("ict",):
        body = _ict_block()
    elif code in ("smc", "smc_pro", "smart"):
        body = _smc_block()
    elif code in ("wyckoff", "wyck"):
        body = _wyckoff_block()
    elif code in ("harmonic", "harm"):
        body = _harmonic_block()
    elif code in ("elliott", "eliott", "wave", "waves"):
        body = _elliott_block()
    elif code in ("time", "time_analysis", "t"):
        body = _time_block()
    elif code in ("price_action", "pa", "price"):
        body = _price_action_block()
    elif code in ("sd", "supply", "supply_demand"):
        body = _sd_block()
    elif code in ("classic", "ta", "classical"):
        body = _classic_block()
    elif code in ("liquidity", "liq"):
        body = _liquidity_block()
    elif code in ("structure", "ms", "market_structure"):
        body = _structure_block()
    elif code in ("multi", "mtf", "multi_timeframe"):
        body = _mtf_block()
    elif code in ("volume", "vol", "volatility"):
        body = _volume_volatility_block()
    elif code in ("risk", "risk_position", "rm"):
        body = _risk_position_block()
    elif code in ("digital", "quant", "digits"):
        body = _digital_block()
    elif code in ("all", "all_schools"):
        body = _all_schools_block()
    else:
        body = (
            "⚠️ هذه المدرسة غير معروفة للمحرك حتى الآن.\n"
            "يمكنك اختيار مدرسة من اللوحة أو استخدام مثلاً: ICT / SMC / Wyckoff / Harmonic / Elliott / Time / "
            "Price Action / Supply & Demand / Classical / Liquidity / Structure / Multi / Volume / Risk."
        )

    full_msg = base_header + body
    return _shrink_text_preserve_content(full_msg, limit=3900)
# ==============================
#   SMC MASTER — Institutional Model
#   Timeframes: 1D / 4H / 1H
# ==============================

def smc_master_model(symbol: str, data: dict) -> dict:
    """
    Institutional Smart Money Concepts Engine
    Returns structured SMC analysis (NO ICT LOGIC)
    """

    result = {
        "symbol": symbol,
        "timeframes": {},
        "liquidity": {},
        "fvg": {},
        "poi": {},
        "scenarios": {},
        "risk": {},
        "summary": {}
    }

    # =========================
    # 1️⃣ DAILY STRUCTURE (1D)
    # =========================
    d = data.get("1D", {})
    result["timeframes"]["1D"] = {
        "trend": d.get("trend"),
        "last_high": d.get("swing_high"),
        "last_low": d.get("swing_low"),
        "structure_state": d.get("structure_state"),
        "bias": d.get("bias"),
    }

    # =========================
    # 2️⃣ 4H STRUCTURE
    # =========================
    h4 = data.get("4H", {})
    result["timeframes"]["4H"] = {
        "trend": h4.get("trend"),
        "bos": h4.get("bos"),
        "choch": h4.get("choch"),
        "phase": h4.get("phase"),
    }

    # =========================
    # 3️⃣ 1H MICRO STRUCTURE
    # =========================
    h1 = data.get("1H", {})
    result["timeframes"]["1H"] = {
        "trend": h1.get("trend"),
        "internal_bos": h1.get("internal_bos"),
        "purpose": "Liquidity engineering",
    }

    # =========================
    # 4️⃣ LIQUIDITY ANALYSIS
    # =========================
    result["liquidity"] = {
        "buy_side": data.get("buy_liquidity"),
        "sell_side": data.get("sell_liquidity"),
        "expected_sweep": data.get("expected_sweep"),
        "taken": data.get("liquidity_taken"),
    }

    # =========================
    # 5️⃣ FVG / IMBALANCE
    # =========================
    result["fvg"] = {
        "active_zone": data.get("fvg_zone"),
        "mitigated": data.get("fvg_mitigated"),
        "move_type": data.get("impulse_type"),
    }

    # =========================
    # 6️⃣ ORDER BLOCKS / POI
    # =========================
    result["poi"] = {
        "bullish_ob": data.get("bullish_ob"),
        "bearish_ob": data.get("bearish_ob"),
        "best_poi": data.get("best_poi"),
        "score": data.get("poi_score"),
    }

    # =========================
    # 7️⃣ SCENARIOS
    # =========================
    result["scenarios"]["bullish"] = {
        "conditions": [
            "Sell-side liquidity sweep",
            "Entry inside POI",
            "1H CHoCH confirmation",
        ],
        "entry": data.get("bull_entry"),
        "targets": data.get("bull_targets"),
        "stop": data.get("bull_sl"),
        "rr": data.get("rr_best"),
    }

    result["scenarios"]["bearish"] = {
        "valid_only_if": "Daily CHoCH confirmed",
        "entry": data.get("bear_entry"),
    }

    # =========================
    # 8️⃣ RISK MANAGEMENT
    # =========================
    result["risk"] = {
        "max_risk": "0.5% - 1%",
        "invalidation": data.get("smc_invalidation"),
        "no_trade_if": [
            "No liquidity sweep",
            "No structure confirmation",
            "Mid-range entry",
        ],
    }

    # =========================
    # 9️⃣ FINAL SUMMARY
    # =========================
    result["summary"] = {
        "bias": data.get("smc_bias"),
        "best_zone": data.get("smc_reaction_zone"),
        "market_state": "Institutional pullback or expansion",
    }

    return result
