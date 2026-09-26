#!/usr/bin/env python3
"""OpenAI-compatible OpenHands -> LifeOS local-AI gateway.

Runs on the always-on Pi. It acquires/releases the existing Tower compute lease,
wakes Tower through the existing AI broker path when required, and proxies the
accepted OpenHands models to Tower Ollama. No inference runs on the Pi.
"""
from __future__ import annotations
import importlib.util, json, pathlib, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("lifeos_ai_broker", ROOT/"governor"/"ai_broker.py")
BROKER=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(BROKER)
MODEL="gpt-oss:20b"
# Keep the previous model available solely as a one-line settings rollback.
ALLOWED_MODELS={MODEL,"qwen2.5-coder:7b-instruct"}
UPSTREAM="http://192.168.0.201:11434/v1"
PORT=18114

def ready():
    try:
        with urlopen("http://192.168.0.201:11434/api/tags", timeout=2) as r: return r.status==200
    except Exception: return False

def ensure_tower():
    BROKER._publish_lease("active")
    if ready(): return
    BROKER._wake_local_ai()
    deadline=time.monotonic()+BROKER.WAKE_TIMEOUT
    while time.monotonic()<deadline:
        time.sleep(3); BROKER._publish_lease("active")
        if ready(): return
    raise RuntimeError("Tower Ollama did not become ready after Wake-on-LAN")

class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self, fmt, *args): print(fmt%args, flush=True)
    def sendj(self, code, obj):
        b=json.dumps(obj,separators=(",",":")).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path=="/health": return self.sendj(200,{"status":"ok","model":MODEL})
        if self.path=="/v1/models": return self.sendj(200,{"object":"list","data":[{"id":m,"object":"model","owned_by":"lifeos"} for m in sorted(ALLOWED_MODELS)]})
        self.sendj(404,{"error":{"message":"not found"}})
    def do_POST(self):
        if self.path!="/v1/chat/completions": return self.sendj(404,{"error":{"message":"not found"}})
        n=int(self.headers.get("Content-Length","0")); body=self.rfile.read(n)
        try:
            payload=json.loads(body); requested=str(payload.get("model",""))
            upstream_model=requested.removeprefix("openai/")
            if upstream_model not in ALLOWED_MODELS: raise ValueError("model not allowed")
            payload["model"]=upstream_model
            ensure_tower()
            req=Request(UPSTREAM+"/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
            with urlopen(req,timeout=max(BROKER.HTTP_TIMEOUT,600)) as r:
                data=r.read(); self.send_response(r.status)
                self.send_header("Content-Type",r.headers.get("Content-Type","application/json"))
                self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        except (HTTPError,URLError,ValueError,RuntimeError) as e:
            self.sendj(502,{"error":{"message":str(e)}})
        finally: BROKER._publish_lease("released",required=False)

if __name__=="__main__":
    ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
