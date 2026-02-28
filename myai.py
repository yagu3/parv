#!/usr/bin/env python3
"""
YaguAI v4.0 — Multi-Agent Computer-Use System
Coordinator + Workers · Persistent Memory · Self-Improvement
Press ESC during execution to pause/resume.
"""

import os, sys, json, subprocess, time, re, msvcrt
from pathlib import Path
import urllib.request, urllib.error
from tools import TOOL_SCHEMAS, execute_tool, ROOT, _ps

# ═══════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════
MODEL_DIRS  = [ROOT / "model", ROOT / "models"]
LLAMA_BIN   = ROOT / "llama.cpp" / "build" / "bin"
LLAMA_EXE   = LLAMA_BIN / "llama-server.exe"
PREFS_FILE  = ROOT / ".ai_preferences.json"
LOG_DIR     = ROOT / "logs"
SKILLS_DIR  = ROOT / "skills"
CUSTOM_TOOLS = ROOT / "tools"
LLAMA_HOST  = "127.0.0.1"
LLAMA_PORT  = 8080
VERSION     = "4.0.0"

# ═══════════════════════════════════════
# UI
# ═══════════════════════════════════════
class S:
    R="\033[0m"; B="\033[1m"; D="\033[2m"
    RED="\033[91m"; GRN="\033[92m"; YLW="\033[93m"
    BLU="\033[94m"; MAG="\033[95m"; CYN="\033[96m"

def _enable_ansi():
    if sys.platform == 'win32':
        try:
            import ctypes; k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except: os.system('')

