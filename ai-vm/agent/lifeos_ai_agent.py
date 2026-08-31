#!/usr/bin/env python3
import json, os, pathlib, queue, subprocess, threading, time, urllib.request, urllib.error, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST=os.environ.get('LIFEOS_AI_AGENT_HOST','0.0.0.0')
PORT=int(os.environ.get('LIFEOS_AI_AGENT_PORT','38125'))
STATE=pathlib.Path(os.environ.get('LIFEOS_AI_AGENT_STATE','/home/joshan/.local/state/lifeos-ai-agent'))
WORKSPACE=pathlib.Path(os.environ.get('LIFEOS_AI_WORKSPACE','/home/joshan/workspace/lifeos-platform'))
OLLAMA=os.environ.get('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL=os.environ.get('OLLAMA_MODEL','qwen2.5-coder:7b-instruct')
CODEX_TEMPLATE=os.environ.get('CODEX_COMMAND_TEMPLATE','')
MAX_ITER=int(os.environ.get('LIFEOS_AI_MAX_ITERATIONS','40'))
STATE.mkdir(parents=True,exist_ok=True)
GOALS=STATE/'goals'; GOALS.mkdir(exist_ok=True)
CURRENT=STATE/'current.json'
LOCK=threading.Lock(); Q=queue.Queue(); STOP=threading.Event(); PAUSED=threading.Event()


def save(obj):
    tmp=CURRENT.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,indent=2)+'\n'); tmp.replace(CURRENT)

def load():
    try:return json.loads(CURRENT.read_text())
    except:return {'status':'idle','goal':None,'iteration':0,'provider':None,'last_message':'idle'}

def ollama(prompt,timeout=120):
    body=json.dumps({'model':OLLAMA_MODEL,'prompt':prompt,'stream':False}).encode()
    req=urllib.request.Request(OLLAMA+'/api/generate',data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.load(r).get('response','')

def codex_available():
    return bool(CODEX_TEMPLATE) and subprocess.run(['bash','-lc','command -v codex >/dev/null'],stdout=subprocess.DEVNULL).returncode==0

def run_codex(goal,iteration):
    prompt=(
      'You are the primary LifeOS engineering agent. Continue autonomously toward the goal below. '
      'Work only inside the configured workspace unless the goal explicitly requires read-only inspection elsewhere. '
      'Do not use sudo, do not modify secrets, and do not perform destructive host changes. '
      'Inspect current state, make the safest useful progress, test your work, and end with one line exactly: '
      'LIFEOS_AGENT_STATUS=COMPLETE or LIFEOS_AGENT_STATUS=CONTINUE or LIFEOS_AGENT_STATUS=BLOCKED, followed by a concise reason.\n\n'
      f'GOAL:\n{goal}\n\nITERATION={iteration}\n')
    cmd=CODEX_TEMPLATE.replace('{workspace}',str(WORKSPACE)).replace('{prompt}',json.dumps(prompt))
    p=subprocess.run(['bash','-lc',cmd],cwd=WORKSPACE,text=True,capture_output=True,timeout=1800)
    out=(p.stdout or '')+'\n'+(p.stderr or '')
    return p.returncode,out[-50000:]

def run_local(goal,iteration):
    prompt=(
      'You are the offline LifeOS planning agent. Return JSON only with keys status, summary, next_action. '
      'status must be COMPLETE, CONTINUE, or BLOCKED. You cannot execute shell commands yourself; '
      'therefore only mark COMPLETE when the supplied goal is informational/planning and fully answered. '
      f'Goal: {goal}\nIteration: {iteration}')
    try:
      text=ollama(prompt)
      return 0,text
    except Exception as e:
      return 1,f'BLOCKED: local Ollama error {type(e).__name__}'

def classify(text,rc):
    u=text.upper()
    if 'LIFEOS_AGENT_STATUS=COMPLETE' in u or '"STATUS":"COMPLETE"' in u.replace(' ',''): return 'complete'
    if 'LIFEOS_AGENT_STATUS=BLOCKED' in u or '"STATUS":"BLOCKED"' in u.replace(' ',''): return 'blocked'
    if rc!=0:return 'retry'
    return 'continue'

def worker():
  while True:
    goal=Q.get()
    if goal is None:return
    gid=goal['id']; text=goal['goal']; hist=[]
    for i in range(1,MAX_ITER+1):
      while PAUSED.is_set(): time.sleep(1)
      if STOP.is_set():
        st={'status':'stopped','goal':text,'goal_id':gid,'iteration':i-1,'provider':None,'last_message':'stopped by user','history':hist}; save(st); STOP.clear(); break
      provider='codex' if codex_available() else 'ollama'
      st={'status':'running','goal':text,'goal_id':gid,'iteration':i,'provider':provider,'last_message':'working','history':hist}; save(st)
      try:
        rc,out=run_codex(text,i) if provider=='codex' else run_local(text,i)
      except subprocess.TimeoutExpired:
        rc,out=124,'iteration timeout'
      result=classify(out,rc); hist.append({'iteration':i,'provider':provider,'rc':rc,'result':result,'summary':out[-4000:]})
      save({'status':result,'goal':text,'goal_id':gid,'iteration':i,'provider':provider,'last_message':out[-1000:],'history':hist})
      if result in ('complete','blocked'): break
      time.sleep(2)
    else:
      save({'status':'blocked','goal':text,'goal_id':gid,'iteration':MAX_ITER,'provider':provider,'last_message':'maximum iterations reached','history':hist})
    (GOALS/f'{gid}.json').write_text(json.dumps(load(),indent=2)+'\n')
    Q.task_done()

threading.Thread(target=worker,daemon=True).start()

class H(BaseHTTPRequestHandler):
  def sendj(self,code,obj):
    b=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
  def body(self):
    n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n) or b'{}')
  def do_GET(self):
    if self.path in ('/','/health'): self.sendj(200,{'service':'lifeos-ai-agent','status':'ok','state':load(),'codex_configured':bool(CODEX_TEMPLATE),'ollama_model':OLLAMA_MODEL})
    elif self.path=='/status': self.sendj(200,load())
    else:self.sendj(404,{'error':'not_found'})
  def do_POST(self):
    if self.path=='/goal':
      d=self.body(); g=str(d.get('goal','')).strip()
      if not g:return self.sendj(400,{'error':'goal_required'})
      gid=str(uuid.uuid4()); Q.put({'id':gid,'goal':g}); self.sendj(202,{'accepted':True,'goal_id':gid})
    elif self.path=='/stop': STOP.set(); self.sendj(202,{'stopping':True})
    elif self.path=='/pause': PAUSED.set(); self.sendj(200,{'paused':True})
    elif self.path=='/resume': PAUSED.clear(); self.sendj(200,{'paused':False})
    else:self.sendj(404,{'error':'not_found'})
  def log_message(self,fmt,*args): pass

if __name__=='__main__':
  ThreadingHTTPServer((HOST,PORT),H).serve_forever()
