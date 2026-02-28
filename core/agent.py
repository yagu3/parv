"""Agent — smart routing, session memory, self-tool-creation, clean answers."""
import re, json, msvcrt, time, os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
TOOL_NAMES = []

# System prompt — chat + tools + self-creation
SYSTEM = """You are YAGU, a helpful AI assistant on Windows. You can chat AND use tools.

Today: {date}
User: {user} | Desktop: {desktop}

RULES:
1. For simple questions, greetings, opinions → just ANSWER directly. No tools needed.
2. For tasks requiring action (files, web, commands) → use the tool format below.
3. After a tool RESULT → give a clear ANSWER with the actual info. Don't call more tools unless needed.
4. You can CREATE new custom tools! Save a .py file to tools/custom/ with this format:
   NAME = "tool_name"
   DESC = "what it does"
   PARAMS = {{"param": ("string", "description", True)}}
   def execute(args): return "result", None

TOOL FORMAT (only when action is needed):
THINK: brief reason
TOOL: tool_name
INPUT: {{"param": "value"}}

ANSWER FORMAT:
ANSWER: your response here

Tools: {tools}
{session}"""


def _check_pause():
    while msvcrt.kbhit():
        if msvcrt.getch() == b'\x1b':
            print(f"\n    ⏸  PAUSED — ESC to resume", flush=True)
            while True:
                if msvcrt.kbhit() and msvcrt.getch() == b'\x1b':
                    print(f"    ▶  RESUMED\n", flush=True); return
                time.sleep(0.1)


