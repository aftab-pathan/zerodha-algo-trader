"""
strategies/strategies.py
Multiple pluggable swing trading strategies.
Each strategy returns: {"signal": "BUY"/"SELL"/"HOLD", "entry", "stop_loss",
                        "target", "confidence": 1-10, "reasoning": str, "strategy": str}
"""

import json
import logging
import numpy as np
import pandas as pd
import anthropic
from ta.momentum  import RSIIndicator
from ta.trend     import MACD, EMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume    import OnBalanceVolumeIndicator
from config.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MIN_CONFIDENCE

logger = logging.getLogger(__name__)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────────────────────────────────────
# Indicator Helper
# ─────────────────────────────────────────────────────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators needed by all strategies."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df["ema_9"]   = EMAIndicator(c, window=9).ema_indicator()
    df["ema_20"]  = EMAIndicator(c, window=20).ema_indicator()
    df["ema_50"]  = EMAIndicator(c, window=50).ema_indicator()
    df["ema_200"] = EMAIndicator(c, window=200).ema_indicator()

    rsi = RSIIndicator(c, window=14)
    df["rsi"] = rsi.rsi()

    macd_obj = MACD(c)
    df["macd"]        = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"]   = macd_obj.macd_diff()

    bb = BollingerBands(c, window=20, window_dev=2)
    df["bb_upper"]  = bb.bollinger_hband()
    df["bb_lower"]  = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_width"]  = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]

    atr = AverageTrueRange(h, l, c, window=14)
    df["atr"] = atr.average_true_range()

    adx_obj = ADXIndicator(h, l, c, window=14)
    df["adx"] = adx_obj.adx()

    df["obv"] = OnBalanceVolumeIndicator(c, v).on_balance_volume()

    # Volume ratio
    df["vol_ratio"] = v / v.rolling(20).mean()

    # 52-week high/low
    df["high_52w"] = h.rolling(252).max()
    df["low_52w"]  = l.rolling(252).min()

    return df.dropna()


def _atr_stops(df: pd.DataFrame, signal: str, atr_mult_sl: float = 2.0,
               atr_mult_tp: float = 4.0):
    """Compute ATR-based stop loss and target prices."""
    last  = df.iloc[-1]
    entry = round(last["close"], 2)
    atr   = last["atr"]
    if signal == "BUY":
        sl     = round(entry - atr * atr_mult_sl, 2)
        target = round(entry + atr * atr_mult_tp, 2)
    else:
        sl     = round(entry + atr * atr_mult_sl, 2)
        target = round(entry - atr * atr_mult_tp, 2)
    return entry, sl, target


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1 — EMA Crossover
# ─────────────────────────────────────────────────────────────────────────────

