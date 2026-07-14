from pathlib import Path
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw_catalog"
RAW_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT = RAW_DIR / "skins.json"

# We'll replace this with the real endpoint once we've chosen the source.
URL = "https://example.com"

def main():
    print("Downloader framework is ready.")
    print(f"Output folder: {RAW_DIR}")
    print("Waiting for data source configuration...")

if __name__ == "__main__":
    main()