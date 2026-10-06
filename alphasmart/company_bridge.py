#!/usr/bin/env python3
"""
Company research bridge — JSON CLI behind the frontend's /company pages.

Runs in its own venv (venv-company, yfinance 1.x) so it can never disturb
the paper-trade venv (yfinance 0.2.x) that the launchd jobs depend on.

    venv-company/bin/python company_bridge.py universe
    venv-company/bin/python company_bridge.py profile MSFT
    venv-company/bin/python company_bridge.py prices MSFT
    venv-company/bin/python company_bridge.py financials MSFT
    venv-company/bin/python company_bridge.py earnings MSFT
    venv-company/bin/python company_bridge.py news MSFT

Every response is cached under .cache/company/ with a per-kind TTL so page
loads don't hammer Yahoo. Add --refresh to bypass the cache.
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache" / "company"

# Same 57-name pool as src/trader/universe.py EXTENDED_EQUITIES.
UNIVERSE = sorted([
    "AAPL", "AMD", "AMZN", "ANET", "ASML", "AVGO", "CRWD", "GOOG", "LLY",
    "MA", "META", "MSFT", "MU", "NOW", "NVDA", "NVO", "PANW", "TSLA", "V",
    "JPM", "BAC", "GS", "MS", "WFC",
    "XOM", "CVX", "COP",
    "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO",
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD",
    "CAT", "BA", "GE", "HON", "UPS",
    "NFLX", "CRM", "ORCL", "ADBE", "INTC", "QCOM", "TXN", "AMAT", "LRCX",
    "IBM", "DIS", "UBER",
])

TTL = {  # seconds
    "info": 12 * 3600,
    "universe": 30 * 60,
    "prices": 30 * 60,
    "financials": 24 * 3600,
    "earnings": 6 * 3600,
    "news": 20 * 60,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clean(v):
    """Make a value JSON-safe: NaN/inf -> None, numpy/pandas scalars -> py."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _cached(kind: str, key: str, fn, refresh: bool):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.{kind}.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < TTL[kind]:
        return json.loads(path.read_text())
    data = fn()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str))
    tmp.replace(path)
    return data


def _check_symbol(sym: str) -> str:
    sym = sym.upper()
    if sym not in UNIVERSE:
        raise ValueError(f"{sym} is not in the research universe")
    return sym


# ---------------------------------------------------------------------------
# info (shared by universe + profile)
# ---------------------------------------------------------------------------

INFO_FIELDS = [
    "longName", "shortName", "sector", "industry", "longBusinessSummary",
    "website", "fullTimeEmployees", "city", "state", "country", "exchange",
    "currency", "currentPrice", "previousClose", "regularMarketChangePercent",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage",
    "twoHundredDayAverage", "marketCap", "enterpriseValue", "beta",
    "sharesOutstanding", "floatShares", "averageVolume",
    "trailingPE", "forwardPE", "pegRatio", "trailingPegRatio",
    "priceToSalesTrailing12Months", "priceToBook", "enterpriseToRevenue",
    "enterpriseToEbitda", "trailingEps", "forwardEps", "bookValue",
    "grossMargins", "operatingMargins", "ebitdaMargins", "profitMargins",
    "returnOnEquity", "returnOnAssets", "revenueGrowth", "earningsGrowth",
    "earningsQuarterlyGrowth", "totalRevenue", "ebitda", "netIncomeToCommon",
    "freeCashflow", "operatingCashflow", "totalCash", "totalDebt",
    "debtToEquity", "currentRatio", "quickRatio",
    "dividendRate", "dividendYield", "payoutRatio", "exDividendDate",
    "fiveYearAvgDividendYield",
    "targetLowPrice", "targetMeanPrice", "targetMedianPrice", "targetHighPrice",
    "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
    "heldPercentInsiders", "heldPercentInstitutions", "shortPercentOfFloat",
    "financialCurrency",
]


