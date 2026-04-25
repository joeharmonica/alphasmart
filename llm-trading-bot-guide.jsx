import { useState, useEffect } from "react";

const phases = [
  {
    id: "overview",
    label: "Overview",
    icon: "◎",
    color: "#0AF0B0",
    content: {
      title: "LLM-Powered Trading Bot — Full Blueprint",
      sections: [
        {
          heading: "What You're Building",
          body: `An automated trading system that uses a Large Language Model (Claude, GPT, etc.) to analyze market data, generate trading signals, and execute orders — across crypto and stock markets.`,
        },
        {
          heading: "Architecture at a Glance",
          body: `┌─────────────────────────────────────────────────────┐
│  DATA LAYER        Market feeds, news, on-chain     │
│  ────────────►     sentiment, technical indicators   │
├─────────────────────────────────────────────────────┤
│  LLM BRAIN         Prompt → Analysis → Signal       │
│  ────────────►     (Claude API / local model)        │
├─────────────────────────────────────────────────────┤
│  STRATEGY ENGINE   Risk management, position sizing  │
│  ────────────►     entry/exit rules, portfolio mgmt  │
├─────────────────────────────────────────────────────┤
│  EXECUTION LAYER   Broker/Exchange API, order mgmt   │
│  ────────────►     Paper → Live trading              │
├─────────────────────────────────────────────────────┤
│  MONITORING        Logging, P&L tracking, alerts     │
│  ────────────►     dashboards, kill-switches         │
└─────────────────────────────────────────────────────┘`,
        },
        {
          heading: "Tech Stack Recommendation",
          body: `• Language: Python 3.11+
• LLM Provider: Anthropic Claude API (recommended) or OpenAI
• Data: yfinance, ccxt (crypto), Alpha Vantage, Polygon.io
• Backtesting: vectorbt, backtrader, or custom engine
• Broker/Exchange: Alpaca (stocks), Binance/Bybit (crypto)
• Database: SQLite (dev) → PostgreSQL (prod)
• Scheduling: APScheduler or cron
• Monitoring: Grafana + Prometheus or custom dashboard`,
        },
        {
          heading: "Time Investment Estimate",
          body: `Phase 1 — Environment Setup:        2–3 days
Phase 2 — Data Pipeline:             3–5 days
Phase 3 — LLM Strategy Engine:       5–7 days
Phase 4 — Backtesting Framework:     5–7 days
Phase 5 — Optimization:              3–5 days
Phase 6 — Paper Trading:             2–4 weeks (run time)
Phase 7 — Live Trading:              Ongoing

Total build time: ~3–4 weeks before paper trading begins.`,
        },
      ],
    },
  },
  {
    id: "setup",
    label: "1. Setup",
    icon: "⚙",
    color: "#00D4FF",
    content: {
      title: "Phase 1 — Environment & Infrastructure Setup",
      sections: [
        {
          heading: "Step 1.1 — Project Structure",
          body: `Create a clean, modular project layout:

trading-bot/
├── config/
│   ├── settings.yaml          # API keys, parameters
│   └── strategies.yaml        # Strategy configurations
├── src/
│   ├── data/
│   │   ├── fetcher.py         # Market data fetching
│   │   ├── preprocessor.py    # Clean & transform data
│   │   └── indicators.py      # Technical indicators
│   ├── llm/
│   │   ├── client.py          # LLM API wrapper
│   │   ├── prompts.py         # Prompt templates
│   │   └── parser.py          # Parse LLM responses
│   ├── strategy/
│   │   ├── signal_generator.py
│   │   ├── risk_manager.py
│   │   └── position_sizer.py
│   ├── execution/
│   │   ├── broker.py          # Broker/exchange interface
│   │   ├── order_manager.py
│   │   └── paper_trader.py
│   ├── backtest/
│   │   ├── engine.py          # Backtesting engine
│   │   ├── metrics.py         # Performance metrics
│   │   └── optimizer.py       # Parameter optimization
│   └── monitoring/
│       ├── logger.py
│       ├── dashboard.py
│       └── alerts.py
├── tests/
├── notebooks/                 # Jupyter for exploration
├── requirements.txt
└── main.py`,
        },
        {
          heading: "Step 1.2 — Install Dependencies",
          body: `# requirements.txt

# Core
python-dotenv==1.0.0
pyyaml==6.0.1
pandas==2.2.0
numpy==1.26.3

# LLM
anthropic==0.40.0        # Claude API
# openai==1.12.0         # Alternative

# Market Data
yfinance==0.2.36         # Free stock data
ccxt==4.2.0              # 100+ crypto exchanges
requests==2.31.0

# Technical Analysis
ta==0.11.0               # Technical indicators
pandas-ta==0.3.14b       # More indicators

# Backtesting
vectorbt==0.26.2         # Vectorized backtesting

# Broker APIs
alpaca-trade-api==3.0.2  # Stocks (US)
python-binance==1.0.19   # Crypto

# Database & Monitoring
sqlalchemy==2.0.25
loguru==0.7.2

# Install:
# python -m venv venv
# source venv/bin/activate
# pip install -r requirements.txt`,
        },
        {
          heading: "Step 1.3 — API Keys & Configuration",
          body: `# config/settings.yaml

llm:
  provider: "anthropic"          # or "openai"
  model: "claude-sonnet-4-20250514"
  max_tokens: 1024
  temperature: 0.2               # Low for consistency

market_data:
  stocks:
    provider: "yfinance"         # Free tier
    # provider: "polygon"        # Paid, better
    # api_key: \${POLYGON_API_KEY}
  crypto:
    exchange: "binance"
    api_key: \${BINANCE_API_KEY}
    api_secret: \${BINANCE_SECRET}

broker:
  stocks:
    provider: "alpaca"
    api_key: \${ALPACA_API_KEY}
    secret_key: \${ALPACA_SECRET}
    base_url: "https://paper-api.alpaca.markets"  # Paper!
  crypto:
    exchange: "binance"          # Same as data
    testnet: true                # Paper trading mode

risk:
  max_position_pct: 0.05        # 5% per position
  max_portfolio_risk: 0.15      # 15% total risk
  stop_loss_pct: 0.03           # 3% stop loss
  max_daily_loss: 0.02          # 2% daily loss limit
  max_trades_per_day: 10

# .env file (NEVER commit this)
ANTHROPIC_API_KEY=sk-ant-...
ALPACA_API_KEY=PK...
ALPACA_SECRET=...
BINANCE_API_KEY=...
BINANCE_SECRET=...`,
        },
        {
          heading: "Step 1.4 — Safety Checklist Before Proceeding",
          body: `Before writing any trading logic:

✓ API keys stored in .env, added to .gitignore
✓ Paper trading endpoints configured (NOT live)
✓ Rate limits understood for each API
✓ Risk parameters defined (see config above)
✓ Kill-switch mechanism planned
✓ Logging framework in place
✓ Version control (git) initialized

CRITICAL SAFETY RULE: Never hardcode API keys.
Always start with paper trading. Always.`,
        },
      ],
    },
  },
  {
    id: "data",
    label: "2. Data Pipeline",
    icon: "📊",
    color: "#FFB800",
    content: {
      title: "Phase 2 — Data Pipeline & Feature Engineering",
      sections: [
        {
          heading: "Step 2.1 — Market Data Fetcher",
          body: `# src/data/fetcher.py

import yfinance as yf
import ccxt
import pandas as pd
from datetime import datetime, timedelta

class StockDataFetcher:
    """Fetch stock data from Yahoo Finance."""
    
    def get_ohlcv(self, symbol: str, period: str = "1y",
                  interval: str = "1d") -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        df.columns = [c.lower() for c in df.columns]
        return df[['open','high','low','close','volume']]
    
    def get_multiple(self, symbols: list, **kwargs):
        return {s: self.get_ohlcv(s, **kwargs) for s in symbols}

class CryptoDataFetcher:
    """Fetch crypto data via CCXT (100+ exchanges)."""
    
    def __init__(self, exchange_id: str = "binance"):
        self.exchange = getattr(ccxt, exchange_id)()
    
    def get_ohlcv(self, symbol: str = "BTC/USDT",
                  timeframe: str = "1d",
                  limit: int = 365) -> pd.DataFrame:
        ohlcv = self.exchange.fetch_ohlcv(
            symbol, timeframe, limit=limit
        )
        df = pd.DataFrame(ohlcv, columns=[
            'timestamp','open','high','low','close','volume'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'],
                                          unit='ms')
        df.set_index('timestamp', inplace=True)
        return df`,
        },
        {
          heading: "Step 2.2 — Technical Indicators",
          body: `# src/data/indicators.py

import pandas as pd
import pandas_ta as ta

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add common technical indicators to OHLCV data."""
    
    # Trend
    df['sma_20']  = ta.sma(df['close'], length=20)
    df['sma_50']  = ta.sma(df['close'], length=50)
    df['ema_12']  = ta.ema(df['close'], length=12)
    df['ema_26']  = ta.ema(df['close'], length=26)
    
    # Momentum
    df['rsi_14']  = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df = pd.concat([df, macd], axis=1)
    
    # Volatility
    bb = ta.bbands(df['close'], length=20, std=2)
    df = pd.concat([df, bb], axis=1)
    df['atr_14']  = ta.atr(df['high'], df['low'],
                            df['close'], length=14)
    
    # Volume
    df['vwap'] = ta.vwap(df['high'], df['low'],
                          df['close'], df['volume'])
    
    # Derived features for LLM
    df['price_vs_sma20'] = (
        (df['close'] - df['sma_20']) / df['sma_20'] * 100
    )
    df['trend'] = (df['sma_20'] > df['sma_50']).map(
        {True: 'bullish', False: 'bearish'}
    )
    
    return df.dropna()`,
        },
        {
          heading: "Step 2.3 — News & Sentiment Data (Optional)",
          body: `# src/data/sentiment.py

import requests

class NewsFetcher:
    """Fetch financial news headlines for LLM analysis."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key  # e.g., NewsAPI, Finnhub
    
    def get_headlines(self, query: str,
                      days_back: int = 3) -> list[dict]:
        # Example using a news API
        url = f"https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "sortBy": "relevancy",
            "pageSize": 10,
            "apiKey": self.api_key,
        }
        resp = requests.get(url, params=params)
        articles = resp.json().get("articles", [])
        return [
            {
                "title": a["title"],
                "description": a["description"],
                "published": a["publishedAt"],
                "source": a["source"]["name"],
            }
            for a in articles
        ]

# For crypto: also consider on-chain data
# - Glassnode API (whale movements, exchange flows)
# - Fear & Greed Index
# - Social sentiment (LunarCrush, Santiment)`,
        },
        {
          heading: "Step 2.4 — Data Preprocessor",
          body: `# src/data/preprocessor.py

def prepare_llm_context(df, symbol, news=None):
    """Convert raw data into a text summary for the LLM."""
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    week_ago = df.iloc[-5] if len(df) >= 5 else df.iloc[0]
    
    context = f"""
=== {symbol} Market Summary ===
Current Price: {latest['close']:.2f}
24h Change:    {((latest['close']/prev['close'])-1)*100:+.2f}%
7d Change:     {((latest['close']/week_ago['close'])-1)*100:+.2f}%
Volume:        {latest['volume']:,.0f}

--- Technical Indicators ---
RSI(14):       {latest['rsi_14']:.1f} {'(overbought)' if latest['rsi_14']>70 else '(oversold)' if latest['rsi_14']<30 else '(neutral)'}
MACD Signal:   {'Bullish' if latest.get('MACDh_12_26_9',0)>0 else 'Bearish'}
Trend (SMA):   {latest['trend'].title()}
Price vs SMA20:{latest['price_vs_sma20']:+.2f}%
ATR(14):       {latest['atr_14']:.2f} (volatility)
Bollinger:     {'Near upper band' if latest['close']>latest.get('BBU_20_2.0',latest['close']) else 'Near lower band' if latest['close']<latest.get('BBL_20_2.0',latest['close']) else 'Mid range'}

--- Recent Price Action (last 5 candles) ---"""
    
    for i in range(-5, 0):
        row = df.iloc[i]
        chg = ((row['close']/df.iloc[i-1]['close'])-1)*100
        context += f"\\n  {row.name.strftime('%Y-%m-%d')}: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f} ({chg:+.2f}%)"
    
    if news:
        context += "\\n\\n--- Recent News ---"
        for n in news[:5]:
            context += f"\\n• [{n['source']}] {n['title']}"
    
    return context`,
        },
      ],
    },
  },
  {
    id: "llm",
    label: "3. LLM Engine",
    icon: "🧠",
    color: "#B44AFF",
    content: {
      title: "Phase 3 — LLM Strategy Engine",
      sections: [
        {
          heading: "Step 3.1 — LLM Client Wrapper",
          body: `# src/llm/client.py

import anthropic
import json
from loguru import logger

class LLMClient:
    def __init__(self, model="claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()  # Uses env key
        self.model = model
    
    def analyze(self, system_prompt: str,
                user_prompt: str) -> dict:
        """Send analysis request, return parsed response."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=0.2,  # Deterministic
                system=system_prompt,
                messages=[{"role": "user",
                           "content": user_prompt}],
            )
            text = response.content[0].text
            return self._parse_response(text)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {"action": "HOLD", "confidence": 0,
                    "reason": f"LLM error: {e}"}
    
    def _parse_response(self, text: str) -> dict:
        """Extract structured JSON from LLM response."""
        try:
            # Find JSON block in response
            start = text.index('{')
            end = text.rindex('}') + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.warning(f"Failed to parse: {text[:200]}")
            return {"action": "HOLD", "confidence": 0,
                    "reason": "Parse error"}`,
        },
        {
          heading: "Step 3.2 — Prompt Engineering (The Core!)",
          body: `# src/llm/prompts.py

SYSTEM_PROMPT = """You are a quantitative trading analyst. 
Your job: analyze market data and output a trading signal.

RULES:
1. You must respond ONLY with a JSON object. No other text.
2. Be conservative — only signal BUY/SELL with high confidence.
3. Always consider risk-reward ratio before signaling.
4. Factor in current trend, momentum, volatility, and volume.
5. If uncertain, output HOLD. It's better to miss a trade
   than take a bad one.

OUTPUT FORMAT (strict JSON):
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0 to 1.0,
  "entry_price": <suggested entry or null>,
  "stop_loss": <price or null>,
  "take_profit": <price or null>,
  "position_size_pct": 0.01 to 0.05,
  "timeframe": "short" | "medium" | "swing",
  "reason": "<2-3 sentence analysis>"
}"""

def build_analysis_prompt(market_context: str,
                          portfolio_state: str = "") -> str:
    prompt = f"""Analyze the following market data and 
provide a trading signal.

{market_context}

"""
    if portfolio_state:
        prompt += f"""Current Portfolio State:
{portfolio_state}
"""
    
    prompt += """Based on the technical indicators, price 
action, and any available news, what is your trading signal?
Remember: respond ONLY with a valid JSON object."""
    
    return prompt`,
        },
        {
          heading: "Step 3.3 — Signal Generator",
          body: `# src/strategy/signal_generator.py

from src.llm.client import LLMClient
from src.llm.prompts import SYSTEM_PROMPT, build_analysis_prompt
from src.data.preprocessor import prepare_llm_context
from loguru import logger

class SignalGenerator:
    def __init__(self):
        self.llm = LLMClient()
        self.signal_history = []
    
    def generate_signal(self, df, symbol,
                        news=None, portfolio=None):
        """Generate a trading signal for a symbol."""
        
        # 1. Prepare context for LLM
        market_ctx = prepare_llm_context(df, symbol, news)
        portfolio_str = str(portfolio) if portfolio else ""
        
        # 2. Build prompt
        user_prompt = build_analysis_prompt(
            market_ctx, portfolio_str
        )
        
        # 3. Get LLM analysis
        signal = self.llm.analyze(SYSTEM_PROMPT, user_prompt)
        
        # 4. Validate signal
        signal = self._validate_signal(signal, df)
        
        # 5. Log and return
        signal['symbol'] = symbol
        signal['timestamp'] = df.index[-1].isoformat()
        self.signal_history.append(signal)
        
        logger.info(
            f"{symbol}: {signal['action']} "
            f"(conf={signal['confidence']:.0%})"
        )
        return signal
    
    def _validate_signal(self, signal, df):
        """Sanity-check the LLM output."""
        # Ensure required fields
        defaults = {
            "action": "HOLD", "confidence": 0,
            "entry_price": None, "stop_loss": None,
            "take_profit": None, "position_size_pct": 0.02,
            "reason": "No reason given"
        }
        for k, v in defaults.items():
            if k not in signal:
                signal[k] = v
        
        # Clamp values
        signal['confidence'] = max(0, min(1,
            signal['confidence']))
        signal['position_size_pct'] = max(0.01, min(0.05,
            signal.get('position_size_pct', 0.02)))
        
        # Only act on high-confidence signals
        if signal['confidence'] < 0.7:
            signal['action'] = 'HOLD'
        
        # Validate stop loss makes sense
        price = df['close'].iloc[-1]
        if signal['action'] == 'BUY' and signal['stop_loss']:
            if signal['stop_loss'] >= price:
                signal['stop_loss'] = price * 0.97
        
        return signal`,
        },
        {
          heading: "Step 3.4 — Risk Manager",
          body: `# src/strategy/risk_manager.py

class RiskManager:
    def __init__(self, config):
        self.max_position_pct = config['max_position_pct']
        self.max_portfolio_risk = config['max_portfolio_risk']
        self.max_daily_loss = config['max_daily_loss']
        self.max_trades_per_day = config['max_trades_per_day']
        self.daily_pnl = 0.0
        self.trades_today = 0
    
    def approve_trade(self, signal, portfolio) -> dict:
        """Gate every trade through risk checks."""
        
        checks = {
            "daily_loss_ok": self.daily_pnl > 
                             -self.max_daily_loss,
            "trade_count_ok": self.trades_today < 
                              self.max_trades_per_day,
            "position_size_ok": signal['position_size_pct']
                                <= self.max_position_pct,
            "portfolio_risk_ok": self._check_portfolio_risk(
                                     portfolio),
            "no_duplicate": signal['symbol'] not in 
                           portfolio.get('open_positions', {}),
        }
        
        approved = all(checks.values())
        
        if not approved:
            failed = [k for k,v in checks.items() if not v]
            return {
                "approved": False,
                "reason": f"Risk check failed: {failed}"
            }
        
        self.trades_today += 1
        return {"approved": True, "checks": checks}
    
    def _check_portfolio_risk(self, portfolio):
        total_exposure = sum(
            pos.get('size_pct', 0)
            for pos in portfolio.get('open_positions',
                                     {}).values()
        )
        return total_exposure < self.max_portfolio_risk
    
    def update_daily_pnl(self, pnl: float):
        self.daily_pnl += pnl
    
    def reset_daily(self):
        self.daily_pnl = 0.0
        self.trades_today = 0`,
        },
      ],
    },
  },
  {
    id: "backtest",
    label: "4. Backtest",
    icon: "⏪",
    color: "#FF6B6B",
    content: {
      title: "Phase 4 — Backtesting Framework",
      sections: [
        {
          heading: "Step 4.1 — Backtesting Engine",
          body: `# src/backtest/engine.py

import pandas as pd
import numpy as np
from loguru import logger

class BacktestEngine:
    """Event-driven backtester for LLM strategies."""
    
    def __init__(self, initial_capital=100_000,
                 commission=0.001):
        self.initial_capital = initial_capital
        self.commission = commission  # 0.1%
    
    def run(self, df, signal_generator, symbol):
        """Walk through historical data bar-by-bar."""
        
        results = {
            'trades': [],
            'equity_curve': [],
            'signals': [],
        }
        
        capital = self.initial_capital
        position = None  # {side, entry, size, stop, target}
        
        # Walk-forward: use expanding window
        lookback = 50  # Minimum bars needed
        
        for i in range(lookback, len(df)):
            bar = df.iloc[i]
            window = df.iloc[:i+1]  # Data up to this bar
            
            # Record equity
            equity = capital
            if position:
                pnl = self._unrealized_pnl(position,
                                            bar['close'])
                equity += pnl
            results['equity_curve'].append({
                'date': bar.name, 'equity': equity
            })
            
            # Check stop loss / take profit
            if position:
                closed = self._check_exits(
                    position, bar, capital, results
                )
                if closed:
                    capital += closed['pnl']
                    position = None
                    continue
            
            # Generate signal (every N bars to save API cost)
            if i % 5 == 0 and position is None:
                signal = signal_generator.generate_signal(
                    window, symbol
                )
                results['signals'].append(signal)
                
                if signal['action'] == 'BUY':
                    size = capital * signal.get(
                        'position_size_pct', 0.02
                    )
                    position = {
                        'side': 'long',
                        'entry': bar['close'],
                        'size': size,
                        'qty': size / bar['close'],
                        'stop': signal.get('stop_loss'),
                        'target': signal.get('take_profit'),
                        'entry_date': bar.name,
                    }
                    capital -= size * (1 + self.commission)
        
        # Close any open position at end
        if position:
            final_pnl = self._unrealized_pnl(
                position, df.iloc[-1]['close']
            )
            capital += position['size'] + final_pnl
            results['trades'].append({
                'entry_date': position['entry_date'],
                'exit_date': df.index[-1],
                'entry': position['entry'],
                'exit': df.iloc[-1]['close'],
                'pnl': final_pnl,
                'return_pct': final_pnl/position['size']*100,
            })
        
        results['final_capital'] = capital
        return results
    
    def _unrealized_pnl(self, pos, current_price):
        return pos['qty'] * (current_price - pos['entry'])
    
    def _check_exits(self, pos, bar, capital, results):
        exit_price = None
        
        if pos['stop'] and bar['low'] <= pos['stop']:
            exit_price = pos['stop']
        elif pos['target'] and bar['high'] >= pos['target']:
            exit_price = pos['target']
        
        if exit_price:
            pnl = pos['qty'] * (exit_price - pos['entry'])
            pnl -= pos['size'] * self.commission  # Exit fee
            results['trades'].append({
                'entry_date': pos['entry_date'],
                'exit_date': bar.name,
                'entry': pos['entry'],
                'exit': exit_price,
                'pnl': pnl,
                'return_pct': pnl / pos['size'] * 100,
            })
            return {'pnl': pnl + pos['size']}
        return None`,
        },
        {
          heading: "Step 4.2 — Performance Metrics",
          body: `# src/backtest/metrics.py

import numpy as np
import pandas as pd

def compute_metrics(results, risk_free_rate=0.05):
    """Compute comprehensive backtest statistics."""
    
    equity = pd.DataFrame(results['equity_curve'])
    equity.set_index('date', inplace=True)
    trades = pd.DataFrame(results['trades'])
    
    returns = equity['equity'].pct_change().dropna()
    
    # Core metrics
    total_return = (
        (results['final_capital'] / 100_000) - 1
    ) * 100
    
    sharpe = (
        (returns.mean() - risk_free_rate/252) /
        returns.std() * np.sqrt(252)
    ) if returns.std() > 0 else 0
    
    # Drawdown
    cummax = equity['equity'].cummax()
    drawdown = (equity['equity'] - cummax) / cummax
    max_drawdown = drawdown.min() * 100
    
    # Trade statistics
    if len(trades) > 0:
        winners = trades[trades['pnl'] > 0]
        losers = trades[trades['pnl'] <= 0]
        win_rate = len(winners) / len(trades) * 100
        avg_win = winners['pnl'].mean() if len(winners) else 0
        avg_loss = abs(losers['pnl'].mean()) if len(losers) else 1
        profit_factor = (
            winners['pnl'].sum() / abs(losers['pnl'].sum())
        ) if len(losers) and losers['pnl'].sum() != 0 else float('inf')
    else:
        win_rate = profit_factor = 0
        avg_win = avg_loss = 0
    
    return {
        'total_return_pct': round(total_return, 2),
        'sharpe_ratio': round(sharpe, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'total_trades': len(trades),
        'win_rate_pct': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'calmar_ratio': round(
            total_return / abs(max_drawdown), 2
        ) if max_drawdown != 0 else 0,
    }

# BENCHMARK TARGETS:
# Sharpe Ratio   > 1.0  (good), > 2.0 (excellent)
# Max Drawdown   < -15% (acceptable), < -10% (good)
# Win Rate       > 50%  with good risk/reward
# Profit Factor  > 1.5  (good), > 2.0 (excellent)`,
        },
        {
          heading: "Step 4.3 — Running Your First Backtest",
          body: `# scripts/run_backtest.py

from src.data.fetcher import StockDataFetcher
from src.data.indicators import add_indicators
from src.strategy.signal_generator import SignalGenerator
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics

# 1. Fetch historical data
fetcher = StockDataFetcher()
df = fetcher.get_ohlcv("AAPL", period="2y", interval="1d")

# 2. Add indicators
df = add_indicators(df)

# 3. Initialize components
signal_gen = SignalGenerator()
engine = BacktestEngine(initial_capital=100_000)

# 4. Run backtest
print("Running backtest... (this calls the LLM)")
results = engine.run(df, signal_gen, "AAPL")

# 5. Compute metrics
metrics = compute_metrics(results)

print("\\n=== BACKTEST RESULTS ===")
for k, v in metrics.items():
    print(f"  {k}: {v}")

print(f"\\nTotal trades: {metrics['total_trades']}")
print(f"Final capital: \${results['final_capital']:,.2f}")

# IMPORTANT: LLM API costs!
# Each signal = 1 API call. 2 years of daily data at
# every 5 bars = ~100 calls. At ~$0.003/call for Sonnet
# that's ~$0.30 per backtest run. Budget accordingly.

# TIP: For faster iteration, cache LLM responses
# during backtesting to avoid re-calling the API.`,
        },
        {
          heading: "Step 4.4 — LLM Response Caching (Save $$)",
          body: `# src/llm/cache.py

import hashlib, json, sqlite3
from pathlib import Path

class LLMCache:
    """Cache LLM responses to avoid repeated API calls."""
    
    def __init__(self, db_path="cache/llm_cache.db"):
        Path(db_path).parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    def _hash(self, system: str, user: str) -> str:
        content = f"{system}|||{user}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get(self, system: str, user: str):
        key = self._hash(system, user)
        row = self.conn.execute(
            "SELECT response FROM cache WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None
    
    def set(self, system: str, user: str, response: dict):
        key = self._hash(system, user)
        self.conn.execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,datetime('now'))",
            (key, json.dumps(response))
        )
        self.conn.commit()

# Usage in LLMClient:
# cache = LLMCache()
# cached = cache.get(system_prompt, user_prompt)
# if cached:
#     return cached
# response = self.client.messages.create(...)
# cache.set(system_prompt, user_prompt, parsed)
# return parsed`,
        },
      ],
    },
  },
  {
    id: "optimize",
    label: "5. Optimize",
    icon: "🔧",
    color: "#FF9E44",
    content: {
      title: "Phase 5 — Strategy Optimization",
      sections: [
        {
          heading: "Step 5.1 — What to Optimize",
          body: `Key optimization dimensions for an LLM trading bot:

1. PROMPT OPTIMIZATION (most impactful!)
   • System prompt tone & instructions
   • How market data is formatted/summarized
   • Which indicators to include
   • How many candles of history to show
   • Whether to include news/sentiment

2. SIGNAL PARAMETERS
   • Confidence threshold (0.5 vs 0.7 vs 0.8)
   • Signal frequency (every bar vs every 5 bars)
   • Position sizing rules
   • Entry/exit logic

3. RISK PARAMETERS
   • Stop loss percentage (1% vs 3% vs 5%)
   • Take profit targets
   • Max position size
   • Max concurrent positions

4. DATA PARAMETERS
   • Timeframe (1h, 4h, 1d)
   • Which indicators to compute
   • Lookback period for context
   • News inclusion yes/no

ANTI-PATTERN WARNING:
Do NOT over-optimize. If your strategy only works on
one specific parameter set, it's curve-fit and will
fail in live trading. Aim for robustness across a
RANGE of reasonable parameters.`,
        },
        {
          heading: "Step 5.2 — Prompt Variation Testing",
          body: `# src/backtest/optimizer.py

import itertools
from copy import deepcopy

class PromptOptimizer:
    """Test different prompt strategies."""
    
    # Define prompt variations to test
    PROMPT_VARIANTS = {
        'conservative': """You are an extremely conservative 
            trader. Only signal when multiple indicators 
            strongly agree. Prefer HOLD over marginal trades.
            Risk management is your top priority.""",
        
        'momentum': """You are a momentum trader. Look for 
            strong trends confirmed by volume and RSI. Enter 
            on pullbacks within trends. Cut losers fast.""",
        
        'mean_reversion': """You are a mean-reversion trader. 
            Look for overextended moves (RSI extremes, 
            Bollinger band touches). Fade extreme moves 
            with tight stops.""",
        
        'multi_factor': """You are a multi-factor analyst. 
            Weigh trend (40%), momentum (30%), 
            volatility (20%), volume (10%). Only trade when 
            3+ factors align in the same direction.""",
    }
    
    def run_prompt_sweep(self, df, symbol, engine):
        """Test all prompt variants and compare."""
        results = {}
        
        for name, system_prompt in self.PROMPT_VARIANTS.items():
            print(f"\\nTesting prompt: {name}")
            
            signal_gen = SignalGenerator()
            # Override the system prompt
            signal_gen.llm.system_override = system_prompt
            
            result = engine.run(df, signal_gen, symbol)
            metrics = compute_metrics(result)
            results[name] = metrics
            
            print(f"  Return: {metrics['total_return_pct']}%")
            print(f"  Sharpe: {metrics['sharpe_ratio']}")
            print(f"  MaxDD:  {metrics['max_drawdown_pct']}%")
        
        return results`,
        },
        {
          heading: "Step 5.3 — Parameter Grid Search",
          body: `# src/backtest/optimizer.py (continued)

class ParameterOptimizer:
    """Grid search over risk/signal parameters."""
    
    PARAM_GRID = {
        'confidence_threshold': [0.5, 0.6, 0.7, 0.8],
        'stop_loss_pct':        [0.02, 0.03, 0.05],
        'take_profit_pct':      [0.04, 0.06, 0.10],
        'position_size_pct':    [0.02, 0.03, 0.05],
        'signal_frequency':     [1, 3, 5],  # every N bars
    }
    
    def grid_search(self, df, symbol, engine, signal_gen):
        """Test parameter combinations."""
        
        keys = list(self.PARAM_GRID.keys())
        values = list(self.PARAM_GRID.values())
        all_results = []
        
        for combo in itertools.product(*values):
            params = dict(zip(keys, combo))
            
            # Apply params to engine/signal_gen
            engine_copy = deepcopy(engine)
            # ... set params on engine_copy ...
            
            result = engine_copy.run(df, signal_gen, symbol)
            metrics = compute_metrics(result)
            metrics['params'] = params
            all_results.append(metrics)
        
        # Sort by Sharpe ratio (risk-adjusted return)
        all_results.sort(
            key=lambda x: x['sharpe_ratio'], reverse=True
        )
        
        return all_results

# WALK-FORWARD OPTIMIZATION (prevents overfitting!)
# Instead of optimizing on all data at once:
# 1. Split data: Train(60%) | Validate(20%) | Test(20%)
# 2. Optimize on Train
# 3. Verify on Validate
# 4. Final test on Test (only once!)
# 
# Even better: rolling walk-forward
# [Train1][Val1] → optimize
#    [Train2][Val2] → optimize
#       [Train3][Val3] → optimize
# Average performance across all windows`,
        },
        {
          heading: "Step 5.4 — Avoiding Overfitting Checklist",
          body: `CRITICAL: The #1 killer of trading bots is overfitting.
Signs your strategy is overfit:

✗ Works great on backtest, fails on new data
✗ Only profitable with very specific parameters
✗ Performance degrades with slight param changes
✗ Sharpe ratio > 4.0 in backtest (suspicious!)
✗ Very few trades (could be luck)

PREVENTION TECHNIQUES:

1. OUT-OF-SAMPLE TESTING
   Never touch test data during optimization.
   
2. WALK-FORWARD ANALYSIS
   Optimize on rolling windows, not all data.

3. CROSS-ASSET VALIDATION
   Does it work on AAPL, MSFT, AND GOOGL?
   Does it work on BTC, ETH, AND SOL?
   
4. CROSS-TIMEFRAME VALIDATION
   Does it work on daily AND 4-hour data?

5. PARAMETER SENSITIVITY
   Good strategy works for stop_loss = 2-5%,
   not just exactly 3.17%.
   
6. MONTE CARLO SIMULATION
   Shuffle trade order 1000x. Is it still
   profitable in 95% of shuffles?

7. MINIMUM TRADE COUNT
   Need 30+ trades minimum for statistical
   significance. Prefer 100+.

If strategy passes all 7, proceed to paper trading.`,
        },
      ],
    },
  },
  {
    id: "paper",
    label: "6. Paper Trade",
    icon: "📝",
    color: "#4AEFB0",
    content: {
      title: "Phase 6 — Paper Trading (Forward Testing)",
      sections: [
        {
          heading: "Step 6.1 — Paper Trading Setup",
          body: `# src/execution/paper_trader.py

import pandas as pd
from datetime import datetime
from loguru import logger

class PaperTrader:
    """Simulate live trading without real money."""
    
    def __init__(self, initial_capital=100_000):
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.positions = {}      # symbol -> position
        self.trade_log = []
        self.equity_history = []
    
    def execute_signal(self, signal, current_price):
        symbol = signal['symbol']
        
        if signal['action'] == 'BUY' and symbol not in self.positions:
            size = self.capital * signal['position_size_pct']
            qty = size / current_price
            
            self.positions[symbol] = {
                'qty': qty,
                'entry': current_price,
                'stop': signal.get('stop_loss'),
                'target': signal.get('take_profit'),
                'size': size,
                'entry_time': datetime.now(),
            }
            self.capital -= size
            
            logger.info(
                f"[PAPER] BUY {symbol} "
                f"qty={qty:.4f} @ {current_price:.2f}"
            )
        
        elif signal['action'] == 'SELL' and symbol in self.positions:
            pos = self.positions.pop(symbol)
            pnl = pos['qty'] * (current_price - pos['entry'])
            self.capital += pos['size'] + pnl
            
            self.trade_log.append({
                'symbol': symbol,
                'entry': pos['entry'],
                'exit': current_price,
                'pnl': pnl,
                'return_pct': pnl / pos['size'] * 100,
                'hold_time': datetime.now() - pos['entry_time'],
            })
            
            logger.info(
                f"[PAPER] SELL {symbol} "
                f"pnl=\${pnl:+.2f} ({pnl/pos['size']*100:+.1f}%)"
            )
    
    def check_stops(self, symbol, current_price):
        """Check stop loss and take profit."""
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        
        if pos['stop'] and current_price <= pos['stop']:
            logger.warning(f"[PAPER] STOP HIT for {symbol}")
            self.execute_signal(
                {'action':'SELL','symbol':symbol}, pos['stop']
            )
        elif pos['target'] and current_price >= pos['target']:
            logger.info(f"[PAPER] TARGET HIT for {symbol}")
            self.execute_signal(
                {'action':'SELL','symbol':symbol}, pos['target']
            )
    
    def get_equity(self, prices: dict) -> float:
        equity = self.capital
        for sym, pos in self.positions.items():
            if sym in prices:
                equity += pos['qty'] * prices[sym]
        return equity`,
        },
        {
          heading: "Step 6.2 — Live Paper Trading Loop",
          body: `# main.py — Paper Trading Mode

import time
import schedule
from src.data.fetcher import StockDataFetcher, CryptoDataFetcher
from src.data.indicators import add_indicators
from src.strategy.signal_generator import SignalGenerator
from src.strategy.risk_manager import RiskManager
from src.execution.paper_trader import PaperTrader
from loguru import logger

# Initialize
fetcher = StockDataFetcher()
signal_gen = SignalGenerator()
risk_mgr = RiskManager(config={'max_position_pct': 0.05,
    'max_portfolio_risk': 0.15, 'max_daily_loss': 0.02,
    'max_trades_per_day': 10})
paper = PaperTrader(initial_capital=100_000)

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]

def trading_cycle():
    """Run one trading cycle."""
    logger.info("=== Starting trading cycle ===")
    
    for symbol in WATCHLIST:
        try:
            # 1. Fetch latest data
            df = fetcher.get_ohlcv(symbol, period="3mo",
                                    interval="1d")
            df = add_indicators(df)
            
            # 2. Check existing stops
            price = df['close'].iloc[-1]
            paper.check_stops(symbol, price)
            
            # 3. Generate signal
            signal = signal_gen.generate_signal(df, symbol)
            
            # 4. Risk check
            portfolio = {
                'open_positions': paper.positions,
                'capital': paper.capital,
            }
            risk_check = risk_mgr.approve_trade(
                signal, portfolio
            )
            
            # 5. Execute if approved
            if signal['action'] != 'HOLD' and risk_check['approved']:
                paper.execute_signal(signal, price)
            elif not risk_check['approved']:
                logger.info(f"{symbol}: Blocked - {risk_check['reason']}")
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
    
    # Log daily summary
    prices = {s: fetcher.get_ohlcv(s, period="1d")['close'].iloc[-1]
              for s in WATCHLIST}
    equity = paper.get_equity(prices)
    logger.info(f"Portfolio equity: \${equity:,.2f}")

# Schedule: run once per day at market open
# For crypto: run every 4 hours (24/7 market)
schedule.every().day.at("09:35").do(trading_cycle)
# OR for crypto:
# schedule.every(4).hours.do(trading_cycle)

logger.info("Paper trading bot started!")
while True:
    schedule.run_pending()
    time.sleep(60)`,
        },
        {
          heading: "Step 6.3 — Paper Trading Validation Criteria",
          body: `Run paper trading for MINIMUM 2-4 weeks before 
considering live money. Track these metrics daily:

MUST-PASS CRITERIA (all must be met):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Positive total P&L after 2+ weeks
✓ Sharpe ratio > 0.5 (annualized)
✓ Max drawdown < 15%
✓ Win rate > 40% (with good risk/reward)
✓ No single trade lost > 3% of portfolio
✓ Strategy behaves as designed (no weird signals)
✓ System runs reliably (no crashes/hangs)
✓ API rate limits not exceeded
✓ LLM responses consistently parseable (>95%)
✓ Risk manager properly blocking bad trades

ADDITIONAL FORWARD-TEST CHECKS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Compare paper results to backtest results
  - If paper >> backtest → suspicious (lucky period)
  - If paper << backtest → strategy may be overfit
  - Ideally within ±30% of backtest metrics

• Monitor for regime changes
  - Does it work in trending AND ranging markets?
  - Test through at least one volatility spike

• Track LLM consistency
  - Log every prompt + response
  - Watch for contradictory signals
  - Monitor average confidence levels

Only proceed to live when ALL criteria are met
for at least 2 consecutive weeks.`,
        },
      ],
    },
  },
  {
    id: "live",
    label: "7. Go Live",
    icon: "🚀",
    color: "#FF4A8D",
    content: {
      title: "Phase 7 — Live Trading with Real Money",
      sections: [
        {
          heading: "Step 7.1 — Broker Integration",
          body: `# src/execution/broker.py

# STOCKS — Alpaca API (commission-free, great for bots)
from alpaca_trade_api import REST as AlpacaREST

class AlpacaBroker:
    def __init__(self, api_key, secret_key, paper=True):
        base_url = (
            "https://paper-api.alpaca.markets" if paper
            else "https://api.alpaca.markets"
        )
        self.api = AlpacaREST(api_key, secret_key, base_url)
    
    def place_order(self, symbol, qty, side, 
                    stop_loss=None, take_profit=None):
        """Place a bracket order with stops."""
        order_params = {
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': 'market',
            'time_in_force': 'day',
        }
        if stop_loss and take_profit:
            order_params.update({
                'order_class': 'bracket',
                'stop_loss': {'stop_price': str(stop_loss)},
                'take_profit': {'limit_price': str(take_profit)},
            })
        return self.api.submit_order(**order_params)
    
    def get_positions(self):
        return self.api.list_positions()
    
    def get_account(self):
        return self.api.get_account()

# CRYPTO — Binance (or Bybit, etc.)
from binance.client import Client as BinanceClient

class CryptoBroker:
    def __init__(self, api_key, api_secret, testnet=True):
        self.client = BinanceClient(api_key, api_secret,
                                     testnet=testnet)
    
    def place_order(self, symbol, qty, side):
        if side == 'buy':
            return self.client.order_market_buy(
                symbol=symbol, quantity=qty
            )
        else:
            return self.client.order_market_sell(
                symbol=symbol, quantity=qty
            )`,
        },
        {
          heading: "Step 7.2 — Gradual Capital Deployment",
          body: `CRITICAL: Never go from $0 to full allocation!

SCALING PLAN (4-8 weeks):
━━━━━━━━━━━━━━━━━━━━━━━━━━

Week 1-2: MICRO ALLOCATION
  • Deploy 5-10% of intended capital
  • Max position size: 1% of portfolio
  • Max 2 concurrent positions
  • Goal: Verify execution works correctly

Week 3-4: SMALL ALLOCATION  
  • Scale to 25% of intended capital
  • Max position size: 2% of portfolio
  • Max 3 concurrent positions
  • Goal: Confirm P&L tracks paper results

Week 5-6: MEDIUM ALLOCATION
  • Scale to 50% of intended capital
  • Max position size: 3% of portfolio
  • Max 5 concurrent positions
  • Goal: Test under normal conditions

Week 7-8: FULL ALLOCATION
  • Deploy 100% of intended capital
  • Full risk parameters from optimization
  • Goal: Steady-state operation

AT ANY STAGE: If drawdown > 10%, STOP.
Go back to paper trading and investigate.

RECOMMENDED STARTING CAPITAL:
• Stocks: $5,000 minimum (for diversification)
• Crypto: $1,000 minimum (lower barriers)
• Never risk money you can't afford to lose.`,
        },
        {
          heading: "Step 7.3 — Kill Switch & Monitoring",
          body: `# src/monitoring/kill_switch.py

class KillSwitch:
    """Emergency stop for the trading bot."""
    
    def __init__(self, max_daily_loss_pct=0.03,
                 max_weekly_loss_pct=0.07,
                 max_total_drawdown_pct=0.15):
        self.max_daily = max_daily_loss_pct
        self.max_weekly = max_weekly_loss_pct
        self.max_drawdown = max_total_drawdown_pct
        self.is_killed = False
    
    def check(self, portfolio_state) -> bool:
        """Returns True if bot should STOP."""
        
        daily = portfolio_state.get('daily_pnl_pct', 0)
        weekly = portfolio_state.get('weekly_pnl_pct', 0)
        drawdown = portfolio_state.get('drawdown_pct', 0)
        
        if daily < -self.max_daily:
            self._kill("Daily loss limit hit: "
                      f"{daily:.1%}")
            return True
        
        if weekly < -self.max_weekly:
            self._kill("Weekly loss limit hit: "
                      f"{weekly:.1%}")
            return True
        
        if drawdown < -self.max_drawdown:
            self._kill("Max drawdown hit: "
                      f"{drawdown:.1%}")
            return True
        
        return False
    
    def _kill(self, reason):
        self.is_killed = True
        logger.critical(f"KILL SWITCH: {reason}")
        # Send alert (email, Telegram, SMS)
        self._send_alert(reason)
        # Close all positions
        self._close_all_positions()
    
    def _send_alert(self, msg):
        # Implement: Telegram bot, email, SMS
        pass
    
    def _close_all_positions(self):
        # Implement: market sell everything
        pass`,
        },
        {
          heading: "Step 7.4 — Ongoing Operations Checklist",
          body: `DAILY (automated):
  ☐ Trading cycle runs on schedule
  ☐ P&L logged to database
  ☐ Kill-switch checks pass
  ☐ LLM API responding normally
  ☐ Broker connection healthy

WEEKLY (manual review):
  ☐ Review all trades and LLM reasoning
  ☐ Compare live vs backtest performance
  ☐ Check for signal degradation
  ☐ Review risk metrics (Sharpe, drawdown)
  ☐ Verify API costs are within budget
  ☐ Update watchlist if needed

MONTHLY:
  ☐ Full strategy performance review
  ☐ Re-run backtest with latest data
  ☐ Consider prompt refinements
  ☐ Review market regime (trending/ranging)
  ☐ Assess if strategy edge still exists
  ☐ Update dependencies and security patches

QUARTERLY:
  ☐ Major strategy review / pivot decision
  ☐ Re-optimize parameters with new data
  ☐ Review cost analysis (LLM API vs returns)
  ☐ Consider adding new assets/strategies

REMEMBER: Markets evolve. A strategy that works today
may stop working in 6 months. Continuous monitoring
and adaptation is non-negotiable.`,
        },
      ],
    },
  },
  {
    id: "tips",
    label: "Pro Tips",
    icon: "💡",
    color: "#FFD700",
    content: {
      title: "Pro Tips & Common Pitfalls",
      sections: [
        {
          heading: "LLM-Specific Best Practices",
          body: `1. PROMPT IS EVERYTHING
   Your prompt is your strategy. Treat prompt engineering
   with the same rigor as algorithm development. Version
   control every prompt change.

2. USE STRUCTURED OUTPUT
   Always force JSON output. Use low temperature (0.1-0.3).
   Validate every response before acting on it.

3. ENSEMBLE APPROACH
   Run 3 prompts (conservative, moderate, aggressive).
   Only trade when 2/3 agree. This reduces noise.

4. CONTEXT WINDOW BUDGET
   Don't dump everything into the prompt. Curate the most
   relevant information. More data ≠ better decisions.

5. CACHE AGGRESSIVELY
   During backtesting, cache every LLM response. Saves
   80-90% on API costs during optimization.

6. LATENCY MATTERS
   LLM calls take 1-3 seconds. Fine for daily/4h trading.
   NOT suitable for high-frequency / scalping.

7. MODEL UPDATES BREAK THINGS
   When your LLM provider updates the model, your strategy
   behavior may change. Always re-validate after updates.`,
        },
        {
          heading: "Common Pitfalls to Avoid",
          body: `❌ PITFALL 1: "It works on backtest, ship it!"
   → Always paper trade for 2+ weeks first.

❌ PITFALL 2: Overfitting to recent market conditions
   → Test across different market regimes.

❌ PITFALL 3: Ignoring API costs
   → At $0.003/call × 100 calls/day × 30 days = $9/month
   → For Opus: ~$0.075/call × 100 × 30 = $225/month
   → Make sure returns justify API costs!

❌ PITFALL 4: No kill switch
   → ALWAYS have automated loss limits.

❌ PITFALL 5: Trading too many assets
   → Start with 3-5 assets you understand well.

❌ PITFALL 6: Overriding the bot manually
   → If you keep overriding, the system is broken.
   → Fix the strategy, don't patch with manual trades.

❌ PITFALL 7: Not accounting for slippage
   → Backtest assumes perfect fills. Reality has slippage.
   → Add 0.1-0.5% slippage to your backtest engine.

❌ PITFALL 8: Survivorship bias in stock selection
   → "I'll backtest on today's top stocks" — but they
   → weren't top stocks 2 years ago. Use point-in-time data.`,
        },
        {
          heading: "Cost-Performance Trade-offs",
          body: `MODEL SELECTION FOR TRADING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Claude Haiku (cheapest)
  Cost: ~$0.001/call
  Best for: High-frequency signals, simple analysis
  Limitation: Less nuanced reasoning

Claude Sonnet (recommended sweet spot)
  Cost: ~$0.003/call  
  Best for: Daily/4h trading, balanced analysis
  Limitation: None significant for most strategies

Claude Opus (most powerful)
  Cost: ~$0.075/call
  Best for: Complex multi-factor analysis, weekly signals
  Limitation: Cost adds up fast at high frequency

COST OPTIMIZATION STRATEGIES:
• Use Haiku for initial screening, Sonnet for decisions
• Cache responses during backtesting
• Batch multiple assets in one prompt
• Only call LLM when indicators suggest opportunity
  (pre-filter with simple rules to avoid unnecessary calls)
• Run less frequently (daily vs hourly)`,
        },
        {
          heading: "Regulatory & Tax Reminder",
          body: `IMPORTANT DISCLAIMERS:
━━━━━━━━━━━━━━━━━━━━━━

• This guide is for EDUCATIONAL PURPOSES ONLY
• Not financial advice. Past performance ≠ future results.
• Algorithmic trading involves substantial risk of loss.

REGULATORY CONSIDERATIONS:
• Stocks: Check PDT rules (USA: $25K min for day trading)
• Crypto: Varies wildly by jurisdiction
• Some jurisdictions require registration for algo trading
• Consult a financial advisor and/or lawyer

TAX OBLIGATIONS:
• Every trade is a taxable event in most jurisdictions
• Log all trades with timestamps, amounts, fees
• Short-term vs long-term capital gains
• Wash sale rules (stocks, USA)
• Consider using a tax-friendly structure if trading
  frequently

YOUR BUILT-IN TRADE LOG WILL SAVE YOU AT TAX TIME.
Keep detailed records from day one.`,
        },
      ],
    },
  },
];

