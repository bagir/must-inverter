# Multi-stage build for UPS Monitoring System

# Build stage
FROM python:3.10-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.10-slim as runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sudo \
    usbutils \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r upsmonitor && useradd -r -g upsmonitor upsmonitor

# Create app directory
WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder /root/.local /home/upsmonitor/.local

# Copy application files
COPY --chown=upsmonitor:upsmonitor . .

# Ensure the user has access to serial devices
RUN usermod -a -G dialout upsmonitor

# Create log directory
RUN mkdir -p /var/log/ups && chown upsmonitor:upsmonitor /var/log/ups

# Switch to non-root user
USER upsmonitor

# Add local bin to PATH
ENV PATH=/home/upsmonitor/.local/bin:$PATH

# Expose web interface port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:8080/api/health', timeout=5)"

# Default command
CMD ["python3", "mustmon.py", "/dev/ttyUSB0"]
