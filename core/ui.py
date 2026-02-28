"""UI helpers — colors, banner, printing."""
import os, sys

class S:
    R="\033[0m"; B="\033[1m"; D="\033[2m"
    RED="\033[91m"; GRN="\033[92m"; YLW="\033[93m"
    BLU="\033[94m"; MAG="\033[95m"; CYN="\033[96m"

def enable_ansi():
    try:
        import ctypes; k=ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except: os.system('')

def banner(v):
    print(f"""{S.CYN}{S.B}
  ╔══════════════════════════════════════════════╗
  ║   🧠 YaguAI v{v}                          ║
  ╚══════════════════════════════════════════════╝{S.R}""")

def info(m):  print(f"  {S.GRN}✓{S.R} {m}")
def warn(m):  print(f"  {S.YLW}⚠{S.R} {m}")
def err(m):   print(f"  {S.RED}✗{S.R} {m}")
def step(m):  print(f"  {S.BLU}→{S.R} {m}")
def dim(m):   print(f"    {S.D}{m}{S.R}")
def sec(m):   print(f"\n  {S.B}{S.CYN}── {m} ──{S.R}")
def hr():     print(f"  {S.D}{'─'*46}{S.R}")
def cls():    os.system('cls' if os.name=='nt' else 'clear')
