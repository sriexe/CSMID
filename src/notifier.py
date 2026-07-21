import os
import requests
import logging

logger = logging.getLogger(__name__)

# Use environment variable or fallback to a default topic
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "csmid-tracker-sri-99")

def send_push_notification(title: str, message: str, priority: str = "default"):
    """
    Sends an instant push notification to your phone using ntfy.sh
    Priority levels: min, low, default, high, urgent
    """
    try:
        url = f"https://ntfy.sh/{NTFY_TOPIC}"
        response = requests.post(
            url,
            data=message.encode('utf-8'),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "chart_with_upwards_trend,game"
            },
            timeout=10
        )
        if response.status_code == 200:
            logger.info("📱 Notification sent successfully to phone.")
        else:
            logger.warning(f"Failed to send notification: {response.text}")
    except Exception as e:
        logger.error(f"Error sending push notification: {e}")