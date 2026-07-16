import json
import os

# 1. Define known paths
watchlist_path = os.path.join("data", "watchlists", "all_weapons.txt")
output_path = os.path.join("data", "watchlists", "all_weapons_with_wears.txt")

# 2. Smart-search for data2.json inside the 'data' directory
data2_path = None
possible_paths = [
    os.path.join("data", "raw_catalog", "data2.json"),
    os.path.join("data", "raw catalog", "data2.json"),
    "data2.json"
]

# Check obvious paths first
for path in possible_paths:
    if os.path.exists(path):
        data2_path = path
        break

# If not found in obvious paths, perform a recursive search inside 'data/'
if not data2_path and os.path.exists("data"):
    print("🔍 Searching recursively for 'data2.json' inside the 'data/' folder...")
    for root, dirs, files in os.walk("data"):
        if "data2.json" in files:
            data2_path = os.path.join(root, "data2.json")
            break

# 3. Verification checks
if not os.path.exists(watchlist_path):
    print(f"\n❌ Error: Could not find '{watchlist_path}'.")
    print("Please make sure you are running this script from the root 'CSMID' folder.")
    exit(1)

if not data2_path:
    print("\n❌ Error: Could not find 'data2.json' inside the 'data' folder structure.")
    print("Please double check that 'data2.json' exists in your catalog folder.")
    exit(1)

print(f"📖 Found watchlist at: {watchlist_path}")
print(f"📖 Found master catalog at: {data2_path}")

# 4. Load the base weapons
with open(watchlist_path, "r", encoding="utf-8") as f:
    base_weapons = {line.strip() for line in f if line.strip()}

# 5. Load the master JSON catalog
with open(data2_path, "r", encoding="utf-8") as f:
    data2 = json.load(f)

# Standard CS2 wear conditions
wears = ["(Factory New)", "(Minimal Wear)", "(Field-Tested)", "(Well-Worn)", "(Battle-Scarred)"]
matched_skins = []

# 6. Cross-reference keys to map Standard + StatTrak
for key in data2.keys():
    # Strip StatTrak™ prefix if present to isolate the core weapon name
    clean_key = key.replace("StatTrak™ ", "")
    
    base_name = clean_key
    for w in wears:
        if w in clean_key:
            # Strip the wear state to get back to the clean base name
            base_name = clean_key.replace(f" {w}", "").strip()
            break
            
    # Save the real Steam name if the core weapon matches your watchlist
    if base_name in base_weapons:
        matched_skins.append(key)

# Sort alphabetically so your database entries remain highly organized
matched_skins.sort()

# 7. Save the generated exact-match watchlist directly to data/watchlists/
with open(output_path, "w", encoding="utf-8") as f:
    for skin in matched_skins:
        f.write(f"{skin}\n")

print(f"\n✅ Success! Created '{output_path}' containing {len(matched_skins)} valid market items.")