"""
YaguAI Memory System — Persistent file-based memory.
Stores user profile, system facts, conversation logs, errors, and instructions.
"""
import os, json, time, hashlib
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.resolve()
MEM_DIR = ROOT / "memory"
CONV_DIR = MEM_DIR / "conversations"

def _ensure_dirs():
    MEM_DIR.mkdir(exist_ok=True)
    CONV_DIR.mkdir(exist_ok=True)

def _load_json(path, default=None):
    if default is None: default = {}
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return default

def _save_json(path, data):
    _ensure_dirs()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

# ═══════════════════════════════════════
# USER PROFILE — permanent details
# ═══════════════════════════════════════
class UserProfile:
    PATH = MEM_DIR / "user_profile.json"

    def __init__(self):
        self.data = _load_json(self.PATH, {
            "name": "", "username": "", "desktop": "",
            "preferences": {}, "known_paths": {},
            "notes": []
        })

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.save()

    def add_note(self, note):
        notes = self.data.setdefault("notes", [])
        if note not in notes:
            notes.append(note)
            if len(notes) > 50: notes.pop(0)  # Keep last 50
            self.save()

    def save(self):
        _save_json(self.PATH, self.data)

    def summary(self):
        d = self.data
        parts = []
        if d.get("name"): parts.append(f"Name: {d['name']}")
        if d.get("username"): parts.append(f"User: {d['username']}")
        if d.get("desktop"): parts.append(f"Desktop: {d['desktop']}")
        if d.get("preferences"):
            parts.append(f"Prefs: {json.dumps(d['preferences'])}")
        if d.get("notes"):
            parts.append(f"Notes: {'; '.join(d['notes'][-5:])}")
        return " | ".join(parts) if parts else "(no profile yet)"

# ═══════════════════════════════════════
# SYSTEM FACTS — learned facts about PC
# ═══════════════════════════════════════
class SystemFacts:
    PATH = MEM_DIR / "system_facts.json"

    def __init__(self):
        self.data = _load_json(self.PATH, {"facts": [], "software": {}, "paths": {}})

    def add_fact(self, fact):
        facts = self.data.setdefault("facts", [])
        if fact not in facts:
            facts.append(fact)
            if len(facts) > 100: facts.pop(0)
            self.save()

    def add_software(self, name, path=""):
        self.data.setdefault("software", {})[name] = path
        self.save()

    def add_path(self, label, path):
        self.data.setdefault("paths", {})[label] = path
        self.save()

    def save(self):
        _save_json(self.PATH, self.data)

    def summary(self):
        d = self.data
        parts = []
        if d.get("facts"):
            parts.append("Facts: " + "; ".join(d["facts"][-5:]))
        if d.get("software"):
            parts.append("Software: " + ", ".join(d["software"].keys()))
        if d.get("paths"):
            parts.append("Paths: " + json.dumps(d["paths"]))
        return " | ".join(parts) if parts else "(no facts yet)"

# ═══════════════════════════════════════
# ERROR LOG — for self-improvement
# ═══════════════════════════════════════
class ErrorLog:
    PATH = MEM_DIR / "errors.json"

    def __init__(self):
        self.data = _load_json(self.PATH, {"errors": [], "patterns": {}})

    def log_error(self, tool_name, error_msg, user_request=""):
        entry = {
            "time": datetime.now().isoformat(),
            "tool": tool_name,
            "error": str(error_msg)[:200],
            "request": user_request[:100]
        }
        self.data.setdefault("errors", []).append(entry)
        # Track patterns
        key = f"{tool_name}:{str(error_msg)[:50]}"
        patterns = self.data.setdefault("patterns", {})
        patterns[key] = patterns.get(key, 0) + 1
        # Keep last 200 errors
        if len(self.data["errors"]) > 200:
            self.data["errors"] = self.data["errors"][-200:]
        self.save()

    def get_lessons(self):
        """Return common error patterns as lessons."""
        patterns = self.data.get("patterns", {})
        if not patterns: return ""
        # Sort by frequency
        sorted_p = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]
        lessons = []
        for pattern, count in sorted_p:
            lessons.append(f"- {pattern} (happened {count}x)")
        return "Common errors to avoid:\n" + "\n".join(lessons)

    def save(self):
        _save_json(self.PATH, self.data)

