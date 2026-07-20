import sys
import os

# Ensure Python can find our source directories
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Import your database manager class
# (Change 'database' to the actual filename where your DatabaseManager code lives)
from database import DatabaseManager 

def main():
    print("🚀 Connecting to Supabase and setting up tables...")
    try:
        db = DatabaseManager()
        print("\n🎉 Everything is set up! Your cloud database is fully initialized.")
        db.close()
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")

if __name__ == "__main__":
    main()