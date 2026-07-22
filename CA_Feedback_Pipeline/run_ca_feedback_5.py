#!/usr/bin/env python3
"""
CA Specialized Stage 5:
Generates detailed feedback for each question based on student answers and actual marks.
"""
import os
import sys
import json
import argparse

pipeline_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(pipeline_dir, "..", "CheckerAI - Backend")
sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

from claude_grading.ca_feedback_generator import process_all_feedback

def main():
    parser = argparse.ArgumentParser(description='CA Specialized Feedback Generation')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    
    aligned_path = os.path.join(dataset_dir, "aligned_answers_with_marks.json")
    
    if not os.path.exists(aligned_path):
        print(f"Error: Aligned answers not found at {aligned_path}")
        sys.exit(1)
        
    with open(aligned_path, "r") as f:
        aligned_answers = json.load(f)
        
    print("="*60)
    print("CA STAGE 5: Specialized Feedback Generation")
    print("="*60)
    
    # Build cache from previous results if available
    cache = {}
    prev_feedback_path = os.path.join(dataset_dir, "feedback_final.json")
    if os.path.exists(prev_feedback_path):
        print(f"Loading previous feedback for caching from {prev_feedback_path}...")
        try:
            with open(prev_feedback_path, "r") as f:
                prev_data = json.load(f)
                
            # Helper to flatten and index previous feedback
            def _extract_feedback(node):
                if isinstance(node, dict):
                    if "feedback" in node and "student_answer" in node:
                        q_text = node.get("question_text", node.get("question", ""))
                        s_ans = node.get("student_answer")
                        m_scored = node.get("marks_scored")
                        if q_text and s_ans:
                            key = f"{q_text}_{s_ans}_{m_scored}"
                            cache[key] = node["feedback"]
                    for v in node.values(): _extract_feedback(v)
                elif isinstance(node, list):
                    for i in node: _extract_feedback(i)
            
            _extract_feedback(prev_data)
            print(f"Loaded {len(cache)} cached feedback items.")
        except Exception as e:
            print(f"Warning: Could not load cache: {e}")

    # Process feedback
    print("Generating detailed feedback for each question...")
    feedback_results = process_all_feedback(aligned_answers, cache=cache)
    
    # Save
    output_path = os.path.join(dataset_dir, "feedback_final.json")
    with open(output_path, "w") as f:
        json.dump(feedback_results, f, indent=2, ensure_ascii=False)
        
    print(f"✓ Feedback results saved to: {output_path}")
    print("\nDone. Next: run_ca_report_6.py")

if __name__ == "__main__":
    main()
