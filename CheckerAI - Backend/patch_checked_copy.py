#!/usr/bin/env python3
"""
patch_checked_copy.py — Correction tool for Stage 7 checked copies.

Given a manifest JSON produced by generate_checked_copy_v2.py, this script lets
you correct marks, feedback text, or individual tick/cross annotations for any
question.  The full overlay is rebuilt from saved manifest coordinates — no LLM
calls, no image analysis, no placement recalculation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PYTHON API  (for frontend / backend integration)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  from patch_checked_copy import get_manifest_summary, apply_patch

  # 1. Get a structured summary to populate the frontend UI
  summary = get_manifest_summary("path/to/checked_copy_manifest.json")

  # 2. Build a corrections dict and apply it
  corrections = {
      "SectionB__Q1": {
          "marks_obtained": 5.0,                     # change marks
          "feedback_text":  "Include interest workings",  # change feedback
      },
      "SectionA__Q3a": {
          "ticks_crosses": [                         # replace all ticks/crosses
              {"index": 0, "action": "cross"},       # flip first one to cross
          ],
          "delete_tick_indices": [2, 3],             # delete by index (0-based)
      }
  }
  output_pdf = apply_patch(
      manifest_path = "path/to/checked_copy_manifest.json",
      corrections   = corrections,
      output_path   = "path/to/checked_copy_patched.pdf",   # optional
  )
  # Returns the path to the patched PDF.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLI USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Fix marks
  python3 patch_checked_copy.py \\
      --manifest  grading_results/dataset_15244/checked_copy_manifest.json \\
      --fix-marks SectionB__Q1 5/10 \\
      --output    grading_results/dataset_15244/checked_copy_patched.pdf

  # Fix feedback text
  python3 patch_checked_copy.py \\
      --manifest    grading_results/dataset_15244/checked_copy_manifest.json \\
      --fix-feedback SectionB__Q1 "Include interest workings" \\
      --output      grading_results/dataset_15244/checked_copy_patched.pdf

  # Fix both at once for multiple questions
  python3 patch_checked_copy.py \\
      --manifest     grading_results/dataset_15244/checked_copy_manifest.json \\
      --fix-marks    SectionB__Q1 5/10 \\
      --fix-feedback SectionB__Q1 "Include interest workings" \\
      --fix-marks    SectionA__Q3 12/16 \\
      --output       grading_results/dataset_15244/checked_copy_patched.pdf

  # Apply corrections from a JSON file (for batch / frontend use)
  python3 patch_checked_copy.py \\
      --manifest          grading_results/dataset_15244/checked_copy_manifest.json \\
      --corrections-json  corrections.json \\
      --output            grading_results/dataset_15244/checked_copy_patched.pdf
"""

import os
import io
import sys
import json
import copy
import random
import argparse
from datetime import datetime

# ── Drawing functions imported from generate_checked_copy_v2 ──────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

try:
    from generate_checked_copy_v2 import (
        _register_fonts,
        _draw_tick,
        _draw_cross,
        _draw_marks_stamp,
        _draw_total_marks_stamp,
        _draw_bold_text,
        _draw_circle,
        FONT_PATH,
    )
except ImportError as e:
    print(f"ERROR: Could not import drawing functions from generate_checked_copy_v2.py\n  {e}")
    sys.exit(1)

