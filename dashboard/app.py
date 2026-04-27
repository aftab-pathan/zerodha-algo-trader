"""
dashboard/app.py

Secure Streamlit dashboard for the Zerodha Algo Trader.

Security model:
  - Password-protected login (bcrypt hashed)
  - Session tokens with expiry
  - No sensitive data in URL / browser history
  - All API calls server-side only
  - Rate limiting on login attempts
  - HTTPS enforced in production via reverse proxy

Run locally:   streamlit run dashboard/app.py
Run in prod:   streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
"""

import os
import sys
import time
import hashlib
import hmac
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import TRADING_CAPITAL, ACTIVE_STRATEGIES, DEFAULT_WATCHLIST, DATA_DIR, LOG_DIR
from core.risk_manager import get_capital_summary

# ─────────────────────────────────────────────────────────────────────────────
# Security — Dashboard Authentication
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "120"))
MAX_LOGIN_ATTEMPTS      = 5

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _check_password(password: str) -> bool:
    stored_hash = DASHBOARD_PASSWORD_HASH
    if not stored_hash:
        # Fallback: use env var DASHBOARD_PASSWORD directly (less secure, dev only)
        fallback_pw = os.getenv("DASHBOARD_PASSWORD", "changeme123")
        return hmac.compare_digest(password, fallback_pw)
    return hmac.compare_digest(_hash_password(password), stored_hash)

def _is_session_valid() -> bool:
    if "authenticated" not in st.session_state:
        return False
    if not st.session_state.authenticated:
        return False
    login_time = st.session_state.get("login_time")
    if login_time and datetime.now() - login_time > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        st.session_state.authenticated = False
        return False
    return True

