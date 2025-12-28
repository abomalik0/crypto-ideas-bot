"""
engine_smart_events.py

✅ الهدف: اكتشاف "أحداث مؤسسية/صدمة سيولة/انفجار تقلب" بناءً على:
- metrics (change/range/volatility)
- pulse (speed/accel/regime)
- risk (risk level)

ملاحظة: هذا الملف جاهز للنقل التدريجي من analysis_engine.py بدون كسر الشغل الحالي.
"""

from __future__ import annotations


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
        "liquidity_shock": False,
        "regime_switch": False,
        "details": {},
    }

    # انفجار تقلب
    if vol >= 70 or (regime == "explosion" and range_pct >= 8):
        events["vol_explosion"] = True
        events["details"]["vol_explosion_reason"] = (
            f"vol={vol:.1f}, range={range_pct:.2f}, regime={regime}"
        )

    # Spike في الزخم (هبوط/صعود)
    if speed >= 35 and accel >= 10 and change <= -1.2:
        events["momentum_spike_down"] = True
        events["details"]["momentum_spike_down_reason"] = (
            f"speed={speed:.1f}, accel={accel:.1f}, chg={change:.2f}"
        )

    if speed >= 35 and accel >= 10 and change >= 1.2:
        events["momentum_spike_up"] = True
        events["details"]["momentum_spike_up_reason"] = (
            f"speed={speed:.1f}, accel={accel:.1f}, chg={change:.2f}"
        )

    # صدمة سيولة: تقلب عالي + تسارع + مخاطرة مرتفعة أو حركة قوية
    if (vol >= 60 and speed >= 30) and (risk_level == "high" or abs(change) >= 2.5):
        events["liquidity_shock"] = True
        events["details"]["liquidity_shock_reason"] = (
            f"risk={risk_level}, vol={vol:.1f}, speed={speed:.1f}, chg={change:.2f}"
        )

    # تحول في نمط السوق
    if prev_regime and prev_regime != regime:
        events["regime_switch"] = True
        events["details"]["regime_switch_reason"] = f"{prev_regime} -> {regime}"

    active_labels: list[str] = []
    if events["vol_explosion"]:
        active_labels.append("انفجار تقلبات (Volatility Explosion)")
    if events["momentum_spike_down"]:
        active_labels.append("هبوط مفاجئ بزخم (Momentum Spike Down)")
    if events["momentum_spike_up"]:
        active_labels.append("صعود مفاجئ بزخم (Momentum Spike Up)")
    if events["liquidity_shock"]:
        active_labels.append("صدمة سيولة (Liquidity Shock)")
    if events["regime_switch"]:
        active_labels.append("تحول فى نمط السوق (Regime Switch)")

    events["active_labels"] = active_labels
    events["active_count"] = len(active_labels)
    return events
