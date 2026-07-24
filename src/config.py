from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Database location
DATABASE_PATH = PROJECT_ROOT / "csmid.db"
DB_PATH = DATABASE_PATH

# Data folders
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
BACKUP_DATA_DIR = PROJECT_ROOT / "data" / "backups"

# Watchlist of skins to collect via `collect --all`
WATCHLISTS_DIR = PROJECT_ROOT / "data" / "watchlists"
DEFAULT_WATCHLIST = WATCHLISTS_DIR / "core.txt"