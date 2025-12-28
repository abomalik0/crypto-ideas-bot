"""
engine_smart_snapshot.py

✅ الهدف: تجميع Smart Snapshot من:
- data_sources (price)
- metrics (range/volatility)
- risk (risk score/level)
- pulse (speed/accel/conf/regime)
- events (institutional signals)
- classifier (alert level + shock score)

ملاحظة: الملف ده جاهز للربط التدريجي لاحقاً بدون كسر الشغل الحالي.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import config
from engine_data_sources import fetch_price_data
from engine_metrics import build_symbol_metrics
from engine_risk import evaluate_risk_level
from engine_smart_pulse import update_market_pulse
from engine_smart_events import detect_institutional_events
from engine_smart_classifier import classify_alert_level


def _safe_logger_info(msg: str, *args) -> None:
    try:
        logger = getattr(config, "logger", None)
        if logger:
            logger.info(msg, *args)
    except Exception:
        pass


def _safe_logger_exception(msg: str, *args) -> None:
    try:
        logger = getattr(config, "logger", None)
        if logger:
            logger.exception(msg, *args)
    except Exception:
        pass


def _compute_zones(price: float, high: float, low: float) -> Dict[str, Any]:
    """
    Zones بسيطة (مش ICT/SMC)، مجرد مستويات تقريبية مفيدة للعرض.
    لاحقاً لما نربط مدارس التحليل هنستبدلها بزونات أقوى.
    """
    if price <= 0:
        return {"support": None, "resistance": None, "mid": None, "band": None}

    mid = (high + low) / 2.0 if high >= low else price
    band = max(0.0, (high - low) / price * 100.0)  # band% تقريبي

    # دعم/مقاومة تقريبية (قريبة من low/high)
    support = low
    resistance = high

    return {
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "mid": round(mid, 2),
        "band_pct": round(band, 2),
    }


def _adaptive_interval_seconds(level: str, regime: Optional[str]) -> int:
    """
    كل ما الخطر أعلى، نقلل الفاصل الزمني للتحديث.
    """
    if level == "critical":
        base = 60
    elif level == "high":
        base = 120
    elif level == "medium":
        base = 180
    else:
        base = 240

    if regime == "explosion":
        base = max(45, base - 30)
    elif regime == "expansion":
        base = max(60, base - 15)

    return int(base)


def compute_smart_market_snapshot(user_symbol: str = "BTCUSDT") -> Optional[Dict[str, Any]]:
    """
    يرجع Snapshot موحد جاهز للاستخدام في SmartAlert.

    الشكل النهائي:
    {
      "symbol": ...,
      "price_data": {...},
      "metrics": {...},
      "risk": {...},
      "pulse": {...},
      "events": {...},
      "alert": {...},
      "zones": {...},
      "adaptive_interval": int,
      "reason": str
    }
    """
    try:
        price_data = fetch_price_data(user_symbol)
        if not price_data:
            _safe_logger_info("Smart snapshot: no price data for %s", user_symbol)
            return None

        price = float(price_data.get("price") or 0.0)
        change_pct = float(price_data.get("change_pct") or 0.0)
        high = float(price_data.get("high") or price)
        low = float(price_data.get("low") or price)

        metrics = build_symbol_metrics(
            price=price,
            change_pct=change_pct,
            high=high,
            low=low,
        )

        if not metrics:
            _safe_logger_info("Smart snapshot: no metrics for %s", user_symbol)
            return None

        risk = evaluate_risk_level(
            change_pct=float(metrics.get("change_pct", 0.0)),
            volatility_score=float(metrics.get("volatility_score", 0.0)),
        )

        pulse = update_market_pulse(metrics)
        events = detect_institutional_events(pulse, metrics, risk)
        alert = classify_alert_level(pulse, metrics, risk, events)

        zones = _compute_zones(price, high, low)

        level = alert.get("level") or "low"
        regime = pulse.get("regime")
        adaptive_interval = _adaptive_interval_seconds(level, regime)

        # reason مختصر للتشخيص
        reasons = []
        if alert.get("reasons"):
            reasons.extend(alert["reasons"])
        if events.get("active_labels"):
            reasons.extend(events["active_labels"])

        reason_text = " | ".join(str(r) for r in reasons[:10]) if reasons else ""

        snapshot = {
            "symbol": user_symbol,
            "price_data": price_data,
            "metrics": metrics,
            "risk": risk,
            "pulse": pulse,
            "events": events,
            "alert": alert,
            "zones": zones,
            "adaptive_interval": adaptive_interval,
            "reason": reason_text,
        }

        return snapshot

    except Exception as e:
        _safe_logger_exception("Error in compute_smart_market_snapshot: %s", e)
        return None


def flatten_snapshot_for_log(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    مساعد اختياري: يطلع المفاتيح اللي عادة بتتسجل في اللوج.
    (مش مستخدم حالياً إلا لو حبيت تربطه بعدين)
    """
    metrics = snapshot.get("metrics") or {}
    pulse = snapshot.get("pulse") or {}
    risk = snapshot.get("risk") or {}
    alert = snapshot.get("alert") or {}

    return {
        "price": metrics.get("price"),
        "chg": metrics.get("change_pct"),
        "range": metrics.get("range_pct"),
        "vol": metrics.get("volatility_score"),
        "level": alert.get("level"),
        "shock": alert.get("shock_score"),
        "speed": pulse.get("speed_index"),
        "accel": pulse.get("accel_index"),
        "conf": pulse.get("direction_confidence"),
        "risk_score": risk.get("score"),
        "structural_risk": 0.0,  # placeholder (هنقويه لاحقاً)
    }
