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


# =====================================================
#   Ultra Market Engine V12 — Multi-Timeframe & Patterns
#   (Layer أعلى فوق المحرك الأساسى بدون كسر أى واجهة)
# =====================================================

# نحاول نستخدم كاش بسيط للـ klines علشان منضغطش على Binance
try:
    KLINES_CACHE = getattr(config, "KLINES_CACHE")
except Exception:  # pragma: no cover - احتياطى
    KLINES_CACHE = {}
    try:
        setattr(config, "KLINES_CACHE", KLINES_CACHE)
    except Exception:
        pass


def _fetch_binance_klines(symbol: str, interval: str, limit: int = 120):
    """
    جلب شموع من Binance لفريم معين.
    نستخدم كاش بسيط بزمن قصير لتقليل الضغط على الـ API.
    """
    cache_key = f"KLINES:{symbol}:{interval}:{limit}"
    now = time.time()
    item = KLINES_CACHE.get(cache_key)
    ttl = 30.0  # 30 ثانية لكل فريم كـ افتراض آمن

    if item and (now - item["time"] <= ttl):
        return item["data"]

    url = "https://api.binance.com/api/v3/klines"
    try:
        r = config.HTTP_SESSION.get(
            url,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        if r.status_code != 200:
            config.logger.info(
                "Binance klines error %s for %s %s: %s",
                r.status_code,
                symbol,
                interval,
                r.text[:120],
            )
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None

        KLINES_CACHE[cache_key] = {"time": now, "data": data}
        return data
    except Exception as e:  # pragma: no cover - حماية إضافية
        config.logger.exception("Error fetching klines from Binance: %s", e)
        return None


def _approx_rsi_from_closes(closes, period: int = 14) -> float:
    """
    حساب RSI تقريبى من سلسلة أسعار إغلاق.
    لا يستبدل الحساب الاحترافى لكنه كافى للإشارات العامة.
    """
    if not closes or len(closes) < period + 2:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
        elif diff < 0:
            losses.append(-diff)
    if not gains and not losses:
        return 50.0
    avg_gain = sum(gains) / max(1, len(gains))
    avg_loss = sum(losses) / max(1, len(losses))
    if avg_loss == 0:
        return 70.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return max(0.0, min(100.0, rsi))


def _detect_candle_pattern_from_last(open_, high, low, close) -> str:
    """
    قراءة نمط الشمعة الأخيرة: ابتلاعية / بن بار / ماروبوزو / غير ذلك.
    """
    body = abs(close - open_)
    full_range = max(0.0000001, high - low)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low

    body_ratio = body / full_range
    upper_ratio = upper_wick / full_range
    lower_ratio = lower_wick / full_range

    is_bull = close > open_
    is_bear = close < open_

    # ماروبوزو تقريبى
    if body_ratio >= 0.8:
        return "شمعة قوية ممتلئة (ماروبوزو تقريبًا) تدل على زخم واضح."

    # بن بار (هامر / شوتينج ستار)
    if body_ratio <= 0.3:
        if lower_ratio >= 0.6 and is_bull:
            return "شمعة بن بار صاعدة (Hammer) تشير لاحتمال امتصاص بيع من القاع."
        if upper_ratio >= 0.6 and is_bear:
            return "شمعة بن بار هابطة (Shooting Star) تشير لاحتمال رفض من القمة."

    # شمعة عادية بدون نمط واضح
    if is_bull:
        return "شمعة صاعدة عادية بدون نمط انعكاسى واضح."
    if is_bear:
        return "شمعة هابطة عادية بدون نمط انعكاسى واضح."
    return "شمعة حيادية ذات جسم صغير وحركة محدودة."


def _detect_engulfing(prev_open, prev_close, open_, close) -> str | None:
    """
    رصد ابتلاع صاعد/هابط بسيط من آخر شمعتين.
    """
    prev_body = abs(prev_close - prev_open)
    body = abs(close - open_)
    if prev_body <= 0:
        return None

    # ابتلاع صاعد
    if close > open_ and prev_close < prev_open and body > prev_body:
        if open_ <= prev_close and close >= prev_open:
            return "نمط ابتلاع صاعد (Bullish Engulfing) على الشمعتين الأخيرتين."
    # ابتلاع هابط
    if close < open_ and prev_close > prev_open and body > prev_body:
        if open_ >= prev_close and close <= prev_open:
            return "نمط ابتلاع هابط (Bearish Engulfing) على الشمعتين الأخيرتين."
    return None


def _build_timeframe_view(symbol: str, interval: str, limit: int = 80) -> dict:
    """
    بناء قراءة بسيطة لكل فريم:
      - اتجاه تقريبى
      - RSI تقريبى
      - نمط شموع أساسى
    """
    klines = _fetch_binance_klines(symbol, interval, limit=limit)
    if not klines:
        return {
            "interval": interval,
            "direction": "neutral",
            "rsi": 50.0,
            "candle_note": "لا توجد بيانات كافية للفريم حالياً.",
        }

    closes = [float(k[4]) for k in klines]
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    last_close = closes[-1]
    first_close = closes[0]
    change_pct = ((last_close - first_close) / first_close) * 100.0 if first_close else 0.0

    if change_pct >= 1.5:
        direction = "bullish"
    elif change_pct <= -1.5:
        direction = "bearish"
    else:
        direction = "sideways"

    rsi = _approx_rsi_from_closes(closes[-30:])

    o_last = opens[-1]
    h_last = highs[-1]
    l_last = lows[-1]
    c_last = closes[-1]

    candle_note = _detect_candle_pattern_from_last(o_last, h_last, l_last, c_last)
    if len(klines) >= 2:
        o_prev = opens[-2]
        c_prev = closes[-2]
        engulf = _detect_engulfing(o_prev, c_prev, o_last, c_last)
        if engulf:
            candle_note = engulf + " " + candle_note

    return {
        "interval": interval,
        "direction": direction,
        "rsi": round(rsi, 1),
        "change_pct": round(change_pct, 2),
        "candle_note": candle_note,
        "last_close": last_close,
    }


def _detect_ict_model_on_short_tf(symbol: str) -> dict:
    """
    رصد بسيط جدًا لبعض أفكار ICT:
      - سيولة أعلى/أسفل قمة/قاع قريب (Liquidity Sweep)
      - فجوة قيمة عادلة صغيرة (FVG) بين آخر 3 شموع
    """
    klines = _fetch_binance_klines(symbol, "5m", limit=30)
    if not klines or len(klines) < 5:
        return {"active": False, "label": "لا توجد إشارة ICT واضحة حالياً."}

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    h3, h2, h1 = highs[-3], highs[-2], highs[-1]
    l3, l2, l1 = lows[-3], lows[-2], lows[-1]
    c1 = closes[-1]

    ict_label = None
    ict_detail = None

    if h1 > max(h2, h3) and c1 < (h1 + l1) / 2:
        ict_label = "Buy-Side Liquidity Sweep"
        ict_detail = (
            "تم اختراق قمة قريبة مع إغلاق أسفل منتصف الشمعة → "
            "إشارة محتملة لاستهداف سيولة المشترين ثم الهبوط (BSSL)."
        )
    elif l1 < min(l2, l3) and c1 > (h1 + l1) / 2:
        ict_label = "Sell-Side Liquidity Sweep"
        ict_detail = (
            "تم كسر قاع قريب مع إغلاق أعلى منتصف الشمعة → "
            "إشارة محتملة لاستهداف سيولة البائعين ثم الصعود (SSSL)."
        )

    fvg_label = None
    if highs[-3] < lows[-1]:
        fvg_label = "Potential Bullish FVG"
    elif lows[-3] > highs[-1]:
        fvg_label = "Potential Bearish FVG"

    if not ict_label and not fvg_label:
        return {"active": False, "label": "لا توجد إشارة ICT قوية حاليًا على فريم 5 دقائق."}

    parts = []
    if ict_label:
        parts.append(ict_detail or ict_label)
    if fvg_label:
        parts.append("تم رصد فجوة قيمة عادلة صغيرة تدعم قراءة السيولة.")

    return {
        "active": True,
        "label": " / ".join(p for p in parts if p),
        "liquidity_sweep": bool(ict_label),
        "fvg": bool(fvg_label),
    }


def _detect_basic_harmonic_on_1h(symbol: str) -> dict:
    """
    ماسح هارمونيك مبسط جدًا على فريم 1 ساعة.
    لا يدّعى دقة احترافية، فقط يلتقط حركات تشبه ABCD / Bat تقريبيًا.
    """
    klines = _fetch_binance_klines(symbol, "1h", limit=60)
    if not klines or len(klines) < 10:
        return {"active": False, "pattern": None, "label": "لا توجد بنية هارمونيك واضحة حاليًا."}

    closes = [float(k[4]) for k in klines]

    swing_highs = []
    swing_lows = []
    for i in range(2, len(closes) - 2):
        c = closes[i]
        if c > closes[i - 1] and c > closes[i - 2] and c > closes[i + 1] and c > closes[i + 2]:
            swing_highs.append((i, c))
        if c < closes[i - 1] and c < closes[i - 2] and c < closes[i + 1] and c < closes[i + 2]:
            swing_lows.append((i, c))

    swings = sorted(swing_highs + swing_lows, key=lambda x: x[0])
    if len(swings) < 4:
        return {"active": False, "pattern": None, "label": "لا توجد موجة كاملة كفاية لقراءة هارمونيك."}

    last_four = swings[-4:]
    (x_i, x), (a_i, a), (b_i, b), (c_i, c) = last_four

    def _ratio(p1, p2, p3):
        denom = p1 - p2
        if denom == 0:
            return 0.0
        return (p3 - p2) / denom

    xa = a - x
    ab = b - a
    bc = c - b
    if xa == 0 or ab == 0:
        return {"active": False, "pattern": None, "label": "لا توجد نسب واضحة للهارمونيك."}

    r_ab = abs(ab / xa)
    r_bc = abs(bc / ab)

    pattern = None
    if 0.5 <= r_ab <= 0.886 and 0.382 <= r_bc <= 0.886:
        pattern = "Potential ABCD / Gartley-like"
    elif 0.3 <= r_ab <= 0.52 and 0.382 <= r_bc <= 0.886:
        pattern = "Potential Bat-like structure"

    if not pattern:
        return {"active": False, "pattern": None, "label": "لا توجد بنية هارمونيك متناسقة بما يكفى حاليًا."}

    return {
        "active": True,
        "pattern": pattern,
        "label": f"تم رصد بنية هارمونيك تقريبية على فريم 1 ساعة: {pattern} (قراءة تعليمية وليست إشارة دخول مباشرة).",
    }


def _detect_basic_elliott_on_1h(symbol: str) -> dict:
    """
    محاولة مبسطة جدًا لتمييز ما إذا كانت الحركة الأخيرة أشبه بموجة دافعة (5 موجات)
    أو تصحيح ثلاثى، بناءً على عدد القمم/القيعان المتتابعة.
    """
    klines = _fetch_binance_klines(symbol, "1h", limit=80)
    if not klines or len(klines) < 20:
        return {"label": "لا توجد بيانات كافية لقراءة موجات إليوت.", "structure": None, "confidence": 0.0}

    closes = [float(k[4]) for k in klines]

    pivots = []
    for i in range(2, len(closes) - 2):
        c = closes[i]
        if c > closes[i - 1] and c > closes[i - 2] and c > closes[i + 1] and c > closes[i + 2]:
            pivots.append(("H", i, c))
        elif c < closes[i - 1] and c < closes[i - 2] and c < closes[i + 1] and c < closes[i + 2]:
            pivots.append(("L", i, c))

    if len(pivots) < 5:
        return {"label": "الحركة الحالية أقرب لموجات صغيرة متداخلة بدون هيكل 5 موجات واضح.", "structure": None, "confidence": 0.0}

    last_pivots = pivots[-7:]
    ups = sum(1 for t, _, _ in last_pivots if t == "H")
    downs = sum(1 for t, _, _ in last_pivots if t == "L")

    net_move = closes[-1] - closes[-20]
    impulsive_up = net_move > 0 and ups >= 3
    impulsive_down = net_move < 0 and downs >= 3

    if impulsive_up or impulsive_down:
        structure = "impulsive_up" if impulsive_up else "impulsive_down"
        direction_text = "صاعدة" if impulsive_up else "هابطة"
        label = (
            f"الحركة الأخيرة تشبه موجة دافعة {direction_text} (5 موجات تقريبية) "
            "على فريم 1 ساعة — قراءة تقريبية وليست ترقيم إليوت احترافى."
        )
        confidence = 65.0
    else:
        structure = "corrective"
        label = (
            "الحركة الأخيرة أقرب لموجة تصحيحية/جانبية على فريم 1 ساعة، "
            "بدون هيكل 5 موجات واضح."
        )
        confidence = 55.0

    return {
        "label": label,
        "structure": structure,
        "confidence": confidence,
    }


def _build_liquidity_map_v12(metrics: dict, zones: dict) -> dict:
    """
    خريطة سيولة بسيطة فوق/تحت السعر الحالى باستخدام:
      - هاى ولو اليوم
      - مناطق الزونز المحسوبة سابقًا
    """
    price = float(metrics.get("price") or 0.0)
    high = float(metrics.get("high") or 0.0)
    low = float(metrics.get("low") or 0.0)

    dz1_low, dz1_high = zones.get("downside_zone_1", (price * 0.97, price * 0.99))
    dz2_low, dz2_high = zones.get("downside_zone_2", (price * 0.94, price * 0.97))
    uz1_low, uz1_high = zones.get("upside_zone_1", (price * 1.01, price * 1.03))
    uz2_low, uz2_high = zones.get("upside_zone_2", (price * 1.03, price * 1.06))

    liquidity_above = sorted(
        [lvl for lvl in [high, uz1_low, uz1_high, uz2_low, uz2_high] if lvl > price]
    )
    liquidity_below = sorted(
        [lvl for lvl in [low, dz1_low, dz1_high, dz2_low, dz2_high] if lvl < price],
        reverse=True,
    )

    return {
        "price": price,
        "day_high": high,
        "day_low": low,
        "above": liquidity_above,
        "below": liquidity_below,
    }


def _compute_trend_strength_v12(fusion: dict, mtf_views: list[dict]) -> dict:
    """
    قوة الاتجاه النهائية بناءً على:
      - bias من Fusion Brain
      - توافق الفريمات (1m–5m–15m–1h–4h–1d)
    """
    bias = fusion.get("bias") or "neutral"

    bullish = 0
    bearish = 0
    side = 0
    for tf in mtf_views:
        d = tf.get("direction")
        if d == "bullish":
            bullish += 1
        elif d == "bearish":
            bearish += 1
        else:
            side += 1

    total = max(1, bullish + bearish + side)
    align_score = (max(bullish, bearish) / total) * 100.0

    if bias.startswith("strong_bullish") or bias == "bullish":
        dir_core = "bullish"
    elif bias.startswith("strong_bearish") or bias == "bearish":
        dir_core = "bearish"
    else:
        dir_core = "sideways"

    if dir_core == "bullish" and bullish >= bearish:
        trend_score = min(100.0, 60.0 + align_score * 0.4)
        label = "اتجاه صاعد قوى نسبيًا مع توافق فريمات جيد."
    elif dir_core == "bearish" and bearish >= bullish:
        trend_score = min(100.0, 60.0 + align_score * 0.4)
        label = "اتجاه هابط قوى نسبيًا مع توافق فريمات جيد."
    elif align_score <= 40.0:
        trend_score = 35.0
        label = "لا يوجد اتجاه واضح — الفريمات متعارضة إلى حد كبير."
    else:
        trend_score = 50.0
        label = "اتجاه متوسط القوة مع اختلاف بين بعض الفريمات."

    return {
        "trend_score": round(trend_score, 1),
        "alignment": round(align_score, 1),
        "label": label,
        "fusion_bias": bias,
        "counts": {"bullish": bullish, "bearish": bearish, "sideways": side},
    }


def _compute_sentiment_block_v12(metrics: dict, risk: dict) -> dict:
    """
    تكوين مزاج السوق التقريبى (خوف / حذر / تفاؤل / جشع) من:
      - نسبة التغير
      - مستوى التقلب
      - مستوى المخاطر
    """
    change = float(metrics.get("change_pct") or 0.0)
    vol = float(metrics.get("volatility_score") or 0.0)
    risk_level = risk.get("level")

    sentiment = "حذر"
    emoji = "😐"
    note = "السوق يميل إلى الحذر العام مع غياب مزاج متطرف."

    if change <= -4 and vol >= 60:
        sentiment = "خوف / ذعر"
        emoji = "😨"
        note = "حركة هابطة قوية مع تقلب عالى → مزاج خوف واضح بين المشاركين."
    elif change <= -2 and vol >= 45:
        sentiment = "خوف"
        emoji = "😟"
        note = "ضغوط بيعية ملحوظة تجعل المتداولين أكثر حذرًا."
    elif change >= 4 and vol >= 60:
        sentiment = "جشع / نشوة"
        emoji = "🤩"
        note = "صعود حاد مع تقلب عالى → مزاج جشع واضح وخطر فقاعة قصيرة."
    elif change >= 2:
        sentiment = "تفاؤل"
        emoji = "😊"
        note = "صعود ملموس يعكس تفاؤلًا متزايدًا فى السوق."
    elif abs(change) < 1 and vol < 25:
        sentiment = "هدوء / ترقّب"
        emoji = "😴"
        note = "حركة هادئة نسبيًا مع انتظار محفزات جديدة."

    if risk_level == "high" and sentiment in ("تفاؤل", "جشع / نشوة"):
        note += " ⚠️ مع ذلك، محرك المخاطر يشير إلى مستوى عالى، ما يزيد احتمالية التصحيحات المفاجئة."

    return {
        "sentiment": sentiment,
        "emoji": emoji,
        "note": note,
    }


def compute_ultra_market_v12_snapshot() -> dict | None:
    """
    سناب شوت كامل V12:
      - نفس العناصر الأساسية (metrics/risk/pulse/alert/zones/early/fusion)
      - + Multi-Timeframe Views
      - + ICT / Harmonic / Elliott
      - + Liquidity Map
      - + Trend Strength
      - + Sentiment Block
    """
    base = compute_ultra_smart_market_snapshot()
    if not base:
        return None

    metrics = base["metrics"]
    risk = base["risk"]
    zones = base["zones"]
    fusion = base.get("fusion") or fusion_ai_brain(metrics, risk)

    symbol = "BTCUSDT"

    intervals = ["1m", "5m", "15m", "1h", "4h", "1d"]
    mtf_views: list[dict] = []
    for iv in intervals:
        try:
            mtf_views.append(_build_timeframe_view(symbol, iv, limit=80))
        except Exception:
            mtf_views.append(
                {
                    "interval": iv,
                    "direction": "neutral",
                    "rsi": 50.0,
                    "candle_note": "تعذر حساب هذا الفريم حاليًا.",
                }
            )

    ict = _detect_ict_model_on_short_tf(symbol)
    harmonic = _detect_basic_harmonic_on_1h(symbol)
    elliott = _detect_basic_elliott_on_1h(symbol)
    liq_map = _build_liquidity_map_v12(metrics, zones)
    trend_strength = _compute_trend_strength_v12(fusion, mtf_views)
    sentiment_block = _compute_sentiment_block_v12(metrics, risk)

    snap = dict(base)
    snap.update(
        {
            "mtf_views": mtf_views,
            "ict": ict,
            "harmonic": harmonic,
            "elliott": elliott,
            "liquidity_map": liq_map,
            "trend_strength_v12": trend_strength,
            "sentiment_v12": sentiment_block,
            "fusion": fusion,
        }
    )
    return snap


def format_ultra_market_v12_alert() -> str:
    """
    رسالة Ultra Market Engine V12 جاهزة للإرسال مباشرة (يمكن ربطها بأمر /ultra_v12 مثلاً).
    تحتوى على:
      - ملخص V12
      - ثم بلوك Ultra PRO Alert الحالى كمرحلة أخيرة.
    """
    snap = compute_ultra_market_v12_snapshot()
    if not snap:
        return (
            "⚠️ تعذّر إنشاء Ultra Market Engine V12 Snapshot حاليًا بسبب مشكلة فى جلب بيانات السوق.\n"
            "حاول مرة أخرى بعد قليل."
        )

    metrics = snap["metrics"]
    trend_strength = snap["trend_strength_v12"]
    sentiment_block = snap["sentiment_v12"]
    mtf_views = snap["mtf_views"]
    ict = snap["ict"]
    harmonic = snap["harmonic"]
    elliott = snap["elliott"]
    liq_map = snap["liquidity_map"]
    fusion = snap["fusion"]

    price = metrics["price"]
    change = metrics["change_pct"]
    vol = metrics["volatility_score"]
    range_pct = metrics["range_pct"]

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    tf_lines = []
    for tf in mtf_views:
        iv = tf["interval"]
        d = tf["direction"]
        rsi = tf["rsi"]
        note = tf.get("candle_note", "")
        if d == "bullish":
            d_txt = "صاعد"
        elif d == "bearish":
            d_txt = "هابط"
        else:
            d_txt = "عرضى / متذبذب"
        tf_lines.append(
            f"- {iv}: اتجاه {d_txt} | RSI ≈ {rsi:.1f} | {note}"
        )

    ict_line = ict.get("label") if ict.get("active") else "لا توجد إشارة ICT قوية حاليًا (فريم 5 دقائق)."
    harm_line = harmonic.get("label")
    elliott_line = elliott.get("label")

    liq_above = ", ".join(f"{lvl:,.0f}$" for lvl in liq_map.get("above", [])[:4]) or "لا توجد مستويات قريبة فوق السعر."
    liq_below = ", ".join(f"{lvl:,.0f}$" for lvl in liq_map.get("below", [])[:4]) or "لا توجد مستويات قريبة تحت السعر."

    trend_line = trend_strength.get("label")
    trend_score = trend_strength.get("trend_score")
    align = trend_strength.get("alignment")

    sentiment_label = sentiment_block.get("sentiment")
    sentiment_emoji = sentiment_block.get("emoji")
    sentiment_note = sentiment_block.get("note")

    fusion_bias = fusion.get("bias_text", "")
    fusion_smc = fusion.get("smc_view", "")
    fusion_wyckoff = fusion.get("wyckoff_phase", "")

    header_msg = f"""
🧬 <b>Ultra Market Engine V12 — Multi-Timeframe Smart Snapshot</b>
📅 <b>التاريخ:</b> {today_str}

💰 <b>سعر البيتكوين الآن:</b> {price:,.0f}$
📉 <b>تغير 24 ساعة:</b> %{change:+.2f}
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {vol:.1f} / 100

🧭 <b>قوة الاتجاه (Trend Strength Engine):</b>
- {trend_line}
- درجة قوة الاتجاه: <b>{trend_score:.1f}/100</b>
- درجة توافق الفريمات: <b>{align:.1f}%</b>

😶‍🌫️ <b>مزاج السوق (Sentiment & Volatility):</b>
- الحالة العامة: {sentiment_emoji} <b>{sentiment_label}</b>
- {sentiment_note}

🕒 <b>قراءة Multi-Timeframe (1m–5m–15m–1h–4h–1d):</b>
{chr(10).join(tf_lines)}

🎯 <b>مدرسة ICT (فريم 5 دقائق):</b>
- {ict_line}

🎼 <b>هارمونيك:</b>
- {harm_line}

📐 <b>موجات إليوت (قراءة مبسطة):</b>
- {elliott_line}

💧 <b>خريطة السيولة (Liquidity Map):</b>
- أقرب مستويات سيولة فوق السعر: {liq_above}
- أقرب مستويات سيولة تحت السعر: {liq_below}

🧠 <b>ملخص IN CRYPTO Ai (SMC + Wyckoff):</b>
- الاتجاه: {fusion_bias}
- SMC: {fusion_smc}
- مرحلة وايكوف الحالية: {fusion_wyckoff}
""".strip()

    ultra_pro_text = format_ultra_pro_alert()

    full_msg = header_msg + "\n━━━━━━━━━━━━━━━━━━\n" + ultra_pro_text
    return _shrink_text_preserve_content(full_msg, limit=3900)
