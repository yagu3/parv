"""
YaguAI Multi-Agent System — Coordinator + Worker Agents
Team Leader decomposes tasks, workers execute with specialized tools.
"""
import json, re, time
from pathlib import Path
import urllib.request
from tools import TOOL_SCHEMAS, execute_tool, ROOT

# ═══════════════════════════════════════
# TOOL SUBSETS FOR WORKERS
# ═══════════════════════════════════════
TOOL_GROUPS = {
    "researcher": ["web_search", "read_file", "run_command", "python_exec"],
    "coder": ["create_file", "read_file", "run_command", "python_exec",
              "find_files", "list_directory", "create_directory"],
    "file_manager": ["create_file", "read_file", "delete_file", "move_file",
                     "find_files", "list_directory", "create_directory",
                     "download_file"],
    "pc_control": ["take_screenshot", "mouse_click", "mouse_move",
                   "keyboard_type", "keyboard_hotkey", "open_application",
                   "get_active_window", "clipboard_get", "clipboard_set"],
}

def _get_tool_list(group):
    """Get formatted tool list for a worker group."""
    names = TOOL_GROUPS.get(group, [])
    tools = [t for t in TOOL_SCHEMAS if t['function']['name'] in names]
    lines = []
    for t in tools:
        fn = t['function']
        params = fn['parameters'].get('properties', {})
        param_desc = ", ".join(f"{k}: {v['description']}" for k,v in params.items())
        lines.append(f"  - {fn['name']}({param_desc}): {fn['description']}")
    return "\n".join(lines)

# ═══════════════════════════════════════
# WORKER AGENT — executes specific tasks
# ═══════════════════════════════════════
WORKER_PROMPT = """You are a {role} worker agent. You handle ONE specific subtask.

TOOLS:
{tools}

FORMAT (plain text, no markdown):
Thought: what I need to do
Action: tool_name
Action Input: {{"key": "value"}}

Then STOP. Wait for Observation. When done:
Thought: completed
Final Answer: result summary

RULES:
- One Action per turn, then STOP
- NEVER fake Observations
- Desktop: {desktop}
- Workspace: {workspace}
"""

class WorkerAgent:
    def __init__(self, role, llm_url, model_id, hw):
        self.role = role
        self.url = llm_url
        self.model = model_id
        self.system = WORKER_PROMPT.format(
            role=role, tools=_get_tool_list(role),
            desktop=hw.desktop, workspace=ROOT
        )
        self.headers = {"Content-Type": "application/json"}

    def _call_llm(self, messages):
        payload = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": 0.5, "max_tokens": 1024,
            "stop": ["Observation:", "# Observation", "## Observation",
                     "**Observation", "\nObservation\n"]
        }).encode('utf-8')
        req = urllib.request.Request(self.url, data=payload,
                                     headers=self.headers, method='POST')
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode('utf-8'))['choices'][0]['message']['content'].strip()

    def _parse(self, text):
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
        clean = clean.replace('**', '')
        action_m = re.search(r'Action:?\s*\n?\s*(\w+)', clean)
        input_m = re.search(r'Action Input:?\s*\n?\s*(\{[^}]*\})', clean, re.DOTALL)
        if action_m:
            try: args = json.loads(input_m.group(1)) if input_m else {}
            except: args = {}
            return action_m.group(1).strip(), args
        return None, None

    def execute(self, task, print_fn=None):
        """Execute a subtask. Returns result string."""
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": task}
        ]
        for _ in range(5):  # Max 5 tool rounds per worker
            try:
                response = self._call_llm(messages)
            except Exception as e:
                return f"Worker error: {e}"

            # Check final answer
            clean = re.sub(r'^#{1,4}\s*', '', response, flags=re.MULTILINE).replace('**','')
            final_m = re.search(r'Final Answer:?\s*\n?\s*(.*)', clean, re.DOTALL)
            if final_m:
                return final_m.group(1).strip()

            action, args = self._parse(response)
            if action:
                # Check tool is allowed for this worker
                allowed = TOOL_GROUPS.get(self.role, [])
                if action not in allowed:
                    obs = f"Tool '{action}' not available for {self.role}. Use: {', '.join(allowed)}"
                else:
                    if print_fn:
                        preview = ""
                        for k in ["file_path","command","query","code","target","text"]:
                            if k in args:
                                preview = str(args[k])[:50]; break
                        print_fn(f"  👷 {self.role} → {action}  {preview}")
                    result, _ = execute_tool(action, args)
                    obs = result
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"Observation: {obs}\n\nContinue or give Final Answer."})
            else:
                return response  # Direct response
        return "Worker reached max rounds"

# ═══════════════════════════════════════
# COORDINATOR — breaks tasks + dispatches
# ═══════════════════════════════════════
COORDINATOR_PROMPT = """You are the Team Leader of YaguAI agent system on Windows 11.
Your job: break complex tasks into subtasks and delegate to workers.

AVAILABLE WORKERS:
- researcher: web search, research, information gathering
- coder: write/edit code, run commands, Python execution
- file_manager: create/read/delete/move files, download, organize
- pc_control: screenshots, mouse, keyboard, clipboard, open apps

For SIMPLE tasks (single file, one command), handle directly:
Thought: This is simple, I'll handle it directly.
Action: [tool_name]
Action Input: {{"key": "value"}}

For COMPLEX tasks (multiple steps), delegate to workers:
Thought: This needs multiple steps.
Delegate: worker_name
Task: description of what this worker should do

After receiving worker results, continue delegating or finish:
Thought: All done.
Final Answer: summary of what was accomplished.

DIRECT TOOLS (for simple tasks):
{tools}

RULES:
- NEVER fake Observations or worker results
- STOP after each Action/Delegate and WAIT
- Desktop: {desktop}
- Workspace: {workspace}

{memory_context}
{sysinfo}
"""

