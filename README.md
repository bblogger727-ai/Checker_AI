# CheckerAI - AI Exam Evaluator

An AI-powered exam evaluation system that uses GPT-4 for OCR and intelligent grading of handwritten student answer sheets.

## Features

- **OCR Processing**: Upload handwritten answer sheets (PDF) and extract text using GPT-4o vision
- **Question Schema Builder**: Automatically extract question structure from solution PDFs
- **Model Answer Extraction**: Extract correct answers from solution documents
- **Answer Alignment**: Align student answers to the question schema
- **Hybrid Grading**: 
  - MCQs: Fast fuzzy string matching (free, instant)
  - Descriptive: GPT-4.1 evaluation with detailed feedback
- **PDF Generation**: Convert OCR text back to readable PDFs

## Project Structure

```
CheckerAI/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI endpoints
│   │   │   ├── upload.py           # Upload student PDFs
│   │   │   ├── upload_solution.py  # Upload solution PDFs
│   │   │   ├── align_answers.py    # Align answers to schema
│   │   │   ├── model_answers.py    # Build model answers
│   │   │   └── grade_answers.py    # Grade student answers
│   │   ├── core/
│   │   │   └── openai_client.py    # OpenAI client
│   │   ├── services/         # Business logic
│   │   │   ├── ocr_service.py
│   │   │   ├── answer_parser.py
│   │   │   ├── answer_aligner.py
│   │   │   ├── answer_grader.py
│   │   │   └── model_answer_builder.py
│   │   └── main.py           # FastAPI app
│   ├── tools/                # Utility scripts
│   │   ├── ocr_to_pdf.py     # Generate PDFs from OCR
│   │   └── reocr_page.py     # Re-OCR single pages
│   ├── ocr_outputs/          # OCR text output (gitignored)
│   ├── ocr_pdfs/             # Generated PDFs (gitignored)
│   ├── aligned_outputs/      # Aligned answers (gitignored)
│   ├── grading_results/      # Grading output (gitignored)
│   ├── question_schemas/     # Question schemas (gitignored)
│   └── solution_texts/       # Extracted solutions (gitignored)
└── .gitignore
```

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/CheckerAI.git
   cd CheckerAI/backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your OpenAI API key
   ```

5. **Run the server**
   ```bash
   uvicorn app.main:app --reload
   ```

6. **Access API docs**
   Open http://localhost:8000/docs

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload-answer-pdf` | POST | Upload student answer PDF for OCR |
| `/upload-solution-pdf` | POST | Upload solution PDF to build schema |
| `/build-model-answers` | POST | Extract model answers from solution |
| `/align-student-answers` | POST | Align student answers to schema |
| `/grade-student-answers` | POST | Grade answers and generate report |

## Cost Estimates

| Operation | Model | Cost per Paper |
|-----------|-------|----------------|
| OCR (15 pages) | GPT-4o | ~$0.25 |
| Align Answers | GPT-4.1 | ~$0.08 |
| Grade Descriptive | GPT-4.1 | ~$0.07 |
| Grade MCQs | Fuzzy Match | FREE |
| **Total per student** | | **~$0.40** |

## License

MIT
