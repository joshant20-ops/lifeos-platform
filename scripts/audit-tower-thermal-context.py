#!/usr/bin/env python3
import glob,json,os,pathlib,subprocess,time,urllib.request
from datetime import datetime,timezone
MODEL="qwen2.5-coder:7b-instruct"; ACCEPT=80.0; HARD=90.0

def read(p,d=""):
 try:return pathlib.Path(p).read_text().strip()
 except:return d

def temp():
 out=[]
 for b in glob.glob("/sys/class/hwmon/hwmon*"):
  if read(b+"/name")!="coretemp":continue
  for l in glob.glob(b+"/temp*_label"):
   if read(l).lower().startswith("package"):
    v=read(l.replace("_label","_input"))
    if v:out.append(float(v)/1000)
 return max(out) if out else None

def throttle():
 out={}
 for p in glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/*throttle_count"):
  try:out[p]=int(read(p,"0"))
  except:pass
 return out

def procs():
 out={}
 for p in glob.glob("/proc/[0-9]*/stat"):
  pid=p.split("/")[2]
  try:
   cmd=pathlib.Path("/proc/"+pid+"/cmdline").read_bytes().replace(b"\0",b" ").decode(errors="ignore")
   comm=read("/proc/"+pid+"/comm","unknown")
   if "ollama" not in (cmd+" "+comm).lower() and "llama" not in (cmd+" "+comm).lower():continue
   f=pathlib.Path(p).read_text().split();out[int(pid)]=(int(f[13])+int(f[14]),comm)
  except:pass
 return out

def cpu():
 f=pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:];v=list(map(int,f))
 return sum(v),v[3]+(v[4] if len(v)>4 else 0)

def gpu():
 try:
  s=subprocess.check_output(["nvidia-smi","--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used","--format=csv,noheader,nounits"],text=True,timeout=5).splitlines()[0]
  return tuple(float(x.strip()) for x in s.split(","))
 except:return None

def ps():
 try:
  d=json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/ps",timeout=5).read())
  for m in d.get("models",[]):
   if m.get("name")==MODEL:return m
 except:pass
 return {}

def fans():
 rows=[]
 for b in glob.glob("/sys/class/hwmon/hwmon*"):
  for p in glob.glob(b+"/fan*_input"):
   if read(p):rows.append(read(b+"/name","unknown")+":"+pathlib.Path(p).name+":"+read(p))
 return rows

