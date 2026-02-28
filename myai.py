#!/usr/bin/env python3
"""
YaguAI v5.0 — Reliable Local AI Agent
Single smart agent · KV cache quantization · Context management · Robust parsing
"""

import os, sys, json, subprocess, time, re, msvcrt
from pathlib import Path
import urllib.request, urllib.error

ROOT = Path(__file__).parent.resolve()

# Late imports to allow tools.py to define ROOT first
sys.path.insert(0, str(ROOT))
from tools import TOOL_SCHEMAS, execute_tool, _ps

# ═══════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════
MODEL_DIRS  = [ROOT/"model", ROOT/"models"]
LLAMA_BIN   = ROOT/"llama.cpp"/"build"/"bin"
LLAMA_EXE   = LLAMA_BIN/"llama-server.exe"
PREFS_FILE  = ROOT/".ai_preferences.json"
LOG_DIR     = ROOT/"logs"
LLAMA_HOST  = "127.0.0.1"
LLAMA_PORT  = 8080
VERSION     = "5.0.0"

# ═══════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════
class S:
    R="\033[0m"; B="\033[1m"; D="\033[2m"
    RED="\033[91m"; GRN="\033[92m"; YLW="\033[93m"
    BLU="\033[94m"; MAG="\033[95m"; CYN="\033[96m"

def _ansi():
    try:
        import ctypes; k=ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except: os.system('')

