"""Agent — smart routing (chat vs tools), session memory, clean answers."""
import re, json, msvcrt, time
from datetime import datetime

TOOL_NAMES = []

# System prompt — allows BOTH chat and tool use
SYSTEM = """You are YAGU, a helpful AI assistant on Windows. You can chat AND use tools.

Today: {date}
User: {user} | Desktop: {desktop}

RULES:
1. For simple questions (greetings, opinions, facts you know) → just ANSWER directly
2. For tasks requiring action (create files, search web, run commands) → use tools
3. After getting a tool RESULT → give a clear ANSWER with the actual info

TOOL FORMAT (only when needed):
THINK: brief reason
TOOL: tool_name
INPUT: {{"param": "value"}}

ANSWER FORMAT (for final response):
ANSWER: your detailed response here

Available tools: {tools}
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
        self.session_facts = []  # Learned during this session

        global TOOL_NAMES
        TOOL_NAMES = [t['function']['name'] for t in tool_schemas]

        self.hw = hw
        self._rebuild_system()

    def _rebuild_system(self):
        """Rebuild system prompt with latest session facts."""
        tools_str = ", ".join(TOOL_NAMES)
        session = ""
        if self.session_facts:
            session = "\nSession notes: " + " | ".join(self.session_facts[-5:])
        self.system = SYSTEM.format(
            date=datetime.now().strftime("%Y-%m-%d %A"),
            user=self.hw.user, desktop=self.hw.desktop,
            tools=tools_str, session=session
        )

    def _needs_tools(self, msg):
        """Quick check if message likely needs tool use."""
        low = msg.lower()
        # Action words that need tools
        action_words = ['create', 'make', 'write', 'delete', 'remove', 'open',
                       'search', 'find', 'download', 'run', 'execute', 'list',
                       'read file', 'click', 'type', 'screenshot', 'move',
                       'copy', 'rename', 'install', 'save', 'update file']
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

        # Fallback: schema extraction
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
        # Try ANSWER: pattern first
        m = re.search(r'ANSWER:\s*(.*)', text, re.DOTALL|re.I)
        if m: return m.group(1).strip()
        # Strip markup
        clean = text
        clean = re.sub(r'THINK:.*?(?=TOOL:|ANSWER:|$)', '', clean, flags=re.DOTALL|re.I)
        clean = re.sub(r'TOOL:.*', '', clean, flags=re.I)
        clean = re.sub(r'INPUT:.*', '', clean, flags=re.DOTALL|re.I)
        clean = re.sub(r'STOP\s*$', '', clean, flags=re.I)
        clean = re.sub(r'^#{1,4}\s*', '', clean, flags=re.MULTILINE)
        clean = clean.replace('**', '').strip()
        return clean if clean else text.strip()

    def _learn_from_message(self, msg):
        """Extract facts to remember during session."""
        low = msg.lower()
        # Name assignments
        m = re.search(r'(?:call (?:you|yourself)|your name is|name you)\s+(\w+)', low)
        if m:
            name = m.group(1).upper()
            self.session_facts.append(f"User calls me {name}")
            self._rebuild_system()
        # User preferences
        if 'don\'t' in low or 'dont' in low:
            if 'file' in low:
                self.session_facts.append("Don't create files unless asked")
                self._rebuild_system()

    def _trim_history(self):
        """Keep last 4 messages, truncate long ones."""
        if len(self.history) > 4:
            self.history = self.history[-4:]
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

        needs_tools = self._needs_tools(user_msg)

        for round_n in range(4):
            _check_pause()

            msgs = [{"role": "system", "content": self.system}] + list(self.history)

            try:
                resp = self.llm.call(msgs, max_tokens=400)
            except Exception as e:
                if "400" in str(e) or "500" in str(e):
                    warn("Server error — resetting")
                    self.history = [{"role": "user", "content": user_msg}]
                    try:
                        msgs = [{"role": "system", "content": self.system}] + self.history
                        resp = self.llm.call(msgs, max_tokens=400)
                    except:
                        err("Server down"); return "Sorry, the server is having trouble. Try /new."
                else:
                    err(f"Error: {e}"); return None

            # Try tool extraction
            tool, args = self._parse_tool(resp)

            if tool:
                # Show thinking
                m = re.search(r'THINK:?\s*(.*?)(?:TOOL:|Tool:)', resp, re.DOTALL|re.I)
                if m and m.group(1).strip():
                    dim(f"💭 {m.group(1).strip()[:100]}")

                # Show tool call
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

                # Add to history as proper user/assistant pair
                short_result = result[:200] + '...' if len(result) > 200 else result
                self.history.append({"role": "assistant", "content":
                    f"Used {tool}. Result: {short_result}"})
                self.history.append({"role": "user", "content":
                    f"Tool result: {short_result}\nNow give a clear ANSWER to the original question."})
                self._trim_history()
                continue

            # No tool → this is the answer
            clean = self._clean_response(resp)
            if clean:
                self.history.append({"role": "assistant", "content": clean[:300]})
                return clean

        # Exhausted rounds
        return self._clean_response(resp) if resp else "I couldn't complete that. Try /new."

    def clear(self):
        self.history = []
        # Keep session facts
