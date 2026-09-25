FROM python:3.11-slim
WORKDIR /app
# Optimized for Azure B1s 1GB RAM
RUN apt-get update && apt-get install -y wget gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 libxss1 libasound2 libgbm1 libgtk-3-0 curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY solver.py .
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:8000/cron || exit 1
CMD ["uvicorn", "solver:app", "--host", "0.0.0.0", "--port", "8000"]
