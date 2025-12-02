# ==========================================
#              SERVICES MODULE
#      (Realtime Engine + Weekly + Smart Alert)
# ==========================================

import json
import threading
import time
from datetime import datetime, timedelta

import config
from config import send_message, add_alert_history
from analysis_engine import (
    format_analysis,
    format_market_report,
    format_risk_test,
    format_weekly_ai_report,
    get_market_metrics_cached,
    compute_smart_market_snapshot,
    format_ai_alert,
)

# ==============================
#   Caching helpers
# ==============================

def get_cached_response(key: str, builder, cache_seconds: int = 30):
    """
    دالة بسيطة لإعادة استخدام آخر رد جاهز إن وُجد،
    وإلا تستدعى الدالة التى تبنيه.

    لا تستخدم أى بنية معقّدة فى الكاش: مجرد نصوص فى REALTIME_CACHE.
    """
    try:
        value = config.REALTIME_CACHE.get(key)
    except Exception:
        value = None

    if value:
        return value

    value = builder()
    try:
        config.REALTIME_CACHE[key] = value
    except Exception:
        pass
    return value


# ==============================
#   Snapshot persistence (اختيارى)
# ==============================

def load_snapshot():
    """
    تحميل لقطة بسيطة (Snapshot) من ملف إن وُجد، لتسريع أول تشغيل.
    إذا الملف غير موجود أو حدث خطأ → نكتفى باللوج ولا نرفع استثناء.
    """
    path = getattr(config, "SNAPSHOT_FILE", None)
    if not path:
        config.logger.info("No SNAPSHOT_FILE configured, skipping load.")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        config.logger.info("Snapshot file not found, starting cold.")
        return
    except Exception as e:
        config.logger.exception("Failed to load snapshot file: %s", e)
        return

    try:
        cache = data.get("REALTIME_CACHE") or {}
        config.REALTIME_CACHE.update(cache)
        config.logger.info("Snapshot loaded with keys: %s", list(cache.keys()))
    except Exception as e:
        config.logger.exception("Error while applying snapshot: %s", e)


def save_snapshot():
    """
    حفظ Snapshot خفيفة من الـ REALTIME_CACHE إلى ملف (اختيارى).
    تُستخدم من الـ watchdog كل فترة مثلاً.
    """
    path = getattr(config, "SNAPSHOT_FILE", None)
    if not path:
        return

    payload = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "REALTIME_CACHE": dict(config.REALTIME_CACHE),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        config.logger.info("Snapshot saved to %s", path)
    except Exception as e:
        config.logger.exception("Failed to save snapshot: %s", e)


# ==============================
#   Realtime Engine
# ==============================

def realtime_engine_loop():
    """
    ثريد يقوم بتحديث الكاش النصى للتحليلات بشكل دورى
    حتى تكون الأوامر سريعة الاستجابة ولا نضغط على مزود البيانات.
    """
    # منع رسالة التحذير فى أول تشغيل
    config.LAST_REALTIME_TICK = time.time()
    config.logger.info("Realtime engine loop started.")

    while True:
        try:
            now = time.time()
            config.LAST_REALTIME_TICK = now

            # بناء الردود الأساسية
            try:
                config.REALTIME_CACHE["btc_analysis"] = format_analysis("BTCUSDT")
            except Exception as e:
                config.logger.exception("Realtime: error in btc_analysis: %s", e)

            try:
                config.REALTIME_CACHE["market_report"] = format_market_report()
            except Exception as e:
                config.logger.exception("Realtime: error in market_report: %s", e)

            try:
                config.REALTIME_CACHE["risk_test"] = format_risk_test()
            except Exception as e:
                config.logger.exception("Realtime: error in risk_test: %s", e)

            try:
                config.REALTIME_CACHE["weekly_report"] = format_weekly_ai_report()
            except Exception as e:
                config.logger.exception("Realtime: error in weekly_report: %s", e)

            config.REALTIME_CACHE["last_update"] = datetime.utcnow().isoformat(
                timespec="seconds"
            )

            time.sleep(10)
        except Exception as e:
            config.logger.exception("Error in realtime engine loop: %s", e)
            time.sleep(5)


def start_realtime_thread():
    t = threading.Thread(
        target=realtime_engine_loop, daemon=True, name="RealtimeEngine"
    )
    t.start()
    config.logger.info("Realtime engine thread started.")
    return t


