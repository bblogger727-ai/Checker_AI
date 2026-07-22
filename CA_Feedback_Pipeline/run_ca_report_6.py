#!/usr/bin/env python3
"""
CA Specialized Stage 6:
Generates a CLEAN, PROFESSIONAL Markdown report summarizing the feedback.
No sections, no internal metadata, just the core feedback.
"""
import os
import sys
import json
import argparse

def main():
    parser = argparse.ArgumentParser(description='CA Specialized Report Generation')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    parser.add_argument('--title', default='Audit Feedback', help='Report Title')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    
    feedback_path = os.path.join(dataset_dir, "feedback_final.json")
    
    if not os.path.exists(feedback_path):
        print(f"Error: Feedback results not found at {feedback_path}")
        sys.exit(1)
        
    with open(feedback_path, "r") as f:
        feedback_results = json.load(f)
        
    print("="*60)
    print("CA STAGE 6: Specialized Report Generation (Clean Mode)")
    print("="*60)
    
    report_md = f"# {args.title}\n\n"
    
    # Helper to flatten and sort feedback
    def _collect_questions(node, questions=None):
        if questions is None: questions = []
        if isinstance(node, dict):
            if "feedback" in node:
                questions.append(node)
            else:
                for v in node.values():
                    _collect_questions(v, questions)
        elif isinstance(node, list):
            for item in node:
                _collect_questions(item, questions)
        return questions

    all_questions = _collect_questions(feedback_results)

    # Sort questions by ID (e.g. Q1a, Q1b, Q2, etc.)
    def sort_key(q):
        qid = q.get("question_id") or q.get("question_number", "Z99")
        # Try to extract leading number
        match = re.search(r'(\d+)', str(qid))
        num = int(match.group(1)) if match else 999
        return (num, str(qid))

    import re
    all_questions.sort(key=sort_key)

    for q in all_questions:
        qid = q.get("question_id") or q.get("question_number", "Unknown")
        # Clean ID (e.g. Q1a instead of SectionB-Q1a)
        label = str(qid).split('-')[-1]
        if not label.startswith('Q'): label = f"Q{label}"
        
        ms = q.get("marks_scored", "?")
        mt = q.get("marks", "?")
        
        report_md += f"## {label}\n"
        report_md += f"**Marks Scored:** {ms} / {mt}\n\n"
        
        fb = q["feedback"]
        
        # Only show sections if they have content
        wwr = fb.get("what_went_right", "").strip()
        if wwr and wwr.lower() != "n/a":
            report_md += "### What Went Right\n"
            report_md += f"{wwr}\n\n"
            
        www = fb.get("what_went_wrong", "").strip()
        if www and www.lower() != "n/a":
            report_md += "### What Went Wrong\n"
            report_md += f"{www}\n\n"
            
        conc = fb.get("conclusion", "").strip()
        if conc and conc.lower() != "n/a":
            report_md += "### Conclusion\n"
            report_md += f"{conc}\n\n"
            
        report_md += "---\n\n"

    # Save Report
    report_path = os.path.join(dataset_dir, "ca_feedback_report.md")
    with open(report_path, "w") as f:
        f.write(report_md)
        
    print(f"✓ Feedback report saved to: {report_path}")

if __name__ == "__main__":
    main()
