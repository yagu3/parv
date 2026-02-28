"""Priority-based memory manager. Stores in memory/store/."""
import os, json
from pathlib import Path
from datetime import datetime

STORE = Path(__file__).parent / "store"
STORE.mkdir(parents=True, exist_ok=True)

def _load(name, default=None):
    f = STORE / f"{name}.json"
    try:
        if f.exists(): return json.loads(f.read_text('utf-8'))
    except: pass
    return default if default is not None else {}

def _save(name, data):
    (STORE / f"{name}.json").write_text(json.dumps(data, indent=2, default=str), 'utf-8')

class Memory:
    """Priority memory — only loads what fits in token budget."""

    def __init__(self, hw=None):
        self.user = _load("user", {"name":"","desktop":"","notes":[]})
        self.errors = _load("errors", {"log":[],"patterns":{}})
        self.history = _load("history", {"sessions":[]})
        if hw:
            self.user["name"] = hw.user
            self.user["desktop"] = hw.desktop
            _save("user", self.user)

    def log_message(self, role, content):
        """Track current session messages."""
        if not hasattr(self, '_session'):
            self._session = []
        self._session.append({
            "role": role, "text": str(content)[:200],
            "time": datetime.now().isoformat()
        })

    def log_error(self, tool, error, request=""):
        key = f"{tool}:{str(error)[:40]}"
        self.errors["patterns"][key] = self.errors["patterns"].get(key, 0) + 1
        self.errors["log"].append({
            "tool": tool, "error": str(error)[:100],
            "time": datetime.now().isoformat()
        })
        if len(self.errors["log"]) > 100:
            self.errors["log"] = self.errors["log"][-100:]
        _save("errors", self.errors)

    def save_session(self):
        msgs = getattr(self, '_session', [])
        if not msgs: return
        sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Auto-summary from first user message
        user_msgs = [m["text"][:50] for m in msgs if m["role"]=="user"]
        summary = " | ".join(user_msgs[:3]) if user_msgs else "session"
        self.history["sessions"].append({
            "id": sid, "summary": summary,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "msgs": len(msgs)
        })
        if len(self.history["sessions"]) > 30:
            self.history["sessions"] = self.history["sessions"][-30:]
        _save("history", self.history)
        _save(f"session_{sid}", msgs)

    def context(self, budget_tokens=100):
        """Build memory string that fits in token budget (~4 chars/token)."""
        budget = budget_tokens * 4  # ~4 chars per token
        parts = []
        used = 0

        # P1: User identity (always)
        if self.user.get("name"):
            p = f"User: {self.user['name']}, Desktop: {self.user['desktop']}"
            parts.append(p); used += len(p)

        # P2: Error lessons (if fits)
        top_errors = sorted(self.errors.get("patterns",{}).items(),
                           key=lambda x:x[1], reverse=True)[:3]
        if top_errors and used < budget:
            lessons = "Avoid: " + "; ".join(f"{k} ({v}x)" for k,v in top_errors)
            if used + len(lessons) < budget:
                parts.append(lessons); used += len(lessons)

        # P3: Recent history (if fits)
        recent = self.history.get("sessions",[])[-2:]
        if recent and used < budget:
            hist = "Recent: " + " → ".join(s["summary"] for s in recent)
            if used + len(hist) < budget:
                parts.append(hist)

        return "\n".join(parts) if parts else ""
