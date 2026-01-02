# analysis/backtest/run_market_structure.py

from analysis.data.candles import get_historical_candles
from analysis.schools.market_structure.structure_scanner import scan_market_structure


def run_market_structure(
    symbol="BTCUSDT",
    timeframe="1h",
    limit=500
):
    print("\n🔍 Running Market Structure Scan")
    print("=" * 60)
    print(f"Symbol    : {symbol}")
    print(f"Timeframe : {timeframe}")
    print(f"Candles   : {limit}")
    print("=" * 60)

    # =====================
    # 1) Load candles (CSV only)
    # =====================
    candles = get_historical_candles(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit
    )

    if not candles or len(candles) < 50:
        print("❌ Not enough candle data")
        return

    print(f"📊 Candles loaded: {len(candles)}")

    # =====================
    # 2) Scan market structure
    # =====================
    result = scan_market_structure(candles)

    if not result.get("valid"):
        print(f"❌ Scan failed: {result.get('reason')}")
        return

    # =====================
    # 3) Report
    # =====================
    print("\n📐 MARKET STRUCTURE RESULT")
    print("-" * 60)
    print(f"Trend          : {result['trend']}")
    print(f"Total swings   : {result['total_swings']}")

    print("\n📍 Last Structure Points")
    print("-" * 60)
    for s in result["last_structure"]:
        print(
            f"{s['type']:>3} | "
            f"price={s['price']} | "
            f"index={s['index']}"
        )

    print("\n✅ Market Structure scan finished\n")


# =====================
# Run directly
# =====================
if __name__ == "__main__":
    run_market_structure(
        symbol="BTCUSDT",
        timeframe="1h",
        limit=500
    )
