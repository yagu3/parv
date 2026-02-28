#!/usr/bin/env python3
"""YaguAI v6 — Clean modular entry point."""
import os, sys, json, subprocess, time, re
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from core.ui import *
from core.system import SystemInfo, ROOT
from core.llm import LLM
from core.agent import Agent
from tools import get_all_schemas, execute_any
from memory import Memory

VERSION = "7.0.0"
LLAMA_EXE = ROOT / "llama.cpp" / "build" / "bin" / "llama-server.exe"
MODEL_DIRS = [ROOT/"model", ROOT/"models"]
PREFS = ROOT / ".ai_preferences.json"
LOGS = ROOT / "logs"

# ═══ MODEL DISCOVERY ═══
class Model:
    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        self.mb = self.path.stat().st_size / (1024*1024)
        self.gb = self.mb / 1024
        n = self.name.replace('.gguf','')
        qm = re.search(r'[_\-]((?:IQ\d_\w+)|(?:[QF](?:16|32|\d+)(?:_K)?(?:_[SMLX])?))', n, re.I)
        self.quant = qm.group(1).upper() if qm else "?"
        pm = re.search(r'(\d+\.?\d*)[Bb]', n)
        self.params = pm.group(1)+"B" if pm else ""
        self.family = n[:qm.start()].replace('-',' ').replace('_',' ').strip() if qm else n
        low = n.lower()
        self.vision = any(x in low for x in ['vl','vision','llava','minicpm'])
    def display(self):
        parts = [x for x in [self.family, self.params] if x]
        d = " · ".join(parts) or self.name
        return d + (" 👁️" if self.vision else "")
    def id(self): return self.name.replace('.gguf','')

def find_models():
    models = []
    for d in MODEL_DIRS:
        if d.exists():
            for f in d.glob("**/*.gguf"):
                if f.stat().st_size > 50*1024*1024:
                    models.append(Model(f))
    return sorted(models, key=lambda m: m.mb)

# ═══ PROCESS MGR ═══
class Procs:
    def __init__(self): self._p = {}
    def running(self, n):
        try:
            r = subprocess.run(["tasklist","/FI",f"IMAGENAME eq {n}","/FO","CSV","/NH"],
                capture_output=True,text=True,timeout=10,creationflags=0x08000000)
            return n.lower() in r.stdout.lower()
        except: return False
    def start(self, name, cmd):
        LOGS.mkdir(exist_ok=True)
        lf = open(LOGS/f"{name}.log",'w')
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=0x08000000, cwd=str(ROOT))
        self._p[name] = (p, lf)
    def kill(self, n):
        try: subprocess.run(["taskkill","/F","/IM",n],
            capture_output=True,timeout=10,creationflags=0x08000000)
        except: pass
    def cleanup(self):
        for _,(p,lf) in self._p.items():
            try: p.terminate()
            except: pass
            try: lf.close()
            except: pass

def load_prefs():
    try:
        if PREFS.exists(): return json.loads(PREFS.read_text())
    except: pass
    return {}

