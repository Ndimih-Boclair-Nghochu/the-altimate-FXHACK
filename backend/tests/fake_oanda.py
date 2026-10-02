"""A small stateful fake of the OANDA v20 REST API, served through respx.

Enough of the API for the broker contract suite: account, instruments, pricing, market orders
with stop-loss/take-profit on fill and price bound, order lookup by client id, trades,
positions, closes and transactions. Responses follow the shapes in
docs/research/02-oanda-v20-api-spec.md. Failure injection covers the cases where the outcome
of an order POST is unknown to the client.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

import httpx
import respx

from tests.support import CREDENTIALS, PRACTICE, fixture

ACCOUNT = CREDENTIALS.account_id
_ACCOUNT_PREFIX = re.compile(r"^/v3/accounts/(?P<account>[^/]+)(?P<rest>/.*)?$")
_TIME = "2024-03-04T12:00:00.000000000Z"

Failure = Literal["timeout_before", "timeout_after", "server_error_after"]


@dataclass
class _Trade:
    id: str
    client_id: str
    instrument: str
    units: Decimal  # signed
    price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None


@dataclass
class FakeOandaServer:
    balance: Decimal = Decimal("100000")
    prices: dict[str, tuple[Decimal, Decimal, bool]] = field(default_factory=dict)
    trades: dict[str, _Trade] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)  # by client id
    transactions: list[dict[str, Any]] = field(default_factory=list)
    order_posts: int = 0
    fail_next_order: Failure | None = None
    drop_stop_on_fill: bool = False
    requests: list[httpx.Request] = field(default_factory=list)
    _next_id: int = 100

    def router(self) -> respx.Router:
        router = respx.Router(base_url=PRACTICE.rest, assert_all_called=False)
        router.route().mock(side_effect=self.handle)
        return router

    def set_price(self, instrument: str, bid: str, ask: str, *, tradeable: bool = True) -> None:
        self.prices[instrument] = (Decimal(bid), Decimal(ask), tradeable)

    # ------------------------------------------------------------------ plumbing

    def _id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def _record(self, tx: dict[str, Any]) -> dict[str, Any]:
        tx = {"id": self._id(), "time": _TIME, "accountID": ACCOUNT, "userID": 1, **tx}
        self.transactions.append(tx)
        return tx

    @staticmethod
    def _json(status: int, body: dict[str, Any]) -> httpx.Response:
        return httpx.Response(status, json=body, headers={"RequestID": "fake-request"})

    def _not_found(self, message: str = "not found") -> httpx.Response:
        return self._json(404, {"errorMessage": message})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v3/accounts":
            return self._json(200, {"accounts": [{"id": ACCOUNT, "tags": []}]})
        match = _ACCOUNT_PREFIX.match(path)
        if match is None or match["account"] != ACCOUNT:
            return self._json(403, {"errorMessage": "Insufficient authorization"})
        rest = match["rest"] or ""
        method = request.method
        body = json.loads(request.content) if request.content else {}
        routes: list[tuple[str, str, Any]] = [
            ("GET", r"/summary", self._summary),
            ("GET", r"/instruments", self._instruments),
            ("GET", r"/pricing", self._pricing),
            ("POST", r"/orders", self._create_order),
            ("GET", r"/orders/(?P<spec>[^/]+)", self._get_order),
            ("GET", r"/openTrades", self._open_trades),
            ("GET", r"/trades/(?P<spec>[^/]+)", self._get_trade),
            ("PUT", r"/trades/(?P<spec>[^/]+)/close", self._close_trade),
            ("PUT", r"/trades/(?P<spec>[^/]+)/orders", self._trade_orders),
            ("GET", r"/openPositions", self._open_positions),
            ("PUT", r"/positions/(?P<inst>[^/]+)/close", self._close_position),
            ("GET", r"/transactions/sinceid", self._since),
            ("GET", r"/transactions/(?P<tx>[0-9]+)", self._transaction),
        ]
        for verb, pattern, handler in routes:
            found = re.fullmatch(pattern, rest)
            if verb == method and found:
                result: httpx.Response = handler(request, body, **found.groupdict())
                return result
        return self._json(405, {"errorMessage": "unsupported in fake"})

    # ------------------------------------------------------------------ account

    def _unrealized(self) -> Decimal:
        total = Decimal(0)
        for trade in self.trades.values():
            bid, ask, _ = self.prices[trade.instrument]
            exit_price = bid if trade.units > 0 else ask
            total += (exit_price - trade.price) * trade.units
        return total

    def _summary(self, request: httpx.Request, body: Any) -> httpx.Response:
        unrealized = self._unrealized()
        last = self.transactions[-1]["id"] if self.transactions else "100"
        account = {
            "id": ACCOUNT,
            "currency": "USD",
            "balance": str(self.balance),
            "NAV": str(self.balance + unrealized),
            "unrealizedPL": str(unrealized),
            "marginUsed": "0.0000",
            "marginAvailable": str(self.balance + unrealized),
            "marginCloseoutPercent": "0.00000",
            "openTradeCount": len(self.trades),
            "openPositionCount": len({t.instrument for t in self.trades.values()}),
            "hedgingEnabled": False,
            "lastTransactionID": last,
        }
        return self._json(200, {"account": account, "lastTransactionID": last})

    def _instruments(self, request: httpx.Request, body: Any) -> httpx.Response:
        wanted = request.url.params.get("instruments")
        items = fixture("instruments.json")["instruments"]
        if wanted:
            items = [i for i in items if i["name"] in wanted.split(",")]
        return self._json(200, {"instruments": items, "lastTransactionID": "100"})

    def _price_json(self, instrument: str) -> dict[str, Any]:
        bid, ask, tradeable = self.prices[instrument]
        return {
            "type": "PRICE",
            "instrument": instrument,
            "time": _TIME,
            "tradeable": tradeable,
            "bids": [{"price": str(bid), "liquidity": 1_000_000}],
            "asks": [{"price": str(ask), "liquidity": 1_000_000}],
        }

    def _pricing(self, request: httpx.Request, body: Any) -> httpx.Response:
        names = request.url.params.get("instruments", "").split(",")
        prices = [self._price_json(n) for n in names if n in self.prices]
        return self._json(200, {"prices": prices, "time": _TIME})

    # ------------------------------------------------------------------ orders

    def _create_order(self, request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        self.order_posts += 1
        failure, self.fail_next_order = self.fail_next_order, None
        if failure == "timeout_before":
            raise httpx.ReadTimeout("timed out", request=request)
        response = self._execute(body["order"])
        if failure == "timeout_after":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure == "server_error_after":
            return self._json(503, {"errorMessage": "Service unavailable"})
        return response

    def _execute(self, order: dict[str, Any]) -> httpx.Response:
        client_id = order["clientExtensions"]["id"]
        instrument = order["instrument"]
        units = Decimal(order["units"])
        create = self._record({**order, "type": "MARKET_ORDER", "reason": "CLIENT_ORDER"})
        record: dict[str, Any] = {
            "id": create["id"],
            "type": "MARKET",
            "instrument": instrument,
            "units": order["units"],
            "clientExtensions": order["clientExtensions"],
            "createTime": _TIME,
        }
        self.orders[client_id] = record
        bid, ask, tradeable = self.prices[instrument]
        fill_price = ask if units > 0 else bid
        bound = Decimal(order["priceBound"])
        reason = None
        if not tradeable:
            reason = "MARKET_HALTED"
        elif (fill_price - bound) * (1 if units > 0 else -1) > 0:
            reason = "BOUNDS_VIOLATION"
        if reason is not None:
            cancel = self._record(
                {"type": "ORDER_CANCEL", "orderID": create["id"], "reason": reason}
            )
            record.update(state="CANCELLED", cancellingTransactionID=cancel["id"])
            return self._json(
                201,
                {
                    "orderCreateTransaction": create,
                    "orderCancelTransaction": cancel,
                    "lastTransactionID": cancel["id"],
                },
            )
        fill = self._record(
            {
                "type": "ORDER_FILL",
                "orderID": create["id"],
                "clientOrderID": client_id,
                "instrument": instrument,
                "units": str(units),
                "price": str(fill_price),
                "reason": "MARKET_ORDER",
                "commission": "0.0000",
                "halfSpreadCost": "0.5000",
                "tradeOpened": {
                    "tradeID": None,
                    "units": str(units),
                    "price": str(fill_price),
                    "halfSpreadCost": "0.5000",
                },
            }
        )
        fill["tradeOpened"]["tradeID"] = fill["id"]
        stop = order.get("stopLossOnFill")
        target = order.get("takeProfitOnFill")
        self.trades[fill["id"]] = _Trade(
            id=fill["id"],
            client_id=client_id,
            instrument=instrument,
            units=units,
            price=fill_price,
            stop_loss=None if self.drop_stop_on_fill or not stop else Decimal(stop["price"]),
            take_profit=Decimal(target["price"]) if target else None,
        )
        record.update(state="FILLED", fillingTransactionID=fill["id"], tradeOpenedID=fill["id"])
        return self._json(
            201,
            {
                "orderCreateTransaction": create,
                "orderFillTransaction": fill,
                "relatedTransactionIDs": [create["id"], fill["id"]],
                "lastTransactionID": fill["id"],
            },
        )

    def _get_order(self, request: httpx.Request, body: Any, spec: str) -> httpx.Response:
        record = self.orders.get(spec.removeprefix("@"))
        if record is None:
            return self._not_found("Order specified does not exist")
        return self._json(200, {"order": record, "lastTransactionID": "100"})

    def _transaction(self, request: httpx.Request, body: Any, tx: str) -> httpx.Response:
        for item in self.transactions:
            if item["id"] == tx:
                return self._json(200, {"transaction": item, "lastTransactionID": tx})
        return self._not_found()

    def _since(self, request: httpx.Request, body: Any) -> httpx.Response:
        after = int(request.url.params["id"])
        items = [t for t in self.transactions if int(t["id"]) > after]
        last = self.transactions[-1]["id"] if self.transactions else str(after)
        return self._json(200, {"transactions": items, "lastTransactionID": last})

    # ------------------------------------------------------------------ trades

    def _trade_json(self, trade: _Trade) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": trade.id,
            "instrument": trade.instrument,
            "price": str(trade.price),
            "openTime": _TIME,
            "state": "OPEN",
            "initialUnits": str(trade.units),
            "currentUnits": str(trade.units),
            "realizedPL": "0.0000",
            "unrealizedPL": "0.0000",
            "financing": "0.0000",
            "clientExtensions": {"id": trade.client_id},
        }
        if trade.stop_loss is not None:
            data["stopLossOrder"] = {"id": "1", "price": str(trade.stop_loss), "state": "PENDING"}
        if trade.take_profit is not None:
            data["takeProfitOrder"] = {"id": "2", "price": str(trade.take_profit)}
        return data

    def _open_trades(self, request: httpx.Request, body: Any) -> httpx.Response:
        trades = [self._trade_json(t) for t in self.trades.values()]
        return self._json(200, {"trades": trades, "lastTransactionID": "100"})

    def _find_trade(self, spec: str) -> _Trade | None:
        if spec.startswith("@"):
            return next((t for t in self.trades.values() if t.client_id == spec[1:]), None)
        return self.trades.get(spec)

    def _get_trade(self, request: httpx.Request, body: Any, spec: str) -> httpx.Response:
        trade = self._find_trade(spec)
        if trade is None:
            return self._not_found("Trade specified does not exist")
        return self._json(200, {"trade": self._trade_json(trade), "lastTransactionID": "100"})

    def _close_fill(self, trade: _Trade, units: Decimal, reason: str) -> dict[str, Any]:
        bid, ask, _ = self.prices[trade.instrument]
        price = bid if trade.units > 0 else ask
        signed = -units if trade.units > 0 else units
        realized = (price - trade.price) * (units if trade.units > 0 else -units)
        self.balance += realized
        fill = self._record(
            {
                "type": "ORDER_FILL",
                "orderID": self._id(),
                "instrument": trade.instrument,
                "units": str(signed),
                "price": str(price),
                "reason": reason,
                "tradesClosed": [
                    {
                        "tradeID": trade.id,
                        "units": str(signed),
                        "price": str(price),
                        "realizedPL": str(realized),
                        "financing": "0.0000",
                    }
                ],
            }
        )
        remaining = abs(trade.units) - units
        if remaining == 0:
            del self.trades[trade.id]
        else:
            trade.units = remaining if trade.units > 0 else -remaining
        return fill

    def _close_trade(
        self, request: httpx.Request, body: dict[str, Any], spec: str
    ) -> httpx.Response:
        trade = self._find_trade(spec)
        if trade is None:
            return self._not_found("Trade specified does not exist")
        units = abs(trade.units) if body["units"] == "ALL" else Decimal(body["units"])
        fill = self._close_fill(trade, units, "MARKET_ORDER_TRADE_CLOSE")
        return self._json(200, {"orderFillTransaction": fill, "lastTransactionID": fill["id"]})

    def _trade_orders(
        self, request: httpx.Request, body: dict[str, Any], spec: str
    ) -> httpx.Response:
        trade = self._find_trade(spec)
        if trade is None:
            return self._not_found("Trade specified does not exist")
        response: dict[str, Any] = {}
        if "stopLoss" in body:
            trade.stop_loss = Decimal(body["stopLoss"]["price"])
            response["stopLossOrderTransaction"] = self._record(
                {"type": "STOP_LOSS_ORDER", "tradeID": trade.id, "price": body["stopLoss"]["price"]}
            )
        if "takeProfit" in body:
            trade.take_profit = Decimal(body["takeProfit"]["price"])
            response["takeProfitOrderTransaction"] = self._record(
                {
                    "type": "TAKE_PROFIT_ORDER",
                    "tradeID": trade.id,
                    "price": body["takeProfit"]["price"],
                }
            )
        return self._json(200, response)

    # ------------------------------------------------------------------ positions

    def _open_positions(self, request: httpx.Request, body: Any) -> httpx.Response:
        positions: dict[str, dict[str, Any]] = {}
        for trade in self.trades.values():
            pos = positions.setdefault(
                trade.instrument,
                {
                    "instrument": trade.instrument,
                    "unrealizedPL": "0.0000",
                    "long": {"units": "0"},
                    "short": {"units": "0"},
                },
            )
            side = "long" if trade.units > 0 else "short"
            pos[side] = {
                "units": str(Decimal(pos[side]["units"]) + trade.units),
                "averagePrice": str(trade.price),
                "tradeIDs": [trade.id],
            }
        return self._json(200, {"positions": list(positions.values()), "lastTransactionID": "100"})

    def _close_position(
        self, request: httpx.Request, body: dict[str, Any], inst: str
    ) -> httpx.Response:
        response: dict[str, Any] = {}
        for side, key in (("long", "longUnits"), ("short", "shortUnits")):
            if body.get(key) != "ALL":
                continue
            trades = [
                t
                for t in list(self.trades.values())
                if t.instrument == inst and (t.units > 0) == (side == "long")
            ]
            closed = []
            for trade in trades:
                fill = self._close_fill(trade, abs(trade.units), "MARKET_ORDER_POSITION_CLOSEOUT")
                closed.extend(fill["tradesClosed"])
            if closed:
                fill["tradesClosed"] = closed
                response[f"{side}OrderFillTransaction"] = fill
        return self._json(200, response)