from reportlab.pdfgen import canvas
from reportlab.lib.colors import red
from pypdf import PdfReader, PdfWriter


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_manifest_summary(manifest_path: str) -> dict:
    """
    Return a structured summary of the manifest for frontend display.

    Schema of returned dict:
    {
      "source_pdf":  str,
      "output_pdf":  str,
      "generated_at": str,
      "grand_total": {
          "obtained": float,
          "total":    float,
      },
      "questions": {
          "SectionB__Q1": {
              "manifest_key":   "SectionB__Q1",
              "section":        "SectionB",
              "q_id":           "Q1",
              "q_num":          "1",
              "display_name":   "Section B — Q1",
              "marks_obtained": float,
              "marks_total":    float,
              "feedback_text":  str | None,
              "has_stamp":      bool,
              "has_feedback":   bool,
              "ticks_count":    int,
              "crosses_count":  int,
              "ticks_crosses":  list[dict],  # full list with page/x/y/action/size
              "delete_tick_indices": list[int],
              "move_tick_indices": list[dict], # e.g. [{"index": 0, "direction": "down3"}]
              "marks_page": int,
          },
          ...
      }
    }
    """
    manifest = _load_manifest(manifest_path)

    gt = manifest.get("grand_total") or {}
    summary = {
        "source_pdf":   manifest.get("source_pdf", ""),
        "output_pdf":   manifest.get("output_pdf", ""),
        "generated_at": manifest.get("generated_at", ""),
        "grand_total": {
            "obtained": gt.get("obtained", 0.0),
            "total":    gt.get("total",    0.0),
        },
        "questions": {},
    }

    for mkey, q in manifest.get("questions", {}).items():
        section    = q.get("section", "")
        q_id       = q.get("q_id",    mkey)
        q_num      = q.get("q_num",   q_id.replace("Q", ""))
        tcs        = q.get("ticks_crosses", [])
        fb         = q.get("feedback") or {}

        # Human-readable label: "Section B — Q1"
        sec_label = section.replace("Section", "Section ").strip() if section else ""
        q_label   = q_num if q_num.startswith("Q") else f"Q{q_num}"
        display   = f"{sec_label} — {q_label}" if sec_label else q_label

        summary["questions"][mkey] = {
            "manifest_key":   mkey,
            "section":        section,
            "q_id":           q_id,
            "q_num":          q_num,
            "display_name":   display,
            "marks_obtained": q.get("marks_obtained", 0.0),
            "marks_total":    q.get("marks_total",    0.0),
            "feedback_text":  fb.get("text") if fb else None,
            "has_stamp":      q.get("stamp") is not None,
            "has_feedback":   fb is not None and bool(fb.get("text")),
            "ticks_count":    sum(1 for t in tcs if t.get("action") == "tick"),
            "crosses_count":  sum(1 for t in tcs if t.get("action") == "cross"),
            "ticks_crosses":  tcs,
        }

    return summary


