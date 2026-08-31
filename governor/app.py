#!/usr/bin/env python3
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STARTED = time.time()
PORT = int(os.environ.get("GOVERNOR_PORT", "8787"))
POLICY = os.environ.get("PROVIDER_POLICY", "cloud-primary-offline-fallback")
CLOUD_HEALTH_URL = os.environ.get("CLOUD_HEALTH_URL", "https://api.openai.com/")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://z97:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct")
TIMEOUT = float(os.environ.get("PROVIDER_HEALTH_TIMEOUT", "2.0"))


def probe(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "lifeos-governor/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, int(getattr(r, "status", 200))
    except urllib.error.HTTPError as exc:
        # Authentication/authorization responses still prove cloud reachability.
        return True, int(exc.code)
    except Exception as exc:
        return False, exc.__class__.__name__


def state():
    cloud_ok, cloud_detail = probe(CLOUD_HEALTH_URL)
    ollama_ok, ollama_detail = probe(f"{OLLAMA_BASE_URL}/api/tags")
    selected = "codex-cloud" if cloud_ok else ("ollama-z97" if ollama_ok else "none")
    return {
        "service": "lifeos-governor",
        "version": 1,
        "uptime_seconds": int(time.time() - STARTED),
        "policy": POLICY,
        "selected_provider": selected,
        "primary": {"provider": "codex-cloud", "healthy": cloud_ok, "detail": cloud_detail},
        "fallback": {
            "provider": "ollama-z97",
            "healthy": ollama_ok,
            "detail": ollama_detail,
            "model": OLLAMA_MODEL,
            "base_url": OLLAMA_BASE_URL,
        },
        "execution_policy": "gated-control-plane-only",
        "fail_closed": selected == "none",
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        data = json.dumps(payload, sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/health", "/state"):
            payload = state()
            code = 200 if payload["selected_provider"] != "none" else 503
            self._json(code, payload)
        else:
            self._json(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        print("governor", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    if POLICY != "cloud-primary-offline-fallback":
        raise SystemExit("unsupported PROVIDER_POLICY")
    print(f"lifeos-governor listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
