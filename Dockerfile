FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

ENV PCIS_BASE_DIR=/app
ENV PCIS_DOCKER=1
ENV PCIS_DEMO_MODE=1

EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5555/api/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