def apply_patch(
    manifest_path: str,
    corrections:   dict,
    output_path:   str | None = None,
) -> str:
    """
    Apply corrections to a checked-copy PDF and save the patched result.

    Parameters
    ----------
    manifest_path : str
        Path to the manifest JSON produced by generate_checked_copy_v2.py.
    corrections : dict
        Dict keyed by manifest question key (e.g. "SectionB__Q1").
        Each value is a dict with any of:
          - "marks_obtained"  : float  — new marks obtained
          - "marks_total"     : float  — new marks total (usually unchanged)
          - "feedback_text"   : str | None — new feedback text (None removes it)
          - "ticks_crosses"   : list[dict] — either a full replacement list or
                                a list of {"index": int, "action": "tick"|"cross"}
                                to flip individual annotations
    output_path : str | None
        Where to save the patched PDF.  Defaults to
        <original_output_stem>_patched.pdf beside the manifest.

    Returns
    -------
    str
        Absolute path to the saved patched PDF.
    """
    manifest     = _load_manifest(manifest_path)
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))

    # ── Resolve output path ──────────────────────────────────────────────────
    if output_path is None:
        original_out = manifest.get("output_pdf", "checked_copy.pdf")
        stem         = os.path.splitext(os.path.basename(original_out))[0]
        output_path  = os.path.join(manifest_dir, f"{stem}_patched.pdf")

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # ── Apply corrections to a deep copy of the manifest ────────────────────
    patched = _apply_corrections_to_manifest(manifest, corrections)

    # ── Re-draw overlay from patched manifest ────────────────────────────────
    source_pdf = manifest.get("source_pdf", "")
    if not os.path.isabs(source_pdf):
        # Relative paths in the manifest may be relative to the manifest dir
        # OR to the backend root (_HERE). Try both, prefer whichever exists.
        candidate_manifest = os.path.join(manifest_dir, source_pdf)
        candidate_here     = os.path.join(_HERE, source_pdf)
        if os.path.exists(candidate_manifest):
            source_pdf = candidate_manifest
        elif os.path.exists(candidate_here):
            source_pdf = candidate_here
        else:
            source_pdf = candidate_manifest   # let the next check raise clearly
    if not os.path.exists(source_pdf):
        raise FileNotFoundError(f"Source PDF not found: {source_pdf}")

    _redraw_from_manifest(source_pdf, patched, output_path)

    # ── Save an updated manifest alongside the patched PDF ──────────────────
    patched["output_pdf"]    = output_path
    patched["generated_at"]  = datetime.now().isoformat()
    patched["patched_from"]  = manifest_path

    stem_out      = os.path.splitext(output_path)[0]
    manifest_out  = stem_out + "_manifest.json"
    with open(manifest_out, "w", encoding="utf-8") as f:
        json.dump(patched, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Patched manifest → {manifest_out}")

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_manifest(path: str) -> dict:
    """Load and return a manifest JSON, raising clear errors on failure."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_corrections_to_manifest(manifest: dict, corrections: dict) -> dict:
    """
    Deep-copy the manifest and apply all corrections in-place on the copy.
    Also recomputes the grand total if any marks change.
    """
    m = copy.deepcopy(manifest)

    marks_delta = 0.0   # total change in obtained marks across all questions

    for mkey, corr in corrections.items():
        if mkey not in m["questions"]:
            print(f"  ⚠ Warning: question key '{mkey}' not found in manifest — skipping")
            continue

        q = m["questions"][mkey]

        # ── Marks change ───────────────────────────────────────────────────
        if corr.get("remove_stamp"):
            q["stamp"] = None
            print(f"  ❌ {mkey}: marks stamp removed")
            
        if "marks_obtained" in corr:
            old_obtained   = float(q.get("marks_obtained", 0))
            new_obtained   = float(corr["marks_obtained"])
            marks_delta   += new_obtained - old_obtained
            q["marks_obtained"] = new_obtained
            print(f"  📝 {mkey}: marks_obtained {old_obtained} → {new_obtained}")

        if "marks_total" in corr:
            q["marks_total"] = float(corr["marks_total"])

        # ── Feedback change ───────────────────────────────────────────────
        if "feedback_text" in corr:
            new_fb = corr["feedback_text"]
            if new_fb is None or str(new_fb).strip() == "":
                # Remove feedback
                q["feedback"] = None
                print(f"  💬 {mkey}: feedback removed")
            else:
                if q.get("feedback") is None:
                    # No existing feedback recorded — can't place without coords.
                    # We'll use a placeholder position; warn the user.
                    print(f"  ⚠ {mkey}: no existing feedback position in manifest. "
                          "New feedback will be placed at a default position.")
                    q["feedback"] = {
                        "text":      str(new_fb),
                        "page":      q.get("stamp", {}).get("page", 1) if q.get("stamp") else 1,
                        "x":         None,   # sentinel → use default
                        "y":         None,
                        "font_size": None,
                        "scale":     q.get("stamp", {}).get("scale", 1.0) if q.get("stamp") else 1.0,
                    }
                else:
                    old_txt = q["feedback"].get("text", "")
                    q["feedback"]["text"] = str(new_fb)
                    print(f"  💬 {mkey}: feedback updated")
                    print(f"       old: {old_txt!r}")
                    print(f"       new: {new_fb!r}")

        # ── Delete individual ticks/crosses by index (0-based) ──────────
        # Processed FIRST so deletions are resolved before any flip-by-index.
        if "delete_tick_indices" in corr:
            to_delete = set(int(i) for i in corr["delete_tick_indices"])
            existing  = q.get("ticks_crosses", [])
            before    = len(existing)
            q["ticks_crosses"] = [
                tc for i, tc in enumerate(existing) if i not in to_delete
            ]
            after = len(q["ticks_crosses"])
            print(f"  🗑 {mkey}: deleted {before - after} tick/cross annotation(s) "
                  f"at index(es) {sorted(to_delete)}")

        if "move_tick_indices" in corr:
            import re
            existing = q.get("ticks_crosses", [])
            for move in corr["move_tick_indices"]:
                idx = int(move["index"])
                direction_str = move["direction"].strip().lower()
                if 0 <= idx < len(existing):
                    match_obj = re.match(r'([a-z]+)(\d*)', direction_str)
                    if match_obj:
                        dir_name = match_obj.group(1)
                        multiplier = int(match_obj.group(2)) if match_obj.group(2) else 1
                        dist = 30 * multiplier
                        if dir_name == "up": existing[idx]["y"] += dist
                        elif dir_name == "down": existing[idx]["y"] -= dist
                        elif dir_name == "left": existing[idx]["x"] -= dist
                        elif dir_name == "right": existing[idx]["x"] += dist
                    print(f"  ↔ {mkey}: moved tick/cross[{idx}] {direction_str}")
                else:
                    print(f"  ⚠ {mkey}: move index {idx} out of range")

        # ── Tick / Cross changes ───────────────────────────────────────────────────────────────
        if "ticks_crosses" in corr:
            tc_corr = corr["ticks_crosses"]
            existing = q.get("ticks_crosses", [])

            # Check if it's a full replacement (dicts with page/x/y/action/size)
            # or a partial flip list (dicts with index + action)
            if tc_corr and all("index" in c for c in tc_corr):
                # Partial flip: flip individual entries by index
                for flip in tc_corr:
                    idx = int(flip["index"])
                    if 0 <= idx < len(existing):
                        old_action = existing[idx]["action"]
                        existing[idx]["action"] = flip["action"]
                        print(f"  ✓ {mkey}: tick/cross[{idx}] {old_action} → {flip['action']}")
                    else:
                        print(f"  ⚠ {mkey}: tick/cross index {idx} out of range")
            else:
                # Full replacement list (must have page/x/y/action/size)
                q["ticks_crosses"] = tc_corr
                print(f"  ✓ {mkey}: ticks_crosses fully replaced ({len(tc_corr)} items)")

        # ── Move marks / feedback to a different page ──────────────────────────────
        if "marks_page" in corr:
            new_page = int(corr["marks_page"])
            if q.get("stamp"):
                q["stamp"]["page"] = new_page
            if q.get("feedback"):
                q["feedback"]["page"] = new_page
            print(f"  📄 {mkey}: moved marks/feedback to page {new_page}")

        # ── Move Stamp ─────────────────────────────────────────────────────────
        if "move_stamp" in corr:
            move_corr = corr["move_stamp"]
            for move in move_corr:
                direction = move["direction"]
                multiplier = move.get("multiplier", 1)
                dist = 30 * multiplier
                
                stamp = q.get("stamp")
                if stamp:
                    if direction == "up":
                        stamp["y"] += dist
                    elif direction == "down":
                        stamp["y"] -= dist
                    elif direction == "left":
                        stamp["x"] -= dist
                    elif direction == "right":
                        stamp["x"] += dist
                    print(f"  ✓ {mkey}: stamp moved {direction}{multiplier if multiplier > 1 else ''} ({dist}px)")
                else:
                    print(f"  ⚠ {mkey}: no stamp to move")

        # ── Move Feedback ─────────────────────────────────────────────────────────
        if "move_feedback" in corr:
            move_corr = corr["move_feedback"]
            for move in move_corr:
                direction = move["direction"]
                multiplier = move.get("multiplier", 1)
                dist = 30 * multiplier
                
                fb = q.get("feedback")
                if fb:
                    if fb.get("y") is None or fb.get("x") is None:
                        print(f"  ⚠ {mkey}: feedback has no existing coords to move")
                        continue
                    if direction == "up":
                        fb["y"] += dist
                    elif direction == "down":
                        fb["y"] -= dist
                    elif direction == "left":
                        fb["x"] -= dist
                    elif direction == "right":
                        fb["x"] += dist
                    print(f"  ✓ {mkey}: feedback moved {direction}{multiplier if multiplier > 1 else ''} ({dist}px)")
                else:
                    print(f"  ⚠ {mkey}: no feedback to move")

        # ── Move Tick / Cross ──────────────────────────────────────────────────
        if "move_tick" in corr:
            move_corr = corr["move_tick"]
            existing = q.get("ticks_crosses", [])
            for move in move_corr:
                idx = move["index"]
                direction = move["direction"]
                multiplier = move.get("multiplier", 1)
                dist = 30 * multiplier
                
                if 0 <= idx < len(existing):
                    if direction == "up":
                        existing[idx]["y"] += dist
                    elif direction == "down":
                        existing[idx]["y"] -= dist
                    elif direction == "left":
                        existing[idx]["x"] -= dist
                    elif direction == "right":
                        existing[idx]["x"] += dist
                    print(f"  ✓ {mkey}: tick/cross[{idx}] moved {direction}{multiplier if multiplier > 1 else ''} ({dist}px)")
                else:
                    print(f"  ⚠ {mkey}: move_tick index {idx} out of range")

    # ── Recompute grand total ─────────────────────────────────────────────────
    if marks_delta != 0.0 and m.get("grand_total") is not None:
        old_grand = m["grand_total"]["obtained"]
        m["grand_total"]["obtained"] = old_grand + marks_delta
        print(f"  Σ Grand total: {old_grand} → {m['grand_total']['obtained']} "
              f"(Δ {marks_delta:+.1f})")

    return m


def _build_page_plan(manifest: dict) -> dict:
    """
    Index all manifest annotations by page number.

    Returns: {page_num: [drawing_item, ...]}

    Each drawing_item is a dict with a "type" field:
      "grand_total"  — grand-total stamp
      "stamp"        — per-question marks stamp
      "feedback"     — feedback text
      "tick_cross"   — individual tick or cross
    """
    plan: dict = {}

    # Grand total
    gt = manifest.get("grand_total")
    if gt:
        plan.setdefault(int(gt["page"]), []).append({
            "type":    "grand_total",
            "data":    gt,
        })

    # Per-question annotations
    for mkey, q in manifest.get("questions", {}).items():

        # Stamp
        stamp = q.get("stamp")
        if stamp:
            plan.setdefault(int(stamp["page"]), []).append({
                "type":           "stamp",
                "manifest_key":   mkey,
                "marks_obtained": q.get("marks_obtained", 0.0),
                "marks_total":    q.get("marks_total",    0.0),
                "data":           stamp,
            })

        # Feedback
        fb = q.get("feedback")
        if fb and fb.get("text"):
            plan.setdefault(int(fb["page"]), []).append({
                "type":         "feedback",
                "manifest_key": mkey,
                "data":         fb,
            })

        # Ticks & crosses
        for tc in q.get("ticks_crosses", []):
            plan.setdefault(int(tc["page"]), []).append({
                "type":         "tick_cross",
                "manifest_key": mkey,
                "data":         tc,
            })

    return plan


def _redraw_from_manifest(
    source_pdf:  str,
    manifest:    dict,
    output_path: str,
):
    """
    Rebuild the full annotation overlay from manifest coordinates and merge
    it with the (unannotated) source PDF.

    All positions come directly from the manifest — no image analysis,
    no LLM calls, no placement recalculation.
    """
    print(f"\n{'='*62}")
    print("  PATCH — Rebuilding annotation overlay from manifest")
    print(f"{'='*62}")
    print(f"  Source  : {source_pdf}")
    print(f"  Output  : {output_path}")

    font_name  = _register_fonts()
    page_plan  = _build_page_plan(manifest)

    reader     = PdfReader(source_pdf)
    num_pages  = len(reader.pages)
    page_dims  = [(float(p.mediabox.width), float(p.mediabox.height))
                  for p in reader.pages]

    packet = io.BytesIO()
    c      = canvas.Canvas(packet)

    for page_idx in range(num_pages):
        page_num     = page_idx + 1
        pdf_w, pdf_h = page_dims[page_idx]
        c.setPageSize((pdf_w, pdf_h))

        items = page_plan.get(page_num, [])
        if not items:
            c.showPage()
            continue

        # Sort: grand_total first, then stamps, then feedback, then ticks/crosses
        _order = {"grand_total": 0, "stamp": 1, "feedback": 2, "tick_cross": 3}
        items  = sorted(items, key=lambda it: _order.get(it["type"], 9))

        for item in items:
            t    = item["type"]
            data = item["data"]

            # ── Grand-total stamp ──────────────────────────────────────────
            if t == "grand_total":
                scale = float(data.get("scale", pdf_h / 842.0))
                _draw_total_marks_stamp(
                    c,
                    float(data["x"]),
                    float(data["y"]),
                    float(data["obtained"]),
                    float(data["total"]),
                    font_name,
                    scale=scale,
                )
                print(f"  ✓ P{page_num:>2} Grand total stamp  "
                      f"{data['obtained']}/{data['total']}")

            # ── Per-question marks stamp ──────────────────────────────────
            elif t == "stamp":
                scale = float(data.get("scale", pdf_h / 842.0))
                mo    = float(item["marks_obtained"])
                mt    = float(item["marks_total"])
                _draw_marks_stamp(
                    c,
                    float(data["x"]),
                    float(data["y"]),
                    mo, mt,
                    font_name,
                    scale=scale,
                )
                print(f"  ✓ P{page_num:>2} {item['manifest_key']} stamp  {mo}/{mt}")

            # ── Feedback text ─────────────────────────────────────────────
            elif t == "feedback":
                text = data.get("text", "")
                if not text:
                    continue

                x         = data.get("x")
                y         = data.get("y")
                scale     = float(data.get("scale", pdf_h / 842.0))
                font_size = data.get("font_size") or int(11 * scale)

                # Sentinel: feedback added via correction but had no prior position
                if x is None or y is None:
                    x = pdf_w * 0.08
                    y = pdf_h * 0.12   # near bottom — safe default
                    print(f"  ⚠ P{page_num:>2} {item['manifest_key']} feedback: "
                          "no saved position, using default")

                x = float(x)
                y = float(y)

                lines          = text.split("\n")
                est_char_w     = font_size * 0.60
                fb_text_w_pt   = max(len(ln) for ln in lines) * est_char_w
                num_lines      = len(lines)
                bg_h           = num_lines * font_size * 1.5 + 8
                bg_y           = y - (num_lines - 1) * font_size * 1.5 - font_size * 0.3 - 4

                # White background
                c.saveState()
                c.setFillColorRGB(1, 1, 1)
                c.setStrokeColorRGB(1, 1, 1, 0)
                c.rect(x - 4, bg_y, fb_text_w_pt + 8, bg_h, fill=1, stroke=0)

                # Text (two passes: stroke + fill for boldness)
                c.setFont(font_name, font_size)
                c.setFillColor(red)
                c.setStrokeColor(red)
                c.setLineWidth(1.8)
                draw_y = y
                for ln in lines:
                    c.drawString(x, draw_y, ln)
                    draw_y -= font_size * 1.5
                c.setLineWidth(0)
                draw_y = y
                for ln in lines:
                    c.drawString(x, draw_y, ln)
                    draw_y -= font_size * 1.5
                c.restoreState()

                print(f"  ✓ P{page_num:>2} {item['manifest_key']} feedback: {text!r}")

            # ── Tick / Cross ───────────────────────────────────────────────
            elif t == "tick_cross":
                action = data.get("action", "tick")
                x      = float(data["x"])
                y      = float(data["y"])
                sz     = float(data.get("size", 70.0))

                if action == "tick":
                    _draw_tick(c, x, y, size=sz)
                else:
                    _draw_cross(c, x, y, size=sz)

        c.showPage()

    c.save()

    # ── Merge overlay with original PDF ──────────────────────────────────────
    print("  Merging annotations…", flush=True)
    packet.seek(0)
    overlay    = PdfReader(packet)
    out_writer = PdfWriter()
    for i in range(num_pages):
        pg = reader.pages[i]
        if i < len(overlay.pages):
            pg.merge_page(overlay.pages[i])
        out_writer.add_page(pg)

    with open(output_path, "wb") as f:
        out_writer.write(f)

    print(f"\n  ✓ Patched PDF → {output_path}")
    print(f"{'='*62}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse_corrections_from_args(args) -> dict:
    """
    Build a corrections dict from CLI arguments.

    --fix-marks    SectionB__Q1 5/10
    --fix-feedback SectionB__Q1 "Include interest workings"
    --fix-tick     SectionB__Q1 0 cross    (flip annotation[0] to cross)
    """
    corrections: dict = {}

    # --fix-marks KEY OBTAINED/TOTAL  (can be repeated)
    if args.fix_marks:
        for entry in args.fix_marks:
            if len(entry) != 2:
                print(f"  ⚠ --fix-marks: expected KEY OBTAINED/TOTAL, got {entry}")
                continue
            mkey, frac = entry
            try:
                parts = str(frac).split("/")
                if len(parts) == 2:
                    obtained, total = float(parts[0]), float(parts[1])
                else:
                    obtained = float(parts[0])
                    total    = None
            except ValueError:
                print(f"  ⚠ --fix-marks: cannot parse '{frac}' — expected e.g. '5/10' or '5'")
                continue
            corrections.setdefault(mkey, {})["marks_obtained"] = obtained
            if total is not None:
                corrections[mkey]["marks_total"] = total

    # --fix-feedback KEY "text"  (can be repeated)
    if args.fix_feedback:
        for entry in args.fix_feedback:
            if len(entry) != 2:
                print(f"  ⚠ --fix-feedback: expected KEY TEXT, got {entry}")
                continue
            mkey, text = entry
            corrections.setdefault(mkey, {})["feedback_text"] = text

    # --fix-tick KEY INDEX ACTION  (can be repeated)
    if args.fix_tick:
        for entry in args.fix_tick:
            if len(entry) != 3:
                print(f"  ⚠ --fix-tick: expected KEY INDEX ACTION, got {entry}")
                continue
            mkey, idx_str, action = entry
            if action not in ("tick", "cross"):
                print(f"  ⚠ --fix-tick: action must be 'tick' or 'cross', got '{action}'")
                continue
            corrections.setdefault(mkey, {}).setdefault("ticks_crosses", []).append({
                "index":  int(idx_str),
                "action": action,
            })

    # --delete-tick KEY INDEX  (can be repeated; INDEX is 0-based)
    if args.delete_tick:
        for entry in args.delete_tick:
            if len(entry) != 2:
                print(f"  ⚠ --delete-tick: expected KEY INDEX, got {entry}")
                continue
            mkey, idx_str = entry
            corrections.setdefault(mkey, {}).setdefault(
                "delete_tick_indices", []
            ).append(int(idx_str))

    # --move-tick KEY INDEX DIRECTION  (can be repeated)
    if args.move_tick:
        import re
        for entry in args.move_tick:
            if len(entry) != 3:
                print(f"  ⚠ --move-tick: expected KEY INDEX DIRECTION, got {entry}")
                continue
            mkey, idx_str, direction = entry
            
            m = re.match(r'^(up|down|left|right)(\d*)$', direction)
            if not m:
                print(f"  ⚠ --move-tick: direction must be up, down, left, right (optionally followed by a multiplier), got '{direction}'")
                continue
                
            corrections.setdefault(mkey, {}).setdefault("move_tick", []).append({
                "index": int(idx_str),
                "direction": m.group(1),
                "multiplier": int(m.group(2)) if m.group(2) else 1,
            })

    # --move-stamp KEY DIRECTION  (can be repeated)
    if args.move_stamp:
        import re
        for entry in args.move_stamp:
            if len(entry) != 2:
                print(f"  ⚠ --move-stamp: expected KEY DIRECTION, got {entry}")
                continue
            mkey, direction = entry
            
            m = re.match(r'^(up|down|left|right)(\d*)$', direction)
            if not m:
                print(f"  ⚠ --move-stamp: direction must be up, down, left, right (optionally followed by a multiplier), got '{direction}'")
                continue
                
            corrections.setdefault(mkey, {}).setdefault("move_stamp", []).append({
                "direction": m.group(1),
                "multiplier": int(m.group(2)) if m.group(2) else 1,
            })

    # --move-feedback KEY DIRECTION  (can be repeated)
    if args.move_feedback:
        import re
        for entry in args.move_feedback:
            if len(entry) != 2:
                print(f"  ⚠ --move-feedback: expected KEY DIRECTION, got {entry}")
                continue
            mkey, direction = entry
            
            m = re.match(r'^(up|down|left|right)(\d*)$', direction)
            if not m:
                print(f"  ⚠ --move-feedback: direction must be up, down, left, right, got '{direction}'")
                continue
                
            corrections.setdefault(mkey, {}).setdefault("move_feedback", []).append({
                "direction": m.group(1),
                "multiplier": int(m.group(2)) if m.group(2) else 1,
            })

    # --remove-stamp KEY  (can be repeated)
    if args.remove_stamp:
        for mkey in args.remove_stamp:
            corrections.setdefault(mkey, {})["remove_stamp"] = True

    return corrections


def main():
    parser = argparse.ArgumentParser(
        description="Patch a Stage 7 checked-copy PDF using its annotation manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest",  required=True,
                        help="Path to checked_copy_manifest.json")
    parser.add_argument("--output",    default=None,
                        help="Output path for patched PDF (default: <original>_patched.pdf)")

    # Correction arguments — all repeatable
    parser.add_argument("--fix-marks",    nargs=2, action="append", metavar=("KEY", "MARKS"),
                        help="Change marks for a question. MARKS = obtained/total, e.g. 5/10")
    parser.add_argument("--fix-feedback", nargs=2, action="append", metavar=("KEY", "TEXT"),
                        help="Change feedback text for a question.")
    parser.add_argument("--fix-tick",     nargs=3, action="append", metavar=("KEY", "INDEX", "ACTION"),
                        help="Flip a specific tick/cross. ACTION = tick | cross")
    parser.add_argument("--delete-tick",  nargs=2, action="append", metavar=("KEY", "INDEX"),
                        help="Permanently remove a tick/cross annotation by 0-based index.")
    parser.add_argument("--remove-stamp", action="append", metavar="KEY",
                        help="Completely remove the marks stamp for a question.")
    parser.add_argument("--move-tick",    nargs=3, action="append", metavar=("KEY", "INDEX", "DIRECTION"),
                        help="Move a specific tick/cross by 30 pixels. DIRECTION = up | down | left | right")
    parser.add_argument("--move-stamp",   nargs=2, action="append", metavar=("KEY", "DIRECTION"),
                        help="Move the marks stamp by 30 pixels. DIRECTION = up | down | left | right")
    parser.add_argument("--move-feedback",nargs=2, action="append", metavar=("KEY", "DIRECTION"),
                        help="Move the feedback text by 30 pixels. DIRECTION = up | down | left | right")
    parser.add_argument("--corrections-json", default=None,
                        help="Path to a JSON file containing the corrections dict (for batch / frontend use)")

    # Utility
    parser.add_argument("--summary", action="store_true",
                        help="Print a summary of the manifest and exit (no PDF generated)")

    args = parser.parse_args()

    # ── Summary-only mode ─────────────────────────────────────────────────────
    if args.summary:
        summary = get_manifest_summary(args.manifest)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    # ── Build corrections dict ────────────────────────────────────────────────
    corrections: dict = {}

    if args.corrections_json:
        with open(args.corrections_json, "r", encoding="utf-8") as f:
            corrections = json.load(f)
        print(f"  Loaded corrections from {args.corrections_json}")

    # CLI corrections override / merge with JSON corrections
    cli_corrections = _parse_corrections_from_args(args)
    for k, v in cli_corrections.items():
        if k in corrections:
            corrections[k].update(v)
        else:
            corrections[k] = v

    if not corrections:
        print("  No corrections specified.  Use --fix-marks, --fix-feedback, "
              "--fix-tick, or --corrections-json.")
        parser.print_help()
        sys.exit(0)

    # ── Apply patch ───────────────────────────────────────────────────────────
    output_path = apply_patch(
        manifest_path = args.manifest,
        corrections   = corrections,
        output_path   = args.output,
    )
    print(f"\n  Done.  Patched PDF: {output_path}")


if __name__ == "__main__":
    main()