def freq():
 vals=[];gov=set()
 for c in glob.glob("/sys/devices/system/cpu/cpu[0-9]*"):
  if read(c+"/cpufreq/scaling_cur_freq"):vals.append(int(read(c+"/cpufreq/scaling_cur_freq"))//1000)
  if read(c+"/cpufreq/scaling_governor"):gov.add(read(c+"/cpufreq/scaling_governor"))
 return vals,sorted(gov)

def cool():
 subprocess.run(["ollama","stop",MODEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 end=time.time()+600
 while time.time()<end:
  t=temp()
  if t is None or t<=60:print("COOLDOWN_CPU_C="+str(t));return True
  time.sleep(5)
 print("COOLDOWN=TIMEOUT");return False

base=temp();fs,gov=freq();tb=throttle()
print("TIME_GMT="+datetime.now(timezone.utc).isoformat())
print("BASELINE_CPU_C="+str(base))
print("CPU_GOVERNORS="+(",".join(gov) if gov else "UNAVAILABLE"))
print("CPU_FREQ_RANGE_MHZ="+((str(min(fs))+"-"+str(max(fs))) if fs else "UNAVAILABLE"))
print("FAN_TELEMETRY="+((";".join(fans())) if fans() else "UNAVAILABLE"))
print("THROTTLE_COUNTERS_AVAILABLE="+str(bool(tb)).lower())
print("OLLAMA_IDLE_PROCESSES="+",".join(str(k)+":"+v[1] for k,v in sorted(procs().items())))

def case(ctx):
 request={"model":MODEL,"prompt":"Give a long technical analysis of this synthetic sequence: "+" thermalcontext"*3000,"stream":False,"keep_alive":"5m","options":{"num_ctx":ctx,"num_gpu":-1,"num_predict":700}}
 p=subprocess.Popen(["curl","-sS","-f","-o","/dev/null","-H","Content-Type: application/json","--data-binary","@-","http://127.0.0.1:11434/api/generate"],stdin=subprocess.PIPE)
 p.stdin.write(json.dumps(request).encode());p.stdin.close()
 start=time.time();pp=procs();pt,pi=cpu();clk=os.sysconf("SC_CLK_TCK")
 mt=temp() or 0;gc=gu=gp=gv=oc=hb=0;names={};resident={};stop=False;hard=False
 while p.poll() is None and time.time()-start<240:
  time.sleep(1);t=temp()
  if t is not None:mt=max(mt,t)
  np=procs();nt,ni=cpu();dt=max(1,nt-pt);hb=max(hb,100*(1-max(0,ni-pi)/dt))
  ticks=0
  for pid,(x,n) in np.items():ticks+=max(0,x-pp.get(pid,(x,n))[0]);names[pid]=n
  oc=max(oc,100*ticks/clk);pp,pt,pi=np,nt,ni
  g=gpu()
  if g:gc=max(gc,g[0]);gu=max(gu,g[1]);gp=max(gp,g[2]);gv=max(gv,g[3])
  if not resident and time.time()-start>3:resident=ps()
  if t is not None and t>=HARD:hard=True;p.terminate();break
  if t is not None and t>=ACCEPT:stop=True;p.terminate();break
 if p.poll() is None:p.terminate()
 try:rc=p.wait(timeout=10)
 except:p.kill();rc=p.wait()
 subprocess.run(["ollama","stop",MODEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 ta=throttle();td=sum(max(0,ta.get(k,0)-tb.get(k,0)) for k in set(ta)|set(tb))
 safe=rc==0 and mt<ACCEPT and td==0
 pre="CTX"+str(ctx)
 print(pre+"_RC="+str(rc));print(pre+"_STOPPED_AT_80C="+str(stop));print(pre+"_HARD_ABORT_90C="+str(hard))
 print(pre+"_MAX_CPU_C="+str(round(mt,1)));print(pre+"_MAX_HOST_CPU_BUSY_PCT="+str(round(hb,1)))
 print(pre+"_MAX_OLLAMA_AGGREGATE_CORE_PCT="+str(round(oc,1)));print(pre+"_PROCESSES="+",".join(str(k)+":"+names[k] for k in sorted(names)))
 print(pre+"_MAX_GPU_C="+str(round(gc,1)));print(pre+"_MAX_GPU_UTIL_PCT="+str(round(gu,1)));print(pre+"_MAX_GPU_POWER_W="+str(round(gp,2)));print(pre+"_MAX_VRAM_MIB="+str(round(gv,1)))
 print(pre+"_MODEL_SIZE="+str(resident.get("size","UNAVAILABLE")));print(pre+"_MODEL_SIZE_VRAM="+str(resident.get("size_vram","UNAVAILABLE")))
 print(pre+"_REPORTED_CONTEXT="+str(resident.get("context_length",resident.get("details",{}).get("context_length","UNAVAILABLE"))))
 print(pre+"_THROTTLE_DELTA="+str(td));print(pre+"_THERMALLY_SAFE="+str(safe).lower())
 return {"safe":safe,"max":mt,"cpu":oc,"gpu":gu,"hard":hard}

if base is not None and base>=ACCEPT:
 print("ROOT_CAUSE=IDLE_COOLING_FAULT");print("RECOMMENDED_CONTEXT=NONE_THERMALLY_SAFE");raise SystemExit()
cool();a=case(8192);ok=cool();b=None
if ok and not a["hard"]:b=case(4096);cool()
else:print("CTX4096_RESULT=NOT_TESTED")
rec="8192" if a["safe"] else ("4096" if b and b["safe"] else "NONE_THERMALLY_SAFE")
if rec=="8192":cause="8192_WITHIN_THERMAL_ACCEPTANCE"
elif rec=="4096":cause="CONTEXT_SIZE_MATERIALLY_AFFECTS_THERMAL_SAFETY"
elif a["cpu"]<100 and a["gpu"]>=90:cause="CPU_COOLING_DEFECT_INDEPENDENT_OF_PRIMARY_MODEL_COMPUTE"
elif b and abs(a["max"]-b["max"])<=5:cause="CPU_COOLING_DEFECT_WEAK_CONTEXT_DEPENDENCE"
else:cause="CPU_THERMAL_PATH_UNSAFE_PHYSICAL_INSPECTION_REQUIRED"
print("ROOT_CAUSE="+cause);print("RECOMMENDED_CONTEXT="+rec)
print("FINAL_THROTTLE_DELTA="+str(sum(max(0,throttle().get(k,0)-tb.get(k,0)) for k in set(throttle())|set(tb))))
print("RESULT=PASS")
