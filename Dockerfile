FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PCIS_BASE_DIR=/app
ENV PCIS_DOCKER=1

EXPOSE 5555

CMD ["python", "demo/server.py"]
