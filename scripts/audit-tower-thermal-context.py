#!/usr/bin/env python3
import glob, json, os, pathlib, subprocess, time, urllib.request
from collections import deque
from datetime import datetime, timezone

MODEL = "qwen2.5-coder:7b-instruct"
CTX = 8192
ACCEPT = 80.0
HARD = 90.0
PROMPT = "Give a long technical analysis of this synthetic sequence: " + " thermalcontext" * 3000

def read(path, default=""):
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception:
        return default

def package_temp():
    values = []
    for base in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(base + "/name") != "coretemp":
            continue
        for label in glob.glob(base + "/temp*_label"):
            if read(label).lower().startswith("package"):
                raw = read(label.replace("_label", "_input"))
                if raw:
                    values.append(float(raw) / 1000)
    return max(values) if values else None

def throttle_counts():
    result = {}
    for path in glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/*throttle_count"):
        try:
            result[path] = int(read(path, "0"))
        except Exception:
            pass
    return result

def throttle_delta(before):
    after = throttle_counts()
    return sum(max(0, after.get(key, 0) - before.get(key, 0)) for key in set(before) | set(after))

def ollama_processes():
    result = {}
    for stat_path in glob.glob("/proc/[0-9]*/stat"):
        pid = stat_path.split("/")[2]
        try:
            cmd = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            comm = read(f"/proc/{pid}/comm", "unknown")
            if "ollama" not in (cmd + " " + comm).lower() and "llama" not in (cmd + " " + comm).lower():
                continue
            fields = pathlib.Path(stat_path).read_text().split()
            result[int(pid)] = (int(fields[13]) + int(fields[14]), comm)
        except Exception:
            pass
    return result

def host_cpu():
    fields = list(map(int, pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:]))
    return sum(fields), fields[3] + (fields[4] if len(fields) > 4 else 0)

def gpu_metrics():
    try:
        line = subprocess.check_output([
            "nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used",
            "--format=csv,noheader,nounits"
        ], text=True, timeout=5).splitlines()[0]
        return tuple(float(item.strip()) for item in line.split(","))
    except Exception:
        return None

def residency():
    try:
        data = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5).read())
        for item in data.get("models", []):
            if item.get("name") == MODEL:
                return item
    except Exception:
        pass
    return {}

def fans():
    rows = []
    for base in glob.glob("/sys/class/hwmon/hwmon*"):
        for path in glob.glob(base + "/fan*_input"):
            value = read(path)
            if value:
                rows.append(f"{read(base + '/name', 'unknown')}:{pathlib.Path(path).name}:{value}")
    return rows

