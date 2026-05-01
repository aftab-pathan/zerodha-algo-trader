"""
core/stock_universe.py

Build and filter large stock universes (Top 1000 NSE stocks).
2-stage filtering: Stage 1 uses bulk quote API for pre-filtering,
Stage 2 runs full technical analysis on filtered subset.
"""

import os
import json
import time
import logging
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict

from config.config import (
    DATA_DIR,
    PREFILTER_MIN_PRICE,
    PREFILTER_MAX_PRICE,
    PREFILTER_MIN_VOLUME,
    MAX_STAGE2_STOCKS,
    CACHE_DURATION_HOURS,
    QUOTE_BATCH_SIZE,
    QUOTE_BATCH_DELAY,
    QUOTE_MAX_RETRIES,
    QUOTE_RETRY_DELAY,
)

logger = logging.getLogger(__name__)


def build_nse_universe(size: int = 1000) -> List[str]:
    """
    Build NSE equity universe from instruments cache.
    Returns list of top N equity symbols (excludes derivatives).
    
    Args:
        size: Target number of stocks (default 1000)
    
    Returns:
        List of NSE equity trading symbols
    """
    from core.kite_client import get_kite
    
    try:
        logger.info(f"Building NSE equity universe (target size: {size})...")
        instruments = get_kite().instruments("NSE")
        
        # Filter to equities only (exclude FUT, CE, PE, etc.)
        equities = [
            inst["tradingsymbol"]
            for inst in instruments
            if inst.get("instrument_type") == "EQ" and inst.get("segment") == "NSE"
        ]
        
        logger.info(f"Found {len(equities)} NSE equity instruments")
        
        # Return first N symbols (Kite API returns them roughly in order of liquidity)
        universe = equities[:size]
        logger.info(f"Built universe of {len(universe)} stocks")
        
        return universe
        
    except Exception as e:
        logger.error(f"Failed to build NSE universe: {e}")
        return []


def apply_prefilters(symbols: List[str], config: Dict = None) -> List[str]:
    """
    Stage 1: Pre-filter stocks using bulk quote API.
    Filters by price range, volume, and circuit limits.
    
    Args:
        symbols: List of stock symbols to filter
        config: Optional config overrides (min_price, max_price, min_volume)
    
    Returns:
        List of symbols that passed filters
    """
    from core.kite_client import get_kite
    
    if not symbols:
        return []
    
    # Load config with defaults
    cfg = config or {}
    min_price = cfg.get("min_price", PREFILTER_MIN_PRICE)
    max_price = cfg.get("max_price", PREFILTER_MAX_PRICE)
    min_volume = cfg.get("min_volume", PREFILTER_MIN_VOLUME)
    max_stage2 = cfg.get("max_stage2", MAX_STAGE2_STOCKS)
    
    logger.info(f"Stage 1: Pre-filtering {len(symbols)} stocks...")
    logger.info(f"Filters: price ₹{min_price}-₹{max_price}, volume >{min_volume:,}")
    
    filtered = []
    kite = get_kite()
    
    # Process in batches (configurable batch size to avoid Cloudflare blocks)
    batch_size = QUOTE_BATCH_SIZE
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        exchange_symbols = [f"NSE:{s}" for s in batch]
        
        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        logger.info(f"Fetching quotes for batch {batch_num}/{total_batches} ({len(batch)} stocks)...")
        
        # Retry logic with exponential backoff for Cloudflare blocks
        max_retries = QUOTE_MAX_RETRIES
        retry_delay = QUOTE_RETRY_DELAY
        quotes = None
        
        for attempt in range(max_retries):
            try:
                # Use ohlc quote for OHLC + volume data
                quotes = kite.quote(exchange_symbols)
                break  # Success, exit retry loop
                
            except Exception as e:
                error_msg = str(e)
                if "text/html" in error_msg or "cloudflare" in error_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Cloudflare challenge detected, waiting {wait_time}s before retry {attempt+2}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        break
                else:
                    logger.warning(f"Error fetching quotes for batch {batch_num}: {e}")
                    break
        
        if quotes is None:
            logger.warning(f"Skipping batch {batch_num} due to API errors")
            time.sleep(QUOTE_BATCH_DELAY)  # Still delay before next batch
            continue
            
        # Process successful quotes
        try:
            for symbol in batch:
                key = f"NSE:{symbol}"
                if key not in quotes:
                    continue
                
                q = quotes[key]
                ltp = q.get("last_price", 0)
                volume = q.get("volume", 0)
                
                # Check if stock is circuit-halted
                upper_circuit = q.get("upper_circuit_limit", 0)
                lower_circuit = q.get("lower_circuit_limit", 0)
                is_halted = (ltp >= upper_circuit * 0.99) or (ltp <= lower_circuit * 1.01)
                
                # Apply filters
                if (min_price <= ltp <= max_price and 
                    volume >= min_volume and 
                    not is_halted):
                    filtered.append(symbol)
                    
        except Exception as e:
            logger.warning(f"Error processing quotes for batch {batch_num}: {e}")
        
        # Rate limit between batches
        time.sleep(QUOTE_BATCH_DELAY)
    
    # Cap at max_stage2 to keep scan time reasonable
    if len(filtered) > max_stage2:
        logger.info(f"Capping filtered list from {len(filtered)} to {max_stage2} stocks")
        filtered = filtered[:max_stage2]
    
    logger.info(f"Stage 1 complete: {len(symbols)} → {len(filtered)} stocks passed filters")
    
    return filtered


