#!/usr/bin/env python3
"""
generate_watchlists.py

Generates collector watchlists from the master skin catalog.

Input:
    data/master/master_skins.csv

Output (written to data/watchlists/):
    all_weapons.txt
    rifles.txt
    smgs.txt
    pistols.txt
    heavy.txt

Usage:
    python tools/generate_watchlists.py
    python tools/generate_watchlists.py --master path/to/master_skins.csv --out path/to/watchlists
    python tools/generate_watchlists.py --dry-run

Design notes
------------
- No manual watchlist editing after this point (per CSMID handover doc, section 8/9).
  This script is the single source of truth going forward.
- Grouping is based on the `weapon_class` column in master_skins.csv. Because the
  exact string values used in that column weren't available at the time this
  script was written, matching is done via a normalized lookup table
  (WEAPON_CLASS_MAP) rather than a hardcoded exact-string comparison. If your
  master_skins.csv uses class labels not covered below, add them to the map --
  no other logic needs to change.
- Every market_hash_name is de-duplicated and every output file is sorted
  alphabetically, so runs are deterministic and diffable in version control.
- Rows with a missing/blank market_hash_name, or explicitly inactive rows
  (active == false/0), are skipped. Adjust SKIP_INACTIVE below if that's
  not the desired behavior.
"""

import argparse
import csv
import sys
from pathlib import Path
from collections import defaultdict

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# If True, rows where the `active` column evaluates false are excluded from
# every watchlist (including all_weapons.txt).
SKIP_INACTIVE = True

# Normalized weapon_class value -> output category.
# Keys are matched case-insensitively, with whitespace/underscores/hyphens
# collapsed to nothing (see normalize_class()).
# "heavy" here follows Valve's own category (Shotguns + Machine Guns).
WEAPON_CLASS_MAP = {
    # Rifles
    "rifle": "rifles",
    "rifles": "rifles",
    "assaultrifle": "rifles",
    "sniperrifle": "rifles",
    "sniper": "rifles",

    # SMGs
    "smg": "smgs",
    "smgs": "smgs",
    "submachinegun": "smgs",

    # Pistols
    "pistol": "pistols",
    "pistols": "pistols",
    "sidearm": "pistols",

    # Heavy (shotguns + machine guns, per Valve's weapon grouping)
    "heavy": "heavy",
    "shotgun": "heavy",
    "shotguns": "heavy",
    "machinegun": "heavy",
    "machineguns": "heavy",
    "lmg": "heavy",
}

CATEGORY_FILES = ["rifles", "smgs", "pistols", "heavy"]


def normalize_class(value: str) -> str:
    """Lowercase and strip spaces/underscores/hyphens for lookup matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def is_active(row: dict) -> bool:
    val = (row.get("active") or "").strip().lower()
    if val in ("", "true", "1", "yes", "y", "active"):
        return True
    if val in ("false", "0", "no", "n", "inactive"):
        return False
    # Unknown value: default to treating as active rather than silently dropping.
    return True


def load_master_catalog(master_path: Path):
    """Reads master_skins.csv and returns a list of row dicts."""
    if not master_path.exists():
        print(f"ERROR: master catalog not found at {master_path}", file=sys.stderr)
        sys.exit(1)

    with master_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "market_hash_name" not in reader.fieldnames:
            print(
                "ERROR: master_skins.csv is missing the expected "
                "'market_hash_name' column. Found columns: "
                f"{reader.fieldnames}",
                file=sys.stderr,
            )
            sys.exit(1)
        rows = list(reader)
    return rows


def build_watchlists(rows):
    """
    Groups market_hash_name values by category.

    Returns:
        all_weapons: sorted list[str]
        by_category: dict[str, sorted list[str]] for rifles/smgs/pistols/heavy
        unmapped_classes: dict[str, int] count of weapon_class values seen
                           that didn't map to a known category (for reporting)
    """
    all_weapons = set()
    by_category = defaultdict(set)
    unmapped_classes = defaultdict(int)

    for row in rows:
        name = (row.get("market_hash_name") or "").strip()
        if not name:
            continue
        if SKIP_INACTIVE and not is_active(row):
            continue

        all_weapons.add(name)

        raw_class = (row.get("weapon_class") or "").strip()
        norm = normalize_class(raw_class)
        category = WEAPON_CLASS_MAP.get(norm)

        if category:
            by_category[category].add(name)
        elif raw_class:
            unmapped_classes[raw_class] += 1

    sorted_all = sorted(all_weapons)
    sorted_by_category = {
        cat: sorted(by_category.get(cat, set())) for cat in CATEGORY_FILES
    }
    return sorted_all, sorted_by_category, unmapped_classes


def write_watchlist(path: Path, names, dry_run: bool):
    if dry_run:
        print(f"[dry-run] would write {len(names)} entries -> {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")
    print(f"wrote {len(names)} entries -> {path}")


def main():
    parser = argparse.ArgumentParser(description="Generate CSMID watchlists from master_skins.csv")
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("data/master/master_skins.csv"),
        help="Path to master_skins.csv (default: data/master/master_skins.csv)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/watchlists"),
        help="Output directory for generated watchlists (default: data/watchlists)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk",
    )
    args = parser.parse_args()

    rows = load_master_catalog(args.master)
    all_weapons, by_category, unmapped_classes = build_watchlists(rows)

    write_watchlist(args.out / "all_weapons.txt", all_weapons, args.dry_run)
    write_watchlist(args.out / "rifles.txt", by_category["rifles"], args.dry_run)
    write_watchlist(args.out / "smgs.txt", by_category["smgs"], args.dry_run)
    write_watchlist(args.out / "pistols.txt", by_category["pistols"], args.dry_run)
    write_watchlist(args.out / "heavy.txt", by_category["heavy"], args.dry_run)

    categorized_count = sum(len(v) for v in by_category.values())
    print()
    print(f"Total unique market_hash_name entries: {len(all_weapons)}")
    print(f"Categorized into rifles/smgs/pistols/heavy: {categorized_count}")
    print(f"Uncategorized (no matching weapon_class): {len(all_weapons) - categorized_count}")

    if unmapped_classes:
        print()
        print("weapon_class values seen that did not map to a category")
        print("(add these to WEAPON_CLASS_MAP in this script if they should be included):")
        for cls, count in sorted(unmapped_classes.items(), key=lambda x: -x[1]):
            print(f"  {cls!r}: {count} row(s)")


if __name__ == "__main__":
    main()