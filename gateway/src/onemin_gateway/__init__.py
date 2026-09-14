"""1min.ai Agent Gateway.

A stateless OpenAI-compatible translation layer that emulates native tool
calling on top of 1min.ai (which has no native tool-calling support), so that
OpenCode (and other OpenAI-compatible coding agents) can use 1min.ai as a
model backend while keeping full control over tool execution, including MCP
tools.
"""

__version__ = "0.1.0"
