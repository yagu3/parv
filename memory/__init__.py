"""Smart priority-based memory with topic summaries, forget, and priority decay."""
import os, json, math
from pathlib import Path
from datetime import datetime

STORE = Path(__file__).parent / "store"
STORE.mkdir(parents=True, exist_ok=True)

def _load(name, default=None):
    f = STORE / f"{name}.json"
    try:
        if f.exists():
            data = json.loads(f.read_text('utf-8'))
            # Guard: always return correct type
            if default is not None and type(data) != type(default):
                return default
            return data
    except: pass
    return default if default is not None else {}

def _save(name, data):
    (STORE / f"{name}.json").write_text(json.dumps(data, indent=2, default=str), 'utf-8')


class Memory:
    """Priority-based memory with topic summarization and decay."""

    def __init__(self, hw=None):
        self.user = _load("user", {"name":"","desktop":"","notes":[]})
        self.errors = _load("errors", {"log":[],"patterns":{}})
        self.history = _load("history", {"sessions":[]})
        self.facts = _load("facts", [])  # [{fact, priority, created, accessed, access_count}]
        if hw:
            self.user["name"] = hw.user
            self.user["desktop"] = hw.desktop
            _save("user", self.user)

    # ═══ SESSION TRACKING ═══
    def log_message(self, role, content):
        if not hasattr(self, '_session'):
            self._session = []
        self._session.append({
            "role": role, "text": str(content)[:200],
            "time": datetime.now().isoformat()
        })

    def log_error(self, tool, error, request=""):
        if not isinstance(self.errors, dict):
            self.errors = {"log":[], "patterns":{}}
        key = f"{tool}:{str(error)[:40]}"
        self.errors["patterns"][key] = self.errors["patterns"].get(key, 0) + 1
        self.errors["log"].append({
            "tool": tool, "error": str(error)[:100],
            "time": datetime.now().isoformat()
        })
        if len(self.errors["log"]) > 50:
            self.errors["log"] = self.errors["log"][-50:]
        _save("errors", self.errors)

    # ═══ PRIORITY FACTS ═══
    def learn(self, fact_text, priority=5):
        """Add or boost a fact. Higher priority = more important."""
        now = datetime.now().isoformat()
        # Check if similar fact exists
        for f in self.facts:
            if f["fact"].lower() == fact_text.lower():
                f["priority"] = min(10, f["priority"] + 1)
                f["accessed"] = now
                f["access_count"] = f.get("access_count", 0) + 1
                _save("facts", self.facts)
                return
        self.facts.append({
            "fact": fact_text, "priority": priority,
            "created": now, "accessed": now, "access_count": 1
        })
        if len(self.facts) > 50:
            # Decay: sort by priority * access_count, drop lowest
            self.facts.sort(key=lambda x: x["priority"] * x.get("access_count",1), reverse=True)
            self.facts = self.facts[:50]
        _save("facts", self.facts)

    def forget(self, keyword):
        """Remove facts matching keyword. Returns count removed."""
        low = keyword.lower()
        before = len(self.facts)
        self.facts = [f for f in self.facts if low not in f["fact"].lower()]
        removed = before - len(self.facts)
        if removed > 0: _save("facts", self.facts)
        return removed

    def top_facts(self, n=5):
        """Get top N facts by priority, sorted."""
        scored = []
        for f in self.facts:
            score = f["priority"] * math.log2(f.get("access_count", 1) + 1)
            scored.append((score, f))
        scored.sort(reverse=True)
        return [f for _, f in scored[:n]]

    # ═══ SESSION SAVE ═══
    def save_session(self):
        msgs = getattr(self, '_session', [])
        if not msgs: return
        sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_msgs = [m["text"][:50] for m in msgs if m["role"]=="user"]
        summary = " | ".join(user_msgs[:3]) if user_msgs else "session"
        if not isinstance(self.history, dict):
            self.history = {"sessions": []}
        self.history["sessions"].append({
            "id": sid, "summary": summary,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "msgs": len(msgs)
        })
        if len(self.history["sessions"]) > 30:
            self.history["sessions"] = self.history["sessions"][-30:]
        _save("history", self.history)
        _save(f"session_{sid}", msgs)

    # ═══ HISTORY VIEW ═══
    def show_history(self):
        """Return formatted history of past sessions."""
        if not isinstance(self.history, dict):
            return "  No history yet."
        sessions = self.history.get("sessions", [])
        if not sessions:
            return "  No history yet."
        lines = ["  📜 Past Conversations:\n"]
        for i, s in enumerate(reversed(sessions[-10:])):
            lines.append(f"  [{i+1}] {s['date']} ({s['msgs']} msgs)")
            lines.append(f"      {s['summary'][:60]}")
        return "\n".join(lines)

    def show_memory(self):
        """Return formatted view of all stored knowledge."""
        parts = ["  🧠 Memory Contents:\n"]
        # Facts by priority
        if self.facts:
            parts.append("  Facts (by priority):")
            for f in sorted(self.facts, key=lambda x: x["priority"], reverse=True):
                bar = "█" * f["priority"] + "░" * (10 - f["priority"])
                parts.append(f"    [{bar}] {f['fact']}")
        else:
            parts.append("  No facts stored yet.")
        # Error patterns
        if isinstance(self.errors, dict) and self.errors.get("patterns"):
            parts.append("\n  Error patterns:")
            for k, v in sorted(self.errors["patterns"].items(), key=lambda x:x[1], reverse=True)[:3]:
                parts.append(f"    ⚠ {k} ({v}x)")
        return "\n".join(parts)

    # ═══ CONTEXT FOR PROMPT ═══
    def context(self, budget_tokens=100):
        """Build memory string that fits in token budget (~4 chars/token)."""
        budget = budget_tokens * 4
        parts = []
        used = 0

        # P1: User identity (always)
        if self.user.get("name"):
            p = f"User: {self.user['name']}, Desktop: {self.user['desktop']}"
            parts.append(p); used += len(p)

        # P2: Top facts by priority
        top = self.top_facts(3)
        if top and used < budget:
            facts_str = "Remember: " + " | ".join(f["fact"] for f in top)
            if used + len(facts_str) < budget:
                parts.append(facts_str); used += len(facts_str)

        # P3: Error lessons (if fits)
        if isinstance(self.errors, dict):
            top_errors = sorted(self.errors.get("patterns",{}).items(),
                               key=lambda x:x[1], reverse=True)[:2]
            if top_errors and used < budget:
                lessons = "Avoid: " + "; ".join(f"{k} ({v}x)" for k,v in top_errors)
                if used + len(lessons) < budget:
                    parts.append(lessons); used += len(lessons)

        # P4: Recent history (if fits)
        if isinstance(self.history, dict):
            recent = self.history.get("sessions",[])[-2:]
            if recent and used < budget:
                hist = "Recent: " + " → ".join(s["summary"][:30] for s in recent)
                if used + len(hist) < budget:
                    parts.append(hist)

        return "\n".join(parts) if parts else ""
