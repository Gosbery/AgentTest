"""
Central configuration for the Agent.

Loads .env, initializes the OpenAI-compatible client,
and exports WORKDIR, LLM_CLIENT, MODEL_ID.
"""

import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd()
LLM_CLIENT = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
MODEL_ID = os.environ.get("OPENAI_MODEL", "qwen-plus")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL_ID")

# Error Recovery constants (s11)
ESCALATED_MAX_TOKENS = 64000
DEFAULT_MAX_TOKENS = 8000
MAX_RECOVERY_RETRIES = 3  # max continuation attempts after escalation
MAX_RETRIES = 10  # max retry attempts for transient errors
BASE_DELAY_MS = 500  # base delay for exponential backoff
MAX_CONSECUTIVE_529 = 3  # switch to fallback model after N consecutive 529s
CONTINUATION_PROMPT = (
    "Output token limit hit. Resume directly — "
    "no apology, no recap. Pick up mid-thought."
)

# Safety deny list for bash commands
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
