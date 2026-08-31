FROM python:3.12-alpine

RUN addgroup -S governor && adduser -S -G governor governor
WORKDIR /app
COPY app.py /app/app.py
COPY policy.json /app/policy.json
USER governor
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)" || exit 1
CMD ["python", "/app/app.py"]
