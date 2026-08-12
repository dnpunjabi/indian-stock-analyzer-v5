"""
WebSocket Streaming Server
============================
Two-tier real-time pipeline:
  1. Angel One SmartWebSocketV2 (upstream) → Tick Store
  2. FastAPI WebSocket /ws/live-ticks (downstream) → Browser clients

Also includes the AlertEvaluator for instant PRICE alert triggering.
"""

import json
import time
import asyncio
import threading
import logging
import sqlite3
import os
from datetime import datetime
from typing import Dict, Set, Optional, Any, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("websocket_server")

# Try importing Angel One WebSocket SDK
try:
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    SMARTWS_AVAILABLE = True
except ImportError:
    SMARTWS_AVAILABLE = False
    logger.warning("SmartWebSocketV2 not available. Live ticks will not stream.")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tick Store — Thread-safe in-memory cache of latest ticks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TickStore:
    """Thread-safe in-memory store for the latest tick data per symbol."""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_update: float = 0.0

    def update(self, symbol: str, tick: Dict[str, Any]):
        with self._lock:
            self._data[symbol] = tick
            self._last_update = time.time()

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(symbol)

    def get_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {s: self._data[s] for s in symbols if s in self._data}

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._data)

    @property
    def last_update_time(self) -> float:
        return self._last_update

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._data)


