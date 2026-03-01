"""Agent — self-aware YAGU with auto-tool-creation, skills, RAG, persistent memory."""
import re, json, msvcrt, time, os
from datetime import datetime
from pathlib import Path
from core import rag

ROOT = Path(__file__).parent.parent.resolve()
TOOL_NAMES = []

# ═══ SELF-AWARE SYSTEM PROMPT ═══
SYSTEM = """You are YAGU — a self-improving AI assistant running locally on Windows.
You were created by Yagnesh. You run on llama.cpp with a local GGUF model.

Today: {date}
User: {user} | Desktop: {desktop}

YOUR CAPABILITIES:
1. CHAT — answer questions, tell jokes, have conversations.
2. TOOLS — you have {tool_count} built-in tools: {tools}
3. CUSTOM TOOLS — you can CREATE new tools! To do this, output perfectly formatted Python code.
4. SKILLS — you can learn & store procedures in: {root}/skills/
5. MEMORY — you remember facts across sessions.
{skills_summary}
CRITICAL RULES:
1. NEVER hallucinate real-time data (prices, news, weather). You MUST use the `web_search` tool!
2. If the user asks for actions (files, web, commands), ALWAYS use the TOOL FORMAT.
3. To CREATE a custom tool, you must reply with the exact Python code block format shown below.
4. If the user CORRECTS you, accept the correction immediately. Do NOT repeat your wrong answer.
5. Use KNOWLEDGE section below if provided — it contains verified information.

HOW TO USE A TOOL (Example):
THINK: I need to find the current grape price in Surat.
TOOL: web_search
INPUT: {{"query": "grape price Surat today"}}

HOW TO CREATE A CUSTOM TOOL (Example):
THINK: The user wants a tool to get news. I will write the code.
ANSWER:
NAME = "get_news"
DESC = "Fetches latest news"
PARAMS = {{"topic": ("string", "News topic", True)}}
def execute(args):
    return "news results", None

ANSWER FORMAT (For normal chatting):
ANSWER: your response here
{rag_context}
{memory}"""


def _check_pause():
    while msvcrt.kbhit():
        if msvcrt.getch() == b'\x1b':
            print(f"\n    ⏸  PAUSED — ESC to resume", flush=True)
            while True:
                if msvcrt.kbhit() and msvcrt.getch() == b'\x1b':
                    print(f"    ▶  RESUMED\n", flush=True); return
                time.sleep(0.1)


def _load_skills_summary():
    """Load short summaries of all skills."""
    skills_dir = ROOT / "skills"
    if not skills_dir.exists(): return ""
    skills = []
    for f in skills_dir.glob("*.md"):
        if f.name.startswith("_"): continue
        first_line = f.read_text('utf-8', errors='replace').split('\n')[0][:60]
        skills.append(f"  • {f.stem}: {first_line}")
    if skills:
        return "\nYOUR SKILLS:\n" + "\n".join(skills[:5]) + "\n"
    return ""


