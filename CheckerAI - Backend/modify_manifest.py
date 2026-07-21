import json

manifest_path = "grading_results/dataset_15925/checked_copy_manifest.json"
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

# 1. move the marks of Q1a up by 10 (y += 10)
if "SectionB__Q1a" in manifest["questions"]:
    manifest["questions"]["SectionB__Q1a"]["stamp"]["y"] += 10
    print("Moved Q1a stamp up by 10")

# 2. remove the last cross on Q1a on the pdf
if "SectionB__Q1a" in manifest["questions"]:
    q1a_tc = manifest["questions"]["SectionB__Q1a"].get("ticks_crosses", [])
    for i in range(len(q1a_tc) - 1, -1, -1):
        if q1a_tc[i]["action"] == "cross":
            del q1a_tc[i]
            print("Removed last cross on Q1a")
            break

# 3. remove the cross on page no. 1
removed_p1_cross = False
for q_key, q_val in manifest["questions"].items():
    if "ticks_crosses" in q_val:
        original_len = len(q_val["ticks_crosses"])
        q_val["ticks_crosses"] = [
            tc for tc in q_val["ticks_crosses"]
            if not (tc["page"] == 1 and tc["action"] == "cross")
        ]
        if len(q_val["ticks_crosses"]) < original_len:
            removed_p1_cross = True
if removed_p1_cross:
    print("Removed cross on page 1")

# 4. move the marks of Q4a on page 10 down by 10
if "SectionB__Q4a" in manifest["questions"]:
    if manifest["questions"]["SectionB__Q4a"]["stamp"]["page"] == 10:
        manifest["questions"]["SectionB__Q4a"]["stamp"]["y"] -= 10
        print("Moved Q4a stamp down by 10")

# 5. remove the first top tick on page 10 as well
page10_ticks = []
for q_key, q_val in manifest["questions"].items():
    if "ticks_crosses" in q_val:
        for tc in q_val["ticks_crosses"]:
            if tc["page"] == 10 and tc["action"] == "tick":
                page10_ticks.append((tc, q_val["ticks_crosses"]))

if page10_ticks:
    # Sort by Y descending (highest Y is at the top of the page in ReportLab coordinates)
    page10_ticks.sort(key=lambda x: x[0]["y"], reverse=True)
    top_tick, tick_list = page10_ticks[0]
    tick_list.remove(top_tick)
    print("Removed top tick on page 10")

with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)
