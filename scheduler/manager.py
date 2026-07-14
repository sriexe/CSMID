from state import load_state
from collection_queue import get_batch

state = load_state()

batch, new_index, total = get_batch(
    state["current_index"],
    state["batch_size"]
)

print("=" * 60)
print(f"Current Index : {state['current_index']}")
print(f"Batch Size    : {state['batch_size']}")
print(f"Total Skins   : {total}")
print()

print("Today's Queue")

for skin in batch[:10]:
    print("-", skin)

print()

print(f"...and {len(batch)-10} more")

print()

print("Next Index:", new_index)