def _ttm_fcf(t: yf.Ticker) -> float | None:
    """TTM free cash flow = sum of the last 4 quarterly (OCF − capex) figures.
    Yahoo's info['freeCashflow'] is a *levered* FCF that can differ wildly
    from the statement figure shown on the Financials tab."""
    try:
        q = t.quarterly_cashflow
        if q is None or q.empty or "Free Cash Flow" not in q.index:
            return None
        s = q.loc["Free Cash Flow"].dropna().sort_index()
        return float(s.iloc[-4:].sum()) if len(s) >= 4 else None
    except Exception:
        return None


def _fx_series(fin: str | None, cur: str | None) -> pd.Series | None:
    """Daily rate converting 1 unit of statement currency into trading
    currency (e.g. NVO reports in DKK, trades in USD). None if same/unknown."""
    if not fin or not cur or fin == cur:
        return None
    h = yf.Ticker(f"{fin}{cur}=X").history(period="10y")["Close"].dropna()
    if h.empty:
        return None
    h.index = h.index.tz_localize(None)
    return h


def _fetch_info(sym: str) -> dict:
    t = yf.Ticker(sym)
    raw = t.info or {}
    out = {k: _clean(raw.get(k)) for k in INFO_FIELDS}
    # Statement figures (FCF, revenue, ...) are in financialCurrency; price,
    # market cap and targets are in the trading currency.
    out["freeCashflowTtm"] = _clean(_ttm_fcf(t))
    fx = _fx_series(out.get("financialCurrency"), out.get("currency"))
    rate = float(fx.iloc[-1]) if fx is not None else 1.0
    out["fxToTrading"] = _clean(rate)

    # Sanity-check Yahoo's EV (ASML showed $39.7T vs a $0.7T market cap):
    # rebuild EV = market cap + (debt − cash) and use it when Yahoo deviates >50%.
    mcap, debt, cash = out.get("marketCap"), out.get("totalDebt"), out.get("totalCash")
    ev_fixed = False
    if mcap and debt is not None and cash is not None:
        ev_calc = mcap + (debt - cash) * rate
        ev = out.get("enterpriseValue")
        if not ev or abs(ev / ev_calc - 1) > 0.5:
            out["enterpriseValue"] = _clean(ev_calc)
            ev_fixed = True

    if fx is not None or ev_fixed:
        # Yahoo divides trading-currency market cap / EV by statement-currency
        # revenue / EBITDA for foreign filers (NVO P/S showed 0.5x instead of
        # ~3.5x). Recompute those ratios on a single currency.
        def per(num_key: str, den_key: str):
            n, d = out.get(num_key), out.get(den_key)
            return _clean(n / (d * rate)) if n and d else None
        out["priceToSalesTrailing12Months"] = per("marketCap", "totalRevenue")
        out["enterpriseToRevenue"] = per("enterpriseValue", "totalRevenue")
        out["enterpriseToEbitda"] = per("enterpriseValue", "ebitda")
    # yfinance reports dividendYield in percent units (0.75 == 0.75%);
    # normalise to a fraction like every other ratio here.
    if out.get("dividendYield") is not None:
        out["dividendYield"] = out["dividendYield"] / 100.0
    if out.get("exDividendDate"):
        try:
            out["exDividendDate"] = datetime.fromtimestamp(
                int(out["exDividendDate"]), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            pass
    out["symbol"] = sym
    return out


def info(sym: str, refresh: bool = False) -> dict:
    return _cached("info", sym, lambda: _fetch_info(sym), refresh)


# ---------------------------------------------------------------------------
# universe screener
# ---------------------------------------------------------------------------

def _build_universe(refresh: bool) -> dict:
    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = dict(zip(UNIVERSE, ex.map(lambda s: _safe_info(s, refresh), UNIVERSE)))

    px = yf.download(UNIVERSE, period="1y", interval="1d", auto_adjust=True,
                     progress=False, threads=True)["Close"]
    rows = []
    for sym in UNIVERSE:
        i = infos[sym]
        s = px[sym].dropna() if sym in px.columns else pd.Series(dtype=float)

        def ret(n: int):
            return _clean(float(s.iloc[-1] / s.iloc[-1 - n] - 1)) if len(s) > n else None

        ytd = None
        if len(s):
            this_year = s[s.index.year == s.index[-1].year]
            prev = s[s.index.year < s.index[-1].year]
            base = prev.iloc[-1] if len(prev) else (this_year.iloc[0] if len(this_year) else None)
            if base:
                ytd = _clean(float(s.iloc[-1] / base - 1))

        rows.append({
            "symbol": sym,
            "name": i.get("shortName") or i.get("longName") or sym,
            "sector": i.get("sector"),
            "industry": i.get("industry"),
            "price": _clean(float(s.iloc[-1])) if len(s) else i.get("currentPrice"),
            "chg1d": ret(1), "chg1m": ret(21), "chgYtd": ytd, "chg1y": ret(len(s) - 1) if len(s) > 1 else None,
            "marketCap": i.get("marketCap"),
            "trailingPE": i.get("trailingPE"),
            "forwardPE": i.get("forwardPE"),
            "priceToSales": i.get("priceToSalesTrailing12Months"),
            "evToEbitda": i.get("enterpriseToEbitda"),
            "profitMargin": i.get("profitMargins"),
            "roe": i.get("returnOnEquity"),
            "revenueGrowth": i.get("revenueGrowth"),
            "dividendYield": i.get("dividendYield"),
            "recommendation": i.get("recommendationKey"),
            "spark": [_clean(round(float(v), 2)) for v in s.iloc[-63:]],
            "error": i.get("error"),
        })
    return {"asOf": datetime.now(timezone.utc).isoformat(), "rows": rows}


def _safe_info(sym: str, refresh: bool) -> dict:
    try:
        return info(sym, refresh)
    except Exception as exc:  # one bad symbol shouldn't sink the screener
        return {"symbol": sym, "error": str(exc)}


def universe(refresh: bool = False) -> dict:
    return _cached("universe", "_all", lambda: _build_universe(refresh), refresh)


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

def _fetch_prices(sym: str) -> dict:
    df = yf.Ticker(sym).history(period="10y", interval="1d", auto_adjust=True)
    df = df.dropna(subset=["Close"])
    bars = [
        {"t": ts.strftime("%Y-%m-%d"),
         "o": round(float(r.Open), 4), "h": round(float(r.High), 4),
         "l": round(float(r.Low), 4), "c": round(float(r.Close), 4),
         "v": int(r.Volume)}
        for ts, r in df.iterrows()
    ]
    spy = yf.Ticker("SPY").history(period="10y", interval="1d", auto_adjust=True)["Close"].dropna()
    bench = [{"t": ts.strftime("%Y-%m-%d"), "c": round(float(v), 4)} for ts, v in spy.items()]
    return {"symbol": sym, "bars": bars, "benchmark": {"symbol": "SPY", "bars": bench}}


def prices(sym: str, refresh: bool = False) -> dict:
    return _cached("prices", sym, lambda: _fetch_prices(sym), refresh)


# ---------------------------------------------------------------------------
# financial statements
# ---------------------------------------------------------------------------

# (display label, candidate yfinance row names in priority order)
INCOME_ROWS = [
    ("Revenue", ["Total Revenue", "Operating Revenue"]),
    ("Cost of Revenue", ["Cost Of Revenue"]),
    ("Gross Profit", ["Gross Profit"]),
    ("R&D", ["Research And Development"]),
    ("SG&A", ["Selling General And Administration"]),
    ("Operating Income", ["Operating Income"]),
    ("EBITDA", ["EBITDA", "Normalized EBITDA"]),
    ("Interest Expense", ["Interest Expense"]),
    ("Pretax Income", ["Pretax Income"]),
    ("Tax", ["Tax Provision"]),
    ("Net Income", ["Net Income", "Net Income Common Stockholders"]),
    ("Diluted EPS", ["Diluted EPS"]),
    ("Diluted Shares", ["Diluted Average Shares"]),
]
BALANCE_ROWS = [
    ("Cash & Short-Term Inv.", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]),
    ("Total Current Assets", ["Current Assets"]),
    ("Total Assets", ["Total Assets"]),
    ("Total Current Liabilities", ["Current Liabilities"]),
    ("Total Debt", ["Total Debt"]),
    ("Total Liabilities", ["Total Liabilities Net Minority Interest"]),
    ("Shareholders' Equity", ["Stockholders Equity", "Common Stock Equity"]),
    ("Net Debt", ["Net Debt"]),
    ("Working Capital", ["Working Capital"]),
    ("Shares Outstanding", ["Ordinary Shares Number", "Share Issued"]),
]
CASHFLOW_ROWS = [
    ("Operating Cash Flow", ["Operating Cash Flow"]),
    ("Capital Expenditure", ["Capital Expenditure"]),
    ("Free Cash Flow", ["Free Cash Flow"]),
    ("Stock-Based Comp", ["Stock Based Compensation"]),
    ("Dividends Paid", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    ("Buybacks", ["Repurchase Of Capital Stock", "Common Stock Payments"]),
    ("Debt Issued / (Repaid)", ["Net Issuance Payments Of Debt"]),
]


def _statement(df: pd.DataFrame, spec) -> dict:
    if df is None or df.empty:
        return {"periods": [], "rows": []}
    df = df.loc[:, sorted(df.columns)]  # oldest -> newest
    periods = [c.strftime("%Y-%m-%d") for c in df.columns]
    rows = []
    for label, candidates in spec:
        name = next((c for c in candidates if c in df.index), None)
        if name is None:
            continue
        vals = [_clean(float(v)) if pd.notna(v) else None for v in df.loc[name]]
        if all(v is None for v in vals):
            continue
        rows.append({"label": label, "values": vals})
    # Yahoo often appends a stub period with almost nothing reported; drop
    # periods where fewer than half the selected rows have a value.
    keep = [i for i in range(len(periods)) if sum(r["values"][i] is not None for r in rows) * 2 >= len(rows)]
    return {
        "periods": [periods[i] for i in keep],
        "rows": [{"label": r["label"], "values": [r["values"][i] for i in keep]} for r in rows],
    }


def _row(stmt: dict, label: str) -> list:
    for r in stmt["rows"]:
        if r["label"] == label:
            return r["values"]
    return [None] * len(stmt["periods"])


def _div(a, b):
    return _clean(a / b) if a is not None and b not in (None, 0) else None


def _fetch_financials(sym: str) -> dict:
    t = yf.Ticker(sym)
    out = {}
    for freq, (inc, bal, cf) in {
        "annual": (t.income_stmt, t.balance_sheet, t.cashflow),
        "quarterly": (t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow),
    }.items():
        income = _statement(inc, INCOME_ROWS)
        balance = _statement(bal, BALANCE_ROWS)
        cashflow = _statement(cf, CASHFLOW_ROWS)
        out[freq] = {"income": income, "balance": balance, "cashflow": cashflow}

    # Derived annual ratio history (margins, returns, leverage, valuation)
    a = out["annual"]
    inc, bal, cf = a["income"], a["balance"], a["cashflow"]
    periods = inc["periods"]
    rev, gp, op, ni = (_row(inc, k) for k in ("Revenue", "Gross Profit", "Operating Income", "Net Income"))
    eps = _row(inc, "Diluted EPS")
    shares = _row(inc, "Diluted Shares")
    bal_by_p = dict(zip(bal["periods"], zip(_row(bal, "Shareholders' Equity"), _row(bal, "Total Debt"), _row(bal, "Total Assets"))))
    fcf_by_p = dict(zip(cf["periods"], _row(cf, "Free Cash Flow")))

    close = yf.Ticker(sym).history(period="10y", interval="1d", auto_adjust=False)["Close"].dropna()
    close.index = close.index.tz_localize(None)
    meta = info(sym)
    fin_ccy, trade_ccy = meta.get("financialCurrency"), meta.get("currency")
    fx = _fx_series(fin_ccy, trade_ccy)

    def px_at(date_str: str):
        """Period-end price expressed in the *statement* currency, so that
        price / EPS etc. never mixes e.g. USD prices with DKK earnings."""
        s = close[close.index <= pd.Timestamp(date_str)]
        if not len(s):
            return None
        price = float(s.iloc[-1])
        if fx is not None:
            r = fx[fx.index <= pd.Timestamp(date_str)]
            if not len(r):
                return None
            price /= float(r.iloc[-1])
        return price

    hist = []
    for i, p in enumerate(periods):
        eq, debt, assets = bal_by_p.get(p, (None, None, None))
        fcf = fcf_by_p.get(p)
        price = px_at(p)
        mcap = price * shares[i] if price and shares[i] else None
        hist.append({
            "period": p,
            "grossMargin": _div(gp[i], rev[i]),
            "operatingMargin": _div(op[i], rev[i]),
            "netMargin": _div(ni[i], rev[i]),
            "fcfMargin": _div(fcf, rev[i]),
            "roe": _div(ni[i], eq),
            "roa": _div(ni[i], assets),
            "debtToEquity": _div(debt, eq),
            "revenueGrowth": _div(rev[i] - rev[i - 1], abs(rev[i - 1])) if i and rev[i] is not None and rev[i - 1] else None,
            "epsGrowth": _div(eps[i] - eps[i - 1], abs(eps[i - 1])) if i and eps[i] is not None and eps[i - 1] else None,
            "priceAtPeriodEnd": _clean(price),
            "pe": _div(price, eps[i]) if eps[i] and eps[i] > 0 else None,
            "ps": _div(mcap, rev[i]),
            "pfcf": _div(mcap, fcf) if fcf and fcf > 0 else None,
        })
    out["ratioHistory"] = hist
    out["symbol"] = sym
    out["currency"] = fin_ccy or trade_ccy or "USD"
    out["tradingCurrency"] = trade_ccy or "USD"
    return out


def financials(sym: str, refresh: bool = False) -> dict:
    return _cached("financials", sym, lambda: _fetch_financials(sym), refresh)


# ---------------------------------------------------------------------------
# earnings
# ---------------------------------------------------------------------------

def _frame_records(df: pd.DataFrame | None) -> list:
    if df is None or getattr(df, "empty", True):
        return []
    df = df.reset_index()
    return [{str(k): _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def _fetch_earnings(sym: str) -> dict:
    t = yf.Ticker(sym)
    hist, upcoming = [], None
    try:
        ed = t.get_earnings_dates(limit=16)
    except Exception:
        ed = None
    if ed is not None and not ed.empty:
        for ts, r in ed.sort_index().iterrows():
            rec = {
                "date": ts.strftime("%Y-%m-%d"),
                "epsEstimate": _clean(r.get("EPS Estimate")),
                "epsActual": _clean(r.get("Reported EPS")),
                "surprisePct": _clean(r.get("Surprise(%)")),
            }
            if rec["epsActual"] is None and ts.tz_convert(None) > pd.Timestamp.now():
                if upcoming is None:
                    upcoming = rec
            elif rec["epsActual"] is not None:
                hist.append(rec)

    def safe(attr):
        try:
            return _frame_records(getattr(t, attr))
        except Exception:
            return []

    return {
        "symbol": sym,
        "history": hist,
        "upcoming": upcoming,
        "epsEstimates": safe("earnings_estimate"),
        "revenueEstimates": safe("revenue_estimate"),
        "epsTrend": safe("eps_trend"),
        "recommendations": safe("recommendations"),
    }


def earnings(sym: str, refresh: bool = False) -> dict:
    return _cached("earnings", sym, lambda: _fetch_earnings(sym), refresh)


# ---------------------------------------------------------------------------
# news (Yahoo per-symbol RSS — yfinance's Ticker.news currently returns [])
# ---------------------------------------------------------------------------

def _fetch_news(sym: str) -> dict:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    body = urllib.request.urlopen(req, timeout=15).read()
    root = ET.fromstring(body)
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        try:
            pub_iso = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else None
        except (TypeError, ValueError):
            pub_iso = None
        link = it.findtext("link") or ""
        if not link.startswith(("http://", "https://")):
            continue
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": link,
            "summary": (it.findtext("description") or "").strip(),
            "published": pub_iso,
        })
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    pats = _relevance_patterns(sym)
    for it in items:
        text = f"{it['title']} {it['summary']}"
        it["relevant"] = any(p.search(text) for p in pats)
    return {"symbol": sym, "items": items[:40]}


# Yahoo's per-symbol feed mixes in sector/market stories; tag the ones that
# actually mention the company so the UI can default to those.
NAME_ALIASES = {
    "GOOG": ["Google", "Alphabet"], "META": ["Meta", "Facebook", "Instagram"],
    "BRK-B": ["Berkshire"], "HD": ["Home Depot"], "GE": ["GE Aerospace", "General Electric"],
    "MA": ["Mastercard"], "V": ["Visa"], "KO": ["Coca-Cola", "Coca Cola", "Coke"], "PG": ["Procter"],
    "JNJ": ["Johnson & Johnson", "J&J"], "LLY": ["Eli Lilly", "Lilly"], "DIS": ["Disney"],
    "TMO": ["Thermo Fisher"], "PANW": ["Palo Alto"], "LRCX": ["Lam Research"],
    "AMAT": ["Applied Materials"], "TXN": ["Texas Instruments"], "IBM": ["IBM"],
    "BAC": ["Bank of America", "BofA"], "GS": ["Goldman"], "MS": ["Morgan Stanley"],
    "WFC": ["Wells Fargo"], "JPM": ["JPMorgan", "JP Morgan"], "UPS": ["UPS"],
    "CAT": ["Caterpillar"], "BA": ["Boeing"], "HON": ["Honeywell"], "MCD": ["McDonald"],
    "COST": ["Costco"], "WMT": ["Walmart"], "PEP": ["PepsiCo", "Pepsi"],
    "UNH": ["UnitedHealth"], "ABBV": ["AbbVie"], "MRK": ["Merck"], "PFE": ["Pfizer"],
    "XOM": ["Exxon"], "CVX": ["Chevron"], "COP": ["ConocoPhillips"], "NVO": ["Novo Nordisk", "Novo"],
    "CRM": ["Salesforce"], "NOW": ["ServiceNow"], "CRWD": ["CrowdStrike"], "ANET": ["Arista"],
}


def _relevance_patterns(sym: str) -> list:
    import re
    words = list(NAME_ALIASES.get(sym, []))
    try:
        name = (info(sym).get("shortName") or "").replace(",", " ")
    except Exception:
        name = ""
    first = next((w for w in name.split() if w.lower() not in ("the", "inc.", "inc", "corp")), "")
    if len(first) >= 4 and not words:
        words.append(first)
    pats = [re.compile(rf"\b{re.escape(w)}", re.I) for w in words]
    if len(sym) >= 3:
        pats.append(re.compile(rf"\b{re.escape(sym)}\b"))  # case-sensitive ticker
    pats.append(re.compile(rf"[(:$]{re.escape(sym)}\b"))      # (V), NYSE:V, $V
    return pats


def news(sym: str, refresh: bool = False) -> dict:
    return _cached("news", sym, lambda: _fetch_news(sym), refresh)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    refresh = "--refresh" in argv
    args = [a for a in argv if a != "--refresh"]
    try:
        if not args:
            raise ValueError("usage: company_bridge.py <universe|profile|prices|financials|earnings|news> [SYMBOL]")
        cmd = args[0]
        if cmd == "universe":
            data = universe(refresh)
        elif cmd in ("profile", "prices", "financials", "earnings", "news"):
            if len(args) < 2:
                raise ValueError(f"{cmd} needs a SYMBOL")
            sym = _check_symbol(args[1])
            data = {"profile": info, "prices": prices, "financials": financials,
                    "earnings": earnings, "news": news}[cmd](sym, refresh)
        else:
            raise ValueError(f"unknown command {cmd!r}")
        sys.stdout.write(json.dumps(data, default=str))
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