class Agent:
    def __init__(self, llm, hw, tool_schemas, memory=None):
        self.llm = llm
        self.memory = memory
        self.history = []
        self.tool_schemas = tool_schemas
        self.session_facts = self._load_facts()

        global TOOL_NAMES
        TOOL_NAMES = [t['function']['name'] for t in tool_schemas]

        self.hw = hw
        self._rebuild_system()

    def _facts_file(self):
        return ROOT / "memory" / "store" / "session_facts.json"

    def _load_facts(self):
        f = self._facts_file()
        try:
            if f.exists(): return json.loads(f.read_text('utf-8'))
        except: pass
        return []

    def _save_facts(self):
        f = self._facts_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(self.session_facts[-20:], indent=2), 'utf-8')

    def _rebuild_system(self):
        """Rebuild system prompt with latest session facts."""
        tools_str = ", ".join(TOOL_NAMES)
        session = ""
        if self.session_facts:
            session = "\nRemember: " + " | ".join(self.session_facts[-5:])
        self.system = SYSTEM.format(
            date=datetime.now().strftime("%Y-%m-%d %A"),
            user=self.hw.user, desktop=self.hw.desktop,
            tools=tools_str, session=session
        )

    def _needs_tools(self, msg):
        """Quick check if message likely needs tool use."""
        low = msg.lower()
        action_words = ['create', 'make', 'write', 'delete', 'remove', 'open',
                       'search', 'find', 'download', 'run', 'execute', 'list',
                       'read file', 'click', 'type', 'screenshot', 'move',
                       'copy', 'rename', 'install', 'save', 'update file',
                       'show me', 'take screenshot', 'press', 'web']
        return any(w in low for w in action_words)

    def _parse_tool(self, text):
        """Extract tool + args."""
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '').replace('`', '')

        tool = None
        for pat in [r'TOOL:\s*(\w+)', r'Tool:\s*(\w+)', r'Action:\s*(\w+)',
                    r'tool:\s*(\w+)']:
            m = re.search(pat, clean)
            if m:
                name = m.group(1).strip()
                if name in TOOL_NAMES:
                    tool = name; break
                for tn in TOOL_NAMES:
                    if name.lower() in tn or tn in name.lower():
                        tool = tn; break
                if tool: break
        if not tool:
            return None, None

        args = {}
        for pat in [r'INPUT:?\s*(\{.*?\})', r'Input:?\s*(\{.*?\})',
                    r'Action Input:?\s*(\{.*?\})', r'(\{"[^"]+"\s*:.*?\})']:
            m = re.search(pat, clean, re.DOTALL)
            if m:
                raw = m.group(1)
                for attempt in [raw, raw.replace("'", '"')]:
                    try: args = json.loads(attempt); break
                    except: pass
                if args: break

        if not args and tool:
            schema = next((t for t in self.tool_schemas
                          if t['function']['name'] == tool), None)
            if schema:
                for pname in schema['function']['parameters'].get('properties', {}):
                    m = re.search(
                        rf'["\']?{pname}["\']?\s*[:=]\s*["\']([^"\'\n]+)["\']',
                        clean)
                    if m: args[pname] = m.group(1)

        return tool, args

    def _clean_response(self, text):
        """Strip all THINK/TOOL/INPUT markup, return clean text."""
        m = re.search(r'ANSWER:\s*(.*)', text, re.DOTALL|re.I)
        if m: return m.group(1).strip()
        clean = text
        clean = re.sub(r'THINK:.*?(?=TOOL:|ANSWER:|$)', '', clean, flags=re.DOTALL|re.I)
        clean = re.sub(r'TOOL:.*', '', clean, flags=re.I)
        clean = re.sub(r'INPUT:.*', '', clean, flags=re.DOTALL|re.I)
        clean = re.sub(r'STOP\s*$', '', clean, flags=re.I)
        clean = re.sub(r'^#{1,4}\s*', '', clean, flags=re.MULTILINE)
        clean = clean.replace('**', '').strip()
        return clean if len(clean) > 5 else text.strip()

    def _learn_from_message(self, msg):
        """Extract facts to remember during session."""
        low = msg.lower()
        m = re.search(r'(?:call (?:you|yourself)|your name is|name you)\s+(\w+)', low)
        if m:
            name = m.group(1).upper()
            fact = f"User calls me {name}"
            if fact not in self.session_facts:
                self.session_facts.append(fact)
                self._save_facts()
                self._rebuild_system()
        if 'don\'t' in low or 'dont' in low:
            if 'file' in low:
                fact = "Don't create files unless asked"
                if fact not in self.session_facts:
                    self.session_facts.append(fact)
                    self._save_facts()
                    self._rebuild_system()

    def _trim_history(self):
        """Keep last 4 messages, truncate long ones."""
        if len(self.history) > 4:
            self.history = self.history[-4:]
        # Ensure first message is 'user' role
        while self.history and self.history[0]['role'] == 'assistant':
            self.history.pop(0)
        for msg in self.history:
            c = msg.get('content', '')
            if len(c) > 400:
                msg['content'] = c[:400] + '...'

    def send(self, user_msg, execute_fn, print_fn=None):
        """Smart agent loop."""
        from core.ui import dim, warn, err, S

        self._learn_from_message(user_msg)
        self.history.append({"role": "user", "content": user_msg})
        self._trim_history()

        last_resp = ""
        for round_n in range(4):
            _check_pause()

            msgs = [{"role": "system", "content": self.system}] + list(self.history)

            try:
                resp = self.llm.call(msgs, max_tokens=400)
                last_resp = resp
            except Exception as e:
                if "400" in str(e) or "500" in str(e):
                    warn("Server hiccup — retrying")
                    self.history = [{"role": "user", "content": user_msg}]
                    try:
                        msgs = [{"role": "system", "content": self.system}] + self.history
                        resp = self.llm.call(msgs, max_tokens=400)
                        last_resp = resp
                    except:
                        err("Server down"); return "Sorry, server trouble. Try /new."
                else:
                    err(f"Error: {e}"); return None

            # Try tool
            tool, args = self._parse_tool(resp)

            if tool:
                m = re.search(r'THINK:?\s*(.*?)(?:TOOL:|Tool:)', resp, re.DOTALL|re.I)
                if m and m.group(1).strip():
                    dim(f"💭 {m.group(1).strip()[:100]}")

                preview = ""
                for k in ["file_path","command","query","code","target","text","dir_path"]:
                    if k in args: preview = str(args[k])[:55]; break
                print(f"  {S.MAG}⚡ {tool}{S.R}  {S.D}{preview}{S.R}")

                _check_pause()
                result, _ = execute_fn(tool, args)
                rline = result.split('\n')[0][:80]
                if "✓" in rline: dim(f"{S.GRN}{rline}{S.R}")
                elif "✗" in rline: dim(f"{S.RED}{rline}{S.R}")
                else: dim(rline)

                if self.memory and "✗" in result:
                    self.memory.log_error(tool, result, user_msg)

                short_result = result[:200] + '...' if len(result) > 200 else result
                self.history.append({"role": "assistant", "content":
                    f"Used {tool}. Result: {short_result}"})
                self.history.append({"role": "user", "content":
                    f"Tool result: {short_result}\nNow give ANSWER:"})
                self._trim_history()
                continue

            # No tool → answer
            clean = self._clean_response(resp)
            if clean:
                self.history.append({"role": "assistant", "content": clean[:300]})
                return clean

        if last_resp:
            return self._clean_response(last_resp)
        return "Couldn't complete that. Try /new."

    def clear(self):
        self.history = []

    def save(self):
        self._save_facts()
