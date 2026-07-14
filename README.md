Here is a clean, production-grade `README.md` tailored exactly to your new codebase architecture. It breaks down the system design, explains the intelligent pacing logic, and provides crystal-clear instructions for running or troubleshooting the pipeline.

Copy and paste this directly into your project's root `README.md`:

```markdown
# CSMID — Counter-Strike Market Intelligence Dashboard

CSMID is a robust, production-ready data collection engine designed to track historical Valve Steam Market observations for CS2 weapon skins. The project features a native, state-aware intelligent scheduler built to systematically bypass severe Steam API rate-limiting restrictions via dynamic database lookups and adaptive backoff pacing.

---

## 🏗️ System Architecture & Components

The codebase is split cleanly into a thin-client interface layer, a core orchestration layer, a persistent state coordinator, and an append-only data storage engine.


```

CSMID/
├── config.py                 # Application global variables and database paths
├── data/
│   ├── master/               # Master target lists (master_skins.csv)
│   └── watchlists/           # Segmented evaluation slices (all_weapons.txt)
├── scheduler/
│   ├── daily_collect.py      # Native intelligent loop runner (Entrypoint)
│   └── state.py              # Crash-resilient queue state manager
├── src/
│   ├── collection_manager.py # Primary pipeline orchestrator & de-duplicator
│   ├── database.py           # SQLAlchemy layer, schemas, and native DB helpers
│   └── main.py               # Lightweight CLI argument parser
└── scheduler.log             # Main application execution log

```

### 1. The Intelligent Scheduler (`scheduler/daily_collect.py`)
Runs as a memory-efficient, native Python process. It eliminates subprocess invocation overhead and manages system flow via strategic exit-code matching.
* **Smart Pacing:** Evaluates the success or failure of a collection batch and branches into mathematically distinct rest states to stay beneath Steam's security thresholds.
* **Cross-Module Path Resolution:** Automatically hooks system paths on execution to ensure internal cross-imports between root directories run natively on any environment.

### 2. Orchestration & Smart De-duplication (`src/collection_manager.py`)
Acts as the central operational hub. Before executing any network call, it queries the database layer to build a high-performance in-memory lookup set of records updated within the last 20 hours.
* **Network Conservation:** If a skin is marked as fresh locally, it skips the execution immediately, advancing the queue pointer in milliseconds without touching the Steam API.
* **Safe State Wrapping:** If an unhandled exception or database interruption hits, it catches the bubble-up warning, marks the failure, and triggers a defensive cooling window.

### 3. Persistent State Coordinator (`scheduler/state.py`)
Tracks queue progression across machine reboots and application interruptions.
* **Schema Protection:** Saves metadata directly to `scheduler/queue_state.json`.
* **Fault Tolerance:** If the state file is deleted or corrupted, the module gracefully bootstraps safe project defaults dynamically rather than dropping execution.

### 4. Append-Only Layer (`src/database.py`)
Manages your relational SQLite database engine using SQLAlchemy mappings.
* **`skins` Table:** Holds fixed static metadata unique to a single asset listing. Natively parses string inputs to separate variables like Wear, Weapon class, and StatTrak™ status.
* **`market_history` Table:** An absolute **append-only** time-series data layer. Entries are never altered or deleted, ensuring an immutable history log for downstream ML analytical models.

---

## ⏱️ Adaptive Backoff Protocol

The pipeline tracks execution outcomes explicitly, adjusting cooling cycles dynamically based on system return behaviors:

| Exit Code | Event Signal | Core Action | Cooldown Period | Protocol Goal |
| :--- | :--- | :--- | :--- | :--- |
| **`0`** | Clean Batch | Advance Queue Index | **10 Minutes** | Standard pacing to prevent profile alerts. |
| **`2`** | HTTP 429 Rate Limit | Immediate Engine Freeze | **60 Minutes** | Prevents IP cooldown extension blocks. |
| **`1`** | Unhandled Error / DB Outage | Loop Pacing Protection | **5 Minutes** | Diagnostic recovery window. |

---

## 🚀 Setup & Installation

### 1. Environment Setup
Ensure your local environment is locked inside your virtual workspace:
```bash
# Activate your local virtual environment
.venv\Scripts\activate

```

### 2. Initialize the Database Schema

Before running data collections, trigger the baseline database setup to build out master structures, structural constraints, and downstream placeholders:

```python
# Run via python interpreter or entry call to initialize the SQLite database
from src.database import initialize_database
initialize_database()

```

---

## 🛠️ How to Run

### Mode A: Unattended Background Engine (Recommended)

To launch the long-term historical collection process on autopilot:

```bash
python scheduler/daily_collect.py

```

* The scheduler will boot, load your progress out of `scheduler/queue_state.json`, skip existing records, process remaining items, and manage its own sleep windows cleanly.

### Mode B: Lightweight Target CLI

To test a single skin extraction or target an isolated text file manually:

```bash
# Parse a specific skin manually
python src/main.py --skin "AK-47 | Redline (Field-Tested)"

# Target an alternative custom watchlist explicitly
python src/main.py --watchlist data/watchlists/rifles.txt

```

---

## 💻 Cross-Platform Engineering Quirks

### Windows Unicode Constraints

Steam item names heavily utilize special characters like trademark notation symbols (`™`) for StatTrak items.

* To safeguard execution across different host environments, all native file readers (`open()`) explicitly define `encoding="utf-8"`.
* This completely overrides arbitrary system locales (e.g., Windows default `cp1252`), preventing unexpected `UnicodeDecodeError` crashes during production loops.

```

```