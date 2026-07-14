import schedule
import subprocess
import time
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent

COMMAND = [
    sys.executable,
    "src/main.py",
    "collect",
    "--watchlist",
    "all_weapons",
    "--resume",
    "--since-hours",
    "20",
]


def run_collection():

    print("=" * 60)
    print(datetime.now())
    print("Starting scheduled collection...")
    print("=" * 60)
    print("Scheduler Python:", sys.executable)
    print("Running:", COMMAND)

    result = subprocess.run(
        COMMAND,
        cwd=PROJECT_ROOT
    )

    print()
    print("Finished.")
    print("Exit code:", result.returncode)
    print()


schedule.every(1).minutes.do(run_collection)

print("CSMID Scheduler Started")
print("Waiting for next collection...")

while True:

    schedule.run_pending()

    time.sleep(30)