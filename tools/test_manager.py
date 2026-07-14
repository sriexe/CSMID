from collection_manager import CollectionManager

manager = CollectionManager()

stats = manager.collect_batch([
    "AK-47 | Slate",
    "USP-S | Printstream"
])

print(stats)