"""
YaguAI Tools — All agent capabilities for PC control.
Zero external dependencies: uses ctypes + PowerShell.
"""
import os, sys, json, subprocess, time, re, base64, tempfile, shutil, ctypes, ctypes.wintypes
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
user32 = ctypes.windll.user32

# ═══════════════════════════════════════
# TOOL SCHEMAS (sent to LLM)
# ═══════════════════════════════════════
def _t(name, desc, params):
    """Helper to build OpenAI-format tool schema."""
    props = {}
    req = []
    for pname, (ptype, pdesc, required) in params.items():
        props[pname] = {"type": ptype, "description": pdesc}
        if required: req.append(pname)
    return {"type":"function","function":{"name":name,"description":desc,
            "parameters":{"type":"object","properties":props,"required":req}}}

TOOL_SCHEMAS = [
    _t("create_file", "Create or overwrite a file with content. Use for writing code, text, docs, etc.", {
        "file_path": ("string", "Absolute path, e.g. C:\\Users\\yagnesh\\Desktop\\story.txt", True),
        "content": ("string", "Full file content to write", True)}),
    _t("read_file", "Read contents of a file from disk.", {
        "file_path": ("string", "Absolute path of file to read", True)}),
    _t("delete_file", "Delete a file or empty directory.", {
        "file_path": ("string", "Absolute path to delete", True)}),
    _t("move_file", "Move or rename a file/folder.", {
        "source": ("string", "Source path", True),
        "destination": ("string", "Destination path", True)}),
    _t("find_files", "Search for files by name pattern in a directory.", {
        "directory": ("string", "Directory to search in", True),
        "pattern": ("string", "Glob pattern, e.g. *.txt or **/*.py", True)}),
    _t("list_directory", "List files and folders in a directory.", {
        "dir_path": ("string", "Absolute path of directory", True)}),
    _t("run_command", "Execute a shell command (cmd.exe) on the PC. Returns output.", {
        "command": ("string", "Command to run, e.g. 'dir' or 'python script.py'", True),
        "cwd": ("string", "Working directory (optional)", False)}),
    _t("python_exec", "Execute Python code directly. Has full access to the system.", {
        "code": ("string", "Python code to execute", True)}),
    _t("open_application", "Open an application, file, or URL using Windows shell.", {
        "target": ("string", "App name, file path, or URL to open, e.g. 'notepad' or 'https://google.com'", True)}),
    _t("take_screenshot", "Capture a screenshot of the entire screen. Returns the image for analysis.", {}),
    _t("mouse_click", "Click the mouse at screen coordinates (x, y).", {
        "x": ("integer", "X coordinate on screen", True),
        "y": ("integer", "Y coordinate on screen", True),
        "button": ("string", "Mouse button: left, right, or double", False)}),
    _t("mouse_move", "Move mouse cursor to screen coordinates.", {
        "x": ("integer", "X coordinate", True),
        "y": ("integer", "Y coordinate", True)}),
    _t("keyboard_type", "Type text as if from keyboard into the currently focused window.", {
        "text": ("string", "Text to type", True)}),
    _t("keyboard_hotkey", "Press a keyboard shortcut, e.g. ctrl+s, alt+tab, win+d.", {
        "keys": ("string", "Key combo like 'ctrl+c', 'alt+f4', 'enter', 'tab'", True)}),
    _t("clipboard_get", "Get current clipboard text contents.", {}),
    _t("clipboard_set", "Set clipboard text contents.", {
        "text": ("string", "Text to copy to clipboard", True)}),
    _t("download_file", "Download a file from a URL to disk.", {
        "url": ("string", "URL to download from", True),
        "save_path": ("string", "Absolute path to save the file", True)}),
    _t("get_active_window", "Get title and position of the currently active window.", {}),
    _t("wait", "Wait/sleep for a specified number of seconds.", {
        "seconds": ("number", "Seconds to wait", True)}),
    _t("create_directory", "Create a new directory/folder.", {
        "dir_path": ("string", "Absolute path of directory to create", True)}),
    _t("web_search", "Search the web using DuckDuckGo. Returns text results.", {
        "query": ("string", "Search query", True)}),
]

