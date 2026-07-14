# CSMID

Python scraper with SQLite storage and a simple data pipeline.

## Project structure

```
CSMID/
├── src/
│   ├── scraper.py      # Scraping logic
│   ├── database.py     # SQLite helpers
│   ├── config.py       # Paths and settings
│   └── main.py         # CLI entry point
├── data/
│   ├── raw/            # Raw scrape output
│   ├── processed/      # Cleaned data
│   └── backups/        # Backups
├── docs/
├── tests/
├── requirements.txt
└── csmid.db            # Created on first run
```

## Setup

```bash
cd CSMID
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
```

## Usage

Initialize and run a scrape:

```bash
python src/main.py scrape --source example --url https://example.com
```

List stored records:

```bash
python src/main.py list --limit 10
```

## Tests

```bash
pytest tests/
```
