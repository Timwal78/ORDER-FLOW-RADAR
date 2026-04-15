# Order Flow Radar™ — Production Dockerfile
# ScriptMasterLabs™
# Build Timestamp: 2026-04-15 10:25 AM

FROM python:3.12-slim

# Set build-time environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for runtime logs/data
RUN mkdir -p signal_data

# Expose the dashboard port
EXPOSE 8080

# Command to run the institutional orchestrator
CMD ["python", "main.py"]
