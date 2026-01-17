# Multi-stage build for UPS Monitoring System
# Optimized for size and build caching

# ============================================================================
# Build stage - for compiling dependencies
# ============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies to user directory
RUN pip install --no-cache-dir --user --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --user -r requirements.txt

# ============================================================================
# Runtime stage - minimal image
# ============================================================================
FROM python:3.11-slim as runtime

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    usbutils \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with home directory
RUN groupadd -r upsmonitor && \
    useradd -r -g upsmonitor -m -d /home/upsmonitor upsmonitor

# Create necessary directories
RUN mkdir -p /app /var/log/ups /etc/ups_monitor && \
    chown -R upsmonitor:upsmonitor /app /var/log/ups /etc/ups_monitor

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder --chown=upsmonitor:upsmonitor /root/.local /home/upsmonitor/.local

# Copy application files
COPY --chown=upsmonitor:upsmonitor mustmon.py ./
COPY --chown=upsmonitor:upsmonitor config.yaml.example ./config.yaml.example

# Ensure the user has access to serial devices
RUN usermod -a -G dialout upsmonitor

# Add local Python bin to PATH
ENV PATH=/home/upsmonitor/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER upsmonitor

# Expose web interface port (default 8080, configurable via --web-port)
EXPOSE 8080

# Health check - verify web interface is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health', timeout=5).read()"

# Default serial port (can be overridden via docker run -e or --device)
ENV UPS_SERIAL_PORT=/dev/ttyUSB0

# Default command - uses environment variable for serial port
# Can be overridden: docker run ... python3 mustmon.py --config /path/to/config.yaml
CMD python3 mustmon.py ${UPS_SERIAL_PORT}
