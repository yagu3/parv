"""
Custom Tool Template — Drop .py files here, auto-loaded on startup.

Required:
  NAME = "my_tool"           # Tool name (no spaces)
  DESC = "What it does"       # Short description
  PARAMS = {                  # Parameters
      "param1": ("string", "description", True),  # (type, desc, required)
  }
  def execute(args):
      return "result text", None   # (text, image_b64_or_None)
"""
NAME = "_template"
DESC = "Template — rename this file to create a new tool"
PARAMS = {"example": ("string", "Example input", True)}

def execute(args):
    return f"Template called with: {args}", None
