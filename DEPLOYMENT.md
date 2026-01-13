# CheckerAI - Deployment Guide

This guide explains Docker, Kubernetes, and how to deploy the CheckerAI application.

---

## 📦 What is Docker & Why Use It?

### The Problem Without Docker
Without Docker, deploying this app requires:
- Installing Python 3.11 with exact dependencies
- Installing poppler-utils for PDF processing
- Installing PostgreSQL and configuring it
- Installing Node.js and building the frontend
- Configuring nginx for serving

**On every server. Every time. Hoping nothing conflicts.**

### How Docker Solves This

Docker packages your app + ALL dependencies into a **container** - a portable, isolated environment that runs the same everywhere.

```
┌─────────────────────────────────────────────────────┐
│                    WITHOUT DOCKER                    │
│                                                      │
│   Your Laptop        Staging Server      Production  │
│   ┌──────────┐       ┌──────────┐       ┌──────────┐│
│   │Python 3.11│       │Python 3.9│       │Python 3.10│
│   │Works! ✓   │       │Fails! ✗  │       │Fails! ✗  ││
│   └──────────┘       └──────────┘       └──────────┘│
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                     WITH DOCKER                      │
│                                                      │
│   Your Laptop        Staging Server      Production  │
│   ┌──────────┐       ┌──────────┐       ┌──────────┐│
│   │Container │       │Container │       │Container ││
│   │Works! ✓  │ ────▶ │Works! ✓  │ ────▶ │Works! ✓  ││
│   └──────────┘       └──────────┘       └──────────┘│
│         Same container image runs EVERYWHERE         │
└─────────────────────────────────────────────────────┘
```

### Our Docker Setup

```
docker-compose.yml orchestrates 3 containers:

┌─────────────────────────────────────────────────────┐
│                  checkerai-frontend                  │
│                    (nginx:80)                        │
│  Serves React app + proxies /api to backend         │
└─────────────────────┬───────────────────────────────┘
                      │ /api/* requests
                      ▼
┌─────────────────────────────────────────────────────┐
│                  checkerai-backend                   │
│                   (uvicorn:8000)                     │
│  FastAPI + OCR + Grading pipeline                   │
└─────────────────────┬───────────────────────────────┘
                      │ SQL queries
                      ▼
┌─────────────────────────────────────────────────────┐
│                   checkerai-db                       │
│                (PostgreSQL:5432)                     │
│  Stores exams, students, all debug data             │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 Docker Setup (Local Development)

### Prerequisites
- Docker Desktop installed ([Download](https://www.docker.com/products/docker-desktop/))

### Quick Start

```bash
# 1. Clone the repository
git clone git@github.com:GaureshMantri/CheckerAI.git
cd CheckerAI

# 2. Create environment file with your API key
cp .env.docker.example .env
# Edit .env and add: OPENAI_API_KEY=your-key-here

# 3. Build and start all containers
docker compose up --build -d

# 4. Access the app
# Frontend: http://localhost
# API Docs: http://localhost:8000/docs
```

### Useful Commands

```bash
# View running containers
docker ps

# View logs (follow mode)
docker compose logs -f

# View specific service logs
docker compose logs backend

# Stop all containers
docker compose down

# Stop and remove volumes (DELETES DATA!)
docker compose down -v

# Rebuild a specific service
docker compose build backend
docker compose up -d backend

# Access PostgreSQL shell
docker exec -it checkerai-db psql -U postgres -d checkerai

# Access backend container shell
docker exec -it checkerai-backend bash
```

---

## ☸️ Kubernetes (K8s) - For Production Scaling

### Why Kubernetes?

Docker Compose runs everything on **1 machine**. For production, you need:

| Challenge | Kubernetes Solution |
|-----------|---------------------|
| High traffic | Run multiple backend replicas |
| Server crashes | Auto-restart failed containers |
| Zero downtime deploys | Rolling updates |
| Resource limits | CPU/memory quotas per container |
| Load balancing | Automatic across replicas |

### K8s Architecture for CheckerAI

```
                    ┌─────────────────────┐
                    │   Load Balancer     │
                    │  (Cloud Provider)   │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Frontend Pod 1  │  │ Frontend Pod 2  │  │ Frontend Pod 3  │
│    (nginx)      │  │    (nginx)      │  │    (nginx)      │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  Backend Service  │
                    │  (Load Balancer)  │
                    └─────────┬─────────┘
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Backend Pod 1  │  │  Backend Pod 2  │  │  Backend Pod 3  │
│   (FastAPI)     │  │   (FastAPI)     │  │   (FastAPI)     │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │ PostgreSQL (PVC)  │
                    │ or Cloud DB (RDS) │
                    └───────────────────┘
```

### K8s Setup (Coming Soon)

For production K8s deployment, you'll need:

1. **Container Registry** - Push Docker images to:
   - Docker Hub
   - Google Container Registry (GCR)
   - Amazon ECR

2. **K8s Cluster** - Options:
   - Google GKE (easiest)
   - Amazon EKS
   - DigitalOcean Kubernetes
   - Self-hosted (harder)

3. **K8s Manifests** - YAML files for:
   - Deployments (how many replicas)
   - Services (networking)
   - Ingress (external access)
   - Secrets (API keys)
   - PersistentVolumeClaims (database storage)

---

## 📊 Scaling Considerations

### Current Bottleneck

The grading pipeline is **I/O bound** (waiting for OpenAI API):

```
Upload PDF → OCR (GPT-4o) → Align (GPT-4.1) → Grade (GPT-4.1) → PDF
            ~3-5 sec        ~2-3 sec         ~2-3 sec
            
Total: ~8-12 seconds per student paper
```

### Scaling Strategy

1. **Horizontal Pod Autoscaling**
   - Scale backend pods based on CPU/request count
   - Handle multiple papers simultaneously

2. **Background Job Queue** (Future)
   - Add Celery + Redis for async processing
   - Upload returns immediately, grading happens in background
   - Webhook/polling for status

3. **Managed Database**
   - Move PostgreSQL to Cloud SQL/RDS
   - Automated backups, high availability

---

## 🔐 Production Checklist

Before deploying to production:

- [ ] Change default PostgreSQL password
- [ ] Set strong JWT_SECRET_KEY
- [ ] Enable HTTPS (SSL certificate)
- [ ] Add rate limiting to API
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Configure backup for database
- [ ] Add health check endpoints
- [ ] Set resource limits in K8s

---

## 📁 File Structure

```
CheckerAI/
├── CheckerAI - Backend/
│   ├── Dockerfile           # Backend container definition
│   ├── app/
│   │   ├── api/             # FastAPI routes
│   │   ├── services/        # Business logic (OCR, grading)
│   │   ├── core/            # Database, auth config
│   │   └── models.py        # SQLAlchemy models
│   └── requirements.txt
│
├── frontend/
│   ├── Dockerfile           # Multi-stage React build
│   ├── nginx.conf           # SPA routing + API proxy
│   └── src/
│
├── docker-compose.yml       # Local development orchestration
├── .env                     # Environment variables (not in git)
└── .env.docker.example      # Template for .env
```

---

## 🆘 Troubleshooting

### Container won't start
```bash
docker compose logs backend  # Check error messages
```

### Database connection error
```bash
# Ensure postgres is healthy first
docker ps  # Check STATUS column
docker compose restart postgres
```

### Changes not reflecting
```bash
# Rebuild the container
docker compose build backend --no-cache
docker compose up -d backend
```

### Reset everything
```bash
docker compose down -v  # Removes volumes (DATA LOSS!)
docker compose up --build -d
```
