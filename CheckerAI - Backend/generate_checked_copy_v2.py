#!/usr/bin/env python3
"""
Stage 7 (v2): Generate Checked Copy of Student Answer Sheet (Student-Facing)

v2 adds: annotation manifest JSON saved alongside the output PDF.
The manifest records every drawn element (marks stamps, ticks, crosses,
feedback text, grand-total stamp) with exact page / x / y coordinates so
that patch_checked_copy.py can rebuild the overlay without any LLM calls
or image analysis.

All original annotation logic is unchanged.

Usage:
  python3 generate_checked_copy_v2.py \\
      --pdf     "AS FR 15244.pdf" \\
      --grading grading_results/dataset_15244/grading_final.json \\
      --aligned grading_results/dataset_15244/aligned_answers.json \\
      --output  grading_results/dataset_15244/checked_copy.pdf \\
      --ocr     grading_results/dataset_15244/ocr_output.txt
      [--manifest grading_results/dataset_15244/checked_copy_manifest.json]

Annotation logic (v3 — deterministic tier-based):
  Score ≥ 75%  → 2 ticks   per page (last page: 1 tick),  1-2 comment lines
  Score 41-74% → 1 tick    per page (last page: 1 tick),  2-3 comment lines
  Score 25-40% → 1 cross   per page (last page: 1 cross), 3-4 comment lines
  Score < 25%  → 2 crosses per page (last page: 1 cross), 3-4 comment lines

  Shared-page rule: when multiple questions share a page, each question gets
  exactly 1 annotation of its correct type (tick or cross per tier).

  Feedback placement: always directly below the marks stamp, with a 1 cm
  (28 pt) gap from the stamp bottom. Text is clamped so it never overflows
  the page bottom margin.

Coordinate detection (no LLM for theory question placement):
  1. PyMuPDF embedded text-layer search
  2. Pre-produced OCR text file
  3. Pixel first-text-block position
  4. Fixed top-of-page fallback

MCQ annotation: stub for future LLM-based per-option detection.

Usage:
  python3 generate_checked_copy.py \\
      --pdf     "AS FR 15244.pdf" \\
      --grading grading_results/dataset_15244/grading_final.json \\
      --aligned grading_results/dataset_15244/aligned_answers.json \\
      --output  grading_results/dataset_15244/checked_copy.pdf \\
      --ocr     grading_results/dataset_15244/ocr_output.txt
"""

import os
import re
import io
import json
import random
import argparse
import subprocess
from datetime import datetime

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

try:
    from claude_grading.answer_grader_claude import is_meaningful_answer
except ImportError:
    def is_meaningful_answer(text: str) -> bool:
        if not text or not text.strip(): return False
        return len(text.strip().split()) >= 15

from PIL import Image
import numpy as np
import cv2
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import red
import fitz  # PyMuPDF


# ── Constants ─────────────────────────────────────────────────────────────────

FONT_PATH  = os.path.join(BASE_DIR, "IndieFlower-Regular.ttf")
MARGIN_X   = 26.0       # left-edge fallback X for marks stamp
RENDER_DPI = 72         # 72 DPI: accurate enough to see inter-line gaps (was 36 — too blurry)

# ── Tier-based annotation counts ─────────────────────────────────────────────
# Keyed by score % thresholds.  Each entry: (action, count_normal, count_last)
# count_normal = annotations on every page except the last
# count_last   = annotations on the LAST page of the answer (always 1)
#
# Score bands:  ≥75% | 41-74% | 25-40% | <25%

def _tier_ann_params(marks_obtained: float, marks_total: float) -> tuple:
    """
    Return (action, count_normal, count_last) for the given score.

    action       : 'tick' or 'cross'
    count_normal : number of marks to draw on every non-last page
    count_last   : number of marks to draw on the LAST page (always 1)
    """
    ratio = (marks_obtained / marks_total) if marks_total > 0 else 0.0
    if ratio >= 0.75:
        return ("tick",  2, 1)
    elif ratio >= 0.41:
        return ("tick",  1, 1)
    elif ratio >= 0.25:
        return ("cross", 1, 1)
    else:
        return ("cross", 2, 1)


TIER_ACTION = {
    "excellent": "tick",
    "very_good": "tick",
    "good":      "tick",
    "okay":      "cross",   # 25-40%: cross
    "poor":      "cross",
    "no_answer": None,
}

_HEADING_PATTERNS = [
    r"ANSWER\s+TO\s+QUESTION\s*[-#:,]*\s*{n}\b",
    r"ANSWER\s+TO\s+Q\s*[-#:,]*\s*{n}\b",
    r"QUESTION\s*[-#:,]*\s*{n}\b",
    r"\bQ\s*[-#:,]*\s*{n}\b",
    r"ANS\w*\s*[-#:,]*\s*{n}\b",
]


# ── Tesseract auto-install ─────────────────────────────────────────────────────

def _ensure_tesseract() -> bool:
    r = subprocess.run(["which", "tesseract"], capture_output=True, text=True)
    if r.returncode == 0:
        print("  ✓ Tesseract available")
        return True
    print("  ⚠ Tesseract not found — installing via Homebrew…")
    try:
        proc = subprocess.run(["brew", "install", "tesseract"], timeout=360)
        if proc.returncode == 0:
            print("  ✓ Tesseract installed.")
            return True
    except FileNotFoundError:
        print("  ✗ Homebrew not found.  Run: brew install tesseract")
    except subprocess.TimeoutExpired:
        print("  ✗ Homebrew install timed out.")
    return False


# ── Font ──────────────────────────────────────────────────────────────────────

def _register_fonts() -> str:
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont("Handwriting", FONT_PATH))
        return "Handwriting"
    return "Helvetica"


# ── Marks formatting ──────────────────────────────────────────────────────────

def _fmt_marks(n) -> str:
    """5.0→'5', 2.5→'2.5'. No total, no trailing .0."""
    if n is None:
        return "0"
    n = float(n)
    return str(int(n)) if n == int(n) else f"{n:.1f}"


# ── LLM feedback generator ────────────────────────────────────────────────────

_feedback_cache: dict = {}      # (section, q_id) → feedback string
_used_feedback_texts: list = []  # all generated feedback texts for the current doc (for deduplication)


def _generate_llm_feedback(grade_entry: dict, cache_key: str) -> str | None:
    """
    Call GPT-4o-mini to generate a teacher comment for EVERY question — no exceptions.

    Three modes:
      - marks_ratio >= 1.0            → ≤8-word positive praise
      - marks_ratio < 0.60 (< 60%)   → 2–3 concise bullet points listing main errors
      - everything else               → ONE ≤12-word corrective sentence

    Results are cached per question to avoid duplicate API calls.
    """
    if cache_key in _feedback_cache:
        return _feedback_cache[cache_key]

    marks_obtained = float(grade_entry.get("marks_obtained", 0) or 0)
    marks_total    = float(grade_entry.get("marks_total",    0) or 0)
    marks_ratio    = (marks_obtained / marks_total) if marks_total > 0 else 0
    feedback_raw   = grade_entry.get("feedback", "")
    major_errors   = grade_entry.get("major_errors",    []) or []
    key_pts_missed = grade_entry.get("key_points_missed", []) or []

    errors_str = "; ".join(str(e) for e in (major_errors + key_pts_missed)[:4]) if (major_errors or key_pts_missed) else ""

    # ── Build deduplication hint from previously generated feedbacks ───────
    avoid_block = ""
    if _used_feedback_texts:
        # Extract the first 4 words of each prior feedback as "openers" to avoid
        prior_openers = []
        for t in _used_feedback_texts:
            words = t.strip().split()
            if len(words) >= 3:
                prior_openers.append(" ".join(words[:4]))
        if prior_openers:
            openers_str = " | ".join(f'"{p}"' for p in prior_openers[:6])
            avoid_block = (
                f"IMPORTANT: Do NOT start your comment with or reuse any of these phrases "
                f"already used for other questions in this paper: {openers_str}. "
                "Use completely different wording.\n"
            )

    # ── Case 1: Full marks → short praise ─────────────────────────────────
    if marks_ratio >= 1.0:
        prompt = (
            f"A student scored {marks_obtained}/{marks_total} (full marks) on an exam question.\n"
            f"Grader feedback: {feedback_raw}\n"
            f"{avoid_block}\n"
            "Write ONE short positive teacher comment in ≤8 words praising the student. "
            "Vary the wording — avoid generic openers like 'Outstanding analysis'. "
            "Do not include any specific numbers, figures, or monetary amounts. "
            "No quotation marks, no full stop."
        )
        max_tok = 30

    # ── Case 2: Low score (< 60% or 0 marks) → 2–3 bullet points ───────────────
    elif marks_ratio < 0.60 or marks_obtained == 0:
        context      = f"Grader feedback: {feedback_raw}\n" if feedback_raw else ""
        errors_block = f"Key errors: {errors_str}\n" if errors_str else ""
        prompt = (
            f"A student scored {marks_obtained}/{marks_total} on an exam question.\n"
            f"{context}{errors_block}"
            f"{avoid_block}\n"
            "Write 2 to 3 concise bullet points (start each with '•') listing the specific "
            "reasons, missed concepts, or calculation errors for the lost/zero marks. Each bullet must be ≤12 words. "
            "DO NOT use terms like 'model', 'model answer', or 'marking scheme'. Address the student directly as a teacher. "
            "Do not include any specific numbers, figures, or monetary amounts in the bullets — keep feedback conceptual. "
            "No full stop at the end of each bullet. Return only the bullets, no intro text."
        )
        max_tok = 100

    # ── Case 3: Partial score → single corrective sentence ────────────────
    else:
        context      = f"Grader feedback: {feedback_raw}\n" if feedback_raw else ""
        errors_block = f"Key errors: {errors_str}\n" if errors_str else ""
        prompt = (
            f"A student scored {marks_obtained}/{marks_total} on an exam question.\n"
            f"{context}{errors_block}"
            f"{avoid_block}\n"
            "Write ONE concise teacher comment in exactly ≤12 words explaining "
            "what the student should have done differently. "
            "DO NOT use terms like 'model', 'model answer', or 'marking scheme'. Address the student directly as a teacher. "
            "Do not include any specific numbers, figures, or monetary amounts — keep feedback conceptual. "
            "No quotation marks, no full stop at the end."
        )
        max_tok = 40

    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tok,
            temperature=0.5,   # slightly higher → more varied phrasing
        )
        text = resp.choices[0].message.content.strip().rstrip(".")
        _feedback_cache[cache_key] = text
        _used_feedback_texts.append(text)   # track for deduplication
        return text
    except Exception as e:
        print(f"      ⚠ LLM feedback failed: {e}")
        _feedback_cache[cache_key] = None
        return None


def _load_ocr_page_text(ocr_path: str, page_num: int) -> str:
    """Extract the OCR text for a single page from the combined ocr_output.txt."""
    if not ocr_path or not os.path.exists(ocr_path):
        return ""
    try:
        with open(ocr_path, "r") as f:
            content = f.read()
        for chunk in content.split("=== Page "):
            if not chunk.strip():
                continue
            head, _, body = chunk.partition(" ===")
            if head.strip() == str(page_num):
                return body.strip()
    except Exception:
        pass
    return ""


_error_loc_cache: dict = {}   # (section, q_id, page_num) → list[float]

def _locate_errors_in_ocr(grade_entry: dict, ocr_page_text: str, cache_key: str) -> list[float]:
    """
    Ask GPT-4o-mini which lines of the page's OCR text contain the student's errors.
    Returns a list of vertical fractions (0.0 = top of page, 1.0 = bottom).
    One fraction per error found on this page.
    """
    if cache_key in _error_loc_cache:
        return _error_loc_cache[cache_key]

    if not ocr_page_text.strip():
        _error_loc_cache[cache_key] = []
        return []

    major_errors     = grade_entry.get("major_errors", []) or []
    key_pts_missed   = grade_entry.get("key_points_missed", []) or []
    all_errors       = (major_errors + key_pts_missed)[:6]

    if not all_errors:
        _error_loc_cache[cache_key] = []
        return []

    lines       = [l for l in ocr_page_text.split("\n") if l.strip()]
    total_lines = len(lines)
    if total_lines == 0:
        _error_loc_cache[cache_key] = []
        return []

    numbered_text = "\n".join(f"{i+1}: {ln}" for i, ln in enumerate(lines))
    errors_str    = "\n".join(f"- {e}" for e in all_errors)

    prompt = (
        "Below is a page of a student's answer (line-numbered), followed by a list of "
        "errors/missed points identified by the grader.\n\n"
        f"OCR TEXT:\n{numbered_text}\n\n"
        f"GRADER ERRORS:\n{errors_str}\n\n"
        "For each error that corresponds to content actually written on this page, "
        "return the line number where the student wrote the incorrect or incomplete content. "
        "If an error does not appear on this page at all, skip it.\n"
        "Return a JSON object: {\"lines\": [<line_number>, ...]}\n"
        "Return {\"lines\": []} if nothing on this page matches."
    )

    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=120,
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content)
        raw_lines = data.get("lines", [])
        fracs = [
            int(n) / total_lines
            for n in raw_lines
            if isinstance(n, (int, float)) and 1 <= int(n) <= total_lines
        ]
        print(f"      📍 Error lines on page: {raw_lines} → Y fracs: {[f'{f:.2f}' for f in fracs]}", flush=True)
        _error_loc_cache[cache_key] = fracs
        return fracs
    except Exception as e:
        print(f"      ⚠ Error location LLM failed: {e}")
        _error_loc_cache[cache_key] = []
        return []


def _check_final_answer_wrong(grade_entry: dict, student_answer: str) -> dict | None:
    """
    Call GPT-4o-mini to determine if a practical question has a fundamentally wrong 
    final answer. Returns a dict with {"is_final_answer_wrong", "wrong_answer_text", "page_number"} or None.
    """
    if "practical" not in grade_entry.get("grading_method", ""):
        return None
    if grade_entry.get("tier") in ["very_good", "good"]:
        return None

    prompt = f"""
Analyze this student's answer and grader feedback for a practical accounting/finance question.
Determine if their final numerical/practical answer (like a balance sheet total, final profit, etc.) is fundamentally wrong based on the grader feedback.

Student Answer OCR:
{student_answer}

Grader Feedback:
{grade_entry.get('feedback', '')}
Major Errors:
{grade_entry.get('major_errors', [])}

Return a JSON object:
{{
  "is_final_answer_wrong": boolean,
  "wrong_answer_text": "the exact string/number they wrote that is wrong (e.g. 'Total assets: 541000' or '244500'). Keep it brief and exact to what is in the OCR.",
  "reason": "brief reason why"
}}
"""
    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=150,
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content)
        if data.get("is_final_answer_wrong"):
            return data
        return None
    except Exception as e:
        print(f"      ⚠ LLM final answer check failed: {e}")
        return None


# ── Page rendering ─────────────────────────────────────────────────────────────

def _render_gray(fitz_page, dpi: int = RENDER_DPI):
    """
    Render a fitz page to a grayscale PIL Image at low DPI.

    Returns (gray_img, img_w, img_h, scale_x, scale_y) where
    scale_x/y convert image pixels → PDF points (1 px = scale_y PDF points).
    """
    zoom = dpi / 72.0
    mat  = fitz.Matrix(zoom, zoom)
    pix  = fitz_page.get_pixmap(matrix=mat, alpha=False)
    w, h = pix.width, pix.height

    # PDF point dimensions (scale = pts per pixel)
    rect_w = fitz_page.rect.width
    rect_h = fitz_page.rect.height
    if getattr(fitz_page, 'rotation', 0) in (90, 270):
        scale_x = rect_h / w
        scale_y = rect_w / h
    else:
        scale_x = rect_w / w
        scale_y = rect_h / h

    gray = Image.frombytes("RGB", [w, h], bytes(pix.samples)).convert("L")
    return gray, w, h, scale_x, scale_y


