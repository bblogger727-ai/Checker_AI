import json
import os

def enrich_schema_with_marks(schema_path, marks_path, output_path):
    if not os.path.exists(schema_path) or not os.path.exists(marks_path):
        print("Error: Required files not found.")
        return

    with open(schema_path, 'r') as f:
        schema = json.load(f)
    with open(marks_path, 'r') as f:
        marks_data = json.load(f)
    
    marks_dict = marks_data.get("marks", {})
    
    def _enrich(node):
        if isinstance(node, dict):
            # Try to get subpart or construct logical ID
            subp = node.get("subpart")
            if subp and subp in marks_dict:
                m = marks_dict[subp]
                node["marks_scored"] = m.get("scored")
                node["marks"] = m.get("allotted")
                print(f"Enriched {subp}: {node['marks_scored']}/{node['marks']}")
            
            for v in node.values(): _enrich(v)
        elif isinstance(node, list):
            for i in node: _enrich(i)

    _enrich(schema)
    
    with open(output_path, 'w') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Enriched schema saved to: {output_path}")

if __name__ == "__main__":
    dataset_id = "DMCI_TEST"
    base = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results"
    schema_p = f"{base}/dataset_{dataset_id}/schema_with_answers_fixed.json"
    marks_p = f"{base}/dataset_{dataset_id}/student_marks.json"
    out_p = f"{base}/dataset_{dataset_id}/schema_with_marks_enriched.json"
    enrich_schema_with_marks(schema_p, marks_p, out_p)
    
    # Overwrite the original schema used by alignment
    import shutil
    shutil.copy(out_p, os.path.join(os.path.dirname(schema_p), "schema_with_answers.json"))
    print(f"✓ Overwrote original schema_with_answers.json for Stage 4.")
