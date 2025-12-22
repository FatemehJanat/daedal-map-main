FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for geopandas
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Start command - Railway sets PORT env var
CMD uvicorn mapmover:app --host 0.0.0.0 --port ${PORT:-8000}
