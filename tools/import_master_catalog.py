import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SOURCE = PROJECT_ROOT / "data" / "raw_catalog" / "data2.json"
OUTPUT = PROJECT_ROOT / "data" / "master" / "master_skins.csv"

HEADER = [
    "weapon",
    "skin_name",
    "market_hash_name",
    "weapon_class",
    "rarity",
    "collection",
    "stattrak",
    "souvenir",
    "active",
]


WEAPON_CLASSES = {
    "AK-47": "Rifle",
    "M4A4": "Rifle",
    "M4A1-S": "Rifle",
    "AWP": "Rifle",
    "AUG": "Rifle",
    "FAMAS": "Rifle",
    "Galil AR": "Rifle",
    "SG 553": "Rifle",
    "SSG 08": "Rifle",
    "SCAR-20": "Rifle",
    "G3SG1": "Rifle",

    "MAC-10": "SMG",
    "MP9": "SMG",
    "MP7": "SMG",
    "MP5-SD": "SMG",
    "P90": "SMG",
    "PP-Bizon": "SMG",
    "UMP-45": "SMG",

    "USP-S": "Pistol",
    "Glock-18": "Pistol",
    "P2000": "Pistol",
    "CZ75-Auto": "Pistol",
    "Tec-9": "Pistol",
    "Desert Eagle": "Pistol",
    "Dual Berettas": "Pistol",
    "Five-SeveN": "Pistol",
    "P250": "Pistol",
    "R8 Revolver": "Pistol",

    "Nova": "Heavy",
    "MAG-7": "Heavy",
    "Sawed-Off": "Heavy",
    "XM1014": "Heavy",
    "M249": "Heavy",
    "Negev": "Heavy",
}


with open(SOURCE, encoding="utf-8") as f:
    skins = json.load(f)

rows = []
seen = set()

for item in skins.values():

    weapon = item["weapon"]

    if weapon not in WEAPON_CLASSES:
        continue

    market_hash_name = item["name"]

    # Skip duplicates
    if market_hash_name in seen:
        continue

    seen.add(market_hash_name)

    rows.append({
        "weapon": weapon,
        "skin_name": item["finish"],
        "market_hash_name": market_hash_name,
        "weapon_class": WEAPON_CLASSES[weapon],
        "rarity": item["rarity"],
        "collection": "",
        "stattrak": "FALSE",
        "souvenir": "FALSE",
        "active": "TRUE",
    })

rows.sort(key=lambda x: (x["weapon"], x["skin_name"]))

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:

    writer = csv.DictWriter(f, fieldnames=HEADER)

    writer.writeheader()

    writer.writerows(rows)

print(f"Imported {len(rows)} weapon skins.")
print(OUTPUT)