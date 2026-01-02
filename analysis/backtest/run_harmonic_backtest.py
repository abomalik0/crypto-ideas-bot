# analysis/backtest/run_harmonic_backtest.py

from collections import defaultdict

from analysis.data.candles import get_historical_candles
from analysis.schools.harmonic_scanner import scan_harmonic_patterns
from analysis.schools.harmonic_backtest import backtest_harmonic_patterns
from analysis.schools.swing_engine import detect_swings


def run_harmonic_backtest(
    symbol="BTCUSDT",
    timeframe="1h",
    limit=2000  # ✅ اختبار قوي على 2000 شمعة
):
    print("\n🔍 Running Harmonic Backtest")
    print("=" * 60)
    print(f"Symbol    : {symbol}")
    print(f"Timeframe : {timeframe}")
    print(f"Candles   : {limit}")
    print("=" * 60)

    # =====================
    # 1) Load candles
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
    # 2) Detect swings
    # =====================
    swings = detect_swings(
        candles,
        lookback=3,
        min_move=0.002
    )

    if not swings or len(swings) < 5:
        print("❌ Not enough swings detected")
        return

    print(f"📈 Swings detected: {len(swings)}")

    # =====================
    # 3) Scan harmonic patterns
    # =====================
    patterns = scan_harmonic_patterns(
        symbol=symbol,
        timeframe=timeframe,
        swings=swings
    )

    if not patterns:
        print("❌ No harmonic patterns found")
        return

    print(f"📐 Harmonic patterns found: {len(patterns)}")

    # =====================
    # 4) Backtest
    # =====================
    results = backtest_harmonic_patterns(patterns, candles)

    if not results:
        print("❌ No backtest results")
        return

    # =====================
    # 5) Global statistics
    # =====================
    closed_trades = [r for r in results if r["result"] in ("WIN", "LOSS")]

    wins = sum(1 for r in closed_trades if r["result"] == "WIN")
    losses = sum(1 for r in closed_trades if r["result"] == "LOSS")
    total = wins + losses
    win_rate = (wins / total * 100) if total else 0

    open_trades = len(results) - total

    # =====================
    # 6) Breakdown stats
    # =====================
    pattern_stats = defaultdict(lambda: {"WIN": 0, "LOSS": 0})
    direction_stats = defaultdict(lambda: {"WIN": 0, "LOSS": 0})

    for r in closed_trades:
        pattern_stats[r["pattern"]][r["result"]] += 1
        direction_stats[r["direction"]][r["result"]] += 1

    # =====================
    # 7) Summary report
    # =====================
    print("\n📊 BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Total patterns   : {len(patterns)}")
    print(f"Closed trades    : {total}")
    print(f"Open trades      : {open_trades}")
    print(f"Wins             : {wins}")
    print(f"Losses           : {losses}")
    print(f"Win rate         : {win_rate:.2f}%")
    print("=" * 60)

    # =====================
    # 8) Performance by pattern
    # =====================
    print("\n📐 PERFORMANCE BY PATTERN")
    print("-" * 60)
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
    # 9) Performance by direction
    # =====================
    print("\n📈 PERFORMANCE BY DIRECTION")
    print("-" * 60)
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
    # 10) Sample trades
    # =====================
    print("\n🧾 SAMPLE TRADES (First 10)")
    print("-" * 60)
    for r in results[:10]:
        print(
            f"{r['pattern']} | {r['status']} | "
            f"{r['direction']} | {r['result']} | "
            f"conf={r['confidence']}"
        )

    print("\n✅ Backtest finished successfully\n")


# =====================
# Run directly
# =====================
if __name__ == "__main__":
    run_harmonic_backtest(
        symbol="BTCUSDT",
        timeframe="1h",
        limit=2000  # ✅ هنا التعديل النهائي
    )