# Global tick store instance
tick_store = TickStore()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Alert Evaluator — Instant PRICE alert checking per tick
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AlertEvaluator:
    """
    Maintains an in-memory registry of active PRICE/SMA alerts.
    Evaluates them on each incoming tick for instant triggering.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._alerts: Dict[str, List[Dict]] = {}  # symbol → [alert_dicts]
        self._lock = threading.Lock()
        self._triggered_queue: List[Dict] = []  # Triggered alerts pending WS broadcast

    def load_active_alerts(self):
        """Load all untriggered PRICE and SMA alerts from SQLite."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, ticker, condition_type, operator, value, triggered "
                "FROM alerts WHERE triggered = 0 AND condition_type IN ('PRICE', 'SMA')"
            )
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()

            with self._lock:
                self._alerts.clear()
                for row in rows:
                    symbol = row["ticker"].strip().upper()
                    # Remove .NS suffix for matching
                    if symbol.endswith(".NS"):
                        symbol = symbol[:-3]
                    if symbol not in self._alerts:
                        self._alerts[symbol] = []
                    self._alerts[symbol].append(row)

            logger.info(f"AlertEvaluator loaded {len(rows)} active PRICE/SMA alerts "
                        f"across {len(self._alerts)} symbols.")
        except Exception as e:
            logger.error(f"AlertEvaluator failed to load alerts: {e}")

    def register_alert(self, alert: Dict):
        """Dynamically register a new alert (called when user creates one)."""
        if alert.get("condition_type") not in ("PRICE", "SMA"):
            return
        symbol = alert["ticker"].strip().upper()
        if symbol.endswith(".NS"):
            symbol = symbol[:-3]
        with self._lock:
            if symbol not in self._alerts:
                self._alerts[symbol] = []
            self._alerts[symbol].append(alert)
        logger.info(f"AlertEvaluator: Registered new alert #{alert.get('id')} for {symbol}")

    def unregister_alert(self, alert_id: int):
        """Remove an alert from the evaluator (called when user deletes one)."""
        with self._lock:
            for symbol in list(self._alerts.keys()):
                self._alerts[symbol] = [
                    a for a in self._alerts[symbol] if a.get("id") != alert_id
                ]
                if not self._alerts[symbol]:
                    del self._alerts[symbol]

    def get_alert_symbols(self) -> Set[str]:
        """Returns the set of symbols that have active alerts."""
        with self._lock:
            return set(self._alerts.keys())

    def evaluate_tick(self, symbol: str, price: float) -> List[Dict]:
        """
        Check if any PRICE alerts for this symbol have been triggered.
        Returns list of triggered alert dicts.
        """
        triggered = []
        with self._lock:
            alerts = self._alerts.get(symbol, [])
            remaining = []
            for alert in alerts:
                fired = False
                try:
                    threshold = float(alert["value"])
                    operator = alert["operator"]

                    if alert["condition_type"] == "PRICE":
                        if operator == ">" and price > threshold:
                            fired = True
                        elif operator == "<" and price < threshold:
                            fired = True
                except (ValueError, KeyError):
                    pass

                if fired:
                    alert["_triggered_price"] = price
                    alert["_triggered_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
                    triggered.append(alert)
                    # Persist to DB
                    self._mark_triggered_in_db(alert, price)
                else:
                    remaining.append(alert)

            if triggered:
                self._alerts[symbol] = remaining
                if not remaining:
                    del self._alerts[symbol]

        return triggered

    def _mark_triggered_in_db(self, alert: Dict, price: float):
        """Persist the triggered state to SQLite."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            trigger_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ai_context = (
                f"Alert triggered via real-time WebSocket tick. "
                f"Price reached ₹{price:.2f} (Target: {alert['operator']} {alert['value']})."
            )
            cursor.execute(
                "UPDATE alerts SET triggered = 1, status = 'Triggered', "
                "trigger_date = ?, ai_context = ? WHERE id = ?",
                (trigger_date, ai_context, alert["id"])
            )
            conn.commit()
            conn.close()
            logger.info(
                f"ALERT TRIGGERED (real-time): #{alert['id']} {alert['ticker']} "
                f"price ₹{price:.2f} {alert['operator']} {alert['value']}"
            )
        except Exception as e:
            logger.error(f"Failed to persist alert trigger #{alert.get('id')}: {e}")

    def pop_triggered_queue(self) -> List[Dict]:
        """Pop all triggered alerts from the queue (for WS broadcast)."""
        with self._lock:
            items = list(self._triggered_queue)
            self._triggered_queue.clear()
            return items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Connection Manager — Tracks browser WebSocket clients
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConnectionManager:
    """Manages multiple browser WebSocket connections with per-client subscriptions."""

    def __init__(self):
        # ws → set of subscribed symbols
        self._connections: Dict[WebSocket, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = set()
        logger.info(f"Browser WS client connected. Total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.pop(websocket, None)
        logger.info(f"Browser WS client disconnected. Total: {len(self._connections)}")

    async def subscribe(self, websocket: WebSocket, symbols: List[str]):
        async with self._lock:
            if websocket in self._connections:
                self._connections[websocket] = set(s.upper() for s in symbols)

    async def unsubscribe(self, websocket: WebSocket, symbols: List[str]):
        async with self._lock:
            if websocket in self._connections:
                for s in symbols:
                    self._connections[websocket].discard(s.upper())

    def get_all_subscribed_symbols(self) -> Set[str]:
        """Returns the union of all symbols subscribed by all clients."""
        result = set()
        # Take a snapshot copy of connections to avoid dict size mutation during iteration
        for symbols in list(self._connections.values()):
            result.update(symbols)
        return result

    async def broadcast_ticks(self, ticks: Dict[str, Dict], source: str = "yfinance_fallback"):
        """Send tick updates to each client, filtered by their subscription set."""
        disconnected = []
        indices = {"^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^CNXINFRA", "^CNXAUTO"}
        for ws, subscribed_symbols in list(self._connections.items()):
            # Filter ticks to only those the client cares about, plus index tickers
            client_ticks = {s: t for s, t in ticks.items() if s in subscribed_symbols or s in indices}
            if not client_ticks:
                continue
            try:
                await ws.send_json({"type": "ticks", "data": client_ticks, "source": source})
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast_alert(self, alert_data: Dict):
        """Push an alert trigger notification to ALL connected clients."""
        disconnected = []
        for ws in list(self._connections.keys()):
            try:
                await ws.send_json({"type": "alert_triggered", "alert": alert_data})
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            await self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Global instances
connection_manager = ConnectionManager()
alert_evaluator: Optional[AlertEvaluator] = None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Angel One Upstream WebSocket Manager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_angel_connector = None
_angel_sws: Optional[Any] = None
_angel_thread: Optional[threading.Thread] = None
_angel_running = False
_subscribed_tokens: Set[str] = set()  # Currently subscribed Angel One tokens
_broadcast_loop_task = None


def _on_data(wsapp, message):
    """Callback: Angel One WebSocket tick received."""
    global alert_evaluator
    try:
        if isinstance(message, str):
            data = json.loads(message)
        elif isinstance(message, dict):
            data = message
        else:
            return

        token = str(data.get("token", ""))
        if not token or not _angel_connector:
            return

        symbol = _angel_connector.token_to_symbol(token)
        if not symbol:
            return

        # Prices from Angel One binary format are in paise (divided by 100 for actual value)
        ltp = float(data.get("last_traded_price", 0)) / 100.0
        close_price = float(data.get("closed_price", 0)) / 100.0
        high_price = float(data.get("high_price_of_the_day", 0)) / 100.0
        low_price = float(data.get("low_price_of_the_day", 0)) / 100.0

        # If values are missing (e.g. if subscribed to LTP mode instead of Quote), fallback to LTP
        if close_price == 0:
            if ltp > 100000:
                ltp = ltp / 100.0
            close_price = ltp

        change = ltp - close_price
        change_pct = (change / close_price * 100.0) if close_price > 0 else 0.0

        tick = {
            "price": round(ltp, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "high": round(high_price, 2) if high_price > 0 else round(ltp, 2),
            "low": round(low_price, 2) if low_price > 0 else round(ltp, 2),
            "volume": int(data.get("volume_trade_for_the_day", 0)),
            "timestamp": time.time(),
        }

        tick_store.update(symbol, tick)

        # Evaluate PRICE alerts for this symbol
        if alert_evaluator and tick["price"] > 0:
            triggered = alert_evaluator.evaluate_tick(symbol, tick["price"])
            if triggered:
                # Queue for async WS broadcast (will be picked up by broadcast loop)
                for alert in triggered:
                    alert_evaluator._triggered_queue.append({
                        "id": alert["id"],
                        "ticker": alert["ticker"],
                        "condition_type": alert["condition_type"],
                        "operator": alert["operator"],
                        "value": alert["value"],
                        "triggered_price": tick["price"],
                        "triggered_time": alert.get("_triggered_time", ""),
                    })

    except Exception as e:
        logger.error(f"Error processing Angel One tick: {e}")


def _on_open(wsapp):
    """Callback: Angel One WebSocket connected."""
    logger.info("Angel One upstream WebSocket connected.")


def _on_error(wsapp, error):
    """Callback: Angel One WebSocket error."""
    logger.error(f"Angel One WebSocket error: {error}")


def _on_close(wsapp, close_status_code=None, close_msg=None):
    """Callback: Angel One WebSocket closed."""
    global _angel_running
    logger.warning(f"Angel One WebSocket closed. Code: {close_status_code}, Msg: {close_msg}")
    # Auto-reconnect after 2 seconds with re-authentication check
    if _angel_running and _angel_connector:
        logger.info("Scheduling Angel One WebSocket reconnection with re-authentication check...")
        def delayed_reconnect():
            time.sleep(2)
            if _angel_running and _angel_connector:
                if not _angel_connector.is_authenticated():
                    logger.info("Session stale upon WS close. Re-authenticating Angel One...")
                    _angel_connector.re_authenticate()
                _start_upstream_thread()
        threading.Thread(target=delayed_reconnect, daemon=True, name="AngelOneReconnect").start()


def _start_upstream_thread():
    """Start the Angel One SmartWebSocketV2 in a background thread."""
    global _angel_sws, _angel_thread

    if not _angel_connector:
        logger.error("Cannot start upstream WS: Angel One connector not set.")
        return

    if not _angel_connector.is_authenticated():
        logger.info("Angel One not authenticated. Attempting auto re-authentication...")
        if not _angel_connector.re_authenticate():
            logger.error("Cannot start upstream WS: Angel One re-authentication failed.")
            return

    if not SMARTWS_AVAILABLE:
        logger.error("Cannot start upstream WS: SmartWebSocketV2 not available.")
        return

    try:
        _angel_sws = SmartWebSocketV2(
            _angel_connector.auth_token,
            _angel_connector.api_key,
            _angel_connector.client_code,
            _angel_connector.feed_token,
        )

        _angel_sws.on_open = _on_open
        _angel_sws.on_data = _on_data
        _angel_sws.on_error = _on_error
        _angel_sws.on_close = _on_close

        def run_ws():
            try:
                _angel_sws.connect()
            except Exception as e:
                logger.error(f"Angel One WS connect failed: {e}")

        _angel_thread = threading.Thread(target=run_ws, daemon=True, name="AngelOneWS")
        _angel_thread.start()
        logger.info("Angel One upstream WebSocket thread started.")
    except Exception as e:
        logger.error(f"Failed to initialize Angel One WebSocket: {e}")


def subscribe_symbols(symbols: List[str]):
    """Subscribe to Angel One tokens for the given symbols."""
    global _subscribed_tokens
    if not _angel_sws or not _angel_connector:
        return

    token_list = _angel_connector.resolve_tokens_batch(symbols)
    if not token_list:
        return

    try:
        # Check if the connection is active
        is_connected = (
            hasattr(_angel_sws, "wsapp")
            and _angel_sws.wsapp
            and hasattr(_angel_sws.wsapp, "sock")
            and _angel_sws.wsapp.sock
            and _angel_sws.wsapp.sock.connected
        )

        if is_connected:
            _angel_sws.subscribe("apex_live_feed", mode=2, token_list=token_list)
            logger.info(f"Subscribed to {len(symbols)} symbols. Total tokens: {len(_subscribed_tokens) + sum(len(g['tokens']) for g in token_list)}")
        else:
            # If not connected yet, register directly into request dict for auto-resubscription on open
            logger.info(f"WebSocket not connected. Registering {len(symbols)} symbols for auto-resubscription.")
            _angel_sws.RESUBSCRIBE_FLAG = True
            if 2 not in _angel_sws.input_request_dict:
                _angel_sws.input_request_dict[2] = {}
            for token in token_list:
                exch = token['exchangeType']
                if exch in _angel_sws.input_request_dict[2]:
                    # Avoid duplicates
                    existing = set(_angel_sws.input_request_dict[2][exch])
                    for t in token["tokens"]:
                        if t not in existing:
                            _angel_sws.input_request_dict[2][exch].append(t)
                else:
                    _angel_sws.input_request_dict[2][exch] = list(token["tokens"])

        for group in token_list:
            _subscribed_tokens.update(group["tokens"])
    except Exception as e:
        logger.warning(f"Error subscribing (will retry or auto-resubscribe): {e}")


def unsubscribe_symbols(symbols: List[str]):
    """Unsubscribe from Angel One tokens."""
    global _subscribed_tokens
    if not _angel_sws or not _angel_connector:
        return

    token_list = _angel_connector.resolve_tokens_batch(symbols)
    if not token_list:
        return

    try:
        is_connected = (
            hasattr(_angel_sws, "wsapp")
            and _angel_sws.wsapp
            and hasattr(_angel_sws.wsapp, "sock")
            and _angel_sws.wsapp.sock
            and _angel_sws.wsapp.sock.connected
        )

        if is_connected:
            _angel_sws.unsubscribe("apex_unsubscribe", mode=2, token_list=token_list)
        
        # Remove from request dict so they don't resubscribe on reconnect
        if 2 in _angel_sws.input_request_dict:
            for token in token_list:
                exch = token['exchangeType']
                if exch in _angel_sws.input_request_dict[2]:
                    tokens_to_remove = set(token["tokens"])
                    _angel_sws.input_request_dict[2][exch] = [
                        t for t in _angel_sws.input_request_dict[2][exch] if t not in tokens_to_remove
                    ]

        for group in token_list:
            _subscribed_tokens -= set(group["tokens"])
        logger.info(f"Unsubscribed {len(symbols)} symbols. Remaining: {len(_subscribed_tokens)}")
    except Exception as e:
        logger.warning(f"Error unsubscribing: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public API — Called by main.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_last_watchdog_time = 0.0

def _recover_upstream_connection():
    global alert_evaluator
    try:
        logger.info("Watchdog recovery: Re-initializing connection...")
        if not _angel_connector:
            return
        if not _angel_connector.is_authenticated():
            logger.info("Watchdog recovery: session stale. Re-authenticating...")
            if not _angel_connector.re_authenticate():
                logger.error("Watchdog recovery: Re-authentication failed.")
                return
        
        # Start the upstream thread
        _start_upstream_thread()
        
        # Delay subscription slightly to let WS connect
        time.sleep(3)
        active_symbols = []
        if alert_evaluator:
            active_symbols.extend(alert_evaluator.get_alert_symbols())
        active_symbols.extend(connection_manager.get_all_subscribed_symbols())
        active_symbols = list(set(active_symbols))
        
        if active_symbols:
            logger.info(f"Watchdog recovery: Re-subscribing to {len(active_symbols)} symbols.")
            subscribe_symbols(active_symbols)
    except Exception as e:
        logger.error(f"Watchdog recovery routine failed: {e}")


def start_angel_upstream(connector, db_path: str, extra_symbols: List[str] = None):
    """
    Initialize and start the Angel One upstream WebSocket.
    Called at FastAPI startup.
    """
    global _angel_connector, _angel_running, alert_evaluator, _broadcast_loop_task

    _angel_connector = connector
    _angel_running = True

    # Initialize alert evaluator
    alert_evaluator = AlertEvaluator(db_path)
    alert_evaluator.load_active_alerts()

    # Start the upstream WebSocket thread
    _start_upstream_thread()

    # Subscribe to initial symbols (alert tickers + any extras)
    initial_symbols = list(alert_evaluator.get_alert_symbols())
    if extra_symbols:
        initial_symbols.extend(extra_symbols)
    initial_symbols = list(set(initial_symbols))

    if initial_symbols:
        # Delay subscription slightly to let WS connect
        def delayed_subscribe():
            time.sleep(3)
            subscribe_symbols(initial_symbols)

        threading.Thread(target=delayed_subscribe, daemon=True).start()

    # Automatically start the watchdog and broadcast loop task at server startup
    if _broadcast_loop_task is None or _broadcast_loop_task.done():
        try:
            loop = asyncio.get_running_loop()
            _broadcast_loop_task = loop.create_task(_broadcast_loop())
            logger.info("Watchdog broadcast loop started successfully at startup.")
        except RuntimeError:
            pass


def stop_angel_upstream():
    """Gracefully shutdown the Angel One WebSocket. Called at FastAPI shutdown."""
    global _angel_running, _angel_sws
    _angel_running = False
    if _angel_sws:
        try:
            _angel_sws.close_connection()
        except Exception:
            pass
    logger.info("Angel One upstream WebSocket stopped.")


def get_feed_status() -> Dict[str, Any]:
    """Returns the current status of the Angel One WebSocket feed."""
    return {
        "feed_active": _angel_running and _angel_thread is not None and _angel_thread.is_alive(),
        "subscribed_tokens": len(_subscribed_tokens),
        "tick_store_symbols": tick_store.count,
        "last_tick_time": datetime.fromtimestamp(tick_store.last_update_time).isoformat() if tick_store.last_update_time else None,
        "connected_clients": connection_manager.client_count,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FastAPI WebSocket Router — Browser Downstream
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

angel_ws_router = APIRouter()


async def fetch_yfinance_ticks(symbols: List[str]) -> Dict[str, Dict]:
    """
    Helper to fetch quotes from yfinance in the background.
    Returns Dict[symbol, tick_data_dict].
    """
    if not symbols:
        return {}
    try:
        import yfinance as yf
        import pandas as pd
        df = await asyncio.to_thread(
            yf.download,
            symbols,
            period="1mo",
            interval="1d",
            progress=False,
            threads=True
        )
        ticks = {}
        if not df.empty:
            is_multi = isinstance(df.columns, pd.MultiIndex)
            for sym in symbols:
                try:
                    if is_multi:
                        if sym not in df.columns.get_level_values(1):
                            continue
                        close_series = df['Close'][sym].dropna()
                        high_series = df['High'][sym].dropna()
                        low_series = df['Low'][sym].dropna()
                        volume_series = df['Volume'][sym].dropna() if 'Volume' in df.columns.get_level_values(0) else pd.Series()
                    else:
                        close_series = df['Close'].dropna()
                        high_series = df['High'].dropna()
                        low_series = df['Low'].dropna()
                        volume_series = df['Volume'].dropna() if 'Volume' in df.columns else pd.Series()
                    
                    if len(close_series) >= 1:
                        price = float(close_series.iloc[-1])
                        prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else None
                        if prev_close is None or abs(price - prev_close) < 1e-6:
                            try:
                                fi_prev = yf.Ticker(sym).fast_info.get('previousClose')
                                if fi_prev and not pd.isna(fi_prev) and float(fi_prev) > 0:
                                    prev_close = float(fi_prev)
                            except Exception:
                                pass
                        if prev_close is None:
                            prev_close = price
                        change = price - prev_close
                        change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0
                        high = float(high_series.iloc[-1]) if len(high_series) >= 1 else price
                        low = float(low_series.iloc[-1]) if len(low_series) >= 1 else price
                        volume = int(volume_series.iloc[-1]) if len(volume_series) >= 1 else 0
                        
                        ticks[sym] = {
                            "price": round(price, 2),
                            "change": round(change, 2),
                            "change_pct": round(change_pct, 2),
                            "high": round(high, 2),
                            "low": round(low, 2),
                            "volume": volume,
                            "timestamp": time.time(),
                        }
                except Exception as e:
                    logger.debug(f"Error parsing yfinance tick for {sym}: {e}")
        return ticks
    except Exception as e:
        logger.error(f"Error fetching yfinance ticks: {e}")
        return {}


_last_fallback_poll_time = 0.0


async def _broadcast_loop():
    """
    Async loop that runs every 1 second, broadcasting tick updates
    and alert triggers to all connected browser clients.
    Also acts as a watchdog to auto-recover dead upstream connections.
    """
    global _last_watchdog_time, _last_fallback_poll_time
    while True:
        try:
            await asyncio.sleep(1)

            # Watchdog check: Auto-recover if upstream connection thread is dead
            now = time.time()
            if _angel_running and _angel_connector and (now - _last_watchdog_time > 3.0):
                _last_watchdog_time = now
                is_alive = _angel_thread is not None and _angel_thread.is_alive()
                if not is_alive:
                    logger.warning("Watchdog: Angel One upstream thread is dead. Re-initializing...")
                    await asyncio.to_thread(_recover_upstream_connection)

            # Run yfinance poll for indices and fallback for active subscriptions
            if now - _last_fallback_poll_time > 3.0:
                _last_fallback_poll_time = now
                
                symbols_to_fetch = set()
                # Always fetch index tickers
                indices = ["^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^CNXINFRA", "^CNXAUTO", "GC=F", "SI=F", "INR=X"]
                symbols_to_fetch.update(indices)
                
                # If Angel One is not authenticated or not active, fetch active subscriptions as fallback
                is_angel_active = (
                    _angel_connector 
                    and _angel_connector.is_authenticated() 
                    and _angel_thread is not None 
                    and _angel_thread.is_alive()
                )
                
                if not is_angel_active:
                    all_subs = connection_manager.get_all_subscribed_symbols()
                    for s in all_subs:
                        if s in ["MCXGOLD", "MCXSILVER", "SPOTGOLD", "SPOTSILVER", "PLATINUM"]:
                            continue
                        if '.' not in s and not s.startswith('^'):
                            symbols_to_fetch.add(f"{s}.NS")
                        else:
                            symbols_to_fetch.add(s)
                            
                if symbols_to_fetch:
                    yf_ticks = await fetch_yfinance_ticks(list(symbols_to_fetch))
                    for yf_sym, tick in yf_ticks.items():
                        tick_store.update(yf_sym, tick)
                        # Also map base symbol (e.g. TCS) for clients subscribing to plain ticker
                        base_sym = yf_sym.replace(".NS", "").replace(".BO", "")
                        tick_store.update(base_sym, tick)

                    # Calculate Gold and Silver Futures in INR (including 15% cumulative import duty: 10% BCD + 5% AIDC)
                    if "GC=F" in yf_ticks and "INR=X" in yf_ticks:
                        gc = yf_ticks["GC=F"]
                        inr = yf_ticks["INR=X"]
                        gold_fut_price = (gc["price"] * inr["price"]) / 31.1034768 * 10 * 1.15
                        gold_fut_change = (gc["change"] * inr["price"]) / 31.1034768 * 10 * 1.15
                        tick_store.update("MCXGOLD", {
                            "price": round(gold_fut_price, 2),
                            "change": round(gold_fut_change, 2),
                            "change_pct": gc["change_pct"],
                            "high": round((gc["high"] * inr["price"]) / 31.1034768 * 10 * 1.15, 2),
                            "low": round((gc["low"] * inr["price"]) / 31.1034768 * 10 * 1.15, 2),
                            "volume": gc["volume"],
                            "timestamp": time.time()
                        })

                    if "SI=F" in yf_ticks and "INR=X" in yf_ticks:
                        si = yf_ticks["SI=F"]
                        inr = yf_ticks["INR=X"]
                        silver_fut_price = (si["price"] * inr["price"]) / 31.1034768 * 1000 * 1.15
                        silver_fut_change = (si["change"] * inr["price"]) / 31.1034768 * 1000 * 1.15
                        tick_store.update("MCXSILVER", {
                            "price": round(silver_fut_price, 2),
                            "change": round(silver_fut_change, 2),
                            "change_pct": si["change_pct"],
                            "high": round((si["high"] * inr["price"]) / 31.1034768 * 1000 * 1.15, 2),
                            "low": round((si["low"] * inr["price"]) / 31.1034768 * 1000 * 1.15, 2),
                            "volume": si["volume"],
                            "timestamp": time.time()
                        })

                # Get latest scraped Gold, Silver and Platinum spot prices
                from backend.commodity_scraper import CommodityScraper
                try:
                    spots = await CommodityScraper.get_prices()
                    if "gold_24k" in spots:
                        g24 = spots["gold_24k"]
                        tick_store.update("SPOTGOLD", {
                            "price": g24["price"],
                            "change": g24["change"],
                            "change_pct": g24["change_pct"],
                            "high": g24["price"],
                            "low": g24["price"],
                            "volume": 0,
                            "timestamp": time.time()
                        })
                    if "silver_1kg" in spots:
                        sil = spots["silver_1kg"]
                        tick_store.update("SPOTSILVER", {
                            "price": sil["price"],
                            "change": sil["change"],
                            "change_pct": sil["change_pct"],
                            "high": sil["price"],
                            "low": sil["price"],
                            "volume": 0,
                            "timestamp": time.time()
                        })
                    if "platinum_10g" in spots:
                        plat = spots["platinum_10g"]
                        tick_store.update("PLATINUM", {
                            "price": plat["price"],
                            "change": plat["change"],
                            "change_pct": plat["change_pct"],
                            "high": plat["price"],
                            "low": plat["price"],
                            "volume": 0,
                            "timestamp": time.time()
                        })
                except Exception as scrap_err:
                    logger.error(f"Error updating commodity ticks: {scrap_err}")

            if connection_manager.client_count == 0:
                continue

            # 1. Broadcast tick updates
            all_symbols = connection_manager.get_all_subscribed_symbols()
            if all_symbols:
                ticks = tick_store.get_batch(list(all_symbols))
                if ticks:
                    is_angel_active = (
                        _angel_connector 
                        and _angel_connector.is_authenticated() 
                        and _angel_thread is not None 
                        and _angel_thread.is_alive()
                    )
                    current_source = "angel" if is_angel_active else "yfinance_fallback"
                    await connection_manager.broadcast_ticks(ticks, source=current_source)

            # 2. Broadcast any triggered alerts
            if alert_evaluator:
                triggered = alert_evaluator.pop_triggered_queue()
                for alert_data in triggered:
                    await connection_manager.broadcast_alert(alert_data)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")


@angel_ws_router.websocket("/ws/live-ticks")
async def websocket_live_ticks(websocket: WebSocket):
    """
    Browser WebSocket endpoint for live tick streaming.

    Client messages:
      {"action": "subscribe", "symbols": ["TCS", "RELIANCE", ...]}
      {"action": "unsubscribe", "symbols": ["TCS"]}
    
    Server messages:
      {"type": "ticks", "data": {"TCS": {price, change, ...}, ...}}
      {"type": "alert_triggered", "alert": {...}}
    """
    global _broadcast_loop_task

    await connection_manager.connect(websocket)

    # Start broadcast loop if not running
    if _broadcast_loop_task is None or _broadcast_loop_task.done():
        _broadcast_loop_task = asyncio.create_task(_broadcast_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action", "")
                symbols = msg.get("symbols", [])

                if action == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})

                elif action == "subscribe" and symbols:
                    await connection_manager.subscribe(websocket, symbols)
                    # Also subscribe on Angel One upstream if not already
                    new_symbols = [s for s in symbols if not tick_store.get(s.upper())]
                    if new_symbols and _angel_sws:
                        subscribe_symbols(new_symbols)
                    logger.info(f"Client subscribed to {len(symbols)} symbols")
                    # Immediately send any cached ticks for the subscribed symbols
                    cached_ticks = tick_store.get_batch(symbols)
                    # Also send indices immediately
                    indices = ["^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^CNXINFRA", "^CNXAUTO"]
                    cached_indices = tick_store.get_batch(indices)
                    if cached_indices:
                        cached_ticks.update(cached_indices)
                    if cached_ticks:
                        await websocket.send_json({"type": "ticks", "data": cached_ticks})

                elif action == "unsubscribe" and symbols:
                    await connection_manager.unsubscribe(websocket, symbols)
                    logger.info(f"Client unsubscribed from {len(symbols)} symbols")

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket endpoint error: {e}")
        await connection_manager.disconnect(websocket)
