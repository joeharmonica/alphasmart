"""
Alpaca paper-trading adapter for AlphaSMART.

Wraps `alpaca-trade-api==3.3.2` (already a project dep) with project-shape
dataclasses and structured shadow-logging. Designed for the equity leg of
the regime-filtered ensemble (xsec 6mo momentum, 15-symbol mega-cap
universe, B binary SPY filter — see tasks/paper_trade_design.md).

Two modes:
  - real:  hits paper-api.alpaca.markets via the SDK
  - mock:  returns canned responses, for local test runs without keys

The mock mode shape mirrors a populated paper account so unit tests +
end-to-end smoke tests can exercise the strategy_runner without API
access.

Auth: read ALPACA_API_KEY + ALPACA_API_SECRET from environment. We only
ever talk to the paper endpoint — there is no live-trading code path
here on purpose (out of scope for execution validation).
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    tradeapi = None  # mock-only mode is still usable

from src.execution.shadow_log import ShadowLog


PAPER_BASE_URL = "https://paper-api.alpaca.markets"


@dataclass
class AlpacaConfig:
    api_key: str
    api_secret: str
    base_url: str = PAPER_BASE_URL

    @classmethod
    def from_env(cls) -> "AlpacaConfig":
        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_API_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set "
                "to use AlpacaPaperBroker in real mode. For local tests "
                "construct with mock=True."
            )
        return cls(api_key=key, api_secret=secret)


@dataclass
class AlpacaAccount:
    account_number: str
    status: str
    buying_power: float
    cash: float
    equity: float
    portfolio_value: float
    pattern_day_trader: bool
    trading_blocked: bool


@dataclass
class AlpacaPosition:
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float
    current_price: float
    unrealized_pl: float
    side: Literal["long", "short"]


@dataclass
class AlpacaOrderRequest:
    symbol: str
    qty: float
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    time_in_force: Literal["day", "gtc"] = "day"
    limit_price: Optional[float] = None
    client_order_id: Optional[str] = None  # for idempotency


@dataclass
class AlpacaOrderResult:
    id: str
    client_order_id: str
    symbol: str
    qty: float
    side: str
    submitted_at: datetime
    status: str
    filled_qty: float = 0.0
    filled_avg_price: Optional[float] = None
    type: str = "market"
    time_in_force: str = "day"


@dataclass
class AlpacaClock:
    timestamp: datetime
    is_open: bool
    next_open: Optional[datetime] = None
    next_close: Optional[datetime] = None


class AlpacaPaperBroker:
    """
    Paper-trading adapter. Constructor never raises in mock mode; in real
    mode it raises immediately if the SDK can't authenticate, so failures
    are caught at startup not mid-rebalance.
    """

    def __init__(
        self,
        config: Optional[AlpacaConfig] = None,
        mock: bool = False,
        log: Optional[ShadowLog] = None,
    ) -> None:
        self.mock = mock
        self.log = log or ShadowLog(channel="alpaca_paper")

        if mock:
            self.config = config or AlpacaConfig(api_key="MOCK", api_secret="MOCK")
            self.api = None
            # Mutable mock state — modified by submit_order
            self._mock_account = AlpacaAccount(
                account_number="MOCK000001",
                status="ACTIVE",
                buying_power=100_000.0,
                cash=100_000.0,
                equity=100_000.0,
                portfolio_value=100_000.0,
                pattern_day_trader=False,
                trading_blocked=False,
            )
            self._mock_positions: dict[str, AlpacaPosition] = {}
            self._mock_orders: list[AlpacaOrderResult] = []
        else:
            if tradeapi is None:
                raise RuntimeError(
                    "alpaca-trade-api is not installed; cannot use real mode. "
                    "Install it (it's already in requirements.txt) or use mock=True."
                )
            self.config = config or AlpacaConfig.from_env()
            self.api = tradeapi.REST(
                key_id=self.config.api_key,
                secret_key=self.config.api_secret,
                base_url=self.config.base_url,
                api_version="v2",
            )
            # Verify connectivity at construction time so failures are caught
            # at startup not at first rebalance. Logged event is the canary.
            try:
                self.api.get_account()
                self.log.event("connect", {"base_url": self.config.base_url, "status": "ok"})
            except Exception as exc:
                self.log.event(
                    "connect",
                    {"base_url": self.config.base_url, "error": str(exc)},
                    level="error",
                )
                raise

    # -------------------------------------------------------------------
    # Account
    # -------------------------------------------------------------------

    def get_account(self) -> AlpacaAccount:
        t0 = time.time()
        if self.mock:
            acc = self._mock_account
        else:
            r = self.api.get_account()
            acc = AlpacaAccount(
                account_number=r.account_number,
                status=str(r.status),
                buying_power=float(r.buying_power),
                cash=float(r.cash),
                equity=float(r.equity),
                portfolio_value=float(r.portfolio_value),
                pattern_day_trader=bool(getattr(r, "pattern_day_trader", False)),
                trading_blocked=bool(getattr(r, "trading_blocked", False)),
            )
        self.log.event("get_account", {"account": acc, "elapsed_ms": int((time.time() - t0) * 1000)})
        return acc

    # -------------------------------------------------------------------
    # Positions
    # -------------------------------------------------------------------

    def get_positions(self) -> list[AlpacaPosition]:
        t0 = time.time()
        if self.mock:
            positions = list(self._mock_positions.values())
        else:
            rows = self.api.list_positions()
            positions = [
                AlpacaPosition(
                    symbol=r.symbol,
                    qty=float(r.qty),
                    avg_entry_price=float(r.avg_entry_price),
                    market_value=float(r.market_value),
                    current_price=float(r.current_price),
                    unrealized_pl=float(r.unrealized_pl),
                    side="long" if float(r.qty) > 0 else "short",
                )
                for r in rows
            ]
        self.log.event(
            "get_positions",
            {"n_positions": len(positions), "elapsed_ms": int((time.time() - t0) * 1000)},
        )
        return positions

    def get_position(self, symbol: str) -> Optional[AlpacaPosition]:
        if self.mock:
            return self._mock_positions.get(symbol)
        try:
            r = self.api.get_position(symbol)
            return AlpacaPosition(
                symbol=r.symbol,
                qty=float(r.qty),
                avg_entry_price=float(r.avg_entry_price),
                market_value=float(r.market_value),
                current_price=float(r.current_price),
                unrealized_pl=float(r.unrealized_pl),
                side="long" if float(r.qty) > 0 else "short",
            )
        except Exception:
            # Alpaca raises 404 if no position; we return None for cleanliness
            return None

    # -------------------------------------------------------------------
    # Clock
    # -------------------------------------------------------------------

    def get_clock(self) -> AlpacaClock:
        if self.mock:
            now = datetime.now(timezone.utc)
            return AlpacaClock(timestamp=now, is_open=True, next_open=None, next_close=None)
        r = self.api.get_clock()
        return AlpacaClock(
            timestamp=r.timestamp,
            is_open=bool(r.is_open),
            next_open=getattr(r, "next_open", None),
            next_close=getattr(r, "next_close", None),
        )

    # -------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------

    def submit_order(self, req: AlpacaOrderRequest) -> AlpacaOrderResult:
        """
        Submit an order. Idempotent if `req.client_order_id` is set — Alpaca
        rejects duplicates with same client_order_id (so a rerun won't
        double-submit).

        For market orders, log the intent timestamp + the broker's submitted
        timestamp; the delta is the headline 'intent_to_fill' metric.
        """
        intent_ts = datetime.now(timezone.utc)
        client_id = req.client_order_id or f"alphasmart-{uuid.uuid4().hex[:12]}"

        if self.mock:
            t0 = time.time()
            # Simulate fill at some plausible price for testing.
            mock_fill_price = 100.0
            order_id = f"mock-{uuid.uuid4().hex[:12]}"
            res = AlpacaOrderResult(
                id=order_id,
                client_order_id=client_id,
                symbol=req.symbol,
                qty=req.qty,
                side=req.side,
                submitted_at=datetime.now(timezone.utc),
                status="filled",
                filled_qty=req.qty,
                filled_avg_price=mock_fill_price,
                type=req.type,
                time_in_force=req.time_in_force,
            )
            # Update mock state
            existing = self._mock_positions.get(req.symbol)
            signed_qty = req.qty if req.side == "buy" else -req.qty
            if existing is None:
                self._mock_positions[req.symbol] = AlpacaPosition(
                    symbol=req.symbol, qty=signed_qty,
                    avg_entry_price=mock_fill_price,
                    market_value=signed_qty * mock_fill_price,
                    current_price=mock_fill_price,
                    unrealized_pl=0.0,
                    side="long" if signed_qty > 0 else "short",
                )
            else:
                new_qty = existing.qty + signed_qty
                if abs(new_qty) < 1e-9:
                    del self._mock_positions[req.symbol]
                else:
                    existing.qty = new_qty
                    existing.market_value = new_qty * mock_fill_price
                    existing.side = "long" if new_qty > 0 else "short"
            self._mock_orders.append(res)
            self._mock_account.cash -= signed_qty * mock_fill_price
            elapsed_ms = int((time.time() - t0) * 1000)
        else:
            t0 = time.time()
            r = self.api.submit_order(
                symbol=req.symbol,
                qty=req.qty,
                side=req.side,
                type=req.type,
                time_in_force=req.time_in_force,
                limit_price=req.limit_price,
                client_order_id=client_id,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            res = AlpacaOrderResult(
                id=r.id,
                client_order_id=r.client_order_id,
                symbol=r.symbol,
                qty=float(r.qty),
                side=r.side,
                submitted_at=r.submitted_at,
                status=str(r.status),
                filled_qty=float(r.filled_qty or 0.0),
                filled_avg_price=float(r.filled_avg_price) if r.filled_avg_price else None,
                type=r.order_type if hasattr(r, "order_type") else r.type,
                time_in_force=r.time_in_force,
            )

        # Headline log entry: intent timestamp, broker submitted timestamp,
        # elapsed wall-clock — the four implementation gaps from
        # paper_trade_design.md §2 are derived from these fields.
        self.log.event(
            "submit_order",
            {
                "intent_ts_utc": intent_ts,
                "submitted_ts_utc": res.submitted_at,
                "elapsed_ms": elapsed_ms,
                "request": req,
                "result": res,
            },
        )
        return res

    def list_open_orders(self) -> list[AlpacaOrderResult]:
        if self.mock:
            return [o for o in self._mock_orders if o.status not in ("filled", "canceled")]
        rows = self.api.list_orders(status="open")
        return [
            AlpacaOrderResult(
                id=r.id, client_order_id=r.client_order_id, symbol=r.symbol,
                qty=float(r.qty), side=r.side, submitted_at=r.submitted_at,
                status=str(r.status), filled_qty=float(r.filled_qty or 0.0),
                filled_avg_price=float(r.filled_avg_price) if r.filled_avg_price else None,
                type=r.order_type if hasattr(r, "order_type") else r.type,
                time_in_force=r.time_in_force,
            )
            for r in rows
        ]

    def cancel_order(self, order_id: str) -> None:
        t0 = time.time()
        if self.mock:
            for o in self._mock_orders:
                if o.id == order_id and o.status not in ("filled", "canceled"):
                    o.status = "canceled"
                    break
        else:
            self.api.cancel_order(order_id)
        self.log.event("cancel_order", {"order_id": order_id, "elapsed_ms": int((time.time() - t0) * 1000)})
