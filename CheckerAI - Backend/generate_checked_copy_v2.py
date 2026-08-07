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

Annotation logic:
  - 1-2 organic ticks/crosses per page, at real ink regions, variable X position
  - Marks stamp (18pt) on first page of each answer only
  - Single-line horizontal feedback (9pt red) ONLY for "poor" tier answers
      * Text is LLM-generated — one proper sentence, ≤12 words
      * Placed in the CENTRAL zone (20-80% page width) in a blank horizontal
        band of ≥260pt, at least 50pt away from every tick/cross

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

MAX_ANN_FIRST    = 2    # max ticks/crosses on first page of an answer
MAX_ANN_CONTINUE = 1    # max ticks/crosses on continuation pages

TIER_ACTION = {
    "excellent": "tick",
    "very_good": "tick",
    "good":      "tick",
    "okay":      "tick",
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
      - marks_ratio < 0.25 (< 25%)   → 2–3 concise bullet points listing main errors
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
            "No quotation marks, no full stop."
        )
        max_tok = 30

    # ── Case 2: Low score (< 50% or 0 marks) → 2–3 bullet points ───────────────
    elif marks_ratio < 0.50 or marks_obtained == 0:
        context      = f"Grader feedback: {feedback_raw}\n" if feedback_raw else ""
        errors_block = f"Key errors: {errors_str}\n" if errors_str else ""
        prompt = (
            f"A student scored {marks_obtained}/{marks_total} on an exam question.\n"
            f"{context}{errors_block}"
            f"{avoid_block}\n"
            "Write 2 to 3 concise bullet points (start each with '•') listing the specific "
            "reasons, missed concepts, or calculation errors for the lost/zero marks. Each bullet must be ≤12 words. "
            "DO NOT use terms like 'model', 'model answer', or 'marking scheme'. Address the student directly as a teacher. "
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


def _find_heading_y(
    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_path
) -> float | None:
    """Two-strategy heading Y (PDF bottom-origin)."""
    y = _heading_fitz(fitz_page, pdf_h, q_num)
    if y: return y

    y = _heading_ocr(ocr_path, fitz_page.number + 1, pdf_h, q_num)
    if y: return y

    return None


def _choose_action(
    page_idx_in_q: int, 
    total_pages: int, 
    ann_idx_on_page: int, 
    anns_on_page: int, 
    tier: str, 
    marks_obtained: float, 
    marks_total: float
) -> str:
    """
    Decide whether to place a tick or a cross.

    Guaranteed rules (override everything):
      - FIRST annotation of the whole answer:
          → tick  if marks_obtained > 0  (student got something right)
          → cross if marks_obtained == 0
      - LAST annotation of the whole answer:
          → cross if marks_obtained < marks_total  (student lost marks somewhere)
          → tick  if marks_obtained == marks_total (perfect)
      - All middle annotations:
          → tick  with probability = marks_ratio
          → cross with probability = 1 - marks_ratio

    This guarantees every imperfect answer has ≥1 cross, and every partially
    correct answer has ≥1 tick, regardless of page count.
    """
    if marks_total <= 0:
        return "cross"

    marks_ratio = min(1.0, max(0.0, marks_obtained / marks_total))

    is_first = (page_idx_in_q == 0 and ann_idx_on_page == 0)
    is_last  = (page_idx_in_q == total_pages - 1 and ann_idx_on_page == anns_on_page - 1)

    # Treat < 20% as effectively 'no answer': always cross on first annotation
    # so near-zero stubs (e.g. 0.5/6 'question is incomplete') don't get a tick.
    meaningful_marks = marks_total > 0 and (marks_obtained / marks_total) >= 0.20

    if is_first:
        return "tick" if meaningful_marks else "cross"

    if is_last:
        return "cross" if marks_obtained < marks_total else "tick"

    # Middle slots: probabilistic, weighted by marks ratio
    return "tick" if random.random() < marks_ratio else "cross"




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


def _plan_annotations_from_ocr(
    ocr_page_text: str,
    q_num: str,
    pdf_w: float, pdf_h: float,
    marks_obtained: float, marks_total: float,
    page_idx_in_q: int, total_pages: int,
    page_used_y_fracs: list,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
    slice_top: float = 0.05,
    slice_bot: float = 0.95,
    is_practical: bool = False,
    is_first: bool = False,
    heading_y_frac: float = None,
    gray: Image.Image = None,
    img_w: int = 1000,
    img_h: int = 1000,
    page_excluded_px_rows: set = None,
    text_blocks: list = None,
    current_page_ann_count: int = 0,
    wrong_lines: list = None,
    correct_lines: list = None,
) -> list:
    """
    Plan tick/cross annotations for one question on one page.

    Y positions are computed by linearly interpolating the OCR line fraction
    within [ink_top, ink_bot] — the pixel-detected written region.  This
    guarantees annotations stay inside the written area regardless of how
    text_blocks happen to be distributed.

    If OCR yields no content lines (empty page, or the page has heavy ink
    but no OCR coverage), we fall back to evenly spaced positions derived
    directly from text_blocks so the page never ends up annotation-free.
    """
    marks_ratio = min(1.0, max(0.0, marks_obtained / marks_total)) if marks_total > 0 else 0
    MAX_ANN_PER_PAGE = 3

    # Dynamic vertical separation: scale with slice height so short answers fit marks comfortably
    slice_h = max(0.05, slice_bot - slice_top)
    if slice_h >= 0.55:
        MIN_SEP = 0.16
    elif slice_h >= 0.30:
        MIN_SEP = 0.11
    else:
        MIN_SEP = 0.07

    if current_page_ann_count >= MAX_ANN_PER_PAGE:
        return []

    # ── Step 1: Build OCR line list and estimate text region ────────────────
    all_raw_lines = ocr_page_text.split('\n')
    written_lines = [l for l in all_raw_lines if l.strip()]
    n_written     = len(written_lines)

    if n_written <= 8 or (ink_bot - ink_top) <= 0.45:
        max_ann = 1
    else:
        max_ann = random.randint(2, MAX_ANN_PER_PAGE)

    max_ann = min(max_ann, MAX_ANN_PER_PAGE - current_page_ann_count)

    # Calculate actual text end from written line count so annotations
    # stop where the student's written text actually ends on this page.
    if n_written > 0:
        line_based_bot = ink_top + (n_written / 22.0) * (0.85 - ink_top) + 0.02
        estimated_ink_bot = min(ink_bot, slice_bot, max(ink_top + 0.10, line_based_bot))
    else:
        estimated_ink_bot = min(ink_bot, slice_bot)

    # ── Step 2: Fragment-first y-placement ────────────────────────────
    # Build the target annotation list: each entry is (action, fragment_text)
    # Priority: wrong_lines (crosses) first since they're harder to miss, then correct_lines (ticks)
    target_annotations: list[tuple[str, str]] = []

    # Interleave ticks and crosses for a more natural look
    wl = list(wrong_lines   or [])
    cl = list(correct_lines or [])
    # Alternate cross/tick up to max_ann total
    while (wl or cl) and len(target_annotations) < max_ann:
        if wl:
            target_annotations.append(("cross", wl.pop(0)))
        if cl and len(target_annotations) < max_ann:
            target_annotations.append(("tick", cl.pop(0)))

    # Resolve exact y-fracs from OCR for each fragment
    y_candidates:   list[float] = []
    ann_ocr_lines:  list[str]   = []
    ann_actions:    list[str]   = []

    for action, frag in target_annotations:
        y_frac = _find_fragment_y(frag, written_lines, ink_top, estimated_ink_bot, slice_top, slice_bot)
        if y_frac is not None:
            y_candidates.append(y_frac)
            ann_ocr_lines.append(frag)
            ann_actions.append(action)

    # ── Step 3: Fill remaining slots with evenly-spaced OCR lines ──────────
    remaining   = max_ann - len(y_candidates)
    total_lines = len(all_raw_lines)
    if remaining > 0 and total_lines > 0:
        content_idxs = []
        for line_idx in range(total_lines):
            if all_raw_lines[line_idx].strip():
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac   = ink_top + raw_frac * (estimated_ink_bot - ink_top)
                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)

        if content_idxs:
            if len(content_idxs) <= remaining:
                fill_idxs = content_idxs
            elif remaining == 1:
                fill_idxs = [content_idxs[len(content_idxs) // 2]]
            else:
                step = len(content_idxs) / remaining
                fill_idxs = [content_idxs[int(i * step)] for i in range(remaining)]

            for line_idx in fill_idxs:
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac   = ink_top + raw_frac * (estimated_ink_bot - ink_top)
                y_candidates.append(y_frac)
                ann_ocr_lines.append(all_raw_lines[line_idx].strip())
                ann_actions.append(None)   # action determined later by score ratio

    # ── Step 4: Fallback if nothing resolved ──────────────────────────
    if not y_candidates and (text_blocks or total_lines > 0):
        if max_ann > 0:
            if ink_top == ink_bot:
                y_centers = [ink_top] * max_ann
            else:
                y_centers = [
                    ink_top + (i + 0.5) * (ink_bot - ink_top) / max_ann
                    for i in range(max_ann)
                ]
            y_candidates = y_centers
        ann_ocr_lines = [""] * len(y_candidates)
        ann_actions   = [None] * len(y_candidates)

    # Pad lists to equal length
    while len(ann_ocr_lines) < len(y_candidates):
        ann_ocr_lines.append("")
    while len(ann_actions) < len(y_candidates):
        ann_actions.append(None)

    # ── Step 5: Emit annotations ────────────────────────────────────────
    n_sel  = len(y_candidates)
    result = []

    for ann_idx, y_frac in enumerate(y_candidates):
        # Skip if too close to heading stamp
        if heading_y_frac is not None and abs(y_frac - heading_y_frac) < 0.06:
            y_frac = heading_y_frac + 0.07

        # Determine the lowest allowed point for this annotation.
        # Constrain by slice_bot so collision avoidance doesn't push into the next Q's zone.
        _ann_ink_bot = min(estimated_ink_bot, slice_bot)

        # Hard top margin floor:
        # ALWAYS enforce an absolute floor of 0.12 (12% down from top of page)
        # so annotations NEVER land in the top 10% margin regardless of slice height.
        lower_bound = max(slice_top, ink_top, 0.12)
        upper_bound = min(_ann_ink_bot - 0.02, 0.88)
        if upper_bound < lower_bound:
            lower_bound = 0.12
            upper_bound = max(0.13, _ann_ink_bot - 0.02)
        y_frac = min(max(y_frac, lower_bound), upper_bound)

        # Collision avoidance — always DROP if no valid non-colliding spot found
        new_y_frac = _get_non_colliding_y(y_frac, page_used_y_fracs, lower_bound, upper_bound, MIN_SEP)

        is_first_ann = (page_idx_in_q == 0 and ann_idx == 0)
        is_last_ann  = (page_idx_in_q == total_pages - 1 and ann_idx == n_sel - 1)

        if new_y_frac is None:
            if is_first_ann:
                # Must place at least one mark, relax separation requirement slightly
                new_y_frac = _get_non_colliding_y(y_frac, page_used_y_fracs, lower_bound, upper_bound, MIN_SEP * 0.5)
                if new_y_frac is None:
                    # To strictly prevent multiple marks on the same horizontal line, skip if no space
                    continue
            else:
                # Strictly enforce distance: skip this annotation to prevent overcrowding
                continue
            
        y_frac = new_y_frac

        # Tick or cross decision
        is_first_ann = (page_idx_in_q == 0 and ann_idx == 0)
        is_last_ann  = (page_idx_in_q == total_pages - 1 and ann_idx == n_sel - 1)

        # ── Tick or cross decision ───────────────────────────────────────────
        # Priority 1: Semantic match against grader-flagged wrong/correct lines
        ocr_line = ann_ocr_lines[ann_idx] if ann_idx < len(ann_ocr_lines) else ""
        if wrong_lines and _line_matches_fragment(ocr_line, wrong_lines):
            action = "cross"
        elif correct_lines and _line_matches_fragment(ocr_line, correct_lines):
            action = "tick"
        else:
            # Priority 2: Score-ratio fallback (original behaviour)
            meaningful_marks_inline = marks_total > 0 and (marks_obtained / marks_total) >= 0.20
            if is_first_ann:
                action = "tick" if meaningful_marks_inline else "cross"
            elif is_last_ann:
                action = "cross" if marks_ratio < 0.50 else "tick"
            else:
                action = "tick" if random.random() < marks_ratio else "cross"

        y_frac = max(0.12, min(y_frac, 0.88))
        y_pdf = pdf_h * (1.0 - y_frac) + random.uniform(-4, 4)
        page_used_y_fracs.append(y_frac)
        if page_excluded_px_rows is not None:
            ann_y_px = int(y_frac * img_h)
            for pr in range(ann_y_px - 40, ann_y_px + 41):
                page_excluded_px_rows.add(pr)

        if gray is not None:
            if action == "cross":
                ann_x = _find_ink_x(
                    gray, img_w, img_h, pdf_w, y_frac, is_practical,
                )
            else:
                ann_x = _find_clear_x(
                    gray, img_w, img_h, pdf_w, y_frac, is_practical,
                    excluded_px_rows=page_excluded_px_rows,
                )
        else:
            ann_x = _random_ann_x(pdf_w, is_practical=is_practical)

        result.append({"y_pdf": y_pdf, "ann_x": ann_x, "action": action})

    return result



def _find_feedback_spot_in_q_bounds(
    ocr_page_text: str,
    q_num: str,
    pdf_h: float,
    pdf_w: float,
    page_used_y_fracs: list,
    text_blocks: list,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
    slice_top: float = 0.05,
    slice_bot: float = 0.95,
) -> tuple[float, float] | None:
    """
    Find a blank spot within the question's own vertical bounds to place
    the feedback comment, avoiding text blocks. If the page is very crowded,
    forces placement in a non-colliding spot as a fallback.
    """
    lines = ocr_page_text.split("\n")
    total_lines = len(lines)
    if total_lines == 0:
        return None

    MIN_SEP   = 0.09
    BLOCK_CLR = 0.035

    def _is_clear_of_blocks(y_frac):
        if not text_blocks:
            return True
        return all(abs(b[0] - y_frac) > BLOCK_CLR for b in text_blocks)

    def _is_clear_of_used(y_frac):
        return all(abs(y_frac - u) >= MIN_SEP for u in page_used_y_fracs)

    def _scale(raw_frac):
        return ink_top + raw_frac * (ink_bot - ink_top)

    def _try_candidate(raw_frac) -> float | None:
        base = _scale(raw_frac)
        for delta in [0.0, -0.04, 0.04, -0.08, 0.08, -0.12, 0.12, -0.16, 0.16]:
            candidate = base + delta
            if candidate < ink_top or candidate > ink_bot:
                continue
            if _is_clear_of_used(candidate) and _is_clear_of_blocks(candidate):
                return candidate
        return None

    # Prefer near the bottom of the slice
    y_frac = _try_candidate((slice_bot - ink_top) / max(0.01, ink_bot - ink_top))
    if y_frac is not None:
        return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Prefer blank lines within this question's physical slice bounds, starting from the BOTTOM
    blank_lines = []
    for i in range(total_lines):
        if not lines[i].strip():
            y_curr = ink_top + ((i + 0.5) / total_lines) * (ink_bot - ink_top)
            if slice_top <= y_curr <= slice_bot:
                blank_lines.append(i)
                
    for b in reversed(blank_lines):
        y_frac = _try_candidate((b + 0.5) / total_lines)
        if y_frac is not None:
            return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Fallback: scan starting from 90% down the slice, moving upwards
    for offset in range(0, 90, 5):
        frac_in_slice = 0.9 - offset / 100.0
        target_y = slice_top + frac_in_slice * (slice_bot - slice_top)
        raw_frac = (target_y - ink_top) / max(0.01, ink_bot - ink_top)
        y_frac = _try_candidate(raw_frac)
        if y_frac is not None:
            return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    return None   # give up — completely packed page


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

    for section, sec_data in aligned_data.items():
        for q_id, aligned_q, grade_entry in _iter_leaf_questions(section, sec_data):
            # ── Skip MCQs entirely — no annotations or marks stamps for MCQs ──
            if "MCQ" in section or "MCQ" in q_id or q_id.isdigit():
                continue

            answer_pages = aligned_q.get("answer_pages", [])
            if not answer_pages:
                continue

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

            # Check if student answer is minimal attempt (<=1 short line / prompt title only)
            student_ans_text = str(aligned_q.get("student_answer", "") or grade_entry.get("student_answer", "") or "").strip()
            cleaned_ans = re.sub(r'^(?:Question|Q|Ans\.?|Answer|Soln\.?|Solution)\s*#?\s*\d+[a-z]?[\s\.\:]*', '', student_ans_text, flags=re.IGNORECASE).strip()
            num_words = len(cleaned_ans.split())
            num_lines = len([l for l in student_ans_text.split('\n') if l.strip()])
            is_minimal_attempt = (num_lines <= 1 or num_words < 15 or not cleaned_ans)

            # Generate feedback if not MCQ, not no_answer, and either >0 marks OR 0 marks with substantial attempt
            if not is_mcq and not is_no_answer:
                if not (is_zero_marks and is_minimal_attempt):
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
                    "is_first":      idx_in_q == 0,
                    "page_idx_in_q": idx_in_q,
                    "total_pages":   len(answer_pages),
                    "marks_obtained": marks_obtained,
                    "marks_total":   marks_total,
                    "tier":          tier,
                    # Feedback only on first page of a poor answer
                    "fb_text":       fb_text if idx_in_q == 0 else None,
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
            # Check if this page has MCQs (if there's MCQ text in the OCR, don't draw the cross)
            ocr_page_text = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""
            has_mcqs = False
            if ocr_page_text:
                for mcq_key in ["MCQ", "mcq", "Multiple Choice", "(a)", "(b)", "(c)", "(d)"]:
                    if mcq_key in ocr_page_text:
                        has_mcqs = True
                        break
            if not has_mcqs and page_num != 1:
                # Page has no mapped questions and no obvious MCQs. Draw a single cross in the center.
                c.saveState()
                c.setStrokeColor(red)
                c.setLineWidth(max(2.0, 3.0 * page_scale))
                # Very large cross to indicate blank / unused / unmapped page
                _draw_cross(c, pdf_w / 2, pdf_h / 2, size=int(60 * page_scale))
                c.restoreState()
            
            c.showPage()
            continue


        # Compute ink bounds from image analysis
        if text_blocks:
            ink_top = max(0.04, min(b[0] - b[1]/2 for b in text_blocks))
            ink_bot = min(0.96, max(b[0] + b[1]/2 for b in text_blocks))
            print(f"    [DEBUG] PyMuPDF raw bounds: ink_top={ink_top:.3f}, ink_bot={ink_bot:.3f}")
        else:
            ink_top, ink_bot = 0.04, 0.96

        # ── Authoritative ink_bot: scan the CENTRAL strip from bottom upward ──────
        # _compute_ink_bot_strict() only looks at the central 80 % of page width,
        # so scanner borders, spine shadows, and corner artifacts are completely
        # ignored. It finds the true last handwritten row on the page.
        strict_ink_bot = _compute_ink_bot_strict(gray, img_w, img_h)
        # Use the tighter of image-block analysis and the central-strip scan,
        # but only if strict_ink_bot didn't catastrophically fail (e.g., due to faint ink)
        if strict_ink_bot > 0.40 or strict_ink_bot > ink_bot - 0.20:
            ink_bot = min(ink_bot, strict_ink_bot)
        print(f"    [DEBUG] Final ink_bot (after strict): ink_top={ink_top:.3f}, ink_bot={ink_bot:.3f}, strict={strict_ink_bot:.3f}")

        # ── Extra guard for continuation pages with small content ───────────────
        # If this page only has continuation items (no is_first) AND the content
        # is short (few OCR lines), printed page numbers at the bottom of the
        # scan sheet mislead _compute_ink_bot_strict into returning ~0.90+.
        # Re-scan the UPPER HALF of the page only so page numbers are excluded.
        page_is_continuation = items and not any(it["is_first"] for it in items)
        if page_is_continuation and gray:
            _upper_bot_px = int(img_h * 0.55)   # only look at top 55 %
            _pixel_ink_bot_row = _find_ink_bottom_in_zone(
                gray, img_h, int(img_h * 0.04), _upper_bot_px
            )
            _pixel_ink_bot_frac = _pixel_ink_bot_row / img_h - 0.02  # negative: strictly inside
            if _pixel_ink_bot_frac < ink_bot:   # only tighten, never widen
                print(
                    f"    [ink-cap] continuation page {page_num}: "
                    f"ink_bot {ink_bot:.2f} → {_pixel_ink_bot_frac:.2f} "
                    f"(upper-half pixel scan)",
                    flush=True,
                )
                ink_bot = _pixel_ink_bot_frac

        # Ensure ink_bot is always at least 0.10 below ink_top
        ink_bot = max(ink_bot, ink_top + 0.10)

        # ── Page-scale factor was moved above grand-total stamp ────────────────
        # (REF_H and page_scale are already defined above)

        # ── Pre-compute headings for all is_first items on this page ────────────────
        # Used by the multi-question stamp slicer below to find each question's
        # ACTUAL vertical position rather than splitting the page equally.
        pre_heading_fracs: dict = {}   # q_num → image-space fraction (0=top, 1=bottom)
        _page_ocr_for_headings = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""
        for _it in items:
            if _it["is_first"]:
                _hy = _find_heading_y(
                    fitz_page, gray, img_w, img_h, pdf_h,
                    _it["q_num"], ocr_text_path
                )
                if _hy is not None:
                    pre_heading_fracs[_it["q_num"]] = 1.0 - _hy / pdf_h  # → image frac

        # ── Populate missing heading fracs from OCR line position ──────────────
        # PyMuPDF can't search handwritten text, so pre_heading_fracs is often
        # empty for hand-written sub-part questions. Use the OCR-derived line
        # position as the primary fallback.
        if _page_ocr_for_headings:
            _total_ocr_ln = max(1, len(_page_ocr_for_headings.split('\n')))
            # Also build a schema-order index so un-found questions get a
            # predictable relative order (avoids arbitrary 0.5 default ties).
            _first_items = [it for it in items if it["is_first"]]
            for _schema_idx, _it in enumerate(_first_items):
                _qn = _it["q_num"]
                if _it["is_first"] and _qn not in pre_heading_fracs:
                    _qs, _ = _find_question_line_bounds(_page_ocr_for_headings, _qn)
                    if _qs >= 0:   # -1 means fallback / not found
                        pre_heading_fracs[_qn] = (
                            ink_top + (_qs / _total_ocr_ln) * (ink_bot - ink_top)
                        )
                    else:
                        # Un-found via OCR: we must assign a fallback so they don't all pile up at 0.0
                        if len(_first_items) == 1:
                            pre_heading_fracs[_qn] = ink_top + 0.1
                        else:
                            # Evenly distribute based on their relative index in the first items list
                            spacing = (ink_bot - ink_top) / (len(_first_items) + 1)
                            pre_heading_fracs[_qn] = ink_top + spacing * (_schema_idx + 1)

        # Track chosen Y coordinates (as fractions) globally per page
        # so if P14 has BOTH Q7 and Q8, their marks don't overlap side-by-side!
        # Tracks pixel rows (image space) already claimed by stamps on this page
        # Tracks pixel rows (image space) already claimed by stamps on this page
        # ── Annotations Phase ──
        page_used_y_fracs = []
        page_drawn_rects_y = []  # List of (y_bottom, y_top) in PDF coords
        _page_mcq_top = False   # True when page 1 has MCQ answers in upper half
        page_annotations_count = 0

        # ── Pre-reserve the grand-total stamp zone on page 1 ──────────────
        # The grand total stamp is drawn at the top-right of page 1 before
        # the per-question loop runs. Pre-populate page_used_y_fracs with its
        # Y so that Q1a's feedback search skips that vertical band.
        if page_num == 1 and grand_total > 0 and _gt_y_frac_page1 is not None:
            # Create a solid wall of exclusion points to prevent any ticks
            # from slipping through the min_sep collision check.
            for i in range(-12, 13):
                page_used_y_fracs.append(max(0.0, min(1.0, _gt_y_frac_page1 + i * 0.01)))
            if _gt_bounds_page1:
                page_drawn_rects_y.append(_gt_bounds_page1)
            # Also block pixel rows so the stamp/feedback scanner avoids this zone
            _gt_px = int(_gt_y_frac_page1 * img_h)
            for _pr in range(max(0, _gt_px - 60), min(img_h, _gt_px + 61)):
                page_excluded_px_rows.add(_pr)

        # ── Filter out ghost items from `items` ────────────────────────────────
        # If there are multiple `is_first` items assigned to this page, but some
        # were not found by OCR/PyMuPDF (and thus not in pre_heading_fracs),
        # they are likely ghosts (mis-assigned by the alignment model).
        # We must drop them so we don't stamp them on this page, AND we must
        # pass their `is_first` and `fb_text` baton to the NEXT page they appear on.
        _firsts_in_items = [it for it in items if it["is_first"]]
        if len(_firsts_in_items) > 1:
            _actual_firsts_qnums = {it["q_num"] for it in _firsts_in_items if it["q_num"] in pre_heading_fracs}
            if _actual_firsts_qnums:
                ghost_items = [it for it in _firsts_in_items if it["q_num"] not in _actual_firsts_qnums]
                if ghost_items:
                    items = [it for it in items if it not in ghost_items]
                    for ghost in ghost_items:
                        next_idx = ghost["page_idx_in_q"] + 1
                        _q = ghost["q_num"]
                        for _p_num, _p_items in drawing_plan.items():
                            if _p_num > page_num:
                                for _p_it in _p_items:
                                    if _p_it["q_num"] == _q and _p_it["page_idx_in_q"] == next_idx:
                                        _p_it["is_first"] = True
                                        _p_it["fb_text"] = ghost["fb_text"]

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

            # Phantom items (unanswered questions) still participate in slice
            # layout (so their heading reserves vertical space on shared pages)
            # but no stamp, ticks, or feedback is drawn for them.
            _is_phantom = item.get("_phantom", False)

            # Slice boundaries for this question's stamp/feedback zone.
            # Defaults to the full page ink range; overridden in the is_first block.
            _item_slice_top = ink_top
            _item_slice_bot = ink_bot

            # ── Marks stamp on first page of each answer ───────────────────────
            heading_y = None
            heading_y_frac = None
            if is_first:
                heading_y = _find_heading_y(
                    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_text_path
                )
                if heading_y:
                    heading_y_frac = 1.0 - heading_y / pdf_h

            # ── Pre-compute per-question vertical slices when page is shared ─
            # Count how many 'is_first' questions are on this page and what
            # their order is, so each gets a distinct, non-overlapping slice.
            # CRITICAL: sort by physical Y position (heading fraction, top→bottom)
            # not by JSON schema order — questions can appear on a page in any
            # physical order (e.g. Q3b printed below Q4b on the same page).
            #
            # ALSO CRITICAL: include ALL questions that have a physical heading
            # on this page, even if they have no student answer (e.g. Q3a with
            # just "Ans. 3(a)" written). Excluding them shrinks the slice count
            # and makes the remaining questions' slices start too high, causing
            # stamps to land in the blank question's visual area.
            # CRITICAL FIX: Include ALL items on this page (even continuations).
            # Continuations won't have a heading in pre_heading_fracs, so they default to 0.0 (top).
            print(f'\n[DEBUG] pre_heading_fracs: {pre_heading_fracs}')
            print(f"\\n[DEBUG] pre_heading_fracs: {pre_heading_fracs}", flush=True)
            page_q_items = list(items)
            _items_qnums = {it["q_num"] for it in page_q_items}
            _phantom_slots = [
                {"q_num": qn, "is_first": True, "_phantom": True}
                for qn in pre_heading_fracs
                if qn not in _items_qnums
            ]
            page_q_items = page_q_items + _phantom_slots
            if len(page_q_items) > 1:
                actual_items = [it for it in page_q_items if it["q_num"] in pre_heading_fracs or not it.get("_phantom")]
                if actual_items:
                    page_q_items = actual_items
                    
            if len(page_q_items) > 1:
                page_q_items = sorted(
                    page_q_items,
                    key=lambda it: pre_heading_fracs.get(it["q_num"], 0.0 if not it.get("is_first") else 0.5)
                )
                _sorted_q_names = [it['q_num'] for it in page_q_items]
                print(f"    [multi-Q] Sorted page order: {_sorted_q_names} (by heading Y)", flush=True)

                # ── Heading-proximity conflict guard ──────────────────────────────
                # If any two is_first questions have detected headings within 8%
                # of each other, the heading detection is unreliable (e.g., the
                # student reused the same physical page for two questions).
                # In this case, discard all heading fracs and fall back to equal-spacing.
                _first_items_sorted = [it for it in page_q_items if it.get("is_first") and it["q_num"] in pre_heading_fracs]
                _has_heading_conflict = False
                for _ci in range(len(_first_items_sorted)):
                    for _cj in range(_ci + 1, len(_first_items_sorted)):
                        _fy_i = pre_heading_fracs.get(_first_items_sorted[_ci]["q_num"], None)
                        _fy_j = pre_heading_fracs.get(_first_items_sorted[_cj]["q_num"], None)
                        if _fy_i is not None and _fy_j is not None and abs(_fy_i - _fy_j) < 0.08:
                            _has_heading_conflict = True
                            print(
                                f"    [heading-conflict] Q{_first_items_sorted[_ci]['q_num']} and Q{_first_items_sorted[_cj]['q_num']} "
                                f"headings within 8% ({_fy_i:.3f} vs {_fy_j:.3f}). Falling back to equal-spacing.",
                                flush=True
                            )
                if _has_heading_conflict:
                    # Discard conflicting heading fracs — equal spacing will apply below
                    for _it in _first_items_sorted:
                        pre_heading_fracs.pop(_it["q_num"], None)

            n_items = len(page_q_items)
            my_order = next((idx for idx, it in enumerate(page_q_items) if it["q_num"] == q_num), 0)
            multi_q_target_y_frac = None
            if ocr_page_text and n_items == 1:
                # Only one question on this page: use OCR bounds normally
                start_ln, end_ln = _find_question_line_bounds(ocr_page_text, q_num)
                total_ln = max(1, len(ocr_page_text.split('\n')))
                q_top_frac = ink_top + (start_ln / total_ln) * (ink_bot - ink_top)
                q_bot_frac = ink_top + (end_ln   / total_ln) * (ink_bot - ink_top)
                # Clamp to actual ink region — never let stamps/feedback drift
                # below the last handwritten line on this page
                q_top_frac = min(q_top_frac, ink_bot)
                q_bot_frac = min(q_bot_frac, ink_bot)
                # Guarantee a sensible minimum height for the search zone
                if q_bot_frac - q_top_frac < 0.12:
                    q_top_frac = max(ink_top, q_top_frac - 0.06)
                    q_bot_frac = min(ink_bot, q_bot_frac + 0.06)

                # ── Page 1 MCQ guard ──────────────────────────────────────────
                # Page 1 of FT papers has MCQ answers at the top and one
                # descriptive answer beginning partway down.  Clamp the stamp
                # and feedback search zone to the bottom 45 % of the page so
                # neither element overlaps the MCQ section.
                ocr_top_lines = ocr_page_text.split('\n')[:10]
                page_has_mcq_top = any(
                    'mcq' in ln.lower() or
                    ('.' in ln and len(ln.strip()) <= 8 and ln.strip()[-1].isalpha())
                    for ln in ocr_top_lines
                )
                if page_has_mcq_top:
                    _page_mcq_top = True
                    q_top_frac = max(q_top_frac, 0.75)
                    q_bot_frac = max(q_bot_frac, q_top_frac + 0.15)
                    print(f"    [MCQ-guard] Clamped stamp/feedback zone to [{q_top_frac:.2f}, {q_bot_frac:.2f}] (MCQ at top of page)", flush=True)
            elif n_items > 1:
                # ── Multiple questions on same page: slicing by heading position ────────
                q_top_frac = ink_top
                if my_order > 0:
                    q_top_frac = max(ink_top, pre_heading_fracs.get(q_num, ink_top) - 0.05)
                q_bot_frac = ink_bot
                if my_order < n_items - 1:
                    next_q = page_q_items[my_order + 1]["q_num"]
                    q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, ink_bot) + 0.02)
                q_bot_frac = max(q_bot_frac, q_top_frac + 0.1)
                
                # Marks stamp target: prefer placing just below the detected heading.
                # Equal-spacing targets are a fallback when heading is unknown.
                firsts_on_page = [it for it in page_q_items if it.get("is_first") and not it.get("_phantom")]
                n_firsts = len(firsts_on_page)
                if n_firsts >= 2 and is_first:
                    if heading_y_frac is not None:
                        # ── Heading-relative target: place stamp just below where the
                        # student wrote the question label ─────────────────────────────
                        _below_heading = heading_y_frac + 0.07   # 7% below heading in image space
                        # Clamp to slice bounds, but ALWAYS stay at least 2% below
                        # the heading — never let the clamp push the target above it.
                        _min_target = heading_y_frac + 0.02
                        _max_target = max(q_bot_frac - 0.05, _min_target + 0.01)
                        multi_q_target_y_frac = max(_min_target, min(_below_heading, _max_target))
                        print(f"    [heading-offset] Q{q_num}: heading={heading_y_frac:.3f} → stamp target={multi_q_target_y_frac:.3f}", flush=True)
                    else:
                        # ── Fallback: evenly-spaced targets when heading not detected ─
                        if n_firsts == 2:
                            _stamp_targets = [0.16, 0.88]
                        elif n_firsts == 3:
                            _stamp_targets = [0.13, 0.50, 0.87]
                        else:
                            _stamp_targets = [round(0.10 + i * (0.80 / (n_firsts - 1)), 2) for i in range(n_firsts)]
                        try:
                            _my_first_order = next(i for i, it in enumerate(firsts_on_page) if it["q_num"] == q_num)
                            multi_q_target_y_frac = _stamp_targets[_my_first_order]
                            print(f"    [multi-Q stamps] Q{q_num} order {_my_first_order+1}/{n_firsts} → target y_frac={multi_q_target_y_frac}", flush=True)
                        except StopIteration:
                            multi_q_target_y_frac = q_top_frac + 0.05
                else:
                    if is_first and my_order > 0:
                        if heading_y_frac is not None:
                            _min_target = max(0.55, heading_y_frac + 0.05)
                        else:
                            _min_target = max(0.55, q_top_frac + 0.05)
                        multi_q_target_y_frac = min(0.88, _min_target)
                    else:
                        multi_q_target_y_frac = q_top_frac + 0.05

                # Absolute slice safety clamp: multi_q_target_y_frac MUST ALWAYS stay inside this question's slice
                _min_target_clamp = max(q_top_frac + 0.03, (heading_y_frac + 0.03) if heading_y_frac is not None else 0.0)
                _max_target_clamp = max(_min_target_clamp + 0.01, q_bot_frac - 0.05)
                multi_q_target_y_frac = max(_min_target_clamp, min(multi_q_target_y_frac, _max_target_clamp))
            else:
                q_top_frac, q_bot_frac = ink_top, ink_bot

            # Force q_top_frac down if we know the physical heading is lower
            if heading_y_frac and heading_y_frac > q_top_frac:
                q_top_frac = max(q_top_frac, heading_y_frac - 0.05)

            # Save slice boundaries for the feedback search below
            _item_slice_top = q_top_frac
            _item_slice_bot = q_bot_frac
            print(f'[DEBUG SLICE] page={page_num}, q={q_num}, order={my_order}, next={next_q if my_order < n_items - 1 else None}, q_bot={q_bot_frac}', flush=True)

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
                    # ── Marks stamp placement: LEFT MARGIN is the primary target ──
                    # Strategy:
                    #   1. Scan the left margin (2–14% width) for the clearest
                    #      vertical band within the question's vertical extent.
                    #   2. If no left-margin gap, search anywhere on the page for
                    #      the largest white rectangle (avoids student text).
                    #   3. Last resort: _find_clear_xy near the heading.


                    # Convert to pixel rows; search within the question vertical extent.
                    # If the heading was detected, shift the search zone to START just
                    # below it so the stamp always lands under the question label.
                    _HEADING_BELOW_OFFSET = 0.03   # 3% of page height below heading
                    if heading_y_frac is not None:
                        _below_heading_row = int((heading_y_frac + _HEADING_BELOW_OFFSET) * img_h)
                        stamp_row_top = max(0, min(_below_heading_row, int(q_bot_frac * img_h) - 20))
                    else:
                        stamp_row_top = max(0, int(q_top_frac * img_h))
                    stamp_row_bot = min(img_h, int(q_bot_frac * img_h))
                    stamp_row_bot = max(stamp_row_bot, stamp_row_top + 20)


                    if multi_q_target_y_frac is not None:
                        # Multi-question page: force position to top/bottom target
                        marks_x, marks_y_placed = _find_clear_xy(
                            gray, img_w, img_h, pdf_w, pdf_h,
                            multi_q_target_y_frac,
                            is_practical=False, min_clear_cols=30,
                            excluded_px_rows=page_excluded_px_rows,
                            max_search_delta=0.45,
                            min_y_frac=q_top_frac,
                            max_y_frac=q_bot_frac,
                        )
                        rh_st = 60
                        print(f"    [multi-Q] stamp forced at y={marks_y_placed:.0f}", flush=True)
                    else:
                        # ── Step 1: dedicated left-margin scanner ─────────────────────
                        margin_spot = _find_left_margin_stamp_spot(
                            gray, img_w, img_h, pdf_w, pdf_h,
                            stamp_row_top, stamp_row_bot,
                            excluded_px_rows=page_excluded_px_rows,
                        )
        
                        if margin_spot:
                            marks_x, marks_y_placed = margin_spot
                            rh_st = 60   # margin strip height estimate for exclusion zone
                            print(f"    ← left-margin stamp at x={marks_x:.0f}, y={marks_y_placed:.0f}", flush=True)
                        else:
                        # ── Step 2: widest white rect in the question's zone ──────────
                            rect_result = _find_largest_white_rect(
                                gray, img_w, img_h, pdf_w, pdf_h,
                                stamp_row_top, stamp_row_bot,
                                min_w_px=40, min_h_px=8,
                                excluded_px_rows=page_excluded_px_rows,
                            )
                            if rect_result:
                                marks_x, marks_y_placed = rect_result[0], rect_result[1]
                                _, _, rw_st, rh_st = rect_result
                            else:
                                # ── Step 3: clear-xy fallback ──────────────────────────────
                                if heading_y:
                                    fallback_target = 1.0 - heading_y / pdf_h
                                elif 'q_top_frac' in locals():
                                    fallback_target = min(q_top_frac + 0.1, 0.9)
                                else:
                                    fallback_target = 0.1
                                _max_delta = 0.45
                                marks_x, marks_y_placed = _find_clear_xy(
                                    gray, img_w, img_h, pdf_w, pdf_h,
                                    fallback_target,
                                    is_practical=False, min_clear_cols=30,
                                    excluded_px_rows=page_excluded_px_rows,
                                    max_search_delta=_max_delta,
                                    min_y_frac=q_top_frac,
                                    max_y_frac=q_bot_frac,
                                )
                                rh_st = 60


                    _STAMP_FONT   = int(28 * page_scale)
                    _STAMP_HALF_H = _STAMP_FONT * 2 + int(4 * page_scale) * 2 + _STAMP_FONT * 0.20 + 10
                    
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


            # ── Plan tick/cross annotations from OCR line positions ───────────

            # Heading Y as a fraction (so annotations skip over the stamp area)
            heading_y_frac = (1.0 - heading_y / pdf_h) if heading_y else None

            annotations = _plan_annotations_from_ocr(
                ocr_page_text   = ocr_page_text,
                q_num           = q_num,
                pdf_w           = pdf_w,
                pdf_h           = pdf_h,
                marks_obtained  = marks_obtained,
                marks_total     = item["marks_total"],
                page_idx_in_q   = item["page_idx_in_q"],
                total_pages     = item["total_pages"],
                page_used_y_fracs = page_used_y_fracs,
                # Pass global ink bounds so OCR line mapping is accurate
                ink_top         = ink_top,
                ink_bot         = ink_bot,
                # Pass slice bounds to constrain the annotations
                slice_top       = _item_slice_top,
                slice_bot       = _item_slice_bot,
                is_practical    = is_practical,
                is_first        = is_first,
                heading_y_frac  = heading_y_frac,
                gray            = gray,
                img_w           = img_w,
                img_h           = img_h,
                page_excluded_px_rows = page_excluded_px_rows,
                text_blocks     = text_blocks,
                current_page_ann_count = page_annotations_count,
                wrong_lines     = item.get("wrong_lines", []),
                correct_lines   = item.get("correct_lines", []),
            )
            page_annotations_count += len(annotations)

            # ── Find feedback spot within this question's OCR bounds ───────────
            fb_x, fb_y = None, None
            if fb_text and ocr_page_text:
                # On multi-Q pages, constrain feedback to the question's own slice
                # so it never drifts into a neighbour's zone.
                spot = _find_feedback_spot_in_q_bounds(
                    ocr_page_text, q_num, pdf_h, pdf_w, page_used_y_fracs,
                    text_blocks = text_blocks,
                    ink_top     = ink_top,
                    ink_bot     = ink_bot,
                    slice_top   = _item_slice_top,
                    slice_bot   = _item_slice_bot,
                )
                if spot:
                    fb_x, fb_y = spot
                    fb_y_frac = 1.0 - fb_y / pdf_h
                    page_used_y_fracs.append(fb_y_frac)
                    # Widen the exclusion band (±0.06) so the next question's
                    # feedback search is pushed clearly away and can't overlap.
                    page_used_y_fracs.append(max(ink_top, fb_y_frac - 0.06))
                    page_used_y_fracs.append(min(ink_bot, fb_y_frac + 0.06))

            # ── Compute final stamp Y (DO NOT DRAW YET) ───────────────────────
            # We must wait until fb_y_final is known before drawing the stamp,
            # because fb_y_final (the actual drawn feedback Y from white-rect
            # search) can differ from the earlier fb_y estimate. Drawing the
            # stamp now and trying to "fix" it later causes double-stamp artifacts
            # in the PDF overlay (white-rect erasing doesn't work in overlays).
            final_stamp_y = None
            if _pending_stamp is not None:
                final_stamp_y = _pending_stamp["y"]
                # Preliminary nudge based on the early fb_y estimate.
                # Use actual range intersection so we only move when there IS overlap.
                # Skip nudging on multi-Q pages where we explicitly forced stamp to top/bottom.
                if fb_y is not None and n_items == 1:
                    FB_FONT_SIZE_PRE = int(14 * page_scale)
                    half_h_pre = _pending_stamp["half_h_pts"]
                    s_bot = final_stamp_y - half_h_pre
                    s_top = final_stamp_y + half_h_pre
                    f_bot = fb_y
                    f_top = fb_y + FB_FONT_SIZE_PRE
                    if min(s_top, f_top) - max(s_bot, f_bot) > 0:  # ranges overlap
                        # Prefer pushing stamp BELOW feedback (natural: stamp near end-of-answer)
                        below_y = f_bot - half_h_pre - 8
                        above_y = f_top + half_h_pre + 8
                        if below_y >= half_h_pre + 4:
                            final_stamp_y = below_y
                        else:
                            final_stamp_y = min(above_y, pdf_h * 0.88 - half_h_pre)

            # ── Draw ticks / crosses ───────────────────────────────────────────
            # On pages where MCQ answers occupy the top half, skip any tick/cross
            # whose y_pdf is above the midpoint (PDF y=0 is bottom, so top half
            # means y_pdf > pdf_h * 0.55).
            if not (is_full_paper and section == "SectionA"):
                for ann in annotations:
                    draw_x = ann["ann_x"] + random.uniform(-2, 2)
                    draw_y = ann["y_pdf"]
                    if _page_mcq_top and draw_y > pdf_h * 0.25:
                        continue   # skip — this annotation falls outside bottom-25% zone
                    if draw_y > pdf_h - 30:
                        continue   # skip — within 30 pixels of top margin
                    if ann["action"] == "tick":
                        sz = random.uniform(65, 80) * page_scale
                        pass # DEFERRED
                    else:
                        sz = random.uniform(55, 70) * page_scale
                        pass # DEFERRED
                    # v2: record tick/cross
                    _manifest["questions"][_mkey]["ticks_crosses"].append({
                        "page":   page_num,
                        "x":      draw_x,
                        "y":      draw_y,
                        "action": ann["action"],
                        "size":   sz,
                    })

            # ── Draw feedback (largest white rect in question zone) ────────────
            placed = False   # ensure always defined before the if placed: check
            if fb_text and not (is_full_paper and section == "SectionA"):
                FB_FONT_SIZE = int(14 * page_scale)
                EST_CHAR_W   = FB_FONT_SIZE * 0.60
                
                import textwrap
                fb_wrapped = []
                for line in fb_text.split('\n'):
                    fb_wrapped.extend(textwrap.wrap(line, width=50))
                
                # Estimate max width based on the longest wrapped line
                max_chars = max([len(ln) for ln in fb_wrapped] + [1])
                fb_text_w_pt = max_chars * EST_CHAR_W
                fb_need_px   = int((fb_text_w_pt / pdf_w) * img_w) + 20
                fb_num_lines = len(fb_wrapped)
                fb_need_h_px = int((FB_FONT_SIZE * 1.5 * fb_num_lines / pdf_h) * img_h)

                # Question pixel bounds from OCR
                # Use largest-white-rect to find a truly ink-free spot for feedback
                # Search within the question's vertical boundaries
                if ocr_page_text:
                    start_ln2, end_ln2 = _find_question_line_bounds(ocr_page_text, q_num)
                    total_ln2 = max(1, len(ocr_page_text.split('\n')))
                    raw_top = start_ln2 / total_ln2
                    raw_bot = end_ln2 / total_ln2
                    if False:
                        t_idx_top = min(len(f_blocks)-1, max(0, int(raw_top * len(f_blocks))))
                        t_idx_bot = min(len(f_blocks)-1, max(0, int(raw_bot * len(f_blocks))))
                        q_top_frac2 = f_blocks[t_idx_top][0]
                        q_bot_frac2 = f_blocks[t_idx_bot][0]
                    else:
                        q_top_frac2 = ink_top + raw_top * (ink_bot - ink_top)
                        q_bot_frac2 = ink_top + raw_bot * (ink_bot - ink_top)
                    
                    # Clamp to this question's slice boundaries on multi-Q pages.
                    # Without this, a top-half question expands its search into the next question's zone.
                    q_top_frac2 = max(q_top_frac2, _item_slice_top)
                    # Strictly prohibit bleeding into the neighbour's slice to prevent feedback overlap!
                    if n_items > 1:
                        q_bot_frac2 = min(q_bot_frac2, _item_slice_bot - 0.01)
                    else:
                        q_bot_frac2 = min(q_bot_frac2, 0.98)
                else:
                    q_top_frac2, q_bot_frac2 = max(ink_top, _item_slice_top), min(ink_bot, _item_slice_bot)

                fb_row_top = max(0,          int(q_top_frac2 * img_h))
                fb_row_bot = min(img_h - 1,  int(q_bot_frac2 * img_h))

                fb_row_bot = max(fb_row_bot, fb_row_top + fb_need_h_px + 4)
                fb_row_bot = min(fb_row_bot, img_h)  # never exceed image height

                rect_result = _find_largest_white_rect(
                    gray, img_w, img_h, pdf_w, pdf_h,
                    fb_row_top, fb_row_bot,
                    min_w_px=fb_need_px, min_h_px=fb_need_h_px,
                    excluded_px_rows=page_excluded_px_rows,
                    align_top=True,
                )

                if rect_result:
                    fb_x_final, fb_y_final = rect_result[0], rect_result[1]
                    print(f"    [DEBUG] Q{q_num} feedback placed at rect (x={fb_x_final:.0f}, y={fb_y_final:.0f}), w={rect_result[2]}, h={rect_result[3]}", flush=True)
                    fb_x_final = min(fb_x_final, pdf_w - fb_text_w_pt - 10)
                    fb_x_final = max(fb_x_final, pdf_w * 0.04)
                    fb_y_frac_used = 1.0 - fb_y_final / pdf_h
                    page_used_y_fracs.append(fb_y_frac_used)
                    fb_cy_px = int((1.0 - fb_y_final / pdf_h) * img_h)
                    half_h = max(30, fb_need_h_px // 2 + 15)
                    for pr2 in range(fb_cy_px - half_h, fb_cy_px + half_h + 1):
                        page_excluded_px_rows.add(pr2)
                    placed = True
                else:
                    # Fallback: gap-between-blocks
                    sorted_blocks2 = sorted(text_blocks, key=lambda b: b[0])
                    prev_bot2, gaps2 = 0.0, []
                    for blk in sorted_blocks2:
                        blk_top = blk[0] - blk[1] / 2
                        if blk_top > prev_bot2 + 0.015:
                            gaps2.append((prev_bot2, blk_top, (prev_bot2 + blk_top) / 2))
                        prev_bot2 = blk[0] + blk[1] / 2
                    if prev_bot2 < 0.96:
                        gaps2.append((prev_bot2, 0.96, (prev_bot2 + 0.96) / 2))

                    fb_y_frac_raw = (1.0 - fb_y / pdf_h) if fb_y is not None else (q_bot_frac2 if q_bot_frac2 < 0.9 else 0.9)
                    best_gap2, best_score2 = None, -1e9
                    for gt, gb, gc in gaps2:
                        if gb < q_top_frac2 or gt > q_bot_frac2: continue
                        if any(abs(gc - u) < 0.05 for u in page_used_y_fracs): continue
                        score = (1.0 if q_top_frac2 <= gc <= q_bot_frac2 else 0.0) * 10 - abs(gc - fb_y_frac_raw)
                        if score > best_score2:
                            best_score2, best_gap2 = score, (gt, gb, gc)

                    if best_gap2:
                        gt, gb, gc = best_gap2
                        fb_y_final = pdf_h * (1.0 - gc)
                        fb_x_final = pdf_w * 0.08
                        fb_x_final = min(fb_x_final, pdf_w - fb_text_w_pt - 10)
                        fb_x_final = max(fb_x_final, pdf_w * 0.04)
                        page_used_y_fracs.append(gc)
                        placed = True
                        print(f"    [DEBUG] Q{q_num} feedback placed via gap fallback at (x={fb_x_final:.0f}, y={fb_y_final:.0f})", flush=True)
                    else:
                        # Absolute fallback: Find ANY clear horizontal line using _find_clear_xy
                        fallback_y_frac = fb_y_frac_raw if fb_y is not None else (q_bot_frac2 if q_bot_frac2 < 0.9 else 0.9)
                        fb_x_final, fb_y_final = _find_clear_xy(
                            gray, img_w, img_h, pdf_w, pdf_h, fallback_y_frac, False,
                            min_clear_cols=20, required_text_width_px=fb_need_px,
                            excluded_px_rows=page_excluded_px_rows,
                            max_search_delta=0.10,
                            min_y_frac=q_top_frac2,
                            max_y_frac=q_bot_frac2,
                        )
                        fb_x_final = min(fb_x_final, pdf_w - fb_text_w_pt - 10)
                        fb_x_final = max(fb_x_final, pdf_w * 0.04)
                        page_used_y_fracs.append(1.0 - fb_y_final / pdf_h)
                        fb_cy_px = int((1.0 - fb_y_final / pdf_h) * img_h)
                        half_h = max(30, fb_need_h_px // 2 + 15)
                        for pr2 in range(fb_cy_px - half_h, fb_cy_px + half_h + 1):
                            page_excluded_px_rows.add(pr2)
                        placed = True
                    print(f"    [DEBUG] Q{q_num} feedback placed via clear-xy fallback at (x={fb_x_final:.0f}, y={fb_y_final:.0f})", flush=True)

            # ── Final overlap check against ALL drawn items on this page ──
            # First, if feedback was placed for THIS question, add it to rects
            # so we avoid it just like previous questions' rects.
            if placed and fb_y_final is not None:
                FB_FSZ = int(14 * page_scale)
                page_drawn_rects_y.append((fb_y_final, fb_y_final + FB_FSZ))

            # Nudge stamp if it overlaps with any feedback or stamp from this or earlier questions
            if _pending_stamp is not None and final_stamp_y is not None:
                half_h_f = _pending_stamp["half_h_pts"]
                
                s_bot_f  = final_stamp_y - half_h_f
                s_top_f  = final_stamp_y + half_h_f

                for r_bot, r_top in page_drawn_rects_y:
                    if min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0:
                        below_y_f = r_bot - half_h_f - 8
                        above_y_f = r_top + half_h_f + 8
                        if below_y_f >= half_h_f + 4:
                            final_stamp_y = below_y_f
                        else:
                            final_stamp_y = min(above_y_f, pdf_h * 0.88 - half_h_f)
                        # Update our own bounds for the next rect check
                        s_bot_f  = final_stamp_y - half_h_f
                        s_top_f  = final_stamp_y + half_h_f
                        print(f"    ↑ Stamp adjusted to y={final_stamp_y:.0f} to clear rect {r_bot:.0f}-{r_top:.0f}", flush=True)

                # ── Right-margin fallback ──────────────────────────────────
                still_collides = any(
                    min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0
                    for r_bot, r_top in page_drawn_rects_y
                )
                if still_collides:
                    _pending_stamp["x"] = pdf_w * 0.88
                    print(f"    → Stamp moved to right margin (x={pdf_w * 0.88:.0f}) to avoid collision", flush=True)

                # Draw stamp exactly once at its final collision-free position
                stamp_half_h = _pending_stamp["half_h_pts"]
                pass # DEFERRED STAMP
                # v2: record stamp
                _manifest["questions"][_mkey]["stamp"] = {
                    "page":  page_num,
                    "x":     _pending_stamp["x"],
                    "y":     final_stamp_y,
                    "scale": page_scale,
                }
                _pending_stamp = None   # consumed — prevent double draw below
                page_drawn_rects_y.append((final_stamp_y - stamp_half_h, final_stamp_y + stamp_half_h))

            # Draw feedback
            if placed and fb_text:
                # --- Overlap prevention for feedback ---
                _all_ann_rects = []
                for q_key, q_data in _manifest.get("questions", {}).items():
                    for tc in q_data.get("ticks_crosses", []):
                        if tc.get("page") == page_num:
                            sz = tc.get("size", 60)
                            _all_ann_rects.append((tc["x"] - sz/2, tc["y"] - sz/2, tc["x"] + sz/2, tc["y"] + sz/2))
                    st = q_data.get("stamp")
                    if st and st.get("page") == page_num:
                        sw, sh = 80 * st.get("scale", 1), 60 * st.get("scale", 1)
                        _all_ann_rects.append((st["x"] - sw/2, st["y"] - sh/2, st["x"] + sw/2, st["y"] + sh/2))
                    fb = q_data.get("feedback")
                    if fb and fb.get("page") == page_num:
                        fb_fsz = fb.get("font_size", 14)
                        lines = len(fb.get("text", "").split("\\n"))
                        fh = lines * fb_fsz * 1.5 + 8
                        fw = 400 * fb.get("scale", 1) # generous width estimate
                        bg_y = fb["y"] - (lines - 1) * fb_fsz * 1.5 - fb_fsz * 0.3 - 4
                        _all_ann_rects.append((fb["x"] - 4, bg_y, fb["x"] + fw, bg_y + fh))
                
                def _rects_overlap(r1, r2):
                    return not (r1[2] < r2[0] or r1[0] > r2[2] or r1[3] < r2[1] or r1[1] > r2[3])

                bg_padding_x = 4
                bg_padding_y = 4
                bg_h = fb_num_lines * FB_FONT_SIZE * 1.5 + bg_padding_y * 2
                bg_w = fb_text_w_pt + bg_padding_x * 2

                _found_clear = False
                _y_offsets = [0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90, 110, -110, 130, -130]
                _x_offsets = [0, 20, -20, 50, -50, 80, -80]
                
                for _x_off in _x_offsets:
                    test_x = fb_x_final + _x_off
                    # Ensure it doesn't go off the left or right edges
                    if test_x < 15 or (test_x + bg_w) > (pdf_w - 15):
                        continue
                    
                    for _y_off in _y_offsets:
                        test_y = fb_y_final + _y_off
                        # Ensure it doesn't go off top or bottom edges
                        if test_y < 30 or test_y > (pdf_h - 30):
                            continue
                            
                        bg_y = test_y - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - bg_padding_y
                        my_rect = (test_x - bg_padding_x, bg_y, test_x - bg_padding_x + bg_w, bg_y + bg_h)
                        
                        if not any(_rects_overlap(my_rect, r) for r in _all_ann_rects):
                            fb_x_final = test_x
                            fb_y_final = test_y
                            _found_clear = True
                            break
                    if _found_clear:
                        break
                # ---------------------------------------

                # c.saveState()
                
                # Draw a white background box to hide noise/scan lines
                bg_y = fb_y_final - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - bg_padding_y
                
                # c.setFillColorRGB(1, 1, 1)
                # c.setStrokeColorRGB(1, 1, 1, 0)
                # c.rect(fb_x_final - bg_padding_x, bg_y, bg_w, bg_h, fill=1, stroke=0)
                
                # c.setFont(font_name, FB_FONT_SIZE)
                # c.setFillColor(red)
                # c.setStrokeColor(red)
                # c.setLineWidth(1.8)
                
                # Wrap text here to prevent it from stretching across the page and overlapping right-margin stamps
                import textwrap
                wrapped_lines = []
                for line in fb_text.split('\\n'):
                    wrapped_lines.extend(textwrap.wrap(line, width=50))
                
                _draw_y = fb_y_final
                for line in wrapped_lines:
                # c.drawString(fb_x_final, _draw_y, line)
                    _draw_y -= FB_FONT_SIZE * 1.5
                    
                # c.setLineWidth(0)
                
                _draw_y = fb_y_final
                for line in wrapped_lines:
                # c.drawString(fb_x_final, _draw_y, line)
                    _draw_y -= FB_FONT_SIZE * 1.5

                # c.restoreState()

                # v2: record feedback
                _manifest["questions"][_mkey]["feedback"] = {
                    "text":      fb_text,
                    "page":      page_num,
                    "x":         fb_x_final,
                    "y":         fb_y_final,
                    "font_size": FB_FONT_SIZE,
                    "scale":     page_scale,
                }

            # ── Phase 3: Final Answer OCR Search ──────────────────────────────
            wrong_final_answer = item.get("wrong_final_answer")
            if wrong_final_answer and ocr_page_text:
                print(f"      🔍 Locating wrong final answer via OCR: '{wrong_final_answer}'", flush=True)
                lines = ocr_page_text.split('\n')
                total_lines = max(1, len(lines))
                found_line = -1
                search_lower = wrong_final_answer.lower().strip()
                for i, line in enumerate(lines):
                    if search_lower in line.lower():
                        found_line = i
                        break
                
                if found_line >= 0:
                    raw_frac = (found_line + 0.5) / total_lines
                    if False:
                        t_idx = min(len(f_blocks)-1, max(0, int(raw_frac * len(f_blocks))))
                        y_frac = f_blocks[t_idx][0]
                    else:
                        y_frac = ink_top + raw_frac * (ink_bot - ink_top)
                    
                    # Robust collision avoidance against ticks/crosses/feedback
                    MIN_SEP = 0.09
                    y_frac = _get_non_colliding_y(y_frac, page_used_y_fracs, ink_top, ink_bot, MIN_SEP)
                    
                    if y_frac is not None:
                        page_used_y_fracs.append(y_frac)
                        ann_y_px = int(y_frac * img_h)
                        for pr in range(ann_y_px - 40, ann_y_px + 41):
                            page_excluded_px_rows.add(pr)
                        
                        cy = pdf_h * (1.0 - y_frac)
                        cx = _find_clear_x(gray, img_w, img_h, pdf_w, y_frac, is_practical, excluded_px_rows=page_excluded_px_rows)
                        
                        print(f"      ✓ OCR found answer. Drawing cross at cx={cx:.1f}, cy={cy:.1f}", flush=True)
                        pass # DEFERRED
                        _manifest.setdefault("phase3_crosses", []).append({"page": page_num, "x": cx, "y": cy, "size": random.uniform(55, 85)})
                    else:
                        print(f"      ✗ Could not find non-colliding spot for wrong final answer", flush=True)
                else:
                    print(f"      ✗ OCR could not locate '{wrong_final_answer}' on page", flush=True)


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
            if qdata.get("feedback") and qdata["feedback"]["page"] == page_num:
                page_fbs.append((qdata["feedback"], qdata["feedback"]))
                
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

        movables = [("stamp", s[0]) for s in page_stamps] + [("feedback", f[0]) for f in page_fbs]
        fixed = [("tick", t[0]) for t in page_ticks] + [("cross", t[0]) for t in page_p3]
        
        for _ in range(15):
            moved_any = False
            for m_type, m_obj in movables:
                m_rect = get_rect(m_obj, m_type)
                
                all_others = [("tick", t[0]) for t in page_ticks] +                              [("cross", t[0]) for t in page_p3] +                              [("stamp", s[0]) for s in page_stamps if s[0] is not m_obj] +                              [("feedback", f[0]) for f in page_fbs if f[0] is not m_obj]
                             
                for o_type, o_obj in all_others:
                    o_rect = get_rect(o_obj, o_type)
                    if _rects_overlap(m_rect, o_rect):
                        dx1 = o_rect[2] - m_rect[0] + 8
                        dx2 = o_rect[0] - m_rect[2] - 8
                        dy1 = o_rect[3] - m_rect[1] + 8
                        dy2 = o_rect[1] - m_rect[3] - 8
                        
                        moves = []
                        if m_type == "stamp":
                            # Stamps move ONLY left/right
                            moves = [
                                (dx1, 0, abs(dx1)),
                                (dx2, 0, abs(dx2)),
                            ]
                        elif m_type == "feedback":
                            # Feedback moves ONLY up/down
                            moves = [
                                (0, dy1, abs(dy1)),
                                (0, dy2, abs(dy2)),
                            ]
                        else:
                            moves = [
                                (dx1, 0, abs(dx1)),
                                (dx2, 0, abs(dx2)),
                                (0, dy1, abs(dy1)),
                                (0, dy2, abs(dy2)),
                            ]
                        
                        moves.sort(key=lambda x: x[2])
                        best_move = moves[0]
                        m_obj["x"] += best_move[0]
                        m_obj["y"] += best_move[1]
                        
                        m_obj["x"] = max(50, min(pdf_w - 50, m_obj["x"]))
                        m_obj["y"] = max(50, min(pdf_h - 50, m_obj["y"]))
                        moved_any = True
                        break
            if not moved_any:
                break
                
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
                marks_obtained=qdata["marks_obtained"],
                marks_total=qdata["marks_total"],
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
