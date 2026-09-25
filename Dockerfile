FROM python:3.11-slim

WORKDIR /app

# No need for chromium - Browserless runs browser remotely
# Only need curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY solver.py .

ENV PORT=8000
ENV HOST=0.0.0.0

# Healthcheck for Render cron
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 CMD curl -f http://localhost:8000/cron || exit 1

CMD ["uvicorn", "solver:app", "--host", "0.0.0.0", "--port", "8000"]
