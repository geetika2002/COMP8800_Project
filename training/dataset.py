import json
from collections import Counter

INPUT = "train_v2.jsonl"
OUTPUT = "train_balanced.jsonl"

with open(INPUT, "r") as f:
    rows = [json.loads(line) for line in f]

expanded = []

for row in rows:
    label = json.loads(row["messages"][2]["content"])["intent"]

    if label == "download":
        expanded.extend([row] * 8)
    elif label == "other":
        expanded.extend([row] * 3)
    elif label == "bruteforce":
        expanded.extend([row] * 2)
    else:  # recon
        expanded.append(row)

with open(OUTPUT, "w") as f:
    for row in expanded:
        f.write(json.dumps(row) + "\n")

print(f"Wrote {len(expanded)} rows to {OUTPUT}")

# show final label counts
counts = Counter()
for row in expanded:
    label = json.loads(row["messages"][2]["content"])["intent"]
    counts[label] += 1
print(dict(counts))