def banner():
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{VERSION}                          ║
  ║   KV-Q4 · Flash Attention · Smart Agent      ║
  ╚══════════════════════════════════════════════╝{S.R}""")

def info(m):  print(f"  {S.GRN}✓{S.R} {m}")
def warn(m):  print(f"  {S.YLW}⚠{S.R} {m}")
def err(m):   print(f"  {S.RED}✗{S.R} {m}")
def step(m):  print(f"  {S.BLU}→{S.R} {m}")
def dim(m):   print(f"    {S.D}{m}{S.R}")
def sec(m):   print(f"\n  {S.B}{S.CYN}── {m} ──{S.R}")
def hr():     print(f"  {S.D}{'─'*46}{S.R}")

# ═══════════════════════════════════════
# SYSTEM DETECTION
# ═══════════════════════════════════════
class SystemInfo:
    def __init__(self):
        self.cpu="?"; self.cores=4; self.threads=8
        self.gpu="?"; self.vram_mb=0; self.has_cuda=False
        self.ram_total=0; self.ram_free=0
        self.user=os.environ.get("USERNAME","User")
        self.desktop=str(Path(os.environ.get("USERPROFILE","C:\\Users\\User"))/"Desktop")
        self._detect()

    def _detect(self):
        sec("System")
        # CPU
        r=_ps("(Get-CimInstance Win32_Processor|Select -First 1).Name+'|'+"
              "(Get-CimInstance Win32_Processor|Select -First 1).NumberOfCores+'|'+"
              "(Get-CimInstance Win32_Processor|Select -First 1).NumberOfLogicalProcessors")
        if '|' in r:
            p=r.split('|'); self.cpu=p[0].strip()
            self.cores=int(p[1]) if p[1].isdigit() else 4
            self.threads=int(p[2]) if p[2].isdigit() else 8
        info(f"CPU: {self.cpu}")
        # RAM
        r=_ps("$o=Get-CimInstance Win32_OperatingSystem;"
              "[math]::Round($o.TotalVisibleMemorySize/1024).ToString()+'|'+"
              "[math]::Round($o.FreePhysicalMemory/1024).ToString()")
        if '|' in r:
            p=r.split('|')
            self.ram_total=int(p[0]) if p[0].isdigit() else 0
            self.ram_free=int(p[1]) if p[1].isdigit() else 0
        info(f"RAM: {self.ram_total//1024}GB ({self.ram_free//1024}GB free)")
        # GPU
        try:
            r=subprocess.run(["nvidia-smi","--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"],capture_output=True,text=True,
                timeout=10,creationflags=0x08000000)
            if r.returncode==0 and r.stdout.strip():
                p=r.stdout.strip().split(',')
                self.gpu=p[0].strip()
                self.vram_mb=int(p[1].strip()) if len(p)>1 else 0
                self.has_cuda=True
        except: pass
        if (LLAMA_BIN/"ggml-cuda.dll").exists(): self.has_cuda=True
        info(f"GPU: {self.gpu} ({self.vram_mb}MB)")

    def optimize(self, model_mb):
        """Smart optimization with KV cache quantization for 4x context."""
        t = max(1, self.cores - 1)
        ngl = 0
        if self.has_cuda and self.vram_mb > 0:
            avail = self.vram_mb - 300
            ngl = 999 if model_mb <= avail else max(1, int(avail / model_mb * 200))
        # KV cache quantization: q4_0 uses ~4x less memory → much bigger context
        # With q4_0 KV cache: 1GB VRAM leftover = ~16K context (vs ~4K with f16)
        vram_for_ctx = max(0, self.vram_mb - model_mb - 200) if ngl >= 50 else 0
        ram_for_ctx = self.ram_free - model_mb - 1024
        avail_for_ctx = vram_for_ctx + (ram_for_ctx if ram_for_ctx > 0 else 0)
        # With q4_0 KV: ~0.5MB per 1K ctx for 4B model, ~1MB per 1K for 12B
        if avail_for_ctx > 4000:
            ctx = 16384
        elif avail_for_ctx > 2000:
            ctx = 8192
        elif avail_for_ctx > 1000:
            ctx = 4096
        else:
            ctx = 2048
        return {
            'threads': t, 'gpu_layers': ngl, 'ctx_size': ctx,
            'batch': 512, 'cache_type_k': 'q4_0', 'cache_type_v': 'q4_0',
            'flash_attn': True
        }

    def summary(self):
        return f"{self.cpu} | {self.gpu} ({self.vram_mb}MB) | {self.ram_total//1024}GB RAM"

# ═══════════════════════════════════════
# MODEL DISCOVERY
# ═══════════════════════════════════════
class ModelInfo:
    def __init__(self, path):
        self.path=Path(path); self.filename=self.path.name
        self.size_mb=self.path.stat().st_size/(1024*1024)
        self.size_gb=self.size_mb/1024
        self.family=""; self.params=""; self.params_b=0.0
        self.quant=""; self.quality=""; self.has_vision=False
        self._parse()
    def _parse(self):
        name=self.filename.replace('.gguf','')
        qm=re.search(r'[_\-]((?:IQ\d_\w+)|(?:[QF](?:16|32|\d+)(?:_K)?(?:_[SMLX])?))',name,re.I)
        if qm: self.quant=qm.group(1).upper(); name=name[:qm.start()]
        pm=re.search(r'[_\-]?(\d+\.?\d*)[Bb]',name)
        if pm:
            self.params=pm.group(1)+"B"; self.params_b=float(pm.group(1))
            idx=name.find(pm.group(0))
            if idx>0: self.family=name[:idx].replace('-',' ').replace('_',' ').strip()
        else: self.family=name.replace('-',' ').replace('_',' ').strip()
        low=self.filename.lower()
        if any(x in low for x in ['vl','vision','visual','llava','minicpm']): self.has_vision=True
        q=self.quant
        if 'Q8' in q or q in ('F32','F16'): self.quality="★★★"
        elif 'Q5' in q or 'Q6' in q: self.quality="★★½"
        elif 'Q4' in q: self.quality="★★"
        elif 'Q3' in q: self.quality="★½"
        else: self.quality="?"
    def display(self):
        parts=[x for x in [self.family,self.params] if x]
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
            try: p.terminate(); p.wait(3)
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
        if msvcrt.getch()==b'\x1b':
            print(f"\n  {S.YLW}⏸  PAUSED — ESC to resume{S.R}", flush=True)
            while True:
                if msvcrt.kbhit() and msvcrt.getch()==b'\x1b':
                    print(f"  {S.GRN}▶  RESUMED{S.R}\n", flush=True); return
                time.sleep(0.1)

# ═══════════════════════════════════════
# TOOL LIST (compact, for system prompt)
# ═══════════════════════════════════════
TOOL_NAMES = [t['function']['name'] for t in TOOL_SCHEMAS]
COMPACT_TOOLS = "\n".join(
    f"- {t['function']['name']}: {t['function']['description']}"
    for t in TOOL_SCHEMAS
)

# ═══════════════════════════════════════
# SMART AGENT — robust parsing, context mgmt
# ═══════════════════════════════════════
SYSTEM = """You are YaguAI, an AI agent controlling a Windows PC. You MUST use tools to act.

TOOLS:
{tools}

