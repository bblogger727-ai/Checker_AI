import json
import os

def finalize_schema_v2(schema_path, marks_path, output_path):
    if not os.path.exists(schema_path) or not os.path.exists(marks_path):
        print("Error: Required files not found.")
        return

    with open(schema_path, 'r') as f:
        schema = json.load(f)
    with open(marks_path, 'r') as f:
        marks_data = json.load(f)
    
    marks_dict = marks_data.get("marks", {})
    
    # Filter function: Only keep questions if they have marks_scored > 0 in manifest
    def _filter_questions(questions_list):
        filtered = []
        for q in questions_list:
            subp = q.get("subpart")
            # If subpart exists in manifest and marks > 0, keep it
            ms_entry = marks_dict.get(subp, {})
            ms = ms_entry.get("scored", 0) if isinstance(ms_entry, dict) else ms_entry
            if ms > 0:
                # Also ensure marks_allotted is updated
                ma = ms_entry.get("allotted", 0) if isinstance(ms_entry, dict) else 0
                q["marks_scored"] = ms
                q["marks"] = ma
                filtered.append(q)
            else:
                print(f"Skipping unattempted question: {subp} (Marks: {ms})")
        return filtered

    new_case_studies = {}
    for cs_key, cs_data in schema.get("CaseStudies", {}).items():
        # Check if the case study itself has marks > 0 (e.g. C1, C2)
        # But safer to check subparts.
        filtered_qs = _filter_questions(cs_data.get("questions", []))
        if filtered_qs:
            new_case_studies[cs_key] = {"questions": filtered_qs}
        else:
            print(f"Skipping unattempted Case Study: {cs_key}")

    final_schema = {"CaseStudies": new_case_studies}
    
    with open(output_path, 'w') as f:
        json.dump(final_schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Final filtered schema saved to: {output_path}")

if __name__ == "__main__":
    dataset_id = "DMCI_TEST"
    base = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results"
    schema_p = f"{base}/dataset_{dataset_id}/schema_with_marks_enriched.json"
    marks_p = f"{base}/dataset_{dataset_id}/student_marks.json"
    out_p = f"{base}/dataset_{dataset_id}/schema_final_attempted_only.json"
    finalize_schema_v2(schema_p, marks_p, out_p)
    
    # Also overwrite the one alignment uses
    import shutil
    shutil.copy(out_p, os.path.join(os.path.dirname(schema_p), "schema_with_answers.json"))
    print(f"✓ Overwrote original schema_with_answers.json for Stage 4.")
