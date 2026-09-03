import os
import sys
import json
import traceback

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath("CheckerAI - Backend"))

from generate_checked_copy_v2 import generate_checked_copy

datasets = [
    'dataset_16064',
    'dataset_16065',
    'dataset_16076',
    'dataset_16079',
    'dataset_16086',
    'dataset_16109',
    'dataset_16110',
    'dataset_16111',
    'dataset_16157',
]

base_dir = "CheckerAI - Backend/grading_results"

results = {}

for ds in datasets:
    print(f"\n{'='*60}")
    print(f"PROCESSING {ds}")
    print(f"{'='*60}")
    dsp = os.path.join(base_dir, ds)
    
    # Locate files
    pdf_path = os.path.join(dsp, "student_answersheet.pdf")
    ocr_path = os.path.join(dsp, "ocr_output.txt")
    
    grading_path = os.path.join(dsp, "grading_final.json")
    if not os.path.exists(grading_path):
        grading_path = os.path.join(dsp, "grading_final_new.json")
    if not os.path.exists(grading_path):
        grading_path = os.path.join(dsp, "grading_final (1).json")

    aligned_path = os.path.join(dsp, "aligned_answers.json")
    if not os.path.exists(aligned_path):
        aligned_path = os.path.join(dsp, "aligned_answers_new.json")
    if not os.path.exists(aligned_path):
        aligned_path = os.path.join(dsp, "aligned_answers (1).json")

    output_pdf = os.path.join(dsp, "test_checked_copy.pdf")
    output_manifest = os.path.join(dsp, "test_checked_manifest.json")

    page_bounds_path = os.path.join(dsp, "page_bounds.json")

    try:
        manifest = generate_checked_copy(
            pdf_path=pdf_path,
            grading_json=grading_path,
            aligned_json=aligned_path,
            output_path=output_pdf,
            ocr_text_path=ocr_path if os.path.exists(ocr_path) else None,
            manifest_path=output_manifest,
            page_bounds_path=page_bounds_path if os.path.exists(page_bounds_path) else None,
        )
        if manifest is None and os.path.exists(output_manifest):
            with open(output_manifest, "r", encoding="utf-8") as _mf:
                manifest = json.load(_mf)
        
        # Validation checks
        val_errors = []
        
        # Load grading to check totals
        with open(grading_path) as gf:
            grading_data = json.load(gf)

        for mkey, qdata in manifest.get("questions", {}).items():
            obt = float(qdata.get("marks_obtained", 0) or 0)
            tot = float(qdata.get("marks_total", 0) or 0)
            if tot == 0:
                continue
            ratio = obt / tot
            
            # Rule 1: No ticks on < 41%, no crosses on >= 41%
            for ann in qdata.get("ticks_crosses", []):
                act = ann.get("action")
                if ratio >= 0.41 and act == "cross":
                    val_errors.append(f"{mkey} (score {obt}/{tot}={ratio:.1%}) received CROSS on page {ann.get('page')}")
                elif ratio < 0.41 and act == "tick":
                    val_errors.append(f"{mkey} (score {obt}/{tot}={ratio:.1%}) received TICK on page {ann.get('page')}")

            # Rule 2: Feedback placement gap
            stamp = qdata.get("stamp")
            fb = qdata.get("feedback")
            if stamp and fb and stamp.get("page") == fb.get("page"):
                expected_fb_y = stamp["y"] - stamp["half_h_pts"] - 28.0
                actual_fb_y = fb["y"]
                if abs(expected_fb_y - actual_fb_y) > 2.0:
                    val_errors.append(f"{mkey} feedback y={actual_fb_y:.1f} differs from expected y={expected_fb_y:.1f} (gap!=28pt)")

        results[ds] = {
            "status": "PASS" if not val_errors else "FAIL",
            "errors": val_errors,
            "questions_count": len(manifest.get("questions", {})),
            "grand_total": manifest.get("grand_total"),
        }
        print(f"Result for {ds}: {'✓ PASS' if not val_errors else '✗ FAIL'}")
        if val_errors:
            for err in val_errors:
                print(f"   - {err}")
    except Exception as e:
        traceback.print_exc()
        results[ds] = {
            "status": "ERROR",
            "error": str(e),
        }
        print(f"Result for {ds}: ✗ ERROR: {e}")

print("\n" + "="*60)
print("FINAL SUMMARY ACROSS ALL DATASETS")
print("="*60)
for ds, res in results.items():
    print(f"{ds:16}: {res['status']}")
    if res.get("errors"):
        for err in res["errors"]:
            print(f"   • {err}")
    elif res.get("error"):
        print(f"   • {res['error']}")
