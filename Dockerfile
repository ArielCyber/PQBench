# Dockerfile
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libpcap for scapy capture; tshark for splitting; iproute2/net-tools are handy for debugging.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tshark tcpdump iproute2 net-tools ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# FastAPI + scapy
RUN pip install --no-cache-dir fastapi uvicorn[standard] scapy requests

# App
WORKDIR /app
COPY sniffer_service.py /app/sniffer_service.py

# Where captures land (mount this as a volume)
VOLUME ["/output"]

# Default env (you can override in compose)
ENV OUTPUT_ROOT=/output \
    CF_FETCH_ON_START=true

# Run the API
CMD ["uvicorn", "sniffer_service:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "10"]
