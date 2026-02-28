"""LLM client — calls llama.cpp server with role validation."""
import json, urllib.request, urllib.error

class LLM:
    def __init__(self, model_id, host="127.0.0.1", port=8080):
        self.model = model_id
        self.url = f"http://{host}:{port}/v1/chat/completions"
        self.headers = {"Content-Type": "application/json"}

    def _fix_roles(self, messages):
        """Ensure strict user/assistant alternation. Gemma/Mistral require this."""
        fixed = []
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                fixed.append(msg)
                continue
            # Merge consecutive same-role messages
            if fixed and fixed[-1]['role'] == role:
                fixed[-1]['content'] += "\n" + content
            else:
                fixed.append({"role": role, "content": content})
        # Must end with user if we want the model to reply
        if fixed and fixed[-1]['role'] == 'assistant':
            fixed.append({"role": "user", "content": "Continue."})
        # Must have at least one user message after system
        non_system = [m for m in fixed if m['role'] != 'system']
        if not non_system or non_system[0]['role'] != 'user':
            fixed.append({"role": "user", "content": "Hello."})
        return fixed

    def call(self, messages, max_tokens=400, temperature=0.4, stop=None):
        """Call LLM with role-validated messages."""
        msgs = self._fix_roles(messages)

        if stop is None:
            stop = ["RESULT:", "Observation:", "\nUser:", "\nYou:"]

        payload = json.dumps({
            "model": self.model, "messages": msgs,
            "temperature": temperature, "max_tokens": max_tokens,
            "stop": stop
        }).encode('utf-8')

        req = urllib.request.Request(self.url, data=payload,
                                     headers=self.headers, method='POST')
        resp = urllib.request.urlopen(req, timeout=300)
        text = json.loads(resp.read().decode('utf-8')
            )['choices'][0]['message']['content'].strip()
        return text

    def health(self):
        try:
            return urllib.request.urlopen(
                f"http://127.0.0.1:8080/health", timeout=5).status == 200
        except: return False
