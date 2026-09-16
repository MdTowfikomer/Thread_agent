FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# Copy backend application package
COPY backend/app ./backend/app

# Set Python path to /app/backend so app modules resolve cleanly
ENV PYTHONPATH=/app/backend

WORKDIR /app/backend

# Dedicated Discord Gateway Worker Entrypoint
CMD ["python", "-m", "app.channels.run_gateway"]