export default function TradingBotGuide() {
  const [activePhase, setActivePhase] = useState("overview");
  const [expandedSection, setExpandedSection] = useState(null);
  const [progress, setProgress] = useState({});

  const active = phases.find((p) => p.id === activePhase);

  const toggleSection = (idx) => {
    setExpandedSection(expandedSection === idx ? null : idx);
  };

  const toggleProgress = (phaseId) => {
    setProgress((prev) => ({ ...prev, [phaseId]: !prev[phaseId] }));
  };

  const completedCount = Object.values(progress).filter(Boolean).length;

  return (
    <div
      style={{
        fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
        background: "#0A0E17",
        color: "#C8D6E5",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div
        style={{
          background: "linear-gradient(135deg, #0A0E17 0%, #141B2D 100%)",
          borderBottom: "1px solid #1E2A3A",
          padding: "20px 24px 16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 28 }}>⚡</span>
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: 20,
                fontWeight: 700,
                color: "#F0F4F8",
                letterSpacing: "-0.02em",
              }}
            >
              LLM Trading Bot Blueprint
            </h1>
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "#5A6B7F", letterSpacing: "0.05em", textTransform: "uppercase" }}>
              From zero to live trading — complete guide
            </p>
          </div>
        </div>
        {/* Progress bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
          <div style={{ flex: 1, height: 3, background: "#1E2A3A", borderRadius: 2 }}>
            <div
              style={{
                width: `${(completedCount / (phases.length - 1)) * 100}%`,
                height: "100%",
                background: "linear-gradient(90deg, #0AF0B0, #00D4FF)",
                borderRadius: 2,
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <span style={{ fontSize: 10, color: "#5A6B7F" }}>
            {completedCount}/{phases.length - 1}
          </span>
        </div>
      </div>

      {/* Navigation tabs */}
      <div
        style={{
          display: "flex",
          overflowX: "auto",
          gap: 2,
          padding: "8px 12px",
          background: "#0D1220",
          borderBottom: "1px solid #1E2A3A",
        }}
      >
        {phases.map((phase) => {
          const isActive = activePhase === phase.id;
          return (
            <button
              key={phase.id}
              onClick={() => {
                setActivePhase(phase.id);
                setExpandedSection(null);
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 10px",
                border: "none",
                borderRadius: 6,
                background: isActive ? `${phase.color}18` : "transparent",
                color: isActive ? phase.color : "#5A6B7F",
                fontSize: 11,
                fontWeight: isActive ? 600 : 400,
                cursor: "pointer",
                whiteSpace: "nowrap",
                fontFamily: "inherit",
                transition: "all 0.2s",
                borderBottom: isActive ? `2px solid ${phase.color}` : "2px solid transparent",
              }}
            >
              <span style={{ fontSize: 13 }}>{phase.icon}</span>
              {phase.label}
            </button>
          );
        })}
      </div>

      {/* Content area */}
      <div style={{ flex: 1, overflow: "auto", padding: "20px 16px" }}>
        {active && (
          <div style={{ maxWidth: 840, margin: "0 auto" }}>
            {/* Phase title */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
              <h2
                style={{
                  margin: 0,
                  fontSize: 18,
                  fontWeight: 700,
                  color: active.color,
                  letterSpacing: "-0.01em",
                }}
              >
                {active.content.title}
              </h2>
              {active.id !== "overview" && active.id !== "tips" && (
                <button
                  onClick={() => toggleProgress(active.id)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 4,
                    border: `1px solid ${progress[active.id] ? "#0AF0B0" : "#2A3548"}`,
                    background: progress[active.id] ? "#0AF0B018" : "transparent",
                    color: progress[active.id] ? "#0AF0B0" : "#5A6B7F",
                    fontSize: 10,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}
                >
                  {progress[active.id] ? "✓ Completed" : "Mark Complete"}
                </button>
              )}
            </div>

            {/* Sections */}
            {active.content.sections.map((section, idx) => {
              const isExpanded = expandedSection === idx;
              return (
                <div
                  key={idx}
                  style={{
                    marginBottom: 8,
                    border: `1px solid ${isExpanded ? `${active.color}40` : "#1E2A3A"}`,
                    borderRadius: 8,
                    overflow: "hidden",
                    transition: "border-color 0.2s",
                  }}
                >
                  <button
                    onClick={() => toggleSection(idx)}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "12px 16px",
                      border: "none",
                      background: isExpanded ? `${active.color}08` : "#111827",
                      color: isExpanded ? "#F0F4F8" : "#8899AA",
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: "pointer",
                      fontFamily: "inherit",
                      textAlign: "left",
                    }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: 4,
                          background: `${active.color}20`,
                          color: active.color,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 10,
                          fontWeight: 700,
                          flexShrink: 0,
                        }}
                      >
                        {idx + 1}
                      </span>
                      {section.heading}
                    </span>
                    <span
                      style={{
                        transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                        transition: "transform 0.2s",
                        fontSize: 10,
                        color: "#5A6B7F",
                      }}
                    >
                      ▼
                    </span>
                  </button>
                  {isExpanded && (
                    <div
                      style={{
                        padding: "16px",
                        background: "#0D1220",
                        borderTop: `1px solid ${active.color}20`,
                      }}
                    >
                      <pre
                        style={{
                          margin: 0,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          fontSize: 12,
                          lineHeight: 1.7,
                          color: "#B0BEC5",
                          fontFamily: "inherit",
                        }}
                      >
                        {section.body}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}

            {/* Quick expand all */}
            <div style={{ textAlign: "center", marginTop: 16 }}>
              <button
                onClick={() => {
                  if (expandedSection === "all") {
                    setExpandedSection(null);
                  } else {
                    setExpandedSection("all");
                    // Expand all by setting to a special value
                  }
                }}
                style={{
                  padding: "6px 16px",
                  borderRadius: 4,
                  border: "1px solid #1E2A3A",
                  background: "transparent",
                  color: "#5A6B7F",
                  fontSize: 10,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
                onMouseOver={(e) => {
                  e.target.style.borderColor = active.color;
                  e.target.style.color = active.color;
                }}
                onMouseOut={(e) => {
                  e.target.style.borderColor = "#1E2A3A";
                  e.target.style.color = "#5A6B7F";
                }}
              >
                Click each section above to expand
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: "10px 16px",
          borderTop: "1px solid #1E2A3A",
          background: "#0D1220",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "#3D4F63",
        }}
      >
        <span>Educational purposes only — not financial advice</span>
        <span>Always start with paper trading</span>
      </div>
    </div>
  );
}
