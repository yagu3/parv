"""System detection — CPU, GPU, RAM, screen. Safe optimization."""
import os, subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()

def _ps(cmd):
    try:
        r = subprocess.run(["powershell","-NoProfile","-Command",cmd],
            capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        return r.stdout.strip()
    except: return ""

class SystemInfo:
    def __init__(self):
        self.cpu="?"; self.cores=4; self.threads=8
        self.gpu="?"; self.vram_mb=0; self.has_cuda=False
        self.ram_total=0; self.ram_free=0
        self.user=os.environ.get("USERNAME","User")
        self.desktop=str(Path(os.environ.get("USERPROFILE","C:\\Users\\User"))/"Desktop")

    def detect(self):
        from core.ui import info, sec
        sec("System")
        # CPU
        r=_ps("(Get-CimInstance Win32_Processor|Select -First 1).Name")
        if r: self.cpu=r.strip()
        r=_ps("(Get-CimInstance Win32_Processor|Select -First 1).NumberOfCores")
        if r.isdigit(): self.cores=int(r)
        r=_ps("(Get-CimInstance Win32_Processor|Select -First 1).NumberOfLogicalProcessors")
        if r.isdigit(): self.threads=int(r)
        info(f"CPU: {self.cpu}")
        # RAM
        r=_ps("$o=Get-CimInstance Win32_OperatingSystem;"
              "[math]::Round($o.TotalVisibleMemorySize/1024).ToString()+'|'+"
              "[math]::Round($o.FreePhysicalMemory/1024).ToString()")
        if '|' in r:
            p=r.split('|')
            self.ram_total=int(p[0]) if p[0].isdigit() else 0
            self.ram_free=int(p[1]) if p[1].isdigit() else 0
        info(f"RAM: {self.ram_total//1024}GB total, {self.ram_free}MB free")
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
        llama_bin = ROOT/"llama.cpp"/"build"/"bin"
        if (llama_bin/"ggml-cuda.dll").exists(): self.has_cuda=True
        info(f"GPU: {self.gpu} ({self.vram_mb}MB VRAM)")
        return self

    def optimize(self, model_mb):
        """Safe optimization — uses only REAL RAM, no swap."""
        t = max(1, self.cores - 1)
        ngl = 0
        if self.has_cuda and self.vram_mb > 0:
            avail = self.vram_mb - 300
            ngl = 999 if model_mb <= avail else max(1, int(avail / model_mb * 200))

        # Context based on ACTUAL free RAM — conservative
        free = self.ram_free  # in MB
        if free < 1500:
            ctx = 2048
        elif free < 3000:
            ctx = 2048  # Stay safe
        elif free < 5000:
            ctx = 4096
        else:
            ctx = 8192

        return {
            'threads': t, 'gpu_layers': ngl, 'ctx_size': ctx,
            'batch': 512,
            # KV cache quantization — reduces KV memory significantly
            'cache_type_k': 'q8_0', 'cache_type_v': 'q8_0',
            'flash_attn': True
        }

    def summary(self):
        return f"{self.gpu} ({self.vram_mb}MB) | {self.ram_free}MB free"
