import requests
import logging

from src.env import NTFY_TOPIC, NTFY_SERVER

logger = logging.getLogger(__name__)

def send_push_notification(title: str, message: str, priority: str = "default"):
    """
    Sends an instant push notification to your phone using ntfy.sh
    Priority levels: min, low, default, high, urgent
    """
    try:
        url = f"{NTFY_SERVER.rstrip('/')}/{NTFY_TOPIC.lstrip('/')}"
        
        # Strip any non-ASCII characters from header strings to prevent latin-1 encoding errors
        safe_title = title.encode('ascii', 'ignore').decode('ascii').strip()
        
        response = requests.post(
            url,
            data=message.encode('utf-8'),  # Body supports UTF-8 (emojis included!)
            headers={
                "Title": safe_title if safe_title else "CSMID Alert",
                "Priority": priority,
                "Tags": "chart_with_upwards_trend,game"  # Keep tag strings pure ASCII
            },
            timeout=10
        )
        if response.status_code == 200:
            logger.info("📱 Notification sent successfully to phone.")
        else:
            logger.warning(f"Failed to send notification: {response.text}")
    except Exception as e:
        logger.error(f"Error sending push notification: {e}")