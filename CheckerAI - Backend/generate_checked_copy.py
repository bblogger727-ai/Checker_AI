#!/usr/bin/env python3
"""
Stage 7: Generate Checked Copy of Student Answer Sheet (Student-Facing)

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

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

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
    r"ANSWER\s+TO\s+QUESTION\s*[-#]?\s*{n}\b",
    r"ANSWER\s+TO\s+Q\s*{n}\b",
    r"QUESTION\s*[-#]?\s*{n}\b",
    r"\bQ\s*{n}\b",
    r"ANS\w*\s+{n}\b",
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

    # ── Case 2: Very poor score (< 25%) → 2–3 bullet points ───────────────
    elif marks_ratio < 0.25:
        context      = f"Grader feedback: {feedback_raw}\n" if feedback_raw else ""
        errors_block = f"Key errors: {errors_str}\n" if errors_str else ""
        prompt = (
            f"A student scored {marks_obtained}/{marks_total} on an exam question.\n"
            f"{context}{errors_block}"
            f"{avoid_block}\n"
            "Write 2 to 3 very short bullet points (start each with '•') listing the "
            "main things the student missed or got wrong. Each bullet must be ≤10 words. "
            "No full stop at the end of each bullet. Return only the bullets, no intro text."
        )
        max_tok = 90

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
    scale_x = fitz_page.rect.width  / w
    scale_y = fitz_page.rect.height / h

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
    Find the true bottom of student handwriting using Tesseract word bounding boxes.

    pytesseract.image_to_data() returns (left, top, width, height, conf, text)
    for every recognized word. The maximum value of (top + height) across all
    words with confidence > 0 gives us the exact pixel row where writing ends.

    This is completely immune to ruled lines, scanner shadows, and scan artifacts
    because Tesseract only reports bounding boxes for TEXT it actually recognized.

    Falls back to a density-based approach if pytesseract is unavailable.

    Returns a fraction of page height (0.0 = top, 1.0 = bottom).
    """
    # ── Primary: Tesseract bounding boxes ────────────────────────────────────
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            gray,
            output_type=pytesseract.Output.DICT,
            config="--psm 3",
        )
        max_bottom = 0
        for i, conf in enumerate(data["conf"]):
            if int(conf) > 10 and str(data["text"][i]).strip():
                bottom = data["top"][i] + data["height"][i]
                if bottom > max_bottom:
                    max_bottom = bottom
        if max_bottom > 10:
            margin = int(img_h * 0.03)   # 3 % padding below last word
            return min(0.93, (max_bottom + margin) / img_h)
    except Exception:
        pass

    # ── Fallback: density-based approach ─────────────────────────────────────
    px      = gray.load()
    INK_THR = 150
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
    hw_threshold = max(0.04, median_d * 4)

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
            if row < int(img_h * 0.03) or row > int(img_h * 0.97):
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
    x_hi  = int(img_w * 0.95)
    width = x_hi - x_lo
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

    for row in range(row_top, row_bot):
        if _row_excluded(row):
            height = [0] * width
            continue

        # Update column heights
        for ci in range(width):
            if px[x_lo + ci, row] >= ink_thr:
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
    
    for c in candidates:
        if c < ink_top or c > ink_bot - 0.02:
            continue
        if all(abs(c - u) >= min_sep for u in page_used):
            return c
    return None


# ── Variable X for ticks/crosses ──────────────────────────────────────────────
def _find_clear_x(gray: Image.Image, img_w: int, img_h: int, pdf_w: float, y_frac: float, is_practical: bool, excluded_px_rows: set = None) -> float:
    """
    Finds an x-coordinate on the page at the given y_frac that does not contain ink.
    Clamped to [0.15, 0.85] width so marks don't touch extreme corners.
    """
    px = gray.load()
    y = int(y_frac * img_h)
    y = max(0, min(img_h - 1, y))

    if excluded_px_rows and any(abs(y - er) <= 50 for er in excluded_px_rows):
        return _random_ann_x(pdf_w, is_practical)
    
    band_half = int(img_h * 0.035)  # increased vertical band to 3.5%
    INK_THR = 215
    
    x_min = int(img_w * 0.15)
    x_max = int(img_w * 0.85)
    
    clear_cols = []
    for x in range(x_min, x_max):
        is_clear = True
        for dy in range(-band_half, band_half + 1, 4):
            yy = min(max(0, y + dy), img_h - 1)
            if px[x, yy] < INK_THR:
                is_clear = False
                break
        if is_clear:
            clear_cols.append(x)
            
    if not clear_cols:
        return _random_ann_x(pdf_w, is_practical)

        
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
    return (center_x / img_w) * pdf_w


