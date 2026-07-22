import logging
import warnings
from datetime import timedelta
import pandas as pd
from src.database import DatabaseManager
from src.notifier import send_push_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.analytics")

def calculate_market_metrics():
    """
    Queries historical price data from Supabase for all tracked items.
    Auto-detects column names to handle schema variations smoothly.
    Calculates 24-hour price changes and 7-day moving averages (SMA).
    """
    db = DatabaseManager()
    
    # Query all columns directly from market_history
    query = """
        SELECT *
        FROM market_history
        WHERE scraped_at >= NOW() - INTERVAL '14 days'
        ORDER BY scraped_at ASC;
    """
    
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Suppresses the harmless Pandas SQLAlchemy warning
            df = pd.read_sql_query(query, db.conn)
    except Exception as e:
        logger.error(f"Error querying market history for analytics: {e}")
        return []
    finally:
        db.close()

    if df.empty:
        logger.warning("No price records found in the last 14 days.")
        return []

    # --- Auto-detect Name and Price Columns ---
    name_col = next((c for c in ['skin_name', 'market_hash_name', 'item_name'] if c in df.columns), None)
    price_col = next((c for c in ['price_usd', 'price', 'lowest_price', 'median_price', 'value'] if c in df.columns), None)

    if not name_col or not price_col:
        logger.error(f"Could not automatically identify columns. Found in table: {list(df.columns)}")
        return []

    logger.info(f"Using columns -> Name: '{name_col}', Price: '{price_col}'")

    # Clean numeric data and datetime objects
    df['price_clean'] = pd.to_numeric(df[price_col], errors='coerce')
    df['scraped_at'] = pd.to_datetime(df['scraped_at'])
    df = df.dropna(subset=['price_clean', 'scraped_at'])

    alerts = []
    grouped = df.groupby(name_col)

    for skin_name, group in grouped:
        if len(group) < 2:
            continue  # Need at least 2 data points

        group = group.sort_values('scraped_at')
        
        latest_row = group.iloc[-1]
        latest_price = float(latest_row['price_clean'])
        latest_time = latest_row['scraped_at']

        # 1. FIX: Calculate TRUE 7-Day Simple Moving Average (SMA)
        seven_days_ago = latest_time - timedelta(days=7)
        group_7d = group[group['scraped_at'] >= seven_days_ago]
        sma_7d = group_7d['price_clean'].mean() if not group_7d.empty else latest_price

        # 2. Find record closest to 24 hours ago
        target_24h_time = latest_time - timedelta(hours=24)
        group['time_diff'] = (group['scraped_at'] - target_24h_time).abs()
        closest_24h_row = group.sort_values('time_diff').iloc[0]
        price_24h_ago = float(closest_24h_row['price_clean'])

        # 3. Calculate percentage metrics
        delta_24h = ((latest_price - price_24h_ago) / price_24h_ago) * 100 if price_24h_ago > 0 else 0.0
        sma_dev = ((latest_price - sma_7d) / sma_7d) * 100 if sma_7d > 0 else 0.0
        
        # --- SIGNAL THRESHOLDS ---
        if delta_24h <= -8.0 or sma_dev <= -10.0:
            alerts.append({
                "type": "DIP 📉",
                "skin": skin_name,
                "price": latest_price,
                "delta_24h": delta_24h,
                "sma_dev": sma_dev
            })
        elif delta_24h >= 10.0 or sma_dev >= 12.0:
            alerts.append({
                "type": "SPIKE 📈",
                "skin": skin_name,
                "price": latest_price,
                "delta_24h": delta_24h,
                "sma_dev": sma_dev
            })

    return alerts

def run_and_notify_analytics():
    """Runs analytics and pings your phone if dip or spike signals are triggered."""
    logger.info("📊 Running market analytics & signal detection engine...")
    alerts = calculate_market_metrics()

    if not alerts:
        logger.info("Market is stable. No significant dips or spikes detected.")
        return

    logger.info(f"Detected {len(alerts)} market signals across tracked items!")
    
    # Format push notification message for phone
    lines = []
    for alert in alerts[:5]:  # Summarize top 5 signals
        lines.append(
            f"{alert['type']} {alert['skin']}\n"
            f"  Price: ${alert['price']:.2f} | 24h: {alert['delta_24h']:+.1f}% | vs 7d Avg: {alert['sma_dev']:+.1f}%"
        )

    msg = "\n\n".join(lines)
    if len(alerts) > 5:
        msg += f"\n\n...and {len(alerts) - 5} more items flagging market activity!"

    send_push_notification(
        title=f"🚨 Market Alert: {len(alerts)} Signals Detected!",
        message=msg,
        priority="high"
    )

if __name__ == "__main__":
    run_and_notify_analytics()