# ==============================
#   Weekly scheduler
# ==============================

def _should_send_weekly_report(now_utc: datetime) -> bool:
    """
    شرط بسيط لإرسال التقرير الأسبوعى مرة واحدة يوم الأحد.
    يمكن تعديل اليوم/الساعة لاحقًا حسب الحاجة.
    """
    last = getattr(config, "LAST_WEEKLY_SENT_DATE", None)
    weekday = now_utc.weekday()  # Monday=0 ... Sunday=6
    # نختار الأحد (6) مثلاً
    if weekday != 6:
        return False

    today_str = now_utc.strftime("%Y-%m-%d")
    if last == today_str:
        return False

    # نفترض أننا نرسل بعد الساعة 12:00 ظهرًا بتوقيت UTC
    if now_utc.hour < 12:
        return False

    return True


def send_weekly_report_to_all_chats():
    """
    إرسال التقرير الأسبوعى لكل الشاتات المعروفة.
    يُستدعى من /weekly_ai_report أو من الـ scheduler.
    """
    try:
        report = format_weekly_ai_report()
    except Exception as e:
        config.logger.exception("Error building weekly AI report: %s", e)
        return []

    sent_to = []
    for chat_id in list(config.KNOWN_CHAT_IDS):
        try:
            send_message(chat_id, report)
            sent_to.append(chat_id)
        except Exception as e:
            config.logger.exception("Failed to send weekly report to %s: %s", chat_id, e)

    if sent_to:
        config.LAST_WEEKLY_SENT_DATE = datetime.utcnow().strftime("%Y-%m-%d")

    return sent_to


def weekly_scheduler_loop():
    config.LAST_WEEKLY_TICK = time.time()
    config.logger.info("Weekly scheduler loop started.")

    while True:
        try:
            now = datetime.utcnow()
            config.LAST_WEEKLY_TICK = time.time()

            if _should_send_weekly_report(now):
                sent_to = send_weekly_report_to_all_chats()
                config.logger.info(
                    "Weekly report sent automatically to %d chats.", len(sent_to)
                )

            time.sleep(60)  # فحص كل دقيقة
        except Exception as e:
            config.logger.exception("Weekly scheduler error: %s", e)
            time.sleep(30)


def start_weekly_scheduler_thread():
    t = threading.Thread(
        target=weekly_scheduler_loop, daemon=True, name="WeeklyScheduler"
    )
    t.start()
    config.logger.info("Weekly scheduler thread started.")
    return t


# ==============================
#   Smart Alert + Micro-Trend
# ==============================

def _compute_mti(metrics: dict, pulse: dict) -> float:
    """
    حساب مؤشر Micro-Trend (MTI) من 0 إلى 100
    بناءً على:
      - التغير اليومى
      - التقلب العام
      - سرعة الحركة اللحظية
      - التسارع اللحظى
    """
    try:
        change = float(metrics.get("change_pct") or 0.0)
        vol = float(metrics.get("volatility_score") or 0.0)
        speed = float(pulse.get("speed_index") or 0.0)
        accel = float(pulse.get("accel_index") or 0.0)
    except Exception:
        return 0.0

    # تحويل القيم لمقاييس ضمنية بسيطة
    change_component = min(30.0, abs(change) * 2.0)
    vol_component = min(25.0, vol * 1.2)
    speed_component = min(25.0, abs(speed) * 20.0)
    accel_component = min(20.0, max(0.0, abs(accel) * 30.0))

    mti = change_component + vol_component + speed_component + accel_component
    if mti > 100:
        mti = 100.0
    return round(mti, 2)


def _should_trigger_early_warning(metrics: dict, pulse: dict, events: dict, mti: float) -> bool:
    """
    منطق اكتشاف "قبل الانهيار" المبكر.
    نركز على:
      - تسارع هبوطى
      - سيولة خارجة
      - أحداث سلبية قوية
      - MTI مرتفع
    """
    try:
        change = float(metrics.get("change_pct") or 0.0)
        speed = float(pulse.get("speed_index") or 0.0)
        accel = float(pulse.get("accel_index") or 0.0)
    except Exception:
        return False

    if mti < 82.0:
        return False

    # نحتاج نوعًا ما من الهبوط الفعلى أو تسارع سلبى واضح
    if change > 0 and accel > -0.15:
        return False

    active_labels = set((events.get("active_labels") or []))

    bearish_signals = {
        "momentum_spike_down",
        "liquidity_flush",
        "stop_run_down",
        "panic_sell",
    }

    has_bearish_event = bool(active_labels & bearish_signals)

    # شرط أساسى:
    #   - تسارع سلبى
    #   - إما حدث سلبى أو سرعة هبوط عالية
    if accel <= -0.15 and (has_bearish_event or speed <= -0.25):
        return True

    return False