FORMAT — use EXACTLY this (plain text, no markdown, no #):
THINK: what I need to do
TOOL: tool_name
INPUT: {{"param": "value"}}

Then STOP. The system shows the RESULT. Then continue or finish:
THINK: done
ANSWER: what I accomplished

RULES:
- ALWAYS use tools. Never give instructions to the user.
- One TOOL per turn. STOP after INPUT line.
- NEVER write RESULT yourself. Wait for the system.
- For create_file: include full content in the "content" param.
- For web_search: use "query" param.
- For python_exec: use "code" param.
- For run_command: use "command" param.
- Desktop: {desktop}
- Workspace: {workspace}
- System: {sysinfo}"""

class Agent:
    def __init__(self, model_id, hw, mem=None):
        self.model = model_id
        self.url = f"http://{LLAMA_HOST}:{LLAMA_PORT}/v1/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        self.memory = mem
        self.history = []
        self.system_prompt = SYSTEM.format(
            tools=COMPACT_TOOLS, desktop=hw.desktop,
            workspace=ROOT, sysinfo=hw.summary()
        )

    def _call(self, messages):
        payload = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": 0.5, "max_tokens": 1024,
            "stop": ["RESULT:", "Result:", "result:",
                     "Observation:", "# RESULT", "## RESULT",
                     "\nYou ❯"]
        }).encode('utf-8')
        req = urllib.request.Request(self.url, data=payload,
                                     headers=self.headers, method='POST')
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read().decode('utf-8'))['choices'][0]['message']['content'].strip()

    def _parse_tool(self, text):
        """Extract TOOL and INPUT — handles all model quirks."""
        # Strip all markdown formatting
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '').replace('`', '')

        # Find tool name — try multiple patterns
        tool = None
        for pattern in [
            r'TOOL:\s*(\w+)', r'Tool:\s*(\w+)', r'Action:\s*(\w+)',
            r'action:\s*(\w+)', r'tool:\s*(\w+)',
            r'TOOL\s*(\w+)', r'Use:\s*(\w+)'
        ]:
            m = re.search(pattern, clean)
            if m and m.group(1) in TOOL_NAMES:
                tool = m.group(1); break
            elif m:
                # Fuzzy match tool name
                candidate = m.group(1).lower()
                for tn in TOOL_NAMES:
                    if candidate in tn or tn in candidate:
                        tool = tn; break
                if tool: break

        if not tool:
            return None, None

        # Find JSON args — try multiple patterns
        args = {}
        for pattern in [
            r'INPUT:\s*(\{[^}]*\})', r'Input:\s*(\{[^}]*\})',
            r'input:\s*(\{[^}]*\})', r'Action Input:\s*(\{[^}]*\})',
            r'args:\s*(\{[^}]*\})', r'(\{[^}]*\})'
        ]:
            m = re.search(pattern, clean, re.DOTALL)
            if m:
                try:
                    args = json.loads(m.group(1))
                    break
                except json.JSONDecodeError:
                    # Try fixing common JSON issues
                    fixed = m.group(1).replace("'", '"')
                    try:
                        args = json.loads(fixed)
                        break
                    except: pass

        return tool, args

    def _parse_answer(self, text):
        """Extract final answer."""
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '')
        for pat in [r'ANSWER:\s*(.*)', r'Answer:\s*(.*)',
                    r'Final Answer:\s*(.*)', r'final answer:\s*(.*)']:
            m = re.search(pat, clean, re.DOTALL)
            if m: return m.group(1).strip()
        return None

    def _compact_history(self):
        """Keep history manageable — summarize old messages."""
        if len(self.history) > 8:
            # Keep first user msg + last 6 messages
            old = self.history[:-6]
            summary = "Previous: "
            user_msgs = [m['content'][:60] for m in old if m['role']=='user']
            summary += " → ".join(user_msgs[:3]) if user_msgs else "earlier conversation"
            self.history = [{"role":"user","content":summary}] + self.history[-6:]

    def send(self, user_message):
        """Main agent loop — robust tool execution."""
        self.history.append({"role":"user","content":user_message})
        self._compact_history()
        if self.memory:
            self.memory.log_message("user", user_message)

        messages = [{"role":"system","content":self.system_prompt}] + self.history

        for round_n in range(8):
            check_pause()
            try:
                response = self._call(messages)
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    # Context too long — aggressive trim
                    warn("Context full, trimming...")
                    self.history = self.history[-4:]
                    messages = [{"role":"system","content":self.system_prompt}] + self.history
                    try: response = self._call(messages)
                    except Exception as e2:
                        err(f"Still failing: {e2}"); return None
                else:
                    err(f"Server error ({e.code})")
                    return None
            except Exception as e:
                err(f"Error: {e}"); return None

            # Check for final answer FIRST
            answer = self._parse_answer(response)
            if answer and not self._parse_tool(response)[0]:
                # Has answer and NO tool call → done
                self.history.append({"role":"assistant","content":response})
                if self.memory: self.memory.log_message("assistant", answer)
                return answer

            # Check for tool call
            tool, args = self._parse_tool(response)
            if tool:
                # Show thinking
                for pat in [r'THINK:\s*(.*?)(?:TOOL:|Tool:|Action:)',
                            r'Thought:\s*(.*?)(?:TOOL:|Tool:|Action:)']:
                    m = re.search(pat, response, re.DOTALL|re.I)
                    if m:
                        thought = m.group(1).strip()[:100]
                        if thought: dim(f"💭 {thought}")
                        break

                # Show tool call
                preview = ""
                for k in ["file_path","command","query","code","target","text","dir_path","url"]:
                    if k in args:
                        preview = str(args[k])[:55]; break
                print(f"  {S.MAG}⚡ {tool}{S.R}  {S.D}{preview}{S.R}")

                check_pause()

                # Execute tool
                result, img = execute_tool(tool, args)
                rline = result.split('\n')[0][:80]
                if "✓" in rline:
                    dim(f"{S.GRN}{rline}{S.R}")
                elif "✗" in rline:
                    dim(f"{S.RED}{rline}{S.R}")
                    if self.memory:
                        self.memory.log_error(tool, result, user_message)
                else:
                    dim(rline)

                # Feed result back
                messages.append({"role":"assistant","content":response})
                messages.append({"role":"user","content":
                    f"RESULT: {result}\n\nUse another TOOL or give ANSWER."})
                self.history.append({"role":"assistant","content":response})
                self.history.append({"role":"user","content":f"RESULT: {result}"})
                continue

            # No tool, no answer — check if it's also not a final answer
            if answer:
                self.history.append({"role":"assistant","content":response})
                return answer

            # Plain text response (model didn't use format)
            self.history.append({"role":"assistant","content":response})
            if self.memory: self.memory.log_message("assistant", response)
            return response

        warn("Max rounds reached")
        return None

    def clear(self):
        self.history = []

# ═══════════════════════════════════════
# PREFS
# ═══════════════════════════════════════
def load_prefs():
    try:
        if PREFS_FILE.exists():
            with open(PREFS_FILE) as f: return json.load(f)
    except: pass
    return {}
def save_prefs(p):
    with open(PREFS_FILE,'w') as f: json.dump(p,f,indent=2)

# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
def main():
    _ansi()
    os.system('cls' if os.name=='nt' else 'clear')
    banner()
    procs = ProcMgr()
    prefs = load_prefs()

    # Dirs
    for d in [LOG_DIR, ROOT/"skills", ROOT/"tools"]:
        d.mkdir(exist_ok=True)

    # System
    hw = SystemInfo()

    # Memory
    sec("Memory")
    from memory import MemoryManager
    mem = MemoryManager(hw_info=hw)
    ctx = mem.build_context()
    if ctx:
        for line in ctx.split('\n')[:2]: dim(line[:70])
    else:
        info("Fresh start (memory builds over time)")

    # Server
    sec("Server")
    if not LLAMA_EXE.exists():
        err(f"Not found: {LLAMA_EXE}"); input("Enter..."); return
    info("llama-server.exe found")

    # Models
    sec("Models")
    models = discover_models()
    if not models:
        err("No GGUF models in model/ folder"); input("Enter..."); return
    for i,m in enumerate(models):
        fits = f"{S.GRN}✓ fits{S.R}" if m.size_mb<(hw.vram_mb-400) else f"{S.YLW}partial{S.R}"
        print(f"  {S.CYN}[{i+1}]{S.R} {m.display()} [{m.quant}] {m.quality} {m.size_gb:.1f}GB {fits}")

    sel = None
    last = prefs.get('last_model','')
    if len(models)==1:
        sel=models[0]; info(f"Auto: {sel.display()}")
    else:
        default=""
        for i,m in enumerate(models):
            if m.filename==last: default=str(i+1)
        while not sel:
            c=input(f"\n  Select [1-{len(models)}]{f' (Enter={default})' if default else ''}: ").strip() or default
            if c.isdigit() and 1<=int(c)<=len(models): sel=models[int(c)-1]
    prefs['last_model']=sel.filename; save_prefs(prefs)

    # Optimize with KV cache quantization
    sec("Optimization")
    opt = hw.optimize(sel.size_mb)
    info(f"GPU: {opt['gpu_layers']} layers · Ctx: {S.GRN}{opt['ctx_size']}{S.R} "
         f"· KV: {S.GRN}q4_0{S.R} · Flash: {S.GRN}ON{S.R}")
    info(f"Threads: {opt['threads']} · Batch: {opt['batch']}")
    dim(f"KV cache Q4 = ~4x more context vs default!")

    # Start server with optimizations
    sec("Starting")
    if procs.is_running("llama-server.exe"):
        info("Already running")
    else:
        step("Starting llama-server...")
        cmd = [
            str(LLAMA_EXE),
            "-m", str(sel.path),
            "-c", str(opt['ctx_size']),
            "-t", str(opt['threads']),
            "-b", str(opt['batch']),
            "-ngl", str(opt['gpu_layers']),
            "--port", str(LLAMA_PORT),
            "--host", LLAMA_HOST,
            "-ctk", opt['cache_type_k'],   # KV cache quantization K
            "-ctv", opt['cache_type_v'],   # KV cache quantization V
            "-fa", "on",                   # Flash attention
        ]
        procs.start_hidden("llama-server", cmd)
        step("Loading model (KV-Q4 + Flash Attention)...")
        if procs.wait_health(f"http://{LLAMA_HOST}:{LLAMA_PORT}/health"):
            info(f"Server {S.GRN}ready{S.R}")
        else:
            err("Failed! Check logs/llama-server.log")
            input("Enter..."); return

    # Agent
    agent = Agent(sel.model_id(), hw, mem=mem)

    # Chat UI
    os.system('cls' if os.name=='nt' else 'clear')
    v = f"👁️ Vision" if sel.has_vision else ""
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{VERSION} · Ready                  ║
  ╚══════════════════════════════════════════════╝{S.R}
  {S.D}Model:   {sel.display()} [{sel.quant}] {v}
  GPU:     {opt['gpu_layers']} layers · Ctx: {S.GRN}{opt['ctx_size']}{S.R} · KV: q4_0
  Memory:  💾 persistent across sessions
  ESC:     pause/resume · /help for commands{S.R}
""")
    hr()

    while True:
        try: user_in = input(f"\n  {S.GRN}You ❯{S.R} ").strip()
        except (EOFError, KeyboardInterrupt): break
        if not user_in: continue

        if user_in.startswith('/'):
            c=user_in.lower().split()[0]
            if c in ('/exit','/quit','/q'): break
            elif c=='/clear':
                os.system('cls' if os.name=='nt' else 'clear'); banner(); continue
            elif c=='/new': agent.clear(); info("New chat!"); continue
            elif c=='/memory':
                sec("Memory")
                print(f"  Profile: {mem.user.summary()}")
                print(f"  Facts:   {mem.facts.summary()}")
                lessons=mem.errors.get_lessons()
                if lessons: print(f"  Errors:\n{lessons}")
                continue
            elif c=='/status':
                info(f"Model: {sel.display()} | History: {len(agent.history)} | "
                     f"Ctx: {opt['ctx_size']} | KV: q4_0"); continue
            elif c=='/help':
                print(f"""
  /exit /clear /new /status /memory /help
  ESC = pause/resume during execution
  
  Examples:
    "Create a poem in apple.txt on my Desktop"
    "Search the web for Python 3.13 features"
    "List all files on my Desktop"
    "Open notepad"
    "What command shows Windows version?"
"""); continue
            else: warn(f"Unknown: {c}"); continue

        print()
        resp = agent.send(user_in)
        if resp:
            print(f"\n  {S.CYN}AI ❯{S.R} {resp}")
        else:
            err("No response")
        hr()

    # Save & cleanup
    sec("Saving")
    mem.save_session(); info("Memory saved")
    hr()
    try: kill=input(f"  Stop server? (Y/N): ").strip().lower()
    except: kill='n'
    if kill=='y': procs.kill("llama-server.exe"); info("Stopped")
    procs.cleanup()
    print(f"\n  {S.D}Goodbye! 👋{S.R}\n")

if __name__=="__main__":
    main()
