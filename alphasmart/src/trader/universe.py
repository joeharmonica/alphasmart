"""
AlphaSmart Trader universe definitions.

The Trader uses a wider pool than the monthly momentum book: a short book
needs breadth (shorting within a 21-name mega-cap momentum pool means
shorting the same names you'd hold next month). Membership rule mirrors
lessons.md #59: liquid US-listed large/mega caps chosen by market-cap and
liquidity, NOT by recent performance — the signal does the selection.

CORE_UNIVERSE  — the existing 21-name momentum pool (kept for overlap
                 studies and as the long-book prior).
EXTENDED_UNIVERSE — CORE + ~30 additional S&P-100-class names across
                 sectors (financials, energy, healthcare, staples,
                 industrials, comms) so the short side has a real
                 cross-section. All have 10y+ daily history except
                 UBER (2019 IPO — handled the same way CRWD is in the
                 momentum book: NaN until listed).
"""
from __future__ import annotations

# Existing paper-trade momentum pool (runner_main.EQUITY_UNIVERSE minus ETFs)
CORE_EQUITIES = sorted([
    "AAPL", "AMD", "AMZN", "ANET", "ASML", "AVGO", "CRWD", "GOOG", "LLY",
    "MA", "META", "MSFT", "MU", "NOW", "NVDA", "NVO", "PANW", "TSLA", "V",
])

# Additional liquid US-listed large caps (sector-diversified)
EXTENDED_ADDITIONS = sorted([
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC",
    # Energy
    "XOM", "CVX", "COP",
    # Healthcare
    "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO",
    # Staples / retail
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD",
    # Industrials
    "CAT", "BA", "GE", "HON", "UPS",
    # Tech / comms not already in core
    "NFLX", "CRM", "ORCL", "ADBE", "INTC", "QCOM", "TXN", "AMAT", "LRCX",
    "IBM", "DIS", "UBER",
])

EXTENDED_EQUITIES = sorted(set(CORE_EQUITIES) | set(EXTENDED_ADDITIONS))

# Index / regime symbols always fetched alongside
MARKET_SYMBOLS = ["SPY", "QQQ"]

ALL_SYMBOLS = sorted(set(EXTENDED_EQUITIES) | set(MARKET_SYMBOLS))
