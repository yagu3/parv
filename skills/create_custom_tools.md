# How to Create Custom Tools
When the user asks me to create a new tool, I save a Python file to `tools/custom/` with this format:

```python
NAME = "tool_name"
DESC = "What the tool does"
PARAMS = {"param_name": ("string", "description", True)}

def execute(args):
    # Tool logic here
    result = args.get("param_name", "")
    return f"Result: {result}", None
```

The tool is auto-loaded on next startup. I can use create_file to save it.