def banner():
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{VERSION} · Multi-Agent System     ║
  ║   Coordinator + Workers + Memory             ║
  ╚══════════════════════════════════════════════╝{S.R}""")

def info(m):  print(f"  {S.GRN}✓{S.R} {m}")
def warn(m):  print(f"  {S.YLW}⚠{S.R} {m}")
def err(m):   print(f"  {S.RED}✗{S.R} {m}")
def step(m):  print(f"  {S.BLU}→{S.R} {m}")
def dim(m):   print(f"    {S.D}{m}{S.R}")
def sec(m):   print(f"\n  {S.B}{S.CYN}── {m} ──{S.R}")
def hr():     print(f"  {S.D}{'─'*46}{S.R}")
def agent_print(m): print(f"  {S.D}{m}{S.R}")

# ═══════════════════════════════════════
# SYSTEM DETECTION
# ═══════════════════════════════════════
class SystemInfo:
    def __init__(self):
        self.cpu="Unknown"; self.cores=4; self.threads=8
        self.gpu="Unknown"; self.vram_mb=0; self.has_cuda=False
        self.ram_total=0; self.ram_free=0
        self.user = os.environ.get("USERNAME","User")
        self.desktop = str(Path(os.environ.get("USERPROFILE","C:\\Users\\User")) / "Desktop")
        self.screen_w=1920; self.screen_h=1080
        self._detect()

    def _detect(self):
        sec("System Detection")
        r = _ps("Get-CimInstance Win32_Processor|Select -First 1|"
                 "ForEach{$_.Name+'|'+$_.NumberOfCores+'|'+$_.NumberOfLogicalProcessors}")
        if '|' in r:
            p = r.split('|')
            self.cpu=p[0].strip()
            self.cores=int(p[1]) if p[1].isdigit() else 4
            self.threads=int(p[2]) if p[2].isdigit() else 8
        info(f"CPU: {self.cpu} ({self.cores}C/{self.threads}T)")
        r = _ps("$o=Get-CimInstance Win32_OperatingSystem;"
                 "[math]::Round($o.TotalVisibleMemorySize/1024).ToString()+'|'+"
                 "[math]::Round($o.FreePhysicalMemory/1024).ToString()")
        if '|' in r:
            p = r.split('|')
            self.ram_total=int(p[0]) if p[0].isdigit() else 0
            self.ram_free=int(p[1]) if p[1].isdigit() else 0
        info(f"RAM: {self.ram_total//1024}GB total · {self.ram_free//1024}GB free")
        try:
            r = subprocess.run(["nvidia-smi","--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"], capture_output=True, text=True,
                timeout=10, creationflags=0x08000000)
            if r.returncode==0 and r.stdout.strip():
                p = r.stdout.strip().split(',')
                self.gpu=p[0].strip()
                self.vram_mb=int(p[1].strip()) if len(p)>1 else 0
                self.has_cuda=True
        except: pass
        if (LLAMA_BIN/"ggml-cuda.dll").exists(): self.has_cuda=True
        vr = f" ({self.vram_mb}MB)" if self.vram_mb else ""
        info(f"GPU: {self.gpu}{vr}")
        if self.has_cuda: info(f"CUDA: {S.GRN}Ready{S.R}")
        try:
            import ctypes as ct
            self.screen_w = ct.windll.user32.GetSystemMetrics(0)
            self.screen_h = ct.windll.user32.GetSystemMetrics(1)
        except: pass
        info(f"Screen: {self.screen_w}x{self.screen_h}")

    def optimize(self, model_mb, param_b):
        p = {'threads':max(1,self.cores-1), 'gpu_layers':0, 'ctx_size':4096, 'batch':512}
        if self.has_cuda and self.vram_mb>0:
            avail = self.vram_mb - 400
            p['gpu_layers'] = 999 if model_mb<=avail else max(1,int(avail/model_mb*param_b*8))
        rl = self.ram_free - model_mb - 1024
        if rl > 4096: p['ctx_size'] = 8192
        elif rl < 2048: p['ctx_size'] = 2048
        if self.has_cuda and self.vram_mb > model_mb+2000:
            p['ctx_size'] = min(16384, p['ctx_size']*2)
        if self.ram_free < 4096: p['batch'] = 256
        return p

    def summary(self):
        return (f"Windows 11 | {self.cpu} ({self.cores}C/{self.threads}T) | "
                f"{self.gpu} ({self.vram_mb}MB) | {self.ram_total//1024}GB RAM | "
                f"Screen: {self.screen_w}x{self.screen_h} | User: {self.user}")

# ═══════════════════════════════════════
# MODEL DISCOVERY
# ═══════════════════════════════════════
class ModelInfo:
    def __init__(self, path: Path):
        self.path=path; self.filename=path.name
        self.size_mb=path.stat().st_size/(1024*1024)
        self.size_gb=self.size_mb/1024
        self.family=""; self.params=""; self.params_b=0.0
        self.variant=""; self.quant=""; self.quality=""
        self.has_vision=False; self._parse()
    def _parse(self):
        name=self.filename.replace('.gguf','')
        qm=re.search(r'[_\-]((?:IQ\d_\w+)|(?:[QF](?:16|32|\d+)(?:_K)?(?:_[SMLX])?))',name,re.I)
        if qm: self.quant=qm.group(1).upper(); name=name[:qm.start()]
        pm=re.search(r'[_\-]?(\d+\.?\d*)[Bb]',name)
        if pm:
            self.params=pm.group(1)+"B"; self.params_b=float(pm.group(1))
            idx=name.find(pm.group(0))
            if idx>0: self.family=name[:idx].replace('-',' ').replace('_',' ').strip()
            self.variant=name[idx+len(pm.group(0)):].replace('-',' ').replace('_',' ').strip()
        else: self.family=name.replace('-',' ').replace('_',' ').strip()
        low=self.filename.lower()
        if any(x in low for x in ['vl','vision','visual','llava','minicpm']): self.has_vision=True
        q=self.quant
        if q in ('F32','F16'): self.quality="Lossless"
        elif 'Q8' in q: self.quality="Excellent"
        elif 'Q6' in q or 'Q5' in q: self.quality="Very Good"
        elif 'Q4' in q: self.quality="Good"
        elif 'Q3' in q: self.quality="Fair"
        else: self.quality="Unknown"
    def display(self):
        parts=[x for x in [self.family,self.params,self.variant] if x]
        n=" · ".join(parts) if parts else self.filename
        if self.has_vision: n+=" 👁️"
        return n
    def model_id(self): return self.filename.replace('.gguf','')

def discover_models():
    models=[]
    for d in MODEL_DIRS:
        if d.exists():
            for f in d.glob("**/*.gguf"):
                if f.stat().st_size>50*1024*1024: models.append(ModelInfo(f))
    return sorted(models, key=lambda m: m.size_mb)

# ═══════════════════════════════════════
# PROCESS MANAGEMENT
# ═══════════════════════════════════════
class ProcMgr:
    def __init__(self): self._procs={}
    def is_running(self, n):
        try:
            r=subprocess.run(["tasklist","/FI",f"IMAGENAME eq {n}","/FO","CSV","/NH"],
                capture_output=True,text=True,timeout=10,creationflags=0x08000000)
            return n.lower() in r.stdout.lower()
        except: return False
    def start_hidden(self, n, cmd):
        LOG_DIR.mkdir(exist_ok=True)
        lf=open(LOG_DIR/f"{n}.log",'w')
        p=subprocess.Popen(cmd,stdout=lf,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,creationflags=0x08000000,cwd=str(ROOT))
        self._procs[n]=(p,lf); return p
    def wait_health(self, url, timeout=120):
        t0=time.time()
        while time.time()-t0<timeout:
            try:
                if urllib.request.urlopen(url,timeout=5).status==200: return True
            except: pass
            time.sleep(2)
        return False
    def kill(self, n):
        try: subprocess.run(["taskkill","/F","/IM",n],capture_output=True,timeout=10,creationflags=0x08000000)
        except: pass
    def cleanup(self):
        for _,(p,lf) in self._procs.items():
            try: p.terminate();p.wait(3)
            except:
                try: p.kill()
                except: pass
            try: lf.close()
            except: pass

# ═══════════════════════════════════════
# ESC PAUSE
# ═══════════════════════════════════════
def check_pause():
    while msvcrt.kbhit():
        if msvcrt.getch() == b'\x1b':
            print(f"\n  {S.YLW}⏸  PAUSED — Press ESC to resume{S.R}", flush=True)
            while True:
                if msvcrt.kbhit() and msvcrt.getch() == b'\x1b':
                    print(f"  {S.GRN}▶  RESUMED{S.R}\n", flush=True); return
                time.sleep(0.1)

# ═══════════════════════════════════════
# PREFERENCES
# ═══════════════════════════════════════
def load_prefs():
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE) as f: return json.load(f)
        except: pass
    return {}
def save_prefs(p):
    with open(PREFS_FILE,'w') as f: json.dump(p, f, indent=2)

# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
def main():
    _enable_ansi()
    os.system('cls' if os.name=='nt' else 'clear')
    banner()
    procs = ProcMgr()
    prefs = load_prefs()

    # Ensure dirs exist
    for d in [LOG_DIR, SKILLS_DIR, CUSTOM_TOOLS]:
        d.mkdir(exist_ok=True)

    # 1. System
    hw = SystemInfo()

    # 2. Memory
    sec("Memory System")
    from memory import MemoryManager
    mem = MemoryManager(hw_info=hw)
    info(f"Loaded: user profile, system facts, error log")
    ctx = mem.build_context()
    if ctx:
        for line in ctx.split('\n')[:3]:
            dim(line[:70])
    else:
        dim("(fresh start — memory will build over time)")

    # 3. Llama server
    sec("Llama.cpp Server")
    if not LLAMA_EXE.exists():
        err(f"llama-server.exe not found in {LLAMA_BIN}")
        input("  Press Enter..."); return
    info("Found: llama-server.exe")
    if (LLAMA_BIN/"ggml-cuda.dll").exists(): info(f"CUDA: {S.GRN}Loaded{S.R}")

    # 4. Models
    sec("Available Models")
    models = discover_models()
    if not models:
        err("No GGUF models (>50MB) in model/ or models/ folder.")
        input("  Press Enter..."); return
    for i,m in enumerate(models):
        fits = f"{S.GRN}fits GPU{S.R}" if m.size_mb<(hw.vram_mb-400) else f"{S.YLW}partial{S.R}"
        print(f"  {S.CYN}[{i+1}]{S.R} {m.display()}")
        dim(f"{m.quant} · {m.size_gb:.1f}GB · {m.quality} · {fits}")

    selected = None
    last = prefs.get('last_model','')
    if len(models)==1:
        selected=models[0]; info(f"Auto-selected: {selected.display()}")
    else:
        default=""
        for i,m in enumerate(models):
            if m.filename==last: default=str(i+1)
        pr=f"\n  Select [1-{len(models)}]"+(f" (Enter={default})" if default else "")+": "
        while not selected:
            c=input(pr).strip() or default
            if c.isdigit() and 1<=int(c)<=len(models): selected=models[int(c)-1]
            else: warn("Invalid.")
    prefs['last_model']=selected.filename; save_prefs(prefs)

    # 5. Optimize
    sec("Optimization")
    opt = hw.optimize(selected.size_mb, selected.params_b)
    info(f"GPU: {opt['gpu_layers']} layers{'  (full)' if opt['gpu_layers']>=999 else ''} "
         f"· Threads: {opt['threads']} · Ctx: {opt['ctx_size']} · Batch: {opt['batch']}")

    # 6. Start server
    sec("Starting Server")
    if procs.is_running("llama-server.exe"):
        info("llama-server already running")
    else:
        step("Starting llama-server (hidden)...")
        cmd = [str(LLAMA_EXE), "-m",str(selected.path), "-c",str(opt['ctx_size']),
               "-t",str(opt['threads']), "-b",str(opt['batch']),
               "-ngl",str(opt['gpu_layers']), "--port",str(LLAMA_PORT),
               "--host",LLAMA_HOST]
        procs.start_hidden("llama-server", cmd)
        step("Loading model...")
        if procs.wait_health(f"http://{LLAMA_HOST}:{LLAMA_PORT}/health"):
            info(f"Server {S.GRN}ready{S.R} on port {LLAMA_PORT}")
        else:
            err("Failed to start. Check logs/llama-server.log")
            input("  Press Enter..."); return

    # 7. Multi-Agent Coordinator
    sec("Agent System")
    from agents import Coordinator
    coordinator = Coordinator(selected.model_id(), hw, memory_mgr=mem)
    info(f"Team Leader initialized")
    info(f"Workers: researcher, coder, file_manager, pc_control")

    # 8. Chat
    os.system('cls' if os.name=='nt' else 'clear')
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{VERSION} · Multi-Agent Ready      ║
  ╚══════════════════════════════════════════════╝{S.R}
  {S.D}Model:   {selected.display()} [{selected.quant}]
  GPU:     {opt['gpu_layers']} layers · Ctx: {opt['ctx_size']}
  Agents:  🎯 Coordinator → 👷 researcher · coder · file_mgr · pc_ctrl
  Memory:  💾 Profile · Facts · Errors · Conversations · Instructions
  ESC:     Pause/Resume during execution
  Commands: /help /status /clear /new /memory /exit{S.R}
""")
    hr()

    while True:
        try: user_in = input(f"\n  {S.GRN}You ❯{S.R} ").strip()
        except (EOFError, KeyboardInterrupt): break
        if not user_in: continue

        if user_in.startswith('/'):
            cl=user_in.lower().split()[0]
            if cl in ('/exit','/quit','/q'): break
            elif cl in ('/clear','/cls'):
                os.system('cls' if os.name=='nt' else 'clear'); banner(); continue
            elif cl == '/new':
                coordinator.clear(); info("New conversation!"); continue
            elif cl == '/status':
                sec("Status")
                info(f"Model: {selected.display()}")
                info(f"Server: {'✓' if procs.is_running('llama-server.exe') else '✗'}")
                info(f"History: {len(coordinator.history)} msgs")
                info(f"Memory: {len(mem.conversation.messages)} logged"); continue
            elif cl == '/memory':
                sec("Memory")
                print(f"  {S.B}User:{S.R} {mem.user.summary()}")
                print(f"  {S.B}Facts:{S.R} {mem.facts.summary()}")
                lessons = mem.errors.get_lessons()
                if lessons: print(f"  {S.B}Errors:{S.R}\n{lessons}")
                recent = mem.conversation.get_recent_summaries()
                if recent: print(f"  {S.B}History:{S.R}\n{recent}")
                continue
            elif cl == '/help':
                print(f"""
  {S.B}Commands:{S.R}      /exit /clear /new /status /memory /help
  {S.B}ESC:{S.R}           Pause/Resume during execution
  {S.B}Architecture:{S.R}
    🎯 Coordinator (Team Leader) receives your request
    → Simple tasks: handles directly using tools
    → Complex tasks: delegates to specialized workers:
      👷 researcher  — web search, info gathering
      👷 coder       — write code, run commands
      👷 file_manager — create/read/delete/move files
      👷 pc_control  — mouse, keyboard, screenshots
  {S.B}Memory:{S.R}        Persists between sessions:
    💾 User profile, system facts, error patterns
    📋 Conversation logs + summaries
    📝 Self-maintained instructions (learns from mistakes)
  {S.B}Examples:{S.R}
    "Create a poem and save to Desktop"
    "Search for latest Python news and save to notes.txt"
    "Find all large files in Downloads"
    "Open calculator"
"""); continue
            else: warn(f"Unknown: {user_in}"); continue

        # Agent query
        print()
        response = coordinator.send(user_in, print_fn=agent_print)
        if response:
            print(f"\n  {S.CYN}AI ❯{S.R} {response}")
        else:
            err("No response.")
        hr()

    # Cleanup: save memory
    sec("Saving")
    step("Saving memory...")
    mem.save_session()
    info("Memory saved")

    print(); hr()
    try: kill=input(f"  Stop llama-server? ({S.GRN}Y{S.R}/{S.RED}N{S.R}): ").strip().lower()
    except: kill='n'
    if kill=='y': step("Stopping..."); procs.kill("llama-server.exe"); info("Done.")
    else: info(f"Server left running (port {LLAMA_PORT}).")
    procs.cleanup()
    print(f"\n  {S.D}Goodbye! 👋{S.R}\n")

if __name__ == "__main__":
    main()