class Coordinator:
    def __init__(self, model_id, hw, memory_mgr=None):
        from tools import TOOL_SCHEMAS as all_tools
        self.model = model_id
        self.url = f"http://127.0.0.1:8080/v1/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        self.memory = memory_mgr
        self.history = []
        self.hw = hw

        # Build tool list for direct use
        tool_lines = []
        for t in all_tools:
            fn = t['function']
            params = fn['parameters'].get('properties', {})
            pdesc = ", ".join(f"{k}" for k in params.keys())
            tool_lines.append(f"  - {fn['name']}({pdesc}): {fn['description']}")

        mem_ctx = memory_mgr.build_context() if memory_mgr else ""
        self.system = COORDINATOR_PROMPT.format(
            tools="\n".join(tool_lines),
            desktop=hw.desktop, workspace=ROOT,
            memory_context=f"MEMORY:\n{mem_ctx}" if mem_ctx else "",
            sysinfo=hw.summary()
        )

        # Create workers
        self.workers = {
            name: WorkerAgent(name, self.url, model_id, hw)
            for name in TOOL_GROUPS
        }

    def _call_llm(self, messages):
        payload = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": 0.6, "max_tokens": 1536,
            "stop": ["Observation:", "# Observation", "## Observation",
                     "**Observation", "\nObservation\n", "Worker Result:"]
        }).encode('utf-8')
        req = urllib.request.Request(self.url, data=payload,
                                     headers=self.headers, method='POST')
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read().decode('utf-8'))['choices'][0]['message']['content'].strip()

    def _parse(self, text):
        """Parse coordinator output — returns (type, data)."""
        clean = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE).replace('**','')

        # Check Final Answer
        final_m = re.search(r'Final Answer:?\s*\n?\s*(.*)', clean, re.DOTALL)
        if final_m:
            return "final", final_m.group(1).strip()

        # Check Delegate
        delegate_m = re.search(r'Delegate:?\s*\n?\s*(\w+)', clean)
        task_m = re.search(r'Task:?\s*\n?\s*(.*?)(?:\n\n|\Z)', clean, re.DOTALL)
        if delegate_m and task_m:
            return "delegate", (delegate_m.group(1).strip(), task_m.group(1).strip())

        # Check direct Action
        action_m = re.search(r'Action:?\s*\n?\s*(\w+)', clean)
        input_m = re.search(r'Action Input:?\s*\n?\s*(\{[^}]*\})', clean, re.DOTALL)
        if action_m:
            try: args = json.loads(input_m.group(1)) if input_m else {}
            except: args = {}
            return "action", (action_m.group(1).strip(), args)

        return "text", clean

    def send(self, user_message, print_fn=None):
        """Full multi-agent loop."""
        self.history.append({"role": "user", "content": user_message})
        if self.memory:
            self.memory.log_message("user", user_message)

        messages = [{"role": "system", "content": self.system}] + self.history

        for round_num in range(12):  # Max 12 rounds
            try:
                response = self._call_llm(messages)
            except Exception as e:
                if self.memory:
                    self.memory.log_error("coordinator", str(e), user_message)
                return f"Error: {e}"

            ptype, pdata = self._parse(response)

            if ptype == "final":
                self.history.append({"role": "assistant", "content": response})
                if self.memory:
                    self.memory.log_message("assistant", pdata)
                return pdata

            elif ptype == "delegate":
                worker_name, task = pdata
                # Show thought
                thought = re.search(r'Thought:?\s*(.*?)(?:Delegate:)', response, re.DOTALL|re.I)
                if thought and print_fn:
                    print_fn(f"    💭 {thought.group(1).strip()[:80]}")
                if print_fn:
                    print_fn(f"  🔀 Delegating to {worker_name}: {task[:60]}...")

                worker = self.workers.get(worker_name)
                if worker:
                    result = worker.execute(task, print_fn=print_fn)
                else:
                    result = f"No worker named '{worker_name}'. Use: researcher, coder, file_manager, pc_control"

                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"Worker Result ({worker_name}): {result}\n\nContinue delegating or give Final Answer."})
                self.history.append({"role": "assistant", "content": response})
                self.history.append({"role": "user", "content": f"Worker Result ({worker_name}): {result}"})

            elif ptype == "action":
                action, args = pdata
                # Direct tool execution
                thought = re.search(r'Thought:?\s*(.*?)(?:Action:)', response, re.DOTALL|re.I)
                if thought and print_fn:
                    print_fn(f"    💭 {thought.group(1).strip()[:80]}")

                preview = ""
                for k in ["file_path","command","query","code","target","text","dir_path"]:
                    if k in args: preview = str(args[k])[:50]; break
                if print_fn:
                    print_fn(f"  ⚡ {action}  {preview}")

                result, _ = execute_tool(action, args)
                if print_fn:
                    print_fn(f"    {result.split(chr(10))[0][:80]}")

                if self.memory and "✗" in result:
                    self.memory.log_error(action, result, user_message)

                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"Observation: {result}\n\nContinue or give Final Answer."})
                self.history.append({"role": "assistant", "content": response})
                self.history.append({"role": "user", "content": f"Observation: {result}"})

            else:
                # Plain text response
                self.history.append({"role": "assistant", "content": response})
                if self.memory:
                    self.memory.log_message("assistant", response)
                return response

        return "Coordinator reached max rounds."

    def clear(self):
        self.history = []
