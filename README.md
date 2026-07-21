
🔍 Key File Explanations:
main.py: Your "Price Update" engine. It strictly looks at the items you are already tracking and grabs their latest market price. Contains guardrails (e.g., skips if scraped < 12 hours ago) to conserve API credits.

run_discovery.py: Your "Radar". It scans the Steam Market for popular items (up to 500 items deep) and adds any newly discovered skins to your database. It ends by pinging your phone with a summary.

src/notifier.py: The bridge to your phone. Uses ntfy.sh to send priority alerts without needing complex developer accounts.

⚙️ Prerequisites
Before running the project locally or on GitHub, you need the following free accounts:

Supabase: Free PostgreSQL database to store your item list and price history.

ScrapingAnt: Web scraping API to bypass Steam's rate limits.

ntfy: A free app on iOS/Android for push notifications. Create a unique topic name in the app (e.g., csmid-tracker-myname).

🚀 Installation & Local Setup
1. Clone the repository
Bash
git clone [https://github.com/YOUR-USERNAME/CSMID.git](https://github.com/YOUR-USERNAME/CSMID.git)
cd CSMID
2. Set up the Python Environment
It is recommended to use Python 3.11+.

Bash
# Create a virtual environment
python -m venv venv

# Activate virtual environment (Windows)
venv\\Scripts\\activate
# Activate virtual environment (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
3. Environment Variables
Create a .env file in the root directory (or export them in your terminal) with the following keys:

Code snippet
SUPABASE_DB_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT].supabase.co:5432/postgres
SCRAPINGANT_API_KEY=your_scrapingant_key_here
NTFY_TOPIC=your_secret_ntfy_topic_name
🏃‍♂️ How to Run the Scripts Locally
Depending on what you want to achieve, run one of the two main scripts from your terminal:

To find new skins and add them to your tracking list:

Bash
python run_discovery.py
(You will receive a phone notification with head/tail samples once this finishes).

To update the prices of the skins you are already tracking:

Bash
python main.py
(Ensure it has been at least 12 hours since your last scrape, or adjust the hours_threshold inside main.py).

☁️ Cloud Automation (GitHub Actions)
This project is designed to run on autopilot in the cloud. You do not need to leave your PC on!

Go to your GitHub Repository -> Settings -> Secrets and variables -> Actions.

Add your environment variables (SUPABASE_DB_URL, SCRAPINGANT_API_KEY, NTFY_TOPIC) as Repository Secrets.

The workflows in .github/workflows/ will automatically execute:

Discovery Daemon: Runs every Sunday at midnight UTC to find new skins.

Scraper Daemon: Runs every 6-12 hours to build your historical price charts.

🔮 Roadmap: Phase 2 (Month 3+)
Once sufficient data (approx. 3 months of 6-hour price intervals) is collected, the system architecture will shift from Data Collection to Data Prediction:

Transition from fixed schedules to Volatility-Based Scraping (scraping high-volume items faster than stable cases).

Implementation of a predict.py module using Pandas/Statsmodels to calculate Moving Averages and RSI.

