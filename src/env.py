import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv is not None and "pytest" not in sys.modules:
    load_dotenv(dotenv_path=BASE_DIR / ".env")


def _env_default(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


SUPABASE_URL: str = _env_default("SUPABASE_URL", "")
SUPABASE_KEY: str = _env_default("SUPABASE_KEY", "")
SUPABASE_DB_URL: str = _env_default("SUPABASE_DB_URL", "")
NTFY_TOPIC: str = _env_default("NTFY_TOPIC", "csmid_alerts")
NTFY_SERVER: str = _env_default("NTFY_SERVER", "https://ntfy.sh")
SCRAPINGANT_API_KEY = _env_default("SCRAPINGANT_API_KEY")
SCRAPERAPI_KEY = _env_default("SCRAPERAPI_KEY")
ZENROWS_API_KEY = _env_default("ZENROWS_API_KEY")
SCRAPINGBEE_API_KEY = _env_default("SCRAPINGBEE_API_KEY")


def validate_env() -> None:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
