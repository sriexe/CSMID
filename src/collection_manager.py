from collector import MarketCollector


class CollectionManager:
    def __init__(self):
        self.collector = MarketCollector()

    def collect_skin(self, market_hash_name):
        return self.collector.collect(market_hash_name)

    def collect_batch(self, skins):
        stats = {
            "collected": 0,
            "failed": 0
        }

        for skin in skins:
            try:
                self.collector.collect(skin)
                stats["collected"] += 1
            except Exception as e:
                print(f"❌ {skin}: {e}")
                stats["failed"] += 1

        return stats