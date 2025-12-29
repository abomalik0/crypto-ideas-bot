"""
engine_smart_pulse.py

✅ Market Pulse Engine:
- keeps small history buffer in config.REALTIME_CACHE
- computes speed, acceleration, direction confidence
- estimates regime (calm/expansion/explosion)
- optional percentiles for vol/range when enough history exists

هدفنا: نخلي speed/accel/conf يبقوا real numbers بدل 0.0
"""

from __future__ import annotations

from typing import Any, Dict, List
import time
import math

import config


# -------------------------
# helpers
# -------------------------

def _now() -> float:
    return time.time()


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _percentile(values: List[float], p: float) -> float:
    """
    p from 0..100
    """
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    d0 = xs[int(f)] * (c - k)
    d1 = xs[int(c)] * (k - f)
    return float(d0 + d1)


def _get_hist() -> List[Dict[str, Any]]:
    cache = getattr(config, "REALTIME_CACHE", None)
    if cache is None:
        config.REALTIME_CACHE = {}
        cache = config.REALTIME_CACHE
    hist = cache.get("pulse_history")
    if not isinstance(hist, list):
        hist = []
        cache["pulse_history"] = hist
    return hist


def _push_hist(item: Dict[str, Any], max_len: int = 60) -> None:
    hist = _get_hist()
    hist.append(item)
    # keep last N
    if len(hist) > max_len:
        del hist[: len(hist) - max_len]


def _direction_confidence(hist: List[Dict[str, Any]], lookback: int = 12) -> float:
    """
    confidence: 0..100
    based on how consistent sign(change_pct) is in last lookback points.
    """
    xs = hist[-lookback:] if len(hist) >= lookback else hist[:]
    if len(xs) < 3:
        return 0.0

    signs = []
    for it in xs:
        ch = float(it.get("change_pct", 0.0))
        if ch > 0.03:
            signs.append(1)
        elif ch < -0.03:
            signs.append(-1)
        else:
            signs.append(0)

    non_zero = [s for s in signs if s != 0]
    if len(non_zero) < 3:
        return 0.0

    pos = sum(1 for s in non_zero if s > 0)
    neg = sum(1 for s in non_zero if s < 0)
    total = pos + neg
    if total == 0:
        return 0.0

    consistency = max(pos, neg) / total  # 0.5..1.0
    return _clamp(consistency * 100.0, 0.0, 100.0)


def _compute_speed(hist: List[Dict[str, Any]], lookback: int = 8) -> float:
    """
    Speed index: 0..50 تقريباً
    Uses average absolute delta of change_pct and range_pct.
    """
    xs = hist[-lookback:] if len(hist) >= lookback else hist[:]
    if len(xs) < 3:
        return 0.0

    deltas = []
    for i in range(1, len(xs)):
        a = float(xs[i].get("change_pct", 0.0))
        b = float(xs[i - 1].get("change_pct", 0.0))
        ra = float(xs[i].get("range_pct", 0.0))
        rb = float(xs[i - 1].get("range_pct", 0.0))
        deltas.append(abs(a - b) + 0.35 * abs(ra - rb))

    avg = sum(deltas) / max(1, len(deltas))
    # scale to a nicer index
    speed = _clamp(avg * 12.0, 0.0, 50.0)
    return speed


def _compute_accel(prev_speed: float, speed: float) -> float:
    """
    accel index ~ -25..25
    """
    return _clamp((speed - prev_speed), -25.0, 25.0)


def _regime(vol: float, range_pct: float, vol_pct: float, rng_pct: float) -> str:
    """
    Regime classification:
    - calm: low vol/range
    - expansion: medium
    - explosion: high vol/range or high percentiles
    """
    # primary thresholds
    if vol >= 70 or range_pct >= 8:
        return "explosion"
    if vol >= 45 or range_pct >= 5:
        return "expansion"

    # percentile assist if history exists
    if vol_pct >= 90 or rng_pct >= 90:
        return "explosion"
    if vol_pct >= 75 or rng_pct >= 75:
        return "expansion"
    return "calm"


# -------------------------
# public API
# -------------------------

def update_market_pulse(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    metrics expects:
    - change_pct
    - range_pct
    - volatility_score
    """
    change_pct = float(metrics.get("change_pct", 0.0))
    range_pct = float(metrics.get("range_pct", 0.0))
    vol = float(metrics.get("volatility_score", 0.0))

    hist = _get_hist()

    # push new tick
    _push_hist(
        {
            "t": _now(),
            "change_pct": change_pct,
            "range_pct": range_pct,
            "vol": vol,
        },
        max_len=60,
    )

    # compute percentiles when enough history
    vol_series = [float(it.get("vol", 0.0)) for it in hist[-40:]]
    rng_series = [float(it.get("range_pct", 0.0)) for it in hist[-40:]]

    if len(vol_series) >= 10:
        vol_pct = _percentile(vol_series, 85.0)
        rng_pct = _percentile(rng_series, 85.0)
        # convert current value percentile approximation:
        # (we use rank-like approach for a lightweight percentile indicator)
        vol_rank = sum(1 for x in vol_series if x <= vol) / len(vol_series) * 100.0
        rng_rank = sum(1 for x in rng_series if x <= range_pct) / len(rng_series) * 100.0
    else:
        vol_pct = 0.0
        rng_pct = 0.0
        vol_rank = 0.0
        rng_rank = 0.0

    # speed/accel
    prev_speed = float(hist[-2].get("speed_index", 0.0)) if len(hist) >= 2 else 0.0
    speed = _compute_speed(hist, lookback=8)
    accel = _compute_accel(prev_speed, speed)

    conf = _direction_confidence(hist, lookback=12)

    current_regime = _regime(vol, range_pct, vol_rank, rng_rank)
    prev_regime = None
    try:
        prev_regime = hist[-2].get("regime") if len(hist) >= 2 else None
    except Exception:
        prev_regime = None

    # store computed fields into latest hist item
    try:
        hist[-1]["speed_index"] = speed
        hist[-1]["accel_index"] = accel
        hist[-1]["direction_confidence"] = conf
        hist[-1]["regime"] = current_regime
        hist[-1]["prev_regime"] = prev_regime
        hist[-1]["vol_percentile"] = vol_rank
        hist[-1]["range_percentile"] = rng_rank
    except Exception:
        pass

    return {
        "speed_index": float(speed),
        "accel_index": float(accel),
        "direction_confidence": float(conf),
        "regime": current_regime,
        "prev_regime": prev_regime,
        "vol_percentile": float(vol_rank),
        "range_percentile": float(rng_rank),
        "history_len": len(hist),
    }
