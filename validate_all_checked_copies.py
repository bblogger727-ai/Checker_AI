import os
import json

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

print("\n" + "="*80)
print("COMPREHENSIVE AUDIT & VALIDATION OF ALL 9 DATASETS")
print("="*80)

total_passed = 0
total_failed = 0

for ds in datasets:
    dsp = os.path.join(base_dir, ds)
    manifest_path = os.path.join(dsp, "test_checked_manifest.json")
    pdf_path = os.path.join(dsp, "test_checked_copy.pdf")
    
    if not os.path.exists(manifest_path):
        print(f"\n[{ds}] ✗ Manifest file missing ({manifest_path})")
        total_failed += 1
        continue
    
    if not os.path.exists(pdf_path):
        print(f"\n[{ds}] ✗ Output PDF missing ({pdf_path})")
        total_failed += 1
        continue

    with open(manifest_path, "r", encoding="utf-8") as mf:
        manifest = json.load(mf)
    
    questions = manifest.get("questions", {})
    grand_total = manifest.get("grand_total")
    
    val_errors = []
    q_summaries = []

    for mkey, qdata in questions.items():
        obt = float(qdata.get("marks_obtained", 0) or 0)
        tot = float(qdata.get("marks_total", 0) or 0)
        if tot == 0:
            continue
        ratio = obt / tot
        
        # Rule checks
        stamp = qdata.get("stamp")
        fb = qdata.get("feedback")
        deferred_fb = qdata.get("deferred_feedback")
        ticks_crosses = qdata.get("ticks_crosses", [])

        # 1. Action vs Score Rule
        for ann in ticks_crosses:
            act = ann.get("action")
            if ratio >= 0.41 and act == "cross":
                val_errors.append(f"  ❌ {mkey} (score {obt}/{tot}={ratio:.1%}) received illegal CROSS on page {ann.get('page')}")
            elif ratio < 0.41 and act == "tick":
                val_errors.append(f"  ❌ {mkey} (score {obt}/{tot}={ratio:.1%}) received illegal TICK on page {ann.get('page')}")

        # 2. Feedback placement (1 cm gap = 28pt)
        if stamp and fb and stamp.get("page") == fb.get("page"):
            expected_fb_y = stamp["y"] - stamp["half_h_pts"] - 28.0
            actual_fb_y = fb["y"]
            if abs(expected_fb_y - actual_fb_y) > 2.0:
                val_errors.append(f"  ❌ {mkey} feedback y={actual_fb_y:.1f} differs from expected y={expected_fb_y:.1f} (1cm gap mismatch)")

        q_summaries.append({
            "key": mkey,
            "score": f"{obt}/{tot} ({ratio:.0%})",
            "stamp_p": stamp["page"] if stamp else "None",
            "fb_p": fb["page"] if fb else (f"Deferred(p{deferred_fb['page']})" if deferred_fb else "None"),
            "ann_counts": f"{sum(1 for a in ticks_crosses if a['action']=='tick')} ticks, {sum(1 for a in ticks_crosses if a['action']=='cross')} crosses"
        })

    gt_str = f"{grand_total['obtained']}/{grand_total['total']}" if grand_total else "N/A"
    if not val_errors:
        print(f"\n[{ds}] ✓ PASS (Total: {gt_str}, Questions: {len(questions)})")
        total_passed += 1
    else:
        print(f"\n[{ds}] ✗ FAIL (Total: {gt_str}, Questions: {len(questions)})")
        total_failed += 1
        for err in val_errors:
            print(err)

    for qs in q_summaries:
        print(f"   • {qs['key']:16} | Score: {qs['score']:12} | Stamp: P{qs['stamp_p']} | FB: {qs['fb_p']} | Annotations: {qs['ann_counts']}")

print("\n" + "="*80)
print(f"AUDIT SUMMARY: {total_passed} PASSED, {total_failed} FAILED out of {len(datasets)} DATASETS")
print("="*80 + "\n")