class Agent:
    def __init__(self, llm, hw, tool_schemas, memory=None):
        self.llm = llm
        self.memory = memory
        self.history = []
        self.tool_schemas = tool_schemas

        global TOOL_NAMES
        TOOL_NAMES = [t['function']['name'] for t in tool_schemas]

        self.hw = hw
        self._rebuild_system()

    def _rebuild_system(self, user_msg=""):
        """Rebuild system prompt with skills, memory, facts, RAG."""
        tools_str = ", ".join(TOOL_NAMES)
        skills = _load_skills_summary()
        # Get top facts from unified memory
        mem = ""
        if self.memory:
            top = self.memory.top_facts(5)
            if top:
                facts = [f["fact"] for f in top]
                mem = "\nREMEMBER: " + " | ".join(facts)
        # RAG: search knowledge/ for relevant context
        rag_ctx = ""
        if user_msg:
            rag_ctx = rag.context_for(user_msg, max_chars=400)
        self.system = SYSTEM.format(
            date=datetime.now().strftime("%Y-%m-%d %A"),
            user=self.hw.user, desktop=self.hw.desktop,
            root=str(ROOT).replace('\\', '/'),
            tools=tools_str, tool_count=len(TOOL_NAMES),
            skills_summary=skills, rag_context=rag_ctx, memory=mem
        )

    # ═══ SMART ROUTING ═══
    def _needs_tools(self, msg):
        low = msg.lower()
        action_words = ['create', 'make', 'write', 'delete', 'remove', 'open',
                       'search', 'find', 'download', 'run', 'execute', 'list',
                       'read file', 'click', 'type', 'screenshot', 'move',
                       'copy', 'rename', 'install', 'save', 'update file',
                       'show me', 'take screenshot', 'press', 'web']
        return any(w in low for w in action_words)

    # ═══ PARSING ═══
    def _parse_tool(self, text):
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

    # ═══ SELF-LEARNING ═══
    def _learn_from_message(self, msg):
        if not self.memory: return
        low = msg.lower()
        m = re.search(r'(?:call (?:you|yourself)|your name is|name you)\s+(\w+)', low)
        if m:
            self.memory.learn(f"User calls me {m.group(1).upper()}", priority=9)
        if ('don\'t' in low or 'dont' in low) and 'file' in low:
            self.memory.learn("Don't create files unless user explicitly asks", priority=8)

    def _auto_save_tool(self, resp, user_msg):
        """Only auto-save tool code when user explicitly asked to create a tool."""
        low = user_msg.lower()
        asked_for_tool = any(w in low for w in ['create tool', 'make tool', 'build tool',
                                                 'create a tool', 'make a tool', 'custom tool',
                                                 'new tool', 'write tool', 'write a tool'])
        if not asked_for_tool:
            return None

        name_m = re.search(r'NAME\s*=\s*["\'](\w+)["\']', resp)
        desc_m = re.search(r'DESC\s*=\s*["\'](.+?)["\']', resp)
        exec_m = re.search(r'def execute\(', resp)

        if name_m and desc_m and exec_m:
            tool_name = name_m.group(1)
            code_m = re.search(r'(NAME\s*=.*?def execute\(.*?\n(?:.*\n)*?.*?return\s+.+)', resp, re.DOTALL)
            if code_m:
                code = code_m.group(1).strip()
                custom_dir = ROOT / "tools" / "custom"
                custom_dir.mkdir(parents=True, exist_ok=True)
                tool_file = custom_dir / f"{tool_name}.py"
                tool_file.write_text(code, encoding='utf-8')
                if self.memory:
                    self.memory.learn(f"Created custom tool: {tool_name}", priority=6)
                return tool_name
        return None

    # ═══ HISTORY ═══
    def _trim_history(self):
        if len(self.history) > 4:
            self.history = self.history[-4:]
        while self.history and self.history[0]['role'] == 'assistant':
            self.history.pop(0)
        for msg in self.history:
            c = msg.get('content', '')
            if len(c) > 400:
                msg['content'] = c[:400] + '...'

    # ═══ MAIN LOOP ═══
    def send(self, user_msg, execute_fn, print_fn=None):
        from core.ui import dim, warn, err, S

        self._learn_from_message(user_msg)
        self._rebuild_system(user_msg)  # Rebuild with RAG context for this message
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

            # Auto-save if model generated tool code AND user asked for it
            saved_tool = self._auto_save_tool(resp, user_msg)
            if saved_tool:
                dim(f"💾 Auto-saved custom tool: {saved_tool}")

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
                # Save to memory for /history
                if self.memory:
                    self.memory.log_message("user", user_msg)
                    self.memory.log_message("assistant", clean[:200])
                return clean

        if last_resp:
            return self._clean_response(last_resp)
        return "Couldn't complete that. Try /new."

    def clear(self):
        self.history = []

    def save(self):
        pass  # Facts saved via memory.learn() automatically