def strategy_ema_crossover(df: pd.DataFrame, symbol: str) -> dict:
    """
    EMA 9/20 crossover with EMA 50 trend filter.
    BUY: 9 crosses above 20, price > EMA50
    SELL: 9 crosses below 20, price < EMA50
    """
    try:
        last   = df.iloc[-1]
        prev   = df.iloc[-2]
        signal = "HOLD"
        confidence = 0

        golden_cross = (prev["ema_9"] < prev["ema_20"]) and (last["ema_9"] > last["ema_20"])
        death_cross  = (prev["ema_9"] > prev["ema_20"]) and (last["ema_9"] < last["ema_20"])
        above_ema50  = last["close"] > last["ema_50"]
        above_ema200 = last["close"] > last["ema_200"]
        strong_adx   = last["adx"] > 20

        if golden_cross and above_ema50:
            signal     = "BUY"
            confidence = 6 + (2 if above_ema200 else 0) + (1 if strong_adx else 0) + (1 if last["vol_ratio"] > 1.5 else 0)
        elif death_cross and not above_ema50:
            signal     = "SELL"
            confidence = 6 + (1 if strong_adx else 0) + (1 if last["vol_ratio"] > 1.5 else 0)

        entry, sl, target = _atr_stops(df, signal) if signal != "HOLD" else (last["close"], 0, 0)
        reasoning = (
            f"EMA9 {'crossed above' if signal == 'BUY' else 'crossed below'} EMA20. "
            f"Price {'above' if above_ema50 else 'below'} EMA50 (trend filter). "
            f"ADX={last['adx']:.1f}, Vol ratio={last['vol_ratio']:.1f}x."
        )

        return {"signal": signal, "entry": entry, "stop_loss": sl, "target": target,
                "confidence": min(confidence, 10), "reasoning": reasoning,
                "strategy": "EMA Crossover"}
    except Exception as e:
        logger.error(f"EMA Crossover error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2 — RSI Reversal
# ─────────────────────────────────────────────────────────────────────────────

def strategy_rsi_reversal(df: pd.DataFrame, symbol: str) -> dict:
    """
    RSI oversold/overbought with Bollinger Band confirmation.
    BUY: RSI < 35 + price near BB lower + RSI turning up
    SELL: RSI > 65 + price near BB upper + RSI turning down
    """
    try:
        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        signal     = "HOLD"
        confidence = 0

        rsi_turning_up   = last["rsi"] > prev["rsi"]
        rsi_turning_down = last["rsi"] < prev["rsi"]
        near_bb_lower    = last["close"] <= last["bb_lower"] * 1.01
        near_bb_upper    = last["close"] >= last["bb_upper"] * 0.99
        above_ema50      = last["close"] > last["ema_50"]

        if last["rsi"] < 35 and rsi_turning_up:
            signal     = "BUY"
            confidence = 6
            if near_bb_lower:  confidence += 2
            if above_ema50:    confidence += 1
            if last["rsi"] < 25: confidence += 1   # extreme oversold
        elif last["rsi"] > 65 and rsi_turning_down:
            signal     = "SELL"
            confidence = 6
            if near_bb_upper:  confidence += 2
            if not above_ema50: confidence += 1
            if last["rsi"] > 75: confidence += 1

        entry, sl, target = _atr_stops(df, signal, 1.5, 3.0) if signal != "HOLD" else (last["close"], 0, 0)
        reasoning = (
            f"RSI={last['rsi']:.1f} ({'oversold' if last['rsi'] < 35 else 'overbought'}, "
            f"turning {'up' if rsi_turning_up else 'down'}). "
            f"BB {'lower' if near_bb_lower else 'upper'} touch confirmed."
        )

        return {"signal": signal, "entry": entry, "stop_loss": sl, "target": target,
                "confidence": min(confidence, 10), "reasoning": reasoning,
                "strategy": "RSI Reversal"}
    except Exception as e:
        logger.error(f"RSI Reversal error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 3 — MACD Momentum
# ─────────────────────────────────────────────────────────────────────────────

def strategy_macd_momentum(df: pd.DataFrame, symbol: str) -> dict:
    """
    MACD histogram expansion with zero-line crossover.
    """
    try:
        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        prev2 = df.iloc[-3]
        signal     = "HOLD"
        confidence = 0

        bullish_crossover = (prev["macd"] < prev["macd_signal"]) and (last["macd"] > last["macd_signal"])
        bearish_crossover = (prev["macd"] > prev["macd_signal"]) and (last["macd"] < last["macd_signal"])
        hist_expanding_up = last["macd_hist"] > prev["macd_hist"] > prev2["macd_hist"]
        hist_expanding_dn = last["macd_hist"] < prev["macd_hist"] < prev2["macd_hist"]
        above_zero        = last["macd"] > 0
        above_ema50       = last["close"] > last["ema_50"]

        if bullish_crossover:
            signal     = "BUY"
            confidence = 6 + (2 if hist_expanding_up else 0) + (1 if above_zero else 0) + (1 if above_ema50 else 0)
        elif bearish_crossover:
            signal     = "SELL"
            confidence = 6 + (2 if hist_expanding_dn else 0) + (1 if not above_zero else 0)

        entry, sl, target = _atr_stops(df, signal) if signal != "HOLD" else (last["close"], 0, 0)
        reasoning = (
            f"MACD={'above' if last['macd'] > last['macd_signal'] else 'below'} signal. "
            f"Histogram={'expanding' if hist_expanding_up or hist_expanding_dn else 'contracting'}. "
            f"MACD {'above' if above_zero else 'below'} zero line."
        )

        return {"signal": signal, "entry": entry, "stop_loss": sl, "target": target,
                "confidence": min(confidence, 10), "reasoning": reasoning,
                "strategy": "MACD Momentum"}
    except Exception as e:
        logger.error(f"MACD Momentum error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 4 — Breakout
# ─────────────────────────────────────────────────────────────────────────────

def strategy_breakout(df: pd.DataFrame, symbol: str) -> dict:
    """
    Price breakout from 20-day consolidation range with volume surge.
    """
    try:
        last  = df.iloc[-1]
        recent = df.tail(20)
        signal     = "HOLD"
        confidence = 0

        # Consolidation: narrow Bollinger band (low volatility)
        narrow_band = last["bb_width"] < recent["bb_width"].mean() * 0.7

        resistance  = recent["high"].max()
        support     = recent["low"].min()
        vol_surge   = last["vol_ratio"] > 2.0    # 2x avg volume

        breakout_up   = last["close"] > resistance and vol_surge
        breakdown_dn  = last["close"] < support and vol_surge
        above_ema50   = last["close"] > last["ema_50"]

        if breakout_up and above_ema50:
            signal     = "BUY"
            confidence = 7 + (1 if narrow_band else 0) + (1 if last["vol_ratio"] > 3 else 0) + (1 if last["adx"] < 25 else 0)
        elif breakdown_dn and not above_ema50:
            signal     = "SELL"
            confidence = 7 + (1 if narrow_band else 0) + (1 if last["vol_ratio"] > 3 else 0)

        entry  = round(last["close"], 2)
        atr    = last["atr"]
        if signal == "BUY":
            sl, target = round(resistance - atr, 2), round(entry + atr * 3, 2)
        elif signal == "SELL":
            sl, target = round(support + atr, 2), round(entry - atr * 3, 2)
        else:
            sl, target = 0, 0

        reasoning = (
            f"Price {'broke above' if signal == 'BUY' else 'broke below'} "
            f"{'resistance' if signal == 'BUY' else 'support'} at "
            f"₹{resistance if signal == 'BUY' else support:.2f}. "
            f"Volume surge: {last['vol_ratio']:.1f}x avg."
        )

        return {"signal": signal, "entry": entry, "stop_loss": sl, "target": target,
                "confidence": min(confidence, 10), "reasoning": reasoning,
                "strategy": "Breakout"}
    except Exception as e:
        logger.error(f"Breakout error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 5 — Claude AI (Multi-factor)
# ─────────────────────────────────────────────────────────────────────────────

def strategy_claude_ai(df: pd.DataFrame, symbol: str) -> dict:
    """
    Uses Claude to do a holistic multi-factor swing trade analysis.
    Sends recent price action + all indicator values.
    """
    try:
        last = df.iloc[-1]
        tail = df.tail(30)[["open", "high", "low", "close", "volume",
                             "rsi", "macd", "macd_signal", "macd_hist",
                             "ema_20", "ema_50", "ema_200",
                             "atr", "adx", "bb_upper", "bb_lower",
                             "vol_ratio"]].round(2)

        prompt = f"""
You are an expert NSE swing trader. Analyze this stock data and give a trading decision.

Stock: {symbol}
Last 30 trading sessions (daily OHLCV + indicators):
{tail.to_json(orient="records")}

Current values:
- RSI: {last['rsi']:.1f}
- MACD: {last['macd']:.3f} / Signal: {last['macd_signal']:.3f}
- EMA20: {last['ema_20']:.2f} / EMA50: {last['ema_50']:.2f} / EMA200: {last['ema_200']:.2f}
- ADX: {last['adx']:.1f}
- ATR: {last['atr']:.2f}
- BB Upper: {last['bb_upper']:.2f} / Lower: {last['bb_lower']:.2f}
- Volume ratio: {last['vol_ratio']:.2f}x

Provide swing trade decision for the NEXT 5-15 trading days.
Respond ONLY with valid JSON (no preamble, no markdown backticks):
{{
  "signal": "BUY" | "SELL" | "HOLD",
  "entry_price": <float — current price or slight pullback>,
  "stop_loss": <float — based on key support/resistance + ATR>,
  "target": <float — next resistance or ATR-based, min 1:2 R:R>,
  "confidence": <int 1-10>,
  "reasoning": "<2-3 sentences: trend + momentum + trigger>",
  "key_levels": "<support and resistance levels to watch>"
}}
"""

        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        # strip accidental markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        return {
            "signal":     data.get("signal", "HOLD"),
            "entry":      float(data.get("entry_price", last["close"])),
            "stop_loss":  float(data.get("stop_loss", 0)),
            "target":     float(data.get("target", 0)),
            "confidence": int(data.get("confidence", 0)),
            "reasoning":  data.get("reasoning", ""),
            "strategy":   "Claude AI",
        }

    except json.JSONDecodeError as e:
        logger.error(f"Claude AI JSON parse error for {symbol}: {e}")
        return _hold()
    except Exception as e:
        logger.error(f"Claude AI strategy error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 6 — 52-Week High Breakout (Added in v3)
# ─────────────────────────────────────────────────────────────────────────────

def strategy_52w_breakout(df: pd.DataFrame, symbol: str) -> dict:
    """
    First 52-week high breakout with volume surge.
    Statistically strongest momentum signal in NSE (60%+ continuation rate).
    Uses wider ATR stop (2.5x) and larger target (6x) for high reward trades.
    """
    try:
        if len(df) < 252:
            return _hold()

        last  = df.iloc[-1]
        prev  = df.iloc[-2]

        rolling_high_52w      = df["high"].rolling(252).max()
        new_52w_high          = last["high"] >= rolling_high_52w.iloc[-1]
        was_already_at_52w    = prev["high"] >= rolling_high_52w.iloc[-2]
        first_breakout        = new_52w_high and not was_already_at_52w

        if not first_breakout:
            return _hold()

        vol_surge     = last["vol_ratio"] > 1.5
        not_extended  = last["rsi"] < 75
        trending      = last["adx"] > 15

        if not (vol_surge and not_extended):
            return _hold()

        confidence = 7
        if last["vol_ratio"] > 2.5:  confidence += 1
        if trending:                  confidence += 1
        if last["rsi"] < 65:         confidence += 1

        entry  = round(last["close"], 2)
        atr    = last["atr"]
        sl     = round(entry - atr * 2.5, 2)
        target = round(entry + atr * 6.0, 2)

        return {
            "signal":     "BUY",
            "entry":      entry,
            "stop_loss":  sl,
            "target":     target,
            "confidence": min(confidence, 10),
            "reasoning":  f"First 52-week high breakout at ₹{entry:.2f}. Volume {last['vol_ratio']:.1f}x avg. ADX={last['adx']:.0f}, RSI={last['rsi']:.0f}.",
            "strategy":   "52W Breakout",
        }
    except Exception as e:
        logger.error(f"52W Breakout error for {symbol}: {e}")
        return _hold()


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Runner
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_MAP = {
    "ema_crossover":   strategy_ema_crossover,
    "rsi_reversal":    strategy_rsi_reversal,
    "macd_momentum":   strategy_macd_momentum,
    "breakout":        strategy_breakout,
    "claude_ai":       strategy_claude_ai,
    "52w_breakout":    strategy_52w_breakout,
}


def run_strategies(df: pd.DataFrame, symbol: str,
                   active_strategies: list) -> list[dict]:
    """
    Run all active strategies on a symbol.
    Returns list of results above MIN_CONFIDENCE.
    """
    df = add_all_indicators(df)
    if df.empty or len(df) < 50:
        logger.warning(f"Not enough data for {symbol}")
        return []

    results = []
    for name in active_strategies:
        fn = STRATEGY_MAP.get(name)
        if fn is None:
            logger.warning(f"Unknown strategy: {name}")
            continue
        result = fn(df, symbol)
        result["symbol"] = symbol
        if result["signal"] != "HOLD" and result["confidence"] >= MIN_CONFIDENCE:
            results.append(result)
            logger.info(f"Signal: {symbol} {result['signal']} "
                        f"[{result['strategy']}] conf={result['confidence']}/10")

    return results


def get_consensus_signal(signals: list[dict]) -> dict | None:
    """
    If multiple strategies agree on the same signal, boost confidence.
    Returns the best (highest confidence) signal, or None.
    """
    if not signals:
        return None

    buy_signals  = [s for s in signals if s["signal"] == "BUY"]
    sell_signals = [s for s in signals if s["signal"] == "SELL"]

    best = None
    if len(buy_signals) >= 2:
        best = max(buy_signals, key=lambda x: x["confidence"])
        best["confidence"] = min(best["confidence"] + len(buy_signals) - 1, 10)
        best["strategy"] = f"CONSENSUS ({', '.join(s['strategy'] for s in buy_signals)})"
    elif len(sell_signals) >= 2:
        best = max(sell_signals, key=lambda x: x["confidence"])
        best["confidence"] = min(best["confidence"] + len(sell_signals) - 1, 10)
        best["strategy"] = f"CONSENSUS ({', '.join(s['strategy'] for s in sell_signals)})"
    elif signals:
        best = max(signals, key=lambda x: x["confidence"])

    return best


def _hold() -> dict:
    return {"signal": "HOLD", "entry": 0, "stop_loss": 0, "target": 0,
            "confidence": 0, "reasoning": "No signal.", "strategy": "unknown"}
