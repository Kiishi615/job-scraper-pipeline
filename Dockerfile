# --- Stage: Base ---
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Install Xvfb for virtual display (keeps headless=False for stealth)
RUN apt-get update && \
    apt-get install -y --no-install-recommends xvfb && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies FIRST (so playwright CLI is available)
COPY requirements_docker.txt .
RUN pip install --no-cache-dir -r requirements_docker.txt

# NOW install Firefox browser binaries
RUN playwright install firefox

# Copy application code
COPY *.py ./
COPY pipeline.docker.cfg ./pipeline.cfg
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Xvfb creates a virtual display on :99
ENV DISPLAY=:99

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "scheduler.py"]
