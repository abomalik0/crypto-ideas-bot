"""
engine_data_sources.py

✅ الهدف: كل شغل الشبكة (Binance/KuCoin/requests) + كاش الأسعار يكون هنا.
ده بيخلّي debugging أسرع، وأي مشكلة API نعرف مكانها فوراً.

⚠️ ملاحظة:
- لا يوجد أي تعامل مع توكنات هنا.
- يعتمد على config.HTTP_SESSION و config.PRICE_CACHE و config.CACHE_TTL_SECONDS و config.API_STATUS
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import config


# ==============================
#   Symbol normalization
# ==============================

def normalize_symbol(user_symbol: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    يحوّل الرمز المدخل لأشكال المنصات:
      - base: BTC
      - binance: BTCUSDT
      - kucoin: BTC-USDT
    """
    base = (user_symbol or "").strip().upper()
    base = base.replace("USDT", "").replace("-", "").strip()
    if not base:
        return None, None, None

    binance_symbol = base + "USDT"
    kucoin_symbol = base + "-USDT"
    return base, binance_symbol, kucoin_symbol


# ==============================
#   Lightweight cache
# ==============================

def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    item = config.PRICE_CACHE.get(key)
    if not item:
        return None
    if time.time() - float(item.get("time", 0)) > float(getattr(config, "CACHE_TTL_SECONDS", 15)):
        return None
    return item.get("data")


def _set_cached(key: str, data: Dict[str, Any]) -> None:
    config.PRICE_CACHE[key] = {
        "time": time.time(),
        "data": data,
    }


# ==============================
#   Exchange fetchers + API health
# ==============================

def fetch_from_binance(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Binance 24hr ticker
    """
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = config.HTTP_SESSION.get(url, params={"symbol": symbol}, timeout=10)
        config.API_STATUS["last_api_check"] = datetime.utcnow().isoformat(timespec="seconds")

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


def fetch_from_kucoin(symbol: str) -> Optional[Dict[str, Any]]:
    """
    KuCoin market stats
    """
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


# ==============================
#   Public API: fetch_price_data
# ==============================

def fetch_price_data(user_symbol: str) -> Optional[Dict[str, Any]]:
    """
    يرجع dict فيه: price/change/high/low/volume + exchange + symbol
    مع fallback Binance -> KuCoin + كاش خفيف.

    Returns None لو فشل كل شيء.
    """
    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    if not base or not binance_symbol or not kucoin_symbol:
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