# ── Pixel-based text-region detection ─────────────────────────────────────────

def _get_text_blocks(gray: Image.Image, img_w: int, img_h: int) -> list:
    """
    Scan ink-bearing rows in the pre-rendered grayscale image.

    Returns list of (center_frac, span_frac) sorted top→bottom
    (fractions of image/page height; 0.0 = top, 1.0 = bottom).
    Blocks < 3 % of page height are filtered as noise.
    """
    px = gray.load()

    INK_THR  = 150          # catches handwriting, ignores very faint shadows
    MIN_ROW  = max(2, int(img_w * 0.03))   # 3 % of row width
    STEP     = 3
    # Skip the very bottom 8 % — scanner border / page-edge shadow
    y_end    = int(img_h * 0.92)

    ink_rows = []
    for y in range(img_h):
        if y >= y_end:
            break
        dark = sum(1 for x in range(0, img_w, STEP) if px[x, y] < INK_THR)
        if dark * STEP >= MIN_ROW:
            ink_rows.append(y)

    if not ink_rows:
        return []

    gap_px      = max(2, int(img_h * 0.02))
    min_span_px = max(3, int(img_h * 0.03))

    blocks, start, prev = [], ink_rows[0], ink_rows[0]
    for row in ink_rows[1:]:
        if row - prev > gap_px:
            if prev - start >= min_span_px:
                blocks.append((start, prev))
            start = row
        prev = row
    if prev - start >= min_span_px:
        blocks.append((start, prev))

    return [((s + e) / 2 / img_h, (e - s) / img_h) for s, e in blocks]


def _find_ink_bottom_in_zone(
    gray: Image.Image,
    img_h: int,
    row_top_px: int,
    row_bot_px: int,
    ink_thr: int = 200,
    min_ink_frac: float = 0.02,
) -> int:
    """
    Scan from bottom upward within [row_top_px, row_bot_px] to find the last
    image row that contains meaningful ink (handwriting, not blank space).

    Used for multi-question pages: given each question's pixel zone,
    find where that question's text ACTUALLY ENDS so the stamp can be
    placed right there.

    Returns the row number (image coords, 0=top). Falls back to row_bot_px.
    """
    px    = gray.load()
    w     = gray.width
    x_lo  = max(0, int(w * 0.10))   # skip left margin (teacher writes there)
    x_hi  = min(w, int(w * 0.92))   # skip right edge scanner shadow
    span  = x_hi - x_lo
    if span < 1:
        return row_bot_px

    row_top_px = max(0, row_top_px)
    row_bot_px = min(img_h - 1, row_bot_px)

    for row in range(row_bot_px, row_top_px, -1):
        n_ink = sum(1 for x in range(x_lo, x_hi) if px[x, row] < ink_thr)
        if n_ink >= span * min_ink_frac:
            return row

    return row_bot_px   # no ink found — use zone bottom as fallback


