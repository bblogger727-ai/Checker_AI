# CheckerAI - Backend Pipeline

Automated exam grading pipeline using GPT-4o for CA exam papers.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run complete pipeline
python run_pipeline.py \
    --qp "path/to/question_paper.pdf" \
    --sa "path/to/solution_answer.pdf" \
    --as "path/to/student_answer.pdf"
```

## Pipeline Stages

The pipeline runs 6 sequential stages:

1. **Schema Generation** - Extracts questions and marks from Question Paper
2. **Model Answer Extraction** - Extracts solutions from Solution PDF (uses Tesseract OCR for tables)
3. **Student OCR** - OCR handwritten student answer sheets
4. **Alignment** - Maps student answers to schema questions
5. **Grading** - Compares student vs model answers (image-based grading for practical questions)
6. **Report Generation** - Creates PDF report with scores and feedback

## Usage

### Basic Usage

```bash
python run_pipeline.py --qp QP.pdf --sa SA.pdf --as AS.pdf
```

### Custom Output Directory

```bash
python run_pipeline.py \
    --qp "QP 8 - 2764.pdf" \
    --sa "SA 8.pdf" \
    --as "AS 8 NORMAL Handwriting + Practical 2764.pdf" \
    --output ./exam_results
```

## Output Files

After pipeline completion, check these directories:

- **`grading_results/`**
  - `grading_final.json` - Complete grading data with scores/feedback
  - `grading_report.pdf` - PDF report for review

- **`pipeline_output/`**
  - `schema.json` - Question schema with marks
  - `schema_with_answers.json` - Schema + model answers
  - `aligned_answers.json` - Student answers mapped to questions

- **`pipeline_temp/`** (for debugging)
  - `1_qp_text.txt` - Extracted Question Paper text
  - `2_sa_text.txt` - Extracted Solution text
  - `3_ocr_output.txt` - Student OCR output

## Core Services

All pipeline logic is in reusable service modules:

- `app/services/solution_schema_builder.py` - Schema generation
- `app/services/model_answer_builder.py` - Model answer extraction
- `app/services/ocr_service.py` - Student answer OCR
- `app/services/answer_parser.py` - OCR text parsing
- `app/services/answer_aligner.py` - Answer alignment
- `app/services/answer_grader.py` - Grading logic (text + image-based)
- `app/services/prompts.py` - All LLM prompts

## Optional: PDF Annotation

To annotate student PDFs with marks/feedback:

```bash
python annotate_pdf.py
```

(Requires `final_coordinates.json` from coordinate extraction)

## Requirements

- Python 3.8+
- OpenAI API key (set in `.env`)
- Tesseract OCR installed
- Dependencies in `requirements.txt`

## Environment Setup

Create `.env` file:

```
OPENAI_API_KEY=your_api_key_here
```

## Examples

### Example 1: Grade CA Inter Taxation Exam
```bash
python run_pipeline.py \
    --qp "CA_Inter_Tax_QP.pdf" \
    --sa "CA_Inter_Tax_SA.pdf" \
    --as "Student_Answer_Sheet.pdf"
```

### Example 2: Grade Multiple Exams
```bash
# Exam 1
python run_pipeline.py --qp QP1.pdf --sa SA1.pdf --as Student1.pdf

# Exam 2
python run_pipeline.py --qp QP2.pdf --sa SA2.pdf --as Student2.pdf
```

## Troubleshooting

- **Schema generation fails**: Check if QP PDF has selectable text
- **OCR quality poor**: Ensure student PDF resolution is at least 200 DPI
- **API timeout**: Check OpenAI API key and rate limits
- **Missing model answers**: Verify SA PDF contains complete solutions

## Architecture

```
run_pipeline.py (CLI)
    ↓
app/services/
    ├── solution_schema_builder.py
    ├── model_answer_builder.py
    ├── ocr_service.py
    ├── answer_parser.py
    ├── answer_aligner.py
    ├── answer_grader.py
    └── prompts.py
    ↓
Output:
    ├── grading_results/grading_final.json
    └── grading_results/grading_report.pdf
```
