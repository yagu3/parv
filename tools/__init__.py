"""Tools — built-in + auto-loaded custom tools."""
import os, sys, json, subprocess, re, base64, time, tempfile, shutil, html
import ctypes, ctypes.wintypes
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
user32 = ctypes.windll.user32

def _ps(cmd):
    try:
        r = subprocess.run(["powershell","-NoProfile","-Command",cmd],
            capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        return r.stdout.strip()
    except: return ""

# ════ SCHEMA HELPER ═══
def _t(name, desc, params):
    props, req = {}, []
    for pn, (pt, pd, rq) in params.items():
        props[pn] = {"type": pt, "description": pd}
        if rq: req.append(pn)
    return {"type":"function","function":{"name":name,"description":desc,
            "parameters":{"type":"object","properties":props,"required":req}}}

# ═══ BUILT-IN SCHEMAS ═══
BUILTIN_SCHEMAS = [
    _t("create_file", "Create/overwrite a file.", {
        "file_path": ("string", "Absolute path", True),
        "content": ("string", "File content to write", True)}),
    _t("read_file", "Read a file.", {
        "file_path": ("string", "Absolute path", True)}),
    _t("delete_file", "Delete a file or directory.", {
        "file_path": ("string", "Path to delete", True)}),
    _t("move_file", "Move/rename a file.", {
        "source": ("string", "Source", True),
        "destination": ("string", "Destination", True)}),
    _t("find_files", "Search files by pattern.", {
        "directory": ("string", "Directory to search", True),
        "pattern": ("string", "Glob pattern like *.txt", True)}),
    _t("list_directory", "List directory contents.", {
        "dir_path": ("string", "Directory path", True)}),
    _t("create_directory", "Create a directory.", {
        "dir_path": ("string", "Path to create", True)}),
    _t("run_command", "Run a shell command.", {
        "command": ("string", "Command to run", True),
        "cwd": ("string", "Working directory", False)}),
    _t("python_exec", "Execute Python code.", {
        "code": ("string", "Python code", True)}),
    _t("web_search", "Search the web. Returns actual text content from results.", {
        "query": ("string", "Search query", True)}),
    _t("open_application", "Open an app, file, or URL.", {
        "target": ("string", "What to open", True)}),
    _t("take_screenshot", "Screenshot the screen.", {}),
    _t("mouse_click", "Click at screen coordinates.", {
        "x": ("integer", "X", True), "y": ("integer", "Y", True),
        "button": ("string", "left/right/double", False)}),
    _t("mouse_move", "Move cursor.", {
        "x": ("integer", "X", True), "y": ("integer", "Y", True)}),
    _t("keyboard_type", "Type text.", {
        "text": ("string", "Text to type", True)}),
    _t("keyboard_hotkey", "Press key combo like ctrl+s.", {
        "keys": ("string", "Key combo", True)}),
    _t("clipboard_get", "Get clipboard text.", {}),
    _t("clipboard_set", "Set clipboard text.", {
        "text": ("string", "Text to copy", True)}),
    _t("download_file", "Download from URL.", {
        "url": ("string", "URL", True),
        "save_path": ("string", "Save path", True)}),
    _t("get_active_window", "Get active window info.", {}),
    _t("wait", "Wait seconds.", {
        "seconds": ("number", "Seconds", True)}),
]

# ═══ KEY MAPS ═══
VK = {
    'enter':0x0D,'tab':0x09,'escape':0x1B,'space':0x20,'backspace':0x08,
    'delete':0x2E,'home':0x24,'end':0x23,'up':0x26,'down':0x28,'left':0x25,'right':0x27,
    'ctrl':0xA2,'alt':0xA4,'shift':0xA0,'win':0x5B,
    'f1':0x70,'f2':0x71,'f3':0x72,'f4':0x73,'f5':0x74,'f6':0x75,
    **{c:ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz'},
    **{str(i):0x30+i for i in range(10)},
}

def _screenshot_b64():
    tmp = os.path.join(tempfile.gettempdir(), "yaguai_screen.png")
    _ps(f"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height)
$g=[System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size)
$g.Dispose();$b.Save('{tmp}');$b.Dispose()""")
    if os.path.exists(tmp):
        with open(tmp,'rb') as f: return base64.b64encode(f.read()).decode()
    return None

# ═══ EXECUTOR ═══
def execute(name, args):
    """Execute a tool → (result_text, image_b64_or_None)."""
    try:
        if name == "create_file":
            fp = Path(args.get("file_path",""))
            content = args.get("content", "")
            if not fp.name: return "✗ No file_path provided", None
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"✓ Created: {fp} ({len(content)} bytes)", None

        elif name == "read_file":
            fp = Path(args.get("file_path",""))
            if not fp.exists(): return f"✗ Not found: {fp}", None
            c = fp.read_text(encoding="utf-8", errors="replace")
            return (c[:3000]+"...(truncated)" if len(c)>3000 else c) or "(empty)", None

        elif name == "delete_file":
            fp = Path(args.get("file_path",""))
            if fp.is_file(): fp.unlink(); return f"✓ Deleted: {fp}", None
            elif fp.is_dir(): shutil.rmtree(str(fp)); return f"✓ Deleted dir: {fp}", None
            return f"✗ Not found: {fp}", None

        elif name == "move_file":
            shutil.move(args["source"], args["destination"])
            return f"✓ Moved: {args['source']} → {args['destination']}", None

        elif name == "find_files":
            d = Path(args.get("directory",""))
            if not d.exists(): return f"✗ Not found: {d}", None
            files = list(d.glob(args.get("pattern","*")))[:20]
            return "\n".join(str(f) for f in files) or "(none)", None

        elif name == "list_directory":
            dp = Path(args.get("dir_path",""))
            if not dp.exists(): return f"✗ Not found: {dp}", None
            items = []
            for item in sorted(dp.iterdir()):
                icon = "📁" if item.is_dir() else "📄"
                items.append(f"{icon} {item.name}")
                if len(items) >= 30: items.append("...more"); break
            return "\n".join(items) or "(empty)", None

        elif name == "create_directory":
            dp = Path(args.get("dir_path",""))
            dp.mkdir(parents=True, exist_ok=True)
            return f"✓ Created: {dp}", None

        elif name == "run_command":
            cwd = args.get("cwd", str(ROOT))
            r = subprocess.run(args.get("command",""), shell=True,
                capture_output=True, text=True, timeout=60, cwd=cwd,
                creationflags=0x08000000)
            out = (r.stdout + r.stderr).strip()
            return (out[:2000]+"...(truncated)" if len(out)>2000 else out) or "(no output)", None

        elif name == "python_exec":
            import io, contextlib
            code = args.get("code") or args.get("script") or ""
            if not code:
                for v in args.values():
                    if isinstance(v, str) and len(v) > 5: code = v; break
            if not code: return "✗ No code. Use {\"code\": \"print('hi')\"}", None
            buf = io.StringIO()
            g = {"__builtins__": __builtins__, "Path": Path, "ROOT": ROOT}
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(code, g)
            out = buf.getvalue()
            return (out[:2000]+"..." if len(out)>2000 else out) or "(no output)", None

        elif name == "web_search":
            import urllib.request, urllib.parse
            query = args.get("query") or args.get("search") or ""
            if not query: return "✗ No query", None
            # Use DuckDuckGo lite for cleaner HTML
            url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            try:
                resp = urllib.request.urlopen(req, timeout=15)
                html = resp.read().decode('utf-8', errors='replace')
                # Extract text snippets from lite results
                results = []
                # DuckDuckGo lite puts results in <td> with class="result-snippet"
                for m in re.finditer(r'class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL):
                    txt = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if txt and len(txt) > 15: results.append(txt)
                    if len(results) >= 5: break
                # Fallback: try regular page
                if not results:
                    url2 = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                    req2 = urllib.request.Request(url2, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                    resp2 = urllib.request.urlopen(req2, timeout=15)
                    html2 = resp2.read().decode('utf-8', errors='replace')
                    for m in re.finditer(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', html2, re.DOTALL):
                        txt = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                        if txt and len(txt) > 15: results.append(txt)
                        if len(results) >= 5: break
                    # Also get titles
                    if not results:
                        for m in re.finditer(r'class="result__a"[^>]*>(.*?)</a>', html2):
                            txt = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                            if txt: results.append(txt)
                            if len(results) >= 5: break
                if results:
                    return "\n".join(f"{i+1}. {html.unescape(r)}" for i,r in enumerate(results)), None
                return "No results found. The web search may be blocked.", None
            except Exception as e:
                return f"✗ Search error: {e}", None

        elif name == "open_application":
            os.startfile(args.get("target",""))
            return f"✓ Opened: {args.get('target')}", None

        elif name == "take_screenshot":
            b64 = _screenshot_b64()
            return ("Screenshot captured.", b64) if b64 else ("✗ Failed", None)

        elif name == "mouse_click":
            x, y = int(args.get("x",0)), int(args.get("y",0))
            btn = args.get("button", "left")
            user32.SetCursorPos(x, y); time.sleep(0.05)
            if btn == "double":
                for _ in range(2):
                    user32.mouse_event(2,0,0,0,0); user32.mouse_event(4,0,0,0,0)
                    time.sleep(0.05)
            elif btn == "right":
                user32.mouse_event(8,0,0,0,0); user32.mouse_event(16,0,0,0,0)
            else:
                user32.mouse_event(2,0,0,0,0); user32.mouse_event(4,0,0,0,0)
            return f"✓ Clicked {btn} at ({x},{y})", None

        elif name == "mouse_move":
            user32.SetCursorPos(int(args.get("x",0)), int(args.get("y",0)))
            return f"✓ Moved to ({args.get('x')},{args.get('y')})", None

        elif name == "keyboard_type":
            text = args.get("text","").replace("'","''")
            _ps(f"Add-Type -AssemblyName System.Windows.Forms;"
                f"[System.Windows.Forms.SendKeys]::SendWait('{text}')")
            return f"✓ Typed: {args.get('text','')[:40]}", None

        elif name == "keyboard_hotkey":
            keys = [k.strip().lower() for k in args.get("keys","").split('+')]
            vks = [VK.get(k) for k in keys]
            if None in vks: return f"✗ Unknown key in: {args.get('keys')}", None
            for v in vks: user32.keybd_event(v,0,0,0)
            time.sleep(0.05)
            for v in reversed(vks): user32.keybd_event(v,0,2,0)
            return f"✓ Pressed: {args.get('keys')}", None

        elif name == "clipboard_get":
            user32.OpenClipboard(0)
            try:
                h = user32.GetClipboardData(13)
                if h:
                    ctypes.windll.kernel32.GlobalLock.restype = ctypes.c_wchar_p
                    t = ctypes.windll.kernel32.GlobalLock(h)
                    ctypes.windll.kernel32.GlobalUnlock(h)
                    return t or "(empty)", None
                return "(empty)", None
            finally: user32.CloseClipboard()

        elif name == "clipboard_set":
            _ps(f"Set-Clipboard -Value '{args.get('text','').replace(chr(39),chr(39)+chr(39))}'")
            return f"✓ Clipboard set", None

        elif name == "download_file":
            import urllib.request as ur
            ur.urlretrieve(args.get("url",""), args.get("save_path",""))
            return f"✓ Downloaded to: {args.get('save_path')}", None

        elif name == "get_active_window":
            title = ctypes.create_unicode_buffer(256)
            hwnd = user32.GetForegroundWindow()
            user32.GetWindowTextW(hwnd, title, 256)
            return f"Window: {title.value}", None

        elif name == "wait":
            time.sleep(float(args.get("seconds",1)))
            return f"✓ Waited {args.get('seconds')}s", None

        else:
            return f"✗ Unknown tool: {name}. Available: {', '.join(t['function']['name'] for t in BUILTIN_SCHEMAS)}", None

    except Exception as e:
        return f"✗ {type(e).__name__}: {e}", None


def get_all_schemas():
    """Get built-in + auto-loaded custom tool schemas."""
    schemas = list(BUILTIN_SCHEMAS)
    custom_dir = ROOT / "tools" / "custom"
    if custom_dir.exists():
        for f in custom_dir.glob("*.py"):
            if f.name.startswith("_"): continue
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(f.stem, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, 'NAME') and hasattr(mod, 'DESC'):
                    params = getattr(mod, 'PARAMS', {})
                    schemas.append(_t(mod.NAME, mod.DESC, params))
            except: pass
    return schemas


def execute_any(name, args):
    """Execute built-in or custom tool."""
    # Try built-in first
    if name in [t['function']['name'] for t in BUILTIN_SCHEMAS]:
        return execute(name, args)
    # Try custom
    custom_dir = ROOT / "tools" / "custom"
    custom_file = custom_dir / f"{name}.py"
    if custom_file.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(name, custom_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, 'execute'):
                return mod.execute(args)
        except Exception as e:
            return f"✗ Custom tool error: {e}", None
    return f"✗ Unknown tool: {name}", None
