#!/usr/bin/env python3
"""Wake-aware stable AI endpoint on the always-on Pi; Tower WoL remains controller-owned."""
from __future__ import annotations
import importlib.util, json, os, pathlib, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("lifeos_ai_broker",ROOT/"governor"/"ai_broker.py")
BROKER=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(BROKER)
MODEL="gpt-oss:20b"
ALLOWED_MODELS={MODEL,"qwen2.5-coder:7b-instruct"}
UPSTREAM="http://192.168.0.201:11434"
PORT=18114
WAKE_TIMEOUT=max(30,int(getattr(BROKER,"WAKE_TIMEOUT",180)))
REQUEST_LOCK=threading.Lock()
INFERENCE_PATHS={"/api/generate","/api/chat","/v1/chat/completions"}
def tower_accessible():
    """Read the retained Tower Accessible state; never wake as a health side effect."""
    try:
        cp=subprocess.run(["mosquitto_sub","-h",BROKER.MQTT_HOST,"-C","1","-W","2","-t","lifeos/tower/state"],capture_output=True,text=True,timeout=4,check=True)
        value=json.loads(cp.stdout).get("accessible")
        return value if isinstance(value,bool) else None
    except Exception: return None
def ollama_ready():
    try:
        with urlopen(UPSTREAM+"/api/tags",timeout=2) as r: return r.status==200
    except Exception: return False
def health_status():
    accessible=tower_accessible(); ready=ollama_ready()
    if ready: accessible=True
    if ready: compute,status="ready","ok"
    elif accessible is False: compute,status="asleep","degraded"
    else: compute,status="unavailable","degraded"
    result={"status":status,"compute":compute,"tower_accessible":accessible,"ollama_ready":ready,"model":MODEL}
    if not ready: result["degraded_reason"]="COMPUTE_ASLEEP" if accessible is False else "OLLAMA_UNAVAILABLE"
    return result
def ensure_tower(lease_id):
    if ollama_ready():
        BROKER._publish_lease("active",lease_id=lease_id); return
    BROKER._publish_lease("active",lease_id=lease_id)
    print("TOWER_WAKE_REQUEST=LEASE",flush=True)
    deadline=time.monotonic()+WAKE_TIMEOUT
    while time.monotonic()<deadline:
        if tower_accessible() is True and ollama_ready(): return
        time.sleep(min(2,max(0.05,WAKE_TIMEOUT/60)))
    raise RuntimeError("Tower/Ollama did not become ready before the bounded wake timeout")
class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,fmt,*args): print(fmt%args,flush=True)
    def sendj(self,code,obj):
        body=json.dumps(obj,separators=(",",":")).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=self.path.split("?",1)[0]
        if path=="/health": return self.sendj(200,health_status())
        if path=="/v1/models": return self.sendj(200,{"object":"list","data":[{"id":m,"object":"model","owned_by":"lifeos"} for m in sorted(ALLOWED_MODELS)]})
        if path=="/api/tags": return self.sendj(200,{"models":[{"name":m,"model":m,"details":{"family":"lifeos"}} for m in sorted(ALLOWED_MODELS)]})
        if path=="/api/ps": return self.sendj(200,{"models":[{"name":MODEL,"model":MODEL}] if health_status()["ollama_ready"] else []})
        return self.sendj(404,{"error":{"message":"not found"}})
    def do_POST(self):
        try:
            path=self.path.split("?",1)[0]
            if path not in INFERENCE_PATHS: return self.sendj(404,{"error":{"message":"not found"}})
            size=int(self.headers.get("Content-Length","0"))
            if size<=0 or size>32*1024*1024: return self.sendj(400,{"error":{"message":"invalid request body size"}})
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict): raise ValueError("request body must be a JSON object")
            model=str(payload.get("model","")).removeprefix("openai/")
            if model not in ALLOWED_MODELS: raise ValueError("model not allowed")
            payload["model"]=model; data=json.dumps(payload,separators=(",",":")).encode()
            lease_id=f"ai-endpoint-{os.getpid()}-{uuid.uuid4().hex}"
            lease_acquired=True
            if not REQUEST_LOCK.acquire(timeout=WAKE_TIMEOUT): raise RuntimeError("Tower wake request queued beyond the bounded wait")
            try: ensure_tower(lease_id)
            finally: REQUEST_LOCK.release()
            request=Request(UPSTREAM+path,data=data,headers={"Content-Type":"application/json"},method="POST")
                with urlopen(request,timeout=max(600,WAKE_TIMEOUT+600)) as r:
                    body=r.read(); self.send_response(r.status)
                    self.send_header("Content-Type",r.headers.get("Content-Type","application/json"))
                    self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        except (HTTPError,URLError,ValueError,RuntimeError) as exc: self.sendj(503,{"error":{"message":str(exc)}})
        except Exception as exc: self.sendj(502,{"error":{"message":"upstream request failed: "+type(exc).__name__}})
        finally:
            if locals().get("lease_acquired",False): BROKER._publish_lease("released",required=False,lease_id=lease_id)
if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