def _build_early_warning_message(snapshot: dict, mti: float) -> str:
    metrics = snapshot.get("metrics") or {}
    pulse = snapshot.get("pulse") or {}
    zones = snapshot.get("zones") or {}
    risk = snapshot.get("risk") or {}

    price = metrics.get("price")
    change = metrics.get("change_pct")
    range_pct = metrics.get("range_pct")
    volatility_score = metrics.get("volatility_score")
    speed = pulse.get("speed_index")
    accel = pulse.get("accel_index")
    liquidity_pulse = metrics.get("liquidity_pulse")
    risk_level = risk.get("level")
    risk_emoji = risk.get("emoji", "")

    downside_1 = zones.get("downside_zone_1")
    downside_2 = zones.get("downside_zone_2")

    def _fmt(v, fmt="{:,.2f}"):
        try:
            if v is None:
                return "-"
            return fmt.format(float(v))
        except Exception:
            return str(v)

    def _fmt_int(v):
        try:
            if v is None:
                return "-"
            return f"{int(round(float(v))):,}"
        except Exception:
            return str(v)

    targets_lines = []
    if downside_1 and len(downside_1) == 2:
        mid1 = (downside_1[0] + downside_1[1]) / 2.0
        targets_lines.append(f"{_fmt_int(mid1)}$")
    if downside_2 and len(downside_2) == 2:
        mid2 = (downside_2[0] + downside_2[1]) / 2.0
        targets_lines.append(f"{_fmt_int(mid2)}$")

    if not targets_lines and downside_1:
        targets_lines.append(f"{_fmt_int(downside_1[0])}$")
        if len(downside_1) > 1:
            targets_lines.append(f"{_fmt_int(downside_1[1])}$")

    targets_text = "\n".join(f"• {t}" for t in targets_lines) if targets_lines else "• مستويات أعمق محتملة أسفل السعر الحالى فى حالة استمرار نفس الزخم."

    try:
        from analysis_engine import _risk_level_ar as _rl_txt
        risk_text = _rl_txt(risk_level) if risk_level else "غير معروف"
    except Exception:
        risk_text = "غير معروف"

    msg = f"""
⚠️ <b>Early Warning — تحذير مبكر قبل حركة قوية</b>

• السعر الحالى للبيتكوين: <b>${_fmt_int(price)}</b> ({_fmt(change, "{:+.2f}%")})
• مدى اليوم ≈ {_fmt(range_pct, "{:.2f}")}% / التقلب ≈ {_fmt(volatility_score, "{:.1f}")} / 100

• تسارع الهبوط اللحظى (تقريبى): {_fmt(accel, "{:+.3f}")}
• سرعة الحركة اللحظية: {_fmt(speed, "{:+.3f}")}
• مؤشر الاتجاه اللحظى (MTI): <b>{mti:.1f} / 100</b>

• نبض السيولة: {liquidity_pulse or "-"}
• مستوى المخاطر العام: {risk_emoji} {risk_text}

🎯 <b>أهداف هبوط محتملة إذا اكتمل السيناريو:</b>
{targets_text}

⏳ هذا التحذير مبنى على تسارع لحظى حاليًا (0.2–1 ثانية) وقد يسبق الحركة الفعلية بعد ثوانٍ.
⚠️ ليس توصية مباشرة بالبيع أو الشراء، وإنما تنبيه تعليمى مبكر.
""".strip()

    return msg


