# Dockerfile for FastAPI Question Paper Generator
# ---------------------------------------------------
# Base image with Python 3.11 (slim) – small footprint
FROM python:3.11-slim

# Install system packages needed for XeLaTeX and Pandoc
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-latex-extra \
    pandoc \
    wget && \
    rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY . .

# Expose the port FastAPI will listen on (the platform provides $PORT)
EXPOSE 8000

# Default command – uvicorn will read $PORT or fall back to 8000
ENV PORT=${PORT:-8000}
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]