def _compute_ink_bot_strict(gray: Image.Image, img_w: int, img_h: int) -> float:
    """
    Find the true bottom of student handwriting using a robust density-based approach.

    This scans the central 84% of the page width to avoid scanner shadows and borders,
    and finds the last row that contains significant dark pixels.
    This effectively ignores stray dots but catches actual handwriting.

    Returns a fraction of page height (0.0 = top, 1.0 = bottom).
    """
    # ── Density-based approach ─────────────────────────────────────────────
    px      = gray.load()
    INK_THR = 210
    STEP    = 3
    x_start = int(img_w * 0.08)
    x_end   = int(img_w * 0.92)
    sampled = max(1, (x_end - x_start) // STEP)

    y_scan_start = int(img_h * 0.03)
    y_scan_end   = int(img_h * 0.92)

    row_densities = []
    for y in range(y_scan_start, y_scan_end):
        dark = sum(1 for x in range(x_start, x_end, STEP) if px[x, y] < INK_THR)
        row_densities.append((y, dark / sampled))

    if not row_densities:
        return 0.90

    all_d    = sorted(d for _, d in row_densities)
    median_d = all_d[len(all_d) // 2]
    # Use a much more reasonable threshold. If the median is high, we don't demand 2x the median.
    # 1.5% dark pixels in a row is typically enough to indicate handwriting.
    hw_threshold = max(0.015, min(0.03, median_d * 1.5))

    last_hw_y = y_scan_start
    for y, d in row_densities:
        if d >= hw_threshold:
            last_hw_y = y

    margin_px = int(img_h * 0.03)
    return min(0.93, max(0.12, (last_hw_y + margin_px) / img_h))


def _block_y_pdf(center_frac: float, pdf_h: float) -> float:
    """Top-origin fraction → ReportLab PDF Y (bottom-origin)."""
    return pdf_h * (1.0 - center_frac)


# ── Central blank-space finder (for feedback placement) ──────────────────────

def _find_feedback_spot(
    gray: Image.Image,
    img_w: int, img_h: int,
    scale_x: float, scale_y: float,
    pdf_h: float, pdf_w: float,
    annotation_y_pdfs: list,
    text_blocks: list,
    min_blank_pts: float = 260,
    page_excluded_px_rows: set = None,
) -> tuple | None:
    """
    Scan rows for the widest blank horizontal run in the CENTRAL page zone
    (20 %–80 % of page width) that is ≥ 260 PDF points wide and at least
    50 PDF points away from every annotation mark.

    Restricts the row search to within the vertical extent of written content
    (so feedback doesn't land in blank margins above/below all text).

    Returns (x_pdf, y_pdf) — the start X and row Y of the best blank band,
    or None if no qualifying region is found.
    """
    px = gray.load()

    THRESHOLD = 215                                 # pixel ≥ this → blank
    X_LO      = int(img_w * 0.20)                  # 20 % from left
    X_HI      = int(img_w * 0.80)                  # 80 % from left
    MIN_COLS  = max(5, int(min_blank_pts / scale_x))

    # Exclusion rows: 50 pt around each annotation + page_excluded_px_rows
    excl = page_excluded_px_rows.copy() if page_excluded_px_rows else set()
    pad  = max(2, int(50 / scale_y))
    for y_p in annotation_y_pdfs:
        y_i = int((1.0 - y_p / pdf_h) * img_h)
        for d in range(-pad, pad + 1):
            if 0 <= y_i + d < img_h:
                excl.add(y_i + d)

    # Vertical search bounds — stay within written content area.
    # If text_blocks is empty (fully scanned / handwritten page), use the
    # middle two-thirds of the page so we avoid blank header/footer margins.
    if text_blocks:
        top_frac = max(0.02, text_blocks[0][0]  - text_blocks[0][1]  / 2)
        bot_frac = min(0.98, text_blocks[-1][0] + text_blocks[-1][1] / 2)
    else:
        top_frac, bot_frac = 0.15, 0.85   # fallback: middle 70 % of page

    row_lo = max(2,       int(top_frac * img_h))
    row_hi = min(img_h-2, int(bot_frac * img_h))

    best_x, best_y_i, best_len = None, None, 0

    for y_i in range(row_lo, row_hi):
        if y_i in excl:
            continue

        # Find longest blank run in central zone.
        # Check only the target row (not ±1) — scanned pages have slight
        # pixel noise so a triple-row AND condition is too strict.
        run_s, run_l = None, 0
        b_s,   b_l   = None, 0
        for x in range(X_LO, X_HI):
            bright = px[x, y_i] >= THRESHOLD
            if bright:
                if run_s is None:
                    run_s = x
                run_l += 1
            else:
                if run_l > b_l:
                    b_s, b_l = run_s, run_l
                run_s, run_l = None, 0
        if run_l > b_l:
            b_s, b_l = run_s, run_l

        if b_l >= MIN_COLS and b_l > best_len:
            best_x, best_y_i, best_len = b_s, y_i, b_l

    if best_x is None:
        return None

    # Start text a quarter into the blank run (looks more centred)
    x_pdf = (best_x + best_len // 4) * scale_x
    y_pdf = pdf_h * (1.0 - best_y_i / img_h)
    return x_pdf, y_pdf


def _find_clear_xy(
    gray: Image.Image, img_w: int, img_h: int,
    pdf_w: float, pdf_h: float,
    target_y_frac: float, is_practical: bool,
    min_clear_cols: int = 40,
    required_text_width_px: int = 0,
    excluded_px_rows: set | None = None,
    exclude_radius: int = 50,
    max_search_delta: float = 0.45,
    min_y_frac: float = 0.03,
    max_y_frac: float = 0.97,
) -> tuple[float, float]:
    """
    Find the nearest location to target_y_frac where a band of rows is
    completely free of ink.  Every pixel in the band (vertically) AND every
    pixel in the horizontal run must be above INK_THR = 215 (near-white).
    This guarantees text placed here will never touch student handwriting.
    """
    px       = gray.load()
    INK_THR  = 215
    x_lo     = int(img_w * 0.15)
    x_hi     = int(img_w * 0.85)
    step_px  = max(1, int(img_h * 0.002))
    BAND     = 5   # number of rows that must ALL be clear
    need_w   = max(min_clear_cols, required_text_width_px)

    def _row_clear_run(row_y):
        """Return (start_x, length) of the longest run in row_y where EVERY
           pixel in [row_y - BAND//2, row_y + BAND//2] is ink-free."""
        best_s, best_l = None, 0
        run_s, run_l   = None, 0
        y_lo = max(0,        row_y - BAND // 2)
        y_hi = min(img_h-1,  row_y + BAND // 2)
        for x in range(x_lo, x_hi):
            col_clear = all(px[x, yy] >= INK_THR for yy in range(y_lo, y_hi + 1))
            if col_clear:
                if run_s is None:
                    run_s = x
                run_l += 1
            else:
                if run_l > best_l:
                    best_s, best_l = run_s, run_l
                run_s, run_l = None, 0
        if run_l > best_l:
            best_s, best_l = run_s, run_l
        return (best_s, best_l) if best_l >= need_w else None

    target_row = int(target_y_frac * img_h)
    max_search = int(img_h * max_search_delta)
    excl = excluded_px_rows or set()

    def _row_excluded(r):
        if not excl: return False
        return any(abs(r - er) <= exclude_radius for er in excl)

    for delta in range(0, max_search, step_px):
        for sign in ([0] if delta == 0 else [1, -1]):
            row = target_row + sign * delta
            if row < int(img_h * min_y_frac) or row > int(img_h * max_y_frac):
                continue
            if _row_excluded(row):
                continue
            result = _row_clear_run(row)
            if result is not None:
                seg_start, seg_len = result
                # Place text a quarter into the clear run (avoids far edges)
                pick_x = seg_start + (max(0, seg_len - seg_len // 3) if is_practical else seg_len // 4)
                # Hard-clamp: keep within [15%, 85%] of page width
                pick_x = max(x_lo, min(x_hi - need_w, pick_x))
                x_pdf  = (pick_x / img_w) * pdf_w
                y_pdf  = pdf_h * (1.0 - row / img_h)
                return x_pdf, y_pdf

    # Absolute fallback — still respect page margins
    import random
    jitter = random.uniform(-10, 10)
    return _random_ann_x(pdf_w, is_practical), pdf_h * (1.0 - target_y_frac) + jitter


def _find_left_margin_stamp_spot(
    gray: Image.Image,
    img_w: int, img_h: int,
    pdf_w: float, pdf_h: float,
    row_top: int, row_bot: int,
    excluded_px_rows: set | None = None,
    ink_thr: int = 215,
    exclude_radius: int = 60,
) -> tuple[float, float] | None:
    """
    Scan only the LEFT MARGIN strip (2%–14% of page width) for the longest
    contiguous clear block in the vertical range [row_top, row_bot].

    Exam-paper teachers write marks in the left margin next to each question,
    so this is the primary placement zone for individual question marks stamps.

    Returns (x_pdf, y_pdf) for the vertical centre of the clearest clear band,
    or None if no suitable strip is found (min 4 clear rows required).
    """
    import bisect
    px = gray.load()

    x_lo = max(0, int(img_w * 0.02))
    x_hi = min(img_w, int(img_w * 0.14))
    if x_hi <= x_lo:
        return None

    excl_sorted = sorted(excluded_px_rows or [])

    def _excluded(r: int) -> bool:
        if not excl_sorted:
            return False
        pos = bisect.bisect_left(excl_sorted, r)
        for idx in (pos - 1, pos):
            if 0 <= idx < len(excl_sorted) and abs(excl_sorted[idx] - r) <= exclude_radius:
                return True
        return False

    # A row is "clear" when ≥70% of margin pixels are white
    clear_rows: list[int] = []
    for row in range(max(0, row_top), min(img_h, row_bot)):
        if _excluded(row):
            continue
        n_clear = sum(1 for x in range(x_lo, x_hi) if px[x, row] >= ink_thr)
        if n_clear >= (x_hi - x_lo) * 0.70:
            clear_rows.append(row)

    if not clear_rows:
        return None

    # Find the longest contiguous run of clear rows
    best_start, best_len = clear_rows[0], 1
    cur_start,  cur_len  = clear_rows[0], 1
    prev = clear_rows[0]
    for r in clear_rows[1:]:
        if r == prev + 1:
            cur_len += 1
        else:
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
            cur_start, cur_len = r, 1
        prev = r
    if cur_len > best_len:
        best_start, best_len = cur_start, cur_len

    if best_len < 4:
        return None

    cy_px = best_start + best_len // 2
    cx_px = x_lo + (x_hi - x_lo) // 2

    x_pdf = (cx_px / img_w) * pdf_w
    y_pdf = pdf_h * (1.0 - cy_px / img_h)
    return x_pdf, y_pdf


def _find_largest_white_rect(
    gray: Image.Image, img_w: int, img_h: int,
    pdf_w: float, pdf_h: float,
    row_top: int, row_bot: int,
    min_w_px: int = 80, min_h_px: int = 12,
    ink_thr: int = 210,
    excluded_px_rows: set | None = None,
    exclude_radius: int = 50,
    align_top: bool = False,
) -> tuple[float, float, float, float] | None:
    """
    Within the pixel rows [row_top, row_bot), find the largest axis-aligned
    rectangle of pixels ALL above ink_thr (genuinely white space).

    Uses the CORRECT O(n) monotonic-stack largest-rectangle-in-histogram
    algorithm. The previous version compared stored WIDTH vs current height
    (stack[-1][1] > h) which is wrong -- the algorithm must compare stored
    HEIGHT vs current height.

    excluded_px_rows: rows within exclude_radius pixels of any member are
    treated as inked (histogram resets), guaranteeing no overlap with stamps.

    Returns (x_pdf, y_pdf, rect_w_px, rect_h_px) in PDF space or None.
    """
    import bisect
    px    = gray.load()
    x_lo  = int(img_w * 0.05)
    x_hi  = min(int(img_w * 0.95), img_w - 1)  # clamp to valid pixel range
    width = x_hi - x_lo
    if width <= 0:
        return None
    excl_sorted = sorted(excluded_px_rows or [])

    def _row_excluded(r):
        if not excl_sorted:
            return False
        pos = bisect.bisect_left(excl_sorted, r)
        for idx in (pos - 1, pos):
            if 0 <= idx < len(excl_sorted) and abs(excl_sorted[idx] - r) <= exclude_radius:
                return True
        return False

    height    = [0] * width
    best_area = 0
    best_rect = None  # (col_start_in_zone, row_end, rect_w, rect_h)

    # Hard-clamp row bounds to valid pixel range (callers may overshoot img_h)
    row_top = max(0, min(row_top, img_h - 1))
    row_bot = max(0, min(row_bot, img_h))

    for row in range(row_top, row_bot):
        if _row_excluded(row):
            height = [0] * width
            continue

        # Update column heights (clamp col index as belt-and-braces defence)
        for ci in range(width):
            col = min(x_lo + ci, img_w - 1)
            if px[col, row] >= ink_thr:
                height[ci] += 1
            else:
                height[ci] = 0

        # ── Correct monotonic-stack largest-rectangle-in-histogram ──────────
        # Stack stores COLUMN INDICES. height[stack[i]] is strictly increasing.
        stack = []
        for ci in range(width + 1):
            h = height[ci] if ci < width else 0
            while stack and height[stack[-1]] > h:   # compare HEIGHTS, not widths
                popped    = stack.pop()
                rect_h    = height[popped]
                left_wall = stack[-1] if stack else -1
                rect_w    = ci - left_wall - 1
                area      = rect_w * rect_h
                if area > best_area and rect_w >= min_w_px and rect_h >= min_h_px:
                    best_area = area
                    best_rect = (left_wall + 1, row, rect_w, rect_h)
            stack.append(ci)

    if best_rect is None:
        return None

    col_start, row_end, rect_w, rect_h = best_rect
    cx_px = x_lo + col_start + rect_w // 4   # a quarter into the clear run
    if align_top:
        cy_px = row_end - rect_h + min_h_px + int(15 * (pdf_h / 842.0))
    else:
        cy_px = row_end - rect_h // 2             # vertical centre

    x_pdf = (cx_px / img_w) * pdf_w
    y_pdf = pdf_h * (1.0 - cy_px / img_h)
    return x_pdf, y_pdf, rect_w, rect_h


def _get_non_colliding_y(y_frac: float, page_used: list, ink_top: float, ink_bot: float, min_sep: float) -> float | None:
    """Finds a vertical position close to y_frac that is at least min_sep away from used positions."""
    candidates = [y_frac]
    step = min_sep * 0.4
    for offset in range(1, 40):
        candidates.append(y_frac + offset * step)
        candidates.append(y_frac - offset * step)
    
    min_top_floor = max(0.12, ink_top)
    max_bot_floor = min(0.88, ink_bot - 0.02)
    for c in candidates:
        if c < min_top_floor or c > max_bot_floor:
            continue
        if all(abs(c - u) >= min_sep for u in page_used):
            return c
    return None


# ── Variable X for ticks/crosses ──────────────────────────────────────────────
def _find_clear_x(gray: Image.Image, img_w: int, img_h: int, pdf_w: float, y_frac: float, is_practical: bool, excluded_px_rows: set = None, page_num: int = None) -> float:
    """
    Finds an x-coordinate on the page at the given y_frac that does not contain ink.
    Clamped to the detected paper boundary (via _page_bounds_data) or [15%, 85%].
    """
    px = gray.load()
    y = int(y_frac * img_h)
    y = max(0, min(img_h - 1, y))

    if excluded_px_rows and any(abs(y - er) <= 50 for er in excluded_px_rows):
        return _random_ann_x(pdf_w, is_practical, page_num=page_num)

    # Use detected paper boundary if available
    px_x_min, px_x_max = _get_page_x_bounds(page_num or 0, pdf_w)
    # Convert from PDF pts to image pixels
    img_x_min = int((px_x_min / pdf_w) * img_w)
    img_x_max = int((px_x_max / pdf_w) * img_w)
    img_x_min = max(0, img_x_min)
    img_x_max = min(img_w, img_x_max)

    band_half = int(img_h * 0.035)  # increased vertical band to 3.5%
    INK_THR = 215

    clear_cols = []
    for x in range(img_x_min, img_x_max):
        is_clear = True
        for dy in range(-band_half, band_half + 1, 4):
            yy = min(max(0, y + dy), img_h - 1)
            if px[x, yy] < INK_THR:
                is_clear = False
                break
        if is_clear:
            clear_cols.append(x)

    if not clear_cols:
        return _random_ann_x(pdf_w, is_practical, page_num=page_num)

    segments = []
    start = clear_cols[0]
    prev = start
    for x in clear_cols[1:]:
        if x == prev + 1:
            prev = x
        else:
            segments.append((start, prev))
            start = x
            prev = x
    segments.append((start, prev))

    min_width = int(img_w * 0.08)
    valid_segments = [s for s in segments if s[1] - s[0] >= min_width]
    if not valid_segments:
        valid_segments = segments

    pref_start = int(img_w * (0.6 if is_practical else 0.1))
    pref_end   = int(img_w * (0.9 if is_practical else 0.4))

    best_segment = valid_segments[0]
    best_score = -1
    for s in valid_segments:
        overlap = max(0, min(s[1], pref_end) - max(s[0], pref_start))
        score = overlap + (s[1] - s[0]) * 0.1
        if score > best_score:
            best_score = score
            best_segment = s

    center_x = (best_segment[0] + best_segment[1]) / 2.0
    result_x = (center_x / img_w) * pdf_w
    # Final clamp to page bounds
    result_x = max(px_x_min, min(px_x_max, result_x))
    return result_x


def _random_ann_x(pdf_w: float, is_practical: bool = False, page_num: int = None, pdf_h: float = None) -> float:
    """
    Pick a natural X position clamped to the detected paper boundary.
    On landscape/wide pages (pdf_w > pdf_h), keep annotations inside a vertical column (10%-40% of width).
    """
    x_min, x_max = _get_page_x_bounds(page_num or 0, pdf_w)
    span = x_max - x_min
    if pdf_h and pdf_w > pdf_h:
        return random.uniform(x_min + span * 0.10, x_min + span * 0.40)

    if is_practical:
        if random.random() < 0.70:
            return random.uniform(x_min + span * 0.50, x_min + span * 0.85)
        return random.uniform(x_min + span * 0.20, x_min + span * 0.50)
    # Theory
    if random.random() < 0.70:
        return random.uniform(x_min, x_min + span * 0.28)
    return random.uniform(x_min + span * 0.28, x_min + span * 0.50)


def _find_ink_x(gray, img_w: int, img_h: int, pdf_w: float, y_frac: float, is_practical: bool) -> float:
    """
    For crosses: find the center of the LARGEST INK segment on this row.
    This ensures the cross is drawn ON TOP of the wrong written value,
    not in blank space next to it.
    Falls back to _random_ann_x if no ink found.
    """
    # Always use actual image dimensions from the image itself to avoid IndexError
    actual_w, actual_h = gray.size  # PIL: (width, height)
    px = gray.load()
    y = int(y_frac * actual_h)
    y = max(0, min(actual_h - 1, y))

    band_half = int(actual_h * 0.025)  # 2.5% vertical band
    INK_THR = 200  # pixel < this => ink

    # Ignore left margin and spiral binding
    x_min = int(actual_w * 0.20)
    x_max = min(int(actual_w * 0.90), actual_w - 1)

    # Collect ink columns
    ink_cols = []
    for x in range(x_min, x_max):
        for dy in range(-band_half, band_half + 1, 3):
            yy = min(max(0, y + dy), actual_h - 1)
            xx = min(max(0, x), actual_w - 1)
            val = px[xx, yy]
            # Handle both grayscale (int) and RGB (tuple)
            scalar = val if isinstance(val, int) else val[0]
            if scalar < INK_THR:
                ink_cols.append(x)
                break

    if not ink_cols:
        return _random_ann_x(pdf_w, is_practical)

    # Build contiguous ink segments
    segments = []
    start = ink_cols[0]
    prev = start
    for x in ink_cols[1:]:
        if x <= prev + 4:  # allow small gaps within a word
            prev = x
        else:
            segments.append((start, prev))
            start = x
            prev = x
    segments.append((start, prev))

    # Prefer the right-most wide segment (most likely to be a value column)
    # Width threshold: at least 3% of page width
    min_width = int(actual_w * 0.03)
    wide_segs = [s for s in segments if s[1] - s[0] >= min_width]
    if not wide_segs:
        wide_segs = segments

    # Pick the rightmost wide segment (numbers tend to be on the right side of tables)
    best = max(wide_segs, key=lambda s: s[0])
    center_x = (best[0] + best[1]) / 2.0
    return (center_x / actual_w) * pdf_w


def _line_matches_fragment(line: str, fragments: list) -> bool:
    """
    Fuzzy-match: return True if any fragment from the list is found
    in this OCR line.  A fragment matches if ≥60% of its words appear
    in the line, OR if the fragment is a pure number that appears
    verbatim in the line.
    """
    if not fragments:
        return False
    line_lower = line.lower()
    # Strip punctuation for word-level check
    line_words = set(re.sub(r'[^a-z0-9]', ' ', line_lower).split())
    for frag in fragments:
        frag = str(frag).strip()
        if not frag:
            continue
        # Pure-number match: check if it appears literally in the line
        if re.fullmatch(r'[\d,\.]+', frag.replace(' ', '')):
            if frag.replace(',', '').replace('.', '').replace(' ', '') in \
               re.sub(r'[^0-9]', '', line):
                return True
        # Word-overlap match
        frag_words = re.sub(r'[^a-z0-9]', ' ', frag.lower()).split()
        if not frag_words:
            continue
            
        overlap = sum(1 for w in frag_words if w in line_words)
        if overlap / len(frag_words) >= 0.6:
            # Numeric safety check: if the fragment has numbers, ensure at least one matches
            # to prevent matching a correct text description with a WRONG number.
            frag_nums = {w for w in frag_words if w.isdigit()}
            if frag_nums:
                if not any(num in line_words for num in frag_nums):
                    continue
            return True
    return False


# ── Organic circle ────────────────────────────────────────────────────────────

def _draw_circle(c: canvas.Canvas, cx: float, cy: float, width: float, height: float):
    """Draw an organic red ellipse/circle to highlight a wrong final answer."""
    c.saveState()
    c.translate(cx, cy)
    c.rotate(random.uniform(-5, 5))

    c.setStrokeColor(red)
    c.setLineWidth(random.uniform(1.8, 2.5))
    c.setLineCap(1)
    c.setLineJoin(1)
    
    # Add a bit of jitter to width and height so it looks drawn by hand
    w = width * random.uniform(0.95, 1.05)
    h = height * random.uniform(0.95, 1.05)
    
    # We draw an irregular ellipse using a bezier path that doesn't quite close perfectly
    # or overlaps slightly at the end
    path = c.beginPath()
    
    # Start top-center, slightly offset
    start_x = random.uniform(-0.1 * w, 0.1 * w)
    start_y = h/2 + random.uniform(-0.1 * h, 0.1 * h)
    path.moveTo(start_x, start_y)
    
    # Draw roughly 4 curves making up the ellipse
    # Top-right quadrant
    path.curveTo(w/2, h/2, w/2, 0, w/2, -h/2 * 0.5)
    # Bottom-right to bottom-left
    path.curveTo(w/2, -h/2, -w/2, -h/2, -w/2, -h/2 * 0.5)
    # Bottom-left to top-left
    path.curveTo(-w/2, 0, -w/2, h/2, -w/2 * 0.5, h/2)
    # Top-left back to start with some overshoot
    path.curveTo(0, h/2, start_x + random.uniform(2, 6), start_y + random.uniform(-4, 4), start_x + random.uniform(-5, 5), start_y + random.uniform(-5, 5))
    
    c.drawPath(path, stroke=1, fill=0)
    c.restoreState()


# ── Organic tick ──────────────────────────────────────────────────────────────

def _draw_tick(c: canvas.Canvas, cx: float, cy: float, size: float = 30):
    r"""Two-Bezier organic tick. Red ink, random angle / width / jitter.

    Shape (matches reference image):
      - Short left arm: starts upper-left, descends steeply to the junction.
      - Long right arm: from junction sweeps diagonally up-right.
      - Angle at junction is clearly OBTUSE (>130°) like a real teacher ✓.

    Geometry overview (junction at origin):

        (left arm start)
             \  ← short, steep downward stroke
              \
               [junction]────────────────────→ (right arm end)
               lowest pt     long, sweeping up-right
    """
    c.saveState()
    c.translate(cx, cy)
    c.rotate(random.uniform(-10, 10))

    sz = size * random.uniform(0.87, 1.15)
    c.setStrokeColor(red)
    base_lw = random.uniform(1.9, 2.8)
    c.setLineWidth(max(1.2, base_lw * (sz / 75.0)))
    c.setLineCap(1)
    c.setLineJoin(1)

    def j(s=0.06):
        return random.uniform(-sz * s, sz * s)

    # ── Geometry: wide obtuse angle at junction ──────────────────────────────
    # Left arm: short, comes from upper-left and descends steeply to junction.
    # Right arm: long, sweeps from junction diagonally up to the right.
    # The dot product of (left-arm-vec · right-arm-vec) is negative → obtuse.
    #
    # Approximate angle at junction ≈ 140° (very wide, like ref image ticks).
    #
    xm, ym =  sz * 0.00, -sz * 0.28   # junction: lowest point
    x0, y0 = -sz * 0.28,  sz * 0.08   # left arm start: upper-left (short arm)
    x1, y1 =  sz * 0.72,  sz * 0.58   # right arm end:  upper-right (long arm)

    # Short left arm — steep descent to junction
    p = c.beginPath()
    p.moveTo(x0 + j(), y0 + j())
    p.curveTo(x0 + sz * 0.05 + j(), y0 - sz * 0.12 + j(),
              xm - sz * 0.10 + j(), ym + sz * 0.10 + j(),
              xm, ym)
    c.drawPath(p, stroke=1, fill=0)

    # Long right arm — sweeps from junction up-right
    p2 = c.beginPath()
    p2.moveTo(xm, ym)
    p2.curveTo(xm + sz * 0.20 + j(), ym + sz * 0.20 + j(),
               x1 - sz * 0.15 + j(), y1 - sz * 0.10 + j(),
               x1 + j(), y1 + j())
    c.drawPath(p2, stroke=1, fill=0)

    c.restoreState()


# ── Organic cross ─────────────────────────────────────────────────────────────

def _draw_cross(c: canvas.Canvas, cx: float, cy: float, size: float = 27):
    """
    Smooth two-arm cross: each arm is ONE continuous Bezier curve (no midpoint kink).
    Line width scales with size so crosses look the same visual weight on any page.
    """
    c.saveState()
    c.translate(cx, cy)
    c.rotate(random.uniform(-11, 11))

    sz = size * random.uniform(0.87, 1.15)
    r  = sz * 0.53
    c.setLineCap(1)
    c.setLineJoin(1)

    def j(s=0.07):
        return random.uniform(-sz * s, sz * s)

    def lw():
        return max(1.2, random.uniform(1.8, 2.8) * (sz / 60.0))

    c.setStrokeColor(red)
    c.setLineWidth(lw())
    p1 = c.beginPath()
    p1.moveTo(-r + j(0.06),  r + j(0.06))
    p1.curveTo(-r * 0.2 + j(0.10),  r * 0.2 + j(0.10),
                r * 0.2 + j(0.10), -r * 0.2 + j(0.10),
                r + j(0.06), -r + j(0.06))
    c.drawPath(p1, stroke=1, fill=0)

    c.setLineWidth(lw())
    p2 = c.beginPath()
    p2.moveTo( r + j(0.06),  r + j(0.06))
    p2.curveTo( r * 0.2 + j(0.10),  r * 0.2 + j(0.10),
               -r * 0.2 + j(0.10), -r * 0.2 + j(0.10),
               -r + j(0.06), -r + j(0.06))
    c.drawPath(p2, stroke=1, fill=0)

    c.restoreState()



def _draw_bold_text(c, text, x, y, font_name, font_size, stroke_w=3.0):
    """Draw text with heavy stroke+fill for extreme boldness."""
    c.setFont(font_name, font_size)
    c.setFillColor(red)
    c.setStrokeColor(red)
    c.setFillAlpha(1.0)
    c.setStrokeAlpha(1.0)
    c.setLineWidth(stroke_w)
    c.drawString(x, y, text)
    c.setLineWidth(0)
    c.drawString(x, y, text)   # solid fill pass


def _draw_marks_stamp(
    c: canvas.Canvas,
    cx: float, cy: float,
    marks_obtained: float, marks_total: float,
    font_name: str,
    scale: float = 1.0,
    q_num: str = None,
):
    """
    Draw a teacher-style fraction stamp at (cx, cy):
        numerator
        -------
        denominator
    with an organic (imperfect) oval surrounding it. Extra bold.
    The `scale` parameter should be pdf_h / 842.0 so annotations look
    the same size relative to the page regardless of scan resolution.
    """
    FONT_SIZE  = int(28 * scale)         # size for each number line
    LINE_GAP   = int(4  * scale)         # gap between number and rule
    RULE_W_PAD = int(6  * scale)         # extra horizontal padding each side
    TEXT_SW    = max(1.0, 2.5 * scale)   # bold text stroke weight
    RULE_SW    = max(1.2, min(3.5, 1.8 * scale))  # dividing line — capped thin
    OVAL_SW    = max(1.5, min(5.0, random.uniform(2.0, 2.8) * scale))

    obtained_str = str(int(marks_obtained)) if marks_obtained == int(marks_obtained) else f"{marks_obtained:.1f}"
    total_str    = str(int(marks_total))    if marks_total    == int(marks_total)    else f"{marks_total:.1f}"

    # Estimate character widths (rough: 0.55 * font_size per char)
    char_w       = FONT_SIZE * 0.55
    numer_w      = len(obtained_str) * char_w
    denom_w      = len(total_str)    * char_w
    rule_w       = max(numer_w, denom_w) + RULE_W_PAD * 2
    total_height = FONT_SIZE * 2 + LINE_GAP * 2 + 2   # two number rows + rule

    c.saveState()
    c.translate(cx, cy)

    # Layout: y=0 is center of the whole stamp
    rule_y   =  0                            # horizontal rule at center
    numer_y  =  rule_y + LINE_GAP + 2       # numerator baseline above rule
    denom_y  =  rule_y - LINE_GAP - FONT_SIZE + 4   # denominator baseline below rule

    # ── Numerator ────────────────────────────────────────────────────
    _draw_bold_text(c, obtained_str, -numer_w / 2, numer_y, font_name, FONT_SIZE, TEXT_SW)

    # ── Horizontal rule ────────────────────────────────────────────────
    c.setStrokeColor(red)
    c.setLineWidth(RULE_SW)
    c.line(-rule_w / 2, rule_y, rule_w / 2, rule_y)

    # ── Denominator ────────────────────────────────────────────────────
    _draw_bold_text(c, total_str, -denom_w / 2, denom_y, font_name, FONT_SIZE, TEXT_SW)

    # ── Organic oval around the whole stamp ──────────────────────────────
    rx = rule_w / 2 + FONT_SIZE * 0.35
    ry = total_height / 2 + FONT_SIZE * 0.20

    c.setStrokeColor(red)
    c.setLineWidth(OVAL_SW)
    c.rotate(random.uniform(-6, 6))

    def j(s):
        return random.uniform(-rx * s, rx * s)

    sx, sy = j(0.08), ry + j(0.06)
    path = c.beginPath()
    path.moveTo(sx, sy)
    path.curveTo( rx + j(0.09),  ry + j(0.09),
                  rx + j(0.09), -ry + j(0.09),
                  j(0.08),      -ry - j(0.06))
    path.curveTo(-rx + j(0.09), -ry + j(0.09),
                 -rx + j(0.09),  ry + j(0.09),
                  sx + j(0.12),  sy + j(0.12))
    c.drawPath(path, stroke=1, fill=0)

    c.restoreState()


def _draw_pending_mcq_stamp(
    c: canvas.Canvas,
    cx: float, cy: float,
    marks_total: float,
    font_name: str,
    scale: float = 1.0,
):
    """
    Draw a marks stamp with '?' as the numerator, indicating MCQ marks are
    pending (teacher will enter them via the Edit Checked Copy UI).

    Visually identical to _draw_marks_stamp but uses '?' instead of a number.
    """
    FONT_SIZE  = int(28 * scale)
    LINE_GAP   = int(4  * scale)
    RULE_W_PAD = int(6  * scale)
    TEXT_SW    = max(1.0, 2.5 * scale)
    RULE_SW    = max(1.2, min(3.5, 1.8 * scale))
    OVAL_SW    = max(1.5, min(5.0, random.uniform(2.0, 2.8) * scale))

    obtained_str = "?"
    total_str    = str(int(marks_total)) if marks_total == int(marks_total) else f"{marks_total:.1f}"

    char_w       = FONT_SIZE * 0.55
    numer_w      = len(obtained_str) * char_w
    denom_w      = len(total_str)    * char_w
    rule_w       = max(numer_w, denom_w) + RULE_W_PAD * 2
    total_height = FONT_SIZE * 2 + LINE_GAP * 2 + 2

    c.saveState()
    c.translate(cx, cy)

    rule_y  =  0
    numer_y =  rule_y + LINE_GAP + 2
    denom_y =  rule_y - LINE_GAP - FONT_SIZE + 4

    _draw_bold_text(c, obtained_str, -numer_w / 2, numer_y, font_name, FONT_SIZE, TEXT_SW)

    c.setStrokeColor(red)
    c.setLineWidth(RULE_SW)
    c.line(-rule_w / 2, rule_y, rule_w / 2, rule_y)

    _draw_bold_text(c, total_str, -denom_w / 2, denom_y, font_name, FONT_SIZE, TEXT_SW)

    rx = rule_w / 2 + FONT_SIZE * 0.35
    ry = total_height / 2 + FONT_SIZE * 0.20

    c.setStrokeColor(red)
    c.setLineWidth(OVAL_SW)
    c.rotate(random.uniform(-6, 6))

    def j(s):
        return random.uniform(-rx * s, rx * s)

    sx, sy = j(0.08), ry + j(0.06)
    path = c.beginPath()
    path.moveTo(sx, sy)
    path.curveTo( rx + j(0.09),  ry + j(0.09),
                  rx + j(0.09), -ry + j(0.09),
                  j(0.08),      -ry - j(0.06))
    path.curveTo(-rx + j(0.09), -ry + j(0.09),
                 -rx + j(0.09),  ry + j(0.09),
                  sx + j(0.12),  sy + j(0.12))
    c.drawPath(path, stroke=1, fill=0)

    c.restoreState()


def _draw_total_marks_stamp(
    c: canvas.Canvas,
    cx: float, cy: float,
    total_obtained: float, total_marks: float,
    font_name: str,
    scale: float = 1.0,
):
    """
    Draw the grand-total fraction at the top of page 1, even bigger and bolder.
    Same stacked format: total_obtained / total_marks with a larger oval.
    Must always be LARGER than individual question stamps (which use 28*scale).
    """
    FONT_SIZE  = int(42 * scale)
    TEXT_SW    = max(1.5, 3.0 * scale)
    RULE_SW    = max(1.2, min(4.0, 2.0 * scale))   # thin rule, capped
    OVAL_SW    = max(1.8, min(6.0, random.uniform(2.4, 3.2) * scale))
    LINE_GAP   = int(5 * scale)
    RULE_W_PAD = int(8 * scale)

    obtained_str = str(int(total_obtained)) if total_obtained == int(total_obtained) else f"{total_obtained:.1f}"
    total_str    = str(int(total_marks))    if total_marks    == int(total_marks)    else f"{total_marks:.1f}"

    char_w   = FONT_SIZE * 0.58
    numer_w  = len(obtained_str) * char_w
    denom_w  = len(total_str)    * char_w
    rule_w   = max(numer_w, denom_w) + RULE_W_PAD * 2
    total_height = FONT_SIZE * 2 + LINE_GAP * 2 + 2

    c.saveState()
    c.translate(cx, cy)

    rule_y  =  0
    numer_y =  rule_y + LINE_GAP + 2
    denom_y =  rule_y - LINE_GAP - FONT_SIZE + 4

    _draw_bold_text(c, obtained_str, -numer_w / 2, numer_y, font_name, FONT_SIZE, TEXT_SW)

    c.setStrokeColor(red)
    c.setLineWidth(RULE_SW)
    c.line(-rule_w / 2, rule_y, rule_w / 2, rule_y)

    _draw_bold_text(c, total_str, -denom_w / 2, denom_y, font_name, FONT_SIZE, TEXT_SW)

    rx = rule_w / 2 + FONT_SIZE * 0.40
    ry = total_height / 2 + FONT_SIZE * 0.25

    c.setStrokeColor(red)
    c.setLineWidth(OVAL_SW)
    c.rotate(random.uniform(-5, 5))

    def j(s):
        return random.uniform(-rx * s, rx * s)

    sx, sy = j(0.06), ry + j(0.05)
    path = c.beginPath()
    path.moveTo(sx, sy)
    path.curveTo( rx + j(0.08),  ry + j(0.08),
                  rx + j(0.08), -ry + j(0.08),
                  j(0.06),      -ry - j(0.05))
    path.curveTo(-rx + j(0.08), -ry + j(0.08),
                 -rx + j(0.08),  ry + j(0.08),
                  sx + j(0.10),  sy + j(0.10))
    c.drawPath(path, stroke=1, fill=0)

    c.restoreState()


# ── MCQ stub ──────────────────────────────────────────────────────────────────

def find_mcq_positions_on_page(page_image: Image.Image, question_numbers: list) -> dict:
    """
    STUB — future MCQ annotation.
    Will call GPT-4o vision with page_image + question_numbers and return
    {q_num: (x_pct, y_pct)} for each MCQ row.  Currently always returns {}.
    """
    return {}


# ── OCR helper ────────────────────────────────────────────────────────────────

def _parse_ocr_page(path: str, page_num: int) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"=== Page (\d+) ===", content)
    for i in range(1, len(blocks) - 1, 2):
        if int(blocks[i]) == page_num:
            return blocks[i + 1].strip()
    return ""


# ── Heading position finders ──────────────────────────────────────────────────

def _heading_fitz(fitz_page, pdf_h: float, q_num: str) -> float | None:
    for s in [
        f"ANSWER TO QUESTION - {q_num}",
        f"ANSWER TO QUESTION # {q_num}",
        f"ANSWER TO QUESTION-{q_num}",
        f"ANSWER TO Q {q_num}",
        f"QUESTION - {q_num}",
        f"Q{q_num}",
    ]:
        hits = fitz_page.search_for(s)
        if hits:
            return pdf_h - hits[0].y0
    return None


def _heading_ocr(path: str, page_num: int, pdf_h: float, q_num: str) -> float | None:
    ocr = _parse_ocr_page(path, page_num)
    if not ocr:
        return None

    # Build standard patterns using the q_num directly (e.g. "4a", "3b")
    pats = [re.compile(t.replace("{n}", re.escape(q_num)), re.IGNORECASE)
            for t in _HEADING_PATTERNS]

    # Also build sub-part aware pattern: "4a" → matches "4(a)", "4 a", "4a"
    # handles the bracketed handwriting format [Question 4(a)] / [Question # 3 (b)]
    # AND student-written "Ans. 4(a)", "Ans 3b" style headings
    m_sub = re.match(r'^(\d+)([a-zA-Z])$', q_num.strip())
    if m_sub:
        base_n   = m_sub.group(1)
        sub_let  = m_sub.group(2)
        sub_pat_str = (
            rf"(?:Q|Question|Ans\.?|Answer)\s*[:#,\s\-\.]*\s*{re.escape(base_n)}"
            rf"[\(\s\.\-]*{re.escape(sub_let)}[\)\s\.\-]*"
        )
        pats.append(re.compile(sub_pat_str, re.IGNORECASE))

    lines = [l.strip() for l in ocr.splitlines() if l.strip()]
    for li, line in enumerate(lines):
        for pat in pats:
            if pat.search(line):
                frac = li / max(len(lines) - 1, 1)
                return pdf_h * (0.95 - 0.90 * frac)
    return None


def _heading_first_block(
    gray: Image.Image, img_w: int, img_h: int, pdf_h: float
) -> float | None:
    blocks = _get_text_blocks(gray, img_w, img_h)
    if not blocks:
        return None
    center, span = blocks[0]
    return pdf_h * (1.0 - (center - span / 2))


_paddle_ocr_instance = None

def _get_paddle_ocr():
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr_instance = PaddleOCR(use_textline_orientation=True, lang='en')
        except Exception as e:
            print(f"  [PaddleOCR] Warning: could not load PaddleOCR: {e}", flush=True)
            _paddle_ocr_instance = False
    return _paddle_ocr_instance


def _extract_page_boxes_paddle(img_np) -> list:
    """
    Extract text lines with bounding boxes from a BGR image using PaddleOCR.
    Returns list of dicts with keys: text, ymin, ymax, xmin, xmax, score (fractions 0..1).
    """
    ocr = _get_paddle_ocr()
    if not ocr:
        return []
    try:
        result = ocr.ocr(img_np)
    except Exception as e:
        print(f"  [PaddleOCR] Prediction error: {e}", flush=True)
        return []
    if not result:
        return []
    h, w = img_np.shape[:2]
    lines = []
    for item in result:
        rec_texts = item.get('rec_texts', [])
        rec_boxes = item.get('rec_boxes', [])
        rec_scores = item.get('rec_scores', [])
        for text, box, score in zip(rec_texts, rec_boxes, rec_scores):
            box = np.array(box)
            if box.ndim == 1:
                xmin, ymin, xmax, ymax = box
            else:
                xmin, ymin = box.min(axis=0)
                xmax, ymax = box.max(axis=0)
            lines.append({
                'text': str(text),
                'ymin': max(0.0, float(ymin) / h),
                'ymax': min(1.0, float(ymax) / h),
                'xmin': max(0.0, float(xmin) / w),
                'xmax': min(1.0, float(xmax) / w),
                'score': float(score),
            })
    lines.sort(key=lambda l: l['ymin'])
    return lines


def _match_q_heading_text(text: str, q_num: str) -> bool:
    """
    Check if a recognized OCR line matches the heading for question q_num.
    Handles circled Unicode numbers, roman numerals, handwriting abbreviations,
    and student conventions (e.g. 'Que = 1(a)', 'Que B', 'Q=2(B)', '(Que-3 1)', 'Que=4').
    """
    t = str(text).strip()
    t_lower = t.lower()
    # Reject pure narrative body sentences
    if any(phrase in t_lower for phrase in [
        'as per as', 'in this case', 'needs to disclose', 'according to as',
        'profit on sale', 'interest on debenture', 'trade payable', 'trade receivable'
    ]):
        return False

    # Extract base digit and sub-letter from q_num (e.g. '1b' -> 1, b; '4—' -> 4, ''; '3b' -> 3, b)
    m_num = re.search(r'\d+', q_num)
    if not m_num:
        return False
    base_num = m_num.group(0)
    m_alpha = re.search(r'[a-zA-Z]', q_num[m_num.end():])
    sub_letter = m_alpha.group(0).lower() if m_alpha else ''

    # Normalize circled numbers ①..⑳ -> Q1..Q20
    for i in range(1, 21):
        t = t.replace(chr(0x245F + i), f'Q{i}')
    t = re.sub(r'^[①-⑳]\s*', 'Q ', t).lower()

    d_map = {'1': r'[1il|]', '2': r'[2z]', '3': r'3', '4': r'4', '5': r'[5s]', '6': r'6', '7': r'7', '8': r'[8b]'}
    b_pat = d_map.get(base_num, re.escape(base_num))
    
    prefix_kw = r'(?:^|\b|\s)[\[|\(]?\s*(?:q|que|qu|question|ans|answer)[\s#\-\.=:_]*'

    # Must have an explicit question/answer keyword OR be at start of line as a label
    if sub_letter:
        sub_pat = rf'(?:\({sub_letter}\)|{sub_letter})'
        # e.g. Que = 1(a), Q1a, Q1(a), Que 1a, Q=2(B)
        p_kw = rf'{prefix_kw}{b_pat}[\s\.\-\)=:_]*{sub_pat}\b'
        if re.search(p_kw, t):
            return True
        # Start of line: e.g. 1(a), (1a), 1a.
        p_sol = rf'^\s*[\(\[]?\s*{b_pat}[\s\.\-\)=:_]*{sub_pat}\b'
        if re.search(p_sol, t):
            return True
        # e.g. Que = B (for 1b only)
        if base_num in ['1']:
            p_sub_only = rf'{prefix_kw}{sub_pat}\b'
            if re.search(p_sub_only, t):
                return True
        # e.g. (Que=31) AX (for 3b) where base question is 3
        p_kw_base = rf'{prefix_kw}{b_pat}'
        if re.search(p_kw_base, t):
            other_subs = [c for c in 'abcdef' if c != sub_letter]
            if not any(f'({c})' in t or f'={c}' in t for c in other_subs):
                return True
    else:
        # If no subpart (e.g. Que=4)
        p_kw_base = rf'{prefix_kw}{b_pat}'
        if re.search(p_kw_base, t):
            return True
        p_sol = rf'^\s*[\(\[]?\s*{b_pat}[\)\]\.\:\-]'
        if re.search(p_sol, t):
            return True

    return False


def _find_heading_y(
    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_path, paddle_lines: list = None
) -> float | None:
    """Heading Y finder using PyMuPDF, PaddleOCR boxes, and OCR text fallback (PDF bottom-origin)."""
    y = _heading_fitz(fitz_page, pdf_h, q_num)
    if y: return y

    if paddle_lines:
        for l in paddle_lines:
            if _match_q_heading_text(l['text'], q_num):
                return pdf_h * (1.0 - l['ymin'])

    y = _heading_ocr(ocr_path, fitz_page.number + 1, pdf_h, q_num)
    if y: return y

    return None


# _choose_action removed — replaced by deterministic _tier_ann_params()




def _find_question_line_bounds(ocr_text: str, q_num: str) -> tuple[int, int]:
    """
    Find the start and end line indices (0-indexed) for question q_num in the
    OCR text. End is exclusive (first line of the NEXT question, or EOF).

    Handles sub-part format: q_num='4a' matches '[Question 4(a)]',
    '[Question # 3 (b)]', 'Q4a', 'Question 4 a', etc.
    """
    import re
    lines = ocr_text.split("\n")

    # Split q_num into base number + optional sub-part letter
    # e.g. "4a" → base="4", sub="a"; "3b" → base="3", sub="b"; "1" → base="1", sub=""
    m_sub = re.match(r'^(\d+)([a-zA-Z]?)$', q_num.strip())
    if m_sub:
        base_num   = m_sub.group(1)
        sub_letter = m_sub.group(2)
    else:
        base_num   = q_num.strip()
        sub_letter = ""

    if sub_letter:
        # Match formats like "4(a)", "4 a", "4a", "4 (a)"
        sub_pat = rf"(?:\({re.escape(sub_letter)}\)|{re.escape(sub_letter)})"
        num_pat = rf"{re.escape(base_num)}[\s\.\-\)]*{sub_pat}"

    else:
        num_pat = re.escape(base_num)

    # Strict: whole line is a question heading (e.g. "[Question 4(a)]", "Q 4a",
    #          "| Question 5(a) |"  <- pipe-delimited table-row format,
    #          "Ans. 5(b)", "Ans 3(a)", "Answer 2b"  <- student-written style)
    q_exact = re.compile(
        rf"^\s*[\[|]?\s*(?:Q|Question|Ans\.?|Answer)\s*[#\s\-\.]*\s*{num_pat}\s*[\]|]?\s*$",
        re.IGNORECASE,
    )
    # Loose: line contains a question heading (content may follow)
    q_loose = re.compile(
        rf"(?:^|\b|\s)[\[|]?\s*(?:Q|Question|Ans\.?|Answer)\s*[#\s\-\.]*\s*{num_pat}\b",
        re.IGNORECASE,
    )
    # Matches ANY question heading (to detect where the next question starts)
    any_q = re.compile(
        r"(?:^|\b|\s)\[?\s*(?:Q|Question|Ans\.?|Answer)\s*[#\s\-\.]*\s*\d+",
        re.IGNORECASE,
    )

    start = None
    for pattern in (q_exact, q_loose):
        for i, line in enumerate(lines):
            stripped = line.strip()
            if start is None and pattern.search(stripped):
                start = i
            elif start is not None and any_q.search(stripped) and not pattern.search(stripped):
                return start, i
        if start is not None:
            return start, len(lines)

    # Super loose fallback: match explicit sub_letter heading e.g. "[a]", "(a)", "a)", "a.", "a -", "a:"
    if sub_letter:
        q_super_loose = re.compile(
            rf"^\s*[\[(\s]*{re.escape(sub_letter)}[\)\]\.:\-]+",
            re.IGNORECASE
        )
        for i, line in enumerate(lines):
            stripped = line.strip()
            if start is None and q_super_loose.search(stripped):
                start = i
            elif start is not None and any_q.search(stripped) and not q_super_loose.search(stripped):
                return start, i
        if start is not None:
            return start, len(lines)

    return -1, len(lines)   # fallback: whole page


def _find_fragment_y(
    fragment: str,
    ocr_lines: list,
    ink_top: float,
    ink_bot: float,
    slice_top: float,
    slice_bot: float,
) -> float | None:
    """
    Find the y_frac of the OCR line that best matches `fragment`.
    Returns None if no match is found within the question's slice.
    """
    if not fragment or not ocr_lines:
        return None
    total = len(ocr_lines)
    if total == 0:
        return None

    frag_lower = fragment.lower()
    frag_words = set(re.sub(r'[^a-z0-9]', ' ', frag_lower).split())
    frag_nums  = {w for w in frag_words if w.isdigit()}

    best_idx   = None
    best_score = 0.0

    for idx, line in enumerate(ocr_lines):
        line_s = line.strip()
        if not line_s:
            continue
        raw_frac = (idx + 0.5) / total
        y_frac   = ink_top + raw_frac * (ink_bot - ink_top)
        # Must be in the question's slice
        if not (slice_top <= y_frac <= slice_bot):
            continue

        line_lower = line_s.lower()
        line_words = set(re.sub(r'[^a-z0-9]', ' ', line_lower).split())

        if not frag_words:
            continue
        overlap = sum(1 for w in frag_words if w in line_words)
        score   = overlap / len(frag_words)

        # Numeric safety: fragment with numbers must match at least one number
        if frag_nums and not any(n in line_words for n in frag_nums):
            score *= 0.3

        if score > best_score:
            best_score = score
            best_idx   = idx

    if best_idx is None or best_score < 0.55:
        return None

    raw_frac = (best_idx + 0.5) / total
    return ink_top + raw_frac * (ink_bot - ink_top)


def _plan_annotations_new(
    marks_obtained: float,
    marks_total: float,
    page_idx_in_q: int,
    total_pages: int,
    n_questions_on_page: int,
    gray: Image.Image,
    img_w: int, img_h: int,
    pdf_w: float, pdf_h: float,
    slice_top: float,
    slice_bot: float,
    page_used_y_fracs: list,
    page_excluded_px_rows: set,
    is_practical: bool,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
    heading_y_frac: float = None,
) -> list:
    """
    Plan tick/cross annotations for one question on one page using the
    deterministic tier-based rules:

      Score ≥ 75%  → tick,  2 per non-last page, 1 on last page
      Score 41-74% → tick,  1 per page
      Score 25-40% → cross, 1 per page
      Score < 25%  → cross, 2 per non-last page, 1 on last page

    Shared-page rule: when n_questions_on_page > 1, cap at 1 annotation
    per question (of the correct tier type).

    Returns list of {"y_pdf": float, "ann_x": float, "action": str}
    """
    if marks_total <= 0:
        return []

    # ── How many annotations for this page? ──────────────────────────────────
    action, count_normal, count_last = _tier_ann_params(marks_obtained, marks_total)
    is_last_page = (page_idx_in_q == total_pages - 1)
    n_anns = count_last if is_last_page else count_normal

    # Shared-page cap: multiple questions on the same page → 1 each
    if n_questions_on_page > 1:
        n_anns = 1

    # ── Determine valid vertical range ───────────────────────────────────────
    # Hard floor: never annotate inside the top 12% margin.
    # NOTE: do NOT add heading_y_frac as a floor here. The slice bounds already
    # incorporate the heading position; adding another offset crushes the zone
    # on tight pages and prevents any annotation from being placed at all.
    lower_bound = max(slice_top, ink_top, 0.12)
    upper_bound = min(slice_bot, ink_bot - 0.02, 0.88)
    if upper_bound <= lower_bound:
        lower_bound = max(0.12, ink_top)
        upper_bound = min(0.88, ink_bot - 0.02)
    if upper_bound <= lower_bound:
        return []  # page has no usable space

    # Dynamic separation so annotations don't crowd on short answers
    slice_h = max(0.05, upper_bound - lower_bound)
    MIN_SEP = 0.18 if slice_h >= 0.55 else (0.12 if slice_h >= 0.30 else 0.08)

    # ── Place n_anns annotations evenly spaced in [lower_bound, upper_bound] ─
    result = []
    for i in range(n_anns):
        if n_anns == 1:
            target_frac = (lower_bound + upper_bound) / 2.0
        else:
            # Spread evenly: first at 25%, last at 75% of the slice
            t = i / (n_anns - 1)   # 0.0 … 1.0
            span_lo = lower_bound + slice_h * 0.20
            span_hi = lower_bound + slice_h * 0.80
            target_frac = span_lo + t * (span_hi - span_lo)

        target_frac = max(lower_bound, min(target_frac, upper_bound))

        # Collision avoidance
        y_frac = _get_non_colliding_y(target_frac, page_used_y_fracs, lower_bound, upper_bound, MIN_SEP)
        if y_frac is None:
            if i == 0:
                # Must place at least 1 — relax separation
                y_frac = _get_non_colliding_y(target_frac, page_used_y_fracs, lower_bound, upper_bound, MIN_SEP * 0.5)
            if y_frac is None:
                continue   # no room — skip this annotation

        y_frac = max(0.12, min(y_frac, 0.88))
        y_pdf  = pdf_h * (1.0 - y_frac) + random.uniform(-4, 4)
        page_used_y_fracs.append(y_frac)
        if page_excluded_px_rows is not None:
            ann_y_px = int(y_frac * img_h)
            for pr in range(ann_y_px - 40, ann_y_px + 41):
                page_excluded_px_rows.add(pr)

        # Find X position in ink (cross) or clear space (tick)
        if gray is not None:
            if action == "cross":
                ann_x = _find_ink_x(gray, img_w, img_h, pdf_w, y_frac, is_practical)
            else:
                ann_x = _find_clear_x(
                    gray, img_w, img_h, pdf_w, y_frac, is_practical,
                    excluded_px_rows=page_excluded_px_rows,
                )
        else:
            ann_x = _random_ann_x(pdf_w, is_practical=is_practical)

        result.append({"y_pdf": y_pdf, "ann_x": ann_x, "action": action})

    return result



def _place_feedback_below_stamp(
    stamp_y: float,
    stamp_half_h: float,
    fb_text: str,
    pdf_w: float,
    pdf_h: float,
    font_size: float,
    page_scale: float = 1.0,
) -> tuple[float, float] | None:
    """
    Place feedback text directly below the marks stamp with a 1 cm (28pt) gap.

    stamp_y      : ReportLab y-coordinate of the stamp centre (bottom-origin)
    stamp_half_h : half-height of the stamp in PDF points
    fb_text      : feedback string (may contain newlines)
    font_size    : font size in PDF points

    Returns (fb_x, fb_y) where fb_y is the baseline of the FIRST line of text.
    Returns None if there is no room on the page even for a single line.
    """
    import textwrap
    GAP_PTS   = 28.0 * page_scale   # 1 cm at this page scale
    MIN_Y     = max(20.0, 30.0 * page_scale)  # bottom margin in PDF points
    LINE_H    = font_size * 1.5

    # Bottom edge of the stamp in ReportLab coords (low y = low on page)
    stamp_bottom = stamp_y - stamp_half_h
    # First line baseline sits GAP_PTS below the stamp bottom
    fb_y_first = stamp_bottom - GAP_PTS

    # Estimate total height required
    wrapped = []
    for raw_line in fb_text.split('\n'):
        wrapped.extend(textwrap.wrap(raw_line, width=55))
    if not wrapped:
        return None
    n_lines      = len(wrapped)
    total_height = n_lines * LINE_H

    # Bottom of feedback block
    fb_y_bottom = fb_y_first - total_height

    # If block would go below the page margin, shift upward
    if fb_y_bottom < MIN_Y:
        shift = MIN_Y - fb_y_bottom
        fb_y_first  += shift
        fb_y_bottom += shift

    # If the first line itself is off the top of the page — no room
    if fb_y_first > pdf_h - 20:
        return None

    # Also cannot be above the stamp itself (edge case: stamp near top)
    if fb_y_first > stamp_bottom - 4:
        return None

    fb_x = max(20.0, pdf_w * 0.04)   # small left margin
    return fb_x, fb_y_first


# ── Helpers ───────────────────────────────────────────────────────────────────

def _block_y_pdf(center_frac: float, pdf_h: float) -> float:
    return pdf_h * (1.0 - center_frac)


# ── Main ──────────────────────────────────────────────────────────────────────

# ── Page-bounds data (loaded once per document, used to clamp annotations) ────
_page_bounds_data: dict = {}   # str(page_num) → {x_min, x_max, y_min, y_max}


def _get_page_x_bounds(page_num: int, pdf_w: float) -> tuple[float, float]:
    """
    Return (x_min_px, x_max_px) for annotation placement on this page.
    If page_bounds_data is loaded, returns the detected paper boundary in PDF
    point coordinates.  Otherwise falls back to [15%, 85%] of page width.
    """
    key = str(page_num)
    if key in _page_bounds_data:
        b = _page_bounds_data[key]
        # Add a small inner margin (1.5%) so annotations don't sit exactly on edge
        margin = pdf_w * 0.015
        return (b["x_min"] * pdf_w + margin, b["x_max"] * pdf_w - margin)
    return (pdf_w * 0.15, pdf_w * 0.85)


def generate_checked_copy(
    pdf_path: str,
    grading_json: str,
    aligned_json: str,
    output_path: str,
    ocr_text_path: str = None,
    manifest_path: str = None,
    page_bounds_path: str = None,
):
    print(f"\n{'='*62}")
    print("  STAGE 7 — Generating Checked Copy (Student-Facing)")
    print(f"{'='*62}")
    print(f"  Source  : {pdf_path}")
    print(f"  Output  : {output_path}")

    _ensure_tesseract()

    # ── Load page bounds if available ─────────────────────────────────────────
    global _page_bounds_data
    _page_bounds_data.clear()
    if page_bounds_path and os.path.exists(page_bounds_path):
        with open(page_bounds_path, "r") as _pb:
            _page_bounds_data = json.load(_pb)
        print(f"  ✓ Page bounds loaded from {page_bounds_path} ({len(_page_bounds_data)} pages)", flush=True)

    # Reset per-document feedback state
    _feedback_cache.clear()
    _used_feedback_texts.clear()

    with open(grading_json, "r") as f:
        grading_data = json.load(f)
    with open(aligned_json, "r") as f:
        aligned_data = json.load(f)

    graded_answers = grading_data.get("graded_answers", {})
    font_name      = _register_fonts()

    # ── Annotation manifest (v2 addition) ─────────────────────────────────────
    # Collects every drawn element so patch_checked_copy.py can rebuild the
    # overlay without LLM calls or image analysis.
    _manifest: dict = {
        "source_pdf":   pdf_path,
        "output_pdf":   output_path,
        "grading_json": grading_json,
        "aligned_json": aligned_json,
        "generated_at": None,          # filled just before saving
        "grand_total":  None,
        "questions":    {},             # manifest_key → annotation record
    }

    # Deferred feedbacks: when stamp is too low for feedback to fit on the same
    # page, we queue it here keyed by manifest_key and place it on the NEXT page.
    _deferred_feedbacks: dict = {}   # mkey → {"text": str, "font_size": int, "scale": float}

    # Flat grading lookup: (section, q_id) → entry
    # Also indexes FT sub-part keys: (section, "Q1a") → sub-part grade entry
    grading_lookup: dict = {}
    for section, sec_data in graded_answers.items():
        for q_id, entry in sec_data.items():
            grading_lookup[(section, q_id)] = entry
            # FT nested format: entry is a dict of sub-parts {Q1a: {...}, Q1b: {...}}
            if isinstance(entry, dict) and "marks_obtained" not in entry:
                for sub_id, sub_entry in entry.items():
                    if isinstance(sub_entry, dict) and "marks_obtained" in sub_entry:
                        grading_lookup[(section, sub_id)] = sub_entry

    reader    = PdfReader(pdf_path)
    doc       = fitz.open(pdf_path)
    num_pages = len(reader.pages)
    page_dims = [(float(p.mediabox.width), float(p.mediabox.height))
                 for p in reader.pages]

    # Grand total from paper metadata (not sum of attempted q totals)
    meta            = grading_data.get("metadata", {})
    grand_obtained  = float(meta.get("total_marks_obtained", 0) or 0)
    grand_total     = float(meta.get("total_marks_possible", 0) or 0)
    # Fallback: sum from graded answers if metadata absent
    if grand_total == 0:
        for sec_data in graded_answers.values():
            for entry in sec_data.values():
                grand_obtained += float(entry.get("marks_obtained", 0) or 0)
                grand_total    += float(entry.get("marks_total",    0) or 0)

    paper_num       = str(meta.get("paper_num", "")).lower()
    is_portionwise  = ("portionwise" in paper_num) or (grand_total < 100)
    is_full_paper   = not is_portionwise
    _mcq_entries = [
        entry for (sec, q_id), entry in grading_lookup.items()
        if sec == "SectionA" and "marks_obtained" in entry
    ]
    _mcq_skipped = _mcq_entries and all(e.get("skipped_mcq") or e.get("marks_obtained") is None for e in _mcq_entries)
    if _mcq_skipped:
        mcq_total_obtained = None   # pending — teacher enters manually
    else:
        mcq_total_obtained = sum(
            float(entry.get("marks_obtained", 0) or 0)
            for entry in _mcq_entries
        )
    mcq_total_possible = 30.0
    mcq_page_marked = False


    # ── Build per-page drawing plan ────────────────────────────────────────────
    drawing_plan: dict = {}   # page_num → list of plan items

    def _iter_leaf_questions(section: str, sec_data: dict):
        """
        Yield (effective_q_id, aligned_q_dict, grade_entry) for every leaf question.

        Handles two formats transparently:
          • Old/flat  : SectionB → Q1 → {answer_pages, student_answer, ...}
          • FT/nested : SectionB → Q1 → Q1a → {answer_pages, student_answer, ...}

        A dict is a 'leaf' when it has an 'answer_pages' key directly.
        A dict is a 'parent' when its values are further dicts (sub-parts).
        """
        for q_id, aligned_q in sec_data.items():
            if not isinstance(aligned_q, dict):
                continue

            if "answer_pages" in aligned_q:
                # ── Old flat format ──
                grade_entry = grading_lookup.get((section, q_id))
                if grade_entry is None:
                    for k, v in grading_lookup.items():
                        if k[1] == q_id:
                            grade_entry = v
                            break
                if grade_entry is not None:
                    yield q_id, aligned_q, grade_entry
            else:
                # ── FT nested format: iterate sub-parts ──
                for sub_id, sub_q in aligned_q.items():
                    if not isinstance(sub_q, dict) or "answer_pages" not in sub_q:
                        continue
                    # Look up grading for the sub-part key directly
                    grade_entry = grading_lookup.get((section, sub_id))
                    if grade_entry is None:
                        # Try looking inside the parent's graded dict
                        parent_entry = grading_lookup.get((section, q_id), {})
                        if isinstance(parent_entry, dict):
                            grade_entry = parent_entry.get(sub_id)
                    if grade_entry is None:
                        for k, v in grading_lookup.items():
                            if k[1] == sub_id:
                                grade_entry = v
                                break
                    if grade_entry is not None:
                        yield sub_id, sub_q, grade_entry

    # ── Pre-pass: detect sub-questions that share identical answer_pages ──────
    # When Q4a and Q4b both have answer_pages=[5,6,7] (student wrote them
    # continuously), placing both stamps on page 5 causes the "is_first"
    # marker for Q4b to land on the wrong page (page 5 instead of where Q4b
    # actually ends).  We identify siblings that share pages and mark all but
    # the FIRST sibling (in schema order) as "deferred" — their stamp will be
    # placed on their LAST page instead of their first.
    _sibling_pages_seen: dict = {}  # frozenset(answer_pages) → first q_id that claimed it
    _deferred_stamp_q_ids: set = set()  # q_ids whose stamp should go on their last page

    for _section, _sec_data in aligned_data.items():
        for _q_id, _aligned_q, _grade_entry in _iter_leaf_questions(_section, _sec_data):
            if "MCQ" in _section or "MCQ" in _q_id or _q_id.isdigit():
                continue
            _ap = tuple(sorted(_aligned_q.get("answer_pages", [])))
            if not _ap:
                continue
            _key = (_section, _ap)
            if _key not in _sibling_pages_seen:
                _sibling_pages_seen[_key] = _q_id
            else:
                # This sub-question shares pages with a prior sibling → defer its stamp
                _deferred_stamp_q_ids.add((_section, _q_id))
                print(
                    f"  [sibling-page] {_section}/{_q_id} shares pages {list(_ap)} "
                    f"with {_sibling_pages_seen[_key]} → stamp deferred to last page",
                    flush=True,
                )

    for section, sec_data in aligned_data.items():
        for q_id, aligned_q, grade_entry in _iter_leaf_questions(section, sec_data):
            # ── Skip MCQs entirely — no annotations or marks stamps for MCQs ──
            if "MCQ" in section or "MCQ" in q_id or q_id.isdigit():
                continue

            answer_pages = aligned_q.get("answer_pages", [])
            if not answer_pages:
                continue

            # ── Sibling-page deferral: stamp goes on the LAST page ────────────
            # When this sub-part shares answer_pages with an earlier sibling,
            # mark it so that is_first=True is only set on the last answer page
            # (instead of the first), avoiding a collision with the sibling's
            # stamp on the shared first page.
            _is_deferred = (section, q_id) in _deferred_stamp_q_ids
            _stamp_page_idx = len(answer_pages) - 1 if _is_deferred else 0

            student_ans_str = grade_entry.get("student_answer", "").strip()
            if not student_ans_str or not is_meaningful_answer(student_ans_str) or grade_entry.get("grading_method") == "no_answer":
                print(f"  ⊘ Skip {section}/{q_id} — unanswered/meaningless")
                # Still add a phantom entry so the page-slice logic reserves
                # vertical space for this question's heading on a multi-Q page.
                # No stamp, annotations, or feedback will be drawn for it.
                q_num_ph = aligned_q.get("question_number", q_id).replace("Q", "").strip()
                for idx_ph, page_num_ph in enumerate(answer_pages):
                    drawing_plan.setdefault(page_num_ph, []).append({
                        "q_num":          q_num_ph,
                        "grade_entry":    grade_entry,
                        "is_first":       idx_ph == 0,
                        "page_idx_in_q":  idx_ph,
                        "total_pages":    len(answer_pages),
                        "marks_obtained": 0,
                        "marks_total":    float(grade_entry.get("marks_total", 0) or 0),
                        "tier":           "poor",
                        "fb_text":        None,
                        "wrong_final_answer": None,
                        "section":        section,
                        "q_id":           q_id,
                        "_phantom":       True,   # sentinel: skip all drawing
                    })
                continue

            tier = grade_entry.get("tier", "poor")
            if TIER_ACTION.get(tier) is None:
                continue


            q_num          = aligned_q.get("question_number", q_id).replace("Q", "").strip()
            marks_obtained = float(grade_entry.get("marks_obtained", 0) or 0)
            marks_total    = float(grade_entry.get("marks_total",    0) or 0)

            # Pre-generate LLM feedback — descriptive questions only, skip MCQs
            is_mcq = "MCQ" in section or "MCQ" in q_id or q_id.isdigit()
            # Skip feedback entirely for no-answer questions
            is_no_answer = (
                grade_entry.get("grading_method") == "no_answer" or
                not grade_entry.get("student_answer", "").strip()
            )
            fb_text = None
            is_zero_marks = (marks_obtained == 0)
            marks_ratio_local = (marks_obtained / marks_total) if marks_total > 0 else 0
            is_low_score = marks_ratio_local < 0.60

            # Check if student answer is minimal attempt (<=1 short line / prompt title only)
            student_ans_text = str(aligned_q.get("student_answer", "") or grade_entry.get("student_answer", "") or "").strip()
            cleaned_ans = re.sub(r'^(?:Question|Q|Ans\.?|Answer|Soln\.?|Solution)\s*#?\s*\d+[a-z]?[\s\.\:]*', '', student_ans_text, flags=re.IGNORECASE).strip()
            num_words = len(cleaned_ans.split())
            num_lines = len([l for l in student_ans_text.split('\n') if l.strip()])
            is_minimal_attempt = (num_lines <= 1 or num_words < 15 or not cleaned_ans)

            # Generate feedback:
            # - 0 marks + minimal attempt (student barely wrote anything): always suppress
            # - Non-zero marks < 60%: ALWAYS generate — no other gate applies
            # - Everything else: suppress only if zero marks AND minimal attempt
            if not is_mcq and not is_no_answer:
                if is_zero_marks and is_minimal_attempt:
                    pass  # hard suppress — student wrote nothing meaningful, 0 marks
                elif is_low_score or not is_zero_marks:
                    cache_key = f"{section}__{q_id}"
                    fb_text   = _generate_llm_feedback(grade_entry, cache_key)
                    if fb_text:
                        fb_text = fb_text.replace('response', 'answer').replace('Response', 'Answer')
                        fb_text = fb_text.replace('insightful', 'comprehensive').replace('Insightful', 'Comprehensive')
                        print(f'  💬 Feedback for Q{q_num}: "{fb_text}"', flush=True)

            # Check for fundamentally wrong final practical answer
            # Skip for no-answer questions — nothing to mark wrong
            wrong_final_answer = None if is_no_answer else _check_final_answer_wrong(grade_entry, aligned_q.get("student_answer", ""))
            target_page = None
            if wrong_final_answer:
                search_text = wrong_final_answer["wrong_answer_text"]
                print(f"  ⭕ Detected wrong final answer for Q{q_num}: '{search_text}'")
                try:
                    if ocr_text_path and os.path.exists(ocr_text_path):
                        with open(ocr_text_path, "r") as f:
                            ocr_content = f.read()
                        pages = ocr_content.split("=== Page ")
                        # Fallback simple search
                        for p in pages:
                            if not p.strip(): continue
                            p_num_str = p.split(" ===")[0]
                            if search_text.lower() in p.lower():
                                target_page = int(p_num_str)
                                break
                except Exception as e:
                    pass
                    
                if not target_page and answer_pages:
                    target_page = answer_pages[-1]

            for idx_in_q, page_num in enumerate(answer_pages):
                drawing_plan.setdefault(page_num, []).append({
                    "q_num":         q_num,
                    "grade_entry":   grade_entry,
                    "is_first":      idx_in_q == _stamp_page_idx,
                    "page_idx_in_q": idx_in_q,
                    "total_pages":   len(answer_pages),
                    "marks_obtained": marks_obtained,
                    "marks_total":   marks_total,
                    "tier":          tier,
                    # Feedback on the stamp page (first for normal, last for deferred)
                    "fb_text":       fb_text if idx_in_q == _stamp_page_idx else None,
                    # Circle task assigned to the precise target page
                    "wrong_final_answer": wrong_final_answer["wrong_answer_text"] if wrong_final_answer and page_num == target_page else None,
                    # Semantic annotation fragments from grader Phase 1
                    "wrong_lines":   grade_entry.get("wrong_lines", []) or [],
                    "correct_lines": grade_entry.get("correct_lines", []) or [],
                    # v2: manifest tracking
                    "section":       section,
                    "q_id":          q_id,
                })

    print(f"  Annotating {len(drawing_plan)} pages")

    # ── Build overlay canvas ──────────────────────────────────────────────────
    packet = io.BytesIO()
    c      = canvas.Canvas(packet)

    for page_idx in range(num_pages):
        page_num     = page_idx + 1
        pdf_w, pdf_h = page_dims[page_idx]
        c.setPageSize((pdf_w, pdf_h))
        _gt_y_frac_page1 = None   # set below when grand-total stamp is drawn on p1
        _gt_bounds_page1 = None

        # ── Page-scale factor (A4 = 842 pt reference) ─────────────────────────
        # Calibrate all annotation sizes to the actual page height so stamps,
        # ticks, and feedback look identical regardless of scan resolution.
        REF_H      = 842.0
        page_scale = pdf_h / REF_H   # 1.0 for A4, ~3.26 for 2748pt scans

        items = drawing_plan.get(page_num, [])
        if not items and page_num != 1:
            c.showPage()
            continue

        fitz_page              = doc[page_idx]
        gray, img_w, img_h, sx, sy = _render_gray(fitz_page)
        text_blocks = _get_text_blocks(gray, img_w, img_h)
        page_excluded_px_rows: set = set()

        # ── Grand total stamp on page 1 (top-right corner) ─────────────────────────
        if page_num == 1 and grand_total > 0:
            # Estimate oval radius for the scaled stamp so we can clamp within page
            STAMP_FONT  = int(42 * page_scale)
            STAMP_CHARS = max(len(str(int(grand_obtained))), len(str(int(grand_total))))
            oval_rx = (STAMP_CHARS * STAMP_FONT * 0.58 / 2) + STAMP_FONT * 0.40 + 8
            oval_ry = (STAMP_FONT * 2 + int(5 * page_scale) * 2 + 2) / 2 + STAMP_FONT * 0.25
            # Keep stamp fully on-page: stay at least oval_rx from each edge
            gt_x_max = pdf_w - oval_rx - 8
            gt_x_min = pdf_w * 0.55
            gt_y_max = pdf_h - oval_ry - 8
            gt_y_min = oval_ry + 8
            gt_x, gt_y = _find_clear_xy(
                gray, img_w, img_h, pdf_w, pdf_h,
                target_y_frac=0.07, is_practical=False, min_clear_cols=80,
            )
            # If the clear search drifted way too far down (e.g. past top 15%),
            # force the stamp to the top-center to prevent it from
            # floating awkwardly in the middle of page 1.
            if 1.0 - gt_y / pdf_h > 0.15:
                gt_x, gt_y = pdf_w / 2.0, gt_y_max
            else:
                gt_x = max(gt_x_min, min(gt_x_max, gt_x))
                gt_y = max(gt_y_min, min(gt_y_max, gt_y))
            _draw_total_marks_stamp(c, gt_x, gt_y, grand_obtained, grand_total,
                                    font_name, scale=page_scale)
            # Record grand-total position so Q1a feedback search avoids it
            _gt_y_frac_page1 = 1.0 - gt_y / pdf_h   # convert ReportLab y → image frac
            _gt_bounds_page1 = (gt_y - oval_ry, gt_y + oval_ry)
            _manifest["grand_total"] = {
                "obtained":    grand_obtained,
                "total":       grand_total,
                "page":        page_num,
                "x":           gt_x,
                "y":           gt_y,
                "y_frac":      _gt_y_frac_page1,
                "scale":       page_scale,
                "mcq_pending": mcq_total_obtained is None,
            }

        # ── MCQ total stamp on page where MCQs are (or fallback to last page) ──────────
        if (is_full_paper or len(_mcq_entries) > 0) and not mcq_page_marked:
            ocr_page_text = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""
            has_mcqs_for_stamp = False
            
            # If it's the last page and we still haven't marked it, force it here
            is_last_page = (page_num == num_pages)
            
            if ocr_page_text:
                # Use stricter keywords so we don't accidentally match page 1 because of "(a)"
                for mcq_key in ["mcq", "multiple choice", "section a", "section-a"]:
                    if mcq_key in ocr_page_text.lower():
                        has_mcqs_for_stamp = True
                        break
            
            if has_mcqs_for_stamp or is_last_page:
                    mcq_page_marked = True
                    _f = int(28 * page_scale)
                    _half_h = _f * 2 + int(4 * page_scale) * 2 + _f * 0.20 + 10
                    mcq_x = pdf_w * 0.15
                    mcq_y = pdf_h * 0.88 - _half_h

                    if mcq_total_obtained is None:
                        # MCQ marks pending — draw ?/30 placeholder
                        _draw_pending_mcq_stamp(c, mcq_x, mcq_y, mcq_total_possible, font_name, scale=page_scale)
                    else:
                        _draw_marks_stamp(c, mcq_x, mcq_y, mcq_total_obtained, mcq_total_possible, font_name, scale=page_scale)

                    _manifest["mcq_total"] = {
                        "obtained": mcq_total_obtained,   # None = pending
                        "total":    mcq_total_possible,
                        "pending":  mcq_total_obtained is None,
                        "page":     page_num,
                        "x":        mcq_x,
                        "y":        mcq_y,
                        "scale":    page_scale,
                    }

                    # Exclude pixels so feedback search doesn't land on it
                    stamp_cy_px = int((1.0 - mcq_y / pdf_h) * img_h)
                    for pr in range(stamp_cy_px - 80, stamp_cy_px + 81):
                        page_excluded_px_rows.add(pr)



        if not items:
            c.showPage()
            continue


        # ── Extract precise text bounding boxes using PaddleOCR ──────────────
        pix_page = fitz_page.get_pixmap(dpi=150)
        img_np = np.frombuffer(pix_page.samples, dtype=np.uint8).reshape(pix_page.height, pix_page.width, pix_page.n)
        if pix_page.n == 4:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        paddle_lines = _extract_page_boxes_paddle(img_bgr)

        # Compute ink bounds from PaddleOCR bounding boxes (or fallback to image analysis)
        if paddle_lines:
            ink_top = max(0.04, min(l["ymin"] for l in paddle_lines))
            ink_bot = min(0.96, max(l["ymax"] for l in paddle_lines))
            print(f"    [PaddleOCR] Extracted {len(paddle_lines)} text boxes: ink_top={ink_top:.3f}, ink_bot={ink_bot:.3f}", flush=True)
        elif text_blocks:
            ink_top = max(0.04, min(b[0] - b[1]/2 for b in text_blocks))
            ink_bot = min(0.96, max(b[0] + b[1]/2 for b in text_blocks))
            print(f"    [DEBUG] PyMuPDF raw bounds: ink_top={ink_top:.3f}, ink_bot={ink_bot:.3f}", flush=True)
        else:
            ink_top, ink_bot = 0.04, 0.96

        # ── Authoritative ink_bot scan ──────────────────────────────────────────
        strict_ink_bot = _compute_ink_bot_strict(gray, img_w, img_h)
        if strict_ink_bot > ink_bot and not paddle_lines:
            ink_bot = strict_ink_bot
        print(f"    [DEBUG] Final ink bounds: ink_top={ink_top:.3f}, ink_bot={ink_bot:.3f}", flush=True)

        # Ensure ink_bot is always at least 0.10 below ink_top
        ink_bot = max(ink_bot, ink_top + 0.10)

        # ── Pre-compute headings for all is_first items on this page ────────────────
        pre_heading_fracs: dict = {}   # q_num → image-space fraction (0=top, 1=bottom)
        _page_ocr_for_headings = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""
        for _it in items:
            if not _it.get("is_first"):
                continue  # continuation questions start at top of page, no heading needed
            _hy = _find_heading_y(
                fitz_page, gray, img_w, img_h, pdf_h,
                _it["q_num"], ocr_text_path, paddle_lines=paddle_lines
            )
            if _hy is not None:
                pre_heading_fracs[_it["q_num"]] = 1.0 - _hy / pdf_h  # → image frac
                print(f"    [heading] Found Q{_it['q_num']} heading at y_frac={pre_heading_fracs[_it['q_num']]:.3f}", flush=True)

        # Also search paddle_lines for un-attempted phantom questions that appear on this page
        _items_base = {re.search(r'\d+', it['q_num']).group(0) for it in items if re.search(r'\d+', it['q_num'])}
        if paddle_lines:
            for l in paddle_lines:
                for _sec, _sec_data in graded_answers.items():
                    if isinstance(_sec_data, dict):
                        for _qid in _sec_data:
                            _clean_q = _qid.replace("Q", "").strip()
                            m_base = re.search(r'\d+', _clean_q)
                            if m_base and m_base.group(0) in _items_base:
                                continue
                            if _clean_q not in pre_heading_fracs and _match_q_heading_text(l["text"], _clean_q):
                                pre_heading_fracs[_clean_q] = l["ymin"]
                                print(f"    [heading] Found phantom Q{_clean_q} heading at y_frac={l['ymin']:.3f}: \"{l['text']}\"", flush=True)

        # Track chosen Y coordinates (as fractions) globally per page
        page_used_y_fracs = []
        page_drawn_rects_y = []  # List of (y_bottom, y_top) in PDF coords
        _page_mcq_top = False   # True when page 1 has MCQ answers in upper half
        page_annotations_count = 0

        # ── Pre-reserve the grand-total stamp zone on page 1 ──────────────
        if page_num == 1 and grand_total > 0 and _gt_y_frac_page1 is not None:
            for i in range(-12, 13):
                page_used_y_fracs.append(max(0.0, min(1.0, _gt_y_frac_page1 + i * 0.01)))
            if _gt_bounds_page1:
                page_drawn_rects_y.append(_gt_bounds_page1)
            _gt_px = int(_gt_y_frac_page1 * img_h)
            for _pr in range(max(0, _gt_px - 60), min(img_h, _gt_px + 61)):
                page_excluded_px_rows.add(_pr)



        for item in items:
            q_num          = item["q_num"]
            grade_entry    = item["grade_entry"]
            is_first       = item["is_first"]
            marks_obtained = item["marks_obtained"]
            tier           = item["tier"]
            fb_text        = item["fb_text"]

            # v2: manifest key for this question
            _m_section = item.get("section", "")
            _m_q_id    = item.get("q_id",    q_num)
            _mkey      = f"{_m_section}__{_m_q_id}"
            if _mkey not in _manifest["questions"]:
                _manifest["questions"][_mkey] = {
                    "section":        _m_section,
                    "q_id":           _m_q_id,
                    "q_num":          q_num,
                    "marks_obtained":  marks_obtained,
                    "marks_total":     item["marks_total"],
                    "stamp":           None,
                    "feedback":        None,
                    "ticks_crosses":   [],
                }

            # ── Load OCR and practical flag early ──────────────────────────────
            is_practical  = "practical" in grade_entry.get("grading_method", "").lower()
            ocr_page_text = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""
            _is_phantom = item.get("_phantom", False)

            # ── Marks stamp on first page of each answer ───────────────────────
            heading_y = None
            heading_y_frac = None
            if is_first:
                heading_y = _find_heading_y(
                    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_text_path, paddle_lines=paddle_lines
                )
                if heading_y:
                    heading_y_frac = 1.0 - heading_y / pdf_h

            # ── Pre-compute per-question vertical slices ───────────────────────
            page_q_items = list(items)
            _items_qnums = {it["q_num"] for it in page_q_items}
            _items_base_set = {re.search(r'\d+', it['q_num']).group(0) for it in page_q_items if re.search(r'\d+', it['q_num'])}
            _phantom_slots = [
                {"q_num": qn, "is_first": True, "_phantom": True}
                for qn in pre_heading_fracs
                if qn not in _items_qnums and (not re.search(r'\d+', qn) or re.search(r'\d+', qn).group(0) not in _items_base_set)
            ]
            page_q_items = page_q_items + _phantom_slots

            if len(page_q_items) > 1:
                page_q_items = sorted(
                    page_q_items,
                    key=lambda it: 0.0 if not it.get("is_first") else pre_heading_fracs.get(it["q_num"], 0.5)
                )

            n_items = len(page_q_items)
            my_order = next((idx for idx, it in enumerate(page_q_items) if it["q_num"] == q_num), 0)

            if n_items == 1:
                q_top_frac = ink_top
                q_bot_frac = ink_bot
            else:
                # Multi-question slicing
                if my_order == 0:
                    q_top_frac = ink_top
                else:
                    q_top_frac = pre_heading_fracs.get(q_num, ink_top)

                if my_order < n_items - 1:
                    next_q = page_q_items[my_order + 1]["q_num"]
                    q_bot_frac = pre_heading_fracs.get(next_q, ink_bot)
                else:
                    q_bot_frac = ink_bot

            q_bot_frac = max(q_bot_frac, q_top_frac + 0.08)
            _item_slice_top = q_top_frac
            _item_slice_bot = q_bot_frac
            print(f"    [slice] Q{q_num} order {my_order+1}/{n_items}: [{q_top_frac:.3f}..{q_bot_frac:.3f}] (heading={heading_y_frac})", flush=True)

            # Phantoms only needed the slice computation above.
            # Skip all stamp/annotation/feedback drawing.
            if is_first and not _is_phantom:
                if is_full_paper and section == "SectionA":
                    _STAMP_FONT   = int(28 * page_scale)
                    _STAMP_HALF_H = _STAMP_FONT * 2 + int(4 * page_scale) * 2 + _STAMP_FONT * 0.20 + 10
                    if not mcq_page_marked:
                        _pending_stamp = {
                            "x":           pdf_w * 0.1,  # near left margin
                            "y":           pdf_h * 0.88 - _STAMP_HALF_H, # top
                            "half_h_pts":  _STAMP_HALF_H,
                            "marks_obtained": mcq_total_obtained,
                            "marks_total":    30,  # MCQ total marks
                        }
                        mcq_page_marked = True
                        stamp_cy_px = int((1.0 - _pending_stamp["y"] / pdf_h) * img_h)
                        for pr in range(stamp_cy_px - 80, stamp_cy_px + 81):
                            page_excluded_px_rows.add(pr)
                    else:
                        _pending_stamp = None
                    print(f"  ✓ P{page_num:>2} Q{q_num:<3} MCQ (Full Paper)", flush=True)
                else:
                    _STAMP_FONT   = int(28 * page_scale)
                    _STAMP_HALF_H = _STAMP_FONT * 2 + int(4 * page_scale) * 2 + _STAMP_FONT * 0.20 + 10

                    # Convert to pixel rows; search within the question vertical extent
                    stamp_row_top = max(0, int(q_top_frac * img_h))
                    stamp_row_bot = min(img_h, int(q_bot_frac * img_h))
                    stamp_row_bot = max(stamp_row_bot, stamp_row_top + 20)

                    # Scan left margin for clean spot in question's slice
                    margin_spot = _find_left_margin_stamp_spot(
                        gray, img_w, img_h, pdf_w, pdf_h,
                        stamp_row_top, stamp_row_bot,
                        excluded_px_rows=page_excluded_px_rows,
                    )
                    if margin_spot:
                        marks_x, marks_y_placed = margin_spot
                        rh_st = 60
                        print(f"    ← left-margin stamp at x={marks_x:.0f}, y={marks_y_placed:.0f}", flush=True)
                    else:
                        # Direct zone-top placement in left margin
                        _target_stamp_frac = q_top_frac + 0.04
                        marks_y_placed = pdf_h * (1.0 - _target_stamp_frac) - _STAMP_HALF_H
                        marks_x = max(24.0, pdf_w * 0.04)
                        rh_st = 60
                        print(f"    ← direct zone-top stamp at x={marks_x:.0f}, y={marks_y_placed:.0f}", flush=True)
                    
                    # Clamp stamp Y position so it avoids top 12% margin and bottom 5%
                    marks_y_placed = min(max(marks_y_placed, pdf_h * 0.05 + _STAMP_HALF_H), pdf_h * 0.88 - _STAMP_HALF_H)

                    # Register the stamp's pixel row range so feedback avoids it
                    stamp_cy_px = int((1.0 - marks_y_placed / pdf_h) * img_h)
                    STAMP_H_PX  = max(int(rh_st), 80)   # at least 80px exclusion zone
                    for pr in range(stamp_cy_px - STAMP_H_PX // 2,
                                    stamp_cy_px + STAMP_H_PX // 2 + 1):
                        page_excluded_px_rows.add(pr)
                    stamp_y_frac = 1.0 - marks_y_placed / pdf_h
                    page_used_y_fracs.append(stamp_y_frac)

                    # ── Store stamp info; actual drawing is DEFERRED until after feedback ──
                    # This allows the overlap check to move the stamp before drawing it
                    # (re-drawing on top leaves the original in the PDF too).
                    _pending_stamp = {
                        "x":           marks_x + random.uniform(-1, 2),
                        "y":           marks_y_placed,
                        "half_h_pts":  _STAMP_HALF_H,
                        "marks_obtained": marks_obtained,
                        "marks_total":    item["marks_total"],
                    }
                    print(f"  ✓ P{page_num:>2} Q{q_num:<3} {_fmt_marks(marks_obtained)}/{_fmt_marks(item['marks_total'])} [{tier}]", flush=True)
            else:
                # No stamp on continuation pages
                if _is_phantom:
                    continue   # nothing to draw for unanswered questions
                _pending_stamp = None
                print(f"  → P{page_num:>2} Q{q_num:<3} continuation", flush=True)


            # ── Plan tick/cross annotations (new deterministic tier-based logic) ───
            # n_questions_on_page = number of non-phantom first-questions on this page
            # (only is_first items count — continuation items don't add stamps/ticks)
            n_questions_on_page = len([it for it in items if it.get("is_first") and not it.get("_phantom")])

            # Only plan annotations on the FIRST page of a question (where the stamp appears).
            # Continuation pages have no stamp and should not accumulate extra ticks/crosses.
            if _is_phantom:
                annotations = []
            else:
                annotations = _plan_annotations_new(
                    marks_obtained        = marks_obtained,
                    marks_total           = item["marks_total"],
                    page_idx_in_q         = item["page_idx_in_q"],
                    total_pages           = item["total_pages"],
                    n_questions_on_page   = n_questions_on_page,
                    gray                  = gray,
                    img_w                 = img_w,
                    img_h                 = img_h,
                    pdf_w                 = pdf_w,
                    pdf_h                 = pdf_h,
                    slice_top             = _item_slice_top,
                    slice_bot             = _item_slice_bot,
                    page_used_y_fracs     = page_used_y_fracs,
                    page_excluded_px_rows = page_excluded_px_rows,
                    is_practical          = is_practical,
                    ink_top               = ink_top,
                    ink_bot               = ink_bot,
                    heading_y_frac        = (1.0 - heading_y / pdf_h) if heading_y else None,
                )
            page_annotations_count += len(annotations)

            # ── Feedback placement: directly below the marks stamp ──────────────
            # Feedback is placed right below the stamp with a 1 cm gap.
            # This is computed AFTER the stamp position is finalised.
            # We store (fb_x_final, fb_y_final) for drawing later.
            fb_x_final, fb_y_final = None, None
            placed = False

            # ── Place any deferred feedback from the PREVIOUS page ──────────
            # If the stamp on the prior page was too low for feedback to fit,
            # the feedback was queued in _deferred_feedbacks; place it now at
            # the TOP of this continuation page (below the top margin).
            if not is_first and _mkey in _deferred_feedbacks:
                _df = _deferred_feedbacks.pop(_mkey)
                _df_font = _df["font_size"]
                # Place at the top of the page slice, just below the margin
                _df_y = pdf_h * (1.0 - (_item_slice_top + 0.04))
                _df_y = max(_df_font * 2, min(_df_y, pdf_h - _df_font * 2))
                _df_x = max(20.0, pdf_w * 0.04)
                _manifest["questions"][_mkey]["deferred_feedback"] = {
                    "text":      _df["text"],
                    "page":      page_num,
                    "x":         _df_x,
                    "y":         _df_y,
                    "font_size": _df_font,
                    "scale":     _df["scale"],
                }
                print(f"    [deferred-fb] Q{q_num} feedback placed at top of continuation page {page_num} (y={_df_y:.0f})", flush=True)

            # ── Finalise stamp Y ──────────────────────────────────────────────
            final_stamp_y = _pending_stamp["y"] if _pending_stamp is not None else None
            if _pending_stamp is not None and final_stamp_y is not None:
                stamp_half_h = _pending_stamp["half_h_pts"]
                final_stamp_y = min(
                    max(final_stamp_y, stamp_half_h + 10),
                    pdf_h - stamp_half_h - 10,
                )
                # Store half_h so feedback can reference it after stamp is finalised
                _manifest["questions"][_mkey]["stamp"] = {
                    "page":           page_num,
                    "x":              _pending_stamp["x"],
                    "y":              final_stamp_y,
                    "scale":          page_scale,
                    "marks_obtained": _pending_stamp["marks_obtained"],
                    "marks_total":    _pending_stamp["marks_total"],
                    "half_h_pts":     stamp_half_h,
                }
                page_drawn_rects_y.append((final_stamp_y - stamp_half_h, final_stamp_y + stamp_half_h))
                _pending_stamp = None   # consumed

                # ── Place feedback IMMEDIATELY from the clamped stamp y ────────────
                if fb_text and not (is_full_paper and section == "SectionA"):
                    FB_FONT_SIZE_F = int(14 * page_scale)
                    _fb_spot = _place_feedback_below_stamp(
                        stamp_y      = final_stamp_y,
                        stamp_half_h = stamp_half_h,
                        fb_text      = fb_text,
                        pdf_w        = pdf_w,
                        pdf_h        = pdf_h,
                        font_size    = FB_FONT_SIZE_F,
                        page_scale   = page_scale,
                    )
                    if _fb_spot:
                        fb_x_final, fb_y_final = _fb_spot
                        import textwrap as _tw2
                        _fb_wl = []
                        for _r in fb_text.split('\n'): _fb_wl.extend(_tw2.wrap(_r, width=55))
                        _fb_h_pts = len(_fb_wl) * FB_FONT_SIZE_F * 1.5

                        # Check if feedback overflows this question's vertical slice
                        _slice_bot_y_pdf = pdf_h * (1.0 - _item_slice_bot)
                        _has_next = (item["page_idx_in_q"] + 1 < item["total_pages"])
                        if _has_next and (fb_y_final - _fb_h_pts < _slice_bot_y_pdf):
                            _deferred_feedbacks[_mkey] = {
                                "text":      fb_text,
                                "font_size": FB_FONT_SIZE_F,
                                "scale":     page_scale,
                            }
                            print(f"    [feedback] Q{q_num}: overflows slice bounds ({fb_y_final - _fb_h_pts:.0f} < {_slice_bot_y_pdf:.0f}), deferring feedback to next page", flush=True)
                        else:
                            placed = True
                            _manifest["questions"][_mkey]["feedback"] = {
                                "text":      fb_text,
                                "page":      page_num,
                                "x":         fb_x_final,
                                "y":         fb_y_final,
                                "font_size": FB_FONT_SIZE_F,
                                "scale":     page_scale,
                            }
                            print(f"    [feedback] Q{q_num} at (x={fb_x_final:.0f}, y={fb_y_final:.0f}) — stamp={final_stamp_y:.0f}", flush=True)

                            # Register exclusion rows so other questions' annotations avoid feedback
                            _fb_cy_px = int((1.0 - fb_y_final / pdf_h) * img_h)
                            _fb_half = max(30, int((_fb_h_pts / pdf_h) * img_h) // 2 + 15)
                            for _pr2 in range(_fb_cy_px - _fb_half, _fb_cy_px + _fb_half + 1):
                                page_excluded_px_rows.add(_pr2)
                    else:
                        # Stamp too low — defer to next page if question continues
                        _has_next = (item["page_idx_in_q"] + 1 < item["total_pages"])
                        if _has_next:
                            _deferred_feedbacks[_mkey] = {
                                "text":      fb_text,
                                "font_size": int(14 * page_scale),
                                "scale":     page_scale,
                            }
                            print(f"    [feedback] Q{q_num}: stamp too low, deferring feedback to next page", flush=True)

            # ── Record ticks / crosses (drawn in the page-level draw phase) ───
            if not (is_full_paper and section == "SectionA"):
                for ann in annotations:
                    draw_x = ann["ann_x"] + random.uniform(-2, 2)
                    draw_y = ann["y_pdf"]
                    if _page_mcq_top and draw_y > pdf_h * 0.25:
                        continue
                    if draw_y > pdf_h - 30:
                        continue
                    if ann["action"] == "tick":
                        sz = random.uniform(65, 80) * page_scale
                    else:
                        sz = random.uniform(55, 70) * page_scale
                    _manifest["questions"][_mkey]["ticks_crosses"].append({
                        "page":   page_num,
                        "x":      draw_x,
                        "y":      draw_y,
                        "action": ann["action"],
                        "size":   sz,
                    })

        # === GLOBAL COLLISION RESOLUTION FOR THIS PAGE ===
        page_ticks = []
        page_stamps = []
        page_fbs = []
        page_p3 = []
        
        for mkey, qdata in _manifest["questions"].items():
            for i, t in enumerate(qdata.get("ticks_crosses", [])):
                if t["page"] == page_num:
                    page_ticks.append((t, "tick" if t["action"] == "tick" else "cross"))
            if qdata.get("stamp") and qdata["stamp"]["page"] == page_num:
                page_stamps.append((qdata["stamp"], qdata))
            # Primary feedback
            if qdata.get("feedback") and qdata["feedback"]["page"] == page_num:
                page_fbs.append((qdata["feedback"], qdata["feedback"]))
            # Deferred feedback (placed on a continuation page)
            if qdata.get("deferred_feedback") and qdata["deferred_feedback"]["page"] == page_num:
                page_fbs.append((qdata["deferred_feedback"], qdata["deferred_feedback"]))
                
        for t in _manifest.get("phase3_crosses", []):
            if t["page"] == page_num:
                page_p3.append((t, "cross"))

        def get_rect(obj, otype):
            if otype in ("tick", "cross"):
                sz = obj["size"]
                return (obj["x"] - sz/2, obj["y"] - sz/2, obj["x"] + sz/2, obj["y"] + sz/2)
            elif otype == "stamp":
                _f = int(28 * obj["scale"])
                _half_h = _f * 2 + int(4 * obj["scale"]) * 2 + _f * 0.20 + 10
                _half_w = _f * 3
                return (obj["x"] - _half_w, obj["y"] - _half_h, obj["x"] + _half_w, obj["y"] + _half_h)
            elif otype == "feedback":
                import textwrap
                wrapped = []
                for ln in obj["text"].split('\n'):
                    wrapped.extend(textwrap.wrap(ln, width=50))
                num_lines = len(wrapped)
                bg_w = int(max(len(ln) for ln in wrapped + [""]) * (obj["font_size"] * 0.60) + 20)
                bg_h = int(obj["font_size"] * 1.5 * num_lines + obj["font_size"] * 0.6)
                bg_y = obj["y"] - (num_lines - 1) * obj["font_size"] * 1.5 - obj["font_size"] * 0.3 - 8
                return (obj["x"] - 10, bg_y, obj["x"] - 10 + bg_w, bg_y + bg_h)

        def _rects_overlap(r1, r2):
            return not (r1[2] < r2[0] or r1[0] > r2[2] or r1[3] < r2[1] or r1[1] > r2[3])

        # Adjust ticks/crosses if they overlap with stamp or feedback boxes
        fixed_obstacles = [("stamp", s[0]) for s in page_stamps] + [("feedback", f[0]) for f in page_fbs]
        for t, act in page_ticks + page_p3:
            t_rect = get_rect(t, act)
            for obs_type, obs_obj in fixed_obstacles:
                obs_rect = get_rect(obs_obj, obs_type)
                if _rects_overlap(t_rect, obs_rect):
                    t["x"] = max(t["x"], obs_rect[2] + t["size"] / 2 + 15)
                    t["x"] = min(pdf_w - 40, t["x"])
                    t_rect = get_rect(t, act)
                
        # === DRAW PHASE ===
        for t, act in page_ticks:
            if act == "tick":
                _draw_tick(c, t["x"], t["y"], size=t["size"])
            else:
                _draw_cross(c, t["x"], t["y"], size=t["size"])
                
        for t, act in page_p3:
            _draw_cross(c, t["x"], t["y"], size=t["size"])
            
        for s, qdata in page_stamps:
            _draw_marks_stamp(
                c, 
                cx=s["x"], 
                cy=s["y"], 
                marks_obtained=s.get("marks_obtained", qdata.get("marks_obtained", 0)),
                marks_total=s.get("marks_total", qdata.get("marks_total", 1)),
                font_name=font_name,
                scale=s["scale"]
            )
            
        for f, _ in page_fbs:
            fb_text = f["text"]
            fb_x_final = f["x"]
            fb_y_final = f["y"]
            FB_FONT_SIZE = f["font_size"]
            
            import textwrap
            wrapped_lines = []
            for line in fb_text.split('\n'):
                wrapped_lines.extend(textwrap.wrap(line, width=50))
            fb_num_lines = len(wrapped_lines)
            
            c.saveState()
            bg_w = int(max(len(ln) for ln in wrapped_lines + [""]) * (FB_FONT_SIZE * 0.60) + 20)
            bg_h = int(FB_FONT_SIZE * 1.5 * fb_num_lines + FB_FONT_SIZE * 0.6)
            bg_y = fb_y_final - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - 8
            
            c.setFillColorRGB(1, 1, 1)
            c.setStrokeColorRGB(1, 1, 1, 0)
            c.rect(fb_x_final - 10, bg_y, bg_w, bg_h, fill=1, stroke=0)
            
            c.setFont(font_name, FB_FONT_SIZE)
            c.setFillColorRGB(1, 0, 0)
            c.setStrokeColorRGB(1, 0, 0)
            c.setFillAlpha(1.0)
            c.setStrokeAlpha(1.0)
            
            _draw_y = fb_y_final
            for line in wrapped_lines:
                c.drawString(fb_x_final, _draw_y, line)
                _draw_y -= FB_FONT_SIZE * 1.5
            c.restoreState()

        c.showPage()

    c.save()
    doc.close()

    # ── Merge overlay with original PDF (3-tier: PyMuPDF → pypdf → raw copy) ──
    print("  Merging annotations…", flush=True)
    packet.seek(0)
    # Snapshot bytes so every fallback tier can access the overlay independently
    # (each reader/library may consume the stream position differently)
    _overlay_bytes = packet.read()

    _merge_ok = False

    # ── Tier 1: PyMuPDF ────────────────────────────────────────────────────────
    _orig_doc    = None
    _overlay_doc = None
    try:
        _orig_doc    = fitz.open(pdf_path)
        _overlay_doc = fitz.open("pdf", _overlay_bytes)
        for i in range(len(_orig_doc)):
            if i < len(_overlay_doc):
                _orig_doc[i].show_pdf_page(
                    _orig_doc[i].rect, _overlay_doc, i, keep_proportion=True
                )
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        _orig_doc.save(output_path)
        _merge_ok = True
        print("  ✓ Merged via PyMuPDF", flush=True)
    except Exception as _e1:
        print(f"  ⚠ PyMuPDF merge failed ({_e1}), trying pypdf fallback…", flush=True)
    finally:
        # Always close handles — critical on Windows/Docker to release file locks
        try:
            if _orig_doc is not None:
                _orig_doc.close()
        except Exception:
            pass
        try:
            if _overlay_doc is not None:
                _overlay_doc.close()
        except Exception:
            pass

    # ── Tier 2: pypdf ──────────────────────────────────────────────────────────
    if not _merge_ok:
        try:
            _reader  = PdfReader(pdf_path)
            _overlay = PdfReader(io.BytesIO(_overlay_bytes))
            _writer  = PdfWriter()
            for i in range(len(_reader.pages)):
                pg = _reader.pages[i]
                if i < len(_overlay.pages):
                    pg.merge_page(_overlay.pages[i])
                _writer.add_page(pg)
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                _writer.write(f)
            _merge_ok = True
            print("  ✓ Merged via pypdf fallback", flush=True)
        except Exception as _e2:
            print(f"  ⚠ pypdf merge also failed ({_e2}), copying original PDF without annotations…", flush=True)

    # ── Tier 3: raw copy (last resort — output is unannotated but not missing) ─
    if not _merge_ok:
        try:
            import shutil
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            shutil.copy2(pdf_path, output_path)
            print(f"  ⚠ Saved unannotated copy to {output_path} (merge failed)", flush=True)
        except Exception as _e3:
            print(f"  ✗ All merge strategies failed. Last error: {_e3}", flush=True)
            raise RuntimeError(f"Stage 7 merge completely failed: {_e3}") from _e3

    # ── v2: Save annotation manifest ──────────────────────────────────────────
    _manifest["generated_at"] = datetime.now().isoformat()
    if manifest_path is None:
        stem = os.path.splitext(os.path.abspath(output_path))[0]
        manifest_path = stem + "_manifest.json"
    os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as _mf:
        json.dump(_manifest, _mf, indent=2, ensure_ascii=False)
    print(f"  ✓ Manifest saved  → {manifest_path}")

    print(f"\n  ✓ Checked copy    → {output_path}")
    print(f"{'='*62}\n")
    return _manifest


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 7 v2 — Checked copy generator with manifest")
    parser.add_argument("--pdf",      required=True,  help="Path to student answer-sheet PDF")
    parser.add_argument("--grading",  required=True,  help="Path to grading_final.json")
    parser.add_argument("--aligned",  required=True,  help="Path to aligned_answers.json")
    parser.add_argument("--output",   required=True,  help="Output PDF path")
    parser.add_argument("--ocr",      default=None,   help="Path to ocr_output.txt (optional)")
    parser.add_argument("--manifest", default=None,   help="Manifest JSON output path (default: <output>_manifest.json)")
    parser.add_argument("--bounds",   default=None,   help="Path to page_bounds.json (from detect_page_bounds.py)")
    args = parser.parse_args()

    generate_checked_copy(
        pdf_path         = args.pdf,
        grading_json     = args.grading,
        aligned_json     = args.aligned,
        output_path      = args.output,
        ocr_text_path    = args.ocr,
        manifest_path    = args.manifest,
        page_bounds_path = args.bounds,
    )
