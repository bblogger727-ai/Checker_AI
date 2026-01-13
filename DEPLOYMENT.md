# Deployment Guide - Agentic Student Evaluator

Complete deployment guide for the AI-powered student management system.

---

## 🏗️ Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │           Load Balancer              │
                    │         (nginx on port 80)           │
                    └─────────────────┬───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
    ┌─────────▼─────────┐   ┌────────▼────────┐   ┌─────────▼─────────┐
    │   /api/*           │   │  /api/setter/*  │   │  /api/mentor/*    │
    │   CheckerAI        │   │    SetterAI     │   │     MentorAI      │
    │   Port 8000        │   │    Port 8001    │   │     Port 8002     │
    └─────────┬──────────┘   └────────┬────────┘   └─────────┬─────────┘
              │                       │                       │
              └───────────────────────┼───────────────────────┘
                                      │
                          ┌───────────▼───────────┐
                          │      PostgreSQL       │
                          │       Port 5432       │
                          └───────────────────────┘
```

---

## 🐳 Docker Deployment (Recommended)

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+
- 4GB RAM minimum
- OpenAI API key

### Quick Deploy

```bash
# 1. Clone repository
git clone https://github.com/GaureshMantri/Agentic_Student_Evaluator.git
cd Agentic_Student_Evaluator

# 2. Create environment file
cat > .env << EOF
OPENAI_API_KEY=sk-your-key-here
SMTP_USER=
SMTP_PASSWORD=
EOF

# 3. Build and start all containers
docker compose up -d --build

# 4. Check status
docker compose ps

# 5. View logs
docker compose logs -f
```

### Services Started

| Service | Container Name | Port | Health Check |
|---------|---------------|------|--------------|
| PostgreSQL | checkerai-db | 5432 | `pg_isready` |
| CheckerAI Backend | checkerai-backend | 8000 | `/health` |
| SetterAI Backend | setterai-backend | 8001 | `/health` |
| MentorAI Backend | mentorai-backend | 8002 | `/health` |
| Frontend | checkerai-frontend | 80 | nginx |

### Verify Deployment

```bash
# Check all containers are running
docker ps

# Test each service
curl http://localhost/health           # Frontend (via nginx)
curl http://localhost:8000/health      # CheckerAI
curl http://localhost:8001/health      # SetterAI
curl http://localhost:8002/health      # MentorAI

# Access Swagger docs
open http://localhost:8000/docs        # CheckerAI API
open http://localhost:8001/docs        # SetterAI API
open http://localhost:8002/docs        # MentorAI API
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# === REQUIRED ===
OPENAI_API_KEY=sk-...

# === DATABASE (auto-configured in Docker) ===
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/checkerai

# === EMAIL (Optional - for MentorAI reports) ===
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FROM_EMAIL=your_email@gmail.com
FROM_NAME=Student Evaluator

# === JWT (Future use) ===
JWT_SECRET_KEY=your-secret-key-here
```

### Gmail App Password Setup

For email functionality:
1. Go to Google Account → Security → 2-Step Verification
2. At the bottom, select "App passwords"
3. Generate a new app password for "Mail"
4. Use this password in `SMTP_PASSWORD`

---

## 🔄 Scaling with Docker Compose

### Horizontal Scaling

```yaml
# docker-compose.override.yml
services:
  checker-backend:
    deploy:
      replicas: 3
  
  setter-backend:
    deploy:
      replicas: 2
  
  mentor-backend:
    deploy:
      replicas: 2
```

### With Load Balancer

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
```

---

## ☸️ Kubernetes Deployment

### Prerequisites
- Kubernetes cluster (EKS, GKE, AKS, or local)
- kubectl configured
- Helm 3.x (optional)

### Deployment Steps

1. **Create namespace**
```bash
kubectl create namespace student-evaluator
```

2. **Create secrets**
```bash
kubectl create secret generic api-keys \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=SMTP_PASSWORD=... \
  -n student-evaluator
```

3. **Apply manifests**
```bash
kubectl apply -f k8s/ -n student-evaluator
```

### Sample Kubernetes Manifest

```yaml
# k8s/checker-backend.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checker-backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: checker-backend
  template:
    metadata:
      labels:
        app: checker-backend
    spec:
      containers:
      - name: checker-backend
        image: your-registry/checker-backend:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          value: postgresql://postgres:postgres@postgres:5432/checkerai
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-keys
              key: OPENAI_API_KEY
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: checker-backend
spec:
  selector:
    app: checker-backend
  ports:
  - port: 8000
    targetPort: 8000
```

---

## 📊 Monitoring

### Docker Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f checker-backend
docker compose logs -f setter-backend
docker compose logs -f mentor-backend
```

### Health Endpoints

Each backend exposes:
- `GET /health` - Returns `{"status": "healthy"}`
- `GET /` - Returns service info

### Database Access

```bash
# Connect to PostgreSQL
docker exec -it checkerai-db psql -U postgres -d checkerai

# List tables
\dt

# Query students
SELECT * FROM mentor_students;
```

---

## 🔧 Maintenance

### Backup Database

```bash
# Backup
docker exec checkerai-db pg_dump -U postgres checkerai > backup.sql

# Restore
cat backup.sql | docker exec -i checkerai-db psql -U postgres checkerai
```

### Update Services

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose down
docker compose up -d --build
```

### Reset Database

```bash
# WARNING: Deletes all data
docker compose down -v
docker compose up -d
```

---

## 🐛 Troubleshooting

### Container won't start

```bash
# Check logs
docker logs <container_name>

# Common issues:
# - Port already in use: Change port in docker-compose.yml
# - Database not ready: Wait for postgres healthcheck
# - Missing env vars: Check .env file
```

### API returns errors

```bash
# Check backend logs
docker compose logs -f checker-backend

# Test database connection
docker exec -it checkerai-db pg_isready -U postgres
```

### Frontend shows blank

```bash
# Check nginx logs
docker logs checkerai-frontend

# Verify nginx config
docker exec checkerai-frontend cat /etc/nginx/conf.d/default.conf
```

### Reset everything

```bash
docker compose down -v --rmi all
docker compose up -d --build
```

---

## 🔒 Security Considerations

1. **API Keys**: Never commit `.env` to git
2. **Database**: Change default PostgreSQL password in production
3. **HTTPS**: Use a reverse proxy (nginx, traefik) with SSL in production
4. **Authentication**: JWT authentication is prepared but not enforced (single admin mode)

---

## 📞 Support

For issues and feature requests, please open an issue on GitHub.