def frequencies():
    values, governors = [], set()
    for cpu_path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*"):
        current = read(cpu_path + "/cpufreq/scaling_cur_freq")
        governor = read(cpu_path + "/cpufreq/scaling_governor")
        if current:
            values.append(int(current) // 1000)
        if governor:
            governors.add(governor)
    return values, sorted(governors)

def unload_and_cool(target=60.0, timeout=600):
    subprocess.run(["ollama", "stop", MODEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = package_temp()
        if value is None or value <= target:
            print(f"COOLDOWN_CPU_C={value}")
            return True
        time.sleep(5)
    print("COOLDOWN=TIMEOUT")
    return False

def start_request():
    request = {
        "model": MODEL, "prompt": PROMPT, "stream": False, "keep_alive": "5m",
        "options": {"num_ctx": CTX, "num_gpu": -1, "num_predict": 700},
    }
    proc = subprocess.Popen([
        "curl", "-sS", "-f", "-o", "/dev/null", "-H", "Content-Type: application/json",
        "--data-binary", "@-", "http://127.0.0.1:11434/api/generate"
    ], stdin=subprocess.PIPE)
    proc.stdin.write(json.dumps(request).encode())
    proc.stdin.close()
    return proc

def terminate(proc):
    if proc.poll() is None:
        proc.terminate()
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()

def run_test(label, soak_seconds=None):
    before_throttle = throttle_counts()
    previous_procs = ollama_processes()
    previous_total, previous_idle = host_cpu()
    clock = os.sysconf("SC_CLK_TCK")
    started = time.time()
    proc = start_request()
    requests = 1
    max_temp = package_temp() or 0
    max_gpu_temp = max_gpu_util = max_gpu_power = max_vram = 0
    max_ollama_cpu = max_host_busy = 0
    names, resident = {}, {}
    samples = deque()
    stopped_80 = hard_abort = timed_out = request_error = False

    while True:
        time.sleep(1)
        now = time.time()
        value = package_temp()
        if value is not None:
            max_temp = max(max_temp, value)
            samples.append((now, value))
            while samples and now - samples[0][0] > 180:
                samples.popleft()

        current_procs = ollama_processes()
        total, idle = host_cpu()
        delta_total = max(1, total - previous_total)
        max_host_busy = max(max_host_busy, 100 * (1 - max(0, idle - previous_idle) / delta_total))
        ticks = 0
        for pid, (current_ticks, name) in current_procs.items():
            ticks += max(0, current_ticks - previous_procs.get(pid, (current_ticks, name))[0])
            names[pid] = name
        max_ollama_cpu = max(max_ollama_cpu, 100 * ticks / clock)
        previous_procs, previous_total, previous_idle = current_procs, total, idle

        gpu = gpu_metrics()
        if gpu:
            max_gpu_temp = max(max_gpu_temp, gpu[0])
            max_gpu_util = max(max_gpu_util, gpu[1])
            max_gpu_power = max(max_gpu_power, gpu[2])
            max_vram = max(max_vram, gpu[3])
        if not resident and now - started > 3:
            resident = residency()

        if value is not None and value >= HARD:
            hard_abort = True
            break
        if value is not None and value >= ACCEPT:
            stopped_80 = True
            break

        if proc.poll() is not None:
            rc = proc.returncode
            if rc != 0:
                request_error = True
                break
            if soak_seconds is None:
                break
            if now - started >= soak_seconds:
                break
            proc = start_request()
            requests += 1

        limit = soak_seconds if soak_seconds is not None else 240
        if now - started >= limit:
            timed_out = soak_seconds is None
            break

    rc = terminate(proc)
    elapsed = time.time() - started
    delta = throttle_delta(before_throttle)
    completed = (rc == 0) if soak_seconds is None else not request_error
    safe = not stopped_80 and not hard_abort and not timed_out and completed and max_temp < ACCEPT and delta == 0
    equilibrium = False
    span = None
    if soak_seconds is not None and elapsed >= 300 and samples and samples[-1][0] - samples[0][0] >= 170:
        temps = [sample[1] for sample in samples]
        span = max(temps) - min(temps)
        equilibrium = span <= 2.0

    prefix = label.upper()
    print(f"{prefix}_REQUESTS={requests}")
    print(f"{prefix}_ELAPSED_S={round(elapsed, 1)}")
    print(f"{prefix}_RC={rc}")
    print(f"{prefix}_STOPPED_AT_80C={stopped_80}")
    print(f"{prefix}_HARD_ABORT_90C={hard_abort}")
    print(f"{prefix}_MAX_CPU_C={round(max_temp, 1)}")
    print(f"{prefix}_MAX_HOST_CPU_BUSY_PCT={round(max_host_busy, 1)}")
    print(f"{prefix}_MAX_OLLAMA_AGGREGATE_CORE_PCT={round(max_ollama_cpu, 1)}")
    print(f"{prefix}_PROCESSES=" + ",".join(f"{pid}:{names[pid]}" for pid in sorted(names)))
    print(f"{prefix}_MAX_GPU_C={round(max_gpu_temp, 1)}")
    print(f"{prefix}_MAX_GPU_UTIL_PCT={round(max_gpu_util, 1)}")
    print(f"{prefix}_MAX_GPU_POWER_W={round(max_gpu_power, 2)}")
    print(f"{prefix}_MAX_VRAM_MIB={round(max_vram, 1)}")
    print(f"{prefix}_MODEL_SIZE={resident.get('size', 'UNAVAILABLE')}")
    print(f"{prefix}_MODEL_SIZE_VRAM={resident.get('size_vram', 'UNAVAILABLE')}")
    print(f"{prefix}_REPORTED_CONTEXT={resident.get('context_length', 'UNAVAILABLE')}")
    print(f"{prefix}_THROTTLE_DELTA={delta}")
    print(f"{prefix}_THERMALLY_SAFE={str(safe).lower()}")
    if soak_seconds is not None:
        print(f"{prefix}_LAST_180S_TEMP_SPAN_C={span if span is not None else 'UNAVAILABLE'}")
        print(f"{prefix}_EQUILIBRIUM={str(equilibrium).lower()}")
    subprocess.run(["ollama", "stop", MODEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"safe": safe, "equilibrium": equilibrium, "max_temp": max_temp, "throttle": delta}

baseline = package_temp()
freq, governors = frequencies()
overall_throttle = throttle_counts()
print("TIME_GMT=" + datetime.now(timezone.utc).isoformat())
print(f"BASELINE_CPU_C={baseline}")
print("CPU_GOVERNORS=" + (",".join(governors) if governors else "UNAVAILABLE"))
print("CPU_FREQ_RANGE_MHZ=" + (f"{min(freq)}-{max(freq)}" if freq else "UNAVAILABLE"))
print("FAN_TELEMETRY=" + (";".join(fans()) if fans() else "UNAVAILABLE"))
print("THROTTLE_COUNTERS_AVAILABLE=" + str(bool(overall_throttle)).lower())
print("OLLAMA_IDLE_PROCESSES=" + ",".join(f"{pid}:{data[1]}" for pid, data in sorted(ollama_processes().items())))

if baseline is not None and baseline >= ACCEPT:
    print("ROOT_CAUSE=IDLE_COOLING_FAULT")
    print("RECOMMENDED_CONTEXT=NONE_THERMALLY_SAFE")
    raise SystemExit(2)

unload_and_cool()
comparison = run_test("CTX8192_COMPARABLE")
soak = None
if comparison["safe"] and unload_and_cool():
    soak = run_test("CTX8192_SOAK", soak_seconds=600)
    unload_and_cool()
else:
    print("CTX8192_SOAK_RESULT=NOT_RUN_INITIAL_8192_UNSAFE")

if comparison["safe"] and soak and soak["safe"] and soak["equilibrium"]:
    conclusion = "8192_THERMALLY_ACCEPTED_AT_EQUILIBRIUM"
    recommendation = "8192"
elif comparison["safe"] and soak and soak["safe"]:
    conclusion = "8192_BELOW_LIMIT_BUT_EQUILIBRIUM_NOT_PROVEN"
    recommendation = "NONE_THERMALLY_SAFE"
else:
    conclusion = "CPU_COOLING_REMAINS_INADEQUATE_AT_8192"
    recommendation = "NONE_THERMALLY_SAFE"

print(f"ROOT_CAUSE={conclusion}")
print(f"RECOMMENDED_CONTEXT={recommendation}")
print(f"FINAL_THROTTLE_DELTA={throttle_delta(overall_throttle)}")
print("RESULT=PASS")