# ═══ MAIN ═══
def main():
    enable_ansi()
    cls()
    banner(VERSION)
    procs = Procs()
    prefs = load_prefs()

    # System
    hw = SystemInfo().detect()

    # Memory
    sec("Memory")
    mem = Memory(hw)
    ctx = mem.context()
    if ctx:
        for line in ctx.split('\n')[:2]: dim(line[:70])
    else:
        info("Fresh start")

    # Server
    sec("Server")
    if not LLAMA_EXE.exists():
        err(f"Not found: {LLAMA_EXE}"); input("Enter..."); return
    info("llama-server.exe ✓")

    # Models
    sec("Models")
    models = find_models()
    if not models:
        err("No GGUF models in model/ folder"); input("Enter..."); return
    for i, m in enumerate(models):
        fits = "✓" if m.mb < (hw.vram_mb-400) else "~"
        print(f"  {S.CYN}[{i+1}]{S.R} {m.display()} [{m.quant}] {m.gb:.1f}GB {fits}")

    sel = None
    last = prefs.get('last_model','')
    if len(models) == 1:
        sel = models[0]
    else:
        default = ""
        for i, m in enumerate(models):
            if m.name == last: default = str(i+1)
        while not sel:
            c = input(f"\n  Select [1-{len(models)}]"
                      f"{f' (Enter={default})' if default else ''}: ").strip() or default
            if c.isdigit() and 1 <= int(c) <= len(models):
                sel = models[int(c)-1]
    prefs['last_model'] = sel.name
    PREFS.write_text(json.dumps(prefs, indent=2))

    # Optimize
    sec("Optimize")
    opt = hw.optimize(sel.mb)
    info(f"GPU: {opt['gpu_layers']} layers · Ctx: {opt['ctx_size']} · "
         f"KV: {opt['cache_type_k']} · Flash: ON")
    info(f"Threads: {opt['threads']} · RAM-safe: {hw.ram_free}MB free")

    # Start server
    sec("Server")
    if procs.running("llama-server.exe"):
        info("Already running")
    else:
        step("Starting llama-server...")
        cmd = [
            str(LLAMA_EXE), "-m", str(sel.path),
            "-c", str(opt['ctx_size']),
            "-t", str(opt['threads']),
            "-b", str(opt['batch']),
            "-ngl", str(opt['gpu_layers']),
            "--port", "8080", "--host", "127.0.0.1",
            "-ctk", opt['cache_type_k'],
            "-ctv", opt['cache_type_v'],
            "-fa", "on",
        ]
        procs.start("llama-server", cmd)
        # Wait for health
        step("Loading model...")
        import urllib.request
        for _ in range(60):
            try:
                if urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5).status == 200:
                    info("Ready ✓"); break
            except: pass
            time.sleep(2)
        else:
            err("Failed! Check logs/llama-server.log"); input("Enter..."); return

    # Agent
    llm = LLM(sel.id())
    schemas = get_all_schemas()
    agent = Agent(llm, hw, schemas, memory=mem)

    # Chat UI
    cls()
    v = "👁️" if sel.vision else ""
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{VERSION} · Ready                  ║
  ╚══════════════════════════════════════════════╝{S.R}
  {S.D}Model: {sel.display()} [{sel.quant}] {v}
  GPU:   {opt['gpu_layers']} layers · Ctx: {opt['ctx_size']} (RAM-safe)
  Tools: {len(schemas)} ({len(schemas)-21} custom)
  ESC:   pause/resume · /help for commands{S.R}
""")
    hr()

    while True:
        try: user_in = input(f"\n  {S.GRN}You ❯{S.R} ").strip()
        except (EOFError, KeyboardInterrupt): break
        if not user_in: continue

        if user_in.startswith('/'):
            c = user_in.lower().split()[0]
            if c in ('/exit','/quit','/q'): break
            elif c == '/clear': cls(); banner(VERSION); continue
            elif c == '/new': agent.clear(); info("New chat!"); continue
            elif c == '/memory':
                ctx = mem.context(budget_tokens=500)
                print(f"\n{ctx or '  (empty)'}"); continue
            elif c == '/status':
                info(f"Model: {sel.display()} | History: {len(agent.history)} | Ctx: {opt['ctx_size']}"); continue
            elif c == '/help':
                print(f"""
  /exit /clear /new /status /memory /help

  Just talk naturally:
    "Create a poem in apple.txt on Desktop"
    "Search the web for Python 3.13 news"
    "List files on my Desktop"
    "Open calculator"
"""); continue
            else: warn(f"Unknown: {c}"); continue

        print()
        resp = agent.send(user_in, execute_fn=execute_any)
        if resp:
            print(f"\n  {S.CYN}AI ❯{S.R} {resp}")
        else:
            err("No response")
        hr()

    # Save
    sec("Saving")
    mem.save_session(); agent.save(); info("Memory saved")
    hr()
    try: kill = input("  Stop server? (Y/N): ").strip().lower()
    except: kill = 'n'
    if kill == 'y': procs.kill("llama-server.exe"); info("Stopped")
    procs.cleanup()
    print(f"\n  {S.D}Goodbye! 👋{S.R}\n")

if __name__ == "__main__":
    main()