Automated Buy/Sell signal notifications based on arbitrage opportunities.
"""

with open('README.md', 'w', encoding='utf-8') as f:
f.write(markdown_content)

print("[file-tag: code-generated-file-readme-md-1]")


```text?code_stdout&code_event_index=1
[file-tag: code-generated-file-readme-md-1]

Your Markdown file is ready
MD icon
README
 MD 
Open

I have generated a clean, professional README.md that perfectly outlines your current project architecture. It clearly breaks down the difference between main.py and run_discovery.py, guides anyone (like your friends) through local setup and environment variables, and notes the future transition into the predictive modeling phase!





Gemini is AI and can make mistakes.

# 📈 CSMID - CS2 Market Intelligence Engine

An automated, cloud-hosted tracking and market intelligence engine for Counter-Strike 2 skins. This system automatically discovers trending items on the Steam Community Market, logs their prices into a Postgres database (Supabase) at regular intervals, and sends push notifications to your phone.

---

## 🏗️ Project Structure & File Roles

The repository is structured to separate cloud workflows, source logic, and executable entry points.

```text
CSMID/
│
├── .github/workflows/
│   ├── discovery.yml      # GitHub Action: Runs run_discovery.py every Sunday
│   └── scraper.yml        # GitHub Action: Runs main.py every 6-12 hours
│
├── src/
│   ├── database.py        # Connects to Supabase; manages inserts to tracked_items & market_history
│   ├── discoverer.py      # Contains logic to parse Steam market pages for top items
│   └── notifier.py        # Handles instant phone push notifications via ntfy.sh
│
├── main.py                # 🟢 THE PRICE SCRAPER: Fetches live prices for skins already in the database
├── run_discovery.py       # 🔵 THE DISCOVERER: Finds new trending skins on Steam and adds them to tracking
├── requirements.txt       # Python dependencies (requests, psycopg2-binary, etc.)
└── README.md              # Project documentation
```

### 🔍 Key File Explanations:
*   **`main.py`**: Your "Price Update" engine. It strictly looks at the items you are already tracking and grabs their latest market price. Contains guardrails (e.g., skips if scraped < 12 hours ago) to conserve API credits.
*   **`run_discovery.py`**: Your "Radar". It scans the Steam Market for popular items (up to 500 items deep) and adds any newly discovered skins to your database. It ends by pinging your phone with a summary.
*   **`src/notifier.py`**: The bridge to your phone. Uses `ntfy.sh` to send priority alerts without needing complex developer accounts.

---

## ⚙️ Prerequisites

Before running the project locally or on GitHub, you need the following free accounts:
1.  **[Supabase](https://supabase.com/)**: Free PostgreSQL database to store your item list and price history.
2.  **[ScrapingAnt](https://scrapingant.com/)**: Web scraping API to bypass Steam's rate limits.
3.  **[ntfy](https://ntfy.sh/)**: A free app on iOS/Android for push notifications. Create a unique topic name in the app (e.g., `csmid-tracker-myname`).

---

## 🚀 Installation & Local Setup

### 1. Clone the repository
```bash
git clone https://github.com/YOUR-USERNAME/CSMID.git
cd CSMID
```

### 2. Set up the Python Environment
It is recommended to use Python 3.11+.
```bash
# Create a virtual environment
python -m venv venv

# Activate virtual environment (Windows)
venv\Scripts\activate
# Activate virtual environment (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory (or export them in your terminal) with the following keys:
```env
SUPABASE_DB_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT].supabase.co:5432/postgres
SCRAPINGANT_API_KEY=your_scrapingant_key_here
NTFY_TOPIC=your_secret_ntfy_topic_name
```

---

## 🏃‍♂️ How to Run the Scripts Locally

Depending on what you want to achieve, run one of the two main scripts from your terminal:

**To find new skins and add them to your tracking list:**
```bash
python run_discovery.py
```
*(You will receive a phone notification with head/tail samples once this finishes).*

**To update the prices of the skins you are already tracking:**
```bash
python main.py
```
*(Ensure it has been at least 12 hours since your last scrape, or adjust the `hours_threshold` inside `main.py`).*

---

## ☁️ Cloud Automation (GitHub Actions)

This project is designed to run on autopilot in the cloud. You do not need to leave your PC on!

1. Go to your GitHub Repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Add your environment variables (`SUPABASE_DB_URL`, `SCRAPINGANT_API_KEY`, `NTFY_TOPIC`) as **Repository Secrets**.
3. The workflows in `.github/workflows/` will automatically execute:
   * **Discovery Daemon**: Runs every Sunday at midnight UTC to find new skins.
   * **Scraper Daemon**: Runs every 6-12 hours to build your historical price charts.

---

## 🔮 Roadmap: Phase 2 (Month 3+)
Once sufficient data (approx. 3 months of 6-hour price intervals) is collected, the system architecture will shift from *Data Collection* to *Data Prediction*:
* Transition from fixed schedules to **Volatility-Based Scraping** (scraping high-volume items faster than stable cases).
* Implementation of a `predict.py` module using Pandas/Statsmodels to calculate Moving Averages and RSI.
* Automated Buy/Sell signal notifications based on arbitrage opportunities.
README.md
Displaying README.md.
