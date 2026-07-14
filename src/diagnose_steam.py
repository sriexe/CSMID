"""
diagnose_steam.py
One-off diagnostic -- NOT part of CSMID. Run standalone:

    python diagnose_steam.py

Finding so far: header content and User-Agent do NOT explain the
429s -- three back-to-back requests with zero delay got 200/429/429
regardless of headers used. This script now tests actual spacing
between requests to find the real safe interval.

IMPORTANT: this makes several real requests to Steam with deliberate
waits between them (up to a few minutes total). Let it run to
completion rather than re-running it repeatedly -- re-running it
back-to-back defeats the point and just re-triggers the block.
"""

import time
import requests

URL = "https://steamcommunity.com/market/priceoverview/"
PARAMS = {
    "appid": 730,
    "currency": 1,
    "market_hash_name": "AK-47 | Slate (Minimal Wear)",
}
HEADERS = {"User-Agent": "curl/8.19.0", "Accept": "*/*"}

# Intervals to test, in seconds, ascending. We stop at the first
# interval that succeeds twice in a row.
INTERVALS_TO_TRY = [5, 10, 15, 20, 30]


def request_once() -> int:
    r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=10)
    return r.status_code


print("Waiting 30s upfront to make sure we start from a clean window...")
time.sleep(30)

for interval in INTERVALS_TO_TRY:
    print(f"\n=== Testing {interval}s spacing ===")
    status_a = request_once()
    print(f"Request A: {status_a}")

    time.sleep(interval)

    status_b = request_once()
    print(f"Request B (after {interval}s): {status_b}")

    if status_a == 200 and status_b == 200:
        print(f"\n>>> {interval}s spacing appears SAFE (two in a row succeeded)")
        break
    else:
        print(f">>> {interval}s spacing still triggered a 429. Trying longer wait before next test...")
        time.sleep(20)  # cool down before next interval test
else:
    print("\n>>> None of the tested intervals were fully safe -- may need >30s spacing.")