# analysis/backtest/run_harmonic_backtest.py

from collections import defaultdict

from analysis.schools.harmonic_scanner import scan_harmonic_patterns
from analysis.schools.harmonic_backtest import backtest_harmonic_patterns
from analysis.data.candles import get_historical_candles


def run_harmonic_backtest(
    symbol="BTCUSDT",
    timeframe="1h",
    limit=500
):
    print("\n🔍 Running Harmonic Backtest")
    print("=" * 40)
    print(f"Symbol: {symbol}")
    print(f"Timeframe: {timeframe}")
    print("=" * 40)

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

    print(f"📊 Candles loaded: {len(candles)}")

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

    print(f"📐 Harmonic patterns found: {len(patterns)}")

    # =====================
    # 3) Backtest
    # =====================
    results = backtest_harmonic_patterns(patterns, candles)

    if not results:
        print("❌ No backtest results")
        return

    # =====================
    # 4) Global stats
    # =====================
    wins = sum(1 for r in results if r["result"] == "WIN")
    losses = sum(1 for r in results if r["result"] == "LOSS")
    total = wins + losses
    win_rate = (wins / total * 100) if total else 0

    # =====================
    # 5) Pattern stats
    # =====================
    pattern_stats = defaultdict(lambda: {"WIN": 0, "LOSS": 0})
    direction_stats = defaultdict(lambda: {"WIN": 0, "LOSS": 0})

    for r in results:
        pattern_stats[r["pattern"]][r["result"]] += 1
        direction_stats[r["direction"]][r["result"]] += 1

    # =====================
    # 6) Report
    # =====================
    print("\n📊 BACKTEST SUMMARY")
    print("=" * 40)
    print(f"Total trades : {total}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(f"Win rate     : {win_rate:.2f}%")
    print("=" * 40)

    # =====================
    # 7) Pattern breakdown
    # =====================
    print("\n📐 PERFORMANCE BY PATTERN")
    print("-" * 40)
    for pattern, stat in pattern_stats.items():
        p_total = stat["WIN"] + stat["LOSS"]
        if p_total == 0:
            continue
        p_wr = stat["WIN"] / p_total * 100
        print(
            f"{pattern:15} | Trades: {p_total:3} | "
            f"W: {stat['WIN']:2} | L: {stat['LOSS']:2} | "
            f"WR: {p_wr:5.1f}%"
        )

    # =====================
    # 8) Direction breakdown
    # =====================
    print("\n📈 PERFORMANCE BY DIRECTION")
    print("-" * 40)
    for direction, stat in direction_stats.items():
        d_total = stat["WIN"] + stat["LOSS"]
        if d_total == 0:
            continue
        d_wr = stat["WIN"] / d_total * 100
        print(
            f"{direction:8} | Trades: {d_total:3} | "
            f"W: {stat['WIN']:2} | L: {stat['LOSS']:2} | "
            f"WR: {d_wr:5.1f}%"
        )

    # =====================
    # 9) Detailed trades (اختياري)
    # =====================
    print("\n🧾 SAMPLE TRADES")
    print("-" * 40)
    for r in results[:10]:  # أول 10 صفقات بس
        print(
            f"{r['pattern']} | {r['direction']} | {r['result']}"
        )

    print("\n✅ Backtest finished\n")


# =====================
# Run directly
# =====================
if __name__ == "__main__":
    run_harmonic_backtest(
        symbol="BTCUSDT",
        timeframe="1h",
        limit=800
    )
