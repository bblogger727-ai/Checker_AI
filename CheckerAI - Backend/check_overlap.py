import json

with open("grading_results/dataset_15917/checked_copy_patched_manifest.json") as f:
    m = json.load(f)

gt = m.get("grand_total")
print(f"Grand Total: x={gt['x']} y={gt['y']}")

for q_key, q in m.get("questions", {}).items():
    tcs = q.get("ticks_crosses", [])
    for i, tc in enumerate(tcs):
        if tc.get("page") == 1:
            print(f"Tick {q_key} idx {i}: x={tc['x']} y={tc['y']}")
