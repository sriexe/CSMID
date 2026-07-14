import sys
import argparse
from src.collection_manager import CollectionManager

def cmd_collect(args):
    manager = CollectionManager()
    
    # Single Skin Mode
    if args.skin:
        exit_code = manager.collect_skin(args.skin)
        sys.exit(exit_code)
        
    # Watchlist Queue Mode
    if args.watchlist:
        # Construct path to watchlist file (e.g., data/watchlists/all_weapons.txt)
        watchlist_path = f"data/watchlists/{args.watchlist}.txt"
        
        exit_code = manager.collect_queue(
            watchlist_path=watchlist_path,
            resume=args.resume,
            since_hours=args.since_hours
        )
        sys.exit(exit_code)

def main():
    parser = argparse.ArgumentParser(description="CSMID Data Collection CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    collect_parser = subparsers.add_parser("collect", help="Collect market data")
    collect_parser.add_argument("--skin", type=str, help="Collect a single specific skin")
    collect_parser.add_argument("--watchlist", type=str, help="Watchlist name (e.g., all_weapons)")
    collect_parser.add_argument("--resume", action="store_true", help="Skip skins collected recently")
    collect_parser.add_argument("--since-hours", type=int, default=20, help="Hours window for resume skip logic")
    
    args = parser.parse_args()
    
    if args.command == "collect":
        cmd_collect(args)

if __name__ == "__main__":
    main()