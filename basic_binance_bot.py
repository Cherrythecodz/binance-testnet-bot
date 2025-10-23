import argparse
import time
import hmac
import hashlib
import logging
import requests
from urllib.parse import urlencode

# ---------- CONFIG ----------
TESTNET_BASE = "https://testnet.binancefuture.com"
ORDER_PATH = "/fapi/v1/order"
TIMEOUT = 10  # seconds for HTTP requests
LOGFILE = "basic_binance_bot.log"
# ----------------------------

# Setup logging (file + console)
logger = logging.getLogger("BasicBot")
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

fh = logging.FileHandler(LOGFILE)
fh.setLevel(logging.DEBUG)
fh.setFormatter(fmt)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(fmt)
logger.addHandler(ch)


class BasicBot:
    def __init__(self, api_key: str, api_secret: str, base_url: str = TESTNET_BASE):
        """
        BasicBot - minimal Binance Futures REST trading wrapper (Testnet-compatible).
        """
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        })
        logger.debug("Initialized BasicBot with base_url=%s", self.base_url)

    def _sign_payload(self, params: dict) -> dict:
        """Add timestamp and signature to params and return a query string dict."""
        params = params.copy()
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(self.api_secret, query_string.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    def _post(self, path: str, params: dict):
        url = self.base_url + path
        signed_params = self._sign_payload(params)
        data = urlencode(signed_params)
        logger.debug("POST %s | payload: %s", url, data)
        try:
            resp = self.session.post(url, data=data, timeout=TIMEOUT)
            logger.info("HTTP %s %s -> %s", resp.request.method, resp.url, resp.status_code)
            logger.debug("Response text: %s", resp.text)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logger.error("HTTP error: %s | status_code=%s | response=%s",
                         str(e),
                         getattr(e.response, "status_code", None),
                         getattr(e.response, "text", None))
            raise
        except Exception as e:
            logger.exception("Request failed: %s", e)
            raise

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float,
                    price: float = None, stop_price: float = None, time_in_force: str = "GTC",
                    reduce_only: bool = False, close_position: bool = False):
        """
        Place an order on Binance Futures (USDT-M).

        Supported order_type: MARKET, LIMIT, STOP_LIMIT
        For STOP_LIMIT: provide both stop_price and price.
        """
        symbol = symbol.upper()
        side = side.upper()
        order_type = order_type.upper()

        # Basic validation
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if order_type not in ("MARKET", "LIMIT", "STOP_LIMIT"):
            raise ValueError("order_type must be MARKET, LIMIT, or STOP_LIMIT")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if order_type == "LIMIT" and (price is None or price <= 0):
            raise ValueError("LIMIT orders require a positive price")
        if order_type == "STOP_LIMIT" and (stop_price is None or price is None):
            raise ValueError("STOP_LIMIT requires both stop_price and price")

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET" if order_type == "MARKET" else ("LIMIT" if order_type == "LIMIT" else "STOP"),
            "quantity": float(quantity),
            "recvWindow": 60000,
        }

        if order_type == "LIMIT":
            params.update({"price": str(price), "timeInForce": time_in_force})
        elif order_type == "STOP_LIMIT":
            params.update({"price": str(price), "stopPrice": str(stop_price), "timeInForce": time_in_force})

        # Optional flags:
        if reduce_only:
            params["reduceOnly"] = "true"
        if close_position:
            params["closePosition"] = "true"

        logger.info("Placing %s order: %s %s qty=%s price=%s stopPrice=%s",
                    order_type, side, symbol, quantity, price, stop_price)
        try:
            result = self._post(ORDER_PATH, params)
            logger.info("Order accepted: orderId=%s status=%s", result.get("orderId"), result.get("status"))
            return result
        except Exception as e:
            raise


def parse_args():
    p = argparse.ArgumentParser(description="Basic Binance Futures Testnet Bot (USDT-M)")

    p.add_argument("--api-key", required=True, help="Binance Testnet API key")
    p.add_argument("--api-secret", required=True, help="Binance Testnet API secret")
    p.add_argument("--base-url", default=TESTNET_BASE, help=f"Testnet base URL (default: {TESTNET_BASE})")

    p.add_argument("--symbol", required=True, help="Trading pair symbol e.g. BTCUSDT")
    p.add_argument("--side", required=True, choices=["BUY", "SELL"], help="BUY or SELL")
    p.add_argument("--type", required=True, choices=["MARKET", "LIMIT", "STOP_LIMIT"], help="Order type")
    p.add_argument("--quantity", required=True, type=float, help="Quantity (contract base amount)")
    p.add_argument("--price", type=float, help="Limit price (required for LIMIT, STOP_LIMIT)")
    p.add_argument("--stop-price", dest="stop_price", type=float, help="Stop trigger price (required for STOP_LIMIT)")
    p.add_argument("--time-in-force", default="GTC", choices=["GTC", "IOC", "FOK"], help="Time in force for LIMIT orders")
    p.add_argument("--reduce-only", action="store_true", help="Set reduceOnly flag on order")
    p.add_argument("--close-position", action="store_true", help="Set closePosition flag (useful for market close)")

    return p.parse_args()


def main():
    args = parse_args()
    bot = BasicBot(args.api_key, args.api_secret, base_url=args.base_url)

    try:
        result = bot.place_order(
            symbol=args.symbol,
            side=args.side,
            order_type=args.type,
            quantity=args.quantity,
            price=args.price,
            stop_price=args.stop_price,
            time_in_force=args.time_in_force,
            reduce_only=args.reduce_only,
            close_position=args.close_position
        )

        print("\nORDER RESPONSE SUMMARY:")
        important_keys = ["symbol", "orderId", "clientOrderId", "transactTime",
                          "price", "origQty", "executedQty", "status", "type", "side"]
        for k in important_keys:
            if k in result:
                print(f"  {k:15} : {result[k]}")
        print("\nFull response saved to log file and printed in DEBUG logs.")
    except Exception as e:
        print(f"Order failed: {e}")
        logger.error("Order failed (exception): %s", e)


if __name__ == "__main__":
    main()
