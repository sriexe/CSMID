import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
SUPABASE_DB_URL: str = os.getenv("SUPABASE_DB_URL", "")
NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "csmid_alerts")
NTFY_SERVER: str = os.getenv("NTFY_SERVER", "https://ntfy.sh")
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")
ZENROWS_API_KEY = os.getenv("ZENROWS_API_KEY")
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")


def validate_env() -> None:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
