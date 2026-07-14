from pathlib import Path
import csv

MASTER_CATALOG = Path(__file__).resolve().parent.parent / "data" / "master" / "master_skins.csv"


def load_master_catalog():
    skins = []

    with open(MASTER_CATALOG, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            skins.append(row["market_hash_name"])

    return skins


def get_batch(start_index, batch_size):
    skins = load_master_catalog()

    end = min(start_index + batch_size, len(skins))

    return skins[start_index:end], end, len(skins)