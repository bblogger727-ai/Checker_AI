import json
import sys

with open("grading_results/dataset_15917/checked_copy_manifest.json") as f:
    m = json.load(f)

for q_key, q in m.get("questions", {}).items():
    if q.get("stamp", {}).get("page") == 6:
        print(f"Marks on page 6: {q_key}")
    if q.get("feedback", {}).get("page") == 6:
        print(f"Feedback on page 6: {q_key}")
        
    tcs = q.get("ticks_crosses", [])
    for i, tc in enumerate(tcs):
        page = tc.get("page")
        if page == 1:
            print(f"Page 1 tick/cross: {q_key} idx={i} x={tc['x']} y={tc['y']}")
        if page == 5:
            print(f"Page 5 tick/cross: {q_key} idx={i} x={tc['x']} y={tc['y']}")
        if page == 6:
            print(f"Page 6 tick/cross: {q_key} idx={i} x={tc['x']} y={tc['y']}")
        if page == 12:
            print(f"Page 12 tick/cross: {q_key} idx={i} x={tc['x']} y={tc['y']}")
