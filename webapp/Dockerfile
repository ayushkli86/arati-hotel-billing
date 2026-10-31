# Dockerfile for Arati Hotel Webapp on Render
# Build context: ./webapp (set via rootDir in Render)
FROM python:3.11-slim

# Install system dependencies for WeasyPrint (Debian 13 Trixie package names)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy webapp source code (build context IS webapp, so copy .)
COPY . .

# Expose port
EXPOSE 8080

# Start command - use module path for proper relative imports
CMD ["python", "-m", "uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8080"]