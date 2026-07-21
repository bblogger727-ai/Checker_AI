import json

with open("grading_results/dataset_15917/checked_copy_manifest.json") as f:
    m = json.load(f)

for q_key, q in m.get("questions", {}).items():
    tcs = q.get("ticks_crosses", [])
    for i, tc in enumerate(tcs):
        page = tc.get("page")
        if page == 12:
            print(f"Page 12 tick/cross: {q_key} idx={i} x={tc['x']} y={tc['y']}")