# ═══════════════════════════════════════
# CONVERSATION MEMORY — logs + summaries
# ═══════════════════════════════════════
class ConversationMemory:
    SUMMARY_PATH = MEM_DIR / "conversation_summaries.json"

    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.messages = []
        self.summaries = _load_json(self.SUMMARY_PATH, {"sessions": []})

    def add_message(self, role, content):
        self.messages.append({
            "role": role,
            "content": content[:500] if isinstance(content, str) else str(content)[:500],
            "time": datetime.now().isoformat()
        })

    def save_session(self, summary=""):
        """Save current session to disk."""
        _ensure_dirs()
        # Save full log
        session_file = CONV_DIR / f"{self.session_id}.json"
        _save_json(session_file, {
            "id": self.session_id,
            "messages": self.messages,
            "summary": summary,
            "started": self.messages[0]["time"] if self.messages else "",
            "ended": datetime.now().isoformat()
        })
        # Update summaries
        sessions = self.summaries.setdefault("sessions", [])
        sessions.append({
            "id": self.session_id,
            "summary": summary or self._auto_summary(),
            "messages": len(self.messages),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        # Keep last 50 sessions
        if len(sessions) > 50:
            self.summaries["sessions"] = sessions[-50:]
        _save_json(self.SUMMARY_PATH, self.summaries)

    def _auto_summary(self):
        """Generate a simple summary from user messages."""
        user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
        if not user_msgs: return "Empty session"
        topics = user_msgs[:3]  # First 3 user messages
        return "User asked: " + " | ".join(t[:60] for t in topics)

    def get_recent_summaries(self, n=3):
        """Get recent session summaries."""
        sessions = self.summaries.get("sessions", [])
        if not sessions: return ""
        recent = sessions[-n:]
        lines = ["Recent conversations:"]
        for s in recent:
            lines.append(f"- [{s.get('date','')}] {s.get('summary','')}")
        return "\n".join(lines)

# ═══════════════════════════════════════
# INSTRUCTIONS — self-maintained
# ═══════════════════════════════════════
class Instructions:
    PATH = MEM_DIR / "instructions.md"

    def __init__(self):
        if not self.PATH.exists():
            _ensure_dirs()
            self.PATH.write_text(
                "# YaguAI Self-Maintained Instructions\n\n"
                "## What I've Learned\n- (nothing yet)\n\n"
                "## Common Mistakes to Avoid\n- (nothing yet)\n\n"
                "## User Preferences\n- (nothing yet)\n",
                encoding='utf-8'
            )

    def read(self):
        return self.PATH.read_text(encoding='utf-8') if self.PATH.exists() else ""

    def append(self, section, item):
        """Append an item to a section."""
        content = self.read()
        marker = f"## {section}"
        if marker in content:
            idx = content.index(marker)
            end = content.find("\n## ", idx + len(marker))
            if end == -1: end = len(content)
            section_content = content[idx:end]
            if item not in section_content:
                content = content[:end] + f"- {item}\n" + content[end:]
                self.PATH.write_text(content, encoding='utf-8')

# ═══════════════════════════════════════
# MEMORY MANAGER — unified interface
# ═══════════════════════════════════════
class MemoryManager:
    def __init__(self, hw_info=None):
        _ensure_dirs()
        self.user = UserProfile()
        self.facts = SystemFacts()
        self.errors = ErrorLog()
        self.conversation = ConversationMemory()
        self.instructions = Instructions()

        # Auto-populate user profile from system info
        if hw_info:
            self.user.update(
                username=hw_info.user,
                desktop=hw_info.desktop
            )

    def build_context(self):
        """Build memory context string for system prompt injection."""
        parts = []
        up = self.user.summary()
        if up and up != "(no profile yet)": parts.append(f"USER: {up}")
        sf = self.facts.summary()
        if sf and sf != "(no facts yet)": parts.append(f"SYSTEM: {sf}")
        lessons = self.errors.get_lessons()
        if lessons: parts.append(lessons)
        recent = self.conversation.get_recent_summaries()
        if recent: parts.append(recent)
        instr = self.instructions.read()
        if instr and "nothing yet" not in instr:
            # Only include if there's real content
            parts.append(f"INSTRUCTIONS:\n{instr[:500]}")
        return "\n\n".join(parts) if parts else ""

    def log_message(self, role, content):
        self.conversation.add_message(role, content)

    def log_error(self, tool, error, request=""):
        self.errors.log_error(tool, error, request)

    def learn_fact(self, fact):
        self.facts.add_fact(fact)

    def learn_about_user(self, note):
        self.user.add_note(note)

    def save_session(self, summary=""):
        self.conversation.save_session(summary)
        self.user.save()
        self.facts.save()
        self.errors.save()
