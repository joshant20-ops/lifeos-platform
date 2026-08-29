from time import monotonic

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

STARTED = monotonic()

app = FastAPI(
    title="LifeOS Energy",
    version="0.1.0-dev",
)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LifeOS Energy</title>
  <style>
    body {
      margin: 0;
      background: #0d1117;
      color: #e6edf3;
      font-family: system-ui, sans-serif;
    }
    main {
      width: min(900px, calc(100% - 32px));
      margin: 50px auto;
    }
    .card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 16px;
      padding: 24px;
    }
    .healthy {
      color: #3fb950;
      font-weight: 700;
    }
  </style>
</head>
<body>
  <main>
    <h1>LifeOS Energy</h1>
    <section class="card">
      <p class="healthy">Foundation is running</p>
      <p>Version: 0.1.0-dev</p>
      <p>Next: configuration, logging and energy simulation.</p>
    </section>
  </main>
</body>
</html>
"""


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "healthy",
        "application": "LifeOS Energy",
        "version": "0.1.0-dev",
        "uptime_seconds": round(monotonic() - STARTED, 1),
    }


@app.get("/api/status")
async def status() -> dict[str, object]:
    return {
        "application": "LifeOS Energy",
        "version": "0.1.0-dev",
        "modules": {
            "foundation": "ready",
            "configuration": "planned",
            "simulation": "planned",
            "optimiser": "planned",
        },
    }
