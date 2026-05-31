FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install dependencies and curl for healthcheck
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

# Copy application code
COPY bridge.py /app/bridge.py
COPY nut_server.py /app/nut_server.py
COPY i18n/ /app/i18n/
COPY providers/ /app/providers/
COPY nut-snmp/nut_snmp_agent.py /app/nut_snmp_agent.py

EXPOSE 8100
EXPOSE 3493
EXPOSE 161/udp

# Environment variables:
# REPORTING_MODE=nut|snmp|upsd (default: nut)
# NUT_SERVER_PORT - NUT protocol server port (default: 3493)
# SNMP_PORT - SNMP agent port (default: 161)

# Healthcheck: verify API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8100/api/status || exit 1

# Start bridge (handles REPORTING_MODE internally)
CMD ["python", "/app/bridge.py"]
