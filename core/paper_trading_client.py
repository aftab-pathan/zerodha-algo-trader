"""
core/paper_trading_client.py

Paper Trading Client - Simulates Kite Connect API for testing strategies
without real capital. Mimics KiteConnect interface for drop-in replacement.

Features:
- Simulated order placement with configurable slippage
- Realistic order fills with time delays
- Paper positions and holdings tracking
- P&L calculation
- GTT (Good Till Triggered) simulation

Note: Paper trading still requires Zerodha authentication to fetch real market data.
"""

import os
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from config.config import DATA_DIR, KITE_API_KEY, KITE_API_SECRET

logger = logging.getLogger(__name__)


class PaperTradingClient:
    """
    Paper trading simulator that mimics KiteConnect interface.
    All orders are simulated - no real trades placed.
    
    Maintains a real KiteConnect client internally for market data access.
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or KITE_API_KEY
        self.access_token = None
        
        # Real KiteConnect client for market data (lazy-loaded)
        self._real_kite = None
        
        # Paper trading state stored in memory and persisted to file
        self.paper_state_file = os.path.join(DATA_DIR, "paper_state.json")
        self.state = self._load_state()
        
        # Configuration
        self.slippage_pct = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.002"))  # 0.2% default
        self.fill_delay_seconds = int(os.getenv("PAPER_FILL_DELAY", "3"))  # 3 seconds default
        
        logger.info(f"[PAPER MODE] Initialized with slippage={self.slippage_pct*100}%, fill_delay={self.fill_delay_seconds}s")
    
    def _load_state(self) -> Dict:
        """Load paper trading state from file"""
        if os.path.exists(self.paper_state_file):
            try:
                with open(self.paper_state_file, 'r') as f:
                    state = json.load(f)
                logger.info(f"[PAPER MODE] Loaded state: {len(state.get('open_positions', {}))} open positions")
                return state
            except Exception as e:
                logger.error(f"[PAPER MODE] Error loading state: {e}")
        
        # Default state structure
        return {
            "open_positions": {},      # symbol -> position_data
            "pending_orders": {},      # symbol -> order_data
            "closed_positions": [],    # list of completed trades
            "orders": {},              # order_id -> order_data
            "gtt_orders": {},          # gtt_id -> gtt_data
            "total_pnl": 0.0,
            "paper_capital": float(os.getenv("PAPER_TRADING_CAPITAL", "50000")),
            "last_sync": None,
            "order_counter": 1000,     # for generating order IDs
            "gtt_counter": 5000        # for generating GTT IDs
        }
    
    def _save_state(self):
        """Persist paper trading state to file"""
        try:
            self.state["last_sync"] = datetime.now().isoformat()
            with open(self.paper_state_file, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[PAPER MODE] Error saving state: {e}")
    
    def _generate_order_id(self) -> str:
        """Generate unique order ID"""
        self.state["order_counter"] += 1
        return f"PAPER{self.state['order_counter']}"
    
    def _generate_gtt_id(self) -> str:
        """Generate unique GTT ID"""
        self.state["gtt_counter"] += 1
        return f"GTT{self.state['gtt_counter']}"
    
    def _get_real_kite(self):
        """Get or create real KiteConnect client for market data"""
        if self._real_kite is None:
            from kiteconnect import KiteConnect
            self._real_kite = KiteConnect(api_key=self.api_key)
            if self.access_token:
                self._real_kite.set_access_token(self.access_token)
        return self._real_kite
    
    def login_url(self) -> str:
        """Get Zerodha login URL (delegates to real client for market data access)"""
        return self._get_real_kite().login_url()
    
    def generate_session(self, request_token: str, api_secret: str) -> Dict:
        """Generate session (delegates to real client for market data access)"""
        data = self._get_real_kite().generate_session(request_token, api_secret=api_secret)
        self.access_token = data["access_token"]
        self._get_real_kite().set_access_token(self.access_token)
        logger.info("[PAPER MODE] Authenticated for market data access (orders still simulated)")
        return data
    
    def set_access_token(self, access_token: str):
        """Set access token for both paper and real client"""
        self.access_token = access_token
        if self._real_kite:
            self._real_kite.set_access_token(access_token)
        logger.info("[PAPER MODE] Access token set (simulated orders, real market data)")
    
    def profile(self) -> Dict:
        """Return simulated user profile"""
        return {
            "user_id": "PAPER_USER",
            "user_name": "Paper Trading Account",
            "email": "paper@trading.local",
            "broker": "PAPER"
        }
    
    def holdings(self) -> List[Dict]:
        """Return current paper holdings"""
        holdings = []
        for symbol, pos in self.state["open_positions"].items():
            holdings.append({
                "tradingsymbol": symbol,
                "quantity": pos["quantity"],
                "average_price": pos["entry"],
                "last_price": pos.get("current_price", pos["entry"]),
                "pnl": pos.get("unrealised_pnl", 0.0),
                "product": "CNC"
            })
        return holdings
    
    def positions(self) -> Dict:
        """Return paper positions in Kite format"""
        net_positions = []
        for symbol, pos in self.state["open_positions"].items():
            net_positions.append({
                "tradingsymbol": symbol,
                "quantity": pos["quantity"],
                "average_price": pos["entry"],
                "last_price": pos.get("current_price", pos["entry"]),
                "pnl": pos.get("unrealised_pnl", 0.0),
                "product": "CNC",
                "exchange": "NSE"
            })
        return {"net": net_positions}
    
    def orders(self) -> List[Dict]:
        """Return all paper orders"""
        return list(self.state["orders"].values())
    
    def place_order(
        self,
        variety: str,
        exchange: str,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str,
        price: Optional[float] = None,
        validity: Optional[str] = None,
        trigger_price: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        Simulate order placement with slippage.
        Returns order_id immediately, order will be "filled" after delay.
        """
        order_id = self._generate_order_id()
        
        # Apply slippage to simulate real market conditions
        if order_type == "LIMIT" and price:
            if transaction_type == "BUY":
                fill_price = price * (1 + self.slippage_pct)  # Buy higher
            else:
                fill_price = price * (1 - self.slippage_pct)  # Sell lower
        elif order_type == "MARKET":
            # For market orders, use trigger price or assume current market price
            fill_price = price if price else 0.0
            if transaction_type == "BUY":
                fill_price = fill_price * (1 + self.slippage_pct * 2)  # More slippage on market orders
            else:
                fill_price = fill_price * (1 - self.slippage_pct * 2)
        else:
            fill_price = price if price else 0.0
        
        # Create order record
        order = {
            "order_id": order_id,
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "price": price,
            "fill_price": round(fill_price, 2),
            "order_type": order_type,
            "product": product,
            "status": "TRIGGER PENDING" if order_type == "LIMIT" else "OPEN",
            "status_message": "Paper order placed",
            "order_timestamp": datetime.now().isoformat(),
            "fill_timestamp": None,
            "variety": variety
        }
        
        self.state["orders"][order_id] = order
        
        # Add to pending orders for position tracking
        self.state["pending_orders"][tradingsymbol] = {
            "order_id": order_id,
            "price": fill_price,
            "quantity": quantity,
            "signal": transaction_type,
            "date": datetime.now().isoformat(),
            "fill_after": datetime.now() + timedelta(seconds=self.fill_delay_seconds)
        }
        
        self._save_state()
        
        logger.info(
            f"[PAPER MODE] Order placed: {transaction_type} {quantity} {tradingsymbol} "
            f"@ ₹{price} (fill @ ₹{fill_price} with {self.slippage_pct*100}% slippage) - Order ID: {order_id}"
        )
        
        return order_id
    
    def place_gtt(
        self,
        trigger_type: str,
        tradingsymbol: str,
        exchange: str,
        trigger_values: List[float],
        last_price: float,
        orders: List[Dict]
    ) -> str:
        """
        Simulate GTT (Good Till Triggered) order.
        For OCO (One Cancels Other): trigger_values = [stop_loss, target]
        """
        gtt_id = self._generate_gtt_id()
        
        gtt = {
            "id": gtt_id,
            "trigger_type": trigger_type,
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "trigger_values": trigger_values,
            "last_price": last_price,
            "orders": orders,
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "triggered_at": None,
            "trigger_price": None
        }
        
        self.state["gtt_orders"][gtt_id] = gtt
        self._save_state()
        
        logger.info(
            f"[PAPER MODE] GTT placed: {tradingsymbol} OCO @ SL={trigger_values[0]}, "
            f"Target={trigger_values[1]} - GTT ID: {gtt_id}"
        )
        
        return gtt_id
    
    def get_gtts(self) -> List[Dict]:
        """Return all GTT orders"""
        return list(self.state["gtt_orders"].values())
    
    def cancel_gtt(self, gtt_id: str) -> Dict:
        """Cancel a GTT order"""
        if gtt_id in self.state["gtt_orders"]:
            self.state["gtt_orders"][gtt_id]["status"] = "cancelled"
            self._save_state()
            logger.info(f"[PAPER MODE] GTT cancelled: {gtt_id}")
            return {"status": "success"}
        return {"status": "error", "message": "GTT not found"}
    
    def ltp(self, instruments: List[str]) -> Dict[str, Dict]:
        """
        Get last traded price. For paper trading, we need real market data.
        This is a pass-through to real Kite API since we need actual prices
        for paper trading simulation.
        """
        try:
            # Get real market data using internal real client
            return self._get_real_kite().ltp(instruments)
        except Exception as e:
            logger.error(f"[PAPER MODE] Error getting LTP: {e}")
            # Return dummy data if real API fails
            return {inst: {"last_price": 0.0} for inst in instruments}
    
    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False
    ) -> List[Dict]:
        """
        Get historical data. For paper trading, we need real market data.
        Pass-through to real Kite API.
        """
        try:
            return self._get_real_kite().historical_data(
                instrument_token, from_date, to_date, interval, continuous, oi
            )
        except Exception as e:
            logger.error(f"[PAPER MODE] Error getting historical data: {e}")
            return []
    
    def instruments(self, exchange: str = "NSE") -> List[Dict]:
        """Get instrument list - pass through to real API"""
        try:
            return self._get_real_kite().instruments(exchange)
        except Exception as e:
            logger.error(f"[PAPER MODE] Error getting instruments: {e}")
            return []
    
    def quote(self, instruments: List[str]) -> Dict:
        """Get market quotes - pass through to real API for live data"""
        try:
            return self._get_real_kite().quote(instruments)
        except Exception as e:
            logger.error(f"[PAPER MODE] Error getting quotes: {e}")
            return {}
    
    def get_paper_capital(self) -> float:
        """Get current paper trading capital"""
        return self.state["paper_capital"]
    
    def update_paper_capital(self, new_capital: float):
        """Update paper trading capital"""
        old_capital = self.state["paper_capital"]
        self.state["paper_capital"] = new_capital
        self._save_state()
        logger.info(f"[PAPER MODE] Capital updated: ₹{old_capital:,.2f} → ₹{new_capital:,.2f}")
    
    def reset_paper_state(self):
        """Reset all paper trading state (useful for testing)"""
        initial_capital = self.state["paper_capital"]
        self.state = self._load_state()
        self.state["paper_capital"] = initial_capital
        self._save_state()
        logger.warning("[PAPER MODE] State reset - all positions and P&L cleared")


# Convenience function for getting paper trading stats
def get_paper_stats() -> Dict:
    """Get paper trading statistics"""
    client = PaperTradingClient()
    state = client.state
    
    open_positions_count = len(state["open_positions"])
    closed_positions_count = len(state["closed_positions"])
    total_pnl = state["total_pnl"]
    capital = state["paper_capital"]
    
    # Calculate win rate
    if closed_positions_count > 0:
        winning_trades = sum(1 for pos in state["closed_positions"] if pos.get("realised_pnl", 0) > 0)
        win_rate = (winning_trades / closed_positions_count) * 100
    else:
        win_rate = 0.0
    
    return {
        "mode": "PAPER",
        "capital": capital,
        "open_positions": open_positions_count,
        "closed_positions": closed_positions_count,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "return_pct": (total_pnl / capital) * 100 if capital > 0 else 0.0
    }
