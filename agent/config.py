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

# Safety deny list for bash commands
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
