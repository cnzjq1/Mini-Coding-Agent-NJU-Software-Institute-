"""Top-level configuration. Secrets are read from environment variables only."""

import os

API_KEY = os.getenv("OPENAI_API_KEY", " ")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")

MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "80"))
MAX_HISTORY_CHARS = int(os.getenv("AGENT_MAX_HISTORY_CHARS", "120000"))
CONTEXT_KEEP_RECENT_CHARS = int(os.getenv("AGENT_CONTEXT_KEEP_RECENT_CHARS", "40000"))
COMMAND_TIMEOUT = int(os.getenv("AGENT_COMMAND_TIMEOUT", "120"))
MAX_TOOL_OUTPUT_CHARS = int(os.getenv("AGENT_MAX_TOOL_OUTPUT_CHARS", "30000"))
API_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "4"))
API_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "180"))
REQUIREMENT_MAX_CHARS = int(os.getenv("AGENT_REQUIREMENT_MAX_CHARS", "300000"))
TERMINAL_VISUALS = os.getenv("AGENT_TERMINAL_VISUALS", "1") != "0"
