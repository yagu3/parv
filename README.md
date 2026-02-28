# YaguAI - Parv

> **Local AI Agent** powered by llama.cpp — runs any GGUF model on your hardware.  
> Multi-agent architecture with persistent memory, self-improvement, and full PC control.

## Features

- 🧠 **Multi-Agent** — Coordinator + 4 specialized workers (researcher, coder, file_manager, pc_control)
- 💾 **Persistent Memory** — User profile, system facts, conversation logs, error tracking
- 🔧 **21 Built-in Tools** — File ops, shell commands, Python exec, web search, screenshots, mouse/keyboard
- 🎯 **Self-Improvement** — Tracks errors, learns patterns, maintains its own instructions
- 🖥️ **System-Aware** — Auto-detects CPU/GPU/RAM, optimizes model loading automatically
- 📦 **Portable** — Copy folder to any Windows PC and run

## Quick Start

1. **Put your GGUF model** in the `model/` folder
2. **Build llama.cpp** with CUDA in the `llama.cpp/` folder (or use prebuilt binaries)
3. Run:
   ```
   python myai.py
   ```

## Requirements

- Python 3.8+
- Windows 10/11
- NVIDIA GPU recommended (CUDA support)

## Project Structure

```
├── myai.py          # Main entry — startup, UI, agent orchestration
├── agents.py        # Multi-agent system — coordinator + workers
├── tools.py         # 21 built-in tools — files, commands, PC control
├── memory.py        # Persistent memory — profile, facts, errors, logs
├── run.bat          # One-click launcher
├── model/           # Put your .gguf models here (git-ignored)
├── llama.cpp/       # Build llama.cpp here (git-ignored)
├── memory/          # Persistent memory storage (auto-created)
├── skills/          # Learned skills (auto-created)
├── tools/           # Custom tools (auto-created)
└── logs/            # Runtime logs (git-ignored)
```

## Architecture

```
User → Coordinator (Team Leader)
         ├── Simple tasks → Direct tool execution
         └── Complex tasks → Delegate to workers:
              ├── 🔍 researcher (web search, info gathering)
              ├── 💻 coder (code, commands, Python)
              ├── 📁 file_manager (files, downloads)
              └── 🖱️ pc_control (mouse, keyboard, screenshots)
```

## License

MIT