def smart_alert_loop():
    """
    ثريد متقدّم يقوم بتحليل Snapshot ذكى باستمرار، مع:
        - فترة فحص تكيفية (من 0.2 ثانية إلى عدة ثوانٍ)
        - منطق Early Warning قبل الانهيار
        - منطق منع التكرار والـ Spam
        - إرسال التنبيه فقط عند وجود حدث "يستحق" الإرسال
    """
    # تهيئة متغيرات على مستوى config لو غير موجودة
    if not hasattr(config, "LAST_SMART_ALERT_TIME"):
        config.LAST_SMART_ALERT_TIME = 0.0
    if not hasattr(config, "LAST_SMART_ALERT_KEY"):
        config.LAST_SMART_ALERT_KEY = None
    if not hasattr(config, "LAST_EARLY_WARNING_TIME"):
        config.LAST_EARLY_WARNING_TIME = 0.0

    config.LAST_SMART_TICK = time.time()
    config.logger.info("Smart alert loop started.")

    base_interval = 3.0  # ثوانى فى الوضع الهادئ
    min_interval = 0.2   # أسرع فحص أثناء الانفجار
    max_interval = 8.0   # أبطأ فحص

    while True:
        start_t = time.time()
        config.LAST_SMART_TICK = start_t

        interval = base_interval

        try:
            snapshot = compute_smart_market_snapshot()
        except Exception as e:
            config.logger.exception("Error in compute_smart_market_snapshot: %s", e)
            time.sleep(5)
            continue

        if not snapshot:
            time.sleep(5)
            continue

        metrics = snapshot.get("metrics") or {}
        risk = snapshot.get("risk") or {}
        pulse = snapshot.get("pulse") or {}
        events = snapshot.get("events") or {}
        alert_level = snapshot.get("alert_level") or {}
        zones = snapshot.get("zones") or {}

        # حفظ آخر Snapshot للوحة التحكم إن رغبت
        try:
            config.LAST_SMART_SNAPSHOT = {
                "time": datetime.utcnow().isoformat(timespec="seconds"),
                "metrics": metrics,
                "risk": risk,
                "pulse": pulse,
                "events": events,
                "alert_level": alert_level,
                "zones": zones,
            }
        except Exception:
            pass

        # حساب MTI من النبض الحالى
        mti = _compute_mti(metrics, pulse)

        # محاولة قراءة الفترة التكيفية المقترحة إن وُجدت
        adaptive_interval = snapshot.get("adaptive_interval")
        if adaptive_interval is not None:
            try:
                adaptive_interval = float(adaptive_interval)
                interval = max(min_interval, min(max_interval, adaptive_interval))
            except Exception:
                interval = base_interval
        else:
            interval = base_interval

        # شدة الصدمة الحالية
        shock_score = float(alert_level.get("shock_score") or 0.0)
        level = (alert_level.get("level") or "").lower()
        trend_bias = alert_level.get("trend_bias") or ""
        active_labels = events.get("active_labels") or []

        # ============= منطق Early Warning =============
        early_warning = False
        now = time.time()

        # Cooldown قوى لـ Early Warning (مثلاً 5 دقائق)
        early_cooldown = 5 * 60

        if (
            _should_trigger_early_warning(metrics, pulse, events, mti)
            and (now - config.LAST_EARLY_WARNING_TIME) >= early_cooldown
        ):
            try:
                ew_msg = _build_early_warning_message(snapshot, mti)

                # إرسال للأدمن + كل المستخدمين المعروفين
                targets = set(config.KNOWN_CHAT_IDS) | {config.ADMIN_CHAT_ID}
                sent_count = 0
                for chat_id in targets:
                    try:
                        send_message(chat_id, ew_msg)
                        sent_count += 1
                    except Exception as e:
                        config.logger.exception(
                            "Failed to send early warning to %s: %s", chat_id, e
                        )

                metrics_price = metrics.get("price")
                metrics_change = metrics.get("change_pct")
                add_alert_history(
                    "smart_early",
                    "Early warning micro-trend",
                    price=metrics_price,
                    change=metrics_change,
                )

                config.LAST_EARLY_WARNING_TIME = now
                config.logger.info(
                    "Early warning sent: mti=%.1f shock=%.1f sent_to=%d",
                    mti,
                    shock_score,
                    sent_count,
                )
                early_warning = True
            except Exception as e:
                config.logger.exception("Error while sending early warning: %s", e)

        # ============= منطق Smart Alert الرئيسى =============
        # نرسل فقط فى الحالات القوية، مع Cooldown منع التكرار
        # للحد من الإزعاج (Noise).
        min_cooldown = 5 * 60  # 5 دقائق بين كل تنبيهين عاديين

        alert_key = f"{level}|{int(round(shock_score))}|{trend_bias}|{','.join(active_labels)}"

        strong_condition = False

        # لو تم إرسال Early Warning فى هذه الدورة، نتجنب إرسال تنبيه عادى إضافى
        if early_warning:
            strong_condition = False

        # مستوى عالى أو صدمة قوية
        if level in ("high", "extreme"):
            strong_condition = True
        elif shock_score >= 70:
            strong_condition = True
        elif shock_score >= 55 and any(
            lbl in active_labels
            for lbl in ("vol_explosion", "liquidity_flush", "panic_sell")
        ):
            strong_condition = True

        # لو مفيش سبب قوى → لا تنبيه عادى
        if strong_condition:
            elapsed = now - config.LAST_SMART_ALERT_TIME
            if elapsed >= min_cooldown and alert_key != config.LAST_SMART_ALERT_KEY:
                try:
                    text = format_ai_alert()
                    targets = set(config.KNOWN_CHAT_IDS) | {config.ADMIN_CHAT_ID}
                    sent_count = 0
                    for chat_id in targets:
                        try:
                            send_message(chat_id, text)
                            sent_count += 1
                        except Exception as e:
                            config.logger.exception(
                                "Failed to send smart alert to %s: %s", chat_id, e
                            )

                    metrics_price = metrics.get("price")
                    metrics_change = metrics.get("change_pct")
                    add_alert_history(
                        "smart",
                        f"{level}: {snapshot.get('reason') or 'Smart alert condition'}",
                        price=metrics_price,
                        change=metrics_change,
                    )

                    config.LAST_SMART_ALERT_TIME = now
                    config.LAST_SMART_ALERT_KEY = alert_key

                    config.logger.info(
                        "Smart alert sent: level=%s shock=%.1f sent_to=%d key=%s",
                        level,
                        shock_score,
                        sent_count,
                        alert_key,
                    )
                except Exception as e:
                    config.logger.exception("Error while sending smart alert: %s", e)

        # النوم حسب الفترة التكيفية
        elapsed_loop = time.time() - start_t
        sleep_for = max(0.1, interval - elapsed_loop)
        time.sleep(sleep_for)