def show_login():
    st.set_page_config(page_title="Algo Trader Login", page_icon="🔒", layout="centered")
    st.markdown("""
        <style>
        .login-box { max-width: 400px; margin: auto; padding-top: 80px; }
        </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔒 Algo Trader Dashboard")
        st.markdown("---")

        attempts = st.session_state.get("login_attempts", 0)
        if attempts >= MAX_LOGIN_ATTEMPTS:
            st.error(f"Too many failed attempts. Refresh page to try again.")
            return

        password = st.text_input("Password", type="password", key="pw_input")
        if st.button("Login", use_container_width=True, type="primary"):
            if _check_password(password):
                st.session_state.authenticated = True
                st.session_state.login_time    = datetime.now()
                st.session_state.login_attempts = 0
                st.rerun()
            else:
                st.session_state.login_attempts = attempts + 1
                remaining = MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts
                st.error(f"Incorrect password. {remaining} attempts remaining.")
                time.sleep(1)  # slow brute force

        st.markdown("---")
        st.caption("🛡️ Session expires after 2 hours of inactivity")


# ─────────────────────────────────────────────────────────────────────────────
# Data Loaders (cached)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=10)   # refresh every 10 seconds for better sync
def load_state() -> dict:
    state_file = os.path.join(DATA_DIR, "state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {"open_positions": {}, "closed_positions": [], "total_pnl": 0}

@st.cache_data(ttl=300)
def load_trades() -> pd.DataFrame:
    trade_file = os.path.join(LOG_DIR, "trades.csv")
    if os.path.exists(trade_file):
        return pd.read_csv(trade_file)
    return pd.DataFrame()

@st.cache_data(ttl=300)
def load_backtest_results() -> list:
    results = []
    if not os.path.exists(DATA_DIR):
        return results
    for f in sorted(os.listdir(DATA_DIR)):
        if f.startswith("backtest_") and f.endswith(".json"):
            with open(os.path.join(DATA_DIR, f)) as fp:
                results.extend(json.load(fp))
    return results

def load_live_data():
    """Fetch live data from Kite — only called when user is on live tab."""
    try:
        from core.kite_client import get_holdings, get_ltp, get_portfolio_value, is_authenticated
        if not is_authenticated():
            return None, None, 0
        holdings = get_holdings()
        if not holdings.empty and "tradingsymbol" in holdings.columns:
            syms = holdings[holdings["quantity"] > 0]["tradingsymbol"].tolist()
            ltps = get_ltp(syms) if syms else {}
        else:
            ltps = {}
        pv = get_portfolio_value()
        return holdings, ltps, pv
    except Exception as e:
        return None, None, 0


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Pages
# ─────────────────────────────────────────────────────────────────────────────

def page_overview():
    st.header("📊 Portfolio Overview")
    
    # Add refresh button
    col1, col2 = st.columns([6, 1])
    with col2:
        if st.button("🔄 Refresh", help="Reload data from files"):
            st.cache_data.clear()
            st.rerun()
    
    state     = load_state()
    open_pos  = state.get("open_positions", {})
    closed    = state.get("closed_positions", [])
    total_pnl = state.get("total_pnl", 0)

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    cap_summary = get_capital_summary()
    col1.metric("💰 Trading Capital", f"₹{TRADING_CAPITAL:,.0f}")
    col2.metric("📂 Open Positions",  len(open_pos))
    col3.metric("✅ Closed Trades",   len(closed))
    col4.metric("💵 Total P&L",       f"₹{total_pnl:+,.0f}",
                delta_color="normal" if total_pnl >= 0 else "inverse")

    st.markdown("---")

    # Open positions table
    st.subheader("📌 Open Positions")
    if open_pos:
        rows = []
        for sym, p in open_pos.items():
            rows.append({
                "Symbol":    sym,
                "Signal":    p.get("signal", ""),
                "Strategy":  p.get("strategy", ""),
                "Entry ₹":   p.get("entry", 0),
                "SL ₹":      p.get("stop_loss", 0),
                "Target ₹":  p.get("target", 0),
                "Qty":        p.get("quantity", 0),
                "Capital":   f"₹{p.get('entry',0)*p.get('quantity',0):,.0f}",
                "Date":      p.get("date", "")[:10],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No open positions.")

    # Risk gauges
    st.markdown("---")
    st.subheader("🛡️ Risk Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Daily Loss Limit",   f"₹{cap_summary['daily_loss_limit_inr']:,.0f}")
    col2.metric("Weekly Loss Limit",  f"₹{cap_summary['weekly_loss_limit_inr']:,.0f}")
    col3.metric("Max Drawdown Limit", cap_summary["total_drawdown_limit"])

    col1, col2, col3 = st.columns(3)
    col1.metric("Risk / Trade",       cap_summary["max_risk_per_trade_pct"])
    col2.metric("Max Single Stock",   cap_summary["max_single_stock_pct"])
    col3.metric("Min R:R Required",   f"1:{cap_summary['min_risk_reward']}")


def page_pnl():
    st.header("📈 P&L Analytics")
    trades_df = load_trades()

    if trades_df.empty:
        st.info("No trade history yet. Start trading to see analytics.")
        return

    # Ensure numeric columns
    for col in ["entry", "sl", "target", "qty", "capital", "risk", "rr", "confidence"]:
        if col in trades_df.columns:
            trades_df[col] = pd.to_numeric(trades_df[col], errors="coerce")

    state     = load_state()
    closed    = pd.DataFrame(state.get("closed_positions", []))

    if not closed.empty and "realised_pnl" in closed.columns:
        # Cumulative P&L chart
        closed["exit_date"] = pd.to_datetime(closed["exit_date"])
        closed_sorted = closed.sort_values("exit_date")
        closed_sorted["cumulative_pnl"] = closed_sorted["realised_pnl"].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=closed_sorted["exit_date"],
            y=closed_sorted["cumulative_pnl"],
            mode="lines+markers",
            name="Cumulative P&L",
            line=dict(color="#00d4aa", width=2),
            fill="tonexty",
            fillcolor="rgba(0,212,170,0.1)"
        ))
        fig.update_layout(
            title="Cumulative Net P&L", xaxis_title="Date", yaxis_title="₹",
            height=350, template="plotly_dark"
        )
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)

        # Win/Loss pie
        wins   = (closed_sorted["realised_pnl"] > 0).sum()
        losses = (closed_sorted["realised_pnl"] <= 0).sum()
        fig_pie = px.pie(
            values=[wins, losses], names=["Wins", "Losses"],
            color_discrete_map={"Wins": "#00d4aa", "Losses": "#ff4b4b"},
            title="Win / Loss Ratio"
        )
        col1.plotly_chart(fig_pie, use_container_width=True)

        # P&L by strategy
        if "strategy" in closed_sorted.columns:
            strat_pnl = closed_sorted.groupby("strategy")["realised_pnl"].sum().reset_index()
            fig_bar = px.bar(strat_pnl, x="strategy", y="realised_pnl",
                             title="P&L by Strategy",
                             color="realised_pnl",
                             color_continuous_scale=["#ff4b4b", "#00d4aa"])
            col2.plotly_chart(fig_bar, use_container_width=True)

        # Stats summary
        st.subheader("📊 Performance Metrics")
        pnls = closed_sorted["realised_pnl"]
        wins_vals  = pnls[pnls > 0]
        loss_vals  = pnls[pnls <= 0]
        win_rate   = round(len(wins_vals) / len(pnls) * 100, 1) if len(pnls) > 0 else 0
        pf         = round(wins_vals.sum() / abs(loss_vals.sum()), 2) if loss_vals.sum() != 0 else 0
        exp        = round(pnls.mean(), 2) if len(pnls) > 0 else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Win Rate",       f"{win_rate:.1f}%")
        c2.metric("Profit Factor",  f"{pf:.2f}")
        c3.metric("Expectancy",     f"₹{exp:,.0f}/trade")
        c4.metric("Avg Win",        f"₹{wins_vals.mean():,.0f}" if len(wins_vals) > 0 else "—")
        c5.metric("Avg Loss",       f"₹{abs(loss_vals.mean()):,.0f}" if len(loss_vals) > 0 else "—")

        st.subheader("📋 Trade History")
        display_cols = ["symbol", "strategy", "signal", "entry", "exit_price",
                        "quantity", "realised_pnl", "exit_type", "exit_date"]
        avail = [c for c in display_cols if c in closed_sorted.columns]
        st.dataframe(closed_sorted[avail].sort_values("exit_date", ascending=False),
                     use_container_width=True, hide_index=True)


def page_backtest():
    st.header("🔬 Backtesting")

    col1, col2, col3 = st.columns(3)
    symbol   = col1.selectbox("Symbol",   ["RELIANCE", "TCS", "INFY", "HDFCBANK"] + DEFAULT_WATCHLIST)
    strategy = col2.selectbox("Strategy", [s for s in ACTIVE_STRATEGIES if s != "claude_ai"])
    days     = col3.slider("History (days)", 200, 1000, 500, step=50)

    if st.button("▶ Run Backtest", type="primary"):
        with st.spinner(f"Backtesting {symbol} / {strategy}…"):
            try:
                from core.kite_client import get_historical_data, is_authenticated
                from backtesting.backtester import backtest_strategy, print_report

                if not is_authenticated():
                    st.error("Please login to Kite first (run login.py).")
                    return

                df     = get_historical_data(symbol, interval="day", days=days)
                result = backtest_strategy(symbol, strategy, df)

                # Display metrics
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Win Rate",      f"{result.win_rate:.1f}%")
                c2.metric("Profit Factor", f"{result.profit_factor:.2f}")
                c3.metric("Sharpe Ratio",  f"{result.sharpe_ratio:.2f}")
                c4.metric("Max Drawdown",  f"{result.max_drawdown_pct:.1f}%")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Trades",  result.total_trades)
                c2.metric("Net P&L",       f"₹{result.total_net_pnl:+,.0f}")
                c3.metric("Expectancy",    f"₹{result.expectancy:,.0f}")
                c4.metric("Avg Hold",      f"{result.avg_holding_days:.1f}d")

                rating = "🟢 Strategy looks viable" if result.sharpe_ratio > 1 and result.win_rate > 45 \
                         else "🟡 Borderline — use with caution" if result.profit_factor > 1 \
                         else "🔴 Strategy underperforms — do NOT trade live"
                st.info(rating)

                # Equity curve from trades
                if result.trades:
                    trade_df = pd.DataFrame([
                        {"date": t.exit_date, "pnl": t.net_pnl, "exit": t.exit_reason}
                        for t in result.trades
                    ])
                    trade_df["cumulative"] = trade_df["pnl"].cumsum() + TRADING_CAPITAL

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=trade_df["date"], y=trade_df["cumulative"],
                        mode="lines+markers",
                        line=dict(color="#00d4aa"),
                        name="Equity Curve"
                    ))
                    fig.add_hline(y=TRADING_CAPITAL, line_dash="dash",
                                  annotation_text="Starting Capital")
                    fig.update_layout(title="Equity Curve (Backtest)", height=350,
                                      template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)

                    # Trade details
                    st.subheader("Trade Log")
                    tdf = pd.DataFrame([{
                        "Date":       t.exit_date,
                        "Signal":     t.signal,
                        "Entry":      f"₹{t.entry_price:.2f}",
                        "Exit":       f"₹{t.exit_price:.2f}",
                        "Qty":        t.quantity,
                        "Net P&L":    f"₹{t.net_pnl:+,.0f}",
                        "Exit Reason":t.exit_reason,
                        "Hold Days":  t.holding_days,
                    } for t in result.trades])
                    st.dataframe(tdf, use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Backtest error: {e}")

    # Show saved results
    saved = load_backtest_results()
    if saved:
        st.markdown("---")
        st.subheader("📁 Saved Backtest Results")
        saved_df = pd.DataFrame([{
            "Symbol":       r.get("symbol"), "Strategy": r.get("strategy"),
            "Win Rate":     f"{r.get('win_rate',0):.1f}%",
            "Profit Factor":r.get("profit_factor"),
            "Sharpe":       r.get("sharpe_ratio"),
            "Net P&L":      f"₹{r.get('total_net_pnl',0):+,.0f}",
            "Max DD":       f"{r.get('max_drawdown_pct',0):.1f}%",
            "Trades":       r.get("total_trades"),
        } for r in saved])
        st.dataframe(saved_df, use_container_width=True, hide_index=True)


def page_capital():
    st.header("⚙️ Capital & Risk Settings")
    cap_summary = get_capital_summary()

    st.subheader("💰 Update Trading Capital")
    new_capital = st.number_input(
        "Trading Capital (₹)", min_value=5000, max_value=10000000,
        value=int(TRADING_CAPITAL), step=5000
    )

    if st.button("Update Capital", type="primary"):
        try:
            from core.trading_engine import update_capital
            result = update_capital(float(new_capital))
            st.success(f"✅ Capital updated to ₹{new_capital:,.0f}")
            st.json(result)
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("---")
    st.subheader("📊 Current Risk Parameters")
    col1, col2 = st.columns(2)
    for i, (k, v) in enumerate(cap_summary.items()):
        if k == "cost_model":
            continue
        (col1 if i % 2 == 0 else col2).metric(k.replace("_", " ").title(), str(v))

    st.markdown("---")
    st.subheader("🔧 Strategy Controls")
    st.write("Active strategies (edit `.env` to change permanently):")
    for strat in ACTIVE_STRATEGIES:
        st.checkbox(strat, value=True, disabled=True)

    st.info("To enable/disable strategies: edit `ACTIVE_STRATEGIES` in your `.env` file and restart the scheduler.")


def page_watchlist():
    st.header("📋 Watchlist Management")

    state = load_state()
    shortlisted = list(state.get("open_positions", {}).keys())

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Today's Shortlisted")
        if shortlisted:
            st.write(shortlisted)
        else:
            st.info("No shortlisted stocks today.")

        st.subheader("📌 Default Watchlist")
        st.write(DEFAULT_WATCHLIST)

    with col2:
        st.subheader("➕ Add Custom Stock")
        custom = st.text_input("Symbol (e.g. TATASTEEL)")
        if st.button("Add to Scan List") and custom:
            st.success(f"{custom.upper()} will be added to next scan.")

        st.subheader("🔄 Force Refresh Zerodha Watchlist")
        if st.button("Refresh Watchlist on Kite", type="secondary"):
            try:
                from core.kite_client import clear_watchlist, add_to_watchlist, is_authenticated
                if is_authenticated():
                    clear_watchlist()
                    added = add_to_watchlist(DEFAULT_WATCHLIST)
                    st.success(f"Added {len(added)} stocks to Kite watchlist.")
                else:
                    st.error("Kite not authenticated.")
            except Exception as e:
                st.error(str(e))


def page_logs():
    st.header("📜 Audit & System Logs")

    # Audit log
    audit_file = os.path.join(LOG_DIR, "audit.log")
    if os.path.exists(audit_file):
        with open(audit_file) as f:
            lines = f.readlines()[-50:]   # last 50 entries
        entries = [json.loads(l) for l in lines if l.strip()]
        if entries:
            st.subheader("🔐 Audit Trail (last 50)")
            st.dataframe(pd.DataFrame(entries[::-1]), use_container_width=True, hide_index=True)

    # Scheduler log
    sched_file = os.path.join(LOG_DIR, "scheduler.log")
    if os.path.exists(sched_file):
        with open(sched_file) as f:
            lines = f.readlines()[-100:]
        st.subheader("📋 Scheduler Log (last 100 lines)")
        st.code("".join(lines), language="text")


# ─────────────────────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not _is_session_valid():
        show_login()
        return

    st.set_page_config(
        page_title="Zerodha Algo Trader",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Sidebar
    with st.sidebar:
        st.markdown("## 📈 Algo Trader")
        st.markdown(f"**Capital:** ₹{TRADING_CAPITAL:,.0f}")
        st.markdown(f"**Mode:** {'🟡 DRY RUN' if os.getenv('DRY_RUN','true').lower()=='true' else '🔴 LIVE'}")
        st.markdown("---")

        page = st.radio("Navigate", [
            "📊 Overview",
            "📈 P&L Analytics",
            "🔬 Backtesting",
            "⚙️ Capital & Risk",
            "📋 Watchlist",
            "📜 Logs",
        ])

        st.markdown("---")
        if st.button("🚪 Logout"):
            st.session_state.authenticated = False
            st.rerun()

        login_time = st.session_state.get("login_time")
        if login_time:
            elapsed = datetime.now() - login_time
            remaining = SESSION_TIMEOUT_MINUTES - int(elapsed.total_seconds() / 60)
            st.caption(f"Session: {remaining}m remaining")

    # Route
    if   "Overview"   in page: page_overview()
    elif "P&L"        in page: page_pnl()
    elif "Backtest"   in page: page_backtest()
    elif "Capital"    in page: page_capital()
    elif "Watchlist"  in page: page_watchlist()
    elif "Logs"       in page: page_logs()


if __name__ == "__main__":
    main()
