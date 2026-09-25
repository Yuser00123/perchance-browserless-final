FROM python:3.11-slim

WORKDIR /app

# Install chromium + deps for SeleniumBase UC
RUN apt-get update && apt-get install -y \
    wget gnupg curl \
    chromium chromium-driver \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libasound2 libcups2 libdrm2 libxdamage1 libxkbcommon0 libxcomposite1 libxrandr2 libgbm1 \
    libpango-1.0-0 libgtk-3-0 libxfixes3 libxext6 libx11-6 libglib2.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    fonts-liberation libappindicator3-1 xdg-utils xvfb \
    && rm -rf /var/lib/apt/lists/*

# Check chromium
RUN which chromium && chromium --version || echo "chromium not found, trying chromium-browser" && which chromium-browser && chromium-browser --version || echo "try google-chrome" && which google-chrome || echo "no chrome found"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY solver.py .

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:8000/cron || exit 1

CMD ["uvicorn", "solver:app", "--host", "0.0.0.0", "--port", "8000"]
