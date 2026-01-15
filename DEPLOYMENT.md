# Deployment Guide

This guide covers deploying the AI-powered User Management API to various environments.

## Prerequisites

- Python 3.10+
- PostgreSQL 13+
- Node.js 18+ (for frontend)
- Ollama (for AI features)
- Redis (optional, for distributed caching)

## Quick Start (Development)

### 1. Clone the Repository

```bash
git clone <repository-url>
cd FastAPI_Python_ReactTalon_PostGres
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the project root:

```env
# Database Configuration
DATABASE_URL=postgresql://username:password@localhost:5432/user_management

# Environment
ENVIRONMENT=development

# Ollama AI Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_API_KEY=your-api-key
OLLAMA_MODEL=llama3.2

# Redis (optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Frontend URL (for production CORS)
FRONTEND_URL=http://localhost:3000
```

### 4. Database Setup

```bash
# Create PostgreSQL database
createdb user_management

# Tables are created automatically on first run
```

### 5. Start Ollama (for AI features)

```bash
# Pull the model
ollama pull llama3.2

# Start Ollama server (usually runs on port 11434)
ollama serve
```

### 6. Start the Backend

```bash
# Development mode with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Frontend Setup

```bash
cd frontend
npm install
npm start
```

The application will be available at:
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Frontend: http://localhost:3000

---

## Production Deployment

### Environment Variables for Production

```env
# Production database
DATABASE_URL=postgresql://produser:securepassword@db.example.com:5432/user_management_prod

# Production environment
ENVIRONMENT=production

# AI Configuration
OLLAMA_BASE_URL=http://ollama.internal:11434
OLLAMA_API_KEY=production-api-key
OLLAMA_MODEL=llama3.2

# Redis for distributed caching
REDIS_HOST=redis.example.com
REDIS_PORT=6379
REDIS_DB=0

# CORS for production frontend
FRONTEND_URL=https://app.example.com
```

### Docker Deployment

#### docker-compose.yml

```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/user_management
      - ENVIRONMENT=production
      - OLLAMA_BASE_URL=http://ollama:11434
      - OLLAMA_API_KEY=${OLLAMA_API_KEY}
      - OLLAMA_MODEL=llama3.2
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - FRONTEND_URL=https://app.example.com
    depends_on:
      - db
      - redis
      - ollama
    volumes:
      - ./uploads:/app/uploads
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=user_management
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  postgres_data:
  ollama_data:
```

#### Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8000

# Start application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Frontend Dockerfile

```dockerfile
FROM node:18-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

#### Frontend nginx.conf

```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Deploy with Docker Compose

```bash
# Build and start all services
docker-compose up -d --build

# View logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

---

## Database Management

### Backup

```bash
# Backup database
pg_dump -U postgres user_management > backup.sql

# Docker backup
docker-compose exec db pg_dump -U postgres user_management > backup.sql
```

### Restore

```bash
# Restore database
psql -U postgres user_management < backup.sql

# Docker restore
cat backup.sql | docker-compose exec -T db psql -U postgres user_management
```

### Migrations

Currently, tables are created automatically via SQLAlchemy on startup. For production, consider using Alembic for migrations:

```bash
# Initialize Alembic
alembic init migrations

# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## Performance Tuning

### PostgreSQL Configuration

```sql
-- For production, adjust these in postgresql.conf
shared_buffers = 256MB
effective_cache_size = 768MB
work_mem = 16MB
maintenance_work_mem = 128MB
max_connections = 100
```

### Connection Pooling

The application uses SQLAlchemy connection pooling. For production:

```python
# In database.py, production settings:
pool_size=20           # Base number of connections
max_overflow=10        # Additional connections when needed
pool_timeout=30        # Wait time for connection
pool_recycle=3600      # Recycle connections hourly
pool_pre_ping=True     # Test connections before use
```

### Redis Caching

For high-traffic deployments, configure Redis:

```env
REDIS_HOST=redis.example.com
REDIS_PORT=6379
REDIS_DB=0
```

The cache stores AI query results with 24-hour TTL.

---

## Monitoring

### Health Check Endpoint

```bash
# Check API health
curl http://localhost:8000/health
```

Response includes:
- Database connectivity status
- File system access status
- Connection pool statistics

### Logging

Application logs are written to stdout. In production, configure log aggregation:

```bash
# View logs
docker-compose logs -f backend

# With timestamps
docker-compose logs -f --timestamps backend
```

---

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   ```
   [ERROR] DATABASE_URL not set in .env file
   ```
   Solution: Ensure `.env` file exists with valid DATABASE_URL

2. **AI Service Unavailable**
   ```
   AI service error: Connection refused
   ```
   Solution: Ensure Ollama is running (`ollama serve`)

3. **File Upload Fails**
   ```
   Failed to save uploaded file
   ```
   Solution: Check `uploads/` directory exists and has write permissions

4. **Redis Connection Failed**
   ```
   Redis not available: Connection refused
   ```
   Solution: Redis is optional - the app falls back to file-based caching

### Debug Mode

Enable SQL logging in development:

```env
ENVIRONMENT=development
```

This sets `echo=True` for SQLAlchemy to log all SQL queries.

---

## Security Checklist

- [ ] Use HTTPS in production
- [ ] Set strong DATABASE_URL password
- [ ] Configure CORS with specific frontend URL
- [ ] Keep Ollama API key secure
- [ ] Regularly backup database
- [ ] Monitor for unusual activity
- [ ] Keep dependencies updated