# ═══════════════════════════════════════
# TOOL EXECUTORS
# ═══════════════════════════════════════
def _ps(cmd):
    try:
        r = subprocess.run(["powershell","-NoProfile","-Command",cmd],
            capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        return r.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

# Virtual key codes for keyboard_hotkey
VK_MAP = {
    'enter':0x0D,'tab':0x09,'escape':0x1B,'space':0x20,'backspace':0x08,
    'delete':0x2E,'home':0x24,'end':0x23,'pageup':0x21,'pagedown':0x22,
    'up':0x26,'down':0x28,'left':0x25,'right':0x27,
    'ctrl':0xA2,'alt':0xA4,'shift':0xA0,'win':0x5B,
    'f1':0x70,'f2':0x71,'f3':0x72,'f4':0x73,'f5':0x74,'f6':0x75,
    'f7':0x76,'f8':0x77,'f9':0x78,'f10':0x79,'f11':0x7A,'f12':0x7B,
    'a':0x41,'b':0x42,'c':0x43,'d':0x44,'e':0x45,'f':0x46,'g':0x47,
    'h':0x48,'i':0x49,'j':0x4A,'k':0x4B,'l':0x4C,'m':0x4D,'n':0x4E,
    'o':0x4F,'p':0x50,'q':0x51,'r':0x52,'s':0x53,'t':0x54,'u':0x55,
    'v':0x56,'w':0x57,'x':0x58,'y':0x59,'z':0x5A,
    '0':0x30,'1':0x31,'2':0x32,'3':0x33,'4':0x34,
    '5':0x35,'6':0x36,'7':0x37,'8':0x38,'9':0x39,
}

def _screenshot_path():
    """Take screenshot using PowerShell, return temp file path."""
    tmp = os.path.join(tempfile.gettempdir(), "yaguai_screen.png")
    _ps(f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
$g.Dispose()
$bmp.Save('{tmp}')
$bmp.Dispose()
""")
    return tmp

def _screenshot_base64():
    """Take screenshot, return as base64 string."""
    path = _screenshot_path()
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')
    return None

def _key_press(vk, down=True):
    flags = 0 if down else 0x0002  # KEYEVENTF_KEYUP
    user32.keybd_event(vk, 0, flags, 0)

def execute_tool(name, args):
    """Execute a tool, return (result_text, image_base64_or_None)."""
    try:
        if name == "create_file":
            fp = Path(args["file_path"])
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(args["content"], encoding="utf-8")
            return f"✓ File created: {fp} ({len(args['content'])} bytes)", None

        elif name == "read_file":
            fp = Path(args["file_path"])
            if not fp.exists(): return f"✗ File not found: {fp}", None
            c = fp.read_text(encoding="utf-8", errors="replace")
            return (c[:4000]+"...(truncated)" if len(c)>4000 else c), None

        elif name == "delete_file":
            fp = Path(args["file_path"])
            if fp.is_file(): fp.unlink(); return f"✓ Deleted: {fp}", None
            elif fp.is_dir(): shutil.rmtree(str(fp)); return f"✓ Deleted directory: {fp}", None
            return f"✗ Not found: {fp}", None

        elif name == "move_file":
            shutil.move(args["source"], args["destination"])
            return f"✓ Moved: {args['source']} → {args['destination']}", None

        elif name == "find_files":
            d = Path(args["directory"])
            if not d.exists(): return f"✗ Directory not found: {d}", None
            files = list(d.glob(args["pattern"]))[:30]
            return "\n".join(str(f) for f in files) or "(no matches)", None

        elif name == "list_directory":
            dp = Path(args["dir_path"])
            if not dp.exists(): return f"✗ Not found: {dp}", None
            items = []
            for item in sorted(dp.iterdir()):
                p = "📁" if item.is_dir() else "📄"
                sz = ""
                if item.is_file():
                    s = item.stat().st_size
                    sz = f" ({s//(1024*1024)}MB)" if s>1048576 else f" ({s//1024}KB)" if s>1024 else ""
                items.append(f"{p} {item.name}{sz}")
                if len(items)>=40: items.append("...more"); break
            return "\n".join(items) or "(empty)", None

        elif name == "run_command":
            cwd = args.get("cwd", str(ROOT))
            r = subprocess.run(args["command"], shell=True, capture_output=True,
                text=True, timeout=120, cwd=cwd, creationflags=0x08000000)
            out = (r.stdout + r.stderr).strip()
            return (out[:3000]+"...(truncated)" if len(out)>3000 else out) or "(no output)", None

        elif name == "python_exec":
            import io, contextlib
            # Handle model sending wrong key names
            code = args.get("code") or args.get("script") or args.get("python") or ""
            if not code:
                # Try first string value
                for v in args.values():
                    if isinstance(v, str) and len(v) > 5:
                        code = v; break
            if not code:
                return "✗ No code provided. Use key 'code' with your Python code.", None
            buf = io.StringIO()
            g = {"__builtins__": __builtins__, "Path": Path, "ROOT": ROOT}
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(code, g)
            out = buf.getvalue()
            return (out[:3000]+"...(truncated)" if len(out)>3000 else out) or "(executed, no output)", None

        elif name == "open_application":
            os.startfile(args["target"])
            return f"✓ Opened: {args['target']}", None

        elif name == "take_screenshot":
            b64 = _screenshot_base64()
            if b64:
                return "Screenshot captured. I can see the screen now.", b64
            return "✗ Failed to capture screenshot", None

        elif name == "mouse_click":
            x, y = int(args["x"]), int(args["y"])
            btn = args.get("button", "left")
            user32.SetCursorPos(x, y)
            time.sleep(0.05)
            if btn == "double":
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.05)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
            elif btn == "right":
                user32.mouse_event(0x0008, 0, 0, 0, 0)
                user32.mouse_event(0x0010, 0, 0, 0, 0)
            else:
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
            return f"✓ Clicked {btn} at ({x}, {y})", None

        elif name == "mouse_move":
            user32.SetCursorPos(int(args["x"]), int(args["y"]))
            return f"✓ Cursor moved to ({args['x']}, {args['y']})", None

        elif name == "keyboard_type":
            # Use PowerShell SendKeys for reliable text input
            text = args["text"].replace("'", "''")
            _ps(f"Add-Type -AssemblyName System.Windows.Forms;"
                f"[System.Windows.Forms.SendKeys]::SendWait('{text}')")
            return f"✓ Typed: {args['text'][:50]}{'...' if len(args['text'])>50 else ''}", None

        elif name == "keyboard_hotkey":
            keys = [k.strip().lower() for k in args["keys"].split('+')]
            vks = []
            for k in keys:
                vk = VK_MAP.get(k)
                if vk is None: return f"✗ Unknown key: {k}", None
                vks.append(vk)
            for vk in vks: _key_press(vk, True)
            time.sleep(0.05)
            for vk in reversed(vks): _key_press(vk, False)
            return f"✓ Pressed: {args['keys']}", None

        elif name == "clipboard_get":
            user32.OpenClipboard(0)
            try:
                h = user32.GetClipboardData(13)  # CF_UNICODETEXT
                if h:
                    ctypes.windll.kernel32.GlobalLock.restype = ctypes.c_wchar_p
                    text = ctypes.windll.kernel32.GlobalLock(h)
                    ctypes.windll.kernel32.GlobalUnlock(h)
                    return text or "(empty clipboard)", None
                return "(empty clipboard)", None
            finally:
                user32.CloseClipboard()

        elif name == "clipboard_set":
            _ps(f"Set-Clipboard -Value '{args['text'].replace(chr(39), chr(39)+chr(39))}'")
            return f"✓ Clipboard set ({len(args['text'])} chars)", None

        elif name == "download_file":
            urllib_req = __import__('urllib.request', fromlist=['urlretrieve'])
            urllib_req.urlretrieve(args["url"], args["save_path"])
            return f"✓ Downloaded to: {args['save_path']}", None

        elif name == "get_active_window":
            title = ctypes.create_unicode_buffer(256)
            hwnd = user32.GetForegroundWindow()
            user32.GetWindowTextW(hwnd, title, 256)
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return (f"Window: {title.value}\n"
                    f"Position: ({rect.left},{rect.top}) Size: {rect.right-rect.left}x{rect.bottom-rect.top}"), None

        elif name == "wait":
            time.sleep(float(args["seconds"]))
            return f"✓ Waited {args['seconds']}s", None

        elif name == "create_directory":
            dp = Path(args["dir_path"])
            dp.mkdir(parents=True, exist_ok=True)
            return f"✓ Directory created: {dp}", None

        elif name == "web_search":
            import urllib.request, urllib.parse
            query = args.get("query") or args.get("search") or ""
            if not query: return "✗ No query provided", None
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            try:
                resp = urllib.request.urlopen(req, timeout=15)
                html = resp.read().decode('utf-8', errors='replace')
                # Extract result snippets
                results = []
                for m in re.finditer(r'class="result__snippet">(.*?)</a>', html, re.DOTALL):
                    text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if text and len(text) > 20:
                        results.append(text)
                    if len(results) >= 5: break
                if not results:
                    # Fallback: extract any text between tags
                    for m in re.finditer(r'class="result__a"[^>]*>(.*?)</a>', html):
                        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                        if text: results.append(text)
                        if len(results) >= 5: break
                return "\n".join(f"{i+1}. {r}" for i,r in enumerate(results)) or "No results found", None
            except Exception as e:
                return f"✗ Search failed: {e}", None

        else:
            return f"✗ Unknown tool: {name}. Available: create_file, read_file, run_command, python_exec, web_search, create_directory, etc.", None

    except Exception as e:
        return f"✗ {type(e).__name__}: {e}", None