def _random_ann_x(pdf_w: float, is_practical: bool = False) -> float:
    """
    Pick a natural X position. Clamped so it doesn't touch extreme corners.
    """
    if is_practical:
        if random.random() < 0.70:
            return random.uniform(pdf_w * 0.62, pdf_w * 0.85)
        return random.uniform(pdf_w * 0.35, pdf_w * 0.62)
    # Theory
    if random.random() < 0.70:
        return random.uniform(pdf_w * 0.15, pdf_w * 0.35)
    return random.uniform(pdf_w * 0.35, pdf_w * 0.50)


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
):
    """
    Draw a proper stacked fraction:
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
    pats = [re.compile(t.replace("{n}", re.escape(q_num)), re.IGNORECASE)
            for t in _HEADING_PATTERNS]
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
) -> float:
    """Four-strategy heading Y (PDF bottom-origin)."""
    y = _heading_fitz(fitz_page, pdf_h, q_num)
    if y: return y

    y = _heading_ocr(ocr_path, fitz_page.number + 1, pdf_h, q_num)
    if y: return y

    y = _heading_first_block(gray, img_w, img_h, pdf_h)
    if y: return y

    return pdf_h * 0.91


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

    if is_first:
        return "tick" if marks_obtained > 0 else "cross"

    if is_last:
        return "cross" if marks_obtained < marks_total else "tick"

    # Middle slots: probabilistic, weighted by marks ratio
    return "tick" if random.random() < marks_ratio else "cross"




def _find_question_line_bounds(ocr_text: str, q_num: str) -> tuple[int, int]:
    """
    Find the start and end line indices (0-indexed) for question q_num in the
    OCR text. End is exclusive (first line of the NEXT question, or EOF).
    """
    import re
    lines = ocr_text.split("\n")

    # Strict: line is exactly "Q<num>" possibly with surrounding spaces
    q_exact   = re.compile(rf"^\s*(?:Q|Question)[\s\-\.]*{re.escape(q_num)}\s*$", re.IGNORECASE)
    # Loose:  line starts with Q<num> followed by word boundary
    q_loose   = re.compile(rf"^\s*(?:Q|Question)[\s\-\.]*{re.escape(q_num)}\b",   re.IGNORECASE)
    any_q     = re.compile(r"^\s*(?:Q|Question)[\s\-\.]*\d+\b", re.IGNORECASE)

    start = None
    for pattern in (q_exact, q_loose):
        for i, line in enumerate(lines):
            stripped = line.strip()
            if start is None and pattern.match(stripped):
                start = i
            elif start is not None and any_q.match(stripped) and not pattern.match(stripped):
                return start, i
        if start is not None:
            return start, len(lines)

    return 0, len(lines)   # fallback: whole page


def _plan_annotations_from_ocr(
    ocr_page_text: str,
    q_num: str,
    pdf_w: float, pdf_h: float,
    marks_obtained: float, marks_total: float,
    page_idx_in_q: int, total_pages: int,
    page_used_y_fracs: list,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
    is_practical: bool = False,
    is_first: bool = False,
    heading_y_frac: float = None,
    gray: Image.Image = None,
    img_w: int = 1000,
    img_h: int = 1000,
    page_excluded_px_rows: set = None,
    text_blocks: list = None,
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
    MIN_SEP     = 0.12
    max_ann     = random.randint(2, 4)

    # ── Step 1: build candidate Y-fracs from OCR lines ───────────────────────
    y_candidates: list[float] = []

    if ocr_page_text.strip():
        lines       = ocr_page_text.split("\n")
        total_lines = len(lines)
        start_line, end_line = _find_question_line_bounds(ocr_page_text, q_num)

        content_idxs = [
            i for i in range(start_line + 1, min(end_line, total_lines))
            if lines[i].strip()
        ]

        if content_idxs:
            # Pick evenly-spaced content lines
            if len(content_idxs) <= max_ann:
                selected = content_idxs
            else:
                step     = len(content_idxs) / max_ann
                selected = [content_idxs[int(i * step)] for i in range(max_ann)]

            for line_idx in selected:
                # Map OCR line fraction → position within the ink region only.
                # Never use text_blocks index mapping — it spreads positions
                # across the full page even when writing covers only part of it.
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac   = ink_top + raw_frac * (ink_bot - ink_top)
                y_candidates.append(y_frac)

    # ── Step 2: fallback to text_blocks when OCR gave nothing ─────────────────
    # Handles pages that are densely written but have no OCR coverage.
    if not y_candidates and text_blocks:
        # Sample evenly from the detected ink blocks
        step = max(1, len(text_blocks) / max_ann)
        for i in range(min(max_ann, len(text_blocks))):
            blk_center = text_blocks[int(i * step)][0]   # center_frac
            # Clamp to measured ink region
            y_candidates.append(min(max(blk_center, ink_top), ink_bot - 0.02))

    # ── Step 3: absolute fallback — evenly spaced within ink region ───────────
    if not y_candidates:
        span = ink_bot - ink_top
        for i in range(max_ann):
            y_candidates.append(ink_top + span * (i + 0.5) / max_ann)

    # ── Step 4: emit annotations ──────────────────────────────────────────────
    n_sel  = len(y_candidates)
    result = []

    for ann_idx, y_frac in enumerate(y_candidates):
        # Skip if too close to heading stamp
        if heading_y_frac is not None and abs(y_frac - heading_y_frac) < 0.06:
            y_frac = heading_y_frac + 0.07

        # Hard-clamp to ink region
        y_frac = min(max(y_frac, ink_top), ink_bot - 0.02)

        # Collision avoidance
        y_frac = _get_non_colliding_y(y_frac, page_used_y_fracs, ink_top, ink_bot, MIN_SEP)
        if y_frac is None:
            continue

        # Tick or cross decision
        is_first_ann = (page_idx_in_q == 0 and ann_idx == 0)
        is_last_ann  = (page_idx_in_q == total_pages - 1 and ann_idx == n_sel - 1)

        if is_first_ann:
            action = "tick" if marks_obtained > 0 else "cross"
        elif is_last_ann:
            action = "cross" if marks_obtained < marks_total else "tick"
        else:
            action = "tick" if random.random() < marks_ratio else "cross"

        y_pdf = pdf_h * (1.0 - y_frac) + random.uniform(-4, 4)
        page_used_y_fracs.append(y_frac)
        if page_excluded_px_rows is not None:
            ann_y_px = int(y_frac * img_h)
            for pr in range(ann_y_px - 40, ann_y_px + 41):
                page_excluded_px_rows.add(pr)

        if gray is not None:
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

    start_line, end_line = _find_question_line_bounds(ocr_page_text, q_num)
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

    # Prefer just after the question ends
    raw_frac = min(1.0, (end_line + 0.5) / total_lines)
    y_frac = _try_candidate(raw_frac)
    if y_frac is not None:
        return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Prefer blank lines within this question's OCR bounds, starting from the BOTTOM
    blank_lines = [
        i for i in range(start_line + 1, min(end_line, total_lines))
        if not lines[i].strip()
    ]
    for bl in reversed(blank_lines):
        raw_frac = (bl + 0.5) / total_lines
        y_frac = _try_candidate(raw_frac)
        if y_frac is not None:
            return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Fallback 1: Just after the question heading (start of the question)
    raw_frac_start = (start_line + 1.5) / total_lines
    y_frac = _try_candidate(raw_frac_start)
    if y_frac is not None:
        return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Fallback 2: Middle of the question
    middle_line = (start_line + min(end_line, total_lines)) / 2.0
    raw_frac_mid = middle_line / total_lines
    y_frac = _try_candidate(raw_frac_mid)
    if y_frac is not None:
        return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # FINAL FALLBACK: Ignore text blocks, force placement near the start to ensure feedback is placed!
    base = _scale(raw_frac_start)
    for delta in [0.0, -0.04, 0.04, -0.08, 0.08, -0.12, 0.12, -0.16, 0.16]:
        candidate = base + delta
        if candidate < ink_top or candidate > ink_bot:
            continue
        if _is_clear_of_used(candidate):
            return pdf_w * 0.08, pdf_h * (1.0 - candidate)
            
    return None   # give up — completely packed page


# ── Helpers ───────────────────────────────────────────────────────────────────

def _block_y_pdf(center_frac: float, pdf_h: float) -> float:
    return pdf_h * (1.0 - center_frac)


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_checked_copy(
    pdf_path: str,
    grading_json: str,
    aligned_json: str,
    output_path: str,
    ocr_text_path: str = None,
):
    print(f"\n{'='*62}")
    print("  STAGE 7 — Generating Checked Copy (Student-Facing)")
    print(f"{'='*62}")
    print(f"  Source  : {pdf_path}")
    print(f"  Output  : {output_path}")

    _ensure_tesseract()

    # Reset per-document feedback state
    _feedback_cache.clear()
    _used_feedback_texts.clear()

    with open(grading_json, "r") as f:
        grading_data = json.load(f)
    with open(aligned_json, "r") as f:
        aligned_data = json.load(f)

    graded_answers = grading_data.get("graded_answers", {})
    font_name      = _register_fonts()

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

            if not grade_entry.get("student_answer", "").strip():
                print(f"  ⊘ Skip {section}/{q_id} — unanswered")
                continue

            tier = grade_entry.get("tier", "poor")
            if TIER_ACTION.get(tier) is None:
                continue


            q_num          = aligned_q.get("question_number", q_id).replace("Q", "").strip()
            marks_obtained = float(grade_entry.get("marks_obtained", 0) or 0)
            marks_total    = float(grade_entry.get("marks_total",    0) or 0)

            # Pre-generate LLM feedback — descriptive questions only, skip MCQs
            is_mcq = "MCQ" in section or "MCQ" in q_id or q_id.isdigit()
            fb_text = None
            if not is_mcq and grade_entry.get("student_answer", "").strip():
                cache_key = f"{section}__{q_id}"
                fb_text   = _generate_llm_feedback(grade_entry, cache_key)
                if fb_text:
                    print(f'  💬 Feedback for Q{q_num}: "{fb_text}"', flush=True)

            # Check for fundamentally wrong final practical answer
            wrong_final_answer = _check_final_answer_wrong(grade_entry, aligned_q.get("student_answer", ""))
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
                    "wrong_final_answer": wrong_final_answer["wrong_answer_text"] if wrong_final_answer and page_num == target_page else None
                })

    print(f"  Annotating {len(drawing_plan)} pages")

    # ── Build overlay canvas ──────────────────────────────────────────────────
    packet = io.BytesIO()
    c      = canvas.Canvas(packet)

    for page_idx in range(num_pages):
        page_num     = page_idx + 1
        pdf_w, pdf_h = page_dims[page_idx]
        c.setPageSize((pdf_w, pdf_h))

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
            gt_x = max(gt_x_min, min(gt_x_max, gt_x))
            gt_y = max(gt_y_min, min(gt_y_max, gt_y))
            _draw_total_marks_stamp(c, gt_x, gt_y, grand_obtained, grand_total,
                                    font_name, scale=page_scale)

        if not items:
            c.showPage()
            continue

        # Filter out scanner noise / stray marks for calculating ink bounds
        f_blocks = text_blocks
        if text_blocks:
            max_span = max(b[1] for b in text_blocks)
            f_blocks = [b for b in text_blocks if b[1] >= max_span * 0.30]
            if not f_blocks:
                f_blocks = text_blocks

        # Compute ink bounds from image analysis
        if f_blocks:
            ink_top = max(0.04, min(b[0] - b[1]/2 for b in f_blocks))
            ink_bot = min(0.96, max(b[0] + b[1]/2 for b in f_blocks))
        else:
            ink_top, ink_bot = 0.04, 0.96

        # ── Authoritative ink_bot: scan the CENTRAL strip from bottom upward ──────
        # _compute_ink_bot_strict() only looks at the central 80 % of page width,
        # so scanner borders, spine shadows, and corner artifacts are completely
        # ignored. It finds the true last handwritten row on the page.
        strict_ink_bot = _compute_ink_bot_strict(gray, img_w, img_h)
        # Use the tighter of image-block analysis and the central-strip scan
        ink_bot = min(ink_bot, strict_ink_bot)
        # Ensure ink_bot is always at least 0.10 below ink_top
        ink_bot = max(ink_bot, ink_top + 0.10)

        # ── Page-scale factor was moved above grand-total stamp ────────────────
        # (REF_H and page_scale are already defined above)

        # ── Pre-compute headings for all is_first items on this page ────────────────
        # Used by the multi-question stamp slicer below to find each question's
        # ACTUAL vertical position rather than splitting the page equally.
        pre_heading_fracs: dict = {}   # q_num → image-space fraction (0=top, 1=bottom)
        for _it in items:
            if _it["is_first"]:
                _hy = _find_heading_y(
                    fitz_page, gray, img_w, img_h, pdf_h,
                    _it["q_num"], ocr_text_path
                )
                if _hy is not None:
                    pre_heading_fracs[_it["q_num"]] = 1.0 - _hy / pdf_h  # → image frac

        # Track chosen Y coordinates (as fractions) globally per page
        # so if P14 has BOTH Q7 and Q8, their marks don't overlap side-by-side!
        # Tracks pixel rows (image space) already claimed by stamps on this page
        # Tracks pixel rows (image space) already claimed by stamps on this page
        page_used_y_fracs = []
        page_excluded_px_rows: set = set()
        page_drawn_rects_y = []  # List of (y_bottom, y_top) in PDF coords
        _page_mcq_top = False   # True when page 1 has MCQ answers in upper half

        for item in items:
            q_num          = item["q_num"]
            grade_entry    = item["grade_entry"]
            is_first       = item["is_first"]
            marks_obtained = item["marks_obtained"]
            tier           = item["tier"]
            fb_text        = item["fb_text"]

            # ── Load OCR and practical flag early ──────────────────────────────
            is_practical  = "practical" in grade_entry.get("grading_method", "").lower()
            ocr_page_text = _load_ocr_page_text(ocr_text_path, page_num) if ocr_text_path else ""

            # ── Marks stamp on first page of each answer ───────────────────────
            heading_y = None
            if is_first:
                heading_y = _find_heading_y(
                    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_text_path
                )

                # ── Marks stamp placement: LEFT MARGIN is the primary target ──
                # Strategy:
                #   1. Scan the left margin (2–14% width) for the clearest
                #      vertical band within the question's vertical extent.
                #   2. If no left-margin gap, search anywhere on the page for
                #      the largest white rectangle (avoids student text).
                #   3. Last resort: _find_clear_xy near the heading.

                # ── Pre-compute per-question vertical slices when page is shared ─
                # Count how many 'is_first' questions are on this page and what
                # their order is, so each gets a distinct, non-overlapping slice.
                first_items_on_page = [it for it in items if it["is_first"]]
                n_firsts = len(first_items_on_page)
                my_order = next((i for i, it in enumerate(first_items_on_page)
                                 if it["q_num"] == q_num), 0)

                multi_q_target_y_frac = None   # default; set in n_firsts>1 branch
                if ocr_page_text and n_firsts == 1:
                    # Only one question on this page: use OCR bounds normally
                    start_ln, end_ln = _find_question_line_bounds(ocr_page_text, q_num)
                    total_ln = max(1, len(ocr_page_text.split('\n')))
                    q_top_frac = ink_top + (start_ln / total_ln) * (ink_bot - ink_top)
                    q_bot_frac = ink_top + (end_ln   / total_ln) * (ink_bot - ink_top)
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
                elif n_firsts > 1:
                    # ── Multiple questions on same page: ink-bottom-per-zone approach ──
                    # User insight: the first Q's text ends somewhere in the TOP of the
                    # page, and the second Q's text ends somewhere in the BOTTOM of the
                    # page. Find the actual ink bottom in each question's zone and
                    # place the stamp there — not at an equal-division midpoint.
                    first_q_nums_ordered = [it["q_num"] for it in first_items_on_page]
                    my_idx = first_q_nums_ordered.index(q_num)

                    # Determine the split between this Q and the next Q
                    if my_idx + 1 < len(first_q_nums_ordered):
                        next_q_num = first_q_nums_ordered[my_idx + 1]
                        next_hfrac = pre_heading_fracs.get(next_q_num)
                        # Split point in image coords (0=top, 1=bottom):
                        # use next Q's heading if found, otherwise true midpoint
                        split_frac = next_hfrac if next_hfrac else (ink_top + ink_bot) / 2.0
                    else:
                        split_frac = ink_bot  # last question — extends to page bottom

                    my_hfrac  = pre_heading_fracs.get(q_num, ink_top)
                    zone_top_px = max(0,      int(my_hfrac  * img_h))
                    zone_bot_px = min(img_h,  int(split_frac * img_h))

                    # Find where this question's handwriting ACTUALLY ENDS
                    ink_bot_row = _find_ink_bottom_in_zone(
                        gray, img_h, zone_top_px, zone_bot_px
                    )

                    if my_idx == len(first_q_nums_ordered) - 1:
                        # ── LAST question on a multi-Q page ───────────────────────
                        # Force stamp to the BOTTOM of the page.
                        # Heading detection often misidentifies the question
                        # number, placing it too high. Using the bottom zone
                        # ensures the stamp is near where the student finished
                        # writing this question, which is always near the bottom.
                        q_top_frac = max(split_frac, 0.65)
                        q_bot_frac = 0.95
                        multi_q_target_y_frac = 0.82
                    else:
                        # Other questions: anchor search to just below ink bottom
                        ink_bot_frac = ink_bot_row / img_h
                        q_top_frac   = max(ink_top,    ink_bot_frac - 0.01)
                        q_bot_frac   = min(split_frac, ink_bot_frac + 0.10)

                        if q_bot_frac - q_top_frac < 0.04:
                            q_bot_frac = min(ink_bot, q_top_frac + 0.08)

                        multi_q_target_y_frac = ink_bot_frac + 0.01
                else:
                    multi_q_target_y_frac = None   # single-Q page: no override
                    q_top_frac, q_bot_frac = ink_top, ink_bot

                # Convert to pixel rows; search the full question vertical extent
                stamp_row_top = max(0,      int(q_top_frac * img_h))
                stamp_row_bot = min(img_h,  int(q_bot_frac * img_h))
                stamp_row_bot = max(stamp_row_bot, stamp_row_top + 20)

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
                        # For multi-Q pages use ink_bot_frac as target, not heading_y,
                        # so the stamp is always near the question's last written line.
                        if multi_q_target_y_frac is not None:
                            fallback_target = multi_q_target_y_frac
                        else:
                            fallback_target = 1.0 - heading_y / pdf_h if heading_y else 0.1
                        marks_x, marks_y_placed = _find_clear_xy(
                            gray, img_w, img_h, pdf_w, pdf_h,
                            fallback_target,
                            is_practical=False, min_clear_cols=30,
                            excluded_px_rows=page_excluded_px_rows,
                        )
                        rh_st = 60


                # Register the stamp's pixel row range so feedback avoids it
                stamp_cy_px = int((1.0 - marks_y_placed / pdf_h) * img_h)
                STAMP_H_PX  = max(int(rh_st), 80)   # at least 80px exclusion zone
                for pr in range(stamp_cy_px - STAMP_H_PX // 2,
                                stamp_cy_px + STAMP_H_PX // 2 + 1):
                    page_excluded_px_rows.add(pr)
                page_used_y_fracs.append(1.0 - marks_y_placed / pdf_h)

                # ── Store stamp info; actual drawing is DEFERRED until after feedback ──
                # This allows the overlap check to move the stamp before drawing it
                # (re-drawing on top leaves the original in the PDF too).
                _STAMP_FONT   = int(28 * page_scale)
                _STAMP_HALF_H = _STAMP_FONT * 2 + int(4 * page_scale) * 2 + _STAMP_FONT * 0.20 + 10
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
                ink_top         = ink_top,
                ink_bot         = ink_bot,
                is_practical    = is_practical,
                is_first        = is_first,
                heading_y_frac  = heading_y_frac,
                gray            = gray,
                img_w           = img_w,
                img_h           = img_h,
                page_excluded_px_rows = page_excluded_px_rows,
                text_blocks     = f_blocks,
            )

            # ── Find feedback spot within this question's OCR bounds ───────────
            fb_x, fb_y = None, None
            if fb_text and ocr_page_text:
                spot = _find_feedback_spot_in_q_bounds(
                    ocr_page_text, q_num, pdf_h, pdf_w, page_used_y_fracs,
                    text_blocks = text_blocks,
                    ink_top     = ink_top,
                    ink_bot     = ink_bot,
                )
                if spot:
                    fb_x, fb_y = spot
                    fb_y_frac = 1.0 - fb_y / pdf_h
                    page_used_y_fracs.append(fb_y_frac)

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
                if fb_y is not None:
                    FB_FONT_SIZE_PRE = int(11 * page_scale)
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
                            final_stamp_y = min(above_y, pdf_h - half_h_pre - 4)

            # ── Draw ticks / crosses ───────────────────────────────────────────
            # On pages where MCQ answers occupy the top half, skip any tick/cross
            # whose y_pdf is above the midpoint (PDF y=0 is bottom, so top half
            # means y_pdf > pdf_h * 0.55).
            for ann in annotations:
                draw_x = ann["ann_x"] + random.uniform(-2, 2)
                draw_y = ann["y_pdf"]
                if _page_mcq_top and draw_y > pdf_h * 0.25:
                    continue   # skip — this annotation falls outside bottom-25% zone
                if ann["action"] == "tick":
                    sz = random.uniform(65, 80) * page_scale
                    _draw_tick(c, draw_x, draw_y, size=sz)
                else:
                    _draw_cross(c, draw_x, draw_y, size=random.uniform(55, 70) * page_scale)

            # ── Draw feedback (largest white rect in question zone) ────────────
            if fb_text:
                placed = False   # ensure always defined before the if placed: check
                FB_FONT_SIZE = int(11 * page_scale)
                EST_CHAR_W   = FB_FONT_SIZE * 0.60
                fb_text_w_pt = len(fb_text) * EST_CHAR_W
                fb_need_px   = int((fb_text_w_pt / pdf_w) * img_w) + 20
                fb_num_lines = len(fb_text.split('\n'))
                fb_need_h_px = int((FB_FONT_SIZE * 1.5 * fb_num_lines / pdf_h) * img_h)

                # Question pixel bounds from OCR
                # Use largest-white-rect to find a truly ink-free spot for feedback
                # Search within the question's vertical boundaries
                if ocr_page_text:
                    start_ln2, end_ln2 = _find_question_line_bounds(ocr_page_text, q_num)
                    total_ln2 = max(1, len(ocr_page_text.split('\n')))
                    raw_top = start_ln2 / total_ln2
                    raw_bot = end_ln2 / total_ln2
                    if f_blocks:
                        t_idx_top = min(len(f_blocks)-1, max(0, int(raw_top * len(f_blocks))))
                        t_idx_bot = min(len(f_blocks)-1, max(0, int(raw_bot * len(f_blocks))))
                        q_top_frac2 = f_blocks[t_idx_top][0]
                        q_bot_frac2 = f_blocks[t_idx_bot][0]
                    else:
                        q_top_frac2 = ink_top + raw_top * (ink_bot - ink_top)
                        q_bot_frac2 = ink_top + raw_bot * (ink_bot - ink_top)
                    
                    # Ensure we have some room below the ink to place feedback if needed
                    # By passing align_top=True later, it will stick closely to the bottom of the ink
                    q_bot_frac2 = max(q_bot_frac2, ink_bot + 0.15)
                    q_bot_frac2 = min(q_bot_frac2, 0.98)
                else:
                    q_top_frac2, q_bot_frac2 = ink_top, ink_bot

                fb_row_top = max(0,          int(q_top_frac2 * img_h))
                fb_row_bot = min(img_h - 1,  int(q_bot_frac2 * img_h))

                fb_row_bot = max(fb_row_bot, fb_row_top + fb_need_h_px + 4)

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
                    for pr2 in range(fb_cy_px - 20, fb_cy_px + 21):
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
                        if gb < ink_top or gt > ink_bot: continue
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
                    else:
                        # Absolute fallback: Find ANY clear horizontal line using _find_clear_xy
                        fallback_y_frac = fb_y_frac_raw if fb_y is not None else (q_bot_frac2 if q_bot_frac2 < 0.9 else 0.9)
                        fb_x_final, fb_y_final = _find_clear_xy(
                            gray, img_w, img_h, pdf_w, pdf_h, fallback_y_frac, False,
                            min_clear_cols=20, required_text_width_px=fb_need_px,
                            excluded_px_rows=page_excluded_px_rows,
                            max_search_delta=0.10,
                        )
                        fb_x_final = min(fb_x_final, pdf_w - fb_text_w_pt - 10)
                        fb_x_final = max(fb_x_final, pdf_w * 0.04)
                        page_used_y_fracs.append(1.0 - fb_y_final / pdf_h)
                        placed = True

                if placed:
                    # ── Final overlap check against ALL drawn items on this page ──
                    # Nudge stamp if it overlaps with any feedback or stamp from
                    # this or earlier questions on the same page.
                    if _pending_stamp is not None and final_stamp_y is not None:
                        FB_FSZ   = int(11 * page_scale)
                        half_h_f = _pending_stamp["half_h_pts"]
                        
                        # First, if feedback was placed for THIS question, add it to rects
                        # so we avoid it just like previous questions' rects.
                        if placed and fb_y_final is not None:
                            page_drawn_rects_y.append((fb_y_final, fb_y_final + FB_FSZ))

                        s_bot_f  = final_stamp_y - half_h_f
                        s_top_f  = final_stamp_y + half_h_f

                        for r_bot, r_top in page_drawn_rects_y:
                            if min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0:
                                below_y_f = r_bot - half_h_f - 8
                                above_y_f = r_top + half_h_f + 8
                                if below_y_f >= half_h_f + 4:
                                    final_stamp_y = below_y_f
                                else:
                                    final_stamp_y = min(above_y_f, pdf_h - half_h_f - 4)
                                # Update our own bounds for the next rect check
                                s_bot_f  = final_stamp_y - half_h_f
                                s_top_f  = final_stamp_y + half_h_f
                                print(f"    ↑ Stamp adjusted to y={final_stamp_y:.0f} to clear rect {r_bot:.0f}-{r_top:.0f}", flush=True)

                        # ── Right-margin fallback ──────────────────────────────────
                        # If the stamp STILL collides after nudging, move it to the
                        # right margin (last 8 % of page width) so it is always
                        # visible and never hidden behind handwritten text.
                        still_collides = any(
                            min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0
                            for r_bot, r_top in page_drawn_rects_y
                        )
                        if still_collides:
                            _pending_stamp["x"] = pdf_w * 0.88
                            print(f"    → Stamp moved to right margin (x={pdf_w * 0.88:.0f}) to avoid collision", flush=True)

                    # Draw stamp exactly once at its final collision-free position
                    if _pending_stamp is not None and final_stamp_y is not None:
                        _draw_marks_stamp(
                            c,
                            _pending_stamp["x"],
                            final_stamp_y,
                            _pending_stamp["marks_obtained"],
                            _pending_stamp["marks_total"],
                            font_name,
                            scale=page_scale,
                        )
                        _pending_stamp = None   # consumed — prevent double draw below
                        page_drawn_rects_y.append((final_stamp_y - half_h_f, final_stamp_y + half_h_f))

                    c.saveState()
                    
                    # Draw a white background box to hide noise/scan lines
                    bg_padding_x = 4
                    bg_padding_y = 4
                    bg_h = fb_num_lines * FB_FONT_SIZE * 1.5 + bg_padding_y * 2
                    bg_w = fb_text_w_pt + bg_padding_x * 2
                    bg_y = fb_y_final - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - bg_padding_y
                    
                    c.setFillColorRGB(1, 1, 1)
                    c.setStrokeColorRGB(1, 1, 1, 0)
                    c.rect(fb_x_final - bg_padding_x, bg_y, bg_w, bg_h, fill=1, stroke=0)
                    
                    c.setFont(font_name, FB_FONT_SIZE)
                    c.setFillColor(red)
                    c.setStrokeColor(red)
                    c.setLineWidth(1.8)
                    
                    _draw_y = fb_y_final
                    for line in fb_text.split('\n'):
                        c.drawString(fb_x_final, _draw_y, line)
                        _draw_y -= FB_FONT_SIZE * 1.5
                        
                    c.setLineWidth(0)
                    
                    _draw_y = fb_y_final
                    for line in fb_text.split('\n'):
                        c.drawString(fb_x_final, _draw_y, line)
                        _draw_y -= FB_FONT_SIZE * 1.5
                        
                    c.restoreState()

            # If no feedback was placed (or this is a continuation page),
            # draw the stamp now — it was deferred and hasn't been drawn yet.
            if _pending_stamp is not None and final_stamp_y is not None:
                _draw_marks_stamp(
                    c,
                    _pending_stamp["x"],
                    final_stamp_y,
                    _pending_stamp["marks_obtained"],
                    _pending_stamp["marks_total"],
                    font_name,
                    scale=page_scale,
                )
                half_h_f = _pending_stamp["half_h_pts"]
                page_drawn_rects_y.append((final_stamp_y - half_h_f, final_stamp_y + half_h_f))
                _pending_stamp = None

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
                    if f_blocks:
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
                        _draw_cross(c, cx, cy, size=random.uniform(55, 85))
                    else:
                        print(f"      ✗ Could not find non-colliding spot for wrong final answer", flush=True)
                else:
                    print(f"      ✗ OCR could not locate '{wrong_final_answer}' on page", flush=True)

        c.showPage()

    c.save()
    doc.close()

    # ── Merge overlay with original PDF ───────────────────────────────────────
    print("  Merging annotations…", flush=True)
    packet.seek(0)
    overlay    = PdfReader(packet)
    out_writer = PdfWriter()
    for i in range(num_pages):
        pg = reader.pages[i]
        if i < len(overlay.pages):
            pg.merge_page(overlay.pages[i])
        out_writer.add_page(pg)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        out_writer.write(f)

    print(f"\n  ✓ Checked copy → {output_path}")
    print(f"{'='*62}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 7 — Checked copy generator")
    parser.add_argument("--pdf",     required=True)
    parser.add_argument("--grading", required=True)
    parser.add_argument("--aligned", required=True)
    parser.add_argument("--output",  required=True)
    parser.add_argument("--ocr",     default=None)
    args = parser.parse_args()

    generate_checked_copy(
        pdf_path      = args.pdf,
        grading_json  = args.grading,
        aligned_json  = args.aligned,
        output_path   = args.output,
        ocr_text_path = args.ocr,
    )
