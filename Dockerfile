# --- Stage: Base ---
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Install Xvfb for virtual display (keeps headless=False for stealth)
RUN apt-get update && \
    apt-get install -y --no-install-recommends xvfb && \
    rm -rf /var/lib/apt/lists/*

# Install Firefox for Playwright
RUN playwright install firefox

# Install Python dependencies (slim list, not the full 351-line requirements.txt)
COPY requirements_docker.txt .
RUN pip install --no-cache-dir -r requirements_docker.txt

# Copy application code
COPY *.py ./
COPY pipeline.docker.cfg ./pipeline.cfg

# Xvfb creates a virtual display on :99
# The scrapers run with headless=False, thinking they have a real screen
ENV DISPLAY=:99

# Start Xvfb in the background, then run the scheduler
CMD Xvfb :99 -screen 0 1366x768x24 -nolisten tcp -nolisten unix & \
    sleep 2 && \
    python scheduler.py
