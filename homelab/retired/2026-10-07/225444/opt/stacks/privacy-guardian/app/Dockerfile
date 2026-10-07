FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/
COPY templates /app/templates
COPY brokers.csv /app/brokers.csv
COPY config.yaml /app/config.yaml

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "app.py"]
