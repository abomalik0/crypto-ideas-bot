def analyze_coin(symbol):
    try:
        symbol_upper = symbol.upper()

        # ---- 1) السعر الحالي ----
        price = get_price(symbol_upper)

        # ---- 2) بيانات الشموع لفريم يومي ----
        data = get_klines(symbol_upper, "1d", 200)
        closes = [float(c[4]) for c in data]

        # ---- 3) الاتجاه العام ----
        if closes[-1] > closes[-50]:
            trend = "العملـة تتحرك داخل اتجاه صاعد مستقر."
        elif closes[-1] < closes[-50]:
            trend = "الاتجاه العام يميل للهبوط."
        else:
            trend = "الاتجاه العام حيادي."

        # ---- 4) سلوك السعر (Price Action) ----
        last_close = closes[-1]
        prev_close = closes[-2]

        if last_close > prev_close:
            price_action = "تحسّن ملحوظ في حركة السعر اليومية."
        elif last_close < prev_close:
            price_action = "ضغط بيعي واضح في الحركة اليومية."
        else:
            price_action = "حركة سعرية مستقرة دون تغيّر كبير."

        # ---- 5) الدعم والمقاومة ----
        lowest = min(closes[-30:])
        highest = max(closes[-30:])
        sr = f"الدعم: {lowest:.2f} – المقاومة: {highest:.2f}"

        # ---- 6) المتوسطات (MA50 + MA200) ----
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / 200

        if ma50 > ma200:
            ma_text = "تقاطع إيجابي – متوسط 50 فوق 200."
        else:
            ma_text = "تقاطع سلبي – متوسط 50 أسفل 200."

        moving_averages = f"MA50: {ma50:.2f} – MA200: {ma200:.2f}\n{ma_text}"

        # ---- 7) مؤشر القوة النسبية RSI ----
        rsi = calculate_rsi(closes)
        if rsi > 70:
            rsi_state = "تشبّع شرائي"
        elif rsi < 30:
            rsi_state = "تشبّع بيعي"
        else:
            rsi_state = "منطقة حيادية"

        # ---- 8) النماذج الفنية (مبسطة) ----
        patterns = detect_patterns(closes)

        if patterns == "None":
            patterns = "لا يوجد نموذج واضح حالياً."

        # ---- 9) الرسالة النهائية ----
        msg = f"""
📌 **تحليل فني لعملة {symbol_upper}**

💰 **السعر الحالي:** {price}$

📉 **الاتجاه العام (Daily):**
{trend}

🧭 **سلوك السعر:**
{price_action}

🎯 **الدعوم والمقاومات:**
{sr}

🔷 **نماذج فنية:**
{patterns}

📊 **المتوسطات المتحركة:**
{moving_averages}

📈 **RSI:** {rsi:.2f} – ({rsi_state})

---

🤖 **تحليل مُولّد بواسطة IN CRYPTO AI**
        """

        return msg

    except Exception as e:
        return f"حدث خطأ أثناء تحليل العملة: {e}"
