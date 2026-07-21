import json
with open("grading_results/dataset_15913/checked_copy_patched_manifest.json") as f: d = json.load(f)
for key in ["SectionB__Q3a", "SectionB__Q2b", "SectionB__Q5a"]:
    q = d["questions"][key]
    print("---", key, "---")
    tcs = q.get("ticks_crosses", [])
    if key == "SectionB__Q3a": page_tcs = [(i, tc) for i, tc in enumerate(tcs) if tc["page"] == 9]
    elif key == "SectionB__Q2b": page_tcs = [(i, tc) for i, tc in enumerate(tcs) if tc["page"] == 8]
    elif key == "SectionB__Q5a": page_tcs = [(i, tc) for i, tc in enumerate(tcs) if tc["page"] == 1]
    page_tcs.sort(key=lambda x: x[1]["y"], reverse=True)
    for visual_idx, (orig_idx, tc) in enumerate(page_tcs):
        y = tc.get("y")
        action = tc.get("action")
        print(f"Visual {visual_idx+1}: Index {orig_idx}, y={y}, action={action}")

