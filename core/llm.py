"""LLM client — calls llama.cpp server with context budget management."""
import json, urllib.request, urllib.error

class LLM:
    def __init__(self, model_id, host="127.0.0.1", port=8080):
        self.model = model_id
        self.url = f"http://{host}:{port}/v1/chat/completions"
        self.headers = {"Content-Type": "application/json"}

    def call(self, messages, max_tokens=512, temperature=0.4,
             stop=None, prefill=""):
        """Call LLM. If prefill is set, forces assistant to start with it."""
        msgs = list(messages)
        if prefill:
            msgs.append({"role": "assistant", "content": prefill})

        if stop is None:
            stop = ["RESULT:", "Result:", "Observation:",
                    "\nUser:", "\nYou:", "\nuser:"]

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
        return (prefill + text) if prefill else text

    def health(self):
        try:
            return urllib.request.urlopen(
                f"http://127.0.0.1:8080/health", timeout=5).status == 200
        except: return False
