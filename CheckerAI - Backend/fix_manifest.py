import json

manifest_path = "grading_results/dataset_15925/checked_copy_manifest.json"
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

# Revert previous stamp modifications
manifest["questions"]["SectionB__Q1a"]["stamp"]["y"] -= 10
if manifest["questions"]["SectionB__Q4a"]["stamp"]["page"] == 10:
    manifest["questions"]["SectionB__Q4a"]["stamp"]["y"] += 10

# Apply up10 to Q1a tick
q1a_tc = manifest["questions"]["SectionB__Q1a"].get("ticks_crosses", [])
if len(q1a_tc) > 0:
    q1a_tc[0]["y"] += 300
    print("Moved Q1a tick up by 300px (up10)")

# Apply down10 to Q4a tick on page 10
q4a_tc = manifest["questions"]["SectionB__Q4a"].get("ticks_crosses", [])
for tc in q4a_tc:
    if tc["page"] == 10:
        tc["y"] -= 300
        print("Moved Q4a page 10 tick down by 300px (down10)")

with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)

