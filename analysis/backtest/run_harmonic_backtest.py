# analysis/backtest/run_harmonic_backtest.py

from analysis.schools.harmonic_scanner import scan_harmonic_patterns
from analysis.schools.harmonic_backtest import backtest_harmonic_patterns

# لو عندك دالة جاهزة لجلب البيانات
from analysis.data.candles import get_historical_candles


def run_harmonic_backtest(
    symbol="BTCUSDT",
    timeframe="1h",
    limit=500
):
    print("🔍 Running Harmonic Backtest...")
    print(f"Symbol: {symbol} | TF: {timeframe}")

    # =====================
    # 1) Get candles
    # =====================
    candles = get_historical_candles(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit
    )

    if not candles or len(candles) < 100:
        print("❌ Not enough candle data")
        return

    # =====================
    # 2) Scan patterns
    # =====================
    patterns = scan_harmonic_patterns(
        symbol=symbol,
        timeframe=timeframe,
        swings=None,
        candles=candles
    )

    if not patterns:
        print("❌ No harmonic patterns found")
        return

    print(f"📐 Found {len(patterns)} harmonic patterns")

    # =====================
    # 3) Backtest
    # =====================
    results = backtest_harmonic_patterns(patterns, candles)

    wins = sum(1 for r in results if r["result"] == "WIN")
    losses = sum(1 for r in results if r["result"] == "LOSS")
    total = wins + losses

    win_rate = (wins / total * 100) if total else 0

    # =====================
    # 4) Report
    # =====================
    print("\n📊 BACKTEST RESULT")
    print("=" * 30)
    print(f"Total trades : {total}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(f"Win rate     : {win_rate:.2f}%")
    print("=" * 30)


# تشغيل مباشر
if __name__ == "__main__":
    run_harmonic_backtest(
        symbol="BTCUSDT",
        timeframe="1h",
        limit=800
    )