def get_cache_path(scan_date: date = None) -> Path:
    """Get path to cached universe file for given date."""
    if scan_date is None:
        scan_date = date.today()
    filename = f"filtered_universe_{scan_date.isoformat()}.json"
    return Path(DATA_DIR) / filename


def save_to_cache(symbols: List[str], scan_date: date = None) -> None:
    """Save filtered universe to cache file."""
    cache_path = get_cache_path(scan_date)
    
    try:
        cache_data = {
            "date": scan_date.isoformat() if scan_date else date.today().isoformat(),
            "timestamp": datetime.now().isoformat(),
            "count": len(symbols),
            "symbols": symbols
        }
        
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        logger.info(f"Saved {len(symbols)} symbols to cache: {cache_path}")
        
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


def load_from_cache(max_age_hours: float = None) -> List[str]:
    """
    Load filtered universe from cache if recent enough.
    
    Args:
        max_age_hours: Maximum cache age in hours (default: CACHE_DURATION_HOURS)
    
    Returns:
        List of symbols from cache, or empty list if cache is stale/missing
    """
    if max_age_hours is None:
        max_age_hours = CACHE_DURATION_HOURS
    
    cache_path = get_cache_path()
    
    if not cache_path.exists():
        logger.debug(f"No cache found at {cache_path}")
        return []
    
    try:
        with open(cache_path, 'r') as f:
            cache_data = json.load(f)
        
        # Check cache age
        cache_time = datetime.fromisoformat(cache_data["timestamp"])
        age_hours = (datetime.now() - cache_time).total_seconds() / 3600
        
        if age_hours > max_age_hours:
            logger.info(f"Cache is {age_hours:.1f}h old (max {max_age_hours}h), refreshing...")
            return []
        
        symbols = cache_data.get("symbols", [])
        logger.info(f"Loaded {len(symbols)} symbols from cache ({age_hours:.1f}h old)")
        
        return symbols
        
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
        return []


def cleanup_old_caches(keep_days: int = 7) -> None:
    """Delete cache files older than keep_days."""
    try:
        data_path = Path(DATA_DIR)
        if not data_path.exists():
            return
        
        cutoff = datetime.now().timestamp() - (keep_days * 86400)
        deleted = 0
        
        for cache_file in data_path.glob("filtered_universe_*.json"):
            if cache_file.stat().st_mtime < cutoff:
                cache_file.unlink()
                deleted += 1
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old cache files")
            
    except Exception as e:
        logger.warning(f"Cache cleanup failed: {e}")


def get_filtered_universe(size: int = 1000, use_cache: bool = True,
                          filter_config: Dict = None) -> List[str]:
    """
    Main entry point: Get filtered stock universe.
    
    Process:
    1. Check cache (if use_cache=True)
    2. Build NSE universe (Stage 0)
    3. Apply pre-filters using quote API (Stage 1)
    4. Cache results
    5. Cleanup old caches
    
    Args:
        size: Target universe size (default 1000)
        use_cache: Whether to use/save cache (default True)
        filter_config: Optional dict with filter overrides
    
    Returns:
        List of filtered stock symbols ready for Stage 2 (full technical analysis)
    """
    # Try cache first
    if use_cache:
        cached = load_from_cache()
        if cached:
            return cached
    
    # Build fresh universe
    logger.info(f"Building fresh filtered universe (size: {size})...")
    
    # Stage 0: Get all NSE equities
    universe = build_nse_universe(size)
    
    if not universe:
        logger.error("Failed to build universe, returning empty list")
        return []
    
    # Stage 1: Pre-filter
    filtered = apply_prefilters(universe, filter_config)
    
    # Cache results
    if use_cache and filtered:
        save_to_cache(filtered)
        cleanup_old_caches()
    
    return filtered


def get_universe_stats(symbols: List[str]) -> Dict:
    """Get statistics about a stock universe (for logging/display)."""
    from core.kite_client import get_kite
    
    if not symbols:
        return {"count": 0}
    
    try:
        # Sample first 100 for stats
        sample = symbols[:min(100, len(symbols))]
        exchange_symbols = [f"NSE:{s}" for s in sample]
        
        quotes = get_kite().quote(exchange_symbols)
        
        prices = [q.get("last_price", 0) for q in quotes.values()]
        volumes = [q.get("volume", 0) for q in quotes.values()]
        
        return {
            "count": len(symbols),
            "sample_size": len(sample),
            "avg_price": sum(prices) / len(prices) if prices else 0,
            "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
        }
        
    except Exception as e:
        logger.warning(f"Failed to get universe stats: {e}")
        return {"count": len(symbols), "error": str(e)}
