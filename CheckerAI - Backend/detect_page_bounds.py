#!/usr/bin/env python3
"""
detect_page_bounds.py — Stage 0.5

Detects the actual paper/notebook boundary on each scanned page of a student
answer sheet using OpenCV contour detection.  Saves normalised [0,1] bounding
box coordinates per page so that generate_checked_copy_v2.py can clamp all
annotation x/y coordinates to within the real paper area — avoiding backgrounds,
desk surfaces, adjacent notebook pages, etc.

Algorithm (per page):
  1. Render PDF page at 150 DPI → grayscale image
  2. Bilateral filter  → Canny edge detection
  3. Find all contours → pick the largest closed 4-sided polygon (the page)
  4. Compute bounding box of that polygon, normalise to [0, 1]
  5. Fallback: if no large quad found, use the pixel ink bounding box with
     a small inward margin, or full page if no ink detected.

Output: page_bounds.json
  {
    "1": {"x_min": 0.12, "x_max": 0.88, "y_min": 0.05, "y_max": 0.96},
    "2": {...},
    ...
  }

Usage:
  python3 detect_page_bounds.py --pdf student.pdf --output page_bounds.json
"""

import os
import sys
import json
import argparse
import numpy as np

import fitz  # PyMuPDF
from PIL import Image

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    print("[detect_page_bounds] WARNING: cv2 not installed — falling back to ink-bbox mode", flush=True)


# ── Constants ──────────────────────────────────────────────────────────────────
RENDER_DPI   = 150          # resolution for boundary detection (lower = faster)
INK_THR      = 220          # pixels darker than this are considered "ink"
MIN_AREA_FRAC = 0.15        # quad must cover at least 15% of total page area
MARGIN_FRAC  = 0.02         # safety inward margin added when using fallback


def _render_page_gray(page: fitz.Page, dpi: int = RENDER_DPI) -> np.ndarray:
    """Render a fitz page to a uint8 grayscale numpy array."""
    mat  = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    arr  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr


def _ink_bbox_fallback(gray: np.ndarray, margin: float = MARGIN_FRAC) -> dict:
    """Return the bounding box of all ink pixels, shrunk slightly inward."""
    h, w = gray.shape
    ink_mask = gray < INK_THR
    rows = np.where(ink_mask.any(axis=1))[0]
    cols = np.where(ink_mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}
    r0, r1 = float(rows[0]) / h,  float(rows[-1]) / h
    c0, c1 = float(cols[0]) / w,  float(cols[-1]) / w
    # Apply margin (expand slightly beyond ink to allow annotation in margins)
    return {
        "x_min": max(0.0, c0 - margin),
        "x_max": min(1.0, c1 + margin),
        "y_min": max(0.0, r0 - margin),
        "y_max": min(1.0, r1 + margin),
    }


def _detect_bounds_cv2(gray: np.ndarray) -> dict | None:
    """
    Use OpenCV to find the largest 4-sided polygon (the paper boundary).
    Returns normalised bounding box dict, or None if detection fails.
    """
    h, w = gray.shape

    # Preprocessing
    blur  = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
    edges = cv2.Canny(blur, threshold1=30, threshold2=100)
    # Dilate edges slightly to close small gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges  = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Sort by area descending
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    page_area = h * w
    best_quad = None

    for cnt in contours[:10]:  # check only top-10 largest contours
        area = cv2.contourArea(cnt)
        if area < MIN_AREA_FRAC * page_area:
            break  # sorted, so remaining are all smaller

        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx  = cv2.approxPolyDP(cnt, epsilon, True)

        if len(approx) == 4:
            best_quad = approx
            break

    if best_quad is None:
        return None

    pts = best_quad.reshape(-1, 2)  # shape (4, 2)
    x0  = float(pts[:, 0].min()) / w
    x1  = float(pts[:, 0].max()) / w
    y0  = float(pts[:, 1].min()) / h
    y1  = float(pts[:, 1].max()) / h

    # Sanity clamp
    return {
        "x_min": max(0.0, x0),
        "x_max": min(1.0, x1),
        "y_min": max(0.0, y0),
        "y_max": min(1.0, y1),
    }


def detect_page_bounds(pdf_path: str) -> dict:
    """
    Main entry point.  Returns a dict mapping page_number (str) -> bounds dict.
    """
    doc    = fitz.open(pdf_path)
    result = {}

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page     = doc[page_idx]
        gray     = _render_page_gray(page)

        bounds = None

        if _CV2_AVAILABLE:
            bounds = _detect_bounds_cv2(gray)
            method = "contour"

        if bounds is None:
            bounds = _ink_bbox_fallback(gray)
            method = "ink_bbox"

        result[str(page_num)] = bounds
        print(
            f"  P{page_num:2d}  [{method}]  "
            f"x:[{bounds['x_min']:.3f}, {bounds['x_max']:.3f}]  "
            f"y:[{bounds['y_min']:.3f}, {bounds['y_max']:.3f}]",
            flush=True,
        )

    doc.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Detect paper boundary per page in a student PDF scan.")
    parser.add_argument("--pdf",    required=True, help="Path to student answer-sheet PDF")
    parser.add_argument("--output", required=True, help="Output page_bounds.json path")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("  STAGE 0.5 — Detecting Page Boundaries")
    print(f"{'='*60}")
    print(f"  PDF    : {args.pdf}")
    print(f"  Output : {args.output}")

    bounds = detect_page_bounds(args.pdf)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(bounds, f, indent=2)

    print(f"\n  ✓ Saved page_bounds.json → {args.output}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