def start_smart_alert_thread():
    t = threading.Thread(
        target=smart_alert_loop, daemon=True, name="SmartAlertEngine"
    )
    t.start()
    config.logger.info("Smart alert thread started.")
    return t


# ==============================
#   Watchdog
# ==============================

def watchdog_loop():
    """
    ثريد بسيط يراقب زمن آخر Tick لكل ثريد رئيسى
    ويمكنه مستقبلاً إعادة تشغيل أى ثريد متوقف (إدارياً).
    حالياً يكتفى باللوج فقط.
    """
    config.LAST_WATCHDOG_TICK = time.time()
    config.logger.info("Watchdog loop started.")

    while True:
        try:
            now = time.time()
            config.LAST_WATCHDOG_TICK = now

            def _age(name, attr):
                val = getattr(config, attr, None)
                if not val:
                    return None
                return now - float(val)

            realtime_age = _age("realtime", "LAST_REALTIME_TICK")
            weekly_age = _age("weekly", "LAST_WEEKLY_TICK")
            smart_age = _age("smart", "LAST_SMART_TICK")

            config.logger.debug(
                "Watchdog: realtime_age=%s weekly_age=%s smart_age=%s",
                realtime_age,
                weekly_age,
                smart_age,
            )

            # حفظ Snapshot كل 5 دقائق مثلاً
            try:
                last_snapshot = getattr(config, "LAST_SNAPSHOT_SAVE", 0.0)
                if now - last_snapshot >= 5 * 60:
                    save_snapshot()
                    config.LAST_SNAPSHOT_SAVE = now
            except Exception as e:
                config.logger.exception("Watchdog snapshot save error: %s", e)

            time.sleep(30)
        except Exception as e:
            config.logger.exception("Watchdog loop error: %s", e)
            time.sleep(30)


def start_watchdog_thread():
    t = threading.Thread(
        target=watchdog_loop, daemon=True, name="Watchdog"
    )
    t.start()
    config.logger.info("Watchdog thread started.")
    return t
