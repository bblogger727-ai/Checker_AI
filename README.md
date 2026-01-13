# 🎓 Agentic Student Evaluator

**AI-Powered Complete Student Management System for CA (Chartered Accountancy) Education**

A comprehensive platform with three integrated AI modules for exam paper generation, automated grading, and student mentoring.

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    AGENTIC STUDENT EVALUATOR                                │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │  SetterAI   │    │  CheckerAI  │    │  MentorAI   │                     │
│  │   📝        │ → │   ✓         │ → │   👨‍🏫        │                     │
│  │  Generate   │    │   Grade     │    │   Track &   │                     │
│  │  Papers     │    │   Papers    │    │   Mentor    │                     │
│  └─────────────┘    └─────────────┘    └─────────────┘                     │
│         │                  │                  │                             │
│         ↓                  ↓                  ↓                             │
│  ┌─────────────────────────────────────────────────────┐                   │
│  │                    PostgreSQL                        │                   │
│  │         Shared Database for All Modules             │                   │
│  └─────────────────────────────────────────────────────┘                   │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Three AI Modules

### 1. 📝 SetterAI - Exam Paper Generator
Generate custom exam papers using AI and question banks.

**Features:**
- Subject & syllabus management
- Question bank with PYQs (Previous Year Questions)
- Weighted random question selection
- AI-generated questions when bank is insufficient
- Paper templates (Full test, Portionwise, etc.)
- Solution auto-generation
- Publish to CheckerAI for grading

### 2. ✓ CheckerAI - Automated Grading System
AI-powered assessment of handwritten student answer sheets.

**Features:**
- PDF upload of solution papers
- Automatic schema extraction (questions + marking scheme)
- Student paper OCR using GPT-4 Vision
- Answer alignment to questions
- AI grading with detailed justifications
- Downloadable grading reports

### 3. 👨‍🏫 MentorAI - Student Progress Tracking
Track student performance and provide personalized mentoring.

**Features:**
- Student profiles with auto-generated IDs
- Exam performance tracking with trends
- 24 predefined problem categories (Health, Mindset, Study, Personal)
- LLM-generated personalized reports
- WhatsApp & Email delivery
- Consultation history tracking
- Pending follow-up alerts

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- OpenAI API Key

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/GaureshMantri/Agentic_Student_Evaluator.git
cd Agentic_Student_Evaluator
```

2. **Create environment file**
```bash
cp .env.docker.example .env
# Edit .env and add your OPENAI_API_KEY
```

3. **Start all services**
```bash
docker compose up -d
```

4. **Access the application**
- **Frontend**: http://localhost
- **CheckerAI API**: http://localhost:8000/docs
- **SetterAI API**: http://localhost:8001/docs
- **MentorAI API**: http://localhost:8002/docs

5. **Login**
- Username: `RuchaSarda`
- Password: `CA@Rucha`

---

## 🐳 Docker Services

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| Frontend | checkerai-frontend | 80 | React SPA with Nginx |
| CheckerAI | checkerai-backend | 8000 | Grading API |
| SetterAI | setterai-backend | 8001 | Paper Generation API |
| MentorAI | mentorai-backend | 8002 | Mentoring API |
| Database | checkerai-db | 5432 | PostgreSQL |

---

## 📁 Project Structure

```
Agentic_Student_Evaluator/
├── CheckerAI - Backend/       # Grading system backend
│   ├── app/
│   │   ├── api/               # REST endpoints
│   │   ├── services/          # OCR, grading, PDF generation
│   │   └── core/              # Database, OpenAI client
│   └── Dockerfile
│
├── SetterAI - Backend/        # Paper generation backend
│   ├── app/
│   │   ├── api/               # Subjects, questions, templates, papers
│   │   └── services/          # Paper & solution generators
│   └── Dockerfile
│
├── MentorAI - Backend/        # Mentoring system backend
│   ├── app/
│   │   ├── api/               # Students, problems, consultations
│   │   └── services/          # Report generation, email, WhatsApp
│   └── Dockerfile
│
├── frontend/                  # React SPA
│   ├── src/
│   │   ├── pages/             # Dashboard, Setter, Mentor, etc.
│   │   └── services/          # API clients
│   ├── nginx.conf             # Reverse proxy config
│   └── Dockerfile
│
├── docker-compose.yml         # Full stack orchestration
└── .env                       # Environment variables
```

---

## 🔧 Environment Variables

```env
# Required
OPENAI_API_KEY=sk-...

# Optional (for MentorAI email)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FROM_EMAIL=your_email@gmail.com
FROM_NAME=Student Evaluator
```

---

## 📊 Workflow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE WORKFLOW                                  │
└──────────────────────────────────────────────────────────────────────────┘

1. PAPER CREATION (SetterAI)
   ├── Add subjects with syllabus
   ├── Import question bank (PYQs)
   ├── Create paper template
   ├── Generate paper with AI
   ├── Review & edit questions
   ├── Generate solution
   └── Publish to CheckerAI

2. EXAM GRADING (CheckerAI)
   ├── Solution PDF uploaded
   ├── AI extracts marking schema
   ├── Students take exam
   ├── Upload student answer PDFs
   ├── OCR extracts handwritten text
   ├── AI grades with justifications
   └── Auto-links to MentorAI

3. STUDENT MENTORING (MentorAI)
   ├── Student profiles auto-created
   ├── Performance tracked over time
   ├── Mentor selects problems
   ├── AI generates personalized report
   ├── Report sent via WhatsApp/Email
   └── Follow-ups tracked
```

---

## 💰 Cost Estimates (OpenAI API)

| Operation | Model | Est. Cost |
|-----------|-------|-----------|
| Paper Generation | GPT-4.1 | ~$0.02/paper |
| Schema Extraction | GPT-4 Vision | ~$0.03/page |
| Student Paper OCR | GPT-4 Vision | ~$0.03/page |
| Grading | GPT-4.1 | ~$0.02/paper |
| Mentor Report | GPT-4.1 | ~$0.02/report |

**Typical per-student cost**: ~$0.10 (5-page paper)

---

## 🛠️ Development

### Run locally without Docker

```bash
# Backend (each in separate terminal)
cd "CheckerAI - Backend" && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd "SetterAI - Backend" && pip install -r requirements.txt && uvicorn app.main:app --port 8001
cd "MentorAI - Backend" && pip install -r requirements.txt && uvicorn app.main:app --port 8002

# Frontend
cd frontend && npm install && npm run dev
```

### Rebuild after changes

```bash
docker compose down
docker compose up --build -d
```

---

## 📄 License

MIT License - See LICENSE file for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

---

**Built with ❤️ for CA Education**
