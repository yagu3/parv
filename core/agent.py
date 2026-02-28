"""Agent — single smart agent with robust parsing, focused context, date injection."""
import re, json, msvcrt, time
from datetime import datetime

TOOL_NAMES = []  # Set by main.py after loading tools

# Ultra-compact system prompt with few-shot example + date
SYSTEM = """You are an AI agent on Windows. Act by calling tools. NEVER just explain — DO it.

Today: {date}
User desktop: {desktop}
Workspace: {workspace}

Tools: {tools}

Format:
THINK: what I need to do
TOOL: tool_name
INPUT: {{"param": "value"}}

Then STOP. System gives RESULT. Continue or finish with a detailed ANSWER.

Example:
User: create hello.txt on Desktop
THINK: create file with content
TOOL: create_file
INPUT: {{"file_path": "{desktop}\\\\hello.txt", "content": "Hello World!"}}

IMPORTANT:
- ALWAYS use tools. NEVER just describe what you would do.
- Give DETAILED answers, not just "done". Say WHAT you did and WHAT the result was.
- For web_search, read the RESULT carefully and include actual info in your ANSWER."""


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

        # Set global tool names for parser
        global TOOL_NAMES
        TOOL_NAMES = [t['function']['name'] for t in tool_schemas]

        # Compact tool list
        tools_str = ", ".join(TOOL_NAMES)

        self.system = SYSTEM.format(
            date=datetime.now().strftime("%Y-%m-%d %A"),
            desktop=hw.desktop, workspace=hw.desktop.rsplit('\\',1)[0],
            tools=tools_str
        )

    def _parse_tool(self, text):
        """Extract tool + args — extremely robust."""
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '').replace('`', '')

        # Find tool name
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

        # Find args — JSON
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

        # Fallback: extract from tool schema
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

    def _parse_answer(self, text):
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '')
        for pat in [r'ANSWER:\s*(.*)', r'Answer:\s*(.*)',
                    r'Final Answer:\s*(.*)']:
            m = re.search(pat, clean, re.DOTALL)
            if m: return m.group(1).strip()
        return None

    def _trim_history(self):
        """Keep only last 4 messages to stay in context budget."""
        if len(self.history) > 4:
            self.history = self.history[-4:]

    def send(self, user_msg, execute_fn, print_fn=None):
        """Run agent loop. execute_fn(tool, args) -> (result, img)."""
        from core.ui import dim, warn, err, S

        self.history.append({"role": "user", "content": user_msg})
        self._trim_history()

        msgs = [{"role": "system", "content": self.system}] + self.history
        use_prefill = True

        for round_n in range(6):
            _check_pause()
            try:
                pf = "THINK:" if use_prefill else ""
                resp = self.llm.call(msgs, max_tokens=512, prefill=pf)
            except Exception as e:
                if "400" in str(e) or "500" in str(e):
                    warn("Context full, trimming...")
                    self.history = self.history[-2:]
                    msgs = [{"role": "system", "content": self.system}] + self.history
                    try: resp = self.llm.call(msgs, max_tokens=512, prefill="THINK:")
                    except Exception as e2:
                        err(f"Failed: {e2}"); return None
                else:
                    err(f"Error: {e}"); return None

            use_prefill = False

            # Try tool
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

                msgs.append({"role": "assistant", "content": resp})
                msgs.append({"role": "user", "content":
                    f"RESULT: {result}\nCall another TOOL or give a detailed ANSWER about what you did and found."})
                self.history.append({"role": "assistant", "content": resp})
                self.history.append({"role": "user", "content": f"RESULT: {result}"})
                continue

            # Try answer
            answer = self._parse_answer(resp)
            if answer:
                self.history.append({"role": "assistant", "content": resp})
                return answer

            # No tool, no answer → re-prompt once
            if round_n == 0:
                dim("💭 (redirecting to tools...)")
                msgs.append({"role": "assistant", "content": resp})
                msgs.append({"role": "user", "content":
                    "Use a TOOL now. Format: TOOL: name then INPUT: {...}"})
                use_prefill = True
                continue

            # Give up, return whatever model said
            self.history.append({"role": "assistant", "content": resp})
            return resp

        return None

    def clear(self):
        self.history